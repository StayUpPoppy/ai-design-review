"""Decimal coil contract, editable names and frozen simulated SW tasks; temporary DB only."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import os

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review, create_request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from ai_design_review import standard_selector
from ai_design_review.generation_contract import normalize_generation_value
from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.generation_schemas import GenerationPositiveCoilParameter, GenerationParameterPackageV2
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_persistence import GenerationJobRecord
from ai_design_review.solidworks import build_solidworks_command


def main():
    for field in ("total_coils", "active_coils"):
        for value in (10, 10.5, 8.25, 8.25123456789):
            assert normalize_generation_value(field, value) == value
            assert GenerationPositiveCoilParameter(value=value, label=field, confirmation_source="human_confirmed").value == value
        for value in (None, "", "abc", 0, -1, True, False, float("nan"), float("inf"), float("-inf")):
            try:
                normalize_generation_value(field, value)
            except (ValueError, TypeError): pass
            else: raise AssertionError((field, value))
            try:
                GenerationPositiveCoilParameter(value=value, label=field, confirmation_source="human_confirmed")
            except ValidationError: pass
            else: raise AssertionError((field, value, "schema"))
    original = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness, standard_selector.standard_references, api._post_solidworks_command
    submissions = []
    api._post_solidworks_command = lambda url, payload, **kwargs: submissions.append(deepcopy(payload))
    api.verify_review_roughness = lambda *a, **k: None
    standard_selector.standard_references = lambda *a, **k: []
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api.REVIEW_PERSISTENCE = repo = ReviewPersistence(f"sqlite+pysqlite:///{root / 'decimal.db'}")
            repo.create_schema_for_testing(); api.API_RUN_ROOT = root / "runs"; api.API_RUN_ROOT.mkdir()
            review = ready_review()
            review["drawing_summary"]["drawing_name"] = "原始名称"
            review["spring_parameters"]["total_coils"]["value"] = 10.5
            review["spring_parameters"]["active_coils"]["value"] = 8.25
            repo.create_review("decimal", review, owner=OWNER)
            with TestClient(api.app) as client:
                endpoint = "/api/reviews/decimal"
                current = client.get(endpoint).json()
                for name in ("  客户 图纸-001  ", "", "图" * 512, "😀" * 512):
                    current["drawing_summary"]["drawing_name"] = name
                    saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"], "events": [{"client_event_id": f"name-{current['review_revision']}", "event_type": "drawing_name_updated", "target_field": "drawing_summary.drawing_name"}]})
                    assert saved.status_code == 200, saved.text
                    current = client.get(endpoint).json()
                    assert current["drawing_summary"]["drawing_name"] == name.strip()
                    listed = client.get("/api/reviews?limit=100").json()["reviews"][0]
                    assert listed["drawing_name"] == (name.strip() or None)
                    assert listed["drawing_no"] == "SW-PUSH-001"
                    package = client.get(endpoint + "/generation-package").json()["parameter_package"]
                    GenerationParameterPackageV2.model_validate(package)
                    model = build_solidworks_command("1000000001", package, current)["models"][0]
                    assert model["modelName"] == (name.strip() or package["source"]["spring_type_label"])
                    assert model["modelParameters"]["圈数"] == 10.5
                    assert model["modelParameters"]["有效圈数n"] == 8.25
                for name in ("图" * 513, "😀" * 513, 123):
                    invalid = deepcopy(current); invalid["drawing_summary"]["drawing_name"] = name
                    response = client.patch(endpoint, json={"review": invalid, "expected_revision": current["review_revision"]})
                    assert response.status_code == 422, response.text
                    assert client.get(endpoint).json()["review_revision"] == current["review_revision"]
                current["drawing_summary"]["drawing_name"] = "新任务冻结名称"
                saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"]})
                assert saved.status_code == 200, saved.text
                current = client.get(endpoint).json()
                request = {**create_request("decimal-frozen"), "expected_review_revision": current["review_revision"]}
                created = client.post(endpoint + "/generation-jobs", json=request)
                assert created.status_code == 202, created.text
                job = created.json()["generation_job"]
                frozen = deepcopy(submissions[-1]); model = frozen["models"][0]
                assert model["modelName"] == "新任务冻结名称"
                assert [model["modelParameters"][key] for key in ("圈数", "有效圈数n")] == [10.5, 8.25]
                current["drawing_summary"]["drawing_name"] = "后来的名称"
                for field, value in (("total_coils", 10.5123456789), ("active_coils", 8.25123456789)):
                    current["spring_parameters"][field]["value"] = value
                stale = deepcopy(current)
                saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"]})
                assert saved.status_code == 200, saved.text
                assert client.patch(endpoint, json={"review": stale, "expected_revision": stale["review_revision"]}).status_code == 409
                current = client.get(endpoint).json()
                new_package = client.get(endpoint + "/generation-package").json()["parameter_package"]
                assert new_package["solidworks_preview"]["modelParameters"]["圈数"] == 10.5123456789
                assert new_package["solidworks_preview"]["modelParameters"]["有效圈数n"] == 8.25123456789
                with repo._session() as session:
                    record = session.get(GenerationJobRecord, job["generation_id"])
                    assert record.parameter_package["source"]["drawing_name"] == "新任务冻结名称"
                    assert record.execution_options["solidworks_payload"] == frozen
                # Same frozen/idempotent task remains unchanged after review edits.
                assert client.post(endpoint + "/generation-jobs", json=request).status_code == 409
                assert len(submissions) == 1
                invalid = deepcopy(current); invalid["spring_parameters"]["active_coils"]["value"] = 11
                assert assess_generation_readiness(invalid)["status"] == "blocked"
                package = build_generation_parameter_package(current)
                assert package["source"]["drawing_name"] == "后来的名称"
                original_url = os.environ.pop("SOLIDWORKS_GENERATION_URL")
                try:
                    repo.create_review("decimal-retry", review, owner=OWNER)
                    queued = client.post("/api/reviews/decimal-retry/generation-jobs", json=create_request("decimal-original-retry"))
                    assert queued.status_code == 202, queued.text
                    retry_job = queued.json()["generation_job"]
                    with repo._session() as session:
                        record = session.get(GenerationJobRecord, retry_job["generation_id"])
                        record.status = "failed"; session.commit()
                    changed = deepcopy(review); changed["drawing_summary"]["drawing_name"] = "重试前的新名称"
                    changed["spring_parameters"]["total_coils"]["value"] = 11.5
                    assert client.patch("/api/reviews/decimal-retry", json={"review": changed, "expected_revision": 1}).status_code == 200
                    retried = client.post(f"/api/generation-jobs/{retry_job['generation_id']}/retry")
                    assert retried.status_code in (200, 202), retried.text
                    assert retried.json()["generation_job"]["parameter_hash"] == retry_job["parameter_hash"]
                    with repo._session() as session:
                        frozen_retry = session.get(GenerationJobRecord, retry_job["generation_id"]).parameter_package
                        assert frozen_retry["source"]["drawing_name"] == "原始名称"
                        assert frozen_retry["generation_parameters"]["spring_parameters"]["total_coils"]["value"] == 10.5
                finally: os.environ["SOLIDWORKS_GENERATION_URL"] = original_url
            print("Decimal coils/drawing name: finite numeric contract, precision, blank/512 limit, CAS, reopen, list, SW and frozen idempotency passed")
    finally:
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness, standard_selector.standard_references, api._post_solidworks_command = original


if __name__ == "__main__": main()
