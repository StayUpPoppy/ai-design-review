from __future__ import annotations

from math import isfinite
from typing import Any

from .end_conditions import (
    END_GRINDING_GROUND,
    END_GRINDING_NOT_GROUND,
    END_TYPE_NOT_TIGHT,
    END_TYPE_TIGHT,
    normalize_end_grinding,
    normalize_end_type,
)


GENERATION_SCHEMA_VERSION = "spring_generation_parameters/v1"
COMPRESSION_GENERATION_INPUT_FIELDS = (
    "wire_diameter",
    "mean_diameter",
    "free_length",
    "total_coils",
    "active_coils",
    "handedness",
    "end_grinding",
    "end_coils_closed",
)
COMPRESSION_GENERATION_DEFAULTS: dict[str, int | float] = {
    "wire_diameter": 3.0,
    "mean_diameter": 23.0,
    "free_length": 45.0,
    "total_coils": 10,
    "active_coils": 8,
    "end_grinding": 1,
    "end_coils_closed": 1,
}
COMPRESSION_GENERATION_UNITS: dict[str, str | None] = {
    "wire_diameter": "mm",
    "mean_diameter": "mm",
    "free_length": "mm",
    "total_coils": None,
    "active_coils": None,
    "handedness": None,
    "end_grinding": None,
    "end_coils_closed": None,
}
COMPRESSION_GENERATION_LABELS = {
    "wire_diameter": "线径",
    "mean_diameter": "中径",
    "free_length": "自由长度",
    "total_coils": "总圈数",
    "active_coils": "有效圈数",
    "handedness": "旋向",
    "end_grinding": "两端磨削",
    "end_coils_closed": "端圈压并",
}


def apply_generation_defaults(review: dict[str, Any]) -> list[str]:
    """Add missing protocol defaults as pending review values.

    The review model keeps its existing Chinese/internal end-condition fields.
    Only the generation export translates them to the frozen SolidWorks names.
    """

    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "")
    if spring_type != "compression_spring":
        return []
    parameters = review.setdefault("spring_parameters", {})
    if not isinstance(parameters, dict):
        return []

    applied: list[str] = []
    for field, default in COMPRESSION_GENERATION_DEFAULTS.items():
        if generation_source_item(parameters, field) is not None:
            continue
        internal_field, internal_value = _default_internal_value(field, default)
        existing = parameters.get(internal_field)
        item = dict(existing) if isinstance(existing, dict) else {}
        item.update(
            {
                "value": internal_value,
                "unit": COMPRESSION_GENERATION_UNITS[field],
                "source": ["solidworks_protocol_default"],
                "default_source": GENERATION_SCHEMA_VERSION,
                "need_human_review": True,
            }
        )
        parameters[internal_field] = item
        applied.append(field)
    return applied


def generation_source_item(parameters: dict[str, Any], field: str) -> dict[str, Any] | None:
    if field == "mean_diameter":
        direct = _raw_parameter_item(parameters, "mean_diameter")
        if direct is not None:
            return direct
        return _derived_mean_diameter_item(parameters)
    if field == "end_coils_closed":
        direct = parameters.get("end_coils_closed")
        if isinstance(direct, dict) and direct.get("value") not in (None, ""):
            return direct
        legacy = parameters.get("end_type")
        if isinstance(legacy, dict) and legacy.get("value") not in (None, ""):
            return legacy
        return None
    return _raw_parameter_item(parameters, field)


def generation_parameter_state(parameters: dict[str, Any], field: str) -> str:
    item = generation_source_item(parameters, field)
    if item is None:
        return "missing"
    if item.get("need_human_review"):
        return "pending"
    try:
        normalize_generation_value(field, item.get("value"))
    except ValueError:
        return "invalid"
    return "confirmed"


def normalize_generation_value(field: str, value: Any) -> float | int | str:
    if field in {"wire_diameter", "mean_diameter", "free_length"}:
        number = _finite_number(value, field)
        if number <= 0:
            raise ValueError(f"{field} must be greater than zero")
        return round(number, 3)
    if field in {"total_coils", "active_coils"}:
        number = _finite_number(value, field)
        if number <= 0 or not number.is_integer():
            raise ValueError(f"{field} must be a positive integer")
        return int(number)
    if field == "handedness":
        normalized = _normalized_text(value)
        if normalized in {"right", "right_hand", "r", "右旋"}:
            return "right"
        if normalized in {"left", "left_hand", "l", "左旋"}:
            return "left"
        raise ValueError("handedness must be right or left")
    if field == "end_grinding":
        binary = _binary_value(value)
        if binary is not None:
            return binary
        normalized = normalize_end_grinding(value)
        if normalized == END_GRINDING_GROUND:
            return 1
        if normalized == END_GRINDING_NOT_GROUND:
            return 0
        raise ValueError("end_grinding must be 0 or 1")
    if field == "end_coils_closed":
        binary = _binary_value(value)
        if binary is not None:
            return binary
        text = _normalized_text(value)
        if text in {"closed_and_ground", "closed_and_unground", "closed_ground"}:
            return 1
        normalized = normalize_end_type(value)
        if normalized == END_TYPE_TIGHT:
            return 1
        if normalized == END_TYPE_NOT_TIGHT:
            return 0
        raise ValueError("end_coils_closed must be 0 or 1")
    raise ValueError(f"Unsupported generation field: {field}")


def export_generation_parameters(parameters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    exported: dict[str, dict[str, Any]] = {}
    for field in COMPRESSION_GENERATION_INPUT_FIELDS:
        item = generation_source_item(parameters, field)
        if item is None or item.get("need_human_review"):
            continue
        try:
            value = normalize_generation_value(field, item.get("value"))
        except ValueError:
            continue
        exported[field] = {
            "label": COMPRESSION_GENERATION_LABELS[field],
            "value": value,
            "unit": COMPRESSION_GENERATION_UNITS[field],
            "tolerance_upper": item.get("tolerance_upper"),
            "tolerance_lower": item.get("tolerance_lower"),
            "confirmation_source": "human_confirmed",
        }
    return exported


def validate_generation_parameters(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    normalized: dict[str, float | int | str] = {}
    for field in COMPRESSION_GENERATION_INPUT_FIELDS:
        item = generation_source_item(parameters, field)
        if item is None or item.get("need_human_review"):
            continue
        try:
            normalized[field] = normalize_generation_value(field, item.get("value"))
        except ValueError as exc:
            issues.append(_contract_issue(field, str(exc)))

    wire = normalized.get("wire_diameter")
    mean = normalized.get("mean_diameter")
    if isinstance(wire, (int, float)) and isinstance(mean, (int, float)) and mean <= wire:
        issues.append(_contract_issue("mean_diameter", "中径必须大于线径，确保计算内径大于零。"))
    total = normalized.get("total_coils")
    active = normalized.get("active_coils")
    if isinstance(total, int) and isinstance(active, int) and active > total:
        issues.append(_contract_issue("active_coils", "有效圈数不能大于总圈数。"))
    return issues


def _default_internal_value(field: str, value: int | float) -> tuple[str, Any]:
    if field == "end_coils_closed":
        return "end_type", END_TYPE_TIGHT if value == 1 else END_TYPE_NOT_TIGHT
    if field == "end_grinding":
        return "end_grinding", END_GRINDING_GROUND if value == 1 else END_GRINDING_NOT_GROUND
    return field, value


def _raw_parameter_item(parameters: dict[str, Any], field: str) -> dict[str, Any] | None:
    item = parameters.get(field)
    if not isinstance(item, dict) or item.get("value") in (None, ""):
        return None
    return item


def _derived_mean_diameter_item(parameters: dict[str, Any]) -> dict[str, Any] | None:
    wire = _raw_parameter_item(parameters, "wire_diameter")
    if wire is None:
        return None
    try:
        wire_value = _finite_number(wire.get("value"), "wire_diameter")
    except ValueError:
        return None

    for diameter_field, operation in (
        ("outer_diameter", lambda diameter: diameter - wire_value),
        ("inner_diameter", lambda diameter: diameter + wire_value),
    ):
        diameter = _raw_parameter_item(parameters, diameter_field)
        if diameter is None:
            continue
        try:
            diameter_value = _finite_number(diameter.get("value"), diameter_field)
        except ValueError:
            continue
        return {
            "value": round(operation(diameter_value), 3),
            "unit": "mm",
            "source": ["derived", f"{diameter_field}_and_wire_diameter"],
            "source_fields": [diameter_field, "wire_diameter"],
            "formula": (
                "outer_diameter - wire_diameter"
                if diameter_field == "outer_diameter"
                else "inner_diameter + wire_diameter"
            ),
            "need_human_review": bool(
                diameter.get("need_human_review") or wire.get("need_human_review")
            ),
        }
    return None


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _binary_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and isfinite(float(value)) and float(value) in {0.0, 1.0}:
        return int(value)
    text = str(value).strip()
    if text in {"0", "1"}:
        return int(text)
    return None


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "")


def _contract_issue(field: str, reason: str) -> dict[str, Any]:
    return {
        "rule_id": "SW-CONTRACT-V1",
        "field": field,
        "fields": [field],
        "label": COMPRESSION_GENERATION_LABELS[field],
        "severity": "blocked",
        "message": reason,
        "reason": reason,
    }
