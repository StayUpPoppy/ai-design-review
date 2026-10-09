from __future__ import annotations

import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "translation-revalidation-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "translation-revalidation-user"
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).parent)]

from ai_design_review.technical_translation import (TechnicalTranslationEngine, apply_translation_result,
    protect_engineering_text, restore_engineering_text, translation_diagnostic, translation_snapshot, validate_translation)
from ai_design_review.technical_translation_recovery import revalidate_translations
from ai_design_review.technical_requirement_recognition import collect_technical_requirements
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command
from test_generation_readiness import _ready_review

PAIRS = [
    ("9. Занеболить силой F₃ с выдержкой под нагрузкой не менее 6 часов", "在力 F3 作用下强压处理，保载时间不少于 6 小时"),
    ("10. Определить остаточную деформацию после заневоливания силой F₃", "强压处理后测定力 F3 作用下的残余变形"),
    ("11. Остальные Т.Т. по СТ ЦКБА 030-2006 – 2 группа точности", "其余技术要求按 СТ ЦКБА 030-2006 – 2组精度执行"),
    ("12. Покрытие Ц15.hr ГОСТ 9306-85. Т.Т. и контроль качества покрытия по ГОСТ 9301-86", "镀层 Ц15.hr GOST 9306-85。镀层技术要求和质量控制按 GOST 9301-86 执行"),
    ("13. Изготовление и технические характеристики выполнить по ГОСТ 9389-75 (Проволока Б-1-1,5 ГОСТ 9389-75)", "制造和技术特性按 GOST 9389-75 执行（钢丝 Б-1-1.5 GOST 9389-75）"),
]


def failed_note(index=0):
    original, translated = PAIRS[index]
    return {"requirement_id": f"r-{index}", "type": "process", "content": original,
            "original_content": original, "recognized_content": translated, "need_human_review": True,
            "source": ["qwen_vision"], "source_language": "ru", "translation_status": "failed",
            "translation_error": "旧校验误判", "translation_input_snapshot": {"content": original, "type": "process"}}


def run():
    for original, chinese in PAIRS:
        assert validate_translation(original, chinese) is None, translation_diagnostic(original, chinese)
    for changed in [PAIRS[0][1].replace("F3", "F2"), PAIRS[0][1].replace("6", "8")]:
        assert translation_diagnostic(PAIRS[0][0], changed)["code"] == "engineering_mismatch"
    assert validate_translation(PAIRS[3][0], PAIRS[3][1].replace("Ц15.hr", "Ц16.hr"))
    assert validate_translation(PAIRS[4][0], PAIRS[4][1].replace("Б-1-1.5", "Б-1-1.6"))
    assert validate_translation(PAIRS[2][0], PAIRS[2][1].replace("СТ ЦКБА", "ST TsKBA"))
    assert validate_translation(PAIRS[3][0], PAIRS[3][1].replace("GOST", "GB/T"))
    assert translation_diagnostic("Polish the surface", "表面 Polish")["code"] == "foreign_prose_remaining"
    source = "Force F₃=2850 N; ГОСТ 9389-75; Б-1-1,5; k=G*d^4/(8*D^3*n); ⟦ENG_bad⟧"
    protected, tokens = protect_engineering_text(source)
    assert restore_engineering_text(protected, tokens) == source
    for broken in [protected.replace(next(iter(tokens)), ""), protected + next(iter(tokens)), protected + "⟦ENG_9999⟧"]:
        try:
            restore_engineering_text(broken, tokens)
            raise AssertionError("Broken placeholders must fail")
        except ValueError:
            pass
    calls = []
    def completion(rows):
        calls.append(rows)
        return {"requirements": [{"requirement_id": row["requirement_id"], "content": row["content"].replace("Shear modulus", "剪切模量"), "source_language": "en"} for row in rows]}
    row = {"requirement_id": "n", "type": "process", "content": "Shear modulus G*=80000 MPa"}
    result = TechnicalTranslationEngine(completion_fn=completion).translate([row])[0]
    assert result["translation_status"] == "translated" and "80000" in result["content"]
    assert "80000" not in calls[0][0]["content"]
    for reply in ["剪切模量", "剪切模量 ⟦ENG_9999⟧"]:
        broken = TechnicalTranslationEngine(completion_fn=lambda rows: {"requirements": [{"requirement_id": "n", "content": reply}]}).translate([row])[0]
        if "⟦ENG_9999⟧" in reply:
            assert broken["translation_error_code"] == "invalid_response" and broken["content"] == row["content"]
        else:
            assert broken["translation_status"] == "translated" and broken["translation_warnings"]
    uncertain = TechnicalTranslationEngine(completion_fn=lambda rows: {"requirements": [{"requirement_id": "n", "error": "无法确定"}]}).translate([row])[0]
    assert uncertain["translation_error_code"] == "model_uncertain"
    review = _ready_review()
    notes = [failed_note(index) for index in range(5)]
    review["technical_requirements"] = notes
    raw = {"spring_type": "compression_spring", "technical_requirements": [
        {"type": "process", "content": translated, "original_content": original, "source_language": "ru", "original_number": str(index+9), "source_order": index+9}
        for index, (original, translated) in enumerate(PAIRS)]}
    recognized = collect_technical_requirements(qwen_payload_to_candidates(raw))
    with patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("Revalidation must never call Qwen")):
        results = revalidate_translations(review, notes, recognized)
        assert all(result["recovery_mode"] == "automatic" for result in results)
        before_parameters = deepcopy(review["spring_parameters"])
        for item, result in zip(notes, results):
            assert apply_translation_result(review, item, result)
            assert item["need_human_review"] and item["human_confirmed"] is False
        assert review["spring_parameters"] == before_parameters
        assert "保载" not in build_generation_parameter_package(review)["generation_parameters"]["technical_requirements_text"]
        for note in notes:
            note["need_human_review"] = False
        package = build_generation_parameter_package(review)
        command = build_solidworks_command("1000000055", package, review)
        text = command["models"][0]["extraProperties"]["技术要求"]
        assert "保载" in text and "Ц15.hr" in text and not text.startswith("技术要求\n")
        assert all(f"{index}." in text for index in range(1,6))
        for edited in [ {"source": ["human_edited"]}, {"content": "人工补充 " + PAIRS[0][0]}, {"type": "other"}, {"translation_input_snapshot": None} ]:
            item = {**failed_note(), **edited}
            result = revalidate_translations(review, [item], recognized)[0]
            assert result["recovery_mode"] == "preview" and result["content"] == item["content"]
        item = failed_note()
        ai_review = {"agent_actions": [{"technical_requirement_changes": [{"requirement_id": item["requirement_id"], "operation": "update"}]}]}
        assert revalidate_translations(ai_review, [item], recognized)[0]["recovery_mode"] == "preview"
        ambiguous_history = {"change_history": [{"event_type": "technical_requirement_updated", "before_state": "legacy text"}]}
        assert revalidate_translations(ambiguous_history, [item], recognized)[0]["recovery_mode"] == "preview"
        assert revalidate_translations({}, [item], recognized + recognized)[0]["recovery_mode"] == "preview"
        no_evidence = failed_note(); no_evidence.pop("recognized_content")
        assert revalidate_translations({}, [no_evidence], [])[0]["recovery_mode"] == "unavailable"
        missing_original = failed_note(); missing_original.pop("original_content")
        assert revalidate_translations({}, [missing_original], recognized)[0]["recovery_mode"] == "unavailable"
    from fastapi.testclient import TestClient
    from ai_design_review import api
    from ai_design_review.io_utils import write_json
    from ai_design_review.review_persistence import ReviewPersistence
    with tempfile.TemporaryDirectory(prefix="translation-revalidation-") as directory:
        root = Path(directory); job = root / "order"; job.mkdir()
        note = failed_note()
        write_json(job / "review.json", {"technical_requirements": [note], "spring_parameters": {}})
        write_json(job / "qwen_vision_raw.json", {"parsed": raw})
        write_json(job / "owner.json", {"user_id": "translation-revalidation-user", "username": "translation-revalidation-user"})
        before = (job / "review.json").read_bytes()
        request = {"mode": "revalidate", "requirements": [{"requirement_id": note["requirement_id"], "source_snapshot": translation_snapshot(note)}]}
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")), patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("No model")):
            client = TestClient(api.app)
            response = client.post("/api/reviews/order/technical-requirements/translate", json=request)
            assert response.status_code == 200, response.text
            assert response.json()["requirements"][0]["recovery_mode"] == "automatic"
            assert (job / "review.json").read_bytes() == before
            invalid = deepcopy(request); invalid["mode"] = "bad"
            assert client.post("/api/reviews/order/technical-requirements/translate", json=invalid).status_code == 400
            changed = deepcopy(request); changed["requirements"][0]["source_snapshot"]["content"] = "新内容"
            assert client.post("/api/reviews/order/technical-requirements/translate", json=changed).status_code == 409
            deleted = deepcopy(request); deleted["requirements"][0]["requirement_id"] = "deleted"
            assert client.post("/api/reviews/order/technical-requirements/translate", json=deleted).status_code == 400
            write_json(job / "owner.json", {"user_id": "someone-else"})
            assert client.post("/api/reviews/order/technical-requirements/translate", json=request).status_code == 404
    print("PASS: Russian engineering tokens, protected translation, evidence recovery, preview guards, read-only API and SW output")


if __name__ == "__main__":
    run()
