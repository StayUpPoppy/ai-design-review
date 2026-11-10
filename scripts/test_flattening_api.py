"""Flattening persistence and captured SW requests in a disposable offline database."""
from copy import deepcopy
from pathlib import Path
import tempfile
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_solidworks_push_api import api, OWNER, ready_review, create_request
from ai_design_review.review_persistence import ReviewPersistence, PersistenceError
from ai_design_review.generation_persistence import GenerationJobRecord


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'flattening.db'}")
        repository.create_schema_for_testing()
        old_repository, old_root, old_post = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api._post_solidworks_command
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = repository, root / "runs"
        api.API_RUN_ROOT.mkdir()
        submissions = []
        api._post_solidworks_command = lambda url, payload, **kwargs: submissions.append(deepcopy(payload))
        try:
            with TestClient(api.app) as client:
                repository.create_review("flattening", ready_review(), owner=OWNER)
                endpoint = "/api/reviews/flattening"
                original = deepcopy(repository.get_review("flattening", owner_user_id=OWNER["user_id"]))
                live = client.get(endpoint).json()
                assert live["spring_parameters"]["flattening"]["value"] == 0
                assert live["spring_parameters"]["flattening"]["need_human_review"]
                assert repository.get_review("flattening", owner_user_id=OWNER["user_id"]) == original, "GET must not persist defaults"
                pending = client.get(endpoint + "/generation-package").json()["parameter_package"]
                assert "flattening" not in pending["generation_parameters"]["spring_parameters"]
                created = client.post(endpoint + "/generation-jobs", json=create_request("flattening-pending"))
                assert created.status_code == 202, created.text
                frozen = created.json()["generation_job"]
                frozen_request = deepcopy(submissions[-1])
                assert "是否制扁" not in frozen_request["models"][0]["modelParameters"]
                revision = 1
                for value in (0, 1):
                    live = client.get(endpoint).json()
                    item = live["spring_parameters"]["flattening"]
                    item.update(value=value, need_human_review=False, confirmation_snapshot={"kind": "parameter", "value": value})
                    item["source"] = ["human_confirmed", *item["source"]]
                    events = [{"client_event_id": f"flattening-confirm-{value}", "event_type": "safe_fields_confirmed", "metadata": {"fields": ["flattening"]}}]
                    if value == 1:
                        events.insert(0, {"client_event_id": "flattening-edit-one", "event_type": "parameter_value_updated", "target_field": "flattening"})
                    body = {"review": live, "expected_revision": revision, "events": events}
                    with patch.object(repository, "save_review", side_effect=PersistenceError("模拟保存失败")):
                        failed = client.patch(endpoint, json=body)
                        assert failed.status_code >= 400
                    assert repository.get_review("flattening", owner_user_id=OWNER["user_id"])["revision"] == revision
                    saved = client.patch(endpoint, json=body)
                    assert saved.status_code == 200, saved.text
                    revision = saved.json()["review_revision"]
                    current = client.get(endpoint).json()["spring_parameters"]["flattening"]
                    assert current["value"] == value and current["need_human_review"] is False
                    assert current["default_source"] == "flattening-default/v1" and "solidworks_protocol_default" in current["source"]
                    package = client.get(endpoint + "/generation-package").json()["parameter_package"]
                    assert package["solidworks_preview"]["modelParameters"]["是否制扁"] == value
                    request = {**create_request(f"confirmed-{value}"), "expected_review_revision": revision}
                    new = client.post(endpoint + "/generation-jobs", json=request)
                    assert new.status_code == 202, new.text
                    assert submissions[-1]["models"][0]["modelParameters"]["是否制扁"] == value
                    stale = client.patch(endpoint, json=body)
                    assert stale.status_code == 409, stale.text
                live = client.get(endpoint).json()
                live["spring_parameters"]["flattening"].update(value=0, need_human_review=False)
                changed = client.patch(endpoint, json={"review": live, "expected_revision": revision,
                    "events": [{"event_type": "parameter_value_updated", "target_field": "flattening"}]})
                assert changed.status_code == 200, changed.text
                revision = changed.json()["review_revision"]
                item = client.get(endpoint).json()["spring_parameters"]["flattening"]
                assert item["need_human_review"] is True, "Changing a confirmed selection must revoke confirmation"
                assert "是否制扁" not in client.get(endpoint + "/generation-package").json()["parameter_package"]["solidworks_preview"]["modelParameters"]
                invalid = client.get(endpoint).json(); invalid["spring_parameters"]["flattening"]["value"] = 2
                assert client.patch(endpoint, json={"review": invalid, "expected_revision": revision,
                    "events": [{"event_type": "parameter_value_updated", "target_field": "flattening"}]}).status_code == 422
                with repository._session() as session:
                    stored = session.get(GenerationJobRecord, frozen["generation_id"])
                    assert stored.execution_options["solidworks_payload"] == frozen_request
                    stored.status = "failed"; session.commit()
                # Direct SW jobs require a new TaskId; queue-based original-parameter retries reuse the frozen package.
                assert client.post(f"/api/generation-jobs/{frozen['generation_id']}/retry").status_code == 409
                url = os.environ.pop("SOLIDWORKS_GENERATION_URL")
                try:
                    queued = client.post(endpoint + "/generation-jobs", json={**create_request("queued-legacy"), "expected_review_revision": revision})
                    assert queued.status_code == 202, queued.text
                    queued_job = queued.json()["generation_job"]
                    with repository._session() as session:
                        record = session.get(GenerationJobRecord, queued_job["generation_id"])
                        original_package = deepcopy(record.parameter_package)
                        record.status = "failed"; session.commit()
                    live = client.get(endpoint).json(); live["spring_parameters"]["flattening"].update(value=1, need_human_review=False)
                    assert client.patch(endpoint, json={"review": live, "expected_revision": revision,
                        "events": [{"event_type": "parameter_value_updated", "target_field": "flattening"}, {"event_type": "modified_value_confirmed", "target_field": "flattening"}]}).status_code == 200
                    retried = client.post(f"/api/generation-jobs/{queued_job['generation_id']}/retry")
                    assert retried.status_code in (200, 202), retried.text
                    assert retried.json()["generation_job"]["parameter_hash"] == queued_job["parameter_hash"]
                    with repository._session() as session:
                        job = session.get(GenerationJobRecord, queued_job["generation_id"])
                        assert job.parameter_package == original_package
                        assert "flattening" not in job.parameter_package["generation_parameters"]["spring_parameters"]
                finally:
                    os.environ["SOLIDWORKS_GENERATION_URL"] = url
                history = client.get(endpoint + "/changes").json()["events"]
                assert any(e["event_type"] == "safe_fields_confirmed" and "flattening" in (e.get("metadata") or {}).get("fields", []) for e in history)
        finally:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api._post_solidworks_command = old_repository, old_root, old_post
            repository.dispose()
    print("PASS flattening API: read-only defaults, batch 0/1, audit, failure/retry, CAS, edit revocation, captured SW and frozen retries")

if __name__ == "__main__": main()
