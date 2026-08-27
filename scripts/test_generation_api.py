from __future__ import annotations

import os
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "generation-user-a"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "generation-user-a"
os.environ["AI_REVIEW_MOCK_REAL_NAME"] = "Generation User A"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "generation-factory-a"
os.environ["AI_REVIEW_MOCK_ORG_NAME"] = "Generation Factory A"
os.environ["GENERATION_WORKER_API_KEY"] = "test-worker-key"
os.environ["GENERATION_ADMIN_API_KEY"] = "test-admin-key"
os.environ["MOCK_SOLIDWORKS_ENABLED"] = "true"
os.environ["GENERATION_MAX_ARTIFACT_MB"] = "1"
os.environ["AI_REVIEW_ALLOW_SQLITE_GENERATION_TESTS"] = "true"

from ai_design_review import api  # noqa: E402
from ai_design_review.generation_persistence import GenerationEventRecord, GenerationJobRecord  # noqa: E402
from ai_design_review.mock_solidworks_worker import MockSolidWorksWorker, render_mock_artifacts  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


OWNER_A = {
    "user_id": "generation-user-a",
    "username": "generation-user-a",
    "real_name": "Generation User A",
    "org_id": "generation-factory-a",
    "org_name": "Generation Factory A",
}


def parameter(value: object, unit: str | None = None) -> dict[str, object]:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["test"]}


def ready_review(*, wire: float = 2.0, free_length: float = 50.0) -> dict[str, object]:
    return {
        "drawing_summary": {
            "drawing_no": "GEN-001",
            "drawing_name": "Mock compression spring",
            "spring_type": "compression_spring",
            "spring_type_label": "圆柱螺旋压缩弹簧",
        },
        "spring_parameters": {
            "material": parameter("60Si2MnA"),
            "wire_diameter": parameter(wire, "mm"),
            "outer_diameter": parameter(20.0, "mm"),
            "free_length": parameter(free_length, "mm"),
            "total_coils": parameter(10.0, "圈"),
            "active_coils": parameter(8.0, "圈"),
            "handedness": parameter("right"),
            "end_type": parameter("closed_and_ground"),
            "end_grinding": parameter("ground"),
            "load_points": [],
            "torque_points": [],
        },
        "standard_selection": {
            "selected_standard": None,
            "status": "not_started",
            "need_human_review": False,
            "human_confirmed": False,
        },
        "standardization_results": [],
        "technical_requirements": [
            {
                "requirement_id": "techreq_surface",
                "type": "surface",
                "content": "表面处理：表面镀锌。",
                "need_human_review": False,
            },
            {
                "requirement_id": "techreq_process",
                "type": "process",
                "content": "去除毛刺。\n不得有锐边。",
                "need_human_review": False,
            },
        ],
        "derived_parameters": {},
        "derived_parameters_stale": False,
    }


def set_mock_user(user_id: str) -> None:
    os.environ["AI_REVIEW_MOCK_USER_ID"] = user_id
    os.environ["AI_REVIEW_MOCK_USERNAME"] = user_id
    os.environ["AI_REVIEW_MOCK_REAL_NAME"] = user_id
    os.environ["AI_REVIEW_MOCK_ORG_ID"] = f"factory-{user_id}"
    os.environ["AI_REVIEW_MOCK_ORG_NAME"] = f"Factory {user_id}"


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'generation.db'}")
        repository.create_schema_for_testing()
        original_repository = api.REVIEW_PERSISTENCE
        original_run_root = api.API_RUN_ROOT
        api.REVIEW_PERSISTENCE = repository
        api.API_RUN_ROOT = root / "api_runs"
        api.API_RUN_ROOT.mkdir()
        repository.create_review("review-generation", ready_review(), owner=OWNER_A)
        try:
            with TestClient(api.app) as client:
                assert client.get("/docs").status_code == 200
                assert client.get("/docs").history[0].status_code == 307
                assert client.get("/api/docs").status_code == 200
                openapi_response = client.get("/api/openapi.json")
                assert openapi_response.status_code == 200
                openapi = openapi_response.json()
                assert "/api/reviews/{job_id}/generation-jobs" in openapi["paths"]
                assert "/api/generation-worker/jobs/claim" in openapi["paths"]
                assert "GenerationWorkerBearer" in openapi["components"]["securitySchemes"]
                assert "GenerationAdminBearer" in openapi["components"]["securitySchemes"]

                readiness = client.get("/api/reviews/review-generation/generation-readiness")
                assert readiness.status_code == 200, readiness.text
                readiness_view = readiness.json()["generation_readiness"]
                assert readiness_view["status"] == "ready_with_warnings"
                assert any(item["field"] == "standard_no" for item in readiness_view["warnings"])
                assert not any(item["field"] == "standard_no" for item in readiness_view["missing_fields"])
                package = client.get("/api/reviews/review-generation/generation-package")
                assert package.status_code == 200, package.text
                assert package.json()["parameter_package"]["schema_version"] == "spring_generation_parameters/v1"
                assert package.json()["parameter_package"]["standard_context"] == {
                    "selected_standard": None,
                    "selection_status": "not_started",
                    "human_confirmed": False,
                }
                frozen_parameters = package.json()["parameter_package"]["generation_parameters"]["spring_parameters"]
                assert set(frozen_parameters) == {
                    "wire_diameter", "mean_diameter", "free_length", "total_coils",
                    "active_coils", "handedness", "end_grinding", "end_coils_closed",
                }
                assert frozen_parameters["handedness"]["value"] == "right"
                assert frozen_parameters["end_grinding"]["value"] == 1
                assert frozen_parameters["end_coils_closed"]["value"] == 1
                package_technical_text = package.json()["parameter_package"]["generation_parameters"]["technical_requirements_text"]
                assert package_technical_text == "1.表面处理：表面镀锌。\n2.工艺要求：去除毛刺。；不得有锐边。"

                assert client.patch(
                    "/api/admin/generation-templates/mock/compression-spring/versions/v3/status",
                    json={"enabled": True},
                ).status_code == 401
                enabled = client.patch(
                    "/api/admin/generation-templates/mock/compression-spring/versions/v3/status",
                    headers=bearer("test-admin-key"),
                    json={"enabled": True},
                )
                assert enabled.status_code == 200, enabled.text
                assert enabled.json()["template"]["priority"] == 1002
                matched = client.post(
                    "/api/reviews/review-generation/generation-template-match",
                    json={},
                )
                assert matched.status_code == 200, matched.text
                assert matched.json()["template_match"]["selected_template"]["template_code"] == "mock/compression-spring"
                assert matched.json()["template_match"]["selected_template"]["version"] == "v3"

                request_body = {
                    "expected_review_revision": 1,
                    "idempotency_key": "review-generation-r1-first",
                    "requested_artifact_types": ["pdf"],
                    "mock_scenario": "success",
                }
                created = client.post("/api/reviews/review-generation/generation-jobs", json=request_body)
                assert created.status_code == 202, created.text
                first_job = created.json()["generation_job"]
                generation_id = first_job["generation_id"]
                duplicate = client.post("/api/reviews/review-generation/generation-jobs", json=request_body)
                assert duplicate.status_code == 200, duplicate.text
                assert duplicate.json()["created"] is False
                assert duplicate.json()["generation_job"]["generation_id"] == generation_id

                unauthenticated_claim = client.post(
                    "/api/generation-worker/jobs/claim",
                    json={"worker_id": "worker-a", "capabilities": ["mock_solidworks_compression_v1"]},
                )
                assert unauthenticated_claim.status_code == 401
                no_capability = client.post(
                    "/api/generation-worker/jobs/claim",
                    headers=bearer("test-worker-key"),
                    json={"worker_id": "wrong-worker", "capabilities": ["other"]},
                )
                assert no_capability.status_code == 204
                assert no_capability.content == b""
                claimed = client.post(
                    "/api/generation-worker/jobs/claim",
                    headers=bearer("test-worker-key"),
                    json={"worker_id": "worker-a", "capabilities": ["mock_solidworks_compression_v1"]},
                )
                assert claimed.status_code == 200, claimed.text
                worker_job = claimed.json()["generation_job"]
                assert worker_job["generation_id"] == generation_id
                assert worker_job["parameter_package"]["schema_version"] == "spring_generation_parameters/v1"
                claimed_parameters = worker_job["parameter_package"]["generation_parameters"]["spring_parameters"]
                assert claimed_parameters["mean_diameter"]["value"] == 18
                assert "outer_diameter" not in claimed_parameters
                assert (
                    worker_job["parameter_package"]["generation_parameters"]["technical_requirements_text"]
                    == package_technical_text
                )

                upload_too_early = client.post(
                    f"/api/generation-worker/jobs/{generation_id}/artifacts",
                    headers=bearer("test-worker-key"),
                    data={"worker_id": "worker-a", "artifact_type": "png", "is_mock": "true"},
                    files={"file": ("preview.png", b"png", "image/png")},
                )
                assert upload_too_early.status_code == 409
                for status, progress in (("generating_3d", 20), ("generating_2d", 55), ("uploading", 80)):
                    updated = client.patch(
                        f"/api/generation-worker/jobs/{generation_id}/status",
                        headers=bearer("test-worker-key"),
                        json={"worker_id": "worker-a", "status": status, "stage": status, "progress": progress},
                    )
                    assert updated.status_code == 200, updated.text
                no_preview = client.post(
                    f"/api/generation-worker/jobs/{generation_id}/complete",
                    headers=bearer("test-worker-key"),
                    json={"worker_id": "worker-a"},
                )
                assert no_preview.status_code == 409
                oversized = client.post(
                    f"/api/generation-worker/jobs/{generation_id}/artifacts",
                    headers=bearer("test-worker-key"),
                    data={"worker_id": "worker-a", "artifact_type": "png", "is_mock": "true"},
                    files={"file": ("too-large.png", b"x" * (1024 * 1024 + 1), "image/png")},
                )
                assert oversized.status_code == 413
                mime_mismatch = client.post(
                    f"/api/generation-worker/jobs/{generation_id}/artifacts",
                    headers=bearer("test-worker-key"),
                    data={"worker_id": "worker-a", "artifact_type": "pdf", "is_mock": "true"},
                    files={"file": ("wrong.pdf", b"not-pdf", "image/png")},
                )
                assert mime_mismatch.status_code == 415
                unsupported = client.post(
                    f"/api/generation-worker/jobs/{generation_id}/artifacts",
                    headers=bearer("test-worker-key"),
                    data={"worker_id": "worker-a", "artifact_type": "executable", "is_mock": "true"},
                    files={"file": ("bad.exe", b"bad", "application/octet-stream")},
                )
                assert unsupported.status_code == 400

                rendered = render_mock_artifacts(worker_job)
                assert {item[0] for item in rendered} == {"png", "pdf", "model_manifest", "log"}
                assert all(not item[1].lower().endswith((".sldprt", ".slddrw")) for item in rendered)
                # The real SolidWorks contract only uploads PDF. Upload the mock PDF
                # before any PNG and verify that the API creates the comparison preview.
                for artifact_type, filename, mime_type, content in rendered:
                    if artifact_type == "png":
                        continue
                    uploaded = client.post(
                        f"/api/generation-worker/jobs/{generation_id}/artifacts",
                        headers=bearer("test-worker-key"),
                        data={"worker_id": "worker-a", "artifact_type": artifact_type, "is_mock": "true"},
                        files={"file": (filename, content, mime_type)},
                    )
                    assert uploaded.status_code == 201, uploaded.text
                    artifact = uploaded.json()["artifact"]
                    assert artifact["is_mock"] is True
                    assert len(artifact["sha256"]) == 64

                completed = client.post(
                    f"/api/generation-worker/jobs/{generation_id}/complete",
                    headers=bearer("test-worker-key"),
                    json={"worker_id": "worker-a"},
                )
                assert completed.status_code == 200, completed.text
                assert completed.json()["generation_job"]["status"] == "completed"
                artifacts = client.get(f"/api/generation-jobs/{generation_id}/artifacts").json()["artifacts"]
                png = next(item for item in artifacts if item["artifact_type"] == "png")
                assert png["is_mock"] is True
                downloaded = client.get(png["url"])
                assert downloaded.status_code == 200
                assert downloaded.content.startswith(b"\x89PNG")
                approved = client.post(f"/api/generation-jobs/{generation_id}/approve")
                assert approved.status_code == 200, approved.text
                assert approved.json()["generation_job"]["is_final"] is True

                preview_failure = client.post(
                    "/api/reviews/review-generation/generation-jobs",
                    json={
                        **request_body,
                        "idempotency_key": "review-generation-r1-preview-failure",
                        "parent_generation_id": generation_id,
                    },
                )
                assert preview_failure.status_code == 202, preview_failure.text
                preview_failure_id = preview_failure.json()["generation_job"]["generation_id"]
                failed_preview_claim = client.post(
                    "/api/generation-worker/jobs/claim",
                    headers=bearer("test-worker-key"),
                    json={"worker_id": "preview-failure-worker", "capabilities": ["mock_solidworks_compression_v1"]},
                )
                assert failed_preview_claim.status_code == 200
                assert failed_preview_claim.json()["generation_job"]["generation_id"] == preview_failure_id
                for status, progress in (("generating_3d", 20), ("generating_2d", 55), ("uploading", 80)):
                    assert client.patch(
                        f"/api/generation-worker/jobs/{preview_failure_id}/status",
                        headers=bearer("test-worker-key"),
                        json={"worker_id": "preview-failure-worker", "status": status, "progress": progress},
                    ).status_code == 200
                invalid_pdf = client.post(
                    f"/api/generation-worker/jobs/{preview_failure_id}/artifacts",
                    headers=bearer("test-worker-key"),
                    data={"worker_id": "preview-failure-worker", "artifact_type": "pdf", "is_mock": "true"},
                    files={"file": ("invalid-but-retained.pdf", b"%PDF-1.4\ninvalid", "application/pdf")},
                )
                assert invalid_pdf.status_code == 201, invalid_pdf.text
                failed_preview_artifacts = client.get(
                    f"/api/generation-jobs/{preview_failure_id}/artifacts"
                ).json()["artifacts"]
                assert [item["artifact_type"] for item in failed_preview_artifacts] == ["pdf"]
                assert client.post(
                    f"/api/generation-worker/jobs/{preview_failure_id}/complete",
                    headers=bearer("test-worker-key"),
                    json={"worker_id": "preview-failure-worker"},
                ).status_code == 200
                with repository._session() as session:
                    preview_events = session.query(GenerationEventRecord).filter_by(
                        generation_id=preview_failure_id,
                        event_type="generation_preview_failed",
                    ).all()
                    assert len(preview_events) == 1

                updated_review = ready_review(wire=2.5, free_length=65.0)
                saved = repository.save_review(
                    "review-generation",
                    updated_review,
                    expected_revision=1,
                    owner=OWNER_A,
                )
                assert saved["revision"] == 2
                stale = client.get(f"/api/generation-jobs/{generation_id}")
                assert stale.status_code == 200 and stale.json()["generation_job"]["is_stale"] is True
                assert client.post(f"/api/generation-jobs/{generation_id}/approve").status_code == 409
                stale_revision = client.post(
                    "/api/reviews/review-generation/generation-jobs",
                    json={**request_body, "idempotency_key": "stale-revision", "expected_review_revision": 1},
                )
                assert stale_revision.status_code == 409
                second = client.post(
                    "/api/reviews/review-generation/generation-jobs",
                    json={
                        **request_body,
                        "idempotency_key": "review-generation-r2-second",
                        "expected_review_revision": 2,
                        "parent_generation_id": generation_id,
                        "mock_scenario": "fail_2d",
                    },
                )
                assert second.status_code == 202, second.text
                second_id = second.json()["generation_job"]["generation_id"]
                assert second.json()["generation_job"]["parent_generation_id"] == generation_id

                set_mock_user("generation-user-b")
                assert client.get(f"/api/generation-jobs/{generation_id}").status_code == 404
                assert client.get("/api/reviews/review-generation/generation-jobs").status_code == 404
                set_mock_user("generation-user-a")

                # Exercise the actual independent Worker implementation through HTTP only.
                mock_worker = MockSolidWorksWorker()
                mock_worker.client.close()
                mock_worker.client = client
                mock_worker.worker_id = "worker-b"
                mock_worker.delay = 0
                client.headers["Authorization"] = "Bearer test-worker-key"
                mock_worker._enable_mock_template()
                claimed_second = mock_worker.claim()
                assert claimed_second and claimed_second["generation_id"] == second_id
                first_preview = next(content for kind, _, _, content in rendered if kind == "png")
                second_preview = next(content for kind, _, _, content in render_mock_artifacts(claimed_second) if kind == "png")
                assert first_preview != second_preview
                mock_worker.process(claimed_second)
                failed = client.get(f"/api/generation-jobs/{second_id}")
                assert failed.status_code == 200
                assert failed.json()["generation_job"]["error_code"] == "mock_2d_failed"
                retried = client.post(f"/api/generation-jobs/{second_id}/retry")
                assert retried.status_code == 202, retried.text
                assert retried.json()["generation_job"]["status"] == "queued"
                assert retried.json()["generation_job"]["generation_id"] == second_id
                assert retried.json()["generation_job"]["attempt_count"] == 1
                cancelled = client.post(f"/api/generation-jobs/{second_id}/cancel")
                assert cancelled.status_code == 200
                assert cancelled.json()["generation_job"]["status"] == "cancelled"
                assert mock_worker.claim() is None

                timeout_created = client.post(
                    "/api/reviews/review-generation/generation-jobs",
                    json={
                        **request_body,
                        "idempotency_key": "review-generation-r2-timeout",
                        "expected_review_revision": 2,
                        "parent_generation_id": second_id,
                        "mock_scenario": "timeout",
                    },
                )
                assert timeout_created.status_code == 202
                timeout_id = timeout_created.json()["generation_job"]["generation_id"]
                mock_worker.worker_id = "lease-old-worker"
                leased = mock_worker.claim()
                assert leased and leased["generation_id"] == timeout_id
                with repository._session() as session:
                    record = session.get(GenerationJobRecord, timeout_id)
                    assert record is not None
                    record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    session.commit()
                mock_worker.worker_id = "lease-new-worker"
                reclaimed = mock_worker.claim()
                assert reclaimed and reclaimed["generation_id"] == timeout_id
                assert reclaimed["attempt_count"] == 2
                stale_worker_update = client.patch(
                    f"/api/generation-worker/jobs/{timeout_id}/status",
                    json={"worker_id": "lease-old-worker", "status": "generating_3d", "progress": 10},
                )
                assert stale_worker_update.status_code == 409
                mock_worker.process(reclaimed)
                timed_out = client.get(f"/api/generation-jobs/{timeout_id}")
                assert timed_out.status_code == 200
                assert timed_out.json()["generation_job"]["error_code"] == "mock_timeout"

            # Without a database only readiness/package remain available.
            local_review_id = "local-readiness-only"
            local_dir = api.API_RUN_ROOT / local_review_id
            local_dir.mkdir(parents=True)
            (local_dir / "review.json").write_text(json.dumps(ready_review(), ensure_ascii=False), encoding="utf-8")
            (local_dir / "owner.json").write_text(json.dumps(OWNER_A, ensure_ascii=False), encoding="utf-8")
            no_database = ReviewPersistence("")
            api.REVIEW_PERSISTENCE = no_database
            with TestClient(api.app) as local_client:
                assert local_client.get(f"/api/reviews/{local_review_id}/generation-readiness").status_code == 200
                assert local_client.get(f"/api/reviews/{local_review_id}/generation-package").status_code == 200
                assert local_client.get("/api/generation-templates").status_code == 503
                assert local_client.get(f"/api/reviews/{local_review_id}/generation-jobs").status_code == 503
        finally:
            set_mock_user("generation-user-a")
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_run_root
            repository.dispose()

    print("generation API closed-loop tests passed")


if __name__ == "__main__":
    main()
