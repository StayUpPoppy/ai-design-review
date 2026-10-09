"""Occurrence-based technical notes; classification is not a merge key."""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any

from .surface_terms import normalize_surface_requirement
from .technical_translation import TRANSLATION_KEYS, requires_translation, assess_translation, translation_warning_fields

TECHNICAL_FIELD_TYPES = {
    "heat_treatment": "heat_treatment", "surface_requirement": "surface",
    "hardness": "hardness", "salt_spray": "salt_spray", "lifetime_test": "lifetime",
    "environmental": "environmental", "process_requirement": "process", "other_requirement": "other",
}
RECOGNITION_KEYS = ("original_number", "source_order", "recognition_key", "recognized_content")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def recognition_metadata(item: dict[str, Any], order: int, *, namespace: str = "qwen") -> dict[str, Any]:
    original = str(item.get("original_content") or item.get("content") or item.get("value") or "").strip()
    number = item.get("original_number")
    if number is None:
        # A decimal value such as 12.5 is not an item number.
        match = re.match(r"^\s*(\d+)\s*[.．、)]\s*(?=[^\d\s])", original)
        number = match[1] if match else None
    number = str(number).strip()[:48] if number not in (None, "") else None
    source_order = _number(item.get("source_order"), order)
    page = item.get("page") or 1
    # Order distinguishes repeated numbering and identical text at different occurrences.
    seed = json.dumps([namespace, page, source_order, order, item.get("position"), original], ensure_ascii=False, default=str)
    return {"original_number": number, "source_order": source_order,
            "recognition_key": str(item.get("recognition_key") or "note_" + hashlib.sha256(seed.encode()).hexdigest()[:28]),
            "recognized_content": str(item.get("recognized_content") or item.get("content") or item.get("value") or "").strip()}


def collect_technical_requirements(candidates: list[dict[str, Any]], *, preserve_confirmation_policy: bool = False) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        kind = TECHNICAL_FIELD_TYPES.get(candidate.get("field"))
        if not kind:
            continue
        content = str(candidate.get("value") or "").strip()
        if not content:
            continue
        source = candidate.get("source") or []
        source = source if isinstance(source, list) else [source]
        metadata = recognition_metadata(candidate, index, namespace="|".join(str(x) for x in source) or "candidate")
        item = {"type": kind, "content": content, "original_content": str(candidate.get("original_content") or content),
                "source": deepcopy(source), "evidence": candidate.get("evidence") or "",
                "confidence": candidate.get("confidence", 0),
                "need_human_review": candidate.get("need_human_review", True) if preserve_confirmation_policy else True,
                "page": candidate.get("page") or 1, "position": deepcopy(candidate.get("position")),
                "suggested_region": candidate.get("suggested_region") or "", **metadata,
                **{key: deepcopy(candidate[key]) for key in TRANSLATION_KEYS if key in candidate}}
        existing = next((note for note in notes if _same_occurrence(note, item)), None)
        if existing:
            existing["source"] = list(dict.fromkeys([*existing["source"], *source]))
            continue
        if kind == "surface":
            normalized = normalize_surface_requirement(content, enable_llm=None if preserve_confirmation_policy else False)
            item.update({key: deepcopy(value) for key, value in normalized.items() if key not in {"need_human_review"}})
            item["content"] = normalized["content"]
            # Keep the incumbent recognition policy. Historical recovery never
            # adopts a machine decision as a fresh confirmation.
            item["need_human_review"] = bool(normalized["need_human_review"]) if preserve_confirmation_policy else True
        if item["original_content"] != item["content"] and requires_translation(item["original_content"]):
            diagnostic, warnings = assess_translation(item["original_content"], item["content"])
            if diagnostic:
                item["content"] = item["original_content"]
                item.update(translation_status="failed", translation_error=diagnostic["message"],
                            translation_error_code=diagnostic["code"], translation_error_details=diagnostic["details"],
                            translation_input_snapshot={"content": item["content"], "type": kind}, translation_source="qwen_vision")
            else:
                item.update(translation_status="translated", translation_error="", translation_error_code="", translation_error_details={}, translation_source="qwen_vision")
                item.update(translation_warning_fields(warnings, item["content"], kind))
        item["requirement_id"] = "techreq_" + hashlib.sha256(item["recognition_key"].encode()).hexdigest()[:24]
        notes.append(item)
    return sorted(notes, key=lambda item: (_number(item.get("page"), 1), item["source_order"]))


def _same_occurrence(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["recognition_key"] == right["recognition_key"]:
        return True
    # Cross-engine de-duplication requires the same actual location AND original words.
    return bool(left.get("position") and right.get("position")
                and left.get("page") == right.get("page") and left["position"] == right["position"]
                and _text(left.get("original_content")) == _text(right.get("original_content")))


def _wording(item: dict[str, Any]) -> set[str]:
    return {_text(item.get(key)) for key in ("content", "original_content", "recognized_content", "raw_content") if _text(item.get(key))}


def recovery_preview(review: dict[str, Any], recognized: list[dict[str, Any]]) -> dict[str, Any]:
    existing = [item for item in review.get("technical_requirements") or [] if isinstance(item, dict)]
    events = review.get("change_history") or []
    deleted: list[dict[str, Any]] = []
    edited: list[dict[str, Any]] = []
    # History is newest first. A later deletion must not be cancelled by an
    # older restore event for the same ID.
    deletion_decisions: dict[str, bool] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") not in {"technical_requirement_deleted", "technical_requirement_restored"}:
            continue
        state = event.get("before_state") or event.get("after_state") or {}
        identity = str((event.get("metadata") or {}).get("requirement_id") or state.get("requirement_id") or "")
        deletion_decisions.setdefault(identity, event.get("event_type") == "technical_requirement_deleted")
    for event in events:
        if not isinstance(event, dict):
            continue
        before = event.get("before_state") or {}
        after = event.get("after_state") or {}
        if not isinstance(before, dict):
            continue
        if event.get("event_type") == "technical_requirement_deleted" and deletion_decisions.get(str(before.get("requirement_id")), True):
            deleted.append(before)
        elif event.get("event_type") in {"technical_requirement_updated", "technical_requirement_translated", "technical_requirement_confirmed"}:
            if any(note.get("requirement_id") == (before.get("requirement_id") or after.get("requirement_id") or (event.get("metadata") or {}).get("requirement_id")) for note in existing):
                edited.append(before)
    # AI dialogue edits/deletions have their own rollback log rather than the
    # single-row editor's audit event. Preserve the same user decisions here.
    for log in review.get("agent_actions") or []:
        if not isinstance(log, dict) or log.get("reverted"):
            continue
        baseline = ((log.get("rollback") or {}).get("full_state") or {}).get("technical_requirements") or []
        for change in log.get("technical_requirement_changes") or []:
            if not isinstance(change, dict):
                continue
            identity = change.get("requirement_id")
            before = next((note for note in baseline if isinstance(note, dict) and note.get("requirement_id") == identity), None) or change.get("before")
            if not isinstance(before, dict):
                continue
            if change.get("operation") == "delete":
                deleted.append(before)
            elif change.get("operation") == "update" and any(note.get("requirement_id") == identity for note in existing):
                edited.append(before)
    rows: list[dict[str, Any]] = []
    order_hints: list[dict[str, Any]] = []
    for item in recognized:
        key = item["recognition_key"]
        words = _wording(item)
        if any(note.get("recognition_key") == key for note in existing):
            continue
        matching = [note for note in existing if words & _wording(note)]
        if matching:
            # Legacy snapshots have no occurrence key. Do not replace or duplicate them.
            if any(not note.get("recognition_key") or note.get("recognition_key") == key for note in matching):
                if len(matching) == 1 and sum(bool(words & _wording(note)) for note in recognized) == 1:
                    order_hints.append({"requirement_id": matching[0]["requirement_id"], "page": item["page"],
                                        **{name: item[name] for name in RECOGNITION_KEYS}})
                continue
        if any(note.get("recognition_key") == key or words & _wording(note) for note in deleted):
            continue
        if any(words & _wording(note) for note in edited):
            continue
        evidence = _text(item.get("evidence"))
        uncertain = any(
            note.get("type") == item["type"] and not note.get("recognition_key")
            and ((evidence and _text(note.get("evidence")) == evidence)
                 or (note.get("need_human_review") is False and not _wording(note) & words
                     and not any(_wording(before) & words for before in edited)))
            for note in existing
        )
        rows.append({"requirement": deepcopy(item), "status": "possible_existing" if uncertain else "available",
                     "reason": "可能已存在或被人工改写，请核对后选择。" if uncertain else "原始识别记录中存在，当前技术要求列表未保留。"})
    return {"items": rows, "order_hints": order_hints,
            "message": "请选择需要补回的条目；补回后仍需人工确认。" if rows else "未发现可补回的遗漏条目；原始识别本身缺项时请重新识别或人工补充。"}
