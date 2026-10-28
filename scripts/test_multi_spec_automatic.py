"""Automatic multi-spec completion, offline workers and atomic failure recovery.

run_suite also runs against a newly created, isolated PostgreSQL database.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_multi_spec import api, fixture, OWNER
from fastapi.testclient import TestClient
from ai_design_review import multi_spec_store as store, recognition_worker as workers
from ai_design_review.multi_spec import parse_multi_spec, source_review
from ai_design_review.review_persistence import ReviewPersistence, RecognitionJobRecord, ReviewRecord, ReviewChangeEvent
from sqlalchemy import select, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


def run_suite(repo, root):
    worker = workers.RecognitionWorker(); worker.worker_id = "auto-qa"
    def seed(name, count=3, auto=True, source=True):
        directory = root / name; directory.mkdir()
        options = {"drawing_path": "incoming.png"}
        if auto: options["auto_create_variants"] = True
        repo.create_recognition_job(name, drawing_name=name, artifact_dir=str(directory), input_filename="incoming.png", options=options, owner=OWNER)
        payload = fixture(count)
        review = source_review(payload, parse_multi_spec(payload)) if source else {"drawing_summary": {"drawing_name": name}, "spring_parameters": {}}
        # No drawing directory: local fusion uses only the saved response.
        repo.create_review(name, review, owner=OWNER)
        claimed = repo.claim_next_recognition_job(worker.worker_id, lease_seconds=60)
        assert claimed and claimed["job_id"] == name
        return claimed
    def complete(name, report=lambda *_: None):
        return store.complete_automatic(repo, name, OWNER["user_id"], worker.worker_id, OWNER, root, report)
    def manifest(name): return store.describe(repo, name, OWNER["user_id"])
    def reopen(name):
        with repo._session() as session, session.begin():
            job = session.get(RecognitionJobRecord, name)
            job.status = "processing"; job.worker_id = worker.worker_id
            job.cancellation_requested = False; job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)

    with patch.object(api, "REVIEW_PERSISTENCE", repo), patch.object(api, "API_RUN_ROOT", root), \
         patch.object(workers, "REVIEW_PERSISTENCE", repo), patch.object(workers, "API_RUN_ROOT", root), \
         patch("ai_design_review.engines.qwen_vision_adapter.QwenVisionEngine._call_qwen", side_effect=AssertionError("No model calls")), \
         patch("ai_design_review.surface_terms._decide_with_llm", side_effect=AssertionError("No model calls")):
        # A real upload request marks only new tasks; no worker/cloud is run.
        with TestClient(api.app) as client:
            response = client.post("/api/reviews", files={"drawing": ("new.png", b"offline", "image/png")})
            assert response.status_code == 202, response.text
            uploaded = response.json()["job_id"]
            with repo._session() as session:
                assert session.get(RecognitionJobRecord, uploaded).options["auto_create_variants"] is True
            repo.request_recognition_job_deletion(uploaded, owner_user_id=OWNER["user_id"])

        for count in (3, 13, 50):
            name = f"automatic-{count}"; seed(name, count); progress = []
            def report(stage, percent):
                progress.append(percent)
                assert stage == "creating_variant_reviews" and repo.get_recognition_job(name)["status"] == "processing"
                assert manifest(name)["created_count"] == 0, "No partial children before completion"
            assert complete(name, report) is True
            value = manifest(name)
            assert value["creation_mode"] == "auto" and value["created_count"] == count
            assert [v["order"] for v in value["variants"]] == list(range(1, count + 1))
            assert len({v["review"]["job_id"] for v in value["variants"]}) == count
            assert all(v["creation_status"] == "created" for v in value["variants"])
            assert all(96 <= v <= 99 for v in progress)
            for v in value["variants"]:
                record = repo.get_review(v["review"]["job_id"], owner_user_id=OWNER["user_id"])
                assert record["review"]["spring_parameters"]["wire_diameter"]["need_human_review"]
                assert not repo.get_review(v["review"]["job_id"], owner_user_id="different-user")
            assert repo.get_recognition_job(name)["status"] == "completed"
            assert complete(name) is False
            reopen(name); assert complete(name) is True
            assert manifest(name) == value, "Redelivery keeps child IDs and source revision"

        # Partial existing children retain human changes; missing parameters still create pending reviews.
        seed("partial")
        with repo._session() as session, session.begin():
            record = session.get(ReviewRecord, "partial")
            import copy
            snapshot = copy.deepcopy(record.review_snapshot)
            snapshot["multi_spec"]["variants"][1]["parameters"].pop("wire_diameter")
            record.review_snapshot = snapshot
            session.get(RecognitionJobRecord, "partial").status = "completed"
        value = manifest("partial")
        result = store.create_children(repo, "partial", OWNER["user_id"], {
            "variant_ids": [value["variants"][0]["variant_id"]], "expected_source_revision": value["source_revision"], "idempotency_key": "earlier-manual"}, OWNER, root)
        child_id = result["reviews"][0]["job_id"]
        with repo._session() as session, session.begin():
            child = session.get(ReviewRecord, child_id); child.drawing_name = "人工修改名称"
        reopen("partial"); assert complete("partial") is True
        with repo._session() as session:
            assert session.get(ReviewRecord, child_id).drawing_name == "人工修改名称"
        assert manifest("partial")["created_count"] == 3
        assert repo.get_review(manifest("partial")["variants"][1]["review"]["job_id"], owner_user_id=OWNER["user_id"])["review"]["spring_parameters"]["wire_diameter"]["value"] is None
        if repo._engine.dialect.name == "postgresql":
            # Disable the in-process mutex: database row locks must still serialize workers.
            from concurrent.futures import ThreadPoolExecutor
            from contextlib import nullcontext
            seed("concurrent-auto")
            with patch.object(store, "lock", lambda _: nullcontext()), ThreadPoolExecutor(2) as pool:
                outcomes = list(pool.map(lambda _: complete("concurrent-auto"), range(2)))
            assert outcomes.count(True) == 1 and outcomes.count(False) == 1
            assert manifest("concurrent-auto")["created_count"] == 3

        # A child deleted after success stays deleted even under task redelivery.
        first = manifest("automatic-3")["variants"][0]
        store.delete_family(repo, first["review"]["job_id"], OWNER["user_id"])
        reopen("automatic-3"); assert complete("automatic-3") is True
        deleted = manifest("automatic-3")
        assert deleted["variants"][0]["creation_status"] == "deleted" and deleted["created_count"] == 2
        # Only a new explicit manual operation can recreate it.
        result = store.create_children(repo, "automatic-3", OWNER["user_id"], {
            "variant_ids": [first["variant_id"]], "expected_source_revision": deleted["source_revision"], "idempotency_key": "explicit-recreation"}, OWNER, root)
        assert result["reviews"][0]["job_id"] != first["review"]["job_id"]

        # Fail after one child insertion, inside the final transaction.
        claimed = seed("rollback")
        original = repo._new_record; calls = []
        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2: raise RuntimeError("injected child persistence failure")
            return original(*args, **kwargs)
        with patch.object(repo, "_new_record", side_effect=fail_second): worker._process_job(claimed)
        failed = repo.get_recognition_job("rollback")
        assert failed["status"] == "failed" and "创建规格审图失败" in failed["error_message"]
        assert manifest("rollback")["created_count"] == 0 and manifest("rollback")["source_revision"] == 1
        with repo._session() as session:
            events = session.execute(select(ReviewChangeEvent).where(ReviewChangeEvent.review_job_id == "rollback")).scalars().all()
            assert not any(e.event_type == "variants_created" for e in events)
        # The real runner sees the saved source and skips the model on retry.
        repo.retry_recognition_job("rollback", owner_user_id=OWNER["user_id"])
        retry = repo.claim_next_recognition_job(worker.worker_id, lease_seconds=60)
        assert retry["options"]["auto_create_variants"] is True
        worker._process_job(retry)
        assert repo.get_recognition_job("rollback")["status"] == "completed" and manifest("rollback")["created_count"] == 3

        for name, mode in (("old-source", False), ("single", True)):
            job = seed(name, auto=mode, source=name != "single")
            assert complete(name) is None
            if name == "single":
                async def saved_single(*args, **kwargs): return {}
                with patch.object(workers, "run_recognition_job_record", saved_single): worker._process_job(job)
            else: worker._process_job(job)
            assert repo.get_recognition_job(name)["status"] == "completed"
            if name == "old-source": assert manifest(name)["created_count"] == 0 and manifest(name)["creation_mode"] == "manual"

        # Lease expiry during local preparation must prevent the final commit.
        seed("expired")
        def expire(stage, percent):
            with repo._session() as session, session.begin():
                session.get(RecognitionJobRecord, "expired").lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert complete("expired", expire) is False
        assert manifest("expired")["created_count"] == 0
        with repo._session() as session, session.begin():
            job = session.get(RecognitionJobRecord, "expired"); job.worker_id = "other-worker"
        worker._finalize_cancelled({"job_id": "expired", "owner": OWNER})
        assert repo.get_review("expired", owner_user_id=OWNER["user_id"]), "A stale worker cannot erase the source"
        repo.fail_recognition_job("expired", worker_id="other-worker", error_message="lease test ended")
        # Cancellation during preparation also rolls the final stage back.
        seed("cancelled")
        def cancel(stage, percent):
            with repo._session() as session, session.begin():
                session.get(RecognitionJobRecord, "cancelled").cancellation_requested = True
        assert complete("cancelled", cancel) is False
        assert manifest("cancelled")["created_count"] == 0
        # Source deletion wins the same source→task lock ordering.
        seed("deleted-source")
        def delete_source(stage, percent):
            if repo.get_review("deleted-source", owner_user_id=OWNER["user_id"]):
                store.delete_family(repo, "deleted-source", OWNER["user_id"], 1)
        try: complete("deleted-source", delete_source)
        except store.VariantStoreError as exc: assert exc.status == 404
        else: raise AssertionError("Deleted source must not recreate children")
        with repo._session() as session:
            assert not session.execute(select(ReviewRecord).where(ReviewRecord.parent_review_id == "deleted-source")).scalars().all()


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); url = f"sqlite+pysqlite:///{root/'automatic.db'}"
        repo = ReviewPersistence(url); repo._engine.dispose()
        repo._engine = create_engine(url, poolclass=NullPool); repo._session_factory = sessionmaker(repo._engine, expire_on_commit=False)
        repo.create_schema_for_testing()
        try: run_suite(repo, root)
        finally: repo.dispose()
    print("PASS automatic 3/13/50, atomic rollback, cached worker retry, ownership, legacy/single, lease/cancel/delete and no resurrection")


if __name__ == "__main__": main()
