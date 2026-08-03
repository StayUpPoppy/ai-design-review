from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

from .api import API_RUN_ROOT, RecognitionCancelled, REVIEW_PERSISTENCE, run_recognition_job_record
from .review_persistence import PersistenceError


LOGGER = logging.getLogger("ai_design_review.recognition_worker")
STOP_EVENT = Event()


def _positive_int(name: str, default: int, *, minimum: int = 1, maximum: int = 3600) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


class RecognitionWorker:
    def __init__(self) -> None:
        self.concurrency = _positive_int("RECOGNITION_WORKER_CONCURRENCY", 2, maximum=8)
        self.poll_seconds = _positive_int("RECOGNITION_JOB_POLL_SECONDS", 1, maximum=30)
        self.lease_seconds = _positive_int("RECOGNITION_JOB_LEASE_SECONDS", 900, minimum=60, maximum=3600)
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}"

    def run(self) -> None:
        if not REVIEW_PERSISTENCE.configured:
            raise RuntimeError("DATABASE_URL is required for the recognition worker.")
        health = REVIEW_PERSISTENCE.health(check_connection=True)
        if health.get("status") != "available":
            raise RuntimeError(f"PostgreSQL is unavailable for the recognition worker: {health.get('reason') or 'unknown error'}")
        LOGGER.info("Recognition worker %s started with concurrency=%s", self.worker_id, self.concurrency)
        futures: set[Future[None]] = set()
        with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="recognition") as executor:
            while not STOP_EVENT.is_set():
                completed = {future for future in futures if future.done()}
                for future in completed:
                    futures.discard(future)
                    try:
                        future.result()
                    except Exception:
                        LOGGER.exception("Recognition worker thread stopped unexpectedly")

                claimed_any = False
                while not STOP_EVENT.is_set() and len(futures) < self.concurrency:
                    job = REVIEW_PERSISTENCE.claim_next_recognition_job(
                        self.worker_id,
                        lease_seconds=self.lease_seconds,
                    )
                    if job is None:
                        break
                    claimed_any = True
                    futures.add(executor.submit(self._process_job, job))

                if not claimed_any:
                    STOP_EVENT.wait(self.poll_seconds)

            for future in futures:
                future.result()
        LOGGER.info("Recognition worker %s stopped", self.worker_id)

    def _process_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return
        LOGGER.info("Starting recognition job %s", job_id)

        def report(stage: str, progress: int) -> None:
            updated = REVIEW_PERSISTENCE.update_recognition_job_progress(
                job_id,
                worker_id=self.worker_id,
                stage=stage,
                progress=progress,
                lease_seconds=self.lease_seconds,
            )
            if not updated:
                raise RecognitionCancelled("Recognition job was cancelled.")

        try:
            report("preparing_file", 5)
            asyncio.run(run_recognition_job_record(job, progress_callback=report))
            if REVIEW_PERSISTENCE.recognition_job_cancel_requested(job_id, worker_id=self.worker_id):
                self._finalize_cancelled(job)
                return
            completed = REVIEW_PERSISTENCE.complete_recognition_job(job_id, worker_id=self.worker_id)
            if not completed:
                self._finalize_cancelled(job)
                return
            LOGGER.info("Completed recognition job %s", job_id)
        except RecognitionCancelled:
            self._finalize_cancelled(job)
            LOGGER.info("Cancelled recognition job %s", job_id)
        except Exception as exc:
            if REVIEW_PERSISTENCE.recognition_job_cancel_requested(job_id, worker_id=self.worker_id):
                self._finalize_cancelled(job)
                LOGGER.info("Cancelled recognition job %s", job_id)
                return
            message = f"{type(exc).__name__}: {exc}"
            try:
                REVIEW_PERSISTENCE.fail_recognition_job(job_id, worker_id=self.worker_id, error_message=message)
            except PersistenceError:
                LOGGER.exception("Unable to mark recognition job %s as failed", job_id)
            LOGGER.exception("Recognition job %s failed", job_id)

    def _finalize_cancelled(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("job_id") or "")
        owner = job.get("owner") if isinstance(job.get("owner"), dict) else {}
        try:
            REVIEW_PERSISTENCE.delete_review(job_id, owner_user_id=str(owner.get("user_id") or ""))
            artifact_dir = REVIEW_PERSISTENCE.finalize_cancelled_recognition_job(job_id, worker_id=self.worker_id)
            self._remove_artifacts(artifact_dir)
        except PersistenceError:
            LOGGER.exception("Unable to finalize cancelled recognition job %s", job_id)

    @staticmethod
    def _remove_artifacts(artifact_dir: str | None) -> None:
        if not artifact_dir:
            return
        path = Path(artifact_dir).resolve()
        try:
            path.relative_to(API_RUN_ROOT.resolve())
        except ValueError:
            LOGGER.warning("Skipped unsafe recognition artifact cleanup: %s", path)
            return
        shutil.rmtree(path, ignore_errors=True)


def _request_stop(*_: object) -> None:
    STOP_EVENT.set()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    worker = RecognitionWorker()
    try:
        worker.run()
    finally:
        REVIEW_PERSISTENCE.dispose()


if __name__ == "__main__":
    main()
