from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any

from .standardizers.coil_counts import COMPANY_ACTIVE_COIL_RULE, derive_active_coils
from .standardizers.compression import calculate_compression_solid_height, derive_compression_parameters
from .standardizers.diameters import calculate_compression_diameter_completion
from .standardizers.stiffness import calculate_compression_spring_rate


FORMULA_RULES = {
    "solid_height": "FORMULA-SOLID-HEIGHT",
    "spring_rate": "FORMULA-SPRING-RATE",
    "wire_diameter": "FORMULA-DIAMETER-WIRE",
    "outer_diameter": "FORMULA-DIAMETER-OUTER",
    "inner_diameter": "FORMULA-DIAMETER-INNER",
    "mean_diameter": "FORMULA-DIAMETER-MEAN",
}


def build_parameter_suggestions(
    review: dict[str, Any],
    *,
    based_on_revision: int | None = None,
) -> list[dict[str, Any]]:
    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "")
    if spring_type != "compression_spring":
        return []
    parameters = review.get("spring_parameters") or {}
    revision = based_on_revision if based_on_revision is not None else _integer(review.get("review_revision"))
    suggestions = [
        *_formula_suggestions(parameters, review.get("spring_features") or {}, revision),
        *_standardization_suggestions(
            parameters,
            review.get("standardization_results") or [],
            review.get("standard_selection") or {},
            revision,
        ),
        *_informational_suggestions(parameters, revision),
    ]
    suggestions = _deduplicate_suggestions(suggestions)
    _mark_conflicts(suggestions)
    return suggestions


def dependency_snapshot(parameters: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {
        field: _parameter_dependency_value(parameters.get(field))
        for field in sorted(dict.fromkeys(str(field) for field in fields if field))
    }


def dependency_token(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    value = 2166136261
    for byte in encoded:
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return f"fnv1a32:{value:08x}"


def _formula_suggestions(
    parameters: dict[str, Any],
    spring_features: dict[str, Any],
    revision: int | None,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    solid = calculate_compression_solid_height(parameters)
    if solid.get("status") == "calculated":
        suggestions.append(_suggestion(
            parameters,
            source="formula",
            target_field="solid_height",
            suggested_value=solid.get("value"),
            unit=solid.get("unit"),
            rule_id=FORMULA_RULES["solid_height"],
            basis=solid.get("basis") or "",
            source_fields=solid.get("source_fields") or [],
            based_on_revision=revision,
        ))

    for field, calculation in calculate_compression_diameter_completion(parameters).items():
        suggestions.append(_suggestion(
            parameters,
            source="formula",
            target_field=field,
            suggested_value=calculation.get("value"),
            unit="mm",
            rule_id=FORMULA_RULES[field],
            basis=calculation.get("basis") or calculation.get("formula") or "",
            source_fields=calculation.get("source_fields") or [],
            based_on_revision=revision,
        ))

    active_inputs = deepcopy(parameters)
    active_inputs.pop("active_coils", None)
    active = derive_active_coils("compression_spring", active_inputs).get("active_coils") or {}
    if active.get("value") is not None:
        suggestions.append(_suggestion(
            parameters,
            source="formula",
            target_field="active_coils",
            suggested_value=active.get("value"),
            unit=active.get("unit"),
            rule_id=str(active.get("rule_id") or COMPANY_ACTIVE_COIL_RULE),
            basis=active.get("basis") or "",
            source_fields=active.get("source_fields") or [],
            based_on_revision=revision,
        ))

    stiffness = calculate_compression_spring_rate(parameters, spring_features)
    if stiffness.get("status") == "calculated":
        suggestions.append(_suggestion(
            parameters,
            source="formula",
            target_field="spring_rate",
            suggested_value=stiffness.get("value"),
            unit=stiffness.get("unit") or "N/mm",
            rule_id=FORMULA_RULES["spring_rate"],
            basis=stiffness.get("basis") or "",
            source_fields=stiffness.get("source_fields") or [],
            based_on_revision=revision,
        ))
    return suggestions


def _standardization_suggestions(
    parameters: dict[str, Any],
    results: list[dict[str, Any]],
    standard_selection: dict[str, Any],
    revision: int | None,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    fallback_fields = sorted(str(field) for field in parameters.keys())
    standard_candidates = {
        str(item.get("suggested_value")).strip()
        for item in results
        if isinstance(item, dict)
        and item.get("target_field") == "standard_no"
        and item.get("suggested_value") not in (None, "")
    }
    for index, result in enumerate(results):
        if not isinstance(result, dict) or not result.get("target_field"):
            continue
        has_value = result.get("suggested_value") is not None
        has_tolerance = result.get("suggested_tolerance_upper") is not None or result.get("suggested_tolerance_lower") is not None
        if not has_value and not has_tolerance:
            continue
        metadata = result.get("metadata") or {}
        source_fields = metadata.get("source_fields") or result.get("source_fields") or fallback_fields
        raw_status = str(result.get("status") or "")
        if raw_status == "stale":
            status = "stale"
        elif (
            raw_status == "need_context"
            and result.get("target_field") == "standard_no"
            and _target_state(parameters, "standard_no").get("value") in (None, "")
            and len(standard_candidates) == 1
            and str(result.get("suggested_value") or "").strip() == str(standard_selection.get("selected_standard") or "").strip()
            and standard_selection.get("rules_available") is True
            and not (standard_selection.get("metadata") or {}).get("conflicts")
            and metadata.get("target_field_valid") is not False
            and not metadata.get("target_field_error")
        ):
            # An explicit application is the user's acceptance of the one
            # supported recommendation; it is not a drawing-recognized value.
            status = "available"
        elif raw_status in {"suggested", "llm_suggested", "human_confirmed"} and metadata.get("target_field_valid") is not False and not metadata.get("target_field_error"):
            # ``human_confirmed`` records that this recommendation was applied
            # once.  It is provenance, not the current recommendation state:
            # if the user later changes the target away from the recommendation,
            # the same still-valid recommendation must become available again.
            status = "available"
        else:
            status = "informational"
        suggestions.append(_suggestion(
            parameters,
            source="standardization",
            target_field=str(result.get("target_field")),
            suggested_value=result.get("suggested_value"),
            suggested_tolerance_upper=result.get("suggested_tolerance_upper"),
            suggested_tolerance_lower=result.get("suggested_tolerance_lower"),
            unit=result.get("unit"),
            rule_id=str(result.get("rule_id") or f"STANDARDIZATION-{index + 1}"),
            basis=str(result.get("basis") or ""),
            source_fields=list(source_fields) if isinstance(source_fields, list) else fallback_fields,
            based_on_revision=revision,
            status=status,
            result_index=index,
        ))
    return suggestions


def _informational_suggestions(parameters: dict[str, Any], revision: int | None) -> list[dict[str, Any]]:
    derived = derive_compression_parameters(deepcopy(parameters))
    labels = {
        "spring_index": ("FORMULA-SPRING-INDEX", "旋绕比为只读计算结果，用于判断标准规则适用范围。"),
        "slenderness_ratio": ("FORMULA-SLENDERNESS", "细长比为只读计算结果，用于评估垂直度和稳定性风险。"),
    }
    suggestions: list[dict[str, Any]] = []
    for field, (rule_id, fallback_basis) in labels.items():
        item = derived.get(field)
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        suggestions.append(_suggestion(
            parameters,
            source="formula",
            target_field=field,
            suggested_value=item.get("value"),
            unit=item.get("unit"),
            rule_id=rule_id,
            basis=item.get("basis") or item.get("formula") or fallback_basis,
            source_fields=item.get("source_fields") or [],
            based_on_revision=revision,
            status="informational",
            application_mode="none",
        ))
    return suggestions


def _suggestion(
    parameters: dict[str, Any],
    *,
    source: str,
    target_field: str,
    suggested_value: Any,
    unit: str | None,
    rule_id: str,
    basis: str,
    source_fields: list[str],
    based_on_revision: int | None,
    suggested_tolerance_upper: Any = None,
    suggested_tolerance_lower: Any = None,
    status: str | None = None,
    result_index: int | None = None,
    application_mode: str | None = None,
) -> dict[str, Any]:
    current = _target_state(parameters, target_field)
    has_value = suggested_value is not None
    has_tolerance = suggested_tolerance_upper is not None or suggested_tolerance_lower is not None
    mode = application_mode or ("value_and_tolerance" if has_value and has_tolerance else "value" if has_value else "tolerance" if has_tolerance else "none")
    snapshot = dependency_snapshot(parameters, source_fields)
    payload = {
        "source": source,
        "target_field": target_field,
        "suggested_value": suggested_value,
        "suggested_tolerance_upper": suggested_tolerance_upper,
        "suggested_tolerance_lower": suggested_tolerance_lower,
        "rule_id": rule_id,
        "dependency_token": dependency_token(snapshot),
    }
    suggestion_id = f"suggestion_{sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"
    resolved_status = status or _formula_status(current, suggested_value, suggested_tolerance_upper, suggested_tolerance_lower)
    if resolved_status == "available" and not _suggestion_has_effective_change(
        current,
        mode,
        suggested_value,
        suggested_tolerance_upper,
        suggested_tolerance_lower,
    ):
        resolved_status = "informational"
    return {
        "suggestion_id": suggestion_id,
        "source": source,
        "target_field": target_field,
        "current_value": current.get("value"),
        "current_tolerance_upper": current.get("tolerance_upper"),
        "current_tolerance_lower": current.get("tolerance_lower"),
        "suggested_value": suggested_value,
        "suggested_tolerance_upper": suggested_tolerance_upper,
        "suggested_tolerance_lower": suggested_tolerance_lower,
        "unit": unit or current.get("unit"),
        "application_mode": mode,
        "rule_id": rule_id,
        "basis": basis,
        "source_fields": list(dict.fromkeys(source_fields)),
        "dependency_snapshot": snapshot,
        "dependency_token": payload["dependency_token"],
        "based_on_revision": based_on_revision,
        "status": resolved_status,
        "standardization_result_index": result_index,
        "standardization_result_indexes": [result_index] if result_index is not None else [],
    }


def _formula_status(
    current: dict[str, Any],
    suggested_value: Any,
    upper: Any,
    lower: Any,
) -> str:
    # ``last_applied_suggestion_id`` is audit provenance only.  Availability is
    # always derived from the live value/tolerance so a recommendation can
    # reappear after the user applies it and then edits the parameter again.
    same_value = suggested_value is None or _equal(current.get("value"), suggested_value)
    same_tolerance = (upper is None and lower is None) or (
        _equal(current.get("tolerance_upper"), upper) and _equal(current.get("tolerance_lower"), lower)
    )
    # A formula that merely reproduces the current value is a verification,
    # not a change proposal. Confirmation remains a separate parameter-row
    # action and must not be disguised as "apply suggestion".
    if same_value and same_tolerance:
        return "informational"
    return "available"


def _suggestion_has_effective_change(
    current: dict[str, Any],
    mode: str,
    suggested_value: Any,
    upper: Any,
    lower: Any,
) -> bool:
    value_changed = mode in {"value", "value_and_tolerance"} and not _equal(current.get("value"), suggested_value)
    tolerance_changed = mode in {"tolerance", "value_and_tolerance"} and (
        not _equal(current.get("tolerance_upper"), upper)
        or not _equal(current.get("tolerance_lower"), lower)
    )
    return value_changed or tolerance_changed


def _target_state(parameters: dict[str, Any], target: str) -> dict[str, Any]:
    if target.startswith("load_points."):
        parts = target.split(".")
        if len(parts) == 3:
            label, field = parts[1], parts[2]
            for point in parameters.get("load_points") or []:
                if str(point.get("label") or "").upper() == label.upper():
                    return {
                        "value": point.get(field),
                        "tolerance_upper": point.get("load_tolerance_upper"),
                        "tolerance_lower": point.get("load_tolerance_lower"),
                        "unit": point.get(f"{field}_unit"),
                        "need_human_review": point.get("need_human_review"),
                        "last_applied_suggestion_id": point.get("last_applied_suggestion_id"),
                    }
        return {}
    item = parameters.get(target)
    return dict(item) if isinstance(item, dict) else {"value": item}


def _parameter_dependency_value(value: Any) -> Any:
    if isinstance(value, dict):
        parameter_keys = ("value", "tolerance_upper", "tolerance_lower")
        load_point_keys = (
            "load_point_id", "label", "height", "force", "height_unit", "force_unit",
            "load_tolerance_upper", "load_tolerance_lower", "load_tolerance_percent", "test_height_type",
        )
        keys = parameter_keys if any(key in value for key in parameter_keys) else load_point_keys
        return {key: _parameter_dependency_value(value.get(key)) for key in keys if key in value}
    if isinstance(value, list):
        return [_parameter_dependency_value(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _deduplicate_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in suggestions:
        signature = json.dumps({
            "target_field": item.get("target_field"),
            "suggested_value": item.get("suggested_value"),
            "suggested_tolerance_upper": item.get("suggested_tolerance_upper"),
            "suggested_tolerance_lower": item.get("suggested_tolerance_lower"),
            "application_mode": item.get("application_mode"),
        }, ensure_ascii=False, sort_keys=True, default=str)
        existing = selected.get(signature)
        if existing is None:
            selected[signature] = item
            order.append(signature)
            continue
        existing.setdefault("supporting_sources", [existing.get("source")])
        if item.get("source") not in existing["supporting_sources"]:
            existing["supporting_sources"].append(item.get("source"))
        if item.get("status") == "available" and existing.get("status") == "informational":
            # A formula may already match a confirmed parameter while the
            # corresponding standard result still needs explicit adoption.
            existing["status"] = "available"
        existing_indexes = existing.setdefault("standardization_result_indexes", [])
        for result_index in item.get("standardization_result_indexes") or []:
            if result_index not in existing_indexes:
                existing_indexes.append(result_index)
    return [selected[key] for key in order]


def _mark_conflicts(suggestions: list[dict[str, Any]]) -> None:
    by_target: dict[str, list[dict[str, Any]]] = {}
    for item in suggestions:
        if item.get("status") != "available" or item.get("application_mode") == "none":
            continue
        by_target.setdefault(str(item.get("target_field") or ""), []).append(item)
    for group in by_target.values():
        if len(group) > 1:
            for item in group:
                item["status"] = "conflict"


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        return abs(float(left) - float(right)) <= 1e-9
    return left == right


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
