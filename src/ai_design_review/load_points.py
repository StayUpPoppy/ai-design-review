from __future__ import annotations

import hashlib
import re
import uuid
from math import isfinite
from typing import Any


def new_load_point_id() -> str:
    return f"loadpt_{uuid.uuid4().hex}"


def normalize_load_point_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def canonical_load_point_label(value: Any) -> str:
    return normalize_load_point_label(value).casefold()


def load_point_confirmation_key(load_point_id: str) -> str:
    return f"load_point_{load_point_id}"


def load_point_is_complete(item: Any) -> bool:
    if not isinstance(item, dict) or not normalize_load_point_label(item.get("label")):
        return False
    try:
        height = float(item.get("height"))
        force = float(item.get("force"))
    except (TypeError, ValueError):
        return False
    return isfinite(height) and isfinite(force) and height > 0 and force >= 0


def load_point_is_confirmed(item: Any) -> bool:
    return load_point_is_complete(item) and isinstance(item, dict) and item.get("need_human_review") is False


def load_point_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "load_point_id": str(item.get("load_point_id") or ""),
        "label": normalize_load_point_label(item.get("label")),
        "height": item.get("height"),
        "height_unit": item.get("height_unit") or "mm",
        "force": item.get("force"),
        "force_unit": item.get("force_unit") or "N",
        "load_tolerance_upper": item.get("load_tolerance_upper"),
        "load_tolerance_lower": item.get("load_tolerance_lower"),
        "need_human_review": bool(item.get("need_human_review", True)),
    }


def ensure_load_point_ids(review: dict[str, Any]) -> bool:
    """Give legacy test points stable internal IDs and preserve old confirmations."""

    parameters = review.get("spring_parameters")
    if not isinstance(parameters, dict):
        return False
    points = parameters.get("load_points")
    if not isinstance(points, list):
        if points in (None, ""):
            parameters["load_points"] = []
            return points is not None
        return False

    confirmations = review.setdefault("manual_confirmations", {})
    if not isinstance(confirmations, dict):
        confirmations = {}
        review["manual_confirmations"] = confirmations
    changed = False
    used: set[str] = set()
    for index, item in enumerate(points):
        if not isinstance(item, dict):
            continue
        label = normalize_load_point_label(item.get("label"))
        if label != item.get("label"):
            item["label"] = label
            changed = True
        point_id = _valid_load_point_id(item.get("load_point_id"))
        if not point_id or point_id in used:
            point_id = _legacy_load_point_id(item, index, used)
            item["load_point_id"] = point_id
            changed = True
        used.add(point_id)
        stable_key = load_point_confirmation_key(point_id)
        legacy_key = f"load_points_{index}"
        if stable_key not in confirmations and isinstance(confirmations.get(legacy_key), dict):
            confirmations[stable_key] = dict(confirmations[legacy_key])
            confirmations[stable_key]["load_point_id"] = point_id
            changed = True
    return changed


def _valid_load_point_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text and len(text) <= 96 and re.fullmatch(r"[A-Za-z0-9_-]+", text) else None


def _legacy_load_point_id(item: dict[str, Any], index: int, used: set[str]) -> str:
    seed = "|".join((str(index), normalize_load_point_label(item.get("label")), str(item.get("height") or ""), str(item.get("force") or "")))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    candidate = f"loadpt_{digest}"
    suffix = 2
    while candidate in used:
        candidate = f"loadpt_{digest}_{suffix}"
        suffix += 1
    return candidate
