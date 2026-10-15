import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from test_support_coils import baseline

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "support-coils-test"
from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.io_utils import write_json
from ai_design_review.review_persistence import ReviewPersistence


def main():
    with tempfile.TemporaryDirectory(prefix="support-coils-") as directory:
        root = Path(directory); job = root / "support"; job.mkdir()
        write_json(job / "review.json", baseline())
        write_json(job / "owner.json", {"user_id": "support-coils-test"})
        original = (job / "review.json").read_bytes()
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")), TestClient(api.app) as client:
            r = client.get("/api/reviews/support").json()
            p = r["spring_parameters"]; s = p["support_coils"]
            assert s["value"] == 1 and s["support_coils_original"]["value"] == 2
            assert (job / "review.json").read_bytes() == original, "GET must not silently save corrections"
            s["support_coils_adjustment"]["audit_recorded"] = True
            assert client.patch("/api/reviews/support", json={"review": r, "events": [{"event_type": "support_coils_recalculated", "target_field": "support_coils", "before_state": {"value": 2}, "after_state": {"value": 1}}]}).status_code == 200
            for field in ("total_coils", "active_coils", "support_coils"):
                p[field]["need_human_review"] = False
            r["manual_confirmations"]["support_coils"] = {"confirmed": True, "value": 1}
            s["confirmation_snapshot"] = {"kind": "parameter", "value": 1}
            assert client.patch("/api/reviews/support", json={"review": r}).status_code == 200
            p["total_coils"].update(value=18, source=["human_edited"], need_human_review=True)
            assert client.patch("/api/reviews/support", json={"review": r}).status_code == 200
            r = client.get("/api/reviews/support").json(); p = r["spring_parameters"]
            assert p["support_coils"]["value"] == 1 and p["support_coils"]["support_coils_waiting_confirmation"]
            p["total_coils"]["need_human_review"] = False
            assert client.patch("/api/reviews/support", json={"review": r}).status_code == 200
            r = client.get("/api/reviews/support").json(); s = r["spring_parameters"]["support_coils"]
            assert s["value"] == 2 and s["need_human_review"] and not s["derived_value_stale"]
            assert "support_coils" not in r["manual_confirmations"] and "confirmation_snapshot" not in s
            assert s["support_coils_adjustment"]["previous_confirmation"]["confirmed"]
            assert client.get("/api/reviews/support").json()["spring_parameters"]["support_coils"] == s
            # Explicit/manual values stay intact with a conflict, including a manual blank.
            s.update(value=3, source=["human_edited"], need_human_review=False)
            assert client.patch("/api/reviews/support", json={"review": r}).status_code == 200
            reopened = client.get("/api/reviews/support").json()
            assert reopened["spring_parameters"]["support_coils"]["value"] == 3
            assert reopened["spring_parameters"]["support_coils"]["support_coils_conflict"]
            reopened["spring_parameters"]["support_coils"].update(value="", need_human_review=True)
            assert client.patch("/api/reviews/support", json={"review": reopened}).status_code == 200
            assert client.get("/api/reviews/support").json()["spring_parameters"]["support_coils"]["value"] == ""
    print("Support coil API passed: GET read-only, save/reopen, confirmed-input recalculation, revoked snapshot and manual protection")


if __name__ == "__main__":
    main()
