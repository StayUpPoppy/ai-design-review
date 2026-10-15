from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "solidworks-push-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "solidworks-push-user"
os.environ["AI_REVIEW_MOCK_REAL_NAME"] = "SolidWorks Push User"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "solidworks-push-factory"
os.environ["AI_REVIEW_MOCK_ORG_NAME"] = "SolidWorks Push Factory"
os.environ["AI_REVIEW_ALLOW_SQLITE_GENERATION_TESTS"] = "true"
os.environ["MOCK_SOLIDWORKS_ENABLED"] = "false"
os.environ["SOLIDWORKS_GENERATION_URL"] = "http://solidworks.test/solidworks/command"
os.environ["SOLIDWORKS_REQUEST_TIMEOUT_SECONDS"] = "10"
os.environ["GENERATION_MAX_ARTIFACT_MB"] = "1"

from ai_design_review import api  # noqa: E402
from ai_design_review.generation_persistence import GenerationEventRecord, GenerationJobRecord  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402
from ai_design_review.solidworks import build_solidworks_command  # noqa: E402


OWNER = {
    "user_id": "solidworks-push-user",
    "username": "solidworks-push-user",
    "real_name": "SolidWorks Push User",
    "org_id": "solidworks-push-factory",
    "org_name": "SolidWorks Push Factory",
}


def parameter(value: object, unit: str | None = None) -> dict[str, object]:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["test"]}


def ready_review() -> dict[str, object]:
    return {
        "drawing_summary": {
            "drawing_no": "SW-PUSH-001",
            "drawing_name": "压缩弹簧",
            "spring_type": "compression_spring",
            "spring_type_label": "压缩弹簧",
        },
        "spring_parameters": {
            "material": parameter("60Si2Mn"),
            "wire_diameter": parameter(3, "mm"),
            "outer_diameter": parameter(32, "mm"),
            "free_length": parameter(50, "mm"),
            "total_coils": parameter(9, "圈"),
            "active_coils": parameter(7, "圈"),
            "support_coils": parameter(1, "圈"), "pitch": parameter(6.5, "mm"),
            "surface_roughness_ra": {
                **parameter(12.5, "μm"),
                "surface_location": "两端面",
            },
            "handedness": parameter("left"),
            "end_type": parameter("closed_and_ground"),
            "end_grinding": parameter("ground"),
            "solid_height": {**parameter(25, "mm"), "value_kind": "input_height"},
            "load_points": [
                {"label": "Fb", "height": 25, "force": 2300, "need_human_review": False},
                {"label": "F1", "height": 38, "force": 2000, "need_human_review": False},
                {"label": "F2", "height": 43, "force": 2100, "need_human_review": False},
            ],
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
            {"requirement_id": "tech-1", "type": "other", "content": "端圈并紧磨平。", "need_human_review": False},
            {"requirement_id": "tech-2", "type": "surface", "content": "表面喷丸处理。", "need_human_review": False},
            {"requirement_id": "tech-3", "type": "surface", "content": "表面处理：表面喷丸处理。", "page": 2, "recognition_key": "note-other-position", "need_human_review": False},
            {"requirement_id": "tech-4", "type": "heat_treatment", "content": "热处理：热处理要求：300℃/20min。", "need_human_review": False},
            {"requirement_id": "tech-5", "type": "heat_treatment", "content": "300 °C/20 min", "need_human_review": False},
        ],
        "derived_parameters": {},
        "derived_parameters_stale": False,
    }


def pdf_base64(*, color: str = "white") -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), color).save(buffer, format="PDF")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def create_request(key: str) -> dict[str, object]:
    return {
        "expected_review_revision": 1,
        "idempotency_key": key,
        "requested_artifact_types": ["pdf"],
    }


def assert_optional_solidworks_fields_are_explicit_null() -> None:
    payload = build_solidworks_command(
        "1000000000",
        {
            "source": {"drawing_name": "压缩弹簧", "spring_type_label": "压缩弹簧"},
            "generation_parameters": {
                "spring_parameters": {
                    "wire_diameter": {"value": 3},
                    "mean_diameter": {"value": 29},
                    "free_length": {"value": 50},
                    "total_coils": {"value": 9},
                    "handedness": {"value": "right"},
                },
                "load_points": [],
                "technical_requirements_text": "",
            },
        },
        {"spring_parameters": {"solid_height": {"value": 25, "need_human_review": True, "value_kind": "input_height"}}},
    )
    model = payload["models"][0]
    assert model["modelParameters"]["有效圈数n"] is None
    assert model["modelParameters"]["是否磨平"] is None
    assert model["modelParameters"]["是否并紧"] is None
    assert set(model["modelParameters"]) == {"线径", "中径", "自由高度", "圈数", "有效圈数n", "是否磨平", "是否并紧"}
    assert "P'" not in model["extraProperties"]
    assert "Hb =" not in model["extraProperties"]["技术要求"]
    assert model["customProperties"] == {"旋向": "右旋"}
    assert model["titleBlockProperties"] == {}

    confirmed = build_solidworks_command(
        "1000000001",
        {
            "source": {"drawing_name": "压缩弹簧"},
            "generation_parameters": {
                "spring_parameters": {
                    "wire_diameter": {"value": 3}, "mean_diameter": {"value": 29},
                    "free_length": {"value": 50}, "total_coils": {"value": 9},
                    "handedness": {"value": "right"},
                },
                "load_points": [], "technical_requirements_text": "",
            },
        },
        {"spring_parameters": {"solid_height": {"value": 35, "need_human_review": False, "value_kind": "input_height"}}},
    )
    assert "Hb = 35 mm" in confirmed["models"][0]["extraProperties"]["技术要求"]

    legacy_package = {
        "source": {"drawing_name": "压缩弹簧"},
        "generation_parameters": {
            "spring_parameters": {},
            "load_points": [],
            "technical_requirements_text": "1.其他要求：端圈并紧磨平。",
        },
    }
    review = {"spring_parameters": {}}
    legacy_text = build_solidworks_command("1000000002", legacy_package, review)["models"][0]["extraProperties"]["技术要求"]
    assert legacy_text == "1.其他要求：端圈并紧磨平。"
    legacy_package["generation_parameters"]["technical_requirements_text"] = "技术要求\n" + legacy_text
    assert build_solidworks_command("1000000003", legacy_package, review)["models"][0]["extraProperties"]["技术要求"] == legacy_text


def main() -> None:
    assert_optional_solidworks_fields_are_explicit_null()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'solidworks_push.db'}")
        repository.create_schema_for_testing()
        repository.create_review("review-solidworks-push", ready_review(), owner=OWNER)
        original_repository = api.REVIEW_PERSISTENCE
        original_run_root = api.API_RUN_ROOT
        original_post = api._post_solidworks_command
        original_http_post = api.httpx.post
        original_preview_renderer = api.render_pdf_with_pdftoppm
        original_sleep = api.time.sleep
        submissions: list[dict[str, object]] = []

        def accept_command(url: str, payload: dict[str, object], *, timeout_seconds: float) -> None:
            submissions.append({"url": url, "payload": payload, "timeout_seconds": timeout_seconds})

        api.REVIEW_PERSISTENCE = repository
        api.API_RUN_ROOT = root / "api_runs"
        api.API_RUN_ROOT.mkdir()
        api._post_solidworks_command = accept_command
        try:
            with TestClient(api.app) as client:
                preview_runtime = client.get("/api/health").json()["generation_runtime"]["preview_renderer"]
                assert preview_runtime["engine"] == "pdftoppm"
                assert preview_runtime["status"] in {"available", "unavailable"}
                created = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-first"),
                )
                assert created.status_code == 202, created.text
                job = created.json()["generation_job"]
                task_id = int(job["generation_id"])
                assert 1_000_000_000 <= task_id <= 9_999_999_999
                assert len(str(task_id)) == 10
                assert job["parent_generation_id"] is None
                assert job["status"] == "claimed"
                assert job["status_message"] == "已提交至 SolidWorks，等待生成进度回调。"
                assert len(submissions) == 1

                command = submissions[0]
                assert command["url"] == "http://solidworks.test/solidworks/command"
                assert command["timeout_seconds"] == 10
                payload = command["payload"]
                assert isinstance(payload, dict)
                assert payload["TaskId"] == task_id
                model = payload["models"][0]
                assert model["modelId"] == 1
                assert model["materialCode"] is None
                assert model["modelParameters"] == {
                    "线径": 3,
                    "中径": 29,
                    "自由高度": 50,
                    "圈数": 9,
                    "有效圈数n": 7,
                    "是否磨平": 1,
                    "是否并紧": 1,
                }
                exported = client.get("/api/reviews/review-solidworks-push/generation-package")
                assert exported.status_code == 200, exported.text
                assert exported.json()["parameter_package"]["solidworks_preview"]["modelParameters"] == model["modelParameters"]
                assert (
                    exported.json()["parameter_package"]["solidworks_preview"]["extraProperties"]["技术要求"]
                    == model["extraProperties"]["技术要求"]
                )
                assert model["customProperties"] == {"旋向": "左旋"}
                extra = model["extraProperties"]
                assert list(extra) == ["技术要求", "P'", "C", "τ_b"]
                notes = extra["技术要求"]
                assert notes.count("表面喷丸处理") == 1 and notes.count("热处理：") == 1
                assert "热处理：热处理要求" not in notes
                assert notes.startswith("1.两端并紧磨平，每端磨270°。\n2.材料：60Si2Mn。\n3.绕制方向：左旋。\n4.")
                assert "粗糙度" not in notes
                assert "有效圈数：7 圈。" in notes and "工作圈数：" not in notes
                for expected in ("Hb = 25 mm", "Fb = 2300 N", "H1 = 38 mm", "F1 = 2000 N", "H2 = 43 mm", "F2 = 2100 N", "表面喷丸处理"):
                    assert expected in notes, notes
                assert isinstance(extra["P'"], (int, float)) and extra["C"] == round(29 / 3, 4)
                assert extra["τ_b"] > 0
                title = model["titleBlockProperties"]
                assert title["材料"] == "60Si2Mn" and isinstance(title["重量"], (int, float))
                assert title["表面粗糙度"] == 12.5
                with repository._session() as session:
                    stored_package = session.get(GenerationJobRecord, job["generation_id"]).parameter_package
                    mass = stored_package["derived_parameters"]["solidworks_design_checks"]["metrics"]["unit_mass"]
                    assert stored_package["solidworks_preview"]["titleBlockProperties"] == title
                assert title["重量"] == round(mass["value"], 8) and mass["unit"] == "kg"
                assert exported.json()["parameter_package"]["solidworks_preview"]["titleBlockProperties"] == title
                assert "surface_roughness_ra" not in model["modelParameters"]
                assert job["execution_options"]["solidworks_payload"] == payload

                duplicate_create = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-first"),
                )
                assert duplicate_create.status_code == 200, duplicate_create.text
                assert duplicate_create.json()["generation_job"]["generation_id"] == job["generation_id"]
                assert len(submissions) == 1

                from test_technical_requirement_equivalence import order2_review
                order2 = order2_review()
                order2["spring_parameters"]["solid_height"].update(source=["manual"], value_kind="input_height")
                repository.create_review("order2-technical-dedup", order2, owner=OWNER)
                order2_preview = client.get("/api/reviews/order2-technical-dedup/generation-package")
                assert order2_preview.status_code == 200, order2_preview.text
                order2_created = client.post("/api/reviews/order2-technical-dedup/generation-jobs", json=create_request("order2-dedup-r1"))
                assert order2_created.status_code == 202, order2_created.text
                order2_job = order2_created.json()["generation_job"]
                order2_payload = submissions[-1]["payload"]
                order2_notes = order2_payload["models"][0]["extraProperties"]["技术要求"]
                assert len(order2_notes.splitlines()) == 14, order2_notes
                assert order2_payload["models"][0]["titleBlockProperties"]["表面粗糙度"] == 12.5
                assert "粗糙度" not in order2_notes
                assert order2_payload["models"][0]["titleBlockProperties"] == order2_preview.json()["parameter_package"]["solidworks_preview"]["titleBlockProperties"]
                assert order2_payload["models"][0]["extraProperties"] == order2_preview.json()["parameter_package"]["solidworks_preview"]["extraProperties"]
                assert len(repository.get_review("order2-technical-dedup", owner_user_id=OWNER["user_id"])["review"]["technical_requirements"]) == 9
                with repository._session() as session:
                    order2_frozen = session.get(GenerationJobRecord, order2_job["generation_id"]).parameter_package
                    assert order2_frozen["solidworks_preview"]["extraProperties"]["技术要求"] == order2_notes
                submission_count = len(submissions)
                order2_retry = client.post("/api/reviews/order2-technical-dedup/generation-jobs", json=create_request("order2-dedup-r1"))
                assert order2_retry.status_code == 200 and len(submissions) == submission_count
                assert order2_retry.json()["generation_job"]["execution_options"]["solidworks_payload"] == order2_payload
                if os.getenv("SAVE_SW_QA_OUTPUT") == "1":
                    out = Path("outputs/technical-duplication-qa")
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "order2-request.json").write_text(json.dumps(order2_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    (out / "order2-requirements.txt").write_text(order2_notes, encoding="utf-8")

                progress = {"TaskId": task_id, "status": "generating_3d", "progress": 35, "message": "正在生成三维图"}
                progress_response = client.post("/api/solidworks/status", json=progress)
                assert progress_response.status_code == 200, progress_response.text
                assert progress_response.json() == {"TaskId": task_id, "code": 200}
                duplicate_progress = client.post("/api/solidworks/status", json=progress)
                assert duplicate_progress.status_code == 200, duplicate_progress.text
                assert duplicate_progress.json() == {"TaskId": task_id, "code": 200}

                completed = {
                    "TaskId": task_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "二维图和三维模型生成完成",
                    "file": {
                        "fileName": "SP-3x29-50-LH-001.pdf",
                        "mimeType": "application/pdf",
                        "contentBase64": pdf_base64(),
                    },
                }
                observed_statuses: list[str] = []

                def render_after_status_check(*args, **kwargs):
                    current = api.GenerationStore(repository).get_job(str(task_id), owner_user_id=OWNER["user_id"])
                    observed_statuses.append(str(current["status"]))
                    assert current["status"] != "completed"
                    return original_preview_renderer(*args, **kwargs)

                api.render_pdf_with_pdftoppm = render_after_status_check
                try:
                    completed_response = client.post("/api/solidworks/status", json=completed)
                finally:
                    api.render_pdf_with_pdftoppm = original_preview_renderer
                assert completed_response.status_code == 200, completed_response.text
                assert completed_response.json() == {"TaskId": task_id, "code": 200}
                assert observed_statuses
                job_response = client.get(f"/api/generation-jobs/{task_id}")
                assert job_response.status_code == 200, job_response.text
                completed_job = job_response.json()["generation_job"]
                assert completed_job["status"] == "completed"
                assert completed_job["progress"] == 100
                assert completed_job["preview_status"] == "ready"
                assert completed_job["preview_attempt_count"] == 1
                assert completed_job["preview_error_message"] is None
                assert completed_job["status_message"] == "二维图和三维模型生成完成"
                pdf = next(item for item in completed_job["artifacts"] if item["artifact_type"] == "pdf")
                preview_png = next(item for item in completed_job["artifacts"] if item["artifact_type"] == "png")
                assert pdf["mime_type"] == "application/pdf"
                assert len(pdf["sha256"]) == 64
                assert preview_png["mime_type"] == "image/png"
                downloaded = client.get(pdf["url"])
                assert downloaded.status_code == 200
                assert downloaded.content.startswith(b"%PDF-")
                assert downloaded.headers["content-disposition"].startswith("attachment;")
                inline_preview = client.get(f"{pdf['url']}?inline=1")
                assert inline_preview.status_code == 200
                assert inline_preview.content == downloaded.content
                assert inline_preview.headers["content-type"].startswith("application/pdf")
                assert inline_preview.headers["content-disposition"].startswith("inline;")
                non_pdf_preview = client.get(f"{preview_png['url']}?inline=1")
                assert non_pdf_preview.headers["content-disposition"].startswith("attachment;")

                duplicate_pdf = client.post("/api/solidworks/status", json=completed)
                assert duplicate_pdf.status_code == 200, duplicate_pdf.text
                assert duplicate_pdf.json() == {"TaskId": task_id, "code": 200}
                conflicting = {**completed, "file": {**completed["file"], "contentBase64": pdf_base64(color="black")}}
                conflict_response = client.post("/api/solidworks/status", json=conflicting)
                assert conflict_response.status_code == 409
                assert "detail" in conflict_response.json()
                assert "TaskId" not in conflict_response.json()
                assert client.post("/api/solidworks/status", json={**progress, "progress": 60}).status_code == 409
                assert client.post(
                    "/api/solidworks/status",
                    json={"TaskId": 1_234_567_890, "status": "generating_2d", "progress": 60},
                ).status_code == 404
                assert client.post(
                    "/api/solidworks/status",
                    json={**completed, "file": {**completed["file"], "contentBase64": "data:application/pdf;base64,AAA"}},
                ).status_code == 422
                assert client.post(
                    "/api/solidworks/status",
                    json={**completed, "file": {**completed["file"], "contentBase64": base64.b64encode(b"not a pdf").decode("ascii")}},
                ).status_code == 415
                assert client.post(
                    "/api/solidworks/status",
                    json={"TaskId": task_id, "status": "completed", "progress": 100},
                ).status_code == 422

                preview_failure_create = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-preview-failure"),
                )
                assert preview_failure_create.status_code == 202, preview_failure_create.text
                preview_failure_task_id = int(preview_failure_create.json()["generation_job"]["generation_id"])
                render_attempts = 0

                def fail_preview_render(*args, **kwargs):
                    nonlocal render_attempts
                    render_attempts += 1
                    raise OSError("temporary preview renderer failure")

                api.render_pdf_with_pdftoppm = fail_preview_render
                api.time.sleep = lambda _: None
                try:
                    preview_failure_response = client.post(
                        "/api/solidworks/status",
                        json={
                            **completed,
                            "TaskId": preview_failure_task_id,
                            "file": {**completed["file"], "fileName": "preview-failure.pdf"},
                        },
                    )
                finally:
                    api.render_pdf_with_pdftoppm = original_preview_renderer
                    api.time.sleep = original_sleep
                assert preview_failure_response.status_code == 200, preview_failure_response.text
                assert render_attempts == 3
                preview_failure_job = client.get(
                    f"/api/generation-jobs/{preview_failure_task_id}"
                ).json()["generation_job"]
                assert preview_failure_job["status"] == "completed"
                assert preview_failure_job["preview_status"] == "failed"
                assert preview_failure_job["preview_attempt_count"] == 3
                assert preview_failure_job["preview_error_message"] == "服务器生成 PDF 对比预览时发生临时错误。"
                assert [item["artifact_type"] for item in preview_failure_job["artifacts"]] == ["pdf"]

                preview_retry = client.post(
                    f"/api/generation-jobs/{preview_failure_task_id}/preview/retry"
                )
                assert preview_retry.status_code == 200, preview_retry.text
                preview_retry_job = preview_retry.json()["generation_job"]
                assert preview_retry_job["status"] == "completed"
                assert preview_retry_job["preview_status"] == "ready"
                assert preview_retry_job["preview_attempt_count"] == 4
                assert preview_retry_job["preview_error_message"] is None
                assert [item["artifact_type"] for item in preview_retry_job["artifacts"]].count("png") == 1
                idempotent_preview_retry = client.post(
                    f"/api/generation-jobs/{preview_failure_task_id}/preview/retry"
                )
                assert idempotent_preview_retry.status_code == 200, idempotent_preview_retry.text
                assert [
                    item["artifact_type"]
                    for item in idempotent_preview_retry.json()["generation_job"]["artifacts"]
                ].count("png") == 1
                with repository._session() as session:
                    preview_events = session.query(GenerationEventRecord).filter_by(
                        generation_id=str(preview_failure_task_id)
                    ).all()
                    event_types = [item.event_type for item in preview_events]
                    assert event_types.count("generation_preview_created") == 1
                    assert event_types.count("generation_preview_failed") == 1
                    assert event_types.count("generation_preview_retried") == 1

                cancelled_create = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-cancelled"),
                )
                assert cancelled_create.status_code == 202, cancelled_create.text
                cancelled_task_id = int(cancelled_create.json()["generation_job"]["generation_id"])
                cancelled = client.post(f"/api/generation-jobs/{cancelled_task_id}/cancel")
                assert cancelled.status_code == 200, cancelled.text
                assert cancelled.json()["generation_job"]["status"] == "cancelled"

                cancelled_progress = {
                    "TaskId": cancelled_task_id,
                    "status": "generating_3d",
                    "progress": 35,
                    "message": "正在生成三维图",
                }
                cancelled_progress_response = client.post("/api/solidworks/status", json=cancelled_progress)
                assert cancelled_progress_response.status_code == 409, cancelled_progress_response.text
                assert cancelled_progress_response.json() == {"TaskId": cancelled_task_id, "code": 409}
                repeated_cancelled_progress = client.post("/api/solidworks/status", json=cancelled_progress)
                assert repeated_cancelled_progress.status_code == 409, repeated_cancelled_progress.text
                assert repeated_cancelled_progress.json() == {"TaskId": cancelled_task_id, "code": 409}
                cancelled_error_response = client.post(
                    "/api/solidworks/status",
                    json={
                        "TaskId": cancelled_task_id,
                        "status": "generating_3d_error",
                        "message": "该错误不应覆盖取消状态",
                    },
                )
                assert cancelled_error_response.status_code == 409, cancelled_error_response.text
                assert cancelled_error_response.json() == {"TaskId": cancelled_task_id, "code": 409}

                cancelled_completed = {
                    "TaskId": cancelled_task_id,
                    "status": "completed",
                    "progress": 100,
                    "file": {
                        "fileName": "cancelled-drawing.pdf",
                        "mimeType": "application/pdf",
                        "contentBase64": pdf_base64(),
                    },
                }
                cancelled_completed_response = client.post("/api/solidworks/status", json=cancelled_completed)
                assert cancelled_completed_response.status_code == 409, cancelled_completed_response.text
                assert cancelled_completed_response.json() == {"TaskId": cancelled_task_id, "code": 409}
                cancelled_job = client.get(f"/api/generation-jobs/{cancelled_task_id}").json()["generation_job"]
                assert cancelled_job["status"] == "cancelled"
                assert cancelled_job["artifacts"] == []
                cancelled_artifact_dir = api.API_RUN_ROOT / "_generation_artifacts" / str(cancelled_task_id)
                assert not cancelled_artifact_dir.exists()

                race_create = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-cancel-race"),
                )
                assert race_create.status_code == 202, race_create.text
                race_task_id = int(race_create.json()["generation_job"]["generation_id"])
                original_decode = api._decode_solidworks_pdf

                def cancel_after_preflight(content_base64: str) -> bytes:
                    content = original_decode(content_base64)
                    raced_cancel = api.GenerationStore(repository).cancel_job(
                        str(race_task_id), owner_user_id=OWNER["user_id"]
                    )
                    assert raced_cancel is not None
                    assert raced_cancel["status"] == "cancelled"
                    return content

                api._decode_solidworks_pdf = cancel_after_preflight
                try:
                    race_response = client.post(
                        "/api/solidworks/status",
                        json={
                            "TaskId": race_task_id,
                            "status": "completed",
                            "progress": 100,
                            "file": {
                                "fileName": "race-cancelled.pdf",
                                "mimeType": "application/pdf",
                                "contentBase64": pdf_base64(),
                            },
                        },
                    )
                finally:
                    api._decode_solidworks_pdf = original_decode
                assert race_response.status_code == 409, race_response.text
                assert race_response.json() == {"TaskId": race_task_id, "code": 409}
                race_job = client.get(f"/api/generation-jobs/{race_task_id}").json()["generation_job"]
                assert race_job["status"] == "cancelled"
                assert race_job["artifacts"] == []
                race_artifact_dir = api.API_RUN_ROOT / "_generation_artifacts" / str(race_task_id)
                assert not list(race_artifact_dir.glob("*")) if race_artifact_dir.exists() else True

                three_d_error_create = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-3d-error"),
                )
                assert three_d_error_create.status_code == 202, three_d_error_create.text
                three_d_error_task_id = int(three_d_error_create.json()["generation_job"]["generation_id"])
                three_d_started = client.post(
                    "/api/solidworks/status",
                    json={
                        "TaskId": three_d_error_task_id,
                        "status": "generating_3d",
                        "progress": 35,
                        "message": "正在生成三维图",
                    },
                )
                assert three_d_started.status_code == 200, three_d_started.text
                three_d_error = {
                    "TaskId": three_d_error_task_id,
                    "status": "generating_3d_error",
                    "message": "模型重建失败",
                }
                three_d_error_response = client.post("/api/solidworks/status", json=three_d_error)
                assert three_d_error_response.status_code == 200, three_d_error_response.text
                assert three_d_error_response.json() == {"TaskId": three_d_error_task_id, "code": 200}
                three_d_error_job = client.get(
                    f"/api/generation-jobs/{three_d_error_task_id}"
                ).json()["generation_job"]
                assert three_d_error_job["status"] == "failed"
                assert three_d_error_job["stage"] == "generating_3d_error"
                assert three_d_error_job["progress"] == 35
                assert three_d_error_job["error_code"] == "solidworks_3d_generation_failed"
                assert three_d_error_job["error_message"] == "模型重建失败"
                assert three_d_error_job["status_message"] == "模型重建失败"
                duplicate_three_d_error = client.post("/api/solidworks/status", json=three_d_error)
                assert duplicate_three_d_error.status_code == 200, duplicate_three_d_error.text
                assert duplicate_three_d_error.json() == {"TaskId": three_d_error_task_id, "code": 200}
                changed_stage_error = client.post(
                    "/api/solidworks/status",
                    json={
                        "TaskId": three_d_error_task_id,
                        "status": "generating_2d_error",
                        "message": "不能覆盖三维失败终态",
                    },
                )
                assert changed_stage_error.status_code == 409, changed_stage_error.text
                assert "detail" in changed_stage_error.json()
                assert "TaskId" not in changed_stage_error.json()
                assert client.post(
                    "/api/solidworks/status",
                    json={"TaskId": three_d_error_task_id, "status": "generating_3d_error"},
                ).status_code == 422
                assert client.post(
                    "/api/solidworks/status",
                    json={**three_d_error, "file": completed["file"]},
                ).status_code == 422

                two_d_error_create = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-2d-error"),
                )
                assert two_d_error_create.status_code == 202, two_d_error_create.text
                two_d_error_task_id = int(two_d_error_create.json()["generation_job"]["generation_id"])
                two_d_started = client.post(
                    "/api/solidworks/status",
                    json={
                        "TaskId": two_d_error_task_id,
                        "status": "generating_2d",
                        "progress": 68,
                        "message": "正在生成二维图",
                    },
                )
                assert two_d_started.status_code == 200, two_d_started.text
                two_d_error_response = client.post(
                    "/api/solidworks/status",
                    json={
                        "TaskId": two_d_error_task_id,
                        "status": "generating_2d_error",
                        "message": "二维工程图生成失败",
                    },
                )
                assert two_d_error_response.status_code == 200, two_d_error_response.text
                assert two_d_error_response.json() == {"TaskId": two_d_error_task_id, "code": 200}
                two_d_error_job = client.get(
                    f"/api/generation-jobs/{two_d_error_task_id}"
                ).json()["generation_job"]
                assert two_d_error_job["status"] == "failed"
                assert two_d_error_job["stage"] == "generating_2d_error"
                assert two_d_error_job["progress"] == 68
                assert two_d_error_job["error_code"] == "solidworks_2d_generation_failed"
                assert two_d_error_job["error_message"] == "二维工程图生成失败"

                failed_create = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-submit-fail"),
                )
                assert failed_create.status_code == 202, failed_create.text
                failed_task = failed_create.json()["generation_job"]
                failed_callback = client.post(
                    "/api/solidworks/status",
                    json={
                        "TaskId": int(failed_task["generation_id"]),
                        "status": "failed",
                        "progress": 42,
                        "errorCode": "solidworks_rebuild_failed",
                        "message": "SolidWorks 重建失败。",
                    },
                )
                assert failed_callback.status_code == 200, failed_callback.text
                assert failed_callback.json() == {"TaskId": int(failed_task["generation_id"]), "code": 200}
                assert client.post(f"/api/generation-jobs/{failed_task['generation_id']}/retry").status_code == 409

                # A final version never prevents a new TaskId or its SW callbacks.
                assert client.post(f"/api/generation-jobs/{task_id}/approve").status_code == 200
                new_with_final = client.post("/api/reviews/review-solidworks-push/generation-jobs", json=create_request("with-final-new-task"))
                assert new_with_final.status_code == 202, new_with_final.text
                new_id = int(new_with_final.json()["generation_job"]["generation_id"])
                assert new_id != task_id
                assert client.post("/api/solidworks/status", json={"TaskId": new_id, "status": "generating_3d", "progress": 33}).status_code == 200
                assert client.get(f"/api/generation-jobs/{new_id}").json()["generation_job"]["progress"] == 33
                new_completion = client.post("/api/solidworks/status", json={"TaskId": new_id, "status": "completed", "progress": 100, "file": {"fileName": "new.pdf", "mimeType": "application/pdf", "contentBase64": pdf_base64()}})
                assert new_completion.status_code == 200, new_completion.text
                blocked = client.post(f"/api/generation-jobs/{new_id}/approve")
                assert blocked.status_code == 409 and blocked.json()["detail"]["current_final_generation_id"] == str(task_id)
                assert client.post(f"/api/generation-jobs/{task_id}/unapprove").status_code == 200
                assert client.post(f"/api/generation-jobs/{new_id}/approve").status_code == 200
                assert client.post(f"/api/generation-jobs/{task_id}/unapprove").status_code == 200
                assert client.get(f"/api/generation-jobs/{new_id}").json()["generation_job"]["is_final"] is True

                # Open ends omit the modelling key and generated note; internal n and readiness stay intact.
                for grinding in (0, 1):
                    open_id = f"open-end-{grinding}"
                    open_review = ready_review()
                    open_review["spring_parameters"]["end_type"] = parameter("两端不并紧")
                    open_review["spring_parameters"]["end_grinding"] = parameter(grinding)
                    active = 8 if grinding else 9
                    open_review["spring_parameters"]["active_coils"] = parameter(active, "圈")
                    repository.create_review(open_id, open_review, owner=OWNER)
                    open_preview = client.get(f"/api/reviews/{open_id}/generation-package")
                    assert open_preview.status_code == 200, open_preview.text
                    open_package = open_preview.json()["parameter_package"]
                    assert open_package["generation_parameters"]["spring_parameters"]["active_coils"]["value"] == active
                    open_create = client.post(f"/api/reviews/{open_id}/generation-jobs", json=create_request(open_id))
                    assert open_create.status_code == 202, open_create.text
                    open_job = open_create.json()["generation_job"]
                    open_payload = submissions[-1]["payload"]
                    open_model = open_payload["models"][0]
                    assert open_model["modelParameters"]["是否并紧"] == 0
                    assert "有效圈数n" not in open_model["modelParameters"]
                    assert list(open_model["modelParameters"]) == ["线径", "中径", "自由高度", "圈数", "是否磨平", "是否并紧"]
                    open_notes = open_model["extraProperties"]["技术要求"]
                    expected_end_note = "两端不并紧，端面磨平。" if grinding else "两端不并紧，不磨平。"
                    assert open_notes.startswith("1." + expected_end_note + "\n") and "每端磨270°" not in open_notes
                    assert "工作圈数：" not in open_notes and "有效圈数：" not in open_notes
                    assert "总圈数：9 圈。" in open_notes
                    assert {key: open_model[key] for key in open_package["solidworks_preview"]} == open_package["solidworks_preview"]
                    with repository._session() as session:
                        frozen_open = session.get(GenerationJobRecord, open_job["generation_id"]).parameter_package
                        assert frozen_open["solidworks_preview"] == open_package["solidworks_preview"]
                        assert "active_coils" in frozen_open["generation_parameters"]["spring_parameters"]
                    before_retry_count = len(submissions)
                    open_retry = client.post(f"/api/reviews/{open_id}/generation-jobs", json=create_request(open_id))
                    assert open_retry.status_code == 200, open_retry.text
                    assert len(submissions) == before_retry_count
                    assert open_retry.json()["generation_job"]["execution_options"]["solidworks_payload"] == open_payload
                    changed_open = repository.get_review(open_id, owner_user_id=OWNER["user_id"])["review"]
                    changed_open["spring_parameters"]["end_type"] = parameter("两端并紧")
                    changed_response = client.patch(f"/api/reviews/{open_id}", json={"expected_revision": 1, "review": changed_open})
                    assert changed_response.status_code == 200, changed_response.text
                    stale_retry = client.post(f"/api/reviews/{open_id}/generation-jobs", json=create_request(open_id))
                    assert stale_retry.status_code == 409 and stale_retry.json()["detail"]["code"] == "review_revision_conflict"
                    assert len(submissions) == before_retry_count
                    assert client.get(f"/api/generation-jobs/{open_job['generation_id']}").json()["generation_job"]["execution_options"]["solidworks_payload"] == open_payload
                pending_open = ready_review()
                pending_open["spring_parameters"]["end_type"] = parameter("两端不并紧")
                pending_open["spring_parameters"]["active_coils"]["need_human_review"] = True
                repository.create_review("open-active-pending", pending_open, owner=OWNER)
                before_pending_count = len(submissions)
                pending_create = client.post("/api/reviews/open-active-pending/generation-jobs", json=create_request("open-active-pending"))
                assert pending_create.status_code == 409, pending_create.text
                assert len(submissions) == before_pending_count

                def reject_command(url: str, payload: dict[str, object], *, timeout_seconds: float) -> None:
                    raise TimeoutError("test timeout")

                api._post_solidworks_command = reject_command
                submit_failure = client.post(
                    "/api/reviews/review-solidworks-push/generation-jobs",
                    json=create_request("solidworks-push-r1-network-fail"),
                )
                assert submit_failure.status_code == 202, submit_failure.text
                assert submit_failure.json()["generation_job"]["status"] == "failed"
                assert submit_failure.json()["generation_job"]["error_code"] == "solidworks_submit_failed"

                class Non2xxResponse:
                    status_code = 503
                    text = "busy"

                api.httpx.post = lambda *args, **kwargs: Non2xxResponse()
                try:
                    original_post("http://solidworks.test/command", {}, timeout_seconds=1)
                    raise AssertionError("non-2xx SolidWorks acceptance must fail")
                except RuntimeError as exc:
                    assert "HTTP 503" in str(exc)
                finally:
                    api.httpx.post = original_http_post
        finally:
            api._post_solidworks_command = original_post
            api.httpx.post = original_http_post
            api.render_pdf_with_pdftoppm = original_preview_renderer
            api.time.sleep = original_sleep
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_run_root
            repository.dispose()

    print("SolidWorks push API tests passed: ten-digit TaskId, command payload, callbacks, PDF storage, failures, and cancellation.")


if __name__ == "__main__":
    main()
