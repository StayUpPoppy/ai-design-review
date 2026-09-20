from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "suggestion-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "suggestion-user"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "suggestion-org"

from ai_design_review import api  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'reviews.db'}")
        repository.create_schema_for_testing()
        old_repository, old_root = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT
        try:
            api.REVIEW_PERSISTENCE = repository
            api.API_RUN_ROOT = root / "api_runs"
            job_dir = api.API_RUN_ROOT / "standardization-revision"
            job_dir.mkdir(parents=True)
            review = _review()
            owner = {"user_id": "suggestion-user", "username": "suggestion-user", "org_id": "suggestion-org"}
            write_json(job_dir / "review.json", review)
            repository.create_review("standardization-revision", review, artifact_dir=str(job_dir), owner=owner)

            with TestClient(api.app, raise_server_exceptions=False) as client:
                historical = client.get("/api/reviews/standardization-revision")
                assert historical.status_code == 200, historical.text
                assert historical.json()["review_revision"] == 1

                response = client.post(
                    "/api/reviews/standardization-revision/standardize",
                    json={"review": historical.json(), "expected_revision": 1, "use_llm_standardization": False},
                )
                assert response.status_code == 200, response.text
                payload = response.json()
                assert payload["review_revision"] == 2
                assert payload["review"]["review_revision"] == 2
                suggestions = payload["review"]["parameter_reasonableness"]["suggestions"]
                assert suggestions
                assert all(item["based_on_revision"] == 2 for item in suggestions)
                standard = next(item for item in suggestions if item["target_field"] == "standard_no")
                assert standard["status"] == "available"
                assert standard["suggested_value"] == "GB/T 1239.2-2009"
                available_targets = {item["target_field"] for item in suggestions if item["status"] == "available"}
                assert {
                    "standard_no", "outer_diameter", "free_length", "total_coils",
                    "perpendicularity", "permanent_set_limit",
                } <= available_targets
                assert payload["review"]["spring_parameters"]["standard_no"]["value"] in (None, "")

                stored = repository.get_review("standardization-revision", owner_user_id="suggestion-user")
                assert stored["revision"] == 2
                assert stored["review"]["parameter_reasonableness"]["suggestions"]
                assert all(item["based_on_revision"] == 2 for item in stored["review"]["parameter_reasonableness"]["suggestions"])
                reopened = client.get("/api/reviews/standardization-revision")
                assert reopened.status_code == 200, reopened.text
                assert all(item["based_on_revision"] == 2 for item in reopened.json()["parameter_reasonableness"]["suggestions"])
        finally:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = old_repository, old_root
            repository.dispose()

    print("standardization suggestion revision API tests passed")


def _review() -> dict:
    def param(value, unit="mm"):
        return {"value": value, "unit": unit, "need_human_review": True, "source": ["qwen_vision"] if value not in (None, "") else []}

    return {
        "drawing_summary": {"drawing_no": "TEST-STANDARD", "spring_type": "compression_spring"},
        "spring_parameters": {
            "wire_diameter": param(2),
            "outer_diameter": param(27),
            "free_length": param(19),
            "total_coils": param(4, "turns"),
            "active_coils": param(2, "turns"),
            "end_type": param("两端并紧", ""),
            "end_grinding": param("两端磨平", ""),
            "accuracy_grade": param("2级", ""),
            "standard_no": param(None, ""),
            "load_points": [],
        },
        "spring_features": {},
        "standardization_results": [],
        "technical_requirements": [],
    }


if __name__ == "__main__":
    main()
