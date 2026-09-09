from __future__ import annotations

import math
from typing import Any


def build_solidworks_command(
    generation_id: str,
    parameter_package: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    """Translate the frozen review snapshot into SolidWorks' command format."""

    try:
        task_id = int(str(generation_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("SolidWorks TaskId must be a numeric generation id.") from exc
    if not 1_000_000_000 <= task_id <= 9_999_999_999:
        raise ValueError("SolidWorks TaskId must be a positive 10-digit Long value.")

    generation_parameters = parameter_package.get("generation_parameters") or {}
    spring_parameters = generation_parameters.get("spring_parameters") or {}
    load_points = generation_parameters.get("load_points") or []
    source = parameter_package.get("source") or {}

    values = {
        field: _parameter_value(spring_parameters.get(field))
        for field in (
            "wire_diameter",
            "mean_diameter",
            "free_length",
            "total_coils",
            "handedness",
            "material",
        )
    }
    load_values = _load_point_values(load_points)
    solid_height = _review_parameter_value(review, "solid_height")
    handedness = _solidworks_handedness(values["handedness"])
    technical_text = str(generation_parameters.get("technical_requirements_text") or "")

    model_parameters = {
        "线径": values["wire_diameter"],
        "中径": values["mean_diameter"],
        "自由高度": values["free_length"],
        "圈数": values["total_coils"],
        "压并高度Hb": solid_height,
        "工作高度H1": load_values["F1"]["height"],
        "工作高度H2": load_values["F2"]["height"],
    }
    extra_properties = {
        "技术要求": technical_text,
        "材料": values["material"],
        "旋向": handedness,
        "压并高度Hb": solid_height,
        "工作高度H1": load_values["F1"]["height"],
        "工作高度H2": load_values["F2"]["height"],
        "Fb": load_values["Fb"]["force"],
        "F1": load_values["F1"]["force"],
        "F2": load_values["F2"]["force"],
    }
    spring_label = str(source.get("spring_type_label") or "压缩弹簧")
    return {
        "TaskId": task_id,
        "models": [
            {
                "modelId": None,
                "modelName": str(source.get("drawing_name") or spring_label),
                "modelLabel": spring_label,
                "materialCode": None,
                "modelParameters": model_parameters,
                "customProperties": {"旋向": handedness},
                "extraProperties": extra_properties,
            }
        ],
    }


def _parameter_value(item: Any) -> Any | None:
    if not isinstance(item, dict):
        return None
    return _finite_or_text(item.get("value"))


def _review_parameter_value(review: dict[str, Any], field: str) -> Any | None:
    parameters = review.get("spring_parameters") or {}
    item = parameters.get(field) if isinstance(parameters, dict) else None
    if not isinstance(item, dict) or item.get("need_human_review"):
        return None
    return _finite_or_text(item.get("value"))


def _load_point_values(load_points: Any) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {
        "Fb": {"height": None, "force": None},
        "F1": {"height": None, "force": None},
        "F2": {"height": None, "force": None},
    }
    if not isinstance(load_points, list):
        return result
    for item in load_points:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip().casefold()
        normalized_label = "Fb" if label == "fb" else label.upper()
        if normalized_label not in result:
            continue
        height = item.get("height") if isinstance(item.get("height"), dict) else {}
        force = item.get("force") if isinstance(item.get("force"), dict) else {}
        result[normalized_label] = {
            "height": _finite_number(height.get("value")),
            "force": _finite_number(force.get("value")),
        }
    return result


def _solidworks_handedness(value: Any) -> str | None:
    if value == "left":
        return "左旋"
    if value == "right":
        return "右旋"
    return None


def _finite_or_text(value: Any) -> Any | None:
    number = _finite_number(value)
    if number is not None:
        return number
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 3)
