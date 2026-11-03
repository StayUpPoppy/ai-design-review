from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Never connect to a configured deployment database from this regression test.
os.environ["DATABASE_URL"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from ai_design_review import api, recognition_worker  # noqa: E402
from ai_design_review.generation_persistence import GenerationArtifactRecord, GenerationStore  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence, ReviewRecord  # noqa: E402


def payload(user_id: str = "cloud-a", **fields: object) -> dict[str, object]:
    return {"userId": user_id, "username": f"user-{user_id}", **fields}


def headers(value: object, *, name: str = "datynkinfo") -> dict[str, str]:
    return {"Cookie": f"{name}={quote(json.dumps(value))}"}


def session_tests(client: TestClient) -> None:
    for fields in (
        {},
        {"currentOrgId": None, "currentOrgName": None},
        {"currentOrgId": "", "currentOrgName": ""},
        {"currentOrgId": None, "currentOrgName": ""},
    ):
        response = client.get("/api/session", headers=headers(payload(**fields)))
        assert response.status_code == 200, response.text
        identity = response.json()["identity"]
        assert identity["user_id"] == "cloud-a"
        assert identity["real_name"] == identity["username"] == "user-cloud-a"
        assert identity["org_id"] == identity["org_name"] == ""
        assert identity["source"] == "erp_cookie_json"  # Keep the existing API shape.
        assert identity["is_mock"] is False

    complete = client.get("/api/session", headers=headers(payload(
        realName="云平台用户", currentOrgId=2, currentOrgName="工厂",
    )))
    assert complete.status_code == 200, complete.text
    assert complete.json()["identity"]["real_name"] == "云平台用户"
    assert complete.json()["identity"]["org_id"] == "2"
    assert complete.json()["identity"]["org_name"] == "工厂"

    cloud = headers(payload())["Cookie"]
    erp = headers(payload("erp-b", currentOrgId="erp-org", currentOrgName="ERP"), name="userinfo")["Cookie"]
    for cookie in (f"{cloud}; {erp}", f"{erp}; {cloud}"):
        response = client.get("/api/session", headers={"Cookie": cookie})
        assert response.status_code == 200, response.text
        assert response.json()["identity"]["user_id"] == "cloud-a"

    invalid_headers = [
        {},
        {"Cookie": erp},
        headers(payload(), name="erp_review_identity"),
        {"Cookie": "datynkinfo="},
        {"Cookie": "datynkinfo=%7B"},
        headers(None),
        headers([]),
        headers("not-an-object"),
        headers({"username": "missing-id"}),
        headers({"userId": "missing-username"}),
        headers(payload(user_id=" ")),
        headers(payload(username=None)),
        headers(payload(username=" ")),
        {"Cookie": f"datynkinfo=%7B; {erp}"},
    ]
    for request_headers in invalid_headers:
        response = client.get("/api/session", headers=request_headers)
        assert response.status_code == 401, response.text

    with patch.dict(os.environ, {"ERP_IDENTITY_COOKIE_NAME": "custom_identity"}):
        assert client.get("/api/session", headers=headers(payload())).status_code == 401
        custom = client.get("/api/session", headers=headers(payload(), name="custom_identity"))
        assert custom.status_code == 200, custom.text

    with patch.dict(os.environ, {"AI_REVIEW_IDENTITY_MODE": "mock"}):
        mocked = client.get("/api/session")
        assert mocked.status_code == 200, mocked.text
        assert mocked.json()["identity"]["is_mock"] is True


def recognition_tests(client: TestClient, repository: ReviewPersistence) -> str:
    user_a, user_b = headers(payload()), headers(payload("cloud-b"))
    other_cookie = headers(payload("erp-b"), name="userinfo")["Cookie"]
    mixed = {"Cookie": f"{user_a['Cookie']}; {other_cookie}"}
    worker = recognition_worker.RecognitionWorker()
    worker.worker_id = "cloud-identity-test"
    job_ids = []

    async def simulate_recognition(**kwargs: Any) -> dict[str, str]:
        identity = kwargs["identity"]
        assert identity.user_id == "cloud-a"
        assert identity.org_id == identity.org_name == ""
        assert await kwargs["drawing"].read() == b"test-drawing"
        job_id = kwargs["job_id"]
        job_dir = api.API_RUN_ROOT / job_id
        (job_dir / "pages").mkdir()
        (job_dir / "pages" / "page-1.png").write_bytes(b"test-preview")
        review = {"drawing_summary": {"drawing_no": job_id, "spring_type": "compression_spring"}}
        write_json(job_dir / "review.json", review)
        write_json(job_dir / "owner.json", identity.as_owner_dict())
        kwargs["progress_callback"]("saving_result", 95)
        api._create_review_persistence(job_id, review, file_info={}, artifact_dir=str(job_dir), identity=identity)
        return {"job_id": job_id}

    # Exercise the real queued-job runner and worker lifecycle, replacing only recognition execution.
    with patch.object(api, "run_recognition_execution", side_effect=simulate_recognition):
        for fields in (
            {},
            {"currentOrgId": None, "currentOrgName": None},
            {"currentOrgId": "", "currentOrgName": ""},
            {"currentOrgId": None, "currentOrgName": ""},
        ):
            upload_headers = {"Cookie": f"{headers(payload(**fields))['Cookie']}; {other_cookie}"}
            response = client.post("/api/reviews", headers=upload_headers,
                files={"drawing": ("cloud.png", b"test-drawing", "image/png")},
                data={"use_qwen": "false", "use_ocr": "false"})
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]
            job_ids.append(job_id)
            queued = repository.get_recognition_job(job_id, owner_user_id="cloud-a")
            assert queued and queued["status"] == "queued"
            status_path = f"/api/reviews/{job_id}/recognition-status"
            assert client.get(status_path, headers=user_a).status_code == 200
            assert client.get(status_path, headers=user_b).status_code == 404
            assert client.post(f"/api/reviews/{job_id}/retry", headers=user_b).status_code == 409
            assert client.delete(f"/api/reviews/{job_id}", headers=user_b).status_code == 404

            claimed = repository.claim_next_recognition_job(worker.worker_id, lease_seconds=60)
            assert claimed and claimed["job_id"] == job_id
            assert claimed["owner"]["org_id"] == claimed["owner"]["org_name"] == ""
            worker._process_job(claimed)
            completed = repository.get_recognition_job(job_id, owner_user_id="cloud-a")
            assert completed["status"] == "completed", completed
            assert client.get(status_path, headers=mixed).json()["recognition"]["status"] == "completed"
            assert client.get(f"/api/reviews/{job_id}", headers=mixed).status_code == 200
            assert client.get(f"/api/reviews/{job_id}", headers=user_b).status_code == 404
            artifact_path = f"/api/reviews/{job_id}/artifacts/pages/page-1.png"
            assert client.get(artifact_path, headers=mixed).content == b"test-preview"
            assert client.get(artifact_path, headers=user_b).status_code == 404
            with repository._session() as session:
                record = session.get(ReviewRecord, job_id)
                assert record.owner_org_id == record.owner_org_name == ""

    assert {row["job_id"] for row in client.get("/api/reviews", headers=mixed).json()["reviews"]} == set(job_ids)
    assert client.get("/api/reviews", headers=user_b).json()["reviews"] == []
    job_id = job_ids[0]
    review = repository.get_review(job_id, owner_user_id="cloud-a")["review"]
    saved = client.patch(f"/api/reviews/{job_id}", headers=mixed, json={
        "review": review, "expected_revision": 1,
        "events": [{"event_type": "parameter_value_updated", "source": "manual"}],
    })
    assert saved.status_code == 200, saved.text
    actor = repository.list_change_events(job_id, owner_user_id="cloud-a")[0]["actor"]
    assert actor["erp_user_id"] == "cloud-a"
    assert actor["department_id"] == actor["factory_name"] == ""
    return job_id


def generation_tests(client: TestClient, repository: ReviewPersistence, review_id: str) -> None:
    user_a, user_b = headers(payload()), headers(payload("cloud-b"))
    owner = client.get("/api/session", headers=user_a).json()["identity"]
    generation_id = "cloud-generation"
    job, created = GenerationStore(repository).create_job({
        "generation_id": generation_id, "review_job_id": review_id, "review_revision": 2,
        "idempotency_key": "cloud-test", "request_fingerprint": "cloud-fingerprint",
        "template_code": "test/cloud", "template_version": "v1", "worker_capability": "test",
        "parameter_schema_version": "spring_generation_parameters/v2", "parameter_hash": "test-hash",
        "parameter_package": {}, "requested_artifact_types": ["png"],
        "readiness": {"status": "ready", "summary": "Test fixture", "confirmed_core_count": 1, "core_field_count": 1},
    }, owner=owner)
    assert created and job["generation_id"] == generation_id
    relative_path = f"{generation_id}/preview.png"
    artifact_file = api.API_RUN_ROOT / "_generation_artifacts" / relative_path
    artifact_file.parent.mkdir(parents=True)
    artifact_file.write_bytes(b"generation-preview")
    with repository._session() as session, session.begin():
        session.add(GenerationArtifactRecord(
            artifact_id="cloud-preview", generation_id=generation_id, artifact_type="png",
            filename="preview.png", relative_path=relative_path, mime_type="image/png",
            size_bytes=len(b"generation-preview"), sha256=hashlib.sha256(b"generation-preview").hexdigest(),
            is_mock=True,
        ))

    paths = [
        f"/api/reviews/{review_id}/generation-jobs",
        f"/api/generation-jobs/{generation_id}",
        f"/api/generation-jobs/{generation_id}/artifacts",
        f"/api/generation-jobs/{generation_id}/artifacts/cloud-preview",
    ]
    for path in paths:
        response = client.get(path, headers=user_a)
        assert response.status_code == 200, response.text
        assert client.get(path, headers=user_b).status_code == 404
    assert client.get(paths[-1], headers=user_a).content == b"generation-preview"
    assert client.post(f"/api/generation-jobs/{generation_id}/cancel", headers=user_b).status_code == 404


def main() -> None:
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
        "AI_REVIEW_IDENTITY_MODE": "cookie_json",
        "AI_REVIEW_ALLOW_SQLITE_GENERATION_TESTS": "true",
    }):
        os.environ.pop("ERP_IDENTITY_COOKIE_NAME", None)  # Verify the new default name.
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'cloud_identity.db'}")
        repository.create_schema_for_testing()
        try:
            with patch.object(api, "REVIEW_PERSISTENCE", repository), \
                    patch.object(api, "API_RUN_ROOT", root / "runs"), \
                    patch.object(recognition_worker, "REVIEW_PERSISTENCE", repository), \
                    patch.object(recognition_worker, "API_RUN_ROOT", root / "runs"), \
                    TestClient(api.app) as client:
                session_tests(client)
                review_id = recognition_tests(client, repository)
                generation_tests(client, repository, review_id)
        finally:
            repository.dispose()
    print("Cloud identity tests passed: datynkinfo, optional organizations, queued recognition, and user isolation.")


if __name__ == "__main__":
    main()
