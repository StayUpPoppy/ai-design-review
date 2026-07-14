from __future__ import annotations

import re
from typing import Any


COMPANY_SIMPLE_ACTIVE_COIL_RULE = "COMPANY-SIMPLE-ACTIVE-COILS-V1"


def derive_active_coils(spring_type: str, spring_parameters: dict[str, Any]) -> dict[str, Any]:
    """Apply the current company-level fallback for active coil count.

    A drawing-recognized or manually entered active coil count remains the
    source of truth. This only supplies a derived value when it is absent.
    """
    if _number(_param_value(spring_parameters, "active_coils")) is not None:
        return {}

    total = _number(_param_value(spring_parameters, "total_coils"))
    if total is None:
        return {}

    if spring_type == "compression_spring":
        value = total - 2
        formula = "total_coils - 2"
        basis = "公司简易算法：压缩弹簧有效圈数 = 总圈数 - 2。"
    elif spring_type in {"extension_spring", "torsion_spring"}:
        value = total
        formula = "total_coils"
        basis = "公司简易算法：拉伸弹簧/扭转弹簧有效圈数 = 本体总圈数。"
    else:
        return {}

    if value <= 0:
        return {}

    return {
        "active_coils": {
            "field": "active_coils",
            "value": _round(value),
            "unit": "turns",
            "source": ["derived", "company_simple_rule"],
            "formula": formula,
            "basis": basis,
            "rule_id": COMPANY_SIMPLE_ACTIVE_COIL_RULE,
            "source_fields": ["total_coils"],
            "confidence": 0.99,
            "need_human_review": False,
        }
    }


def apply_company_simple_active_coils(spring_type: str, spring_parameters: dict[str, Any]) -> bool:
    """Populate the editable parameter with the company fallback when absent.

    The same calculation is still available as a derived value for callers that
    standardize raw parameters directly. Workflow callers use this helper so a
    newly uploaded drawing shows the proposed active coil count immediately.
    """
    derived = derive_active_coils(spring_type, spring_parameters)
    item = derived.get("active_coils")
    if not item:
        return False

    spring_parameters["active_coils"] = {
        "field": "active_coils",
        "value": item["value"],
        "unit": item["unit"],
        "tolerance_upper": None,
        "tolerance_lower": None,
        "source": ["company_simple_rule"],
        "evidence": item["basis"],
        "confidence": item["confidence"],
        "page": 1,
        "position": None,
        "suggested_region": "company_simple_active_coils",
        "need_human_review": False,
        "derived_rule_id": item["rule_id"],
        "derived_formula": item["formula"],
        "source_fields": item["source_fields"],
    }
    return True


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
