from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "accuracy-inference-test"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "accuracy-inference-test"
from fastapi.testclient import TestClient
from ai_design_review import api, standard_selector
from ai_design_review.accuracy_inference import refresh_accuracy_inference
from ai_design_review.io_utils import read_json, write_json, project_path
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.workflow import DrawingReviewWorkflow
from test_accuracy_inference import base


def main():
    original = (api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.ragflow_runtime_status, api.verify_review_roughness, standard_selector.standard_references)
    standard_selector.standard_references = lambda *a, **k: []
    api.ragflow_runtime_status = lambda **k: {"status": "not_configured"}
    api.verify_review_roughness = lambda *a, **k: None
    try:
        # Replays new recognition locally, before any frontend/history state.
        candidates = [{"field": f, "value": p["value"], "unit": p.get("unit"), "tolerance_upper": p.get("tolerance_upper"), "tolerance_lower": p.get("tolerance_lower"), "source": "qwen_vision", "confidence": .99, "evidence": f}
                      for f, p in base(.2)["spring_parameters"].items()]
        candidates.append({"field": "drawing_name", "value": "compression spring", "source": "qwen_vision", "confidence": .99})
        workflow = DrawingReviewWorkflow(read_json(project_path("config", "factory_rules.json")))
        for enabled in (True, False):
            new = workflow.run(None, candidates, run_standardization=enabled)
            assert new["accuracy_inference"]["selection_mode"] == "auto"
            assert new["spring_parameters"]["accuracy_grade"]["value"] == "1级", new["accuracy_inference"]
            assert new["spring_parameters"].get("free_length_accuracy_grade", {}).get("value") is None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api.REVIEW_PERSISTENCE = repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'accuracy.db'}")
            repository.create_schema_for_testing(); api.API_RUN_ROOT = root
            review = base(.2); refresh_accuracy_inference(review, initialize=True)
            folder = root / "inference"; folder.mkdir(); write_json(folder / "review.json", review)
            owner = {"user_id": "accuracy-inference-test", "username": "accuracy-inference-test"}
            repository.create_review("inference", review, artifact_dir=str(folder), owner=owner)
            with TestClient(api.app) as client:
                changed = deepcopy(review)
                changed["spring_parameters"]["free_length"].update(tolerance_upper=.6, tolerance_lower=-.6)
                response = client.patch("/api/reviews/inference", json={"review": changed, "expected_revision": 1})
                assert response.status_code == 200, response.text
                persisted = client.get("/api/reviews/inference").json()
                assert persisted["spring_parameters"]["accuracy_grade"]["value"] == "2级"
                assert persisted["accuracy_inference"]["selection_mode"] == "auto"
                # Real AI-grade route, with no LLM/RAG request: set grade then local rules.
                response = client.post("/api/reviews/inference/standardization-chat", json={"message": "按三级精度标准化", "use_llm": False, "expected_revision": persisted["review_revision"]})
                assert response.status_code == 200, response.text
                manual = response.json()["review"]
                assert manual["accuracy_inference"]["selection_mode"] == "manual"
                assert manual["spring_parameters"]["accuracy_grade"]["value"] == "3级"
                manual["spring_parameters"]["free_length"].update(tolerance_upper=.1, tolerance_lower=-.1, tolerance_source="human")
                response = client.patch("/api/reviews/inference", json={"review": manual, "expected_revision": response.json()["review_revision"]})
                assert response.status_code == 200, response.text
                saved = client.get("/api/reviews/inference").json()
                assert saved["spring_parameters"]["accuracy_grade"]["value"] == "3级"
                assert saved["accuracy_inference"]["inferred_grade"] == "1级"
                # Existing revision guard rejects a late auto-mode response.
                response = client.patch("/api/reviews/inference", json={"review": changed, "expected_revision": 1})
                assert response.status_code == 409
                assert client.get("/api/reviews/inference").json()["accuracy_inference"]["selection_mode"] == "manual"
        print("Accuracy inference API: new recognition, local standardization, persisted edits, AI selection and revision protection passed")
    finally:
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.ragflow_runtime_status, api.verify_review_roughness, standard_selector.standard_references = original


if __name__ == "__main__":
    main()
