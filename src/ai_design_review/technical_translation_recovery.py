"""Revalidate saved evidence, without a model call, a write, or a confirmation."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .technical_translation import (
    TechnicalTranslationEngine, can_recover_translation_failure, requires_translation,
    assess_translation, translation_snapshot, translation_warning_fields,
)


def _words(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*\d+\s*[.．、)]\s*(?=[^\d\s])", "", text, count=1)
    return re.sub(r"\s+", " ", text)


def _human_changed(review: dict[str, Any], item: dict[str, Any]) -> bool:
    sources = item.get("source") or []
    sources = sources if isinstance(sources, list) else [sources]
    if any(str(source).startswith(("human_edited", "human_input", "human_added", "manual_edit", "agent_", "ai_dialogue")) for source in sources):
        return True
    identity = item["requirement_id"]
    for event in review.get("change_history") or []:
        if not isinstance(event, dict) or event.get("event_type") != "technical_requirement_updated":
            continue
        metadata, before, after = (event.get(name) for name in ("metadata", "before_state", "after_state"))
        identities = {state.get("requirement_id") for state in (metadata, before, after) if isinstance(state, dict) and isinstance(state.get("requirement_id"), str)}
        target = event.get("target_field")
        if identity in identities or target == f"technical_requirements.{identity}":
            return True
        if not identities and not target:
            # A legacy edit without an address cannot prove that this row was untouched.
            return True
    for action in review.get("agent_actions") or []:
        if not isinstance(action, dict) or action.get("reverted"):
            continue
        if any(change.get("requirement_id") == identity and change.get("operation") == "update"
               for change in action.get("technical_requirement_changes") or [] if isinstance(change, dict)):
            return True
    return False


def revalidate_translations(review: dict[str, Any], items: list[dict[str, Any]], recognized: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for item in items:
        snapshot = translation_snapshot(item)
        result = {"requirement_id": item["requirement_id"], "source_snapshot": snapshot,
                  "content": snapshot["content"], "original_content": item.get("original_content") or "",
                  "source_language": item.get("source_language") or "unknown", "translation_status": "failed",
                  "translation_error": item.get("translation_error") or "没有通过校验的已有中文译文，请重新翻译或人工填写。",
                  "translation_error_code": item.get("translation_error_code") or "",
                  "translation_error_details": deepcopy(item.get("translation_error_details") or {}),
                  "translation_input_snapshot": deepcopy(item.get("translation_input_snapshot") or snapshot),
                  "translation_source": item.get("translation_source") or "none", "recovery_mode": "unavailable"}
        results.append(result)
        if can_recover_translation_failure(item):
            result.update(TechnicalTranslationEngine().translate([item])[0], recovery_mode="automatic")
            continue
        if item.get("translation_status") != "failed":
            continue
        key = item.get("recognition_key")
        matches = [note for note in recognized if key and note.get("recognition_key") == key]
        if not matches and item.get("original_content"):
            matches = [note for note in recognized if _words(note.get("original_content")) == _words(item["original_content"])]
        # A persisted recognition candidate is usable when full raw artifacts are missing.
        if not matches and not recognized and item.get("original_content") and item.get("recognized_content"):
            matches = [item]
        candidates = []
        for note in matches:
            original = str(note.get("original_content") or "").strip()
            translated = str(note.get("recognized_content") or note.get("content") or "").strip()
            if not original or original == translated or not requires_translation(original):
                continue
            diagnostic, warnings = assess_translation(original, translated)
            if diagnostic:
                result.update(translation_error=diagnostic["message"], translation_error_code=diagnostic["code"],
                              translation_error_details=diagnostic["details"])
                continue
            candidates.append({"content": translated, "original_content": original,
                               "source_language": note.get("source_language") or item.get("source_language") or "unknown",
                               "translation_source": "saved_recognition", "original_number": note.get("original_number"),
                               "recognition_key": note.get("recognition_key"), "type": note.get("type")})
            candidates[-1].update(translation_warning_fields(warnings, translated, str(note.get("type") or "other")))
        if not candidates:
            continue
        unchanged = (snapshot == item.get("translation_input_snapshot")
                     and _words(snapshot["content"]) == _words(item.get("original_content"))
                     and _words(candidates[0]["original_content"]) == _words(item.get("original_content"))
                     and candidates[0]["type"] == snapshot["type"] and not _human_changed(review, item))
        if len(matches) == len(candidates) == 1 and unchanged:
            result.update({key: value for key, value in candidates[0].items() if key in {
                "content", "original_content", "source_language", "translation_source", "translation_warnings", "translation_warning_snapshot"}})
            result.update(translation_status="translated", translation_error="", translation_error_code="",
                          translation_error_details={}, translation_input_snapshot=snapshot, recovery_mode="automatic")
        else:
            result.update(recovery_mode="preview", translation_candidates=candidates,
                          recovery_reason="已有人工编辑或无法唯一对应原图条目，请对照后选择；不会自动覆盖当前文本。")
    return results
