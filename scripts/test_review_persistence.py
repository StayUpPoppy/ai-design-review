from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.review_persistence import ReviewPersistence, RevisionConflictError  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite+pysqlite:///{Path(directory) / 'review_persistence.db'}"
        repository = ReviewPersistence(database_url)
        repository.create_schema_for_testing()

        review = {
            "drawing_summary": {"drawing_no": "YD-001", "drawing_name": "test spring", "spring_type": "compression_spring"},
            "spring_parameters": {"wire_diameter": {"value": 1.5, "unit": "mm"}},
        }
        owner_a = {
            "user_id": "1001",
            "username": "engineer-a",
            "real_name": "Engineer A",
            "org_id": "org-a",
            "org_name": "Factory A",
        }
        owner_b = {
            "user_id": "1002",
            "username": "engineer-b",
            "real_name": "Engineer B",
            "org_id": "org-b",
            "org_name": "Factory B",
        }
        try:
            created = repository.create_review(
                "job001",
                review,
                file_info={"kind": "pdf"},
                artifact_dir="outputs/api_runs/job001",
                owner=owner_a,
            )
            assert created["revision"] == 1
            assert created["events"][0]["event_type"] == "review_created"

            updated_review = {
                **review,
                "spring_parameters": {"wire_diameter": {"value": 1.6, "unit": "mm", "need_human_review": True}},
            }
            saved = repository.save_review(
                "job001",
                updated_review,
                expected_revision=1,
                actor={"erp_user_id": "1001", "username": "engineer-a"},
                owner=owner_a,
                events=[
                    {
                        "event_type": "parameter_value_updated",
                        "target_field": "wire_diameter",
                        "source": "manual",
                        "before_state": {"value": 1.5},
                        "after_state": {"value": 1.6},
                        "metadata": {"client_event_id": "client-audit-001"},
                    }
                ],
            )
            assert saved["revision"] == 2
            assert saved["events"][0]["client_event_id"] == "client-audit-001"
            assert saved["events"][0]["actor"]["erp_user_id"] == "1001"

            stored = repository.get_review("job001", owner_user_id="1001")
            assert stored is not None
            assert stored["revision"] == 2
            assert stored["review"]["spring_parameters"]["wire_diameter"]["value"] == 1.6
            assert repository.get_review("job001", owner_user_id="1002") is None
            assert repository.list_reviews(owner_user_id="1002") == []

            events = repository.list_change_events("job001", owner_user_id="1001")
            assert [event["event_type"] for event in events] == ["parameter_value_updated", "review_created"]

            repository.create_review(
                "job002",
                {"drawing_summary": {"drawing_no": "YD-002", "drawing_name": "second review", "spring_type": "compression_spring", "overall_status": "need_review"}},
                owner=owner_a,
            )
            recent = repository.list_reviews(limit=1, owner_user_id="1001")
            assert len(recent) == 1
            assert recent[0]["job_id"] == "job002"
            assert recent[0]["drawing_no"] == "YD-002"
            assert recent[0]["overall_status"] == "need_review"

            assert repository.delete_review("job002", owner_user_id="1002") is False
            assert repository.delete_review("job002", owner_user_id="1001") is True
            assert repository.get_review("job002", owner_user_id="1001") is None
            assert repository.delete_review("job002", owner_user_id="1001") is False

            try:
                repository.save_review("job001", updated_review, expected_revision=1, owner=owner_a)
            except RevisionConflictError as exc:
                assert exc.current_revision == 2
            else:
                raise AssertionError("Expected optimistic revision conflict")
        finally:
            repository.dispose()

    print("review persistence tests passed")


if __name__ == "__main__":
    main()
