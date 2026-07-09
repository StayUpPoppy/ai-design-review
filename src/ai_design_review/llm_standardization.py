from __future__ import annotations

import re
from typing import Any

from .spring_templates import field_default_unit, template_field_keys


LLM_STANDARDIZATION_FIELD = "llm_standardization_results"

_LOAD_POINT_TARGET_RE = re.compile(r"^load_points\.([^.]+)\.(force)$")
_PASS_THROUGH_STATUSES = {"need_context", "not_applicable", "rules_pending"}


def normalize_llm_standardization_results(
    payload: Any,
    *,
    spring_type: str,
    spring_parameters: dict[str, Any],
    standard_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalize LLM/RAG standardization JSON for frontend display.

    LLM output is never treated as authoritative calculation. Valid mapped items
    are returned as confirmable suggestions, but they remain human-review
    required and carry validation metadata.
    """

    items = _extract_items(payload)
    results: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                {
                    "index": index,
                    "status": "skipped",
                    "reason": "LLM standardization item is not an object.",
                    "value": item,
                }
            )
            continue
        normalized, diagnostic = _normalize_item(
            item,
            index=index,
            spring_type=spring_type,
            spring_parameters=spring_parameters,
            standard_selection=standard_selection,
        )
        results.append(normalized)
        if diagnostic:
            diagnostics.append(diagnostic)
    return {
        "standardization_results": results,
        "diagnostics": diagnostics,
    }


def _extract_items(payload: Any) -> list[Any]:
    if payload in (None, ""):
        return []
    value = payload
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    if isinstance(value, dict) and "standardization_results" in value:
        value = value.get("standardization_results")
    if isinstance(value, dict) and "results" in value:
        value = value.get("results")
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return []


def _normalize_item(
    item: dict[str, Any],
    *,
    index: int,
    spring_type: str,
    spring_parameters: dict[str, Any],
    standard_selection: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    original_target = str(item.get("target_field") or "").strip()
    target_field, target_valid, target_error = _validate_target_field(
        original_target,
        spring_type=spring_type,
        spring_parameters=spring_parameters,
    )
    raw_status = str(item.get("status") or "").strip()
    status = _normalize_status(raw_status, target_valid)
    metadata = dict(item.get("metadata") or {})
    references = item.get("references") or item.get("rag_references") or item.get("source_chunks")
    if references:
        metadata["rag_references"] = references
    metadata.update(
        {
            "source": "llm_standardization",
            "target_field_valid": target_valid,
            "target_field_error": target_error,
            "original_target_field": original_target,
            "original_status": raw_status,
        }
    )
    if item.get("confidence") is not None:
        metadata["llm_confidence"] = _number_or_original(item.get("confidence"))

    standard_no = (
        item.get("standard_no")
        or (standard_selection or {}).get("selected_standard")
        or _param_value(spring_parameters, "standard_no")
        or ""
    )
    basis = str(item.get("basis") or item.get("reason") or "").strip()
    if not basis:
        basis = "LLM/RAG 标准化建议缺少可追溯依据，需人工确认。"
    if target_error:
        basis = f"{basis} 字段映射提示：{target_error}"

    normalized = {
        "target_field": target_field,
        "suggested_value": _number_or_original(item.get("suggested_value")),
        "suggested_tolerance_upper": _number_or_none(item.get("suggested_tolerance_upper")),
        "suggested_tolerance_lower": _number_or_none(item.get("suggested_tolerance_lower")),
        "unit": item.get("unit") or _target_unit(target_field, spring_type, spring_parameters),
        "standard_no": standard_no,
        "rule_id": str(item.get("rule_id") or f"LLM-STANDARDIZATION-{index}"),
        "basis": basis,
        "status": status,
        "need_human_review": True,
        "confidence": _number_or_original(item.get("confidence")) if item.get("confidence") is not None else None,
        "metadata": metadata,
    }
    if normalized["confidence"] is None:
        normalized.pop("confidence", None)

    diagnostic = None
    if not target_valid:
        diagnostic = {
            "index": index,
            "status": "unmapped",
            "target_field": original_target,
            "reason": target_error,
            "rule_id": normalized["rule_id"],
        }
    return normalized, diagnostic


def _validate_target_field(
    target_field: str,
    *,
    spring_type: str,
    spring_parameters: dict[str, Any],
) -> tuple[str, bool, str]:
    if not target_field:
        return "unmapped", False, "缺少 target_field，无法映射到前端参数。"

    allowed_fields = set(template_field_keys(spring_type))
    allowed_fields.add("standard_no")
    if target_field in allowed_fields:
        return target_field, True, ""

    match = _LOAD_POINT_TARGET_RE.match(target_field)
    if match:
        label = match.group(1)
        labels = _load_point_labels(spring_parameters)
        if labels and label not in labels:
            return target_field, True, f"载荷点 {label} 当前未在识别结果中找到，确认前需人工核对。"
        return target_field, True, ""

    return target_field, False, f"字段 {target_field} 不在当前弹簧模板中，已标记为未映射。"


def _normalize_status(raw_status: str, target_valid: bool) -> str:
    if not target_valid:
        return "unmapped"
    if raw_status in _PASS_THROUGH_STATUSES:
        return raw_status
    return "llm_suggested"


def _target_unit(target_field: str, spring_type: str, spring_parameters: dict[str, Any]) -> str | None:
    if target_field.startswith("load_points."):
        return "N" if target_field.endswith(".force") else None
    parameter = spring_parameters.get(target_field)
    if isinstance(parameter, dict) and parameter.get("unit"):
        return parameter.get("unit")
    return field_default_unit(spring_type, target_field)


def _load_point_labels(spring_parameters: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for index, point in enumerate(spring_parameters.get("load_points", []) or [], start=1):
        label = str(point.get("label") or f"F{index}").strip()
        if label:
            labels.add(label)
    return labels


def _param_value(mapping: dict[str, Any], field: str) -> Any:
    value = mapping.get(field)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _number_or_none(value: Any) -> int | float | None:
    number = _number_or_original(value)
    return number if isinstance(number, (int, float)) else None


def _number_or_original(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else number
