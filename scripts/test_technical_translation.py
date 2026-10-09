from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.technical_translation import (TechnicalTranslationEngine, apply_translation_result, can_recover_translation_failure, prepare_review_translations, requires_translation, translation_blocks_export, validate_translation)
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.fusion import fuse_candidates
from ai_design_review.workflow import DrawingReviewWorkflow
from test_generation_readiness import _ready_review
from technical_translation_test_support import protected_reply


def run():
    fixtures = json.loads((Path(__file__).parent / "fixtures" / "technical_translation_classification.json").read_text(encoding="utf-8"))
    for text in fixtures["not_required"]:
        assert not requires_translation(text), text
    for text in fixtures["requires_translation"]:
        assert requires_translation(text), text
    assert validate_translation("Dimensions according to 3D model", "尺寸以3D模型为准") is None
    assert validate_translation("Dimensions according to 3D model", "尺寸以2D模型为准")
    assert validate_translation("Dimensions according to 3D model", "尺寸以模型为准")
    assert validate_translation("Dimensions according to 3d model", "尺寸以3D模型为准") is None
    assert validate_translation("未注尺寸以3D为准", "未注尺寸以2D为准")
    def unexpected_model_call(_rows):
        raise AssertionError("Chinese engineering notes must not call Qwen")
    local_engine = TechnicalTranslationEngine(completion_fn=unexpected_model_call)
    chinese_3d = "7.未注尺寸以3D为准"
    historical = {"requirement_id": "historical-3d", "type": "other", "content": chinese_3d,
                  "original_content": chinese_3d, "source_language": "zh", "translation_status": "failed",
                  "translation_error": "译文仍包含外语说明，请重试或人工填写中文。",
                  "translation_input_snapshot": {"content": chinese_3d, "type": "other"},
                  "translation_source": "qwen_text:old", "source": ["qwen_vision"], "raw_content": "术语原文",
                  "need_human_review": False, "human_confirmed": True, "confirmation_snapshot": {"content": chinese_3d}}
    assert can_recover_translation_failure(historical)
    recovered_review = _ready_review()
    recovered_review["technical_requirements"] = [copy.deepcopy(historical)]
    recovered_review["manual_confirmations"] = {"technical_requirement_historical-3d": {"confirmed": True}, "technical_0": {"confirmed": True}}
    recovered_item = recovered_review["technical_requirements"][0]
    assert translation_blocks_export(recovered_item), "historical failure must remain blocked until rechecked"
    result = local_engine.translate([recovered_item])[0]
    assert result["translation_status"] == "not_required" and result["translation_error"] == ""
    assert result["original_content"] == chinese_3d and result["translation_source"] == "qwen_text:old"
    assert apply_translation_result(recovered_review, recovered_item, result)
    assert recovered_item["need_human_review"] and not recovered_item["human_confirmed"]
    assert recovered_item["source"] == ["qwen_vision"] and recovered_item["raw_content"] == "术语原文"
    assert not recovered_review["manual_confirmations"] and "confirmation_snapshot" not in recovered_item
    assert not translation_blocks_export(recovered_item)
    assert chinese_3d not in build_generation_parameter_package(recovered_review)["generation_parameters"]["technical_requirements_text"]
    recovered_item["need_human_review"] = False
    package_3d = build_generation_parameter_package(recovered_review)
    assert package_3d["generation_parameters"]["technical_requirements_text"] == "1.其他要求：未注尺寸以3D为准"
    assert build_solidworks_command("1000000070", package_3d, recovered_review)["models"][0]["extraProperties"]["技术要求"] == "1.其他要求：未注尺寸以3D为准"
    assert recovered_item["content"] == chinese_3d, "output numbering must not rewrite the saved original text"
    for change in [{"translation_error": "翻译改变了数值或公差，原文已保留，请核对后重试。"},
                   {"translation_error": "翻译未返回此条目或返回了重复ID，请重试。"},
                   {"translation_input_snapshot": {"content": "旧文本", "type": "other"}},
                   {"original_content": "Dimensions according to 3D model"}, {"original_content": ""}]:
        unsafe = {**copy.deepcopy(historical), **change}
        assert not can_recover_translation_failure(unsafe), change
        assert local_engine.translate([unsafe])[0]["translation_status"] == "failed", change
    new_chinese_review = {"technical_requirements": [{"requirement_id": "new-3d", "type": "other", "content": chinese_3d, "need_human_review": False}]}
    prepare_review_translations(new_chinese_review, local_engine)
    assert new_chinese_review["technical_requirements"][0]["need_human_review"] is False
    foreign = ["Shear modulus G* = 80000 MPa", "Модуль сдвига G*=80000 МПа", "表面Coating Zn15.hr GOST9306-85", "ばねの表面を研磨する", "تلميع سطح النابض"]
    neutral = ["去除毛刺，端圈磨平。", "G* = 80000 MPa", "INCONEL 750", "SUS304", "60Si2Mn", "12Х18Н10Т", "Ц15.хр", "B-1-1.5", "GOST 9389-75", "Ra 12.5μm", "300°C+10°C/20min+1min", "按 GB/T 1239.2-2009 检验"]
    assert all(requires_translation(text) for text in foreign)
    assert not any(requires_translation(text) for text in neutral)
    candidate_notes = qwen_payload_to_candidates({"spring_type": "compression_spring", "technical_requirements": [{"type": "heat_treatment", "content": "热处理 300°C", "original_content": "Heat treatment 300°C", "source_language": "en", "evidence": "图中热处理要求"}]})
    fused = fuse_candidates(candidate_notes)
    built = DrawingReviewWorkflow({})._build_technical_requirements(fused["fields"])
    assert built[0]["original_content"] == "Heat treatment 300°C" and built[0]["source_language"] == "en"
    pairs = [
        (foreign[0], "剪切模量 G* = 80000 MPa"),
        (foreign[1], "剪切模量 G*=80000 MPa"),
        ("CoatingZn15.hrGOST9306-85.QualitycontrolperGOST9301-86", "涂层 Zn15.hr 按 GOST9306-85 执行；质量控制按 GOST9301-86 执行"),
        ("Manufacturing and technical characteristics per GOST 9389-75 (Wire B-1-1.5 GOST 9389-75)", "制造和技术特性按 GOST 9389-75（钢丝 B-1-1.5 GOST 9389-75）"),
        ("Surface roughness Ra 12,5μm", "表面粗糙度 Ra 12.5μm"),
        ("Heat treatment 300°C+10°C/20min+1min", "热处理 300°C+10°C/20min+1min"),
        ("Load F1=210.0 N ±10%", "载荷 F1=210.0 N ±10%"),
        ("Spring rate k=G*d^4/(8*D^3*n)", "刚度k=G*d^4/(8*D^3*n)"),
    ]
    for original, translated in pairs:
        assert validate_translation(original, translated) is None, (original, validate_translation(original, translated))
    assert validate_translation("Modulus G*=80000.0 MPa", "剪切模量 G*=80000 MPa") is None
    for invalid in ["剪切模量 G* = 8000 MPa", "剪切模量 G* = 80000", "剪切模量 G = 80000 MPa", "Shear modulus G* = 80000 MPa"]:
        assert validate_translation(foreign[0], invalid), invalid
    assert validate_translation("Coating GOST 9389-75", "镀层 GB/T 9389-75")
    assert validate_translation(pairs[-1][0], "刚度k=G*n^4/(8*D^3*n)")
    assert validate_translation("Modulus ratio x=G/d", "模量比x=d/G")
    calls = []
    def complete(rows):
        calls.append(rows)
        return {"requirements": [{"requirement_id": row["requirement_id"], "content": protected_reply(row, pairs[index][1]), "source_language": "ru" if index == 1 else "en"} for index, row in enumerate(rows)]}
    engine = TechnicalTranslationEngine(completion_fn=complete)
    notes = [{"requirement_id": f"n-{i}", "type": "process", "content": pair[0], "need_human_review": False, "raw_content": "术语归一化原文"} for i, pair in enumerate(pairs)]
    chinese = {"requirement_id": "chinese", "type": "other", "content": neutral[0], "need_human_review": False}
    review = {"technical_requirements": [*notes, chinese], "manual_confirmations": {"technical_requirement_n-0": {"confirmed": True}, "technical_0": {"confirmed": True}}, "spring_parameters": {"free_length": {"value": 50, "need_human_review": False}}}
    before_parameters = copy.deepcopy(review["spring_parameters"])
    results = prepare_review_translations(review, engine)
    assert len(calls) == 1 and len(calls[0]) == len(pairs)
    assert all(n["translation_status"] == "translated" and n["need_human_review"] for n in notes)
    assert notes[0]["original_content"] == foreign[0] and notes[0]["raw_content"] == "术语归一化原文"
    assert not review["manual_confirmations"]
    assert chinese["need_human_review"] is False and chinese["translation_status"] == "not_required"
    assert review["spring_parameters"] == before_parameters
    direct = {"technical_requirements": [{"requirement_id": "direct", "type": "other", "content": pairs[0][1], "original_content": pairs[0][0]}]}
    prepare_review_translations(direct, engine)
    assert len(calls) == 1 and direct["technical_requirements"][0]["translation_source"] == "qwen_vision"
    for bad in [{"requirements": []}, {"requirements": [{"requirement_id": "unknown", "content": "测试"}]}, "bad json"]:
        rows = TechnicalTranslationEngine(completion_fn=lambda _rows: bad).translate([{ "requirement_id": "n-0", "type": "other", "content": foreign[0]}])
        assert rows[0]["translation_status"] == "failed" and rows[0]["content"] == foreign[0]
    changed = TechnicalTranslationEngine(completion_fn=lambda _rows: {"requirements": [{"requirement_id": "n-0", "content": "错误数值 1"}]}).translate([{ "requirement_id": "n-0", "type": "other", "content": foreign[0]}])[0]
    assert changed["translation_status"] == "translated" and changed["translation_warnings"]
    with patch.dict(os.environ, {"QWEN_API_KEY": "", "DASHSCOPE_API_KEY": "", "TECHNICAL_REQUIREMENT_TRANSLATION_MODEL": "", "STANDARDIZATION_CHAT_MODEL": "chat-test", "QWEN_MODEL": "vision-test"}):
        missing = TechnicalTranslationEngine()
        assert missing.model == "chat-test"
        assert missing.translate([{ "requirement_id": "n", "type": "other", "content": foreign[0]}])[0]["translation_status"] == "failed"
    ready = _ready_review()
    ready["technical_requirements"] = [{"requirement_id": "foreign", "type": "process", "content": foreign[0], "need_human_review": False}, {"requirement_id": "zh", "type": "other", "content": "去除毛刺", "need_human_review": False}]
    readiness = assess_generation_readiness(ready)
    assert readiness["status"] == "ready_with_warnings", readiness
    assert any(w.get("requirement_id") == "foreign" for w in readiness["warnings"])
    package = build_generation_parameter_package(ready)
    text = package["generation_parameters"]["technical_requirements_text"]
    assert text.startswith("1.") and not text.startswith("技术要求\n") and "去除毛刺" in text and "Shear" not in text
    assert translation_blocks_export(ready["technical_requirements"][0])
    # Retry only transient failures; model output validation never calls again.
    import httpx
    actual_client = httpx.Client
    requests = []
    def temporary(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("temporary", request=request)
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        protected = payload["requirements"][0]["content"].replace("Shear modulus", "剪切模量")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"requirements": [{"requirement_id": "n", "content": protected, "source_language": "en"}]})}}]})
    with patch.dict(os.environ, {"QWEN_API_KEY": "fake-unit-test-key"}), patch("httpx.Client", lambda **kwargs: actual_client(transport=httpx.MockTransport(temporary), **kwargs)):
        assert TechnicalTranslationEngine().translate([{ "requirement_id": "n", "type": "other", "content": foreign[0]}])[0]["translation_status"] == "translated"
        assert len(requests) == 2
    print("PASS: translation batching, multilingual/engineering validation, historical confirmation, export and warnings")


if __name__ == "__main__":
    run()
