from __future__ import annotations

import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import update

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.review_persistence import RecognitionJobRecord, ReviewPersistence, _utcnow  # noqa: E402


OWNER_A = {
    "user_id": "1001",
    "username": "engineer-a",
    "real_name": "Engineer A",
    "org_id": "factory-a",
    "org_name": "Factory A",
}
OWNER_B = {
    "user_id": "1002",
    "username": "engineer-b",
    "real_name": "Engineer B",
    "org_id": "factory-b",
    "org_name": "Factory B",
}


def create_job(repository: ReviewPersistence, job_id: str, owner: dict[str, str] = OWNER_A) -> dict:
    return repository.create_recognition_job(
        job_id,
        drawing_name=f"{job_id}.pdf",
        artifact_dir=f"outputs/api_runs/{job_id}",
        input_filename=f"{job_id}.pdf",
        options={"drawing_path": f"incoming/{job_id}.pdf", "use_qwen": True},
        owner=owner,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = ReviewPersistence(f"sqlite+pysqlite:///{Path(directory) / 'recognition_jobs.db'}")
        repository.create_schema_for_testing()
        try:
            first = create_job(repository, "job-a")
            second = create_job(repository, "job-b")
            other = create_job(repository, "job-c", OWNER_B)
            assert first["status"] == "queued" and first["queue_position"] == 1
            assert second["queue_position"] == 2
            assert repository.get_recognition_job("job-c", owner_user_id="1001") is None
            assert [item["job_id"] for item in repository.list_recognition_jobs(owner_user_id="1002")] == ["job-c"]

            claimed_first = repository.claim_next_recognition_job("worker-1", lease_seconds=60)
            claimed_second = repository.claim_next_recognition_job("worker-2", lease_seconds=60)
            assert claimed_first and claimed_first["job_id"] == "job-a"
            assert claimed_second and claimed_second["job_id"] == "job-b"
            assert claimed_first["options"]["use_qwen"] is True
            assert claimed_first["owner"]["user_id"] == "1001"
            assert repository.update_recognition_job_progress("job-a", worker_id="worker-1", stage="qwen_vision", progress=35)
            assert repository.complete_recognition_job("job-a", worker_id="worker-1")
            complete = repository.get_recognition_job("job-a", owner_user_id="1001")
            assert complete and complete["status"] == "completed" and complete["progress"] == 100

            cancelling = repository.request_recognition_job_deletion("job-b", owner_user_id="1001")
            assert cancelling and cancelling["action"] == "cancelling"
            assert repository.recognition_job_cancel_requested("job-b", worker_id="worker-2")
            assert repository.finalize_cancelled_recognition_job("job-b", worker_id="worker-2")
            assert repository.get_recognition_job("job-b", owner_user_id="1001") is None

            queued_delete = repository.request_recognition_job_deletion("job-c", owner_user_id="1002")
            assert queued_delete and queued_delete["action"] == "deleted"
            assert repository.get_recognition_job("job-c", owner_user_id="1002") is None

            create_job(repository, "job-d")
            failed = repository.claim_next_recognition_job("worker-3", lease_seconds=60)
            assert failed and failed["job_id"] == "job-d"
            assert repository.fail_recognition_job("job-d", worker_id="worker-3", error_message="Qwen timeout")
            stored_failed = repository.get_recognition_job("job-d", owner_user_id="1001")
            assert stored_failed and stored_failed["status"] == "failed"
            retried = repository.retry_recognition_job("job-d", owner_user_id="1001")
            assert retried and retried["status"] == "queued" and retried["attempt_count"] == 1

            reclaimed = repository.claim_next_recognition_job("worker-4", lease_seconds=60)
            assert reclaimed and reclaimed["job_id"] == "job-d" and reclaimed["attempt_count"] == 2
            with repository._session() as session:  # type: ignore[attr-defined]
                session.execute(
                    update(RecognitionJobRecord)
                    .where(RecognitionJobRecord.job_id == "job-d")
                    .values(lease_expires_at=_utcnow() - timedelta(seconds=1))
                )
                session.commit()
            recovered_claim = repository.claim_next_recognition_job("worker-5", lease_seconds=60)
            assert recovered_claim and recovered_claim["job_id"] == "job-d" and recovered_claim["attempt_count"] == 3
            recovered = repository.get_recognition_job("job-d", owner_user_id="1001")
            assert recovered and recovered["status"] == "processing"
        finally:
            repository.dispose()

    print("recognition job persistence tests passed")


if __name__ == "__main__":
    main()
