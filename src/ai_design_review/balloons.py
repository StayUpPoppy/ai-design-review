from __future__ import annotations

from typing import Any


FIELD_LABELS = {
    "material": "材料",
    "wire_diameter": "线径",
    "outer_diameter": "外径",
    "free_length": "自由长度",
    "total_coils": "总圈数",
    "active_coils": "有效圈数",
    "handedness": "旋向",
    "heat_treatment": "热处理",
    "surface_requirement": "表面/外观",
    "salt_spray": "盐雾",
    "environmental": "环保要求",
    "lifetime_test": "寿命测试",
}


def generate_balloons(
    spring_parameters: dict[str, Any],
    technical_requirements: list[dict[str, Any]],
    review_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    balloons: list[dict[str, Any]] = []
    status_by_field = _status_by_field(review_results)

    for field, param in spring_parameters.items():
        if field == "load_points":
            for item in param:
                balloons.append(_load_point_balloon(len(balloons) + 1, item))
            continue
        if not isinstance(param, dict) or param.get("value") in (None, ""):
            continue
        balloons.append(_field_balloon(len(balloons) + 1, field, param, status_by_field))

    for item in technical_requirements:
        balloons.append(_tech_balloon(len(balloons) + 1, item, status_by_field))

    return balloons


def _field_balloon(index: int, field: str, param: dict[str, Any], status_by_field: dict[str, str]) -> dict[str, Any]:
    return {
        "bubble_id": f"B{index:02d}",
        "field": field,
        "label": FIELD_LABELS.get(field, field),
        "value": _format_value(param),
        "status": status_by_field.get(field, "need_review" if param.get("need_human_review") else "pass"),
        "page": param.get("page", 1),
        "position": _position(param.get("position")),
        "suggested_region": param.get("suggested_region", ""),
        "evidence": param.get("evidence", ""),
        "message": "需要人工确认" if param.get("need_human_review") else "识别结果可作为审查候选",
    }


def _load_point_balloon(index: int, item: dict[str, Any]) -> dict[str, Any]:
    label = item.get("label") or f"F{index}"
    return {
        "bubble_id": f"B{index:02d}",
        "field": "load_point",
        "label": f"载荷测试点 {label}",
        "value": f"{item.get('height')}mm / {item.get('force')}N±{item.get('force_tolerance_percent')}%",
        "status": "need_review" if item.get("need_human_review") else "pass",
        "page": item.get("page", 1),
        "position": _position(item.get("position")),
        "suggested_region": item.get("suggested_region", "主视图载荷标注"),
        "evidence": item.get("evidence", ""),
        "message": "载荷测试点需与原图和检验标准复核",
    }


def _tech_balloon(index: int, item: dict[str, Any], status_by_field: dict[str, str]) -> dict[str, Any]:
    field = item.get("type", "technical_requirement")
    return {
        "bubble_id": f"B{index:02d}",
        "field": field,
        "label": FIELD_LABELS.get(field, "技术要求"),
        "value": item.get("content", ""),
        "status": status_by_field.get(field, "need_review" if item.get("need_human_review") else "pass"),
        "page": item.get("page", 1),
        "position": _position(item.get("position")),
        "suggested_region": item.get("suggested_region", "技术要求区域"),
        "evidence": item.get("evidence", ""),
        "message": "技术要求需进入工艺/质量流转",
    }


def _format_value(param: dict[str, Any]) -> str:
    value = param.get("value")
    unit = param.get("unit") or ""
    upper = param.get("tolerance_upper")
    lower = param.get("tolerance_lower")
    text = f"{value}{unit}"
    if upper is not None and lower is not None:
        if abs(float(upper) + float(lower)) < 1e-9 and abs(float(upper)) == abs(float(lower)):
            text += f" ±{abs(float(upper)):g}"
        else:
            text += f" {float(upper):g}/{float(lower):g}"
    return text


def _position(position: Any) -> dict[str, Any]:
    if isinstance(position, dict):
        return {
            "x": position.get("x"),
            "y": position.get("y"),
            "width": position.get("width"),
            "height": position.get("height"),
            "coordinate_type": position.get("coordinate_type", "unknown"),
        }
    return {
        "x": None,
        "y": None,
        "width": None,
        "height": None,
        "coordinate_type": "unknown",
    }


def _status_by_field(review_results: list[dict[str, Any]]) -> dict[str, str]:
    priority = {"fail": 5, "missing": 4, "need_review": 3, "warning": 2, "pass": 1}
    mapped: dict[str, str] = {}
    for result in review_results:
        status = result.get("status", "need_review")
        for field in result.get("related_fields", []):
            if priority.get(status, 0) > priority.get(mapped.get(field, ""), 0):
                mapped[field] = status
    return mapped
