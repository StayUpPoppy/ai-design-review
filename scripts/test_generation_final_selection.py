"""Final-selection transaction regression; --postgres uses an isolated test schema."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["AI_REVIEW_ALLOW_SQLITE_GENERATION_TESTS"] = "true"
from ai_design_review.generation_persistence import FinalGenerationAlreadySelectedError, GenerationEventRecord, GenerationJobRecord, GenerationStore
from ai_design_review.review_persistence import Base, ReviewPersistence

OWNER = {"user_id": "qa-final-owner", "username": "QA final owner"}


def run(repository: ReviewPersistence, *, concurrent: bool = False) -> None:
    repository.create_review("qa-final-review", {"spring_parameters": {}, "technical_requirements": []}, owner=OWNER)
    store = GenerationStore(repository)
    for identifier in ("1000000001", "1000000002"):
        store.create_job({"generation_id": identifier, "review_job_id": "qa-final-review", "review_revision": 1,
            "idempotency_key": identifier, "request_fingerprint": identifier, "template_code": "qa-final",
            "template_version": "v1", "worker_capability": "qa", "parameter_schema_version": "v2",
            "parameter_hash": identifier, "parameter_package": {"frozen": identifier}, "readiness": {},
            "requested_artifact_types": [], "status": "completed", "execution_options": {"frozen": identifier}}, owner=OWNER)
    first, second = "1000000001", "1000000002"
    before_review = repository.get_review("qa-final-review", owner_user_id=OWNER["user_id"])
    with repository._session() as session:
        snapshots = {r.generation_id: (deepcopy(r.parameter_package), deepcopy(r.execution_options), r.status) for r in session.execute(select(GenerationJobRecord)).scalars()}
    assert store.approve_job(first, owner=OWNER, current_revision=1)["is_final"]
    assert store.approve_job(first, owner=OWNER, current_revision=1)["is_final"]
    try:
        store.approve_job(second, owner=OWNER, current_revision=1)
        raise AssertionError("direct replacement must fail")
    except FinalGenerationAlreadySelectedError as exc:
        assert exc.current_final_generation_id == first
    assert store.unapprove_job(first, owner={"user_id": "other"}) is None
    assert store.unapprove_job("missing", owner=OWNER) is None
    for _ in range(2):
        cleared = store.unapprove_job(first, owner=OWNER)
        assert not cleared["is_final"] and cleared["approved_by"] is None and cleared["approved_at"] is None
    with repository._session() as session:
        events = list(session.execute(select(GenerationEventRecord).where(GenerationEventRecord.event_type == "generation_unapproved")).scalars())
        assert len(events) == 1 and events[0].payload["previous_approved_by"] == OWNER
        assert events[0].payload["previous_approved_at"] and events[0].payload["cancelled_by"] == OWNER
    assert store.approve_job(second, owner=OWNER, current_revision=1)["is_final"]
    store.unapprove_job(first, owner=OWNER)
    assert store.get_job(second, owner_user_id=OWNER["user_id"])["is_final"]
    store.unapprove_job(second, owner=OWNER)
    if concurrent:
        for _ in range(4):
            barrier = Barrier(2)
            def approve(identifier):
                barrier.wait(timeout=10)
                try:
                    result = store.approve_job(identifier, owner=OWNER, current_revision=1)
                    return result["generation_id"]
                except FinalGenerationAlreadySelectedError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(approve, identifier) for identifier in (first, second)]
                winners = [result for f in futures if (result := f.result(timeout=20))]
            assert len(winners) == 1, winners
            selected = winners[0]
            barrier = Barrier(2)
            def cancel():
                barrier.wait(timeout=10)
                return store.unapprove_job(selected, owner=OWNER)
            with repository._session() as session:
                previous_count = len(list(session.execute(select(GenerationEventRecord).where(GenerationEventRecord.event_type == "generation_unapproved")).scalars()))
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(cancel), pool.submit(cancel)]
                assert all(not f.result(timeout=20)["is_final"] for f in futures)
            with repository._session() as session:
                assert len(list(session.execute(select(GenerationEventRecord).where(GenerationEventRecord.event_type == "generation_unapproved")).scalars())) == previous_count + 1
    with repository._session() as session:
        for record in session.execute(select(GenerationJobRecord)).scalars():
            assert (record.parameter_package, record.execution_options, record.status) == snapshots[record.generation_id]
    after_review = repository.get_review("qa-final-review", owner_user_id=OWNER["user_id"])
    assert before_review == after_review, "final selection must not alter review data or revision"


def main():
    if "--postgres" in sys.argv:
        schema = "qa_final_" + uuid.uuid4().hex
        admin = create_engine(os.environ["DATABASE_URL"])
        repository = ReviewPersistence(os.environ["DATABASE_URL"])
        try:
            with admin.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            repository._engine = repository._engine.execution_options(schema_translate_map={None: schema})
            repository._session_factory = sessionmaker(bind=repository._engine, expire_on_commit=False)
            Base.metadata.create_all(repository._engine)
            run(repository, concurrent=True)
        finally:
            repository.dispose()
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            admin.dispose()
        print("PASS: PostgreSQL final-selection parent locks, concurrent approve/cancel, idempotency and frozen snapshots")
    else:
        with tempfile.TemporaryDirectory() as directory:
            repository = ReviewPersistence(f"sqlite+pysqlite:///{Path(directory) / 'final.db'}")
            try:
                repository.create_schema_for_testing()
                run(repository)
            finally:
                repository.dispose()
        print("PASS: final-selection conflict, cancel audit, owner isolation, idempotency and frozen snapshots")


if __name__ == "__main__":
    main()
