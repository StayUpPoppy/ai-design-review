"""Read-only explanations and navigation for incomplete standardization results."""
from __future__ import annotations

import re
from typing import Any

from .standardizers.stiffness import calculate_compression_spring_rate


FIELD_LABELS = {
    "material": "材料", "wire_diameter": "线径", "outer_diameter": "外径", "inner_diameter": "内径",
    "mean_diameter": "中径", "free_length": "自由高度", "total_coils": "总圈数", "active_coils": "有效圈数",
    "support_coils": "支承圈数", "spring_rate": "刚度", "accuracy_grade": "精度等级", "standard_no": "执行标准",
    "diameter_accuracy_grade": "直径精度等级", "free_length_accuracy_grade": "自由高度精度等级",
    "load_accuracy_grade": "载荷精度等级", "stiffness_accuracy_grade": "刚度精度等级", "pitch": "节距",
    "end_type": "端部形式", "end_grinding": "端面磨削", "perpendicularity": "垂直度", "straightness": "直线度",
}
ACTIONABLE_STATUSES = {"suggested", "llm_suggested", "human_confirmed"}


def field_label(field: str) -> str:
    load = re.fullmatch(r"load_points\.(.+)\.force", field)
    return FIELD_LABELS.get(field) or (f"{load[1]} 力值" if load else field)


def _unique(fields: list) -> list[str]:
    return list(dict.fromkeys(str(field) for field in fields if field))


def affected_targets(result: dict, parameters: dict) -> list[str]:
    target = str(result.get("target_field") or "")
    if target == "load_points":
        return [f"load_points.{point.get('label') or f'F{index + 1}'}.force"
                for index, point in enumerate(parameters.get("load_points") or [])]
    return [target] if target else []


def root_missing_fields(result: dict, rate_calculation: dict) -> list[str]:
    missing = _unique((result.get("metadata") or {}).get("missing_fields") or [])
    rate_missing = rate_calculation.get("missing_fields") or []
    return _unique([root for field in missing for root in (rate_missing if field == "spring_rate" and rate_missing else [field])])


def annotate_missing_roots(review: dict) -> None:
    """Enrich result metadata without adopting formula values or changing inputs."""
    results = review.get("standardization_results") or []
    rate = calculate_compression_spring_rate(review.get("spring_parameters") or {}, review.get("spring_features") or {}) if any(
        "spring_rate" in ((item.get("metadata") or {}).get("missing_fields") or []) and item.get("status") != "stale"
        for item in results
    ) else {}
    for item in results:
        if item.get("status") == "stale":
            continue
        metadata = item.get("metadata") or {}
        if metadata.get("missing_fields"):
            item.setdefault("metadata", {})["root_missing_fields"] = root_missing_fields(item, rate)


def _has_value(parameters: dict, field: str) -> bool:
    load = re.fullmatch(r"load_points\.(.+)\.force", field)
    value = next((p.get("force") for p in parameters.get("load_points") or [] if p.get("label") == load[1]), None) if load else (parameters.get(field) or {}).get("value")
    return value is not None and str(value).strip() != ""


def describe_diagnostic(group: dict, parameters: dict) -> dict:
    roots, targets = group["root_missing_fields"], group["affected_fields"]
    load_labels = [match[1] for target in targets if (match := re.fullmatch(r"load_points\.(.+)\.force", target))]
    affected = f"{'、'.join(load_labels)} 的力值公差" if len(load_labels) == len(targets) else f"{'、'.join(map(field_label, targets))}的标准公差"
    names = "、".join(map(field_label, roots))
    via_rate = "spring_rate" in group["missing_fields"] and "spring_rate" not in roots
    if roots:
        prefix = f"需补充或核对{names}" if any(_has_value(parameters, field) for field in roots) else f"缺少{names}"
        message = f"{prefix}，{'无法计算刚度，因此' if via_rate else ''}{affected}尚未生成。"
        calculation = f"刚度计算需要{names}；载荷公差计算依赖刚度。" if via_rate else f"公差计算需要有效的{names}。"
        operation = "补充或核对" if any(_has_value(parameters, field) for field in roots) else "补充"
        resolution = f"{operation}{names}后重新标准化"
        resolution += "，也可直接填写刚度或手填力值公差。" if via_rate else "，或手填力值公差。" if "spring_rate" in group["missing_fields"] else "，或手填公差。"
        if "material" in roots and _has_value(parameters, "material"):
            calculation += "当前材料未匹配可用剪切模量，请核对材料。"
    else:
        message = group["basis"] or "当前规则无法计算，请核对输入或手填公差。"
        calculation = "当前规则未形成唯一可应用值。"
        resolution = "请按上述规则说明核对参数，或手填公差。"
    basis = group["basis"]
    if roots and ("缺少有效计算依据" in basis or "缺少有效载荷、精度等级或有效圈数" in basis):
        basis = ""
    return {**group, "basis": basis, "category": "standardization", "fields": roots or targets, "message": message,
            "calculation": calculation, "explanation": "补齐后重新生成建议；当前公差保持不变。",
            "customer_question": resolution, "resolution": resolution, "via_spring_rate": via_rate}


def diagnostic_groups(review: dict, *, require_fresh: bool = True) -> list[dict[str, Any]]:
    """Merge only equal load problems, preserving every affected test point."""
    from .execution_standards import VERSION, fingerprint
    results = review.get("standardization_results") or []
    context = review.get("standardization_context") or {}
    if require_fresh and (context.get("version") != VERSION or context.get("input_fingerprint") != fingerprint(review)):
        return []
    parameters = review.get("spring_parameters") or {}
    rate = calculate_compression_spring_rate(parameters, review.get("spring_features") or {}) if any(
        "spring_rate" in ((item.get("metadata") or {}).get("missing_fields") or []) for item in results
    ) else {}
    groups: dict[tuple, dict] = {}
    valid_targets = {target for result in results if result.get("status") in ACTIONABLE_STATUSES
                     and any(result.get(key) is not None for key in ("suggested_value", "suggested_tolerance_upper", "suggested_tolerance_lower"))
                     for target in affected_targets(result, parameters)}
    for index, result in enumerate(results):
        metadata = result.get("metadata") or {}
        status = str(result.get("status") or "")
        if status in ACTIONABLE_STATUSES | {"stale"} or result.get("target_field") == "standard_no" or metadata.get("value_kind") == "reference_limit" or result.get("rule_id") == "GBT1239.2-SOLID":
            continue
        targets = [target for target in affected_targets(result, parameters) if target not in valid_targets]
        if not targets:
            continue
        missing = _unique(metadata.get("missing_fields") or [])
        roots = root_missing_fields(result, rate)
        basis = str(result.get("basis") or "")
        rule = str(result.get("rule_id") or f"STANDARDIZATION-DIAGNOSTIC-{index + 1}")
        severity = "needs_input" if status in {"need_context", "rules_pending", "unmapped"} else "warning"
        kind = "load" if all(re.fullmatch(r"load_points\.(.+)\.force", target) for target in targets) else tuple(targets)
        key = (rule, severity, kind, tuple(sorted(roots)), "spring_rate" in missing, basis if not roots else "")
        if key not in groups:
            groups[key] = {"rule_id": rule, "severity": severity, "missing_fields": missing, "root_missing_fields": roots,
                           "affected_fields": [], "basis": basis}
        groups[key]["affected_fields"] = _unique(groups[key]["affected_fields"] + targets)
    return [describe_diagnostic(group, parameters) for group in groups.values()]
