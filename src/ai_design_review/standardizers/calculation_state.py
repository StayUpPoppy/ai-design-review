"""Small provenance and snapshot helpers shared by compression calculations."""
from __future__ import annotations

import math
import re
from typing import Any

LENGTH_UNITS = {"mm": 1, "毫米": 1, "cm": 10, "m": 1000, "in": 25.4, "inch": 25.4, "英寸": 25.4}


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or isinstance(value, str) and not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value.strip()):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def sources(item: Any) -> list[str]:
    values = item.get("source", []) if isinstance(item, dict) else []
    return [str(v).lower() for v in (values if isinstance(values, list) else [values])]


def human_override(item: Any) -> bool:
    return isinstance(item, dict) and (bool(item.get("human_modified")) or any(s.startswith("human") and s != "human_confirmed" or s in {"manual", "manual_input", "standardization_chat", "ai_chat"} for s in sources(item)))


def parameter_current(parameters: dict[str, Any], field: str, path: tuple[str, ...] = ()) -> bool:
    if field in path:
        return False
    item = parameters.get(field)
    if not isinstance(item, dict):
        return True
    if item.get("derived_value_stale") or item.get("formula_recommendation_stale") and not human_override(item):
        return False
    if human_override(item) or not any(s in {"formula_calculation", "derived"} for s in sources(item)):
        return True
    for parent in item.get("source_fields", []):
        value = parameters.get(parent)
        raw = value.get("value") if isinstance(value, dict) else value
        if raw in (None, "") or not parameter_current(parameters, parent, (*path, field)):
            return False
    return True


def solid_height_kind(item: Any) -> str:
    if not isinstance(item, dict):
        return "unknown" if item not in (None, "") else "missing"
    if human_override(item):
        return "input_height"
    if item.get("value_kind") in {"reference_limit", "input_height", "nominal_estimate"}:
        return item["value_kind"]
    if item.get("formula_calculation_kind") == "nominal_solid_height":
        return "nominal_estimate"
    if re.search(r"Hb.*dmax", str(item.get("formula", "")), re.I) or re.search(r"压并高度上限|Hb\s*[≤<]", str(item.get("evidence", ""))):
        return "reference_limit"
    if item.get("formula_calculation_kind") == "solid_height" or any(s in {"formula_calculation", "derived"} or s.endswith("formula_suggestion_applied") for s in sources(item)):
        return "reference_limit"
    if item.get("value") in (None, "") and not item.get("derived_value_stale") and not any(s.startswith(("human", "manual")) for s in sources(item)):
        return "missing"
    if sources(item) and any(s.startswith(("qwen", "human", "manual", "vision", "drawing", "ocr")) for s in sources(item)):
        return "input_height"
    return "missing" if item.get("value") in (None, "") else "unknown"


def same_inputs(old: Any, current: dict[str, Any]) -> bool:
    # A result-version bump does not change the physical book-table model.
    return isinstance(old, dict) and all(old.get(k) == v for k, v in current.items() if k not in {"model_version", "model_id"})


def preserve_candidate(item: dict[str, Any], calculation: dict[str, Any]) -> None:
    recorded = item.get("formula_calculation_inputs")
    stale = calculation.get("value") is None or not same_inputs(recorded, calculation["inputs"])
    item.update(derived_value_stale=stale, formula_recommendation_stale=stale)
    if stale:
        item["formula_recalculation_candidate"] = calculation
        item["formula_calculation_reason"] = "计算依据已变化或无法验证，请应用新候选值后重新确认"
    else:
        item.pop("formula_recalculation_candidate", None)
        item.pop("formula_calculation_reason", None)
