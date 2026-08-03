from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review import recognition_worker as worker_module  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


OWNER = {
    "user_id": "1001",
    "username": "engineer-a",
    "real_name": "Engineer A",
    "org_id": "factory-a",
    "org_name": "Factory A",
}


def create_job(repository: ReviewPersistence, job_id: str, root: Path) -> None:
    artifact_dir = root / job_id
    artifact_dir.mkdir()
    (artifact_dir / "placeholder.txt").write_text("queued", encoding="utf-8")
    repository.create_recognition_job(
        job_id,
        drawing_name=f"{job_id}.pdf",
        artifact_dir=str(artifact_dir),
        input_filename=f"{job_id}.pdf",
        options={"drawing_path": "incoming/drawing.pdf"},
        owner=OWNER,
    )


async def fake_execution(job: dict, *, progress_callback):
    progress_callback("qwen_vision", 35)
    await asyncio.sleep(0)
    progress_callback("saving_result", 95)
    return {"job_id": job["job_id"]}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'worker_jobs.db'}")
        repository.create_schema_for_testing()
        previous_repository = worker_module.REVIEW_PERSISTENCE
        previous_runner = worker_module.run_recognition_job_record
        previous_output_root = worker_module.API_RUN_ROOT
        worker_module.REVIEW_PERSISTENCE = repository
        worker_module.run_recognition_job_record = fake_execution
        worker_module.API_RUN_ROOT = root
        try:
            create_job(repository, "job-success", root)
            claimed = repository.claim_next_recognition_job("worker-test", lease_seconds=60)
            assert claimed is not None
            worker = worker_module.RecognitionWorker()
            worker.worker_id = "worker-test"
            worker._process_job(claimed)
            success = repository.get_recognition_job("job-success", owner_user_id="1001")
            assert success and success["status"] == "completed" and success["progress"] == 100

            create_job(repository, "job-cancelled", root)
            claimed_cancelled = repository.claim_next_recognition_job("worker-test", lease_seconds=60)
            assert claimed_cancelled is not None
            deleting = repository.request_recognition_job_deletion("job-cancelled", owner_user_id="1001")
            assert deleting and deleting["action"] == "cancelling"
            worker._process_job(claimed_cancelled)
            assert repository.get_recognition_job("job-cancelled", owner_user_id="1001") is None
            assert not (root / "job-cancelled").exists()
        finally:
            worker_module.REVIEW_PERSISTENCE = previous_repository
            worker_module.run_recognition_job_record = previous_runner
            worker_module.API_RUN_ROOT = previous_output_root
            repository.dispose()

    print("recognition worker tests passed")


if __name__ == "__main__":
    main()
