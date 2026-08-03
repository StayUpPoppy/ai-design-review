from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "user-a"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "user-a"
os.environ["AI_REVIEW_MOCK_REAL_NAME"] = "User A"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "factory-a"
os.environ["AI_REVIEW_MOCK_ORG_NAME"] = "Factory A"

from ai_design_review import api  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


def set_mock_user(user_id: str) -> None:
    os.environ["AI_REVIEW_MOCK_USER_ID"] = user_id
    os.environ["AI_REVIEW_MOCK_USERNAME"] = user_id
    os.environ["AI_REVIEW_MOCK_REAL_NAME"] = user_id
    os.environ["AI_REVIEW_MOCK_ORG_ID"] = f"factory-{user_id}"
    os.environ["AI_REVIEW_MOCK_ORG_NAME"] = f"Factory {user_id}"


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'api_jobs.db'}")
        repository.create_schema_for_testing()
        original_repository = api.REVIEW_PERSISTENCE
        original_output_root = api.API_RUN_ROOT
        api.REVIEW_PERSISTENCE = repository
        api.API_RUN_ROOT = root / "api_runs"
        api.API_RUN_ROOT.mkdir()
        try:
            with TestClient(api.app) as client:
                response = client.post(
                    "/api/reviews",
                    files={"drawing": ("queued.pdf", b"not-a-real-pdf", "application/pdf")},
                    data={"use_qwen": "true", "use_ocr": "false"},
                )
                assert response.status_code == 202, response.text
                receipt = response.json()
                job_id = receipt["job_id"]
                assert receipt["recognition_status"] == "queued"
                assert (api.API_RUN_ROOT / job_id / "incoming" / "queued.pdf").is_file()

                listed = client.get("/api/reviews").json()["reviews"]
                assert listed[0]["job_id"] == job_id
                assert listed[0]["recognition_status"] == "queued"
                status = client.get(f"/api/reviews/{job_id}/recognition-status")
                assert status.status_code == 200 and status.json()["recognition"]["status"] == "queued"

                set_mock_user("user-b")
                assert client.get("/api/reviews").json()["reviews"] == []
                assert client.get(f"/api/reviews/{job_id}/recognition-status").status_code == 404
                assert client.delete(f"/api/reviews/{job_id}").status_code == 404

                set_mock_user("user-a")
                claimed = repository.claim_next_recognition_job("test-worker", lease_seconds=60)
                assert claimed and claimed["job_id"] == job_id
                page_dir = api.API_RUN_ROOT / job_id / "pages"
                page_dir.mkdir(parents=True, exist_ok=True)
                (page_dir / "page-1.png").write_bytes(b"preview")
                repository.create_review(
                    job_id,
                    {"drawing_summary": {"drawing_name": "queued.pdf"}},
                    artifact_dir=str(api.API_RUN_ROOT / job_id),
                    owner={
                        "user_id": "user-a",
                        "username": "user-a",
                        "real_name": "user-a",
                        "org_id": "factory-user-a",
                        "org_name": "Factory user-a",
                    },
                )
                assert repository.complete_recognition_job(job_id, worker_id="test-worker")
                completed = client.get(f"/api/reviews/{job_id}/recognition-status")
                assert completed.status_code == 200, completed.text
                assert completed.json()["recognition"]["image_url"] == f"/api/reviews/{job_id}/artifacts/pages/page-1.png"

                # Keep a failed task for retry/delete coverage below.
                retry_job_id = "retry-job"
                repository.create_recognition_job(
                    retry_job_id,
                    drawing_name="retry.pdf",
                    artifact_dir=str(api.API_RUN_ROOT / retry_job_id),
                    input_filename="retry.pdf",
                    options={},
                    owner={
                        "user_id": "user-a",
                        "username": "user-a",
                        "real_name": "user-a",
                        "org_id": "factory-user-a",
                        "org_name": "Factory user-a",
                    },
                )
                claimed = repository.claim_next_recognition_job("test-worker", lease_seconds=60)
                assert claimed and claimed["job_id"] == retry_job_id
                assert repository.fail_recognition_job(retry_job_id, worker_id="test-worker", error_message="Qwen timeout")
                retried = client.post(f"/api/reviews/{retry_job_id}/retry")
                assert retried.status_code == 202, retried.text
                assert retried.json()["recognition"]["status"] == "queued"
                assert client.delete(f"/api/reviews/{retry_job_id}").status_code == 200
                assert client.get(f"/api/reviews/{retry_job_id}/recognition-status").status_code == 404
        finally:
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_output_root
            repository.dispose()

    print("async recognition API tests passed")


if __name__ == "__main__":
    main()
