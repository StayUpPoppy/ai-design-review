"""Offline regression coverage for execution selection and rule regeneration."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "execution-standard-test"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "execution-standard-test"
from fastapi.testclient import TestClient
from ai_design_review import api, standard_selector
from ai_design_review.accuracy_inference import refresh_accuracy_inference
from ai_design_review.execution_standards import fingerprint, invalidate_stale_results, resolve_selection
from ai_design_review.io_utils import write_json
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.standard_selector import COLD_COILED_STANDARD as COLD, HOT_COILED_STANDARD as HOT
from ai_design_review.standardizers.hot_coiled import standardize as hot_standardize
from ai_design_review.workflow import apply_standardization_to_review


def review():
    def p(value, unit="mm", **extra):
        return {"value": value, "unit": unit, "source": ["qwen_vision"], **extra}
    return {"drawing_summary": {"spring_type": "compression_spring"},
            "standard_selection": {"selected_standard": COLD, "selection_source": "human_selected"},
            "spring_parameters": {"standard_no": p(COLD, ""), "wire_diameter": p(3), "outer_diameter": p(30),
                "mean_diameter": p(27), "free_length": p(50, tolerance_upper=.3, tolerance_lower=-.1),
                "active_coils": p(8, "turns"), "total_coils": p(10, "turns"),
                "diameter_accuracy_grade": p("1级", ""), "accuracy_grade": p("2级", "", source=["human_selected"]),
                "load_points": []}}


def calculations():
    r = review()
    refresh_accuracy_inference(r, initialize=True)
    apply_standardization_to_review(r)
    diameter = next(item for item in r["standardization_results"] if item["target_field"] == "outer_diameter")
    assert diameter["suggested_tolerance_upper"] == .54
    assert diameter["metadata"]["effective_grade"] == "2级"
    assert diameter["metadata"]["drawing_specific_grade"] == "1级"
    assert r["spring_parameters"]["free_length"]["tolerance_lower"] == -.1
    assert not invalidate_stale_results(r)
    snapshot = deepcopy(r["accuracy_inference"]["input_snapshot"])
    r["spring_parameters"]["free_length"].update(tolerance_upper=1, tolerance_lower=-1, tolerance_source="standardization")
    refresh_accuracy_inference(r)
    assert r["accuracy_inference"]["input_snapshot"] == snapshot
    assert r["spring_parameters"]["accuracy_grade"]["value"] == "2级"
    units = review()
    for field in ("wire_diameter", "outer_diameter", "mean_diameter", "free_length"):
        p = units["spring_parameters"][field]
        p["value"] /= 10
        p["unit"] = "cm"
    apply_standardization_to_review(units)
    diameter = next(item for item in units["standardization_results"] if item["target_field"] == "outer_diameter")
    assert diameter["suggested_tolerance_upper"] == .054 and diameter["suggested_value"] == 3
    r["standard_selection"].update(selected_standard=HOT, selection_source="human_selected")
    assert invalidate_stale_results(r)
    assert all(item["status"] == "stale" for item in r["standardization_results"])
    resolve_selection(r)
    assert r["standard_selection"]["selected_standard"] == HOT
    assert r["standard_selection"]["metadata"]["drawing_standard"]["value"] == COLD
    # Only the free-height input is available, and all geometric scope limits fail.
    parameters = {"free_length": {"value": 10000}, "accuracy_grade": {"value": "T级", "source": ["human_selected"]}}
    results = hot_standardize(parameters)["standardization_results"]
    height = next(item for item in results if item["target_field"] == "free_length")
    assert height["status"] == "suggested" and height["suggested_tolerance_upper"] == 100
    assert next(item for item in results if item["rule_id"] == "GBT23934-DIA")["status"] == "need_context"
    parameters.update(spring_rate={"value": 10, "unit": "N/mm"}, load_points=[{"label": "F1", "force": .1, "force_unit": "kN"}])
    load = next(item for item in hot_standardize(parameters)["standardization_results"] if item["rule_id"] == "GBT23934-LOAD")
    assert load["suggested_tolerance_upper"] == .015 and load["unit"] == "kN"
    legacy = review()
    legacy["accuracy_inference"] = {"selection_mode": "auto", "rules_version": "compression-accuracy/v2", "input_snapshot": {}, "observed_inputs": {}}
    legacy["spring_parameters"]["accuracy_grade"].update(value="3级", source=["tolerance_inference"])
    refresh_accuracy_inference(legacy)
    assert legacy["spring_parameters"]["accuracy_grade"]["value"] == "3级"
    assert legacy["accuracy_inference"]["rules_upgrade_pending"]
    apply_standardization_to_review(legacy)
    assert not legacy["accuracy_inference"].get("rules_upgrade_pending")
    return r, units


def persistence(database=True):
    original = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness
    try:
        api.verify_review_roughness = lambda *a, **k: None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api.API_RUN_ROOT = root
            api.REVIEW_PERSISTENCE = repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'standards.db'}" if database else "")
            if database:
                repository.create_schema_for_testing()
            r = review()
            folder = root / "selection"
            folder.mkdir()
            write_json(folder / "review.json", r)
            write_json(folder / "owner.json", {"user_id": "execution-standard-test"})
            repository.create_review("selection", r, artifact_dir=str(folder), owner={"user_id": "execution-standard-test", "username": "execution-standard-test"})
            with TestClient(api.app) as client:
                r["standard_selection"]["selected_standard"] = HOT
                r["spring_parameters"]["accuracy_grade"]["value"] = "T级"
                response = client.patch("/api/reviews/selection", json={"review": r, "expected_revision": 1})
                assert response.status_code == 200, response.text
                saved = client.get("/api/reviews/selection").json()
                assert saved["standard_selection"]["selected_standard"] == HOT
                response = client.post("/api/reviews/selection/standardize", json={"review": saved, "expected_revision": saved.get("review_revision")})
                assert response.status_code == 200, response.text
                payload = response.json()
                generated = payload["review"]
                assert not invalidate_stale_results(generated), generated["standardization_context"]
                # Both the review and original evidence survive reload before another calculation.
                saved = client.get("/api/reviews/selection").json()
                assert saved["standard_selection"]["selected_standard"] == HOT
                assert saved["standardization_context"]["input_fingerprint"] == fingerprint(saved)
                changed = deepcopy(saved)
                changed["standard_selection"]["selected_standard"] = COLD
                response = client.patch("/api/reviews/selection", json={"review": changed, "expected_revision": saved.get("review_revision")})
                assert response.status_code == 200, response.text
                saved = client.get("/api/reviews/selection").json()
                assert saved["spring_parameters"]["accuracy_grade"]["value"] is None
                assert saved["spring_parameters"]["accuracy_grade"]["requires_selection"]
                assert all(item["status"] == "stale" for item in saved["standardization_results"])
                response = client.post("/api/reviews/selection/standardize", json={"review": saved, "expected_revision": saved.get("review_revision")})
                assert response.status_code == 422, response.text
                # Forging the old result back to suggested cannot make it current.
                for item in saved["standardization_results"]:
                    item["status"] = "suggested"
                response = client.patch("/api/reviews/selection", json={"review": saved, "expected_revision": saved.get("review_revision"),
                    "events": [{"event_type": "standardization_suggestions_applied", "source": "standardization"}]})
                assert response.status_code == 409, response.text
                # AI grade instructions use the same manually chosen standard.
                response = client.post("/api/reviews/selection/standardization-chat", json={"message": "按二级精度标准化", "use_llm": False, "expected_revision": saved.get("review_revision")})
                assert response.status_code == 200, response.text
                assert response.json()["review"]["spring_parameters"]["accuracy_grade"]["value"] == "2级"
    finally:
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness = original


def load_diagnostics():
    r = review()
    p = r["spring_parameters"]
    p["active_coils"]["value"] = None
    p["total_coils"]["value"] = None
    p["load_points"] = [
        {"label": "F1", "force": 100, "height": 40, "force_tolerance_percent": 10},
        {"label": "F2", "force": 150, "height": 30, "load_tolerance_upper": 4, "load_tolerance_lower": -2},
        {"label": "F3", "force": None, "height": 20},
    ]
    original_points = deepcopy(p["load_points"])
    apply_standardization_to_review(r)
    loads = [item for item in r["standardization_results"] if item["rule_id"] == "GBT1239.2-LOAD"]
    assert [item["target_field"] for item in loads] == [f"load_points.F{i}.force" for i in (1, 2, 3)]
    assert all(item["status"] == "need_context" and "active_coils" in item["metadata"]["missing_fields"] for item in loads)
    assert "load_points.F3.force" in loads[2]["metadata"]["missing_fields"]
    assert p["load_points"] == original_points
    assert not any(item.get("target_field", "").startswith("load_points") for item in r["parameter_reasonableness"]["suggestions"])
    p["active_coils"]["value"] = 2
    apply_standardization_to_review(r)
    loads = [item for item in r["standardization_results"] if item["rule_id"] == "GBT1239.2-LOAD"]
    assert all(item["status"] == "not_applicable" and "手填公差" in item["basis"] for item in loads[:2])
    p["active_coils"]["value"] = 8
    apply_standardization_to_review(r)
    loads = [item for item in r["standardization_results"] if item["rule_id"] == "GBT1239.2-LOAD"]
    assert loads[0]["suggested_tolerance_upper"] == 10
    assert loads[1]["suggested_tolerance_upper"] == 15
    assert loads[2]["status"] == "need_context"
    assert p["load_points"] == original_points
    r["standard_selection"].update(selected_standard=HOT)
    p["active_coils"]["value"] = None
    p["material"] = {"value": "SUS304"}
    p["spring_rate"] = {"value": None}
    apply_standardization_to_review(r)
    loads = [item for item in r["standardization_results"] if item["rule_id"] == "GBT23934-LOAD"]
    assert all("spring_rate" in item["metadata"]["missing_fields"] for item in loads)
    assert "active_coils" in p["spring_rate"]["formula_calculation_missing_fields"]
    assert next(item for item in r["standardization_results"] if item["target_field"] == "free_length")["status"] == "suggested"
    p["spring_rate"] = {"value": 10, "unit": "N/mm", "source": ["human_input"]}
    apply_standardization_to_review(r)
    loads = [item for item in r["standardization_results"] if item["rule_id"] == "GBT23934-LOAD"]
    assert loads[0]["suggested_tolerance_upper"] == 50
    assert loads[1]["suggested_tolerance_upper"] == 50
    assert loads[2]["status"] == "need_context"
    assert p["load_points"] == original_points


if __name__ == "__main__":
    standard_selector.standard_references = lambda *a, **k: []
    cases = calculations()
    if "--json" in sys.argv:
        print(json.dumps(list(cases), ensure_ascii=False))
    else:
        load_diagnostics()
        persistence()
        persistence(database=False)
        print("Execution standards: calculations, units, manual precedence, evidence, freshness, persistence, T-grade switching and AI passed")
