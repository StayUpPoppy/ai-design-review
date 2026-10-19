"""Offline engineering-symbol, failed-candidate and immutable-output regression."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "translation-symbol-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "translation-symbol-user"
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).parent)]

from ai_design_review.technical_translation import (
    TechnicalTranslationEngine, apply_translation_result, assess_translation,
    protect_engineering_text, requires_translation, restore_engineering_text,
    translation_blocks_export, translation_snapshot,
)
from ai_design_review.technical_translation_recovery import revalidate_translations
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command
from test_generation_readiness import _ready_review
from technical_translation_test_support import protected_reply

ORIGINAL = "Arbeitsweg (Hub) sh = 0.85 mm"
CHINESE = "工作行程（行程）sh = 0.85 mm"


def failed_note(candidate=CHINESE):
    return {"requirement_id": "german-stroke", "type": "process", "content": ORIGINAL,
            "original_content": ORIGINAL, "source": ["qwen_vision", "machine_translation"],
            "source_language": "de", "translation_status": "failed", "need_human_review": True,
            "translation_error": "译文仍包含外语说明，请重试或人工填写中文。",
            "translation_error_code": "foreign_prose_remaining", "translation_source": "qwen_text:test",
            "translation_error_details": {"candidate_content": candidate, "remaining_text": "sh"},
            "translation_input_snapshot": {"content": ORIGINAL, "type": "process"}}


def run():
    fixtures = json.loads((Path(__file__).parent / "fixtures/technical_translation_classification.json").read_text(encoding="utf-8"))
    for text in fixtures["not_required"]:
        assert not requires_translation(text), text
    for text in fixtures["requires_translation"]:
        assert requires_translation(text), text
    pairs = [(ORIGINAL, CHINESE),
             ("Stroke s_h = 0.85 mm", "工作行程 s_h = 0.85 mm"),
             ("Stroke sₕ = 0.85 mm", "工作行程 sₕ = 0.85 mm"),
             ("Minimum load Fmin=sh*k", "最小载荷 Fmin=sh*k"),
             ("Maximum diameter Dmax ≤ 12 mm", "最大直径 Dmax ≤ 12 mm"),
             ("Рабочий ход sh = 0.85 мм", "工作行程 sh = 0.85 мм")]
    for original, chinese in pairs:
        protected, tokens = protect_engineering_text(original)
        assert restore_engineering_text(protected, tokens) == original
        assert assess_translation(original, chinese) == (None, []), (original, assess_translation(original, chinese))
        calls = []
        def completion(rows):
            calls.append(rows)
            assert "0.85" not in rows[0]["content"]
            return {"requirements": [{"requirement_id": "n", "content": protected_reply(rows[0], chinese), "source_language": "de"}]}
        result = TechnicalTranslationEngine(completion_fn=completion).translate([{"requirement_id": "n", "type": "process", "content": original}])[0]
        assert len(calls) == 1 and result["content"] == chinese and result["translation_status"] == "translated"
        assert not result["translation_warnings"]
    for changed in [CHINESE.replace("sh", "sb"), CHINESE.replace("0.85", "0.9"), CHINESE.replace("mm", "μm")]:
        error, warnings = assess_translation(ORIGINAL, changed)
        assert not error and not warnings, changed

    note = {"requirement_id": "n", "type": "process", "content": ORIGINAL}
    calls = []
    def partial(rows):
        calls.append(rows)
        return {"requirements": [{"requirement_id": "n", "source_language": "de",
                                  "content": rows[0]["content"].replace("Arbeitsweg", "工作行程")}]}
    result = TechnicalTranslationEngine(completion_fn=partial).translate([note])[0]
    assert len(calls) == 1 and result["translation_status"] == "translated"
    assert result["content"] == "工作行程 (Hub) sh = 0.85 mm" and result["source_language"] == "de"
    assert not result["translation_error_details"] and not result["translation_warnings"]
    assert result["translation_output_snapshot"] == {"content": result["content"], "type": "process"}
    assert not translation_blocks_export({**result, "type": "process"})
    assert TechnicalTranslationEngine(completion_fn=partial).translate([{**result, "type": "process"}])[0]["content"] == result["content"]
    assert len(calls) == 1, "Accepted output must not loop through the model"
    for content in ["", "中文 ⟦ENG_unknown⟧"]:
        invalid = TechnicalTranslationEngine(completion_fn=lambda rows: {"requirements": [{"requirement_id": "n", "content": content}]}).translate([note])[0]
        assert invalid["translation_status"] == "failed" and "candidate_content" not in invalid["translation_error_details"]
    for response in ["invalid JSON", {"requirements": []}, {"requirements": [{"requirement_id": "other", "content": CHINESE}]}]:
        invalid = TechnicalTranslationEngine(completion_fn=lambda rows: response).translate([note])[0]
        assert "candidate_content" not in invalid["translation_error_details"]

    # A later network failure must not discard a previous same-input candidate.
    def offline(rows):
        raise ValueError("翻译服务连接失败")
    retry = TechnicalTranslationEngine(completion_fn=offline).translate([failed_note()])[0]
    assert retry["translation_error_code"] == "request_failed"
    assert retry["translation_error_details"]["candidate_content"] == CHINESE
    stale = failed_note(); stale["content"] = "New input sh=1 mm"
    assert "candidate_content" not in TechnicalTranslationEngine(completion_fn=offline).translate([stale])[0]["translation_error_details"]

    review = _ready_review(); note = failed_note(); review["technical_requirements"] = [note]
    with patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("No model in local recovery")):
        recovered = revalidate_translations(review, [note], [])[0]
        assert recovered["recovery_mode"] == "automatic" and recovered["content"] == CHINESE
        assert recovered["translation_source"] == "saved_failed_translation"
        for change in [{"source": ["human_edited"]}, {"content": ORIGINAL + "（人工补充）"}, {"type": "other"}]:
            edited = {**failed_note(), **change}
            preview = revalidate_translations({}, [edited], [])[0]
            assert preview["recovery_mode"] == "preview" and preview["content"] == edited["content"]
        for change in [{"translation_input_snapshot": None}, {"original_content": "Other original"}]:
            assert revalidate_translations({}, [{**failed_note(), **change}], [])[0]["recovery_mode"] == "unavailable"
        partial_note = failed_note("工作行程 Hub sh=0.85 mm")
        invalid = revalidate_translations({}, [partial_note], [])[0]
        assert invalid["recovery_mode"] == "automatic" and invalid["content"] == "工作行程 Hub sh=0.85 mm"
        missing = failed_note(); missing["translation_error_details"] = {}
        invalid = revalidate_translations({}, [missing], [])[0]
        assert invalid["recovery_mode"] == "unavailable" and "没有已保存" in invalid["recovery_reason"]
        other = {"original_content": ORIGINAL, "content": "位移 sh = 0.85 mm", "type": "process"}
        assert revalidate_translations({}, [failed_note()], [other])[0]["recovery_mode"] == "preview"
        same = {**other, "content": CHINESE}
        same_result = revalidate_translations({}, [failed_note()], [same])[0]
        assert same_result["recovery_mode"] == "automatic"
        assert apply_translation_result(review, note, recovered)
        assert note["human_confirmed"] is False and note["need_human_review"] and not translation_blocks_export(note)
        assert not build_generation_parameter_package(review)["generation_parameters"]["technical_requirements_text"]
        note["human_confirmed"] = True; note["need_human_review"] = False
        package = build_generation_parameter_package(review)
        frozen = deepcopy(package)
        command = build_solidworks_command("1000000066", package, review)
        assert "sh = 0.85 mm" in command["models"][0]["extraProperties"]["技术要求"]
        note["content"] = "后续修改 sh=1 mm"
        assert build_solidworks_command("1000000066", frozen, review) == command

    # Persist optional metadata and reopen; the existing API remains read-only.
    from fastapi.testclient import TestClient
    from ai_design_review import api
    from ai_design_review.io_utils import write_json
    from ai_design_review.review_persistence import ReviewPersistence
    with tempfile.TemporaryDirectory(prefix="translation-symbol-") as directory:
        root = Path(directory); job = root / "order"; job.mkdir()
        note = failed_note(); write_json(job / "review.json", {"technical_requirements": [note], "spring_parameters": {}})
        write_json(job / "owner.json", {"user_id": "translation-symbol-user", "username": "translation-symbol-user"})
        request = {"mode": "revalidate", "requirements": [{"requirement_id": note["requirement_id"], "source_snapshot": translation_snapshot(note)}]}
        before = (job / "review.json").read_bytes()
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")), patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("No cloud calls")):
            response = TestClient(api.app).post("/api/reviews/order/technical-requirements/translate", json=request)
            assert response.status_code == 200, response.text
            assert response.json()["requirements"][0]["content"] == CHINESE
            assert (job / "review.json").read_bytes() == before
    print("PASS: shared symbol grammar, German screenshot, protected model input, retained failures, offline recovery, read-only API and frozen SW output")


if __name__ == "__main__":
    run()
