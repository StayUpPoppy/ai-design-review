from __future__ import annotations

from copy import deepcopy
from typing import Any

from .standardizers.compression import derive_compression_parameters


COLD_COILED_STANDARD = "GB/T 1239.2-2009"


def assess_parameter_change_set(review: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulate chat parameter patches and report deterministic feasibility checks."""
    applicable = [
        action
        for action in actions
        if isinstance(action, dict)
        and action.get("type") == "propose_parameter_patch"
        and action.get("target_field")
        and action.get("proposed_value") not in (None, "")
    ]
    if not applicable:
        return _result("not_applicable", "本次建议不改变弹簧主参数，无需进行几何预检。")

    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "")
    if spring_type != "compression_spring":
        return _result("not_applicable", "当前仅对压缩弹簧执行参数可行性预检。")

    parameters = deepcopy(review.get("spring_parameters") or {})
    changed_fields: list[str] = []
    for action in applicable:
        target = str(action["target_field"])
        if not _apply_parameter_patch(parameters, target, action.get("proposed_value")):
            continue
        changed_fields.append(target)

    if not changed_fields:
        return _result("not_applicable", "当前建议没有可模拟的参数字段。")

    issues = _compression_issues(parameters, review)
    derived = derive_compression_parameters(parameters)
    preview = _derived_preview(derived)
    status = "blocked" if any(item["severity"] == "blocked" for item in issues) else "warning" if issues else "ready"
    summary = _summary(status, issues)
    return {
        "status": status,
        "summary": summary,
        "issues": issues,
        "changed_fields": list(dict.fromkeys(changed_fields)),
        "derived_preview": preview,
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


def _compression_issues(parameters: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    wire = _number(_value(parameters, "wire_diameter"))
    outer = _number(_value(parameters, "outer_diameter"))
    inner = _number(_value(parameters, "inner_diameter"))
    mean = _number(_value(parameters, "mean_diameter"))
    free_length = _number(_value(parameters, "free_length"))
    total = _number(_value(parameters, "total_coils"))
    active = _number(_value(parameters, "active_coils"))

    _positive_issue(issues, "wire_diameter", wire, "线径必须大于 0 mm。")
    _positive_issue(issues, "outer_diameter", outer, "外径必须大于 0 mm。")
    _positive_issue(issues, "inner_diameter", inner, "内径必须大于 0 mm。")
    _positive_issue(issues, "mean_diameter", mean, "中径必须大于 0 mm。")
    _positive_issue(issues, "free_length", free_length, "自由长度必须大于 0 mm。")
    _positive_issue(issues, "total_coils", total, "总圈数必须大于 0。")
    _positive_issue(issues, "active_coils", active, "有效圈数必须大于 0。")

    if outer is not None and wire is not None and outer - 2 * wire <= 0:
        _issue(
            issues,
            "blocked",
            ["outer_diameter", "wire_diameter"],
            "外径必须大于两倍线径，否则推导内径小于等于 0。",
        )

    derived_mean = outer - wire if outer is not None and wire is not None else inner + wire if inner is not None and wire is not None else mean
    if outer is not None and inner is not None and wire is not None:
        expected_inner = outer - 2 * wire
        if abs(inner - expected_inner) > max(0.02, wire * 0.02):
            _issue(
                issues,
                "warning",
                ["outer_diameter", "inner_diameter", "wire_diameter"],
                f"按外径和线径推导内径应约为 {expected_inner:g} mm，与当前内径不一致。",
            )

    if total is not None and active is not None and active > total:
        _issue(issues, "blocked", ["active_coils", "total_coils"], "有效圈数不能大于总圈数。")

    if derived_mean is not None and wire not in (None, 0):
        spring_index = derived_mean / wire
        selected_standard = str((review.get("standard_selection") or {}).get("selected_standard") or "")
        if selected_standard == COLD_COILED_STANDARD and not 3 <= spring_index <= 22:
            _issue(
                issues,
                "warning",
                ["outer_diameter", "inner_diameter", "mean_diameter", "wire_diameter"],
                f"预计旋绕比 C={spring_index:g} 超出 GB/T 1239.2-2009 当前规则表的 3~22 范围，公差表将不适用。",
            )

    reference_solid = _reference_solid_height(parameters, wire, total)
    explicit_solid = _number(_value(parameters, "solid_height"))
    minimum_free_length = explicit_solid if explicit_solid is not None else reference_solid
    if free_length is not None and minimum_free_length is not None and free_length <= minimum_free_length:
        source = "压并高度" if explicit_solid is not None else "按当前端面方式推导的压并高度"
        _issue(
            issues,
            "blocked",
            ["free_length", "solid_height", "total_coils", "wire_diameter", "end_grinding"],
            f"自由长度必须大于{source} {minimum_free_length:g} mm。",
        )

    for index, point in enumerate(parameters.get("load_points") or [], start=1):
        if not isinstance(point, dict):
            continue
        label = str(point.get("label") or f"F{index}")
        height = _number(point.get("height"))
        force = _number(point.get("force"))
        if height is not None and height <= 0:
            _issue(issues, "blocked", [f"load_points.{label}.height"], f"{label} 的试验高度必须大于 0 mm。")
        if force is not None and force < 0:
            _issue(issues, "blocked", [f"load_points.{label}.force"], f"{label} 的载荷不能为负值。")
        if height is not None and free_length is not None and height > free_length:
            _issue(
                issues,
                "blocked",
                ["free_length", f"load_points.{label}.height"],
                f"{label} 的试验高度不能大于自由长度，否则压缩弹簧没有有效压缩量。",
            )
        if height is not None and minimum_free_length is not None and height < minimum_free_length:
            _issue(
                issues,
                "blocked",
                ["solid_height", f"load_points.{label}.height"],
                f"{label} 的试验高度不能小于压并高度参考值 {minimum_free_length:g} mm。",
            )
    return issues


def _reference_solid_height(parameters: dict[str, Any], wire: float | None, total: float | None) -> float | None:
    if wire is None or total is None:
        return None
    wire_upper = _number((parameters.get("wire_diameter") or {}).get("tolerance_upper")) or 0
    max_wire = wire + max(0, wire_upper)
    end_mode = str(_value(parameters, "end_grinding") or "")
    if not end_mode:
        return None
    return total * max_wire if "磨" in end_mode and "不磨" not in end_mode else (total + 1.5) * max_wire


def _derived_preview(derived: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for field in ("mean_diameter", "spring_index", "slenderness_ratio"):
        item = derived.get(field)
        if isinstance(item, dict) and item.get("value") is not None:
            preview[field] = {"value": item.get("value"), "unit": item.get("unit")}
    return preview


def _positive_issue(issues: list[dict[str, Any]], field: str, value: float | None, message: str) -> None:
    if value is not None and value <= 0:
        _issue(issues, "blocked", [field], message)


def _issue(issues: list[dict[str, Any]], severity: str, fields: list[str], message: str) -> None:
    if any(item["message"] == message for item in issues):
        return
    issues.append({"severity": severity, "fields": fields, "message": message})


def _summary(status: str, issues: list[dict[str, Any]]) -> str:
    if status == "ready":
        return "参数关系校验通过，可人工确认后应用。"
    if status == "blocked":
        blocking = next(item["message"] for item in issues if item["severity"] == "blocked")
        return f"当前建议不可应用：{blocking}"
    return f"参数可应用，但需人工确认风险：{issues[0]['message']}"


def _load_target(target: str) -> tuple[str, str] | None:
    parts = target.split(".")
    if len(parts) == 3 and parts[0] == "load_points" and parts[2] == "force":
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


def _result(status: str, summary: str) -> dict[str, Any]:
    return {"status": status, "summary": summary, "issues": [], "changed_fields": [], "derived_preview": {}}
