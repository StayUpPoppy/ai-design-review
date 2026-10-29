"""Optional SW fields: disposable database and intercepted SW, no external requests."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile

from test_solidworks_push_api import api, OWNER, ready_review, create_request, parameter
from fastapi.testclient import TestClient
from pydantic import ValidationError
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_persistence import GenerationJobRecord
from ai_design_review.generation_schemas import GenerationParameterPackageV2


def optional_review():
    review = ready_review()
    parameters = review["spring_parameters"]
    parameters["outer_diameter"].update(tolerance_upper=1.5, tolerance_lower=-1.5)
    parameters["free_length"].update(tolerance_upper=.5, tolerance_lower=-.5)
    parameters["mean_diameter"] = {**parameter(29, "mm"), "tolerance_upper": .2, "tolerance_lower": -.2}
    parameters["perpendicularity"] = parameter(.01, "mm")
    return review


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'optional.db'}")
        repository.create_schema_for_testing()
        old_repository, old_root, old_post = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api._post_solidworks_command
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = repository, root / "runs"
        api.API_RUN_ROOT.mkdir()
        submissions = []
        api._post_solidworks_command = lambda url, payload, **kwargs: submissions.append(deepcopy(payload))
        try:
            with TestClient(api.app) as client:
                repository.create_review("optional", optional_review(), owner=OWNER)
                endpoint = "/api/reviews/optional"
                response = client.get(endpoint + "/generation-package")
                assert response.status_code == 200, response.text
                package = response.json()["parameter_package"]
                preview = package["solidworks_preview"]
                expected = {"外径": 1.5, "自由高度": .5, "中径": .2}
                assert preview["modelParametersTolerance"] == expected
                assert preview["titleBlockProperties"]["垂直度A"] == .01
                keys = list(preview)
                assert keys[keys.index("modelParameters") + 1] == "modelParametersTolerance"
                title_keys = list(preview["titleBlockProperties"])
                assert title_keys[title_keys.index("客户图号") + 1] == "垂直度A"
                GenerationParameterPackageV2.model_validate(package)
                for invalid in ({"外径": -1}, {"外径": "1.5"}, {"外径": True}, {"内径": 1}, {"外径": float("inf")}):
                    bad = deepcopy(package)
                    bad["solidworks_preview"]["modelParametersTolerance"] = invalid
                    try:
                        GenerationParameterPackageV2.model_validate(bad)
                        raise AssertionError(invalid)
                    except ValidationError:
                        pass
                created = client.post(endpoint + "/generation-jobs", json=create_request("optional-first"))
                assert created.status_code == 202, created.text
                first = created.json()["generation_job"]
                frozen_command = deepcopy(submissions[-1])
                frozen_model = frozen_command["models"][0]
                for key, value in preview.items():
                    assert frozen_model[key] == value, key
                with repository._session() as session:
                    frozen = session.get(GenerationJobRecord, first["generation_id"]).parameter_package
                    assert frozen["solidworks_preview"] == preview
                duplicate = client.post(endpoint + "/generation-jobs", json=create_request("optional-first"))
                assert duplicate.status_code == 200 and len(submissions) == 1

                changed = optional_review()
                changed["spring_parameters"]["outer_diameter"].update(tolerance_upper=.000012345, tolerance_lower=-.000012345)
                changed["spring_parameters"]["perpendicularity"]["value"] = 0
                changed["drawing_summary"]["drawing_no"] = ""
                saved = client.patch(endpoint, json={"review": changed, "expected_revision": 1})
                assert saved.status_code == 200, saved.text
                revision = saved.json()["review_revision"]
                current = client.get(endpoint + "/generation-package").json()["parameter_package"]["solidworks_preview"]
                assert current["modelParametersTolerance"]["外径"] == .000012345
                assert current["titleBlockProperties"]["垂直度A"] == 0 and "客户图号" not in current["titleBlockProperties"]
                request = {**create_request("optional-new"), "expected_review_revision": revision}
                second = client.post(endpoint + "/generation-jobs", json=request)
                assert second.status_code == 202, second.text
                assert second.json()["generation_job"]["parameter_hash"] != first["parameter_hash"]
                assert submissions[-1]["models"][0]["modelParametersTolerance"] == current["modelParametersTolerance"]
                old = client.get(f"/api/generation-jobs/{first['generation_id']}").json()["generation_job"]
                assert old["execution_options"]["solidworks_payload"] == frozen_command
                assert len(submissions) == 2
                assert client.post(endpoint + "/generation-jobs", json={**request, "idempotency_key": "optional-first"}).status_code == 409

                # Both old packages without the new fields and new packages survive original-parameter retry.
                original_url = os.environ.pop("SOLIDWORKS_GENERATION_URL")
                try:
                    for name, review in (("legacy", ready_review()), ("new", optional_review())):
                        job_id = "retry-" + name
                        repository.create_review(job_id, review, owner=OWNER)
                        queued = client.post(f"/api/reviews/{job_id}/generation-jobs", json=create_request("retry-" + name))
                        assert queued.status_code == 202, queued.text
                        job = queued.json()["generation_job"]
                        with repository._session() as session:
                            record = session.get(GenerationJobRecord, job["generation_id"])
                            original = deepcopy(record.parameter_package)
                            assert ("modelParametersTolerance" in original["solidworks_preview"]) == (name == "new")
                            record.status = "failed"
                            session.commit()
                        live = optional_review()
                        live["spring_parameters"]["perpendicularity"]["value"] = .5
                        assert client.patch(f"/api/reviews/{job_id}", json={"review": live, "expected_revision": 1}).status_code == 200
                        retried = client.post(f"/api/generation-jobs/{job['generation_id']}/retry")
                        assert retried.status_code in (200, 202), retried.text
                        assert retried.json()["generation_job"]["parameter_hash"] == job["parameter_hash"]
                        with repository._session() as session:
                            assert session.get(GenerationJobRecord, job["generation_id"]).parameter_package == original
                finally:
                    os.environ["SOLIDWORKS_GENERATION_URL"] = original_url
        finally:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api._post_solidworks_command = old_repository, old_root, old_post
            repository.dispose()
    print("PASS: optional tolerances/perpendicularity API schema, preview, captured SW, save/reopen, frozen fields, hashes, idempotency and legacy/new retries; temporary data only.")


if __name__ == "__main__":
    main()
