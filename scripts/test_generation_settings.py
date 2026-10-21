"""Offline API coverage: disposable SQLite, saved samples, no SW/model requests."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review, create_request
from fastapi.testclient import TestClient
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_persistence import GenerationStore, GenerationJobRecord
from ai_design_review.generation_settings import normalize_generation_settings
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.generation_schemas import GenerationParameterPackageV2
from ai_design_review.solidworks import build_solidworks_command


def main():
    assert normalize_generation_settings({"username": " 阿拉伯特 "}) == {"drawing_model": "X型", "username": "阿拉伯特"}
    assert normalize_generation_settings({"username": ""}, allow_blank=True)["username"] == ""
    for settings in [{"drawing_model": "Z型", "username": "甲"}, {"username": " "}, {"username": "甲" * 257}, {"username": 123}]:
        try:
            normalize_generation_settings(settings)
            raise AssertionError(settings)
        except ValueError:
            pass
    legacy = build_generation_parameter_package(ready_review())
    assert "generation_settings" not in legacy
    assert "Username" not in build_solidworks_command("1000000001", legacy, {**ready_review(), "generation_settings": {"drawing_model": "Y型", "username": "新姓名"}})["models"][0]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'settings.db'}")
        repository.create_schema_for_testing()
        repository.create_review("settings", ready_review(), owner=OWNER)
        old_repository, old_root, old_post = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api._post_solidworks_command
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = repository, root / "runs"
        api.API_RUN_ROOT.mkdir()
        submissions = []
        api._post_solidworks_command = lambda url, payload, **kwargs: submissions.append(deepcopy(payload))
        try:
            with TestClient(api.app) as client:
                endpoint = "/api/reviews/settings"
                preview = client.get(endpoint + "/generation-package")
                assert preview.status_code == 200, preview.text
                package = preview.json()["parameter_package"]
                assert package["generation_settings"] == {"drawing_model": "X型", "username": OWNER["real_name"]}
                assert package["solidworks_preview"]["DrawingModel"] == "X型"
                assert GenerationParameterPackageV2.model_validate(package).model_dump()["generation_settings"] == package["generation_settings"]
                created = client.post(endpoint + "/generation-jobs", json=create_request("settings-legacy-default"))
                assert created.status_code == 202, created.text
                first = created.json()["generation_job"]
                assert first["generation_settings"] == package["generation_settings"]
                original_name = os.environ["AI_REVIEW_MOCK_REAL_NAME"]
                try:
                    os.environ["AI_REVIEW_MOCK_REAL_NAME"] = "同一修订的新署名"
                    same_revision = client.post(endpoint + "/generation-jobs", json=create_request("settings-legacy-default"))
                    assert same_revision.status_code == 409, "Resolved settings must participate in the fingerprint even at the same review revision"
                finally:
                    os.environ["AI_REVIEW_MOCK_REAL_NAME"] = original_name
                review = ready_review()
                before_parameters = deepcopy(review["spring_parameters"])
                review["generation_settings"] = {"drawing_model": "Y型", "username": " 阿拉伯特 "}
                saved = client.patch(endpoint, json={"review": review, "expected_revision": 1})
                assert saved.status_code == 200, saved.text
                revision = saved.json()["review_revision"]
                reopened = client.get(endpoint).json()
                assert reopened["generation_settings"] == {"drawing_model": "Y型", "username": "阿拉伯特"}
                for key, parameter in before_parameters.items():
                    if isinstance(parameter, dict) and "need_human_review" in parameter:
                        assert reopened["spring_parameters"][key]["need_human_review"] == parameter["need_human_review"], key
                request = {**create_request("settings-portrait"), "expected_review_revision": revision}
                second = client.post(endpoint + "/generation-jobs", json=request)
                assert second.status_code == 202, second.text
                second_job = second.json()["generation_job"]
                assert second_job["generation_settings"] == reopened["generation_settings"]
                model = submissions[-1]["models"][0]
                assert (model["DrawingModel"], model["Username"]) == ("Y型", "阿拉伯特")
                assert "Username" not in model["modelParameters"] and "DrawingModel" not in model["titleBlockProperties"]
                assert client.post(endpoint + "/generation-jobs", json=request).status_code == 200
                assert len(submissions) == 2
                reused = {**request, "idempotency_key": "settings-legacy-default"}
                assert client.post(endpoint + "/generation-jobs", json=reused).status_code == 409
                frozen = GenerationStore(repository).get_job(first["generation_id"], owner_user_id=OWNER["user_id"])
                assert frozen["generation_settings"] == package["generation_settings"]
                with repository._session() as session:
                    record = session.get(GenerationJobRecord, first["generation_id"])
                    assert record.parameter_package["generation_settings"] == package["generation_settings"]
                    assert record.owner_username == OWNER["username"]
                assert frozen["execution_options"]["solidworks_payload"]["models"][0]["Username"] == OWNER["real_name"]
                assert frozen["parameter_hash"] != second_job["parameter_hash"]
                review["generation_settings"]["username"] = ""
                saved = client.patch(endpoint, json={"review": review, "expected_revision": revision})
                assert saved.status_code == 200, saved.text
                assert client.get(endpoint).json()["generation_settings"]["username"] == ""
                assert client.get(endpoint + "/generation-package").status_code == 422
                invalid_create = {**create_request("settings-empty-name"), "expected_review_revision": saved.json()["review_revision"]}
                assert client.post(endpoint + "/generation-jobs", json=invalid_create).status_code == 422
                assert len(submissions) == 2
                for settings in [{"drawing_model": "Z型", "username": "甲"}, {"username": "甲" * 257}]:
                    review["generation_settings"] = settings
                    assert client.patch(endpoint, json={"review": review, "expected_revision": saved.json()["review_revision"]}).status_code == 422
                # Exercise the existing worker-compatible original-parameter retry.
                original_url = os.environ.pop("SOLIDWORKS_GENERATION_URL")
                try:
                    mock_review = ready_review()
                    mock_review["generation_settings"] = {"drawing_model": "Y型", "username": "原任务署名"}
                    repository.create_review("settings-retry", mock_review, owner=OWNER)
                    queued = client.post("/api/reviews/settings-retry/generation-jobs", json=create_request("settings-original-retry"))
                    assert queued.status_code == 202, queued.text
                    frozen_job = queued.json()["generation_job"]
                    with repository._session() as session:
                        record = session.get(GenerationJobRecord, frozen_job["generation_id"])
                        record.status = "failed"
                        session.commit()
                    mock_review["generation_settings"] = {"drawing_model": "X型", "username": "后续的新署名"}
                    changed = client.patch("/api/reviews/settings-retry", json={"review": mock_review, "expected_revision": 1})
                    assert changed.status_code == 200, changed.text
                    retried = client.post(f"/api/generation-jobs/{frozen_job['generation_id']}/retry")
                    assert retried.status_code in (200, 202), retried.text
                    assert retried.json()["generation_job"]["generation_settings"] == frozen_job["generation_settings"]
                    assert retried.json()["generation_job"]["parameter_hash"] == frozen_job["parameter_hash"]
                finally:
                    os.environ["SOLIDWORKS_GENERATION_URL"] = original_url
        finally:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api._post_solidworks_command = old_repository, old_root, old_post
    print("PASS: drawing orientation/name defaults, draft validation, save/reopen, unchanged confirmations, schema, SW placement, frozen history, hashes/idempotency and invalid input; mock SW only.")


if __name__ == "__main__":
    main()
