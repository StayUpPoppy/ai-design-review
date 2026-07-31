from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from ai_design_review import api  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


def cookie_value(*, user_id: str, username: str, org_id: str, org_name: str) -> str:
    return quote(
        json.dumps(
            {
                "userId": user_id,
                "username": username,
                "realName": username.title(),
                "currentOrgId": org_id,
                "currentOrgName": org_name,
            }
        )
    )


def main() -> None:
    previous_mode = os.environ.get("AI_REVIEW_IDENTITY_MODE")
    previous_cookie_name = os.environ.get("ERP_IDENTITY_COOKIE_NAME")
    os.environ["AI_REVIEW_IDENTITY_MODE"] = "cookie_json"
    os.environ["ERP_IDENTITY_COOKIE_NAME"] = "erp_review_identity"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'identity_isolation.db'}")
        repository.create_schema_for_testing()
        original_repository = api.REVIEW_PERSISTENCE
        original_run_root = api.API_RUN_ROOT
        try:
            api.REVIEW_PERSISTENCE = repository
            api.API_RUN_ROOT = root / "api_runs"
            job_dir = api.API_RUN_ROOT / "usera001"
            (job_dir / "pages").mkdir(parents=True)
            (job_dir / "pages" / "page-1.png").write_bytes(b"test-image")
            review = {"drawing_summary": {"drawing_no": "A-001", "spring_type": "compression_spring"}}
            owner = {"user_id": "123", "username": "admin", "real_name": "Admin", "org_id": "1", "org_name": "Headquarters"}
            write_json(job_dir / "review.json", review)
            write_json(job_dir / "owner.json", owner)
            repository.create_review("usera001", review, artifact_dir=str(job_dir), owner=owner)

            user_a = {"erp_review_identity": cookie_value(user_id="123", username="admin", org_id="1", org_name="Headquarters")}
            user_b = {"erp_review_identity": cookie_value(user_id="456", username="operator", org_id="2", org_name="Factory B")}
            with TestClient(api.app) as client:
                assert client.get("/api/session").status_code == 401
                session = client.get("/api/session", cookies=user_a)
                assert session.status_code == 200
                assert session.json()["identity"]["username"] == "admin"
                assert session.json()["identity"]["org_name"] == "Headquarters"
                assert [item["job_id"] for item in client.get("/api/reviews", cookies=user_a).json()["reviews"]] == ["usera001"]
                assert client.get("/api/reviews", cookies=user_b).json()["reviews"] == []
                assert client.get("/api/reviews/usera001", cookies=user_b).status_code == 404
                assert client.get("/api/reviews/usera001/artifacts/pages/page-1.png", cookies=user_b).status_code == 404
                assert client.get("/api/reviews/usera001/artifacts/pages/page-1.png", cookies=user_a).status_code == 200
                assert client.get("/artifacts/usera001/pages/page-1.png", cookies=user_a).status_code == 404
                assert client.get("/outputs/api_runs/usera001/pages/page-1.png", cookies=user_a).status_code == 404

                saved = client.patch(
                    "/api/reviews/usera001",
                    cookies=user_a,
                    json={"review": review, "expected_revision": 1, "events": [{"event_type": "parameter_value_updated", "source": "manual"}]},
                )
                assert saved.status_code == 200
                event = repository.list_change_events("usera001", owner_user_id="123")[0]
                assert event["actor"]["erp_user_id"] == "123"
                assert client.delete("/api/reviews/usera001", cookies=user_b).status_code == 404
        finally:
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_run_root
            repository.dispose()
            if previous_mode is None:
                os.environ.pop("AI_REVIEW_IDENTITY_MODE", None)
            else:
                os.environ["AI_REVIEW_IDENTITY_MODE"] = previous_mode
            if previous_cookie_name is None:
                os.environ.pop("ERP_IDENTITY_COOKIE_NAME", None)
            else:
                os.environ["ERP_IDENTITY_COOKIE_NAME"] = previous_cookie_name

    print("ERP identity isolation tests passed")


if __name__ == "__main__":
    main()
