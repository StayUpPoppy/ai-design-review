from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review import api  # noqa: E402
from ai_design_review.identity import IdentityContext  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'review_deletion.db'}")
        repository.create_schema_for_testing()
        original_repository = api.REVIEW_PERSISTENCE
        original_run_root = api.API_RUN_ROOT
        try:
            api.REVIEW_PERSISTENCE = repository
            api.API_RUN_ROOT = root / "api_runs"
            job_dir = api.API_RUN_ROOT / "delete001"
            (job_dir / "pages").mkdir(parents=True)
            (job_dir / "pages" / "page-1.png").write_bytes(b"test-image")
            review = {"drawing_summary": {"drawing_no": "DEL-001", "spring_type": "compression_spring"}}
            identity = IdentityContext(
                user_id="1001",
                username="engineer-a",
                real_name="Engineer A",
                org_id="org-a",
                org_name="Factory A",
                source="mock",
            )
            write_json(job_dir / "review.json", review)
            write_json(job_dir / "owner.json", identity.as_owner_dict())
            repository.create_review("delete001", review, artifact_dir=str(job_dir), owner=identity.as_owner_dict())

            result = api.delete_existing_review("delete001", identity)
            assert result["deleted"] is True
            assert result["persistence"]["mode"] == "postgresql"
            assert result["artifact_cleanup"] == "deleted"
            assert repository.get_review("delete001", owner_user_id="1001") is None
            assert not job_dir.exists()
        finally:
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_run_root
            repository.dispose()

    print("review deletion API test passed")


if __name__ == "__main__":
    main()
