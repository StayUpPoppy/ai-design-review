"""Exact screenshot reproduction and independent-source counterexamples; offline."""
from copy import deepcopy
import json
import sys
from unittest.mock import patch
from test_company_surface_mapping import source_review_fixture, company_id, recognized, CHINESE
from ai_design_review.surface_source_links import surface_source_links, surface_source_key, bind_surface_sources, surface_output_source_keys
from ai_design_review.surface_catalog import accept_recognized_surface, synchronize_surface_review
from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_preview, build_solidworks_command


def main():
    cases = []
    def check(review, expected):
        original = deepcopy(review)
        links = surface_source_links(review)
        assert links["suppressed_ids"] == expected, (links, expected)
        assert original == review, "Read projection must not change text, confirmation or metadata"
        cases.append({"review": deepcopy(review), "links": links, "output_keys": sorted(surface_output_source_keys(review))})
    review = source_review_fixture()
    check(review, ["surface-ocr"])
    from ai_design_review.fusion import fuse_candidates
    qwen = review["technical_requirements"][0]
    ocr = review["technical_requirements"][-1]
    with patch("ai_design_review.surface_terms._decide_with_llm", side_effect=AssertionError("No extra surface model call")):
        fused = fuse_candidates([{**qwen, "field": "surface_requirement", "value": qwen["content"], "source": "qwen_vision", "recognition_channel": "technical_requirements"},
                                 {**ocr, "field": "surface_requirement", "value": ocr["content"], "source": "rapidocr"}])
    assert len(fused["technical_requirements"]) == 2
    assert fused["technical_requirements"][0]["surface_mapping"]["source_requirement_ids"] == [fused["technical_requirements"][1]["requirement_id"]]
    assert fused["technical_requirements"][1]["content"] == ocr["content"]
    assert bind_surface_sources(review)[0]["after"] == ["surface-ocr"]
    assert review["technical_requirements"][0]["surface_mapping"]["source_requirement_ids"] == ["surface-ocr"]
    before = deepcopy(review)
    # Forged client relationships cannot suppress an independent requirement.
    review["technical_requirements"][0]["surface_mapping"]["source_requirement_ids"] = ["heat"]
    bind_surface_sources(review)
    assert review["technical_requirements"][0]["surface_mapping"]["source_requirement_ids"] == ["surface-ocr"]
    for item in review["technical_requirements"][:-1]: item["need_human_review"] = False
    raw = deepcopy(review["technical_requirements"][-1])
    assert not any(v.get("requirement_id") == "surface-ocr" for v in assess_generation_readiness(review)["pending_fields"])
    package = build_generation_parameter_package(review)
    assert "Fe/Ep" not in package["solidworks_preview"]["extraProperties"]["技术要求"]
    assert package["solidworks_preview"]["extraProperties"]["技术要求"].count(CHINESE) == 1
    assert review["technical_requirements"][-1] == raw and raw["need_human_review"]
    frozen = deepcopy(package)
    review["technical_requirements"][0]["surface_mapping"]["catalog_ids"] = [company_id("电镀-镀白锌")]
    assert build_solidworks_command("1000000001", frozen, review)["models"][0]["extraProperties"] == frozen["solidworks_preview"]["extraProperties"]
    for mutation in ("empty", "pending", "choice_conflict"):
        v = source_review_fixture()
        for item in v["technical_requirements"][:2]:
            if mutation == "empty": item["content"] = ""
            if mutation == "choice_conflict": item["surface_mapping"]["catalog_ids"] = [company_id("电镀-镀白锌")]
        check(v, ["surface-ocr"])
        assert "Fe/Ep" not in build_generation_parameter_package(v)["solidworks_preview"]["extraProperties"]["技术要求"]
    for mutation in ("page", "scope", "thickness", "case", "additional", "manual", "position", "ambiguous", "unconverted"):
        v = source_review_fixture(); source = v["technical_requirements"][-1]
        if mutation == "page": source["page"] = 2
        if mutation == "scope": source["application_scope"] = "左端面"
        if mutation == "thickness": source["content"] = source["original_content"] = source["content"].replace("Zn15", "Zn10")
        if mutation == "case": source["content"] = source["original_content"] = source["content"].replace("c2C", "C2c")
        if mutation == "additional": source["content"] += "，不得除氢"
        if mutation == "manual": source["source"].append("human_edited")
        if mutation == "position":
            for root in v["technical_requirements"][:2]: root["position"] = {**source["position"], "x": 900}
        if mutation == "ambiguous": v["technical_requirements"][1]["content"] += " 保持清洁"
        if mutation == "unconverted":
            for root in v["technical_requirements"][:2]: root["surface_mapping"]["conversion_status"] = "needs_input"
        check(v, [])
        assert "surface-ocr" not in surface_source_links(v)["suppressed_ids"]
        if mutation == "position":
            for item in v["technical_requirements"]: item["need_human_review"] = False
            assert "Fe/Ep" in build_generation_parameter_package(v)["solidworks_preview"]["extraProperties"]["技术要求"], "Position conflicts are independent, not globally hidden by text"
    for box in ({}, None, source_review_fixture()["technical_requirements"][-1]["position"]):
        v = source_review_fixture()
        for root in v["technical_requirements"][:2]: root["position"] = box
        check(v, ["surface-ocr"])
    for punctuation in ("；", "。", ";", ""):
        v = source_review_fixture(); v["technical_requirements"][-1]["content"] += punctuation
        check(v, ["surface-ocr"])
    assert surface_source_key("6. 表面处理：Ｆｅ／Ｅｐ.Zn15.P.c2C（除氢）；") == "Fe/Ep.Zn15.P.c2C(除氢)"
    # Legacy multi-ID records are read unchanged, normalised on explicit edit/confirm.
    legacy = recognized(); legacy["requirement_id"] = "legacy-multi"; legacy["content"] = "清洗后上油"
    legacy["surface_mapping"]["catalog_ids"] = [company_id("清洗"), company_id("上油")]
    old = {"technical_requirements": [deepcopy(legacy)]}
    current = deepcopy(old); synchronize_surface_review(current, old)
    assert current["technical_requirements"][0]["surface_mapping"]["catalog_ids"] == legacy["surface_mapping"]["catalog_ids"]
    synchronize_surface_review(current, old, confirmed_ids={"legacy-multi"})
    assert current["technical_requirements"][0]["surface_mapping"]["catalog_ids"] == [company_id("清洗")]
    compound = accept_recognized_surface({"content": "原文", "surface_mapping": {"catalog_ids": legacy["surface_mapping"]["catalog_ids"], "conversion_status": "converted", "converted_content": "清洗后上油"}})
    assert compound["surface_mapping"]["catalog_ids"] == [company_id("清洗")] and compound["content"] == "清洗后上油"
    if "--json" in sys.argv: print(json.dumps(cases, ensure_ascii=True))
    else: print(f"PASS: {len(cases)} surface source projections, read protection, raw-source integrity, confirmed Chinese output, frozen tasks and single selection")


if __name__ == "__main__": main()
