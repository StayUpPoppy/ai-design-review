from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = [
    "material",
    "wire_diameter",
    "outer_diameter",
    "free_length",
    "total_coils",
    "handedness",
]


def run_rule_checks(
    spring_parameters: dict[str, Any],
    technical_requirements: list[dict[str, Any]],
    file_info: dict[str, Any],
    factory_rules: dict[str, Any],
    spring_type: str = "compression_spring",
    required_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    results.extend(_check_required_fields(spring_parameters, required_fields or REQUIRED_FIELDS))
    results.append(_check_material(spring_parameters, factory_rules))
    results.append(_check_process_ranges(spring_parameters, factory_rules))
    if spring_type == "compression_spring":
        results.append(_check_free_length_vs_load_heights(spring_parameters))
        results.append(_check_load_monotonicity(spring_parameters))
    results.append(_check_tolerance_band(spring_parameters, factory_rules))
    results.append(_check_technical_requirements(technical_requirements))
    results.append(_check_scanned_policy(file_info, factory_rules))
    return [item for item in results if item]


def should_require_human_review(
    spring_parameters: dict[str, Any],
    review_results: list[dict[str, Any]],
) -> bool:
    if any(item.get("status") in {"fail", "missing", "need_review"} for item in review_results):
        return True
    if any(param.get("need_human_review") for param in spring_parameters.values() if isinstance(param, dict)):
        return True
    if any(
        item.get("need_human_review")
        for param in spring_parameters.values()
        if isinstance(param, list)
        for item in param
        if isinstance(item, dict)
    ):
        return True
    return False


def determine_erp_ready(
    review_results: list[dict[str, Any]],
    human_review_required: bool,
    factory_rules: dict[str, Any],
) -> tuple[bool, str]:
    erp_policy = factory_rules.get("erp_policy", {})
    blocked_status = set(erp_policy.get("block_on_status", ["fail", "missing", "need_review"]))
    for result in review_results:
        if result.get("status") in blocked_status:
            return False, result.get("message", "存在阻断审查项。")
    if erp_policy.get("block_if_human_review_required", True) and human_review_required:
        return False, "关键图纸字段仍需要人工确认，禁止自动进入 ERP。"
    return True, ""


def overall_status(review_results: list[dict[str, Any]]) -> str:
    statuses = [item.get("status") for item in review_results]
    if "fail" in statuses:
        return "fail"
    if "missing" in statuses or "need_review" in statuses:
        return "need_review"
    if "warning" in statuses:
        return "warning"
    return "pass"


def _check_required_fields(spring_parameters: dict[str, Any], required_fields: list[str]) -> list[dict[str, Any]]:
    results = []
    for field in required_fields:
        value = spring_parameters.get(field, {}).get("value")
        if value in (None, ""):
            results.append(
                _result(
                    "REQ-001",
                    "关键字段完整性",
                    "missing",
                    f"缺少关键弹簧参数：{field}。",
                    [field],
                    "critical",
                )
            )
    return results


def _check_material(spring_parameters: dict[str, Any], factory_rules: dict[str, Any]) -> dict[str, Any]:
    material = spring_parameters.get("material", {}).get("value")
    allowed = factory_rules.get("materials", {}).get("allowed", [])
    if not material:
        return _result("MAT-001", "材料明确性", "missing", "材料未识别。", ["material"], "critical")
    if allowed and material not in allowed:
        return _result("MAT-002", "材料工艺能力", "warning", f"材料 {material} 不在当前工艺白名单中。", ["material"], "medium")
    return _result("MAT-000", "材料工艺能力", "pass", f"材料 {material} 已识别。", ["material"], "low")


def _check_process_ranges(spring_parameters: dict[str, Any], factory_rules: dict[str, Any]) -> dict[str, Any]:
    capability = factory_rules.get("process_capability", {})
    wire = spring_parameters.get("wire_diameter", {}).get("value")
    outer = spring_parameters.get("outer_diameter", {}).get("value")
    messages = []

    if wire is not None:
        low, high = capability.get("wire_diameter_range_mm", [None, None])
        if low is not None and not (low <= float(wire) <= high):
            messages.append(f"线径 {wire}mm 超出工艺范围 {low}-{high}mm。")
    if outer is not None:
        low, high = capability.get("outer_diameter_range_mm", [None, None])
        if low is not None and not (low <= float(outer) <= high):
            messages.append(f"外径 {outer}mm 超出工艺范围 {low}-{high}mm。")

    if messages:
        return _result("CAP-001", "工艺能力范围", "fail", " ".join(messages), ["wire_diameter", "outer_diameter"], "critical")
    return _result("CAP-000", "工艺能力范围", "pass", "线径和外径处于当前工艺范围内。", ["wire_diameter", "outer_diameter"], "low")


def _check_free_length_vs_load_heights(spring_parameters: dict[str, Any]) -> dict[str, Any]:
    free_length = spring_parameters.get("free_length", {}).get("value")
    load_points = spring_parameters.get("load_points", [])
    if free_length is None or not load_points:
        return _result("LOAD-001", "自由长度与压缩高度", "need_review", "自由长度或载荷点缺失，无法判断压缩高度关系。", ["free_length", "load_points"], "high")
    bad = [p for p in load_points if p.get("height") is not None and float(p["height"]) >= float(free_length)]
    if bad:
        return _result("LOAD-002", "自由长度与压缩高度", "fail", "存在压缩高度大于或等于自由长度的载荷点。", ["free_length", "load_points"], "critical")
    return _result("LOAD-000", "自由长度与压缩高度", "pass", "自由长度大于已识别压缩高度。", ["free_length", "load_points"], "low")


def _check_load_monotonicity(spring_parameters: dict[str, Any]) -> dict[str, Any]:
    free_length = spring_parameters.get("free_length", {}).get("value")
    load_points = [
        p for p in spring_parameters.get("load_points", [])
        if p.get("height") is not None and p.get("force") is not None
    ]
    if free_length is None or len(load_points) < 2:
        return _result("LOAD-101", "载荷随压缩量递增", "need_review", "载荷点不足，无法判断载荷曲线趋势。", ["load_points"], "medium")

    ordered = sorted(load_points, key=lambda p: float(free_length) - float(p["height"]))
    for left, right in zip(ordered, ordered[1:]):
        if float(right["force"]) < float(left["force"]):
            return _result("LOAD-102", "载荷随压缩量递增", "fail", "压缩量增大时载荷未递增。", ["load_points"], "critical")
    return _result("LOAD-100", "载荷随压缩量递增", "pass", "载荷随压缩量增大而增大。", ["load_points"], "low")


def _check_tolerance_band(spring_parameters: dict[str, Any], factory_rules: dict[str, Any]) -> dict[str, Any]:
    min_band = factory_rules.get("process_capability", {}).get("min_stable_tolerance_band_mm", 0)
    warnings = []
    for field in ("wire_diameter", "outer_diameter", "free_length"):
        param = spring_parameters.get(field, {})
        upper = param.get("tolerance_upper")
        lower = param.get("tolerance_lower")
        if upper is None or lower is None:
            continue
        band = abs(float(upper) - float(lower))
        if band > 0 and band < float(min_band):
            warnings.append(f"{field} 公差带 {band:g}mm 小于稳定加工阈值 {min_band:g}mm。")
    if warnings:
        return _result("TOL-001", "公差工艺风险", "warning", " ".join(warnings), ["tolerance"], "high")
    return _result("TOL-000", "公差工艺风险", "pass", "未发现低于阈值的尺寸公差带。", ["tolerance"], "low")


def _check_technical_requirements(technical_requirements: list[dict[str, Any]]) -> dict[str, Any]:
    types = {item.get("type") for item in technical_requirements}
    if not types:
        return _result("TECH-001", "技术要求完整性", "warning", "未识别到技术/工艺要求，需人工确认。", ["technical_requirements"], "medium")
    return _result("TECH-000", "技术要求完整性", "pass", "已识别技术/工艺要求。", ["technical_requirements"], "low")


def _check_scanned_policy(file_info: dict[str, Any], factory_rules: dict[str, Any]) -> dict[str, Any]:
    require_review = factory_rules.get("process_capability", {}).get("require_human_review_for_scanned_input", True)
    if require_review and file_info.get("is_scanned_like"):
        return _result("DOC-001", "扫描图纸放行策略", "need_review", "当前输入为扫描图纸或图片，关键尺寸必须人工确认后才能进入 ERP。", ["file"], "high")
    return _result("DOC-000", "扫描图纸放行策略", "pass", "输入文件不触发扫描图纸强制确认策略。", ["file"], "low")


def _result(rule_id: str, name: str, status: str, message: str, fields: list[str], severity: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_name": name,
        "status": status,
        "message": message,
        "related_fields": fields,
        "severity": severity,
    }
