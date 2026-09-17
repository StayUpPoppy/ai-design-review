from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any


SURFACE_ROUGHNESS_FIELD = "surface_roughness_ra"
SURFACE_ROUGHNESS_UNIT = "μm"
SURFACE_ROUGHNESS_LABEL = "表面粗糙度 Ra（μm）"

_ROUGHNESS_PATTERNS = (
    re.compile(r"(?<![A-Za-z])Ra\s*[:：=]?\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(r"(?:表面)?粗糙度\s*(?:Ra\s*)?[:：=]?\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(r"[▽△▼]\s*(\d+(?:[.,]\d+)?)"),
)
_LOCATION_PATTERNS = (
    (re.compile(r"两端(?:面)?"), "两端面"),
    (re.compile(r"(?:左|右)端面"), None),
    (re.compile(r"端面"), "端面"),
)


def surface_roughness_mentions(text: Any) -> list[dict[str, Any]]:
    """Extract explicit Ra values without treating an ordinary dimension as roughness."""

    content = str(text or "").strip()
    if not content:
        return []
    mentions: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for pattern in _ROUGHNESS_PATTERNS:
        for match in pattern.finditer(content):
            value = positive_surface_roughness(match.group(1))
            if value is None:
                continue
            context = content[max(0, match.start() - 36) : min(len(content), match.end() + 36)]
            location = _surface_roughness_location_near(content, match.start(), match.end())
            key = (value, location or "")
            if key in seen:
                continue
            seen.add(key)
            mentions.append(
                {
                    "value": value,
                    "location": location,
                    "evidence": context.strip() or match.group(0),
                }
            )
    return mentions


def surface_roughness_location(text: Any) -> str | None:
    content = str(text or "")
    for pattern, normalized in _LOCATION_PATTERNS:
        match = pattern.search(content)
        if not match:
            continue
        if normalized is not None:
            return normalized
        return match.group(0)
    return None


def _surface_roughness_location_near(text: str, start: int, end: int) -> str | None:
    before = text[max(0, start - 36) : start]
    matches: list[tuple[int, str]] = []
    for pattern, normalized in _LOCATION_PATTERNS:
        for match in pattern.finditer(before):
            matches.append((match.end(), normalized or match.group(0)))
    if matches:
        return max(matches, key=lambda item: item[0])[1]
    return surface_roughness_location(text[end : min(len(text), end + 36)])


def positive_surface_roughness(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return float(number)


def surface_roughness_text(value: Any, location: Any = None) -> str | None:
    number = positive_surface_roughness(value)
    if number is None:
        return None
    prefix = str(location or "").strip()
    label = _compact_number(number)
    return f"{prefix}粗糙度 Ra {label}μm" if prefix else f"表面粗糙度 Ra {label}μm"


def ensure_surface_roughness_parameter(review: dict[str, Any]) -> bool:
    """Add the optional compression-spring parameter and promote legacy notes.

    This intentionally does not scan historical free-form Qwen notes. Those jobs
    need re-recognition because a note alone was never persisted as review data.
    """

    if not isinstance(review, dict) or _spring_type(review) != "compression_spring":
        return False
    changed = _ensure_template_field(review)
    parameters = review.setdefault("spring_parameters", {})
    if not isinstance(parameters, dict):
        return changed
    existing = parameters.get(SURFACE_ROUGHNESS_FIELD)
    if not isinstance(existing, dict):
        existing = _blank_surface_roughness_parameter()
        parameters[SURFACE_ROUGHNESS_FIELD] = existing
        changed = True
    elif not existing.get("unit"):
        existing["unit"] = SURFACE_ROUGHNESS_UNIT
        changed = True

    requirements = review.get("technical_requirements")
    if not isinstance(requirements, list):
        return changed
    retained: list[Any] = []
    promoted: list[dict[str, Any]] = []
    for item in requirements:
        if not isinstance(item, dict) or str(item.get("type") or "").strip().casefold() not in {
            "surface_roughness",
            "roughness",
            "surface_finish",
            "表面粗糙度",
        }:
            retained.append(item)
            continue
        mentions = surface_roughness_mentions(item.get("content"))
        direct = positive_surface_roughness(item.get("content"))
        if not mentions and direct is not None:
            mentions = [{"value": direct, "location": None, "evidence": f"Ra {direct:g}"}]
        if not mentions:
            retained.append(item)
            continue
        for mention in mentions:
            promoted.append(
                {
                    **mention,
                    "source": _source_values(item.get("source")) or ["legacy_technical_requirement"],
                    "confidence": float(item.get("confidence", 0) or 0),
                    "need_human_review": item.get("need_human_review", True),
                }
            )
        changed = True
    if len(retained) != len(requirements):
        review["technical_requirements"] = retained
    if promoted:
        changed = _merge_promoted_mentions(existing, promoted) or changed
    return changed


def confirmed_surface_roughness_requirement(review: dict[str, Any]) -> dict[str, Any] | None:
    if _spring_type(review) != "compression_spring":
        return None
    item = (review.get("spring_parameters") or {}).get(SURFACE_ROUGHNESS_FIELD)
    if not isinstance(item, dict) or item.get("need_human_review") is not False:
        return None
    value = positive_surface_roughness(item.get("value"))
    content = surface_roughness_text(value, item.get("surface_location"))
    if value is None or not content:
        return None
    return {
        "type": "surface_roughness",
        "content": content,
        "confirmation_source": "human_confirmed",
    }


def _merge_promoted_mentions(target: dict[str, Any], mentions: list[dict[str, Any]]) -> bool:
    values: dict[float, dict[str, Any]] = {}
    for mention in mentions:
        value = positive_surface_roughness(mention.get("value"))
        if value is None:
            continue
        values.setdefault(value, mention)
    if not values:
        return False
    had_value = positive_surface_roughness(target.get("value")) is not None
    candidates = [
        {
            "value": float(value),
            "location": item.get("location"),
            "evidence": item.get("evidence", ""),
            "source": item.get("source", []),
        }
        for value, item in values.items()
    ]
    target["roughness_candidates"] = candidates
    target["source"] = _unique([*_source_values(target.get("source")), "legacy_technical_requirement"])
    target["evidence"] = " | ".join(
        value for value in [str(item.get("evidence") or "").strip() for item in mentions] if value
    )
    target["confidence"] = max(float(item.get("confidence", 0) or 0) for item in mentions)
    if not had_value:
        target["need_human_review"] = not (
            len(values) == 1 and all(item.get("need_human_review") is False for item in mentions)
        )
    if len(values) == 1 and target.get("value") in (None, ""):
        value, mention = next(iter(values.items()))
        target["value"] = float(value)
        target["surface_location"] = mention.get("location") or None
        target.pop("roughness_conflict", None)
        if target.get("need_human_review") is False:
            target["source"] = _unique(["human_confirmed", *_source_values(target.get("source"))])
    elif len(values) > 1 and target.get("value") in (None, ""):
        target["value"] = None
        target["roughness_conflict"] = True
    return True


def _ensure_template_field(review: dict[str, Any]) -> bool:
    template = review.get("spring_template")
    if not isinstance(template, dict):
        return False
    fields = template.get("fields")
    if not isinstance(fields, list):
        return False
    if any(isinstance(item, dict) and item.get("key") == SURFACE_ROUGHNESS_FIELD for item in fields):
        return False
    field = {
        "key": SURFACE_ROUGHNESS_FIELD,
        "label": SURFACE_ROUGHNESS_LABEL,
        "unit": SURFACE_ROUGHNESS_UNIT,
    }
    active_index = next(
        (index for index, item in enumerate(fields) if isinstance(item, dict) and item.get("key") == "active_coils"),
        len(fields) - 1,
    )
    fields.insert(active_index + 1, deepcopy(field))
    return True


def _blank_surface_roughness_parameter() -> dict[str, Any]:
    return {
        "value": None,
        "unit": SURFACE_ROUGHNESS_UNIT,
        "tolerance_upper": None,
        "tolerance_lower": None,
        "source": [],
        "evidence": "",
        "confidence": 0,
        "need_human_review": True,
        "page": 1,
        "position": None,
        "suggested_region": "",
    }


def _spring_type(review: dict[str, Any]) -> str:
    return str(
        (review.get("drawing_summary") or {}).get("spring_type")
        or (review.get("spring_template") or {}).get("spring_type")
        or ""
    )


def _source_values(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    return [str(item) for item in raw if item not in (None, "")]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _compact_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(round(value, 6)).rstrip("0").rstrip(".")
