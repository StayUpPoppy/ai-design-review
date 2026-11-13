"""Temporary-DB API validation; no recognition or external SW requests."""
from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
from test_generation_api import api, ready_review, OWNER_A
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_persistence import GenerationJobRecord
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.generation_service import stable_payload_hash


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'output.db'}")
        repository.create_schema_for_testing()
        old_repository, old_root = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = repository, root / "api_runs"
        api.API_RUN_ROOT.mkdir()
        repository.create_review("output-delete", ready_review(), owner=OWNER_A)
        try:
            with TestClient(api.app) as client:
                url = "/api/reviews/output-delete"
                initial = client.get(url).json()
                saved = client.patch(url, json={"review": initial, "expected_revision": initial["review_revision"]})
                assert saved.status_code == 200, saved.text
                package = client.get(url + "/generation-package")
                assert package.status_code == 200, package.text
                payload = package.json()
                frozen = deepcopy(payload["parameter_package"])
                projection = payload["technical_requirements_projection"]
                assert projection["text"] == frozen["solidworks_preview"]["technicalRequirements"]["技术要求"]
                assert all(entry["source_key"] and entry["basis"] for entry in projection["entries"])
                entry = next(entry for entry in projection["entries"] if entry["source_key"] == "auto:handedness")
                review = client.get(url).json()
                original_parameters = deepcopy(review["spring_parameters"])
                review["technical_output_deletions"] = [{key: deepcopy(entry[key]) for key in ("source_key", "fields", "load_point_ids", "basis")}]
                patch = client.patch(url, json={"review": review, "expected_revision": payload["review_revision"], "events": [{
                    "client_event_id": "delete-output-direction", "event_type": "technical_output_deleted", "target_field": "technical_output_deletions",
                    "before_state": {"value": []}, "after_state": {"value": review["technical_output_deletions"]}}]})
                assert patch.status_code == 200, patch.text
                revision = patch.json()["review_revision"]
                reopened = client.get(url).json()
                assert reopened["spring_parameters"] == original_parameters
                assert reopened["technical_output_deletions"] == review["technical_output_deletions"]
                current = client.get(url + "/generation-package").json()
                assert "旋向" not in current["technical_requirements_projection"]["text"]
                assert stable_payload_hash(current["parameter_package"]) != stable_payload_hash(frozen)
                command = build_solidworks_command("1000000001", current["parameter_package"], reopened)
                assert command["models"][0]["technicalRequirements"]["技术要求"] == current["technical_requirements_projection"]["text"]
                assert command["models"][0]["customProperties"]["旋向"] == "右旋"
                assert build_solidworks_command("1000000002", frozen, reopened)["models"][0]["technicalRequirements"]["技术要求"] == projection["text"]
                # Existing task creation/freezing accepts the new review metadata.
                body = {"expected_review_revision": revision, "idempotency_key": "deleted-direction-v1", "requested_artifact_types": ["pdf"], "mock_scenario": "success"}
                created = client.post(url + "/generation-jobs", json=body)
                assert created.status_code == 202, created.text
                task = created.json()["generation_job"]
                with repository._session() as session:
                    task_package = deepcopy(session.get(GenerationJobRecord, task["generation_id"]).parameter_package)
                assert "旋向" not in task_package["solidworks_preview"]["technicalRequirements"]["技术要求"]
                again = client.post(url + "/generation-jobs", json=body)
                assert again.status_code == 200 and again.json()["generation_job"]["generation_id"] == task["generation_id"]
                stale = client.patch(url, json={"review": reopened, "expected_revision": revision - 1})
                assert stale.status_code == 409
                reopened["spring_parameters"]["handedness"]["value"] = "left"
                changed = client.patch(url, json={"review": reopened, "expected_revision": revision})
                assert changed.status_code == 200, changed.text
                latest = client.get(url).json()
                assert not latest["technical_output_deletions"]
                assert "旋向：左" in client.get(url + "/generation-package").json()["technical_requirements_projection"]["text"]
                with repository._session() as session:
                    assert session.get(GenerationJobRecord, task["generation_id"]).parameter_package == task_package
                assert client.get(f"/api/generation-jobs/{task['generation_id']}").json()["generation_job"]["parameter_hash"] == task["parameter_hash"]
        finally:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = old_repository, old_root
            repository.dispose()
    print("PASS technical-output API: typed provenance, save/reopen/audit, CAS, input expiry, unchanged engineering inputs, mock task freezing/idempotency and historical request stability")


if __name__ == "__main__":
    main()
