from __future__ import annotations

from copy import deepcopy
from typing import Any

from .standardizers.compression import derive_compression_parameters, solid_height_mode


COLD_COILED_STANDARD = "GB/T 1239.2-2009"


def assess_parameter_reasonableness(review: dict[str, Any]) -> dict[str, Any]:
    """Assess the recognized compression-spring data itself, not only a proposed edit."""
    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "")
    if spring_type != "compression_spring":
        return _assessment("not_applicable", "当前仅对圆柱螺旋压缩弹簧执行参数合理性诊断。")

    parameters = review.get("spring_parameters") or {}
    issues = _compression_issues(parameters, review, include_missing_context=True)
    derived = derive_compression_parameters(parameters)
    status = _assessment_status(issues)
    return {
        "status": status,
        "summary": _assessment_summary(status, issues),
        "issues": issues,
        "derived_preview": _derived_preview(derived),
        "scope": "cylindrical_helical_compression_spring",
    }


def assess_parameter_change_set(review: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulate chat parameter patches and report only newly introduced issues."""
    applicable = [
        action
        for action in actions
        if isinstance(action, dict)
        and action.get("type") == "propose_parameter_patch"
        and action.get("target_field")
        and action.get("proposed_value") not in (None, "")
    ]
    if not applicable:
        return _change_result("not_applicable", "本次建议不改变弹簧主参数，无需进行参数预检。")

    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "")
    if spring_type != "compression_spring":
        return _change_result("not_applicable", "当前仅对压缩弹簧执行参数可行性预检。")

    baseline_parameters = deepcopy(review.get("spring_parameters") or {})
    baseline_issues = _compression_issues(baseline_parameters, review, include_missing_context=False)
    parameters = deepcopy(baseline_parameters)
    changed_fields: list[str] = []
    for action in applicable:
        target = str(action["target_field"])
        if _apply_parameter_patch(parameters, target, action.get("proposed_value")):
            changed_fields.append(target)

    if not changed_fields:
        return _change_result("not_applicable", "当前建议没有可模拟的参数字段。")

    candidate_issues = _compression_issues(parameters, review, include_missing_context=False)
    baseline_keys = {_issue_key(issue) for issue in baseline_issues}
    issues = [issue for issue in candidate_issues if _issue_key(issue) not in baseline_keys]
    existing_issues = [issue for issue in candidate_issues if _issue_key(issue) in baseline_keys]
    derived = derive_compression_parameters(parameters)
    status = _assessment_status(issues, default="ready")
    return {
        "status": status,
        "summary": _change_summary(status, issues),
        "issues": issues,
        "existing_issues": existing_issues,
        "changed_fields": list(dict.fromkeys(changed_fields)),
        "derived_preview": _derived_preview(derived),
    }


def _apply_parameter_patch(parameters: dict[str, Any], target: str, value: Any) -> bool:
    load_target = _load_target(target)
    if load_target:
        label, field = load_target
        for point in parameters.get("load_points") or []:
            if str(point.get("label") or "").upper() == label.upper():
                point[field] = value
                return True
        return False

    current = parameters.get(target)
    if isinstance(current, dict):
        current["value"] = value
    else:
        parameters[target] = {"value": value}
    return True


def _compression_issues(
    parameters: dict[str, Any],
    review: dict[str, Any],
    *,
    include_missing_context: bool,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    wire = _number(_value(parameters, "wire_diameter"))
    outer = _number(_value(parameters, "outer_diameter"))
    inner = _number(_value(parameters, "inner_diameter"))
    mean = _number(_value(parameters, "mean_diameter"))
    free_length = _number(_value(parameters, "free_length"))
    total = _number(_value(parameters, "total_coils"))
    active = _number(_value(parameters, "active_coils"))

    positive_rules = (
        ("wire_diameter", wire, "线径必须大于 0 mm。"),
        ("outer_diameter", outer, "外径必须大于 0 mm。"),
        ("inner_diameter", inner, "内径必须大于 0 mm。"),
        ("mean_diameter", mean, "中径必须大于 0 mm。"),
        ("free_length", free_length, "自由长度必须大于 0 mm。"),
        ("total_coils", total, "总圈数必须大于 0。"),
        ("active_coils", active, "有效圈数必须大于 0。"),
    )
    for field, value, message in positive_rules:
        if value is not None and value <= 0:
            _issue(
                issues,
                "blocked",
                "geometry",
                f"SPRING-GEO-{field.upper()}",
                [field],
                message,
                calculation=f"{_label(field)}={value:g}",
                basis="压缩弹簧基础几何关系。",
                explanation="该尺寸或圈数不能为零或负数，否则弹簧几何模型不成立。",
                customer_question=f"请客户确认图纸中的{_label(field)}是否填写正确。",
            )

    if outer is not None and wire is not None and outer - 2 * wire <= 0:
        _issue(
            issues,
            "blocked",
            "geometry",
            "SPRING-GEO-OUTER-INNER",
            ["outer_diameter", "wire_diameter"],
            "外径必须大于两倍线径，否则推导内径小于等于 0。",
            calculation=f"内径=外径-2×线径={outer:g}-2×{wire:g}={outer - 2 * wire:g} mm",
            basis="圆丝圆柱螺旋弹簧几何关系：Di=Do-2d。",
            explanation="当前外径无法容纳两侧线径，弹簧截面几何上不成立。",
            customer_question="请客户确认外径或线径是否识别错误，或图纸是否为非圆丝/非圆柱弹簧。",
        )

    derived_mean = _derived_mean_diameter(outer, inner, mean, wire)
    if outer is not None and inner is not None and wire is not None:
        expected_inner = outer - 2 * wire
        if abs(inner - expected_inner) > max(0.02, wire * 0.02):
            _issue(
                issues,
                "warning",
                "geometry",
                "SPRING-GEO-DIAMETER-CONSISTENCY",
                ["outer_diameter", "inner_diameter", "wire_diameter"],
                f"按外径和线径推导内径应约为 {expected_inner:g} mm，与当前内径不一致。",
                calculation=f"Di=Do-2d={outer:g}-2×{wire:g}={expected_inner:g} mm；当前 Di={inner:g} mm",
                basis="圆丝圆柱螺旋弹簧几何关系：Di=Do-2d。",
                explanation="三个直径数据通常应能相互推导；不一致时可能是识别归属错误，或图纸采用了不同受控直径。",
                customer_question="请客户确认外径、内径和线径是否均为同一弹簧本体尺寸。",
            )

    if total is not None and active is not None and active > total:
        _issue(
            issues,
            "blocked",
            "geometry",
            "SPRING-GEO-COIL-COUNT",
            ["active_coils", "total_coils"],
            "有效圈数不能大于总圈数。",
            calculation=f"有效圈数={active:g} 圈；总圈数={total:g} 圈",
            basis="有效圈数属于总圈数的一部分。",
            explanation="当前圈数关系不成立，无法据此计算刚度或载荷。",
            customer_question="请客户确认总圈数和有效圈数，或补充端部形式。",
        )

    selected_standard = _normalized_standard((review.get("standard_selection") or {}).get("selected_standard"))
    spring_index = derived_mean / wire if derived_mean is not None and wire not in (None, 0) else None
    if _is_cold_standard(selected_standard) and spring_index is not None and not 3 <= spring_index <= 22:
        _issue(
            issues,
            "warning",
            "standard_scope",
            "GBT1239.2-SCOPE-SPRING-INDEX",
            ["outer_diameter", "inner_diameter", "mean_diameter", "wire_diameter"],
            f"旋绕比 C={spring_index:g} 超出 GB/T 1239.2-2009 当前规则表的 3~22 范围。",
            calculation=f"C=D/d={derived_mean:g}/{wire:g}={spring_index:g}",
            basis="GB/T 1239.2-2009 表 3-11、表 3-12 当前规则包的旋绕比适用范围为 3~22。",
            explanation="这不是直接判定不可制造，而是当前冷卷公差规则不能直接套用，需要工程复核。",
            customer_question="请客户确认是否仍按 GB/T 1239.2-2009 交付，或提供适用的特殊技术要求。",
        )

    if _is_cold_standard(selected_standard) and total is not None and total > 50:
        _issue(
            issues,
            "warning",
            "standard_scope",
            "GBT1239.2-SCOPE-TOTAL-COILS",
            ["total_coils"],
            "总圈数超出当前 GB/T 1239.2-2009 总圈数公差规则表的最大范围。",
            calculation=f"总圈数 n1={total:g} 圈；当前规则表最大档为 50 圈",
            basis="GB/T 1239.2-2009 表 3-13 当前规则包覆盖至 50 圈。",
            explanation="系统可以保留图纸数值，但不能自动给出该项公差建议。",
            customer_question="请客户确认总圈数是否正确，并补充适用的公差或特殊要求。",
        )

    slenderness = free_length / derived_mean if free_length is not None and derived_mean not in (None, 0) else None
    if _is_cold_standard(selected_standard) and slenderness is not None and slenderness >= 5:
        _issue(
            issues,
            "warning",
            "design_risk",
            "GBT1239.2-SLENDERNESS",
            ["free_length", "outer_diameter", "inner_diameter", "mean_diameter"],
            f"细长比 b={slenderness:g} 大于等于 5，建议重点核查垂直度和直线度。",
            calculation=f"b=H0/D={free_length:g}/{derived_mean:g}={slenderness:g}",
            basis="GB/T 1239.2-2009 表 3-14 注：细长比 b≥5 时建议考核直线度。",
            explanation="弹簧较细长，装配或受压时更需要关注偏斜和端面控制。",
            customer_question="请客户确认是否有垂直度、直线度或导向装配要求。",
        )

    reference_solid = _reference_solid_height(parameters, wire, total)
    explicit_solid = _number(_value(parameters, "solid_height"))
    minimum_free_length = explicit_solid if explicit_solid is not None else reference_solid
    end_mode = solid_height_mode(_value(parameters, "end_grinding"))
    load_points = [point for point in parameters.get("load_points") or [] if isinstance(point, dict)]
    if include_missing_context and load_points and explicit_solid is None and end_mode is None and wire is not None and total is not None:
        _issue(
            issues,
            "needs_input",
            "missing_context",
            "SPRING-CONTEXT-END-CONDITION",
            ["end_grinding", "solid_height"],
            "缺少端部形式或压并高度，无法完整判断载荷点是否进入压并状态。",
            calculation="压并高度需根据端部形式和最大线径计算。",
            basis="压簧压并高度公式依赖端部形式。",
            explanation="没有端部形式时，系统不会猜测“两端磨平”或“两端不磨”。",
            customer_question="请客户补充端部是否磨平，或直接提供压并高度要求。",
        )

    if free_length is not None and minimum_free_length is not None and free_length <= minimum_free_length:
        source = "图纸压并高度" if explicit_solid is not None else "按当前端部形式推导的压并高度"
        _issue(
            issues,
            "blocked",
            "load_condition",
            "SPRING-LOAD-FREE-OVER-SOLID",
            ["free_length", "solid_height", "total_coils", "wire_diameter", "end_grinding"],
            f"自由长度必须大于{source} {minimum_free_length:g} mm。",
            calculation=f"H0={free_length:g} mm；压并高度参考值={minimum_free_length:g} mm",
            basis="压簧自由长度必须大于压并高度，才存在有效压缩行程。",
            explanation="当前弹簧在自由状态下已接近或小于压死状态，无法正常工作。",
            customer_question="请客户确认自由长度、总圈数、线径和端部形式，或提供明确压并高度。",
        )

    _append_load_point_issues(issues, load_points, free_length, minimum_free_length)
    _append_load_relation_issues(issues, load_points)
    return issues


def _append_load_point_issues(
    issues: list[dict[str, Any]],
    load_points: list[dict[str, Any]],
    free_length: float | None,
    minimum_free_length: float | None,
) -> None:
    for index, point in enumerate(load_points, start=1):
        label = str(point.get("label") or f"F{index}")
        height = _number(point.get("height"))
        force = _number(point.get("force"))
        height_field = f"load_points.{label}.height"
        force_field = f"load_points.{label}.force"
        if height is not None and height <= 0:
            _issue(
                issues, "blocked", "load_condition", "SPRING-LOAD-HEIGHT-POSITIVE", [height_field],
                f"{label} 的试验高度必须大于 0 mm。", calculation=f"{label} 高度={height:g} mm",
                basis="压簧试验高度必须为正值。", explanation="零或负高度没有可执行的压簧测试含义。",
                customer_question=f"请客户确认 {label} 的试验高度。",
            )
        if force is not None and force < 0:
            _issue(
                issues, "blocked", "load_condition", "SPRING-LOAD-FORCE-POSITIVE", [force_field],
                f"{label} 的载荷不能为负值。", calculation=f"{label} 力值={force:g} N",
                basis="压缩载荷不能为负值。", explanation="负载荷与当前压簧受压测试定义矛盾。",
                customer_question=f"请客户确认 {label} 的力值和载荷方向。",
            )
        if height is not None and free_length is not None and height > free_length:
            _issue(
                issues, "blocked", "load_condition", "SPRING-LOAD-HEIGHT-OVER-FREE", ["free_length", height_field],
                f"{label} 的试验高度不能大于自由长度，否则弹簧没有有效压缩量。",
                calculation=f"{label} 高度={height:g} mm；自由长度 H0={free_length:g} mm",
                basis="压簧受压后的试验高度应不大于自由长度。", explanation="试验高度更大时，弹簧不是被压缩状态。",
                customer_question=f"请客户确认 {label} 高度是否应为压缩后的高度。",
            )
        if height is not None and minimum_free_length is not None and height < minimum_free_length:
            _issue(
                issues, "blocked", "load_condition", "SPRING-LOAD-HEIGHT-UNDER-SOLID", ["solid_height", height_field],
                f"{label} 的试验高度不能小于压并高度参考值 {minimum_free_length:g} mm。",
                calculation=f"{label} 高度={height:g} mm；压并高度参考值={minimum_free_length:g} mm",
                basis="压簧压并后线圈接触，不能继续按正常弹簧行程压缩。",
                explanation="该测试状态会先压死弹簧，无法达到图纸所述的正常工作状态。",
                customer_question=f"请客户确认 {label} 的测试高度、端部形式或压并高度要求。",
            )


def _append_load_relation_issues(issues: list[dict[str, Any]], load_points: list[dict[str, Any]]) -> None:
    points = []
    for index, point in enumerate(load_points, start=1):
        height = _number(point.get("height"))
        force = _number(point.get("force"))
        if height is None or force is None:
            continue
        points.append((str(point.get("label") or f"F{index}"), height, force, str(point.get("test_height_type") or "")))
    for index, (left_label, left_height, left_force, left_type) in enumerate(points):
        for right_label, right_height, right_force, right_type in points[index + 1:]:
            if left_type and right_type and left_type != right_type:
                continue
            if abs(left_height - right_height) <= 1e-6 and abs(left_force - right_force) > 1e-6:
                _issue(
                    issues, "warning", "load_condition", "SPRING-LOAD-SAME-HEIGHT", [
                        f"load_points.{left_label}.height", f"load_points.{left_label}.force",
                        f"load_points.{right_label}.height", f"load_points.{right_label}.force",
                    ],
                    f"{left_label} 与 {right_label} 的试验高度相同但力值不同，需复核测试条件。",
                    calculation=f"{left_label}: H={left_height:g} mm, F={left_force:g} N；{right_label}: H={right_height:g} mm, F={right_force:g} N",
                    basis="同一弹簧、相同测试条件下，同一高度应对应同一载荷。",
                    explanation="可能是载荷点、工况标注或识别归属不一致。",
                    customer_question="请客户确认两个载荷点是否采用相同测试工况。",
                )
            elif (left_height - right_height) * (left_force - right_force) > 0:
                _issue(
                    issues, "warning", "load_condition", "SPRING-LOAD-MONOTONICITY", [
                        f"load_points.{left_label}.height", f"load_points.{left_label}.force",
                        f"load_points.{right_label}.height", f"load_points.{right_label}.force",
                    ],
                    f"{left_label} 与 {right_label} 的高度/载荷趋势相反，压缩更多时载荷不应更低。",
                    calculation=f"{left_label}: H={left_height:g} mm, F={left_force:g} N；{right_label}: H={right_height:g} mm, F={right_force:g} N",
                    basis="线性压簧在同一测试条件下，压缩量增大时载荷应增大。",
                    explanation="这通常意味着某个载荷点的高度、力值或工况需要复核。",
                    customer_question="请客户确认各载荷点的高度、力值及是否属于同一测试工况。",
                )


def _reference_solid_height(parameters: dict[str, Any], wire: float | None, total: float | None) -> float | None:
    if wire is None or total is None:
        return None
    wire_upper = _number((parameters.get("wire_diameter") or {}).get("tolerance_upper")) or 0
    max_wire = wire + max(0, wire_upper)
    end_mode = solid_height_mode(_value(parameters, "end_grinding"))
    if not end_mode:
        return None
    return total * max_wire if end_mode == "ground" else (total + 1.5) * max_wire


def _derived_mean_diameter(outer: float | None, inner: float | None, mean: float | None, wire: float | None) -> float | None:
    if mean is not None:
        return mean
    if outer is not None and wire is not None:
        return outer - wire
    if inner is not None and wire is not None:
        return inner + wire
    return None


def _derived_preview(derived: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for field in ("mean_diameter", "spring_index", "slenderness_ratio"):
        item = derived.get(field)
        if isinstance(item, dict) and item.get("value") is not None:
            preview[field] = {"value": item.get("value"), "unit": item.get("unit")}
    return preview


def _issue(
    issues: list[dict[str, Any]],
    severity: str,
    category: str,
    rule_id: str,
    fields: list[str],
    message: str,
    *,
    calculation: str,
    basis: str,
    explanation: str,
    customer_question: str,
) -> None:
    if any(item["rule_id"] == rule_id and item["message"] == message for item in issues):
        return
    issues.append({
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "fields": fields,
        "message": message,
        "calculation": calculation,
        "basis": basis,
        "explanation": explanation,
        "customer_question": customer_question,
    })


def _issue_key(issue: dict[str, Any]) -> tuple[str, tuple[str, ...], str]:
    return (
        str(issue.get("severity") or ""),
        tuple(str(field) for field in issue.get("fields") or []),
        str(issue.get("message") or ""),
    )


def _assessment_status(issues: list[dict[str, Any]], *, default: str = "pass") -> str:
    if any(item.get("severity") == "blocked" for item in issues):
        return "blocked"
    if any(item.get("severity") == "needs_input" for item in issues):
        return "needs_input"
    if any(item.get("severity") == "warning" for item in issues):
        return "warning"
    return default


def _assessment_summary(status: str, issues: list[dict[str, Any]]) -> str:
    if status == "pass":
        return "当前已识别参数未发现明显几何矛盾或当前标准适用范围风险。"
    if status == "not_applicable":
        return "当前弹簧类型暂未接入参数合理性诊断。"
    first = issues[0]["message"] if issues else "存在待复核参数。"
    labels = {
        "blocked": "发现无法直接采用的参数矛盾",
        "needs_input": "缺少完整判断所需的信息",
        "warning": "发现需要工程复核的参数风险",
    }
    return f"{labels.get(status, '参数需复核')}：{first}"


def _change_summary(status: str, issues: list[dict[str, Any]]) -> str:
    if status == "ready":
        return "参数关系预检通过，可人工确认后应用。"
    if status == "not_applicable":
        return "本次建议无需进行参数预检。"
    first = issues[0]["message"] if issues else "存在待复核参数。"
    if status == "blocked":
        return f"当前建议不可应用：{first}"
    if status == "needs_input":
        return f"当前建议可继续处理，但还需补充信息：{first}"
    return f"参数可应用，但需人工确认风险：{first}"


def _assessment(status: str, summary: str) -> dict[str, Any]:
    return {"status": status, "summary": summary, "issues": [], "derived_preview": {}, "scope": ""}


def _change_result(status: str, summary: str) -> dict[str, Any]:
    return {"status": status, "summary": summary, "issues": [], "changed_fields": [], "derived_preview": {}}


def _load_target(target: str) -> tuple[str, str] | None:
    parts = target.split(".")
    if len(parts) == 3 and parts[0] == "load_points" and parts[2] in {"force", "height"}:
        return parts[1], parts[2]
    return None


def _value(parameters: dict[str, Any], field: str) -> Any:
    item = parameters.get(field)
    return item.get("value") if isinstance(item, dict) else item


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalized_standard(value: Any) -> str:
    return str(value or "").replace("—", "-").replace(" ", "")


def _is_cold_standard(value: Any) -> bool:
    return _normalized_standard(value) == _normalized_standard(COLD_COILED_STANDARD)


def _label(field: str) -> str:
    labels = {
        "wire_diameter": "线径",
        "outer_diameter": "外径",
        "inner_diameter": "内径",
        "mean_diameter": "中径",
        "free_length": "自由长度",
        "total_coils": "总圈数",
        "active_coils": "有效圈数",
    }
    return labels.get(field, field)
