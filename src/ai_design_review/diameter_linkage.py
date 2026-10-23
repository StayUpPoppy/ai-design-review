"""Explicit diameter edits keep one diameter and the wire diameter fixed.

Recognition completion remains conservative until a user activates this rule.
The browser mirrors this small state machine; shared fixtures check both sides.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .standardizers.calculation_state import LENGTH_UNITS, number

VERSION = "compression-diameters/v1"
DIAMETERS = ("outer_diameter", "inner_diameter", "mean_diameter")
GROUP = ("wire_diameter", *DIAMETERS)


def supported(review: dict[str, Any]) -> bool:
    if (review.get("drawing_summary") or {}).get("spring_type") != "compression_spring":
        return False
    features = review.get("spring_features") or {}
    for field, allowed in (("spring_shape", {"cylindrical", "cylinder", "圆柱"}),
                           ("wire_section", {"round", "circular", "圆形", "圆截面"})):
        value = features.get(field) or {}
        value = value.get("value") if isinstance(value, dict) else value
        if value and value not in {"unknown", "unknown_shape", "unknown_section"} and value not in allowed:
            return False
    return True


def group_state(review: dict[str, Any]) -> dict[str, Any]:
    parameters = review.get("spring_parameters") or {}
    return {"parameters": {f: deepcopy(parameters.get(f)) for f in GROUP},
            "linkage": deepcopy(review.get("diameter_linkage")),
            "manual_confirmations": {k: deepcopy(v) for k, v in (review.get("manual_confirmations") or {}).items() if any(k == f or k.endswith("_" + f) or isinstance(v, dict) and v.get("target_field") == f for f in GROUP)}}


def _factor(item: dict[str, Any]) -> float | None:
    return LENGTH_UNITS.get(str(item.get("unit") or "mm").strip().lower())


def calculate(parameters: dict[str, Any], driver: str) -> dict[str, Any]:
    wire, base = parameters.get("wire_diameter") or {}, parameters.get(driver) or {}
    inputs = {f: {"value": (parameters.get(f) or {}).get("value"),
                  "unit": (parameters.get(f) or {}).get("unit") or "mm"} for f in ("wire_diameter", driver)}
    d, value, df, vf = number(wire.get("value")), number(base.get("value")), _factor(wire), _factor(base)
    reason = ""
    if d is None or d <= 0 or df is None or wire.get("derived_value_stale"):
        reason = "三径联动需要有效线径，请先核对线径。"
    elif value is None or value <= 0 or vf is None:
        reason = "请输入有效的直径正数。"
    elif any(_factor(parameters.get(f) or {}) is None for f in DIAMETERS):
        reason = "三径单位无法换算，请核对单位。"
    else:
        d, value = d * df, value * vf
        mean = value - d if driver == "outer_diameter" else value + d if driver == "inner_diameter" else value
        values = {"outer_diameter": mean + d, "inner_diameter": mean - d, "mean_diameter": mean}
        if any(number(v) is None or v <= 0 or round(v / _factor(parameters.get(f) or {}), 4 if _factor(parameters.get(f) or {}) == 1 else 8) <= 0 for f, v in values.items()):
            reason = "直径关系无效，需满足中径大于线径、内径大于0。"
        else:
            return {"inputs": inputs, "values_mm": values, "status": "calculated", "reason": ""}
    return {"inputs": inputs, "values_mm": {}, "status": "invalid", "reason": reason}


def apply_diameter_linkage(review: dict[str, Any], edited_field: str | None = None) -> dict[str, Any]:
    previous = review.get("diameter_linkage") or {}
    driver = edited_field if edited_field in DIAMETERS else previous.get("driver_field")
    if not supported(review) or driver not in DIAMETERS:
        return {"changed_fields": [], "before": group_state(review)}
    parameters = review.setdefault("spring_parameters", {})
    before = group_state(review)
    calculation = calculate(parameters, driver)
    changed_input = previous.get("driver_field") != driver or previous.get("inputs") != calculation["inputs"] or previous.get("status") != calculation["status"]
    original = previous.get("original_parameters") or deepcopy(before["parameters"])
    review["diameter_linkage"] = {"version": VERSION, "driver_field": driver,
                                  "inputs": calculation["inputs"], "status": calculation["status"],
                                  "reason": calculation["reason"], "original_parameters": original}
    wire = parameters.get("wire_diameter") or {}
    wire_sources = wire.get("source") or []
    wire_sources = wire_sources if isinstance(wire_sources, list) else [wire_sources]
    if "formula_calculation" in wire_sources or "derived" in wire_sources:
        wire["source"] = ["human_edited"] if edited_field == "wire_diameter" else ["diameter_linkage_fixed_input"]
        wire["accuracy_value_source"] = "human" if edited_field == "wire_diameter" else "system"
        for key in ("source_fields", "formula", "formula_calculation_kind", "formula_calculation_inputs"):
            wire.pop(key, None)
    changed = []
    for field in DIAMETERS:
        item = parameters.setdefault(field, {"value": None, "unit": "mm"})
        old = deepcopy(item)
        item["diameter_linkage_managed"] = True
        if calculation["status"] == "calculated":
            if field != driver:
                factor = _factor(item)
                if factor is None:
                    item["unit"], factor = "mm", 1
                value = calculation["values_mm"][field] / factor
                value = round(value, 4 if factor == 1 else 8)
                item["value"] = value
                item["source"] = ["formula_calculation", "diameter_linkage"]
                item["source_fields"] = [driver, "wire_diameter"]
                item["formula"] = _formula(driver, field)
                item["evidence"] = "联动计算：" + item["formula"] + "。"
                item["formula_calculation_kind"] = "diameter_linkage"
                item["formula_calculation_inputs"] = deepcopy(calculation["inputs"])
                item["accuracy_value_source"] = "system"
            elif edited_field in DIAMETERS:
                item["source"] = ["human_edited", "diameter_linkage_driver"]
                item["accuracy_value_source"] = "human"
                item["evidence"] = "人工修改直径，按当前线径联动。"
                for key in ("source_fields", "formula", "formula_calculation_kind", "formula_calculation_inputs"):
                    item.pop(key, None)
            for key in ("diameter_linkage_error", "formula_recommendation_stale", "formula_recalculation_candidate"):
                item.pop(key, None)
            item["derived_value_stale"] = False
        else:
            item["derived_value_stale"] = True
            item["diameter_linkage_error"] = calculation["reason"]
        if changed_input or old.get("value") != item.get("value") or bool(old.get("derived_value_stale")) != bool(item.get("derived_value_stale")):
            item["need_human_review"] = True
            item.pop("confirmation_snapshot", None)
            _revoke(review, field)
            changed.append(field)
    if changed:
        review["derived_parameters_stale"] = True
        review["parameter_reasonableness_stale"] = True
        for row in review.get("standardization_results") or []:
            if row.get("status") in {"suggested", "llm_suggested", "human_confirmed"}:
                row["status"], row["need_human_review"] = "stale", True
    return {"changed_fields": changed, "before": before}


def _formula(driver: str, target: str) -> str:
    return {("outer_diameter", "mean_diameter"): "Dm = Do - d",
            ("outer_diameter", "inner_diameter"): "Di = Do - 2d",
            ("inner_diameter", "mean_diameter"): "Dm = Di + d",
            ("inner_diameter", "outer_diameter"): "Do = Di + 2d",
            ("mean_diameter", "outer_diameter"): "Do = Dm + d",
            ("mean_diameter", "inner_diameter"): "Di = Dm - d"}.get((driver, target), "")


def _revoke(review: dict[str, Any], field: str) -> None:
    for key, entry in (review.get("manual_confirmations") or {}).items():
        if isinstance(entry, dict) and (key == field or key.endswith("_" + field) or entry.get("target_field") == field):
            entry["confirmed"] = False
            entry["revoked_reason"] = "diameter_linkage_changed"
