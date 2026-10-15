"""Projection of recalculation candidates; never changes reviewed parameters."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .standardizers.calculation_state import human_override, number, same_inputs, solid_height_kind
from .standardizers.coil_counts import derive_active_coils
from .standardizers.compression import calculate_compression_solid_height
from .standardizers.design_checks import calculate_nominal_solid_height, calculate_pitch

FIELDS = ("pitch", "active_coils", "solid_height")


def calculations(review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    params = review.get("spring_parameters") or {}
    features = review.get("spring_features") or {}
    shadow = deepcopy(params)
    shadow.pop("active_coils", None)
    active = derive_active_coils("compression_spring", shadow).get("active_coils") or {}
    kind = solid_height_kind(params.get("solid_height"))
    return {
        "pitch": calculate_pitch(params, features),
        "active_coils": active,
        "solid_height": calculate_compression_solid_height(params) if kind == "reference_limit" else calculate_nominal_solid_height(params, features),
    }


def candidate_snapshots(review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (review.get("drawing_summary") or {}).get("spring_type") != "compression_spring":
        return {}
    params = review.get("spring_parameters") or {}
    result = {}
    for field, calc in calculations(review).items():
        item = params.get(field)
        if not isinstance(item, dict) or human_override(item):
            continue
        source = item.get("source") or []
        source = source if isinstance(source, list) else [source]
        kind = solid_height_kind(item) if field == "solid_height" else None
        formula_owned = ("company_active_coil_rule" in source if field == "active_coils" else
                         kind in {"nominal_estimate", "reference_limit"} if field == "solid_height" else
                         item.get("formula_calculation_kind") == "pitch")
        pending_candidate = item.get("formula_recalculation_candidate") or item.get("derived_value_stale") or item.get("formula_recommendation_stale")
        if not formula_owned or not (item.get("need_human_review") is False or pending_candidate):
            continue
        value = number(calc.get("value"))
        if value is None or value <= 0 or same_inputs(item.get("formula_calculation_inputs"), calc.get("inputs") or {}):
            continue
        result[field] = {
            "value": round(value, 4), "unit": calc.get("unit"), "formula": calc.get("formula") or "",
            "inputs": calc.get("inputs") or {}, "source_fields": calc.get("source_fields") or [],
            "basis": calc.get("basis") or "", "purpose": kind or field,
            "status": "estimated" if field == "solid_height" and kind == "nominal_estimate" else "calculated",
        }
    return result
