from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "package-chat-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "package-chat-user"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "package-chat-org"

from ai_design_review import api  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


OWNER = {
    "user_id": "package-chat-user",
    "username": "package-chat-user",
    "real_name": "Package Chat User",
    "org_id": "package-chat-org",
    "org_name": "Package Chat Org",
}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'package-chat.db'}")
        repository.create_schema_for_testing()
        original_repository = api.REVIEW_PERSISTENCE
        original_root = api.API_RUN_ROOT
        try:
            api.REVIEW_PERSISTENCE = repository
            api.API_RUN_ROOT = root / "api_runs"
            job_dir = api.API_RUN_ROOT / "package-chat-review"
            job_dir.mkdir(parents=True)
            review = _review()
            write_json(job_dir / "review.json", review)
            repository.create_review("package-chat-review", review, artifact_dir=str(job_dir), owner=OWNER)
            initial_events = repository.list_change_events(
                "package-chat-review", owner_user_id="package-chat-user"
            )

            with TestClient(api.app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/reviews/package-chat-review/standardization-chat",
                    json={"message": "帮我导出SolidWorks参数包", "use_llm": False, "expected_revision": 1},
                )
                assert response.status_code == 200, response.text
                payload = response.json()
                assert payload["review_revision"] == 2
                assert payload["intent"]["type"] == "generation_package_export_request"
                action = payload["generation_package_export"]
                assert action["source_mode"] == "server"
                assert action["review_revision"] == 2
                assert action["status"] == "ready_with_warnings"
                assert action["can_download"] is True
                assert action["automatic_download"] is True
                assert payload["turn"]["generation_package_export"] == action
                assert payload["standardization_context"]["status"] == "current"
                assert "parameter_reasonableness" not in payload["review"]

                package_response = client.get("/api/reviews/package-chat-review/generation-package")
                assert package_response.status_code == 200, package_response.text
                package_payload = package_response.json()
                assert package_payload["review_revision"] == action["review_revision"]
                package = package_payload["parameter_package"]
                assert package["schema_version"] == "spring_generation_parameters/v1"
                assert set(package["generation_parameters"]["spring_parameters"]) == {
                    "wire_diameter", "mean_diameter", "free_length", "total_coils",
                    "active_coils", "handedness", "end_grinding", "end_coils_closed",
                }
                assert "outer_diameter" not in package["generation_parameters"]["spring_parameters"]
                assert repository.list_change_events(
                    "package-chat-review", owner_user_id="package-chat-user"
                ) == initial_events

                stale = client.post(
                    "/api/reviews/package-chat-review/standardization-chat",
                    json={"message": "导出参数包", "use_llm": False, "expected_revision": 1},
                )
                assert stale.status_code == 409, stale.text

                blocked_review = _review()
                blocked_review["spring_parameters"]["handedness"]["need_human_review"] = True
                blocked = client.post(
                    "/api/reviews/standardization-chat",
                    json={"review": blocked_review, "message": "下载生图参数包", "use_llm": False},
                )
                assert blocked.status_code == 200, blocked.text
                blocked_action = blocked.json()["generation_package_export"]
                assert blocked_action["source_mode"] == "local"
                assert blocked_action["can_download"] is False
                assert blocked_action["status"] == "needs_confirmation"
        finally:
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_root
            repository.dispose()

    print("generation package chat API tests passed")


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring", "drawing_no": "CHAT-PACKAGE-001"},
        "spring_parameters": {
            "wire_diameter": _param(3, "mm"),
            "mean_diameter": _param(23, "mm"),
            "outer_diameter": _param(26, "mm"),
            "inner_diameter": _param(20, "mm"),
            "free_length": _param(45, "mm"),
            "total_coils": _param(10),
            "active_coils": _param(8),
            "handedness": _param("right"),
            "end_grinding": _param(1),
            "end_coils_closed": _param(1),
            "load_points": [],
        },
        "technical_requirements": [
            {"type": "process", "content": "两端磨平", "need_human_review": False},
        ],
        "standard_selection": {},
        "standardization_results": [],
        "derived_parameters": {},
        "manual_confirmations": {},
    }


def _param(value: object, unit: str | None = None) -> dict:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["human_confirmed"]}


if __name__ == "__main__":
    main()
