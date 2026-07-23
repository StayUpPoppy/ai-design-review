from __future__ import annotations

import re
from typing import Any


FORMULA_CALCULATION_SOURCE = "formula_calculation"
DIAMETER_COMPLETION_KIND = "diameter_completion"


def apply_formula_compression_diameter_completion(spring_parameters: dict[str, Any]) -> dict[str, Any]:
    """Complete missing or recognizer-inferred cylindrical spring diameters.

    A direct drawing value or human value is never replaced. Values already
    marked as inferred may be refreshed by the deterministic geometry formula.
    """
    applied_fields: list[str] = []
    calculations: dict[str, dict[str, Any]] = {}
    working = {
        field: dict(item) if isinstance(item, dict) else item
        for field, item in spring_parameters.items()
    }

    # Calculate wire first so outer/inner/mean can use a newly completed wire.
    for target in ("wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter"):
        existing = spring_parameters.get(target)
        if not _can_replace(existing):
            continue
        calculation = _calculation_for(target, _values(working))
        if not calculation or calculation["value"] is None or calculation["value"] <= 0:
            continue
        parameter = _formula_parameter(target, calculation)
        working[target] = parameter
        spring_parameters[target] = parameter
        applied_fields.append(target)
        calculations[target] = calculation

    return {"applied_fields": applied_fields, "calculations": calculations}


def _calculation_for(target: str, values: dict[str, float | None]) -> dict[str, Any] | None:
    outer = values["outer_diameter"]
    inner = values["inner_diameter"]
    mean = values["mean_diameter"]
    wire = values["wire_diameter"]

    if target == "wire_diameter" and outer is not None and inner is not None:
        return _calculation((outer - inner) / 2, "d = (Do - Di) / 2", ["outer_diameter", "inner_diameter"])
    if target == "outer_diameter":
        if inner is not None and wire is not None:
            return _calculation(inner + 2 * wire, "Do = Di + 2d", ["inner_diameter", "wire_diameter"])
        if mean is not None and wire is not None:
            return _calculation(mean + wire, "Do = D + d", ["mean_diameter", "wire_diameter"])
    if target == "inner_diameter":
        if outer is not None and wire is not None:
            return _calculation(outer - 2 * wire, "Di = Do - 2d", ["outer_diameter", "wire_diameter"])
        if mean is not None and wire is not None:
            return _calculation(mean - wire, "Di = D - d", ["mean_diameter", "wire_diameter"])
    if target == "mean_diameter":
        if outer is not None and inner is not None:
            return _calculation((outer + inner) / 2, "D = (Do + Di) / 2", ["outer_diameter", "inner_diameter"])
        if outer is not None and wire is not None:
            return _calculation(outer - wire, "D = Do - d", ["outer_diameter", "wire_diameter"])
        if inner is not None and wire is not None:
            return _calculation(inner + wire, "D = Di + d", ["inner_diameter", "wire_diameter"])
    return None


def _calculation(value: float, formula: str, source_fields: list[str]) -> dict[str, Any]:
    return {
        "value": _round(value),
        "formula": formula,
        "source_fields": source_fields,
        "basis": f"公式推导：{formula}。",
    }


def _formula_parameter(field: str, calculation: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": field,
        "value": calculation["value"],
        "unit": "mm",
        "tolerance_upper": None,
        "tolerance_lower": None,
        "source": [FORMULA_CALCULATION_SOURCE],
        "evidence": calculation["basis"],
        "confidence": 0.88,
        "page": 1,
        "position": None,
        "suggested_region": "formula_computed_diameter",
        "need_human_review": True,
        "formula": calculation["formula"],
        "source_fields": calculation["source_fields"],
        "formula_calculation_kind": DIAMETER_COMPLETION_KIND,
        "formula_calculation_status": "calculated",
    }


def _can_replace(item: Any) -> bool:
    if not isinstance(item, dict):
        return item in (None, "")
    if item.get("value") in (None, ""):
        return True
    sources = _source_values(item.get("source"))
    if any(source.startswith("human") or source in {"manual", "manual_input"} for source in sources):
        return False
    if FORMULA_CALCULATION_SOURCE in sources:
        return item.get("formula_calculation_kind") in (None, DIAMETER_COMPLETION_KIND)
    return _is_recognizer_inference(item) and not _has_direct_drawing_evidence(item)


def _is_recognizer_inference(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("evidence", "suggested_region"))
    return bool(re.search(r"(?:图纸未直接标注|由(?:内径|外径|中径|线径)|计算得出|公式推导|推导)", text))


def _has_direct_drawing_evidence(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("evidence", "suggested_region"))
    return bool(
        re.search(r"(?:图纸标注|(?<!未)(?<!非)直接标注)", text)
        or re.search(r"(?:外径|内径|中径|OD|ID|O\.D\.|I\.D\.)\s*[φΦØø]\s*\d", text, re.IGNORECASE)
    )


def _values(spring_parameters: dict[str, Any]) -> dict[str, float | None]:
    return {
        field: _number(_param_value(spring_parameters, field))
        for field in ("outer_diameter", "inner_diameter", "mean_diameter", "wire_diameter")
    }


def _param_value(parameters: dict[str, Any], field: str) -> Any:
    item = parameters.get(field)
    return item.get("value") if isinstance(item, dict) else item


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float | int:
    rounded = round(float(value), 4)
    return int(rounded) if rounded.is_integer() else rounded


def _source_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item or "").strip().lower() for item in values if item]
