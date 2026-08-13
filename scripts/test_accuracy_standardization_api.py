from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "accuracy-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "accuracy-user"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "accuracy-org"

from ai_design_review import api  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.parameter_change_proposal import build_parameter_change_proposal  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


OWNER = {
    "user_id": "accuracy-user",
    "username": "accuracy-user",
    "real_name": "Accuracy User",
    "org_id": "accuracy-org",
    "org_name": "Accuracy Org",
}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'accuracy.db'}")
        repository.create_schema_for_testing()
        original_repository = api.REVIEW_PERSISTENCE
        original_root = api.API_RUN_ROOT
        original_stage = api._run_standardization_stage
        try:
            api.REVIEW_PERSISTENCE = repository
            api.API_RUN_ROOT = root / "api_runs"
            job_dir = api.API_RUN_ROOT / "accuracy-review"
            job_dir.mkdir(parents=True)
            review = _review()
            proposal = build_parameter_change_proposal(
                review,
                [{"type": "propose_parameter_patch", "target_field": "mean_diameter", "proposed_value": 17, "unit": "mm"}],
                user_goal="中径改成17mm",
                review_revision=1,
            )
            write_json(job_dir / "review.json", review)
            repository.create_review("accuracy-review", review, artifact_dir=str(job_dir), owner=OWNER)

            with TestClient(api.app, raise_server_exceptions=False) as client:
                missing_revision = client.post(
                    "/api/reviews/accuracy-review/standardization-chat",
                    json={"message": "按一级精度标准化", "use_llm": True},
                )
                assert missing_revision.status_code == 400, missing_revision.text
                assert repository.get_review("accuracy-review", owner_user_id="accuracy-user")["revision"] == 1

                response = client.post(
                    "/api/reviews/accuracy-review/standardization-chat",
                    json={"message": "按一级精度标准化", "use_llm": True, "expected_revision": 1},
                )
                assert response.status_code == 200, response.text
                payload = response.json()
                assert payload["review_revision"] == 2
                assert payload["intent"]["type"] == "accuracy_standardization_request"
                assert payload["intent"]["status"] == "completed"
                accuracy = payload["accuracy_standardization"]
                assert accuracy["requested_grade"] == "1级"
                assert accuracy["previous_grade"] == "2级"
                assert accuracy["specialized_grades_retained"]["diameter_accuracy_grade"] == "2级"
                assert accuracy["standardization_result_count"] > 0
                batch = payload["standardization_batch"]
                assert batch["status"] == "ready"
                assert batch["review_revision"] == 2
                assert batch["applicable_count"] == len(batch["items"])
                assert batch["baseline_fingerprint"]
                assert payload["turn"]["standardization_batch"]["batch_id"] == batch["batch_id"]
                assert payload["review"]["standardization_chat"][-1]["standardization_batch"]["batch_id"] == batch["batch_id"]
                assert all(item["label"] and item["change_types"] for item in batch["items"])
                parameters = payload["review"]["spring_parameters"]
                assert parameters["accuracy_grade"]["value"] == "1级"
                assert parameters["accuracy_grade"]["source"] == ["human_selected"]
                assert parameters["accuracy_grade"]["need_human_review"] is False
                assert parameters["diameter_accuracy_grade"]["value"] == "2级"
                stored_proposal = next(
                    item for item in payload["review"]["parameter_change_proposals"]
                    if item["proposal_id"] == proposal["proposal_id"]
                )
                assert stored_proposal["status"] == "stale"

                events = repository.list_change_events("accuracy-review", owner_user_id="accuracy-user")
                accuracy_events = [item for item in events if item["event_type"] == "accuracy_standardization_completed"]
                assert len(accuracy_events) == 1
                assert accuracy_events[0]["revision_before"] == 1
                assert accuracy_events[0]["revision_after"] == 2

                same_grade = client.post(
                    "/api/reviews/accuracy-review/standardization-chat",
                    json={"message": "以1级精度重新生成方案", "use_llm": False, "expected_revision": 2},
                )
                assert same_grade.status_code == 200, same_grade.text
                assert same_grade.json()["review_revision"] == 3
                assert same_grade.json()["accuracy_standardization"]["selection_changed"] is False

                async def failing_stage(*args, **kwargs):
                    raise RuntimeError("simulated standardization failure")

                api._run_standardization_stage = failing_stage
                failed = client.post(
                    "/api/reviews/accuracy-review/standardization-chat",
                    json={"message": "按三级精度标准化", "use_llm": False, "expected_revision": 3},
                )
                assert failed.status_code == 500, failed.text
                stored = repository.get_review("accuracy-review", owner_user_id="accuracy-user")
                assert stored["revision"] == 3
                assert stored["review"]["spring_parameters"]["accuracy_grade"]["value"] == "1级"
                api._run_standardization_stage = original_stage

                specialized = client.post(
                    "/api/reviews/accuracy-review/standardization-chat",
                    json={"message": "直径按三级精度标准化", "use_llm": False, "expected_revision": 3},
                )
                assert specialized.status_code == 200, specialized.text
                specialized_payload = specialized.json()
                assert specialized_payload["intent"]["status"] == "specialized_not_supported"
                assert specialized_payload["review"]["spring_parameters"]["accuracy_grade"]["value"] == "1级"
        finally:
            api._run_standardization_stage = original_stage
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_root
            repository.dispose()

    print("accuracy standardization API tests passed")


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_features": {
            "spring_family": {"value": "helical"},
            "spring_shape": {"value": "cylindrical"},
            "manufacturing_method": {"value": "cold_coiled"},
            "wire_section": {"value": "round"},
        },
        "spring_parameters": {
            "wire_diameter": _param(2, "mm"),
            "mean_diameter": _param(18, "mm"),
            "outer_diameter": _param(20, "mm"),
            "inner_diameter": _param(16, "mm"),
            "free_length": _param(30, "mm"),
            "total_coils": _param(12, "turns"),
            "active_coils": _param(8, "turns"),
            "end_type": _param("两端并紧"),
            "end_grinding": _param("两端磨削"),
            "handedness": _param("right"),
            "accuracy_grade": {
                **_param("2级"),
                "source": ["company_default"],
                "default_source": "company_default",
                "need_human_review": True,
            },
            "diameter_accuracy_grade": _param("2级"),
            "spring_rate": _param(5, "N/mm"),
            "load_points": [
                {"label": "F1", "height": 20, "height_unit": "mm", "force": 100, "force_unit": "N"},
            ],
        },
        "technical_requirements": [],
        "standard_selection": {"selected_standard": "GB/T 1239.2-2009", "status": "applicable"},
        "standardization_results": [],
        "derived_parameters": {},
        "manual_confirmations": {},
    }


def _param(value: object, unit: str | None = None) -> dict:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["human_confirmed"]}


if __name__ == "__main__":
    main()
