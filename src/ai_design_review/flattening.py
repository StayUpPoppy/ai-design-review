"""Optional compression-spring flattening, independent of end/geometry rules."""
from __future__ import annotations

import math
import re
import unicodedata
from copy import deepcopy
from typing import Any

FIELD = "flattening"
DEFAULT_SOURCE = "flattening-default/v1"
LABEL = "是否制扁"
VALUE_LABELS = {0: "不制扁", 1: "制扁"}
_VALUES = {"0": 0, "1": 1, "否": 0, "是": 1, "no": 0, "yes": 1, "false": 0, "true": 1,
           "not_flattened": 0, "flattened": 1, "不制扁": 0, "无需制扁": 0, "制扁": 1}
_ASSIGNMENT = re.compile(r"(?:是否制扁|flattening)\s*[:：=]?\s*(0|1|否|是|no\b|yes\b|false\b|true\b)", re.I)
_MENTION = re.compile(r"(?:不(?:需要|需|要|用|应|得|必|可)?|无[需须]|不得|禁止|未|免)\s*(?:进行)?\s*制扁|制扁"
                      r"|(?:do\s+not|not|without|no|non[-\s]*)\s*flatten(?:ed|ing)?\b|\bflatten(?:ed|ing)?\b", re.I)


def mentions(text: Any) -> set[int]:
    text = unicodedata.normalize("NFKC", str(text or ""))
    values = {_VALUES[match[1].lower()] for match in _ASSIGNMENT.finditer(text)}
    text = _ASSIGNMENT.sub("", text).replace("是否制扁", "")
    for match in _MENTION.finditer(text):
        token = match[0].lower()
        values.add(1 if token == "制扁" or token in {"flatten", "flattened", "flattening"} else 0)
    return values


def normalize(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value) if value in (0, 1) else None
    if not isinstance(value, str):
        return None
    return _VALUES.get(unicodedata.normalize("NFKC", value).strip().lower())


def _sources(item: dict[str, Any]) -> list[str]:
    sources = item.get("source") or []
    return sources if isinstance(sources, list) else [sources]


def human(item: dict[str, Any]) -> bool:
    return any(str(source).startswith("human") or source in {"manual", "manual_input", "parameter_change_proposal"}
               for source in _sources(item))


def prepare_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for candidate in candidates:
        if candidate.get("field") != FIELD:
            result.append(candidate)
            continue
        item = deepcopy(candidate)
        raw = item.get("value")
        values = mentions(item.get("evidence"))
        if human(item):
            value = normalize(raw)
        else:
            value = next(iter(values)) if len(values) == 1 else None
            item["need_human_review"] = True
        if value != raw or value is None:
            item.setdefault("raw_value", raw)
        item.update(value=value, unit=None, tolerance_upper=None, tolerance_lower=None)
        if len(values) > 1:
            item["flattening_conflict"] = True
        elif value is None:
            item["flattening_unverified"] = True
        result.append(item)
    return result


def merge_candidates(merged: dict[str, Any], ordered: list[dict[str, Any]]) -> None:
    values = {normalize(item.get("value")) for item in ordered if normalize(item.get("value")) is not None}
    if not human(ordered[0]) and (len(values) > 1 or any(item.get("flattening_conflict") for item in ordered)):
        merged.update(value=None, flattening_conflict=True, need_human_review=True)
    for key in ("raw_value", "flattening_unverified"):
        if key in ordered[0]:
            merged[key] = deepcopy(ordered[0][key])
    merged.update(unit=None, tolerance_upper=None, tolerance_lower=None)


def ensure(review: dict[str, Any]) -> bool:
    """Add a pending default to a caller-owned view; never perform I/O."""
    if (review.get("drawing_summary") or {}).get("spring_type") != "compression_spring":
        return False
    parameters = review.get("spring_parameters")
    if parameters is None:
        parameters = review["spring_parameters"] = {}
    if not isinstance(parameters, dict):
        return False
    item = parameters.get(FIELD)
    conflicts = [entry for entry in review.get("conflicts") or [] if entry.get("field") == FIELD]
    if conflicts and (not isinstance(item, dict) or not human(item) and item.get("need_human_review") is not False):
        if not isinstance(item, dict):
            item = parameters[FIELD] = {"value": None, "need_human_review": True}
        item["flattening_conflict"] = True
    if isinstance(item, dict):
        if item.get("value") not in (None, ""):
            return False
        if human(item) or item.get("need_human_review") is False or "raw_value" in item or any(item.get(key) for key in (
            "evidence", "raw_value", "flattening_conflict", "flattening_unverified", "conflict", "value_conflict"
        )):
            return False
    parameters[FIELD] = {**(item or {}), "value": 0, "unit": None, "tolerance_upper": None, "tolerance_lower": None,
        "source": ["solidworks_protocol_default"], "default_source": DEFAULT_SOURCE,
        "evidence": "系统默认：不制扁，需人工确认。", "confidence": 0, "need_human_review": True}
    return True


def invalid_reason(item: dict[str, Any] | None) -> str:
    if not item or normalize(item.get("value")) is None:
        return "请选择制扁或不制扁"
    if any(item.get(key) for key in ("flattening_conflict", "flattening_unverified", "conflict", "value_conflict", "derived_value_stale")):
        return "制扁要求存在冲突或缺少明确依据，请先选择后再确认"
    snapshot = item.get("confirmation_snapshot")
    if item.get("need_human_review") is False and snapshot is not None and (
        not isinstance(snapshot, dict) or snapshot.get("value") != item.get("value")
        or isinstance(snapshot.get("value"), bool) != isinstance(item.get("value"), bool)
    ):
        return "制扁选项已修改，请重新确认"
    return ""


def confirmed(item: dict[str, Any] | None) -> bool:
    return bool(item and item.get("need_human_review") is False and not invalid_reason(item))


def warning(item: dict[str, Any] | None) -> str | None:
    if confirmed(item):
        return None
    return "是否制扁未确认，未写入SW参数。" if item and normalize(item.get("value")) is not None and not invalid_reason(item) else "是否制扁缺失或存在冲突，未写入SW参数。"


def prepare_save(review: dict[str, Any], events: list[dict[str, Any]] | None = None, *, previous: dict[str, Any] | None = None) -> None:
    if (review.get("drawing_summary") or {}).get("spring_type") != "compression_spring":
        return
    edited = any(event.get("event_type") == "parameter_value_updated" and event.get("target_field") == FIELD for event in events or [])
    prior = (previous or {}).get("spring_parameters", {}).get(FIELD)
    if FIELD not in review.get("spring_parameters", {}) and isinstance(prior, dict):
        review.setdefault("spring_parameters", {})[FIELD] = deepcopy(prior)
    item = review.get("spring_parameters", {}).get(FIELD)
    if edited and isinstance(item, dict):
        item["source"] = list(dict.fromkeys([*_sources(item), "human_edited"]))
    ensure(review)
    item = review.get("spring_parameters", {}).get(FIELD)
    if not isinstance(item, dict):
        return
    value = normalize(item.get("value"))
    if edited and value is None and item.get("value") not in (None, ""):
        raise ValueError("是否制扁只能选择0（不制扁）或1（制扁）")
    if edited:
        for key in ("flattening_conflict", "flattening_unverified", "conflict", "value_conflict"):
            item.pop(key, None)
    old = (previous or {}).get("spring_parameters", {}).get(FIELD) or {}
    changed = item.get("value") != old.get("value")
    confirmation_event = any(
        event.get("event_type") in {"parameter_confirmed", "recognized_value_confirmed", "modified_value_confirmed", "risk_value_confirmed"} and event.get("target_field") == FIELD
        or event.get("event_type") == "safe_fields_confirmed" and FIELD in (event.get("metadata") or {}).get("fields", [])
        for event in events or []
    )
    if confirmation_event and not edited and any(old.get(key) for key in ("flattening_conflict", "flattening_unverified", "conflict", "value_conflict")):
        raise ValueError("制扁要求存在冲突，请先选择后再确认")
    if (changed or edited) and not confirmation_event:
        item["need_human_review"] = True
        item.pop("confirmation_snapshot", None)
    if changed and item.get("value") in (None, ""):
        item["source"] = list(dict.fromkeys([*_sources(item), "human_modified"]))
    if item.get("need_human_review") is False and invalid_reason(item):
        raise ValueError(invalid_reason(item))
    if value is not None:
        item["value"] = value
    item.update(unit=None, tolerance_upper=None, tolerance_lower=None)
