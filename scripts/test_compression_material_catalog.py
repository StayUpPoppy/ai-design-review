from __future__ import annotations

import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "material-catalog-test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.io_utils import write_json
from ai_design_review.material_catalog import (
    ensure_compression_material, load_material_catalog, material_catalog_matches,
    match_material_catalog, normalize_compression_material_parameter,
    select_compression_material, validate_material_change,
)
from ai_design_review.material_terms import normalize_material, normalize_material_key
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.rules import run_rule_checks
from ai_design_review.standardizers.stiffness import calculate_compression_spring_rate, refresh_compression_spring_rate_freshness


def main() -> None:
    catalog = load_material_catalog()
    assert len(catalog["items"]) == 15
    for entry in catalog["items"]:
        for value in [entry["display_name"], entry["standard_value"], *entry["aliases"]]:
            assert match_material_catalog(value)["id"] == entry["id"], value
        parameters = {"material": {"value": entry["display_name"]}, "wire_diameter": {"value": 1},
                      "mean_diameter": {"value": 9}, "active_coils": {"value": 5}}
        result = calculate_compression_spring_rate(parameters)
        assert result["inputs"]["shear_modulus_mpa"] == entry["shear_modulus_mpa"]
        assert result["config_version"] == catalog["version"] and "公司材料表固定参考值" in result["basis"]
        material_rule = next(row for row in run_rule_checks(parameters, [], {}, {}) if row["rule_id"].startswith("MAT-"))
        assert material_rule["status"] == "pass", material_rule
    assert match_material_catalog("材料：sus 304，符合 ГОСТ 5632-72")["id"] == "4"
    for value in ["SUS316L", "55CrSiA", "ХН70МВТЮБ ГОСТ 5632-72", "ХН70МВТЮБ", "70", "70 mm", "70.0", "XSUS304", "SUS304Б"]:
        assert match_material_catalog(value) is None, value
    assert normalize_material_key("ХН70МВТЮБ") == "ХН70МВТЮБ"
    assert normalize_material("ХН70МВТЮБ")["normalization_status"] == "unmatched"
    assert len(material_catalog_matches("SUS304 或 SUS316")) == 2
    raw = {"value": "ХН70МВТЮБ", "raw_value": "ХН70МВТЮБ ГОСТ 5632-72", "source": ["qwen_vision"], "need_human_review": True}
    alternative = {"value": "INCONEL 750", "evidence": "Допускается замена материала на INCONEL 750 или аналоги", "explicitly_allowed": True, "page": 1}
    selected = normalize_compression_material_parameter(raw, alternatives=[alternative])
    assert selected["value"] == "Inconel X750 镍基合金钢" and selected["standard_value"] == "Inconel X750"
    assert selected["raw_value"] == raw["raw_value"] and selected["need_human_review"] is True
    assert selected["material_selection_source"] == "drawing_substitute" and selected["material_substitution_evidence"]["page"] == 1
    primary = normalize_compression_material_parameter({**raw, "raw_value": "SUS304", "value": "SUS304"}, alternatives=[alternative])
    assert primary["value"] == "SUS304 不锈钢" and primary["material_selection_source"] == "drawing"
    for alternatives in [[{"value": "INCONEL 750", "evidence": "material shown nearby"}],
                         [alternative, {**alternative, "value": "SUS304", "evidence": "允许换用 SUS304"}]]:
        assert normalize_compression_material_parameter(raw, alternatives=alternatives)["value"] == ""
    for text in ["不允许换用 SUS304", "не допускается замена материала на SUS304", "replacement not allowed substitute SUS304",
                 "允许换用未知材料；SUS304 是检验夹具材料", "允许换用未知材料，SUS304 是检验夹具材料",
                 "允许换用未知材料 750. SUS304 是检验夹具材料"]:
        assert normalize_compression_material_parameter(raw, alternatives=[{"value": text, "evidence": text, "explicitly_allowed": True}])["value"] == "", text
    comma_options = normalize_compression_material_parameter(raw, alternatives=[{"value": "允许换用 SUS304, SUS316", "evidence": "允许换用 SUS304, SUS316"}])
    assert comma_options["value"] == "" and comma_options["material_match_status"] == "conflict"
    mixed_raw = {**raw, "raw_value": "ХН70МВТЮБ ГОСТ 5632-72；允许换用 INCONEL 750"}
    assert normalize_compression_material_parameter(mixed_raw)["material_selection_source"] == "drawing_substitute"
    forbidden_primary = {**raw, "raw_value": "ХН70МВТЮБ；禁止使用 SUS304；允许换用 INCONEL 750"}
    assert normalize_compression_material_parameter(forbidden_primary)["value"] == "Inconel X750 镍基合金钢"
    supported_primary = {**raw, "raw_value": "材料 SUS304；不允许换用 INCONEL 750"}
    assert normalize_compression_material_parameter(supported_primary)["value"] == "SUS304 不锈钢"
    conflict = normalize_compression_material_parameter({**raw, "raw_value": "SUS304", "primary_materials": [{"value": "SUS304"}, {"value": "ХН70МВТЮБ"}]})
    assert conflict["value"] == "" and conflict["material_match_status"] == "conflict"
    same_primary = normalize_compression_material_parameter({**raw, "raw_value": "SUS304", "primary_materials": [{"value": "SUS304"}, {"value": "SUS304 ГОСТ 5632-72"}]})
    assert same_primary["value"] == "SUS304 不锈钢"
    blank = select_compression_material(selected, "")
    assert blank["value"] == "" and not blank.get("standard_value") and not blank.get("material_id")
    assert normalize_compression_material_parameter(blank, alternatives=[alternative])["value"] == ""
    manual = select_compression_material(selected, "SUS316 不锈钢")
    assert manual["raw_value"] == raw["raw_value"] and manual["standard_value"] == "SUS316"
    assert "material_substitution_evidence" not in manual
    legacy = {"value": "客户特殊材料", "need_human_review": False, "source": ["human_confirmed"]}
    assert normalize_compression_material_parameter(legacy) == legacy
    for value in ["SUS316L", "70", "SUS304 ГОСТ 5632-72"]:
        try:
            select_compression_material(raw, value)
            raise AssertionError(f"invalid selector value accepted: {value}")
        except ValueError:
            pass
    parameters = {"material": {**manual, "raw_value": "Inconel X750", "standard_value": "Inconel X750"},
                  "wire_diameter": {"value": 1}, "mean_diameter": {"value": 9}, "active_coils": {"value": 5}}
    assert calculate_compression_spring_rate(parameters)["inputs"]["shear_modulus_mpa"] == 71500
    parameters["material"]["value"] = ""
    assert calculate_compression_spring_rate(parameters)["status"] == "missing_context"
    parameters["material"]["value"] = "ХН70МВТЮБ"
    assert calculate_compression_spring_rate(parameters)["status"] == "material_not_configured"
    _assert_formula_freshness()
    review = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {"material": raw},
              "technical_requirements": [{"content": alternative["evidence"], "page": 1}]}
    ensure_compression_material(review)
    assert review["spring_parameters"]["material"]["value"] == selected["value"]
    edited_requirement = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {"material": raw},
                          "technical_requirements": [{"content": "允许换用 INCONEL 750", "source": ["human_edited"], "human_modified": True}]}
    ensure_compression_material(edited_requirement)
    assert edited_requirement["spring_parameters"]["material"]["value"] == "", "Edited text must not become drawing allowance evidence"
    edited_requirement["technical_requirements"][0]["original_content"] = alternative["evidence"]
    ensure_compression_material(edited_requirement)
    assert edited_requirement["spring_parameters"]["material"]["value"] == selected["value"]
    _assert_api(catalog)
    print("compression material catalog tests passed")


def _assert_formula_freshness() -> None:
    parameters = {"material": {"value": "SUS304 不锈钢"}, "wire_diameter": {"value": 1},
                  "mean_diameter": {"value": 9}, "active_coils": {"value": 5},
                  "spring_rate": {"value": round(71000 / (8 * 9**3 * 5), 4), "source": ["formula_calculation"],
                                  "need_human_review": True, "formula_calculation_inputs": {"shear_modulus_mpa": 71000},
                                  "formula_calculation_config_version": "temporary-room-temperature-v1"}}
    old_value = parameters["spring_rate"]["value"]
    assert refresh_compression_spring_rate_freshness(parameters)
    assert parameters["spring_rate"]["formula_recommendation_stale"] is True
    assert "71000" in parameters["spring_rate"]["formula_calculation_reason"] and "71500" in parameters["spring_rate"]["formula_calculation_reason"]
    assert parameters["spring_rate"]["value"] == old_value and parameters["spring_rate"]["need_human_review"] is True
    parameters["spring_rate"]["source"].append("human_confirmed")
    parameters["spring_rate"]["need_human_review"] = False
    assert refresh_compression_spring_rate_freshness(parameters)
    assert parameters["spring_rate"]["value"] == old_value and parameters["spring_rate"]["need_human_review"] is False
    human = deepcopy(parameters)
    human["spring_rate"]["source"].append("human_edited")
    human["spring_rate"].pop("formula_recommendation_stale")
    human["spring_rate"].pop("formula_material_catalog_stale")
    before = deepcopy(human)
    assert refresh_compression_spring_rate_freshness(human) is False and human == before
    same_g = deepcopy(parameters)
    same_g["spring_rate"].pop("formula_recommendation_stale")
    same_g["spring_rate"].pop("formula_material_catalog_stale")
    same_g["spring_rate"]["formula_calculation_inputs"]["shear_modulus_mpa"] = 71500
    same_g["spring_rate"]["value"] = calculate_compression_spring_rate(same_g)["value"]
    assert refresh_compression_spring_rate_freshness(same_g) is False
    assert "formula_recommendation_stale" not in same_g["spring_rate"]
    corrected = deepcopy(parameters)
    corrected["spring_rate"]["value"] = calculate_compression_spring_rate(corrected)["value"]
    assert refresh_compression_spring_rate_freshness(corrected) is False
    assert "formula_recommendation_stale" not in corrected["spring_rate"]


def _assert_api(catalog: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="material-catalog-") as directory:
        root = Path(directory)
        job = root / "test-job"
        job.mkdir()
        review = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {
            "material": {"value": "SUS304", "need_human_review": True, "source": ["qwen_vision"]},
            "wire_diameter": {"value": 1}, "mean_diameter": {"value": 9}, "active_coils": {"value": 5},
            "spring_rate": {"value": round(71000 / (8 * 9**3 * 5), 4), "source": ["formula_calculation"],
                            "need_human_review": True, "formula_calculation_inputs": {"shear_modulus_mpa": 71000},
                            "formula_calculation_config_version": "temporary-room-temperature-v1"}}, "review_results": [
                {"rule_id": "MAT-002", "status": "warning", "related_fields": ["material"]}], "technical_requirements": []}
        write_json(job / "review.json", review)
        write_json(job / "owner.json", {"user_id": "material-catalog-test"})
        original = (job / "review.json").read_bytes()
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")):
            with TestClient(api.app) as client:
                response = client.get("/api/material-catalog")
                assert response.status_code == 200 and response.json() == catalog
                with patch.dict(os.environ, {"AI_REVIEW_IDENTITY_MODE": "cookie_json"}):
                    assert client.get("/api/material-catalog").status_code == 401
                loaded = client.get("/api/reviews/test-job").json()
                assert loaded["spring_parameters"]["material"]["value"] == "SUS304 不锈钢"
                assert loaded["review_results"][0]["status"] == "pass"
                assert loaded["spring_parameters"]["spring_rate"]["formula_recommendation_stale"] is True
                assert loaded["spring_parameters"]["spring_rate"]["value"] == review["spring_parameters"]["spring_rate"]["value"]
                assert (job / "review.json").read_bytes() == original, "GET must not persist material normalization"
                loaded["spring_parameters"]["material"] = select_compression_material(loaded["spring_parameters"]["material"], "17-7PH不锈钢")
                loaded["spring_parameters"]["material"]["need_human_review"] = False
                assert client.patch("/api/reviews/test-job", json={"review": loaded}).status_code == 200
                saved = client.get("/api/reviews/test-job").json()
                assert saved["spring_parameters"]["material"]["value"] == "17-7PH不锈钢"
                assert saved["spring_parameters"]["material"]["need_human_review"] is False
                assert saved["spring_parameters"]["material"]["raw_value"] == "SUS304"
                invalid = deepcopy(saved)
                invalid["spring_parameters"]["material"]["value"] = "SUS316L"
                assert client.patch("/api/reviews/test-job", json={"review": invalid}).status_code == 400
                invalid = deepcopy(saved)
                invalid["spring_parameters"]["material"]["value"] = "SUS304 不锈钢"
                invalid["spring_parameters"]["material"]["standard_value"] = "SUS304"
                assert client.patch("/api/reviews/test-job", json={"review": invalid}).status_code == 400
                invalid = deepcopy(saved)
                invalid["spring_parameters"]["material"]["material_id"] = "4"
                assert client.patch("/api/reviews/test-job", json={"review": invalid}).status_code == 400
                legacy = deepcopy(saved)
                legacy["spring_parameters"]["material"] = {"value": "历史客户材料", "need_human_review": False, "source": ["human_confirmed"]}
                write_json(job / "review.json", legacy)
                preserved = client.get("/api/reviews/test-job").json()
                assert preserved["spring_parameters"]["material"]["value"] == "历史客户材料"
                assert "raw_value" not in preserved["spring_parameters"]["material"]
                assert client.patch("/api/reviews/test-job", json={"review": preserved}).status_code == 200
                chosen = deepcopy(preserved)
                chosen["spring_parameters"]["material"] = select_compression_material(chosen["spring_parameters"]["material"], "SUS304")
                assert client.patch("/api/reviews/test-job", json={"review": chosen}).status_code == 200
                assert "raw_value" not in client.get("/api/reviews/test-job").json()["spring_parameters"]["material"]
                write_json(job / "owner.json", {"user_id": "another-user"})
                assert client.get("/api/reviews/test-job").status_code == 404


if __name__ == "__main__":
    main()
