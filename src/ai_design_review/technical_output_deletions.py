"""Output choices for technical notes; engineering inputs are never deleted here."""
from __future__ import annotations

import copy
from typing import Any


def technical_output_basis(review: dict[str, Any], source_key: str, fields: list[str], point_ids: list[str], *, body: str = "", scope: str = "") -> dict[str, Any]:
    if source_key.startswith("legacy:"):
        return {"body": body, "scope": scope}
    dependencies = {
        "auto:handedness": ["handedness"],
        "auto:coils": ["total_coils", "active_coils", "end_type", "end_coils_closed"],
        "auto:end": ["end_type", "end_coils_closed", "end_grinding"],
    }.get(source_key, fields)
    parameters = review.get("spring_parameters") or {}
    names = sorted(set(field for field in dependencies if not field.startswith("load_points.")))
    keys = ("value", "unit", "tolerance_upper", "tolerance_lower", "surface_location")
    inputs = [[field, {key: (parameters[field] if isinstance(parameters.get(field), dict) else {}).get(key) for key in keys}] for field in names]
    points = []
    for point_id in sorted(set(point_ids)):
        point = next((point for point in parameters.get("load_points") or [] if point.get("load_point_id") == point_id), {})
        snapshot = {key: point.get(key) for key in ("label", "height", "force", "load_tolerance_upper", "load_tolerance_lower", "load_tolerance_percent")}
        snapshot.update(height_unit=point.get("height_unit") or "mm", force_unit=point.get("force_unit") or "N")
        points.append([point_id, snapshot])
    return {"parameters": inputs, "load_points": points, "scope": scope}


def refresh_technical_output_deletions(review: dict[str, Any]) -> None:
    """Expire a choice after its actual inputs change, never on confirmation alone."""
    if "technical_output_deletions" not in review:
        return
    current = []
    records = review.get("technical_output_deletions")
    for item in records if isinstance(records, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("source_key"), str) or not isinstance(item.get("basis"), dict):
            continue
        key = item["source_key"]
        if not key.startswith(("auto:", "legacy:")):
            continue
        fields, points = item.get("fields") or [], item.get("load_point_ids") or []
        if not isinstance(fields, list) or not isinstance(points, list) or not all(isinstance(v, str) for v in [*fields, *points]):
            continue
        if key.startswith("auto:") and technical_output_basis(review, key, fields, points, scope=item["basis"].get("scope", "")) != item["basis"]:
            continue
        current.append(copy.deepcopy(item))
    review["technical_output_deletions"] = current


def technical_output_is_deleted(review: dict[str, Any], entry: dict[str, Any]) -> bool:
    # Compare with provenance/basis rebuilt by the generator, not client row IDs.
    records = review.get("technical_output_deletions")
    return any(isinstance(item, dict) and item.get("source_key") == entry["source_key"] and item.get("basis") == entry["basis"]
               for item in (records if isinstance(records, list) else []))
