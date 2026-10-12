from __future__ import annotations
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "load-recognition-test"
from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.load_point_recognition import partition_load_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package


def main():
    fixture = json.loads((ROOT / "data/test/compression_design_checks.json").read_text(encoding="utf-8"))
    review = copy.deepcopy(fixture["base"])
    review["spring_parameters"]["load_points"] = []
    _, review["load_point_diagnostics"] = partition_load_candidates([{"field": "load_point", "source": "qwen_vision", "evidence": "参数表载荷列第一行", "page": 1,
                                                                    "value": {"label": "F1", "height": 30, "force": 315, "height_unit": "mm", "force_unit": "N"}}])
    with tempfile.TemporaryDirectory(prefix="load-recognition-api-") as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'reviews.db'}")
        repository.create_schema_for_testing()
        repository.create_review("load-test", review, file_info={"kind": "image"}, artifact_dir=str(root / "load-test"), owner={"user_id": "load-recognition-test"})
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", repository), TestClient(api.app) as client:
            loaded = client.get("/api/reviews/load-test").json()
            assert loaded["design_checks"]["work_stresses"] == []
            assert repository.get_review("load-test")["revision"] == 1
            assert loaded["load_point_diagnostics"] == review["load_point_diagnostics"]
            stale = copy.deepcopy(loaded)
            candidate = loaded["load_point_diagnostics"][0]
            candidate["status"] = "promoted"
            candidate["promoted_load_point_id"] = "loadpt_verified"
            point = {"load_point_id": "loadpt_verified", "label": "F1", "height": 30, "height_unit": "mm", "force": 10, "force_unit": "N", "need_human_review": True, "source": ["human_added"], "recognition_candidate_id": candidate["candidate_id"]}
            loaded["spring_parameters"]["load_points"].append(point)
            result = client.patch("/api/reviews/load-test", json={"review": loaded, "expected_revision": 1,
                "events": [{"event_type": "load_candidate_promoted", "target_field": "load_point_diagnostics", "before_state": stale["load_point_diagnostics"][0], "after_state": candidate, "metadata": {"candidate_id": candidate["candidate_id"]}}]})
            assert result.status_code == 200, result.text
            conflict = client.patch("/api/reviews/load-test", json={"review": stale, "expected_revision": 1})
            assert conflict.status_code == 409, conflict.text
            reopened = client.get("/api/reviews/load-test").json()
            assert reopened["load_point_diagnostics"][0]["status"] == "promoted"
            assert reopened["spring_parameters"]["load_points"][0]["force"] == 10
            assert build_generation_parameter_package(reopened)["generation_parameters"]["load_points"] == []
            assert any(e["event_type"] == "load_candidate_promoted" for e in repository.list_change_events("load-test"))
            # Legacy snapshots have no diagnostic field and keep confirmed point contents.
            legacy = copy.deepcopy(fixture["base"])
            legacy.pop("load_point_diagnostics", None)
            repository.create_review("legacy", legacy, file_info={"kind": "image"}, artifact_dir=str(root / "legacy"), owner={"user_id": "load-recognition-test"})
            before = repository.get_review("legacy")["review"]
            assert client.get("/api/reviews/legacy").status_code == 200
            assert repository.get_review("legacy")["review"] == before
        repository.dispose()
    print("load diagnostics API: roundtrip, no GET write, manual promotion audit, revision conflict, export isolation and legacy preservation passed")


if __name__ == "__main__":
    main()
