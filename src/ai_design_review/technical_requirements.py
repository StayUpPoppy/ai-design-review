from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any


TECHNICAL_REQUIREMENT_TYPES = (
    "surface",
    "hardness",
    "heat_treatment",
    "salt_spray",
    "environmental",
    "lifetime",
    "process",
    "other",
)

TECHNICAL_REQUIREMENT_TYPE_LABELS = {
    "surface": "表面处理",
    "hardness": "硬度要求",
    "heat_treatment": "热处理",
    "salt_spray": "盐雾试验",
    "environmental": "环保要求",
    "lifetime": "寿命要求",
    "process": "工艺要求",
    "other": "其他要求",
}

_TYPE_ALIASES = {
    "surface_requirement": "surface",
    "surface_treatment": "surface",
    "hardness_requirement": "hardness",
    "heat": "heat_treatment",
    "heat-treatment": "heat_treatment",
    "salt": "salt_spray",
    "salt_spray_test": "salt_spray",
    "environment": "environmental",
    "environmental_requirement": "environmental",
    "life": "lifetime",
    "process_requirement": "process",
}


def new_technical_requirement_id() -> str:
    return f"techreq_{uuid.uuid4().hex}"


def normalize_technical_requirement_type(value: Any, *, default: str | None = None) -> str | None:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    normalized = _TYPE_ALIASES.get(normalized, normalized)
    if normalized in TECHNICAL_REQUIREMENT_TYPES:
        return normalized
    return default


def technical_requirement_confirmation_key(requirement_id: str) -> str:
    return f"technical_requirement_{requirement_id}"


def ensure_technical_requirement_ids(review: dict[str, Any]) -> bool:
    """Add stable internal IDs to legacy technical requirements in-place.

    Legacy IDs are deterministic for unchanged input, so a read-only load does not
    produce a different identifier on every request. Once the review is saved the
    identifier remains stable even if the requirement content is edited later.
    """

    requirements = review.get("technical_requirements")
    if not isinstance(requirements, list):
        if requirements in (None, ""):
            review["technical_requirements"] = []
            return requirements is not None
        return False

    changed = False
    used: set[str] = set()
    confirmations = review.setdefault("manual_confirmations", {})
    if not isinstance(confirmations, dict):
        confirmations = {}
        review["manual_confirmations"] = confirmations
        changed = True

    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            continue
        requirement_id = _valid_requirement_id(item.get("requirement_id"))
        if not requirement_id or requirement_id in used:
            requirement_id = _legacy_technical_requirement_id(item, index, used)
            item["requirement_id"] = requirement_id
            changed = True
        used.add(requirement_id)

        stable_key = technical_requirement_confirmation_key(requirement_id)
        legacy_key = f"technical_{index}"
        if stable_key not in confirmations and isinstance(confirmations.get(legacy_key), dict):
            confirmations[stable_key] = dict(confirmations[legacy_key])
            confirmations[stable_key]["requirement_id"] = requirement_id
            changed = True
    return changed


def technical_requirement_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_id": str(item.get("requirement_id") or ""),
        "type": normalize_technical_requirement_type(item.get("type"), default="other"),
        "content": str(item.get("content") or "").strip(),
        "need_human_review": bool(item.get("need_human_review", True)),
    }


def canonical_technical_requirement_key(requirement_type: Any, content: Any) -> tuple[str, str]:
    normalized_type = normalize_technical_requirement_type(requirement_type, default="other") or "other"
    normalized_content = re.sub(r"\s+", " ", str(content or "").strip()).casefold()
    return normalized_type, normalized_content


def _valid_requirement_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 96 or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return None
    return text


def _legacy_technical_requirement_id(item: dict[str, Any], index: int, used: set[str]) -> str:
    seed = "|".join(
        (
            str(index),
            str(item.get("type") or "other").strip(),
            str(item.get("content") or "").strip(),
            str(item.get("page") or ""),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    candidate = f"techreq_{digest}"
    suffix = 2
    while candidate in used:
        candidate = f"techreq_{digest}_{suffix}"
        suffix += 1
    return candidate
