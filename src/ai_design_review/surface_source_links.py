"""Associate converted surface notes with unchanged recognition sources.

The projection is pure: opening a legacy review never edits text/confirmation.
Client-provided source IDs are never evidence for an association.
"""
import math
import re
import unicodedata
from typing import Any

from .technical_requirements import technical_requirement_equivalence_key


def surface_source_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"^\d+\s*[.、)]\s*(?=[^\d\s])", "", text)
    text = re.sub(r"^(?:表面处理|表面處理|表面要求)\s*[:：]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(";；。").rstrip()


def surface_scope_key(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _scope(item: dict) -> str:
    return surface_scope_key(item.get("application_scope"))


def _page(item: dict) -> Any:
    return item.get("page") or 1


def _same_position(left: dict, right: dict) -> bool:
    a, b = left.get("position"), right.get("position")
    if not a or not b:
        return True
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if a.get("coordinate_type") != b.get("coordinate_type"):
        return False
    for key in ("x", "y", "width", "height"):
        x, y = a.get(key), b.get(key)
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return False
        if not math.isfinite(x) or not math.isfinite(y) or not math.isclose(x, y, rel_tol=0, abs_tol=1e-6):
            return False
    return True


def _original_keys(item: dict) -> set[str]:
    return {key for source in [item, *(item.get("recognition_aliases") or [])] if isinstance(source, dict)
            for field in ("original_content", "raw_content") if (key := surface_source_key(source.get(field)))}


def _converted(item: dict) -> bool:
    return item.get("type") == "surface" and isinstance(item.get("surface_mapping"), dict) and item["surface_mapping"].get("conversion_status") == "converted" and bool(_original_keys(item))


def surface_source_links(review: dict) -> dict:
    notes = [item for item in review.get("technical_requirements") or [] if isinstance(item, dict)]
    roots = [item for item in notes if item.get("requirement_id") and _converted(item)]
    targets: dict[str, list[str]] = {}
    suppressed = []
    for source in notes:
        source_id = source.get("requirement_id")
        if not source_id or _converted(source):
            continue
        origins = source.get("source") or []
        origins = origins if isinstance(origins, list) else [origins]
        if any(str(v) in {"human_edited", "human_filled", "manual", "ai_chat"} for v in origins):
            continue
        key = surface_source_key(source.get("content"))
        if not key or key != surface_source_key(source.get("original_content") or source.get("content")):
            continue
        matches = [root for root in roots if root["requirement_id"] != source_id and key in _original_keys(root)
                   and _page(root) == _page(source) and _scope(root) == _scope(source) and _same_position(root, source)]
        # Equivalent converted records form one display group. Different
        # translations/conditions are ambiguous and cannot absorb a raw note.
        groups = {technical_requirement_equivalence_key(root) for root in matches}
        if len(groups) != 1:
            continue
        target = matches[0]["requirement_id"]
        targets.setdefault(target, []).append(source_id)
        suppressed.append(source_id)
    return {"sources_by_target": targets, "suppressed_ids": suppressed}


def bind_surface_sources(review: dict) -> list[dict]:
    links = surface_source_links(review)
    changed = []
    for item in review.get("technical_requirements") or []:
        if not isinstance(item, dict) or not isinstance(item.get("surface_mapping"), dict):
            continue
        mapping = item["surface_mapping"]
        desired = links["sources_by_target"].get(item.get("requirement_id"), [])
        before = mapping.get("source_requirement_ids", [])
        if desired:
            mapping["source_requirement_ids"] = desired
        else:
            mapping.pop("source_requirement_ids", None)
        if before != desired:
            changed.append({"requirement_id": item.get("requirement_id"), "before": before, "after": desired})
    return changed


def surface_output_source_keys(review: dict) -> set[tuple[str, str]]:
    """Suppress source fallbacks, without hiding an independent active note."""
    links = surface_source_links(review)
    suppressed = set(links["suppressed_ids"])
    notes = [v for v in review.get("technical_requirements") or [] if isinstance(v, dict)]
    keys = {(key, _scope(root)) for root in notes if _converted(root) for key in _original_keys(root)}
    for item in notes:
        if item.get("requirement_id") not in suppressed and not _converted(item):
            keys.discard((surface_source_key(item.get("content")), _scope(item)))
    return keys
