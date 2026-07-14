from __future__ import annotations

from collections import defaultdict
from typing import Any


SOURCE_PRIORITY = {
    "human": 1.0,
    "manual": 0.98,
    "cad": 0.95,
    "dxf": 0.95,
    "dwg": 0.95,
    "dimension_role_ranker": 0.94,
    "werk24": 0.86,
    "qwen_vision": 0.88,
    "baidu_paddleocr_vl": 0.84,
    "baidu_ocr": 0.82,
    "pdf_text_layer": 0.8,
    "rapidocr": 0.78,
    "ocr": 0.78,
    "azure": 0.78,
    "paddle": 0.78,
    "vision": 0.62,
    "openai": 0.62,
    "inference": 0.45,
}


NORMALIZATION_KEYS = (
    "raw_value",
    "standard_value",
    "normalization_status",
    "normalization_source",
    "normalization_confidence",
    "normalization_reason",
)


def source_weight(source: str) -> float:
    lowered = source.lower()
    for key, weight in SOURCE_PRIORITY.items():
        if key in lowered:
            return weight
    return 0.5


def fuse_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    load_points: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for candidate in candidates:
        field = candidate.get("field")
        if not field:
            continue
        if field == "load_point":
            load_points.append(_normalize_load_point(candidate))
        else:
            grouped[field].append(candidate)

    fields: dict[str, dict[str, Any]] = {}
    for field, items in grouped.items():
        ordered = sorted(items, key=_candidate_score, reverse=True)
        selected = _merge_field(field, ordered)
        fields[field] = selected
        conflict = _detect_conflict(field, ordered)
        if conflict:
            conflicts.append(conflict)

    load_points = _merge_load_points(load_points, conflicts)

    return {
        "fields": fields,
        "load_points": load_points,
        "conflicts": conflicts,
    }


def _candidate_score(candidate: dict[str, Any]) -> float:
    confidence = float(candidate.get("confidence", 0) or 0)
    return confidence * _candidate_source_weight(candidate)


def _candidate_source_weight(candidate: dict[str, Any]) -> float:
    source = candidate.get("source", "")
    sources = source if isinstance(source, list) else [source]
    return max((source_weight(str(item)) for item in sources), default=0.5)


def _merge_field(field: str, ordered: list[dict[str, Any]]) -> dict[str, Any]:
    best = ordered[0]
    sources = [item.get("source", "unknown") for item in ordered]
    evidence = " | ".join(
        str(item.get("evidence", "")).strip()
        for item in ordered
        if item.get("evidence")
    )
    confidence = min(
        0.99,
        max(float(best.get("confidence", 0) or 0), _combined_confidence(ordered)),
    )

    merged = {
        "field": field,
        "value": best.get("value"),
        "unit": best.get("unit"),
        "tolerance_upper": best.get("tolerance_upper"),
        "tolerance_lower": best.get("tolerance_lower"),
        "source": sources,
        "evidence": evidence,
        "confidence": round(confidence, 3),
        "page": best.get("page", 1),
        "position": best.get("position"),
        "suggested_region": best.get("suggested_region", ""),
        "need_human_review": _needs_human_review(best, ordered),
    }
    for key in NORMALIZATION_KEYS:
        if key in best:
            merged[key] = best[key]
    return merged


def _normalize_load_point(candidate: dict[str, Any]) -> dict[str, Any]:
    value = dict(candidate.get("value") or {})
    return {
        "field": "load_point",
        "value": value,
        "source": [candidate.get("source", "unknown")],
        "evidence": candidate.get("evidence", ""),
        "confidence": float(candidate.get("confidence", 0) or 0),
        "page": candidate.get("page", 1),
        "position": candidate.get("position"),
        "suggested_region": candidate.get("suggested_region", ""),
        "need_human_review": _candidate_source_weight(candidate) < 0.98,
    }


def _merge_load_points(load_points: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate F1/F2 candidates emitted by multiple extraction engines."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, point in enumerate(load_points):
        label = str((point.get("value") or {}).get("label") or "").strip().upper()
        key = label or f"__unnamed_{index}"
        groups[key].append(point)

    merged = [_merge_load_point(label, points, conflicts) for label, points in groups.items()]
    return sorted(
        merged,
        key=lambda item: _number_or_default((item.get("value") or {}).get("height"), 999999),
        reverse=True,
    )


def _merge_load_point(
    label: str,
    points: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(points, key=_candidate_score, reverse=True)
    best = ordered[0]
    merged_value: dict[str, Any] = {}
    value_keys = (
        "label",
        "height",
        "height_unit",
        "force",
        "force_unit",
        "force_tolerance_percent",
        "load_tolerance_upper",
        "load_tolerance_lower",
        "load_tolerance_percent",
        "test_height_type",
    )
    for key in value_keys:
        merged_value[key] = _first_load_point_value(ordered, key)
    merged_value["label"] = label if not label.startswith("__unnamed_") else merged_value.get("label")
    merged_value["reference_only"] = all(bool((item.get("value") or {}).get("reference_only")) for item in ordered)

    for key, display_name in (("height", "height"), ("force", "force")):
        values = [_load_point_value(item, key) for item in ordered]
        values = [value for value in values if value not in (None, "")]
        if len(values) > 1 and any(not _values_close(values[0], value) for value in values[1:]):
            conflicts.append(
                {
                    "field": f"load_points.{label}.{key}",
                    "values": values,
                    "sources": _all_sources(ordered),
                    "message": f"Load point {label} has conflicting {display_name} values from multiple sources.",
                    "need_human_review": True,
                }
            )

    confidence = min(0.99, max(float(best.get("confidence", 0) or 0), _combined_confidence(ordered)))
    has_conflict = any(
        item.get("field", "").startswith(f"load_points.{label}.")
        for item in conflicts
    )
    return {
        "field": "load_point",
        "value": merged_value,
        "source": _all_sources(ordered),
        "evidence": _join_evidence(ordered),
        "confidence": round(confidence, 3),
        "page": best.get("page", 1),
        "position": best.get("position"),
        "suggested_region": best.get("suggested_region", ""),
        "need_human_review": has_conflict or _needs_human_review(best, ordered),
    }


def _first_load_point_value(points: list[dict[str, Any]], key: str) -> Any:
    for point in points:
        value = _load_point_value(point, key)
        if value not in (None, ""):
            return value
    return None


def _load_point_value(point: dict[str, Any], key: str) -> Any:
    return (point.get("value") or {}).get(key)


def _all_sources(items: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    for item in items:
        source = item.get("source", "unknown")
        raw_sources = source if isinstance(source, list) else [source]
        for value in raw_sources:
            text = str(value or "unknown")
            if text not in sources:
                sources.append(text)
    return sources


def _join_evidence(items: list[dict[str, Any]]) -> str:
    evidence: list[str] = []
    for item in items:
        value = str(item.get("evidence", "")).strip()
        if value and value not in evidence:
            evidence.append(value)
    return " | ".join(evidence)


def _number_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _combined_confidence(items: list[dict[str, Any]]) -> float:
    if len(items) == 1:
        return float(items[0].get("confidence", 0) or 0)
    score = 1.0
    for item in items[:3]:
        score *= 1 - min(0.95, _candidate_score(item))
    return 1 - score


def _needs_human_review(best: dict[str, Any], ordered: list[dict[str, Any]]) -> bool:
    confidence = float(best.get("confidence", 0) or 0)
    if _candidate_source_weight(best) >= 0.98 and confidence >= 0.95:
        return False
    if len(ordered) < 2:
        return True
    return confidence < 0.9


def _detect_conflict(field: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(items) < 2:
        return None
    values = [item.get("value") for item in items]
    first = values[0]
    for value in values[1:]:
        if not _values_close(first, value):
            return {
                "field": field,
                "values": values,
                "sources": [item.get("source", "unknown") for item in items],
                "message": f"{field} 多个来源识别结果不一致，需要人工确认。",
                "need_human_review": True,
            }
    return None


def _values_close(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-6
    return str(left).strip() == str(right).strip()
