from __future__ import annotations

from collections import defaultdict
from typing import Any


SOURCE_PRIORITY = {
    "human": 1.0,
    "manual": 0.98,
    "cad": 0.95,
    "dxf": 0.95,
    "dwg": 0.95,
    "werk24": 0.86,
    "ocr": 0.78,
    "azure": 0.78,
    "paddle": 0.78,
    "vision": 0.62,
    "openai": 0.62,
    "inference": 0.45,
}


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

    load_points = sorted(
        load_points,
        key=lambda item: item.get("value", {}).get("height", 999999),
        reverse=True,
    )

    return {
        "fields": fields,
        "load_points": load_points,
        "conflicts": conflicts,
    }


def _candidate_score(candidate: dict[str, Any]) -> float:
    confidence = float(candidate.get("confidence", 0) or 0)
    return confidence * source_weight(str(candidate.get("source", "")))


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

    return {
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
        "need_human_review": source_weight(str(candidate.get("source", ""))) < 0.98,
    }


def _combined_confidence(items: list[dict[str, Any]]) -> float:
    if len(items) == 1:
        return float(items[0].get("confidence", 0) or 0)
    score = 1.0
    for item in items[:3]:
        score *= 1 - min(0.95, _candidate_score(item))
    return 1 - score


def _needs_human_review(best: dict[str, Any], ordered: list[dict[str, Any]]) -> bool:
    source = str(best.get("source", ""))
    confidence = float(best.get("confidence", 0) or 0)
    if source_weight(source) >= 0.98 and confidence >= 0.95:
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

