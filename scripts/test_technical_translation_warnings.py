from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "translation-warning-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "translation-warning-user"
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).parent)]

from ai_design_review.technical_translation import (TechnicalTranslationEngine, active_translation_warnings,
    apply_translation_result, assess_translation, prepare_review_translations, protect_engineering_text,
    requires_translation, strip_note_number, translation_blocks_export, translation_snapshot)
from ai_design_review.technical_translation_recovery import revalidate_translations
from ai_design_review.technical_requirement_recognition import collect_technical_requirements
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command
from test_generation_readiness import _ready_review


def run():
    fixtures = json.loads((Path(__file__).parent / "fixtures" / "technical_translation_warning_pairs.json").read_text(encoding="utf-8"))
    raw = {"spring_type": "compression_spring", "technical_requirements": [
        {**row, "source_language": "ru", "source_order": index, "need_human_review": True}
        for index, row in enumerate(fixtures, 1)]}
    recognized = collect_technical_requirements(qwen_payload_to_candidates(raw))
    for note, fixture in zip(recognized, fixtures):
        assert note["content"] == fixture["content"] and note["translation_status"] == "translated"
        assert active_translation_warnings(note)[0]["category"] == fixture["expected_category"]
        assert not requires_translation(note["content"])
    review = _ready_review()
    review["technical_requirements"] = deepcopy(recognized)
    before_parameters = deepcopy(review["spring_parameters"])
    with patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("Usable Chinese must not call Qwen")):
        results = prepare_review_translations(review)
    assert all(row["translation_status"] == "translated" and row["translation_warnings"] for row in results)
    assert review["spring_parameters"] == before_parameters
    assert not build_generation_parameter_package(review)["generation_parameters"]["technical_requirements_text"]
    for note in review["technical_requirements"]:
        assert not translation_blocks_export(note)
        note["need_human_review"] = False
    package = build_generation_parameter_package(review)
    text = package["generation_parameters"]["technical_requirements_text"]
    assert text.startswith("1.") and "\n2." in text and not text.startswith("技术要求\n")
    assert "STsKBA" in text and "B-1-1.5" in text
    command = build_solidworks_command("1000000099", package, review)
    assert command["models"][0]["extraProperties"]["技术要求"] == text
    frozen = deepcopy(package)
    review["technical_requirements"][0]["content"] = "后续人工修改"
    assert not active_translation_warnings(review["technical_requirements"][0])
    assert build_solidworks_command("1000000099", frozen, review)["models"][0]["extraProperties"]["技术要求"] == text

    originals = ["Force F3=16 N", "Dimension 12.5 mm", "Coating GOST 9389-75", "Wire Б-1-1,5", "Dimensions per 3D"]
    changed = ["力 F2=16 N", "尺寸 13 mm", "镀层 GB/T 9389-75", "钢丝 B-1-1.5", "尺寸按2D"]
    for original, chinese in zip(originals, changed):
        error, warnings = assess_translation(original, chinese)
        assert error is None and warnings, (original, chinese)
    assert assess_translation("Polish surface 12.5 mm", "表面 Polish 12.5 mm")[0]["code"] == "foreign_prose_remaining"
    assert assess_translation("Force 16 N", "")[0]["code"] == "invalid_response"
    assert assess_translation("Force 16 N", "力 ⟦ENG_9999⟧")[0]["code"] == "invalid_response"
    assert assess_translation("Force 16 N", "16 N")[0]["code"] == "invalid_response"
    assert not translation_blocks_export({"content": "G*=80000 MPa", "translation_status": "not_required"})
    assert translation_blocks_export({"content": "G*=80000 MPa", "original_content": "Shear modulus G*=80000 MPa", "translation_status": "translated"})
    for prefix in ["11. ", "11．", "11、", "11) ", "11："]:
        assert strip_note_number(prefix + "其余要求") == "其余要求"
        assert protect_engineering_text(prefix + "其余要求")[1] == {}
    assert strip_note_number("12.5 mm") == "12.5 mm"
    original = "11. Shear modulus G*=80000 MPa"
    row = {"requirement_id": "p", "type": "process", "content": original}
    def complete(rows):
        assert "11" not in rows[0]["_engineering_tokens"].values()
        return {"requirements": [{"requirement_id": "p", "content": rows[0]["content"].replace("Shear modulus", "剪切模量")}]}
    result = TechnicalTranslationEngine(completion_fn=complete).translate([row])[0]
    assert result["translation_status"] == "translated" and not result["translation_warnings"]
    for mode in ["missing", "duplicate", "unknown", "foreign", "empty", "wrong_id"]:
        def reply(rows, mode=mode):
            protected = rows[0]["content"].replace("Shear modulus", "剪切模量")
            token = next(iter(rows[0]["_engineering_tokens"]))
            if mode == "missing": protected = protected.replace(token, "")
            if mode == "duplicate": protected += " " + token
            if mode == "unknown": protected += "⟦ENG_9999⟧"
            if mode == "foreign": protected = rows[0]["content"]
            if mode == "empty": protected = ""
            return {"requirements": [{"requirement_id": "wrong" if mode == "wrong_id" else "p", "content": protected}]}
        result = TechnicalTranslationEngine(completion_fn=reply).translate([row])[0]
        if mode in {"missing", "duplicate"}:
            assert result["translation_status"] == "translated" and result["translation_warnings"], (mode, result)
        else:
            assert result["translation_status"] == "failed" and result["content"] == original

    failed = []
    for note in recognized:
        note = deepcopy(note)
        note.update(content=note["original_content"], translation_status="failed", translation_error="历史工程信息不一致")
        note["translation_input_snapshot"] = translation_snapshot(note)
        failed.append(note)
    with patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("Recovery is local only")):
        recovered = revalidate_translations({"technical_requirements": failed}, failed, recognized)
    assert all(result["recovery_mode"] == "automatic" and result["translation_warnings"] for result in recovered)
    for note, result in zip(failed, recovered):
        assert apply_translation_result({"technical_requirements": failed}, note, result)
        assert note["need_human_review"] and not note["human_confirmed"]
    edited = deepcopy(failed[0]); edited.update(content=edited["original_content"], translation_status="failed", source=["human_edited"])
    edited["translation_input_snapshot"] = translation_snapshot(edited)
    assert revalidate_translations({}, [edited], recognized)[0]["recovery_mode"] == "preview"

    from fastapi.testclient import TestClient
    from ai_design_review import api
    from ai_design_review.io_utils import write_json
    from ai_design_review.review_persistence import ReviewPersistence
    with tempfile.TemporaryDirectory(prefix="translation-warnings-") as directory:
        root = Path(directory); job = root / "order"; job.mkdir()
        note = deepcopy(recognized[0]); note.update(content=note["original_content"], translation_status="failed")
        note["translation_input_snapshot"] = translation_snapshot(note)
        write_json(job / "review.json", {"technical_requirements": [note], "spring_parameters": {}})
        write_json(job / "qwen_vision_raw.json", {"parsed": raw})
        write_json(job / "owner.json", {"user_id": "translation-warning-user", "username": "translation-warning-user"})
        before = (job / "review.json").read_bytes()
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")), patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("No paid calls")):
            response = TestClient(api.app).post("/api/reviews/order/technical-requirements/translate", json={"mode": "revalidate", "requirements": [{"requirement_id": note["requirement_id"], "source_snapshot": translation_snapshot(note)}]})
            assert response.status_code == 200, response.text
            result = response.json()["requirements"][0]
            assert result["translation_status"] == "translated" and result["translation_warnings"]
            assert (job / "review.json").read_bytes() == before
    print("PASS: real 11/13 warning fixtures, numbering, token protection, recovery API and frozen SW output")


if __name__ == "__main__":
    run()
