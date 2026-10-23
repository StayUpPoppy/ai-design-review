"""Offline company directory, recognition propagation and SW output fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_design_review.surface_catalog import load_surface_catalog, names_in_content, mapping_reason, accept_recognized_surface, synchronize_surface_review
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates, QwenVisionEngine
from ai_design_review.fusion import fuse_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command, build_solidworks_preview
from ai_design_review.technical_translation import prepare_review_translations, TechnicalTranslationEngine
from ai_design_review.generation_schemas import GenerationParameterPackageV2
from test_solidworks_export import base_review

RAW = "表面处理：Fe/Ep.Zn15.P.c2C（除氢）"
CHINESE = "电镀-镀彩锌，镀层厚度≥15 μm，彩虹铬酸盐处理2级C型，并进行除氢处理。"


def company_id(name): return next(v["id"] for v in load_surface_catalog()["items"] if v["name"] == name)


def recognized():
    return accept_recognized_surface({"type": "process", "content": RAW, "original_content": RAW,
        "surface_mapping": {"catalog_ids": [company_id("电镀-镀彩锌")], "conversion_status": "converted", "converted_content": CHINESE}})


def review_fixture():
    review = base_review()
    item = recognized(); item.update(requirement_id="surface-one", page=1, source=["qwen_vision"], evidence=RAW)
    review["technical_requirements"] = [item, {**deepcopy(item), "requirement_id": "surface-two", "source": ["pdf_text_layer"]},
        {"requirement_id": "heat", "type": "heat_treatment", "content": "消除应力退火", "need_human_review": True},
        {"requirement_id": "press", "type": "process", "content": "压至各圈相接触，保持6h", "need_human_review": True},
        {"requirement_id": "length", "type": "other", "content": "展开长度：约268mm", "need_human_review": True}]
    return review


def source_review_fixture():
    review = review_fixture()
    for item in review["technical_requirements"][:2]:
        item["original_content"] = item["raw_content"] = "6. " + RAW + ";"
    raw = "Fe/Ep.Zn15.P.c2C(除氢)"
    review["technical_requirements"].append({"requirement_id": "surface-ocr", "type": "surface", "content": raw,
        "original_content": raw, "source": ["rapidocr", "machine_translation"], "page": 1,
        "position": {"coordinate_type": "pixel", "x": 535.5, "y": 916, "width": 135, "height": 56},
        "translation_status": "translated", "need_human_review": True})
    return review


def main():
    catalog = load_surface_catalog(); assert len(catalog["items"]) == 49
    assert "电镀-镀锌" not in [v["name"] for v in catalog["items"]]
    for v in catalog["items"]: assert names_in_content(v["name"]) == [v["id"]]
    assert names_in_content("达克罗-泰克锈") == [company_id("达克罗-泰克锈")]
    for text in ("镀锌", "喷塑", "不得发黑", "不得进行发黑", "无需采用电镀-镀白锌", "不采用电镀-镀白锌", RAW): assert names_in_content(text) == []
    assert names_in_content("不得进行发黑，先清洗后上油") == [company_id("清洗"), company_id("上油")]
    item = recognized(); assert not mapping_reason(item) and item["need_human_review"] is True
    original = deepcopy(item)
    item["surface_mapping"]["catalog_ids"] = [company_id("电镀-镀白锌")]
    assert mapping_reason(item) == "公司类型与正文不一致"
    item["surface_mapping"]["catalog_ids"] = []; item["surface_mapping"]["selection_mode"] = "none"
    assert mapping_reason(item) == "" and item["content"] == CHINESE
    for ids in (["invented"], [company_id("电镀-镀彩锌")] * 2):
        malformed = accept_recognized_surface({"content": RAW, "surface_mapping": {"catalog_ids": ids, "conversion_status": "converted", "converted_content": CHINESE}})
        assert malformed["surface_mapping"]["conversion_status"] == "needs_input"
        assert malformed["content"] == RAW
    payload = {"spring_type": {"value": "compression_spring"}, "technical_requirements": [
        {"type": "process", "content": RAW, "original_content": RAW, "page": 1, "surface_mapping": {"catalog_ids": [company_id("电镀-镀彩锌")], "conversion_status": "converted", "converted_content": CHINESE}},
        {"type": "heat_treatment", "content": "消除应力退火", "surface_mapping": {}},
        {"type": "process", "content": "压至各圈相接触，保持6h"},
        {"type": "other", "content": "展开长度：约268mm"}]}
    with patch("ai_design_review.surface_terms._decide_with_llm", side_effect=AssertionError("No secondary Qwen call")):
        candidates = qwen_payload_to_candidates(payload)
        candidates.append({"field": "surface_requirement", "value": RAW, "original_content": RAW, "source": "pdf_text_layer", "page": 1, "recognition_channel": "parameters"})
        notes = fuse_candidates(candidates)["technical_requirements"]
        parameter_only = fuse_candidates(qwen_payload_to_candidates({"parameters": {"surface_requirement": {"value": "客户特殊镀层，厚度≥15 μm"}}}))["technical_requirements"]
        assert parameter_only[0]["content"] == "客户特殊镀层，厚度≥15 μm"
        assert parameter_only[0]["surface_mapping"]["conversion_status"] == "needs_input" and parameter_only[0]["need_human_review"]
    surfaces = [v for v in notes if v["type"] == "surface"]
    assert surfaces and all(v["content"] == CHINESE and v["need_human_review"] for v in surfaces), notes
    assert any(v["content"] == "消除应力退火" and v["type"] == "heat_treatment" for v in notes)
    assert any(v["content"] == "压至各圈相接触，保持6h" and v["type"] == "process" for v in notes)
    def no_completion(*a, **k): raise AssertionError("No automatic supplementary translation")
    prepare_review_translations({"technical_requirements": surfaces}, TechnicalTranslationEngine(completion_fn=no_completion))
    pending = accept_recognized_surface({"type": "surface", "content": "Fe/Ep.Unknown", "surface_mapping": {"conversion_status": "needs_input"}})
    prepare_review_translations({"technical_requirements": [pending]}, TechnicalTranslationEngine(completion_fn=no_completion))
    review = review_fixture()
    for v in review["technical_requirements"]: v["need_human_review"] = False
    package = build_generation_parameter_package(review)
    GenerationParameterPackageV2.model_validate(package)
    text = package["solidworks_preview"]["extraProperties"]["技术要求"]
    assert text.count(CHINESE) == 1 and "Fe/Ep" not in text and "268mm" in text and "保持6h" in text, text
    frozen = deepcopy(package)
    legacy = deepcopy(package); legacy["generation_parameters"]["technical_requirements"] = []
    legacy["generation_parameters"]["technical_requirements_text"] = RAW + "\n消除应力退火"
    assert "Fe/Ep" not in build_solidworks_preview(legacy, review)["extraProperties"]["技术要求"]
    previous = deepcopy(review); review["technical_requirements"][0]["surface_mapping"]["catalog_ids"] = [company_id("电镀-镀白锌")]
    synchronize_surface_review(review, previous)
    assert review["technical_requirements"][0]["need_human_review"] is True
    assert build_solidworks_command("1000000001", frozen, review)["models"][0]["extraProperties"]["技术要求"] == text
    # Inspect the actual outgoing model request while replacing the transport.
    import httpx
    calls = []
    def fake(client, endpoint, headers, data):
        prompt = data["messages"][0]["content"][0]["text"]
        assert all(v["id"] in prompt for v in catalog["items"])
        assert "旧备注" in prompt
        calls.append(data)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}, request=httpx.Request("POST", "https://mock.test"))
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "sample.png"; image.write_bytes(b"local-mock-image")
        with patch("ai_design_review.engines.qwen_vision_adapter._post_qwen_request", side_effect=fake):
            result = QwenVisionEngine(api_key="offline-test").extract_with_raw(image)
            assert result["candidates"]
    assert len(calls) == 1
    # Existing AI proposals are explicitly adopted as a whole. Exact company
    # edits keep that decision; an ambiguous body cannot retain a stale choice.
    from ai_design_review.parameter_change_proposal import _confirmed_technical_requirement
    approved = _confirmed_technical_requirement(recognized(), requirement_id="ai-surface", requirement_type="surface", content=CHINESE.replace("电镀-镀彩锌", "电镀-镀蓝锌"))
    assert approved["surface_mapping"]["catalog_ids"] == [company_id("电镀-镀蓝锌")]
    assert approved["surface_mapping"]["selection_mode"] == "manual" and approved["need_human_review"] is False
    ambiguous = _confirmed_technical_requirement(recognized(), requirement_id="ai-surface", requirement_type="surface", content="镀锌，厚度≥15 μm")
    assert ambiguous["surface_mapping"]["conflict"] and ambiguous["need_human_review"] is True
    if "--json" in sys.argv:
        print(json.dumps({"catalog": catalog, "review": review_fixture(), "source_review": source_review_fixture(), "package": frozen, "raw": RAW, "chinese": CHINESE}, ensure_ascii=True))
    else: print("Company surface: 49 entries, classified/multisource recognition, no supplementary model calls, pending states, Chinese SW output, legacy suppression and frozen requests passed")


if __name__ == "__main__": main()
