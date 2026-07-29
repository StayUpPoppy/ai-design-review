from __future__ import annotations

import re
from typing import Any

from ..end_conditions import END_TYPE_NOT_TIGHT, END_TYPE_TIGHT, normalize_end_type

COMPANY_ACTIVE_COIL_RULE = "COMPANY-ACTIVE-COILS-END-CONDITION-V2"
LEGACY_COMPANY_SIMPLE_ACTIVE_COIL_RULE = "COMPANY-SIMPLE-ACTIVE-COILS-V1"


def derive_active_coils(
    spring_type: str,
    spring_parameters: dict[str, Any],
    *,
    refresh_company_derived: bool = False,
) -> dict[str, Any]:
    """Derive active coils only from an explicit compression end condition.

    A drawing-recognized or manually entered active coil count remains the
    source of truth. This only supplies a derived value when it is absent.
    """
    existing = spring_parameters.get("active_coils")
    if _number(_param_value(spring_parameters, "active_coils")) is not None and not (
        refresh_company_derived and _can_refresh_company_derived(existing)
    ):
        return {}

    total = _number(_param_value(spring_parameters, "total_coils"))
    if total is None:
        return {}

    if spring_type == "compression_spring":
        end_type = normalize_end_type(_param_value(spring_parameters, "end_type"))
        if end_type == END_TYPE_NOT_TIGHT:
            value = total
            formula = "total_coils"
            basis = "端部形式为两端不并紧：有效圈数 = 总圈数。"
            source_fields = ["total_coils", "end_type"]
            support_coils = None
            support_source = None
        elif end_type == END_TYPE_TIGHT:
            support_coils = _number(_param_value(spring_parameters, "support_coils"))
            support_source = "drawing_or_manual"
            if support_coils is None:
                support_coils = 1.0
                support_source = "company_default_per_end"
            value = total - 2 * support_coils
            formula = "total_coils - 2 * support_coils"
            basis = (
                "端部形式为两端并紧：有效圈数 = 总圈数 - 2 × 单端支承圈数；"
                f"当前单端支承圈数为 {support_coils:g} 圈"
                + ("（公司默认值）。" if support_source == "company_default_per_end" else "。")
            )
            source_fields = ["total_coils", "end_type", "support_coils"]
        else:
            return {}
    elif spring_type in {"extension_spring", "torsion_spring"}:
        value = total
        formula = "total_coils"
        basis = "公司简易算法：拉伸弹簧/扭转弹簧有效圈数 = 本体总圈数。"
        source_fields = ["total_coils"]
        support_coils = None
        support_source = None
    else:
        return {}

    if value <= 0:
        return {}

    return {
        "active_coils": {
            "field": "active_coils",
            "value": _round(value),
            "unit": "turns",
            "source": ["derived", "company_active_coil_rule"],
            "formula": formula,
            "basis": basis,
            "rule_id": COMPANY_ACTIVE_COIL_RULE,
            "source_fields": source_fields,
            "confidence": 0.99,
            "need_human_review": spring_type == "compression_spring",
            "support_coils_per_end": _round(support_coils) if support_coils is not None else None,
            "support_coils_source": support_source,
        }
    }


def apply_company_simple_active_coils(spring_type: str, spring_parameters: dict[str, Any]) -> bool:
    """Populate the editable parameter with the end-condition fallback when valid.

    The same calculation is still available as a derived value for callers that
    standardize raw parameters directly. Workflow callers use this helper so a
    newly uploaded drawing shows the proposed active coil count immediately.
    """
    existing = spring_parameters.get("active_coils")
    derived = derive_active_coils(spring_type, spring_parameters, refresh_company_derived=True)
    item = derived.get("active_coils")
    if not item:
        if _can_refresh_company_derived(existing):
            spring_parameters["active_coils"] = _blank_company_derived_active_coils(existing)
            return True
        return False

    spring_parameters["active_coils"] = {
        "field": "active_coils",
        "value": item["value"],
        "unit": item["unit"],
        "tolerance_upper": None,
        "tolerance_lower": None,
        "source": ["company_active_coil_rule"],
        "evidence": item["basis"],
        "confidence": item["confidence"],
        "page": 1,
        "position": None,
        "suggested_region": "company_active_coil_rule",
        "need_human_review": item["need_human_review"],
        "derived_rule_id": item["rule_id"],
        "derived_formula": item["formula"],
        "source_fields": item["source_fields"],
        "support_coils_per_end": item["support_coils_per_end"],
        "support_coils_source": item["support_coils_source"],
    }
    return True


def _can_refresh_company_derived(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("derived_rule_id") not in {COMPANY_ACTIVE_COIL_RULE, LEGACY_COMPANY_SIMPLE_ACTIVE_COIL_RULE}:
        return False
    source = item.get("source", [])
    values = source if isinstance(source, list) else [source]
    return not any(str(value or "").lower().startswith("human") for value in values)


def _blank_company_derived_active_coils(existing: Any) -> dict[str, Any]:
    item = dict(existing) if isinstance(existing, dict) else {}
    item.update(
        {
            "field": "active_coils",
            "value": None,
            "unit": "turns",
            "source": [],
            "evidence": "端部形式未明确，系统不自动推导有效圈数。",
            "confidence": 0,
            "need_human_review": True,
            "derived_rule_id": None,
            "derived_formula": None,
            "source_fields": ["total_coils", "end_type"],
        }
    )
    return item


def _param_value(parameters: dict[str, Any], field: str) -> Any:
    item = parameters.get(field)
    return item.get("value") if isinstance(item, dict) else item


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    match = re.search(r"[-−]?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    return float(match.group(0).replace("−", "-"))


def _round(value: float) -> float | int:
    rounded = round(value, 4)
    return int(rounded) if float(rounded).is_integer() else rounded
