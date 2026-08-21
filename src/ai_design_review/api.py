from __future__ import annotations

import shutil
import uuid
import os
import re
import secrets
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .api_documentation import (
    API_DESCRIPTION,
    API_SUMMARY,
    API_TITLE,
    OPENAPI_TAGS,
    SCALAR_ASSET_FILENAME,
    apply_chinese_openapi_documentation,
)
from .engines.geometry_adapter import GeometryEngine
from .engines.ocr_adapter import OcrJsonEngine
from .engines.ocr_providers import (
    OcrProviderError,
    UnifiedOcrEngine,
    normalize_ocr_provider,
    ocr_runtime_status,
)
from .engines.qwen_vision_adapter import QwenVisionEngine, qwen_runtime_status
from .engines.werk24_adapter import Werk24Engine
from .identity import IdentityContext, IdentityError, resolve_request_identity
from .io_utils import project_path, read_json, write_json
from .generation_contract import apply_generation_defaults
from .generation_persistence import GenerationStore
from .generation_readiness import assess_generation_readiness, build_generation_parameter_package
from .generation_schemas import (
    GenerationArtifactListResponse,
    GenerationArtifactResponse,
    GenerationJobCreate,
    GenerationJobCreateResponse,
    GenerationJobListResponse,
    GenerationJobResponse,
    GenerationPackageResponse,
    GenerationReadinessResponse,
    GenerationTemplateCreate,
    GenerationTemplateListResponse,
    GenerationTemplateMatchRequest,
    GenerationTemplateMatchResponse,
    GenerationTemplateResponse,
    GenerationTemplateStatusUpdate,
    GenerationTemplateVersionCreate,
    GenerationTemplateVersionsResponse,
    GenerationWorkerClaim,
    GenerationWorkerClaimResponse,
    GenerationWorkerComplete,
    GenerationWorkerFailed,
    GenerationWorkerHeartbeat,
    GenerationWorkerStatus,
)
from .generation_service import match_generation_template, request_fingerprint, stable_payload_hash
from .llm_standardization_engine import LLMStandardizationEngine, llm_standardization_runtime_status
from .preprocessing import IMAGE_EXTENSIONS, probe_file, render_pdf_with_pdftoppm
from .parameter_change_proposal import (
    ParameterProposalError,
    apply_parameter_change_proposal,
    discard_parameter_change_proposal,
)
from .review_persistence import PersistenceError, ReviewAccessError, ReviewPersistence, RevisionConflictError
from .standard_knowledge import ragflow_runtime_status, retrieve_standard_chunks
from .standardization_chat_agent import (
    chat_about_standardization,
    parse_accuracy_standardization_request,
    select_general_accuracy_grade,
    standardization_chat_context_needs_refresh,
)
from .standardization_chat_llm import standardization_chat_llm_runtime_status
from .spring_feasibility import assess_parameter_reasonableness
from .load_points import ensure_load_point_ids
from .technical_requirements import ensure_technical_requirement_ids
from .workflow import DrawingReviewWorkflow, apply_standardization_to_review


PROJECT_ROOT = project_path()
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
API_RUN_ROOT = OUTPUT_ROOT / "api_runs"
SAMPLE_ROOT = project_path("data", "samples")
DOCS_ASSET_ROOT = Path(__file__).resolve().parent / "docs_assets"
DEFAULT_FRONTEND_ORIGINS = (
    "http://127.0.0.1:5173,"
    "http://localhost:5173,"
    "http://127.0.0.1:8765,"
    "http://localhost:8765"
)
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv("AI_REVIEW_FRONTEND_ORIGINS", DEFAULT_FRONTEND_ORIGINS).split(",")
    if origin.strip()
]

app = FastAPI(
    title=API_TITLE,
    summary=API_SUMMARY,
    description=API_DESCRIPTION,
    version="0.2.0",
    docs_url=None,
    openapi_url="/api/openapi.json",
    redoc_url=None,
    openapi_tags=OPENAPI_TAGS,
)
app.mount("/api/docs-assets", StaticFiles(directory=str(DOCS_ASSET_ROOT)), name="api-docs-assets")
RAGFLOW_STARTUP_STATUS = ragflow_runtime_status()
REVIEW_PERSISTENCE = ReviewPersistence()
DATABASE_STARTUP_STATUS = REVIEW_PERSISTENCE.health()
GENERATION_TEMPLATE_STARTUP_STATUS: dict[str, Any] = {"status": "not_initialized"}
WORKER_BEARER = HTTPBearer(auto_error=False, scheme_name="GenerationWorkerBearer")
ADMIN_BEARER = HTTPBearer(auto_error=False, scheme_name="GenerationAdminBearer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_RUN_ROOT.mkdir(parents=True, exist_ok=True)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
    )
    app.openapi_schema = apply_chinese_openapi_documentation(schema)
    return app.openapi_schema


app.openapi = custom_openapi


class RecognitionCancelled(RuntimeError):
    """Raised by the worker progress callback after a user cancels a job."""


@app.on_event("startup")
def refresh_runtime_startup_status() -> None:
    global RAGFLOW_STARTUP_STATUS, DATABASE_STARTUP_STATUS, GENERATION_TEMPLATE_STARTUP_STATUS
    RAGFLOW_STARTUP_STATUS = ragflow_runtime_status(check_health=True)
    DATABASE_STARTUP_STATUS = REVIEW_PERSISTENCE.health(check_connection=True)
    mock_enabled = _env_flag("MOCK_SOLIDWORKS_ENABLED", False)
    if REVIEW_PERSISTENCE.configured and mock_enabled:
        try:
            template = GenerationStore(REVIEW_PERSISTENCE).ensure_mock_template(enabled=True)
            GENERATION_TEMPLATE_STARTUP_STATUS = {
                "status": "available",
                "mock_template_enabled": bool(template.get("enabled")),
            }
        except PersistenceError as exc:
            GENERATION_TEMPLATE_STARTUP_STATUS = {"status": "unavailable", "reason": str(exc)}
    elif REVIEW_PERSISTENCE.configured:
        try:
            disabled_count = GenerationStore(REVIEW_PERSISTENCE).disable_mock_templates()
            GENERATION_TEMPLATE_STARTUP_STATUS = {
                "status": "disabled",
                "mock_templates_disabled": disabled_count,
            }
        except PersistenceError as exc:
            GENERATION_TEMPLATE_STARTUP_STATUS = {"status": "unavailable", "reason": str(exc)}
    else:
        GENERATION_TEMPLATE_STARTUP_STATUS = {"status": "not_configured"}


@app.on_event("shutdown")
def close_runtime_resources() -> None:
    REVIEW_PERSISTENCE.dispose()


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ai-design-review-api",
        "health": "/api/health",
        "docs": "/api/docs",
    }


@app.get("/docs", include_in_schema=False)
def legacy_docs_redirect() -> RedirectResponse:
    return RedirectResponse(url="/api/docs", status_code=307)


@app.get("/api/docs", include_in_schema=False)
def scalar_api_docs() -> HTMLResponse:
    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content="弹簧图纸 AI 审查与 SolidWorks 生图 API 中文接口文档" />
    <title>{API_TITLE}</title>
    <style>
      html, body, #app {{ height: 100%; margin: 0; }}
      body {{ background: #ffffff; }}
    </style>
  </head>
  <body>
    <div id="app"></div>
    <script src="/api/docs-assets/{SCALAR_ASSET_FILENAME}"></script>
    <script>
      Scalar.createApiReference('#app', {{
        url: '/api/openapi.json',
        theme: 'default',
        layout: 'modern',
        showSidebar: true,
        hideSearch: false,
        hideModels: false,
        modelsSectionLabel: '数据模型',
        operationTitleSource: 'summary',
        darkMode: false,
        hideDarkModeToggle: false,
        defaultHttpClient: {{ targetKey: 'shell', clientKey: 'curl' }},
        showDeveloperTools: 'always',
        persistAuth: false,
        telemetry: false,
        documentDownloadType: 'both',
        defaultOpenFirstTag: true,
        customFetch: (input, init) => fetch(input, {{ ...(init || {{}}), credentials: 'include' }})
      }})
    </script>
  </body>
</html>""",
        status_code=200,
    )


@app.get("/api/swagger", include_in_schema=False)
def swagger_api_docs() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=app.openapi_url or "/api/openapi.json",
        title=f"{API_TITLE} - Swagger UI",
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ai-design-review",
        "pid": os.getpid(),
        "project_root": str(PROJECT_ROOT),
        "api_runs": str(API_RUN_ROOT),
        "frontend_origins": FRONTEND_ORIGINS,
        "qwen_runtime": qwen_runtime_status(),
        "llm_standardization_runtime": llm_standardization_runtime_status(),
        "standardization_chat_runtime": standardization_chat_llm_runtime_status(),
        "ragflow_runtime": RAGFLOW_STARTUP_STATUS,
        "persistence_runtime": DATABASE_STARTUP_STATUS,
        "recognition_queue_runtime": {
            "status": "available" if REVIEW_PERSISTENCE.configured else "not_configured",
            "backend": "postgresql",
            "configured_concurrency": _configured_recognition_concurrency(),
        },
        "generation_runtime": {
            "status": "available" if _generation_database_available() else "not_configured",
            "backend": "postgresql",
            "template_registry": GENERATION_TEMPLATE_STARTUP_STATUS,
            "mock_mode": _env_flag("MOCK_SOLIDWORKS_ENABLED", False),
        },
        "ocr_runtime": ocr_runtime_status(),
        "geometry_runtime": {"status": "ready", "engine": "geometry"},
        "vlm_runtime": {"status": "not_configured", "mode": "optional_review_only"},
        "paddleocr_runtime": {"status": "deprecated", "replacement": "ocr_runtime"},
    }


def require_identity(request: Request) -> IdentityContext:
    try:
        return resolve_request_identity(request)
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail="ERP identity is required to use the drawing review assistant.") from exc


def _configured_recognition_concurrency() -> int:
    try:
        return min(max(int(os.getenv("RECOGNITION_WORKER_CONCURRENCY", "2")), 1), 8)
    except (TypeError, ValueError):
        return 2


@app.get("/api/session")
def get_session(identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    return {"identity": identity.as_public_dict()}


@app.get("/api/samples/mixed-review")
def get_mixed_review_sample(identity: IdentityContext = Depends(require_identity)) -> FileResponse:
    sample_path = SAMPLE_ROOT / "compression_spring_demo_review.json"
    if not sample_path.is_file():
        raise HTTPException(status_code=404, detail="Sample review not found.")
    return FileResponse(str(sample_path), media_type="application/json")


@app.get("/api/samples/spring-preview")
def get_spring_preview_sample(identity: IdentityContext = Depends(require_identity)) -> FileResponse:
    sample_path = SAMPLE_ROOT / "compression_spring_demo.png"
    if not sample_path.is_file():
        raise HTTPException(status_code=404, detail="Sample preview not found.")
    return FileResponse(str(sample_path), media_type="image/png")


@app.get("/api/standard-knowledge/search")
def search_standard_knowledge(
    standard_no: str | None = None,
    spring_type: str | None = "compression_spring",
    target_fields: str | None = None,
    query: str | None = None,
    limit: int = 6,
    _: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    fields = [
        item.strip()
        for item in str(target_fields or "").split(",")
        if item.strip()
    ]
    chunks = retrieve_standard_chunks(
        standard_no=standard_no,
        spring_type=spring_type,
        target_fields=fields,
        query=query,
        limit=limit,
    )
    return {
        "standard_no": standard_no,
        "spring_type": spring_type,
        "target_fields": fields,
        "query": query or "",
        "count": len(chunks),
        "chunks": chunks,
    }


def require_generation_worker(
    credentials: HTTPAuthorizationCredentials | None = Depends(WORKER_BEARER),
) -> None:
    _require_service_key(credentials, "GENERATION_WORKER_API_KEY", "Generation worker")


def require_generation_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(ADMIN_BEARER),
) -> None:
    _require_service_key(credentials, "GENERATION_ADMIN_API_KEY", "Generation administrator")


@app.get("/api/reviews/{job_id}/generation-readiness", response_model=GenerationReadinessResponse, tags=["Generation"])
def get_generation_readiness(job_id: str, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    review, revision = _load_generation_review(job_id, identity)
    return {
        "review_id": job_id,
        "review_revision": revision,
        "generation_readiness": assess_generation_readiness(review),
    }


@app.get(
    "/api/reviews/{job_id}/generation-package",
    response_model=GenerationPackageResponse,
    responses={409: {"description": "Review is not ready", "content": {"application/json": {"example": {"detail": {"code": "generation_not_ready"}}}}}},
    tags=["Generation"],
)
def get_generation_package(job_id: str, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    review, revision = _load_generation_review(job_id, identity)
    readiness = assess_generation_readiness(review)
    if readiness.get("status") not in {"ready", "ready_with_warnings"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "generation_not_ready", "generation_readiness": readiness},
        )
    return {
        "review_id": job_id,
        "review_revision": revision,
        "generation_readiness": readiness,
        "parameter_package": build_generation_parameter_package(review),
    }


@app.get("/api/generation-templates", response_model=GenerationTemplateListResponse, tags=["Generation Templates"])
def list_generation_templates(
    _: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    return {"templates": GenerationStore(REVIEW_PERSISTENCE).list_templates()}


@app.get("/api/generation-templates/{template_code:path}/versions", response_model=GenerationTemplateVersionsResponse, tags=["Generation Templates"])
def list_generation_template_versions(
    template_code: str,
    _: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    return {
        "template_code": template_code,
        "versions": GenerationStore(REVIEW_PERSISTENCE).list_templates(
            template_code=template_code,
            include_disabled=False,
        ),
    }


@app.post("/api/admin/generation-templates", status_code=201, response_model=GenerationTemplateResponse, tags=["Generation Template Admin"])
def create_generation_template(
    body: GenerationTemplateCreate,
    _: None = Depends(require_generation_admin),
) -> dict[str, Any]:
    _require_generation_database()
    try:
        return {"template": GenerationStore(REVIEW_PERSISTENCE).create_template(body.model_dump())}
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc


@app.post(
    "/api/admin/generation-templates/{template_code:path}/versions",
    status_code=201,
    response_model=GenerationTemplateResponse,
    tags=["Generation Template Admin"],
)
def create_generation_template_version(
    template_code: str,
    body: GenerationTemplateVersionCreate,
    _: None = Depends(require_generation_admin),
) -> dict[str, Any]:
    _require_generation_database()
    try:
        return {
            "template": GenerationStore(REVIEW_PERSISTENCE).create_template(
                {"template_code": template_code, **body.model_dump()}
            )
        }
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc


@app.patch(
    "/api/admin/generation-templates/{template_code:path}/versions/{version}/status",
    response_model=GenerationTemplateResponse,
    tags=["Generation Template Admin"],
)
def update_generation_template_status(
    template_code: str,
    version: str,
    body: GenerationTemplateStatusUpdate,
    _: None = Depends(require_generation_admin),
) -> dict[str, Any]:
    _require_generation_database()
    try:
        return {
            "template": GenerationStore(REVIEW_PERSISTENCE).set_template_status(
                template_code,
                version,
                enabled=body.enabled,
            )
        }
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc


@app.post("/api/reviews/{job_id}/generation-template-match", response_model=GenerationTemplateMatchResponse, tags=["Generation"])
def match_review_generation_template(
    job_id: str,
    body: GenerationTemplateMatchRequest,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    review, revision = _load_generation_review(job_id, identity)
    package = build_generation_parameter_package(review)
    match = match_generation_template(
        review,
        package,
        GenerationStore(REVIEW_PERSISTENCE).list_templates(),
        requested_code=body.template_code,
    )
    return {"review_id": job_id, "review_revision": revision, "template_match": match}


@app.post(
    "/api/reviews/{job_id}/generation-jobs",
    status_code=202,
    response_model=GenerationJobCreateResponse,
    responses={
        200: {"model": GenerationJobCreateResponse, "description": "Existing idempotent request"},
        409: {"description": "Revision, readiness, idempotency, or template conflict", "content": {"application/json": {"example": {"detail": {"code": "review_revision_conflict", "current_revision": 4}}}}},
        503: {"description": "PostgreSQL generation queue is unavailable"},
    },
    tags=["Generation"],
)
def create_generation_job(
    job_id: str,
    body: GenerationJobCreate,
    identity: IdentityContext = Depends(require_identity),
) -> JSONResponse:
    _require_generation_database()
    review, revision = _load_generation_review(job_id, identity)
    if revision is None or body.expected_review_revision != revision:
        raise HTTPException(
            status_code=409,
            detail={"code": "review_revision_conflict", "current_revision": revision},
        )
    readiness = assess_generation_readiness(review)
    if readiness.get("status") not in {"ready", "ready_with_warnings"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "generation_not_ready", "generation_readiness": readiness},
        )
    package = build_generation_parameter_package(review)
    store = GenerationStore(REVIEW_PERSISTENCE)
    match = match_generation_template(
        review,
        package,
        store.list_templates(),
        requested_code=body.template_code,
    )
    if match["status"] != "selected":
        raise HTTPException(status_code=409, detail={"code": match["status"], **match})
    selected = match["selected_template"]
    if body.parent_generation_id:
        parent = store.get_job(body.parent_generation_id, owner_user_id=identity.user_id)
        if parent is None or parent.get("review_id") != job_id:
            raise HTTPException(status_code=400, detail={"code": "invalid_parent_generation"})
    normalized_request = {
        "review_id": job_id,
        "review_revision": revision,
        "parent_generation_id": body.parent_generation_id,
        "template_code": selected["template_code"],
        "template_version": selected["version"],
        "requested_artifact_types": body.requested_artifact_types,
        "mock_scenario": body.mock_scenario,
    }
    generation_id = uuid.uuid4().hex[:16]
    try:
        job, created = store.create_job(
            {
                "generation_id": generation_id,
                "review_job_id": job_id,
                "review_revision": revision,
                "parent_generation_id": body.parent_generation_id,
                "idempotency_key": body.idempotency_key,
                "request_fingerprint": request_fingerprint(normalized_request),
                "template_code": selected["template_code"],
                "template_version": selected["version"],
                "worker_capability": selected["worker_capability"],
                "parameter_schema_version": str(package.get("schema_version") or "unknown"),
                "parameter_hash": stable_payload_hash(package),
                "parameter_package": package,
                "readiness": readiness,
                "requested_artifact_types": body.requested_artifact_types,
                "execution_options": {"mock_scenario": body.mock_scenario},
            },
            owner=identity.as_owner_dict(),
        )
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    return JSONResponse(
        status_code=202 if created else 200,
        content={"created": created, "generation_job": _generation_job_response(job)},
    )


@app.get("/api/reviews/{job_id}/generation-jobs", response_model=GenerationJobListResponse, tags=["Generation"])
def list_review_generation_jobs(
    job_id: str,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    _load_generation_review(job_id, identity)
    jobs = GenerationStore(REVIEW_PERSISTENCE).list_jobs(job_id, owner_user_id=identity.user_id)
    return {"review_id": job_id, "generation_jobs": [_generation_job_response(item) for item in jobs]}


@app.get("/api/generation-jobs/{generation_id}", response_model=GenerationJobResponse, tags=["Generation"])
def get_generation_job(
    generation_id: str,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    job = GenerationStore(REVIEW_PERSISTENCE).get_job(generation_id, owner_user_id=identity.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    return {"generation_job": _generation_job_response(job)}


@app.post("/api/generation-jobs/{generation_id}/cancel", response_model=GenerationJobResponse, tags=["Generation"])
def cancel_generation_job(
    generation_id: str,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    try:
        job = GenerationStore(REVIEW_PERSISTENCE).cancel_job(generation_id, owner_user_id=identity.user_id)
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    return {"generation_job": _generation_job_response(job)}


@app.post("/api/generation-jobs/{generation_id}/retry", status_code=202, response_model=GenerationJobResponse, tags=["Generation"])
def retry_generation_job(
    generation_id: str,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    try:
        job = GenerationStore(REVIEW_PERSISTENCE).retry_job(generation_id, owner_user_id=identity.user_id)
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    for relative_path in job.pop("_discarded_artifact_paths", []):
        try:
            _generation_artifact_path(str(relative_path)).unlink(missing_ok=True)
        except OSError:
            pass
    return {"generation_job": _generation_job_response(job)}


@app.post("/api/generation-jobs/{generation_id}/approve", response_model=GenerationJobResponse, tags=["Generation"])
def approve_generation_job(
    generation_id: str,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    store = GenerationStore(REVIEW_PERSISTENCE)
    existing = store.get_job(generation_id, owner_user_id=identity.user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    _, revision = _load_generation_review(str(existing["review_id"]), identity)
    try:
        job = store.approve_job(
            generation_id,
            owner=identity.as_owner_dict(),
            current_revision=int(revision or 0),
        )
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    return {"generation_job": _generation_job_response(job or existing)}


@app.get("/api/generation-jobs/{generation_id}/artifacts", response_model=GenerationArtifactListResponse, tags=["Generation"])
def list_generation_artifacts(
    generation_id: str,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    _require_generation_database()
    store = GenerationStore(REVIEW_PERSISTENCE)
    if store.get_job(generation_id, owner_user_id=identity.user_id) is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    return {
        "generation_id": generation_id,
        "artifacts": [_generation_artifact_response(item) for item in store.list_artifacts(generation_id, owner_user_id=identity.user_id)],
    }


@app.get("/api/generation-jobs/{generation_id}/artifacts/{artifact_id}", tags=["Generation"])
def download_generation_artifact(
    generation_id: str,
    artifact_id: str,
    identity: IdentityContext = Depends(require_identity),
) -> FileResponse:
    _require_generation_database()
    artifact = GenerationStore(REVIEW_PERSISTENCE).get_artifact(
        generation_id,
        artifact_id,
        owner_user_id=identity.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Generation artifact not found.")
    path = _generation_artifact_path(str(artifact["relative_path"]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Generation artifact file not found.")
    return FileResponse(str(path), filename=str(artifact["filename"]), media_type=artifact.get("mime_type"))


@app.post("/api/generation-worker/jobs/claim", response_model=GenerationWorkerClaimResponse, responses={204: {"description": "No compatible queued job"}}, tags=["Generation Worker"])
def claim_generation_worker_job(
    body: GenerationWorkerClaim,
    _: None = Depends(require_generation_worker),
) -> JSONResponse:
    _require_generation_database()
    try:
        job = GenerationStore(REVIEW_PERSISTENCE).claim_job(
            body.worker_id,
            body.capabilities,
            lease_seconds=_generation_lease_seconds(),
        )
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    if job is None:
        return Response(status_code=204)
    return JSONResponse(status_code=200, content={"generation_job": job})


@app.post("/api/generation-worker/jobs/{generation_id}/heartbeat", response_model=GenerationJobResponse, tags=["Generation Worker"])
def heartbeat_generation_worker_job(
    generation_id: str,
    body: GenerationWorkerHeartbeat,
    _: None = Depends(require_generation_worker),
) -> dict[str, Any]:
    _require_generation_database()
    return {"generation_job": _update_generation_worker_job(generation_id, body.worker_id, stage=body.stage, progress=body.progress)}


@app.patch("/api/generation-worker/jobs/{generation_id}/status", response_model=GenerationJobResponse, tags=["Generation Worker"])
def update_generation_worker_status(
    generation_id: str,
    body: GenerationWorkerStatus,
    _: None = Depends(require_generation_worker),
) -> dict[str, Any]:
    _require_generation_database()
    return {
        "generation_job": _update_generation_worker_job(
            generation_id,
            body.worker_id,
            status=body.status,
            stage=body.stage,
            progress=body.progress,
        )
    }


@app.post(
    "/api/generation-worker/jobs/{generation_id}/artifacts",
    status_code=201,
    response_model=GenerationArtifactResponse,
    responses={
        409: {"description": "Worker lease or task state conflict"},
        413: {"description": "Artifact exceeds GENERATION_MAX_ARTIFACT_MB"},
        415: {"description": "Artifact MIME type does not match artifact_type"},
    },
    tags=["Generation Worker"],
)
async def upload_generation_worker_artifact(
    generation_id: str,
    file: UploadFile = File(...),
    worker_id: str = Form(...),
    artifact_type: str = Form(...),
    is_mock: bool = Form(False),
    _: None = Depends(require_generation_worker),
) -> dict[str, Any]:
    _require_generation_database()
    normalized_type = str(artifact_type).strip().lower()[:64]
    allowed_mime_types = {
        "png": {"image/png"},
        "pdf": {"application/pdf"},
        "model_manifest": {"application/json"},
        "log": {"application/json", "text/plain"},
        "sldprt": {"application/octet-stream", "application/x-solidworks"},
        "slddrw": {"application/octet-stream", "application/x-solidworks"},
        "dwg": {"application/octet-stream", "image/vnd.dwg", "application/acad"},
        "dxf": {"application/octet-stream", "image/vnd.dxf", "application/dxf", "text/plain"},
        "step": {"application/octet-stream", "model/step", "application/step"},
        "stl": {"application/octet-stream", "model/stl", "application/sla"},
    }
    if normalized_type not in allowed_mime_types:
        raise HTTPException(status_code=400, detail={"code": "unsupported_artifact_type"})
    normalized_mime = str(file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if normalized_mime not in allowed_mime_types[normalized_type]:
        raise HTTPException(
            status_code=415,
            detail={"code": "artifact_mime_mismatch", "artifact_type": normalized_type, "mime_type": normalized_mime},
        )
    max_bytes = _generation_max_artifact_bytes()
    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Generation artifact is empty.")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Generation artifact exceeds the configured size limit.")
    artifact_id = uuid.uuid4().hex[:16]
    safe_name = _safe_filename(file.filename or f"{artifact_id}.bin")[:240]
    relative = Path(generation_id) / f"{artifact_id}_{safe_name}"
    target = _generation_artifact_path(relative.as_posix())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    store = GenerationStore(REVIEW_PERSISTENCE)
    try:
        artifact = store.add_artifact(
            {
                "artifact_id": artifact_id,
                "generation_id": generation_id,
                "artifact_type": normalized_type,
                "filename": safe_name,
                "relative_path": relative.as_posix(),
                "mime_type": file.content_type,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "is_mock": bool(is_mock),
            },
            worker_id=worker_id,
        )
    except PersistenceError as exc:
        target.unlink(missing_ok=True)
        raise _generation_http_error(exc) from exc
    if artifact is None:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail={"code": "worker_lease_or_state_conflict"})
    if normalized_type == "pdf":
        try:
            _create_generation_pdf_preview(
                store,
                generation_id=generation_id,
                worker_id=worker_id,
                pdf_artifact=artifact,
                pdf_path=target,
            )
        except Exception as exc:
            try:
                store.record_event(
                    generation_id,
                    "generation_preview_failed",
                    source="system",
                    payload={
                        "source_artifact_id": artifact_id,
                        "reason": f"{type(exc).__name__}: {exc}"[:1000],
                    },
                )
            except PersistenceError:
                pass
    return {"artifact": _generation_artifact_response(artifact)}


@app.post("/api/generation-worker/jobs/{generation_id}/complete", response_model=GenerationJobResponse, tags=["Generation Worker"])
def complete_generation_worker_job(
    generation_id: str,
    body: GenerationWorkerComplete,
    _: None = Depends(require_generation_worker),
) -> dict[str, Any]:
    _require_generation_database()
    try:
        job = GenerationStore(REVIEW_PERSISTENCE).complete_job(generation_id, worker_id=body.worker_id)
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    if job is None:
        raise HTTPException(status_code=409, detail={"code": "worker_lease_or_state_conflict"})
    return {"generation_job": _generation_job_response(job)}


@app.post("/api/generation-worker/jobs/{generation_id}/failed", response_model=GenerationJobResponse, tags=["Generation Worker"])
def fail_generation_worker_job(
    generation_id: str,
    body: GenerationWorkerFailed,
    _: None = Depends(require_generation_worker),
) -> dict[str, Any]:
    _require_generation_database()
    try:
        job = GenerationStore(REVIEW_PERSISTENCE).fail_job(
            generation_id,
            worker_id=body.worker_id,
            error_code=body.error_code,
            error_message=body.error_message,
        )
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    if job is None:
        raise HTTPException(status_code=409, detail={"code": "worker_lease_or_state_conflict"})
    return {"generation_job": _generation_job_response(job)}


async def run_recognition_execution(
    drawing: UploadFile = File(...),
    candidate_json: UploadFile | None = File(None),
    ocr_json: UploadFile | None = File(None),
    use_werk24: bool = Form(False),
    confirm_upload_to_werk24: bool = Form(False),
    use_cached_werk24: bool = Form(False),
    use_ocr: bool = Form(False),
    ocr_provider: str | None = Form(None),
    use_qwen: bool = Form(True),
    use_geometry: bool = Form(False),
    use_vlm: bool = Form(False),
    use_llm_standardization: bool = Form(False),
    vision_provider: str | None = Form("none"),
    use_paddleocr: bool = Form(False),
    use_sample_ocr: bool = Form(False),
    identity: IdentityContext | None = None,
    job_id: str | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    if identity is None:
        raise RuntimeError("Recognition execution requires an identity context.")
    if use_werk24 and not confirm_upload_to_werk24:
        raise HTTPException(
            status_code=400,
            detail="Werk24 upload requires confirm_upload_to_werk24=true.",
        )

    job_id = job_id or uuid.uuid4().hex[:12]
    job_dir = API_RUN_ROOT / job_id
    input_dir = job_dir / "inputs"
    page_dir = job_dir / "pages"
    input_dir.mkdir(parents=True, exist_ok=True)
    page_dir.mkdir(parents=True, exist_ok=True)

    _report_recognition_progress(progress_callback, "preparing_file", 5)
    drawing_path = input_dir / _safe_filename(drawing.filename or "drawing")
    await _save_upload(drawing, drawing_path)

    warnings: list[str] = []
    _report_recognition_progress(progress_callback, "rendering_preview", 15)
    images = _make_preview_images(drawing_path, page_dir, warnings)
    uploaded_file_info = probe_file(drawing_path)
    image_url = _artifact_url(job_id, Path(images[0]).relative_to(job_dir)) if images else None

    candidates: list[dict[str, Any]] = []
    candidate_sources: list[str] = []
    raw_payloads: dict[str, Any] = {}

    if candidate_json is not None and candidate_json.filename:
        candidate_json_path = input_dir / _safe_filename(candidate_json.filename)
        await _save_upload(candidate_json, candidate_json_path)
        candidate_payload = read_json(candidate_json_path)
        candidates.extend(_candidate_list_from_payload(candidate_payload))
        raw_payloads["candidate_json"] = candidate_payload
        candidate_sources.append("candidate_json")

    if use_cached_werk24:
        cached_werk24_path = OUTPUT_ROOT / "werk24_candidates.json"
        if cached_werk24_path.exists():
            cached_payload = read_json(cached_werk24_path)
            candidates.extend(cached_payload.get("candidates", []))
            raw_payloads["cached_werk24"] = cached_payload
            candidate_sources.append("cached_werk24")
        else:
            warnings.append("Cached Werk24 candidates not found: outputs/werk24_candidates.json")

    if use_werk24:
        _report_recognition_progress(progress_callback, "werk24", 25)
        try:
            werk24_payload = await run_in_threadpool(Werk24Engine().extract_with_raw, drawing_path)
            candidates.extend(werk24_payload.get("candidates", []))
            raw_payloads["werk24"] = werk24_payload
            candidate_sources.append("werk24")
        except Exception as exc:
            warnings.append(f"Werk24 extraction failed: {exc}")

    if use_qwen:
        _report_recognition_progress(progress_callback, "qwen_vision", 35)
        try:
            qwen_payload = await run_in_threadpool(
                QwenVisionEngine(work_dir=job_dir / "qwen_pages").extract_with_raw,
                drawing_path,
                [Path(item) for item in images] if images else None,
            )
            candidates.extend(qwen_payload.get("candidates", []))
            raw_payloads["qwen_vision"] = qwen_payload
            candidate_sources.append("qwen_vision")
            write_json(job_dir / "qwen_vision_raw.json", qwen_payload)
        except Exception as exc:
            warnings.append(f"Qwen vision extraction failed: {type(exc).__name__}: {exc}")

    if _needs_dimension_grounding_ocr(candidates, uploaded_file_info, candidate_sources):
        _report_recognition_progress(progress_callback, "dimension_ocr", 55)
        try:
            warnings.append(
                "Qwen 核心尺寸缺少可定位依据，已自动调用本地 RapidOCR 做坐标交叉复核。"
            )
            ocr_payload = await run_in_threadpool(
                UnifiedOcrEngine(
                    provider="rapidocr",
                    work_dir=job_dir / "ocr_dimension_grounding_pages",
                    diagnostics_path=job_dir / "ocr_dimension_grounding_diagnostics.json",
                    dpi=240,
                ).extract_with_raw,
                drawing_path,
            )
            candidates.extend(ocr_payload.get("candidates", []))
            raw_payloads["rapidocr_dimension_grounding"] = ocr_payload
            candidate_sources.append("rapidocr_dimension_grounding")
            warnings.extend(str(item) for item in ocr_payload.get("warnings", []))
        except OcrProviderError as exc:
            diagnostics_url = _artifact_url(job_id, Path("ocr_dimension_grounding_diagnostics.json"))
            warnings.append(f"Dimension-grounding OCR failed: {exc}; diagnostics_url={diagnostics_url}")
        except Exception as exc:
            warnings.append(f"Dimension-grounding OCR failed: {type(exc).__name__}: {exc}")

    if use_geometry:
        _report_recognition_progress(progress_callback, "geometry_review", 65)
        try:
            geometry_payload = await run_in_threadpool(
                GeometryEngine(work_dir=job_dir / "geometry_pages").extract_with_raw,
                drawing_path,
                [Path(item) for item in images] if images else None,
            )
            candidates.extend(geometry_payload.get("candidates", []))
            raw_payloads["geometry"] = geometry_payload
            candidate_sources.append("geometry")
            warnings.extend(str(item) for item in geometry_payload.get("warnings", []))
            write_json(job_dir / "geometry_evidence.json", geometry_payload)
        except Exception as exc:
            warnings.append(f"Geometry analysis failed: {type(exc).__name__}: {exc}")

    should_use_ocr = use_ocr or use_paddleocr or ocr_provider is not None
    if should_use_ocr:
        _report_recognition_progress(progress_callback, "ocr_review", 70)
        try:
            requested_provider = normalize_ocr_provider(
                ocr_provider or ("auto" if use_paddleocr else os.getenv("OCR_PROVIDER", "auto"))
            )
            ocr_payload = await run_in_threadpool(
                UnifiedOcrEngine(
                    provider=requested_provider,
                    work_dir=job_dir / "ocr_pages",
                    diagnostics_path=job_dir / "ocr_diagnostics.json",
                ).extract_with_raw,
                drawing_path,
            )
            candidates.extend(ocr_payload.get("candidates", []))
            selected_provider = str(ocr_payload.get("provider") or "ocr")
            raw_payloads[selected_provider] = ocr_payload
            candidate_sources.append(selected_provider)
            warnings.extend(str(item) for item in ocr_payload.get("warnings", []))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OcrProviderError as exc:
            diagnostics_url = _artifact_url(job_id, Path("ocr_diagnostics.json"))
            warnings.append(f"{exc}; diagnostics_url={diagnostics_url}")
        except Exception as exc:
            warnings.append(f"OCR extraction failed: {type(exc).__name__}: {exc}")

    if ocr_json is not None and ocr_json.filename:
        ocr_json_path = input_dir / _safe_filename(ocr_json.filename)
        await _save_upload(ocr_json, ocr_json_path)
        ocr_candidates = OcrJsonEngine(ocr_json_path).extract()
        candidates.extend(ocr_candidates)
        raw_payloads["ocr_json"] = read_json(ocr_json_path)
        candidate_sources.append("ocr_json")

    if use_sample_ocr:
        sample_ocr_path = project_path("data", "samples", "ocr_example.json")
        ocr_candidates = OcrJsonEngine(sample_ocr_path).extract()
        candidates.extend(ocr_candidates)
        raw_payloads["sample_ocr_json"] = read_json(sample_ocr_path)
        candidate_sources.append("sample_ocr_json")

    if use_vlm:
        provider = str(vision_provider or "none").strip().lower()
        raw_payloads["vlm"] = {
            "status": "skipped",
            "provider": provider,
            "policy": "review_only_requires_ocr_or_geometry_evidence",
            "reason": "VLM adapter is not configured in this local MVP.",
        }
        warnings.append(
            "VLM review skipped: no vision provider is configured. VLM may only cite OCR/geometry evidence "
            "and must not invent dimensions."
        )

    if _needs_ocr_fallback(candidates, uploaded_file_info, candidate_sources):
        _report_recognition_progress(progress_callback, "ocr_fallback", 78)
        try:
            warnings.append("No structured candidates were produced from the selected engines; trying local RapidOCR fallback.")
            ocr_payload = await run_in_threadpool(
                UnifiedOcrEngine(
                    provider="rapidocr",
                    work_dir=job_dir / "ocr_fallback_pages",
                    diagnostics_path=job_dir / "ocr_fallback_diagnostics.json",
                    dpi=200,
                ).extract_with_raw,
                drawing_path,
            )
            candidates.extend(ocr_payload.get("candidates", []))
            raw_payloads["rapidocr_fallback"] = ocr_payload
            candidate_sources.append("rapidocr_fallback")
            warnings.extend(str(item) for item in ocr_payload.get("warnings", []))
        except OcrProviderError as exc:
            diagnostics_url = _artifact_url(job_id, Path("ocr_fallback_diagnostics.json"))
            warnings.append(f"RapidOCR fallback failed: {exc}; diagnostics_url={diagnostics_url}")
        except Exception as exc:
            warnings.append(f"RapidOCR fallback failed: {type(exc).__name__}: {exc}")

    business_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("feature_type") != "dimension_evidence"
    ]
    if not business_candidates:
        warnings.append(
            "No structured recognition candidates were produced. Geometry evidence may still be available, but "
            "dimension fields need Qwen, OCR, imported OCR JSON, or manual confirmation."
        )

    _report_recognition_progress(progress_callback, "building_review", 88)
    rules = read_json(project_path("config", "factory_rules.json"))
    review = DrawingReviewWorkflow(rules).run(str(drawing_path), candidates, run_standardization=False)
    apply_generation_defaults(review)
    llm_standardization_payload: dict[str, Any] | None = None
    if use_llm_standardization:
        warnings.append("LLM/RAG 标准化已改为点击“标准化”按钮后执行，本次上传仅完成识别。")

    _report_recognition_progress(progress_callback, "saving_result", 95)
    candidates_payload = {
        "job_id": job_id,
        "sources": candidate_sources,
        "candidates": candidates,
        "dimension_evidence": raw_payloads.get("geometry", {}).get("dimension_evidence", []),
        "raw_payloads": raw_payloads,
    }
    write_json(job_dir / "candidates.json", candidates_payload)
    write_json(job_dir / "review.json", review)
    write_json(job_dir / "file_info.json", uploaded_file_info)
    write_json(job_dir / "warnings.json", {"warnings": warnings})
    write_json(job_dir / "owner.json", identity.as_owner_dict())
    persistence = _create_review_persistence(
        job_id,
        review,
        file_info=uploaded_file_info,
        artifact_dir=str(job_dir),
        identity=identity,
    )

    return {
        "job_id": job_id,
        "candidate_sources": candidate_sources,
        "candidate_count": len(candidates),
        "business_candidate_count": len(business_candidates),
        "geometry_evidence_count": len(raw_payloads.get("geometry", {}).get("dimension_evidence", [])),
        "image_url": image_url,
        "review_url": _artifact_url(job_id, Path("review.json")),
        "candidates_url": _artifact_url(job_id, Path("candidates.json")),
        "qwen_url": _artifact_url(job_id, Path("qwen_vision_raw.json")) if "qwen_vision" in raw_payloads else None,
        "llm_standardization_url": _artifact_url(job_id, Path("llm_standardization_raw.json")) if llm_standardization_payload and llm_standardization_payload.get("standardization_results") else None,
        "geometry_url": _artifact_url(job_id, Path("geometry_evidence.json")) if "geometry" in raw_payloads else None,
        "warnings": warnings,
        "review_revision": persistence.get("revision"),
        "persistence": _persistence_response(persistence),
        "review": review,
    }


@app.post("/api/reviews", status_code=202)
async def create_review(
    drawing: UploadFile = File(...),
    candidate_json: UploadFile | None = File(None),
    ocr_json: UploadFile | None = File(None),
    use_werk24: bool = Form(False),
    confirm_upload_to_werk24: bool = Form(False),
    use_cached_werk24: bool = Form(False),
    use_ocr: bool = Form(False),
    ocr_provider: str | None = Form(None),
    use_qwen: bool = Form(True),
    use_geometry: bool = Form(False),
    use_vlm: bool = Form(False),
    use_llm_standardization: bool = Form(False),
    vision_provider: str | None = Form("none"),
    use_paddleocr: bool = Form(False),
    use_sample_ocr: bool = Form(False),
    identity: IdentityContext = Depends(require_identity),
) -> JSONResponse:
    """Persist the upload and enqueue it without waiting for OCR or Qwen."""
    if not REVIEW_PERSISTENCE.configured:
        raise HTTPException(status_code=503, detail="PostgreSQL is required for background recognition jobs.")
    if use_werk24 and not confirm_upload_to_werk24:
        raise HTTPException(status_code=400, detail="Werk24 upload requires confirm_upload_to_werk24=true.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = API_RUN_ROOT / job_id
    incoming_dir = job_dir / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    source_drawing_name = _safe_filename(drawing.filename or "drawing")
    drawing_path = incoming_dir / source_drawing_name
    await _save_upload(drawing, drawing_path)
    queued_file_info = {
        "filename": drawing.filename or source_drawing_name,
        "content_type": drawing.content_type,
        "size_bytes": drawing_path.stat().st_size,
    }

    options: dict[str, Any] = {
        "drawing_path": str(drawing_path.relative_to(job_dir)),
        "use_werk24": use_werk24,
        "confirm_upload_to_werk24": confirm_upload_to_werk24,
        "use_cached_werk24": use_cached_werk24,
        "use_ocr": use_ocr,
        "ocr_provider": ocr_provider,
        "use_qwen": use_qwen,
        "use_geometry": use_geometry,
        "use_vlm": use_vlm,
        "use_llm_standardization": use_llm_standardization,
        "vision_provider": vision_provider,
        "use_paddleocr": use_paddleocr,
        "use_sample_ocr": use_sample_ocr,
    }
    if candidate_json is not None and candidate_json.filename:
        candidate_path = incoming_dir / f"candidate_{_safe_filename(candidate_json.filename)}"
        await _save_upload(candidate_json, candidate_path)
        options["candidate_json_path"] = str(candidate_path.relative_to(job_dir))
    if ocr_json is not None and ocr_json.filename:
        ocr_path = incoming_dir / f"ocr_{_safe_filename(ocr_json.filename)}"
        await _save_upload(ocr_json, ocr_path)
        options["ocr_json_path"] = str(ocr_path.relative_to(job_dir))

    try:
        job = REVIEW_PERSISTENCE.create_recognition_job(
            job_id,
            drawing_name=drawing.filename or source_drawing_name,
            artifact_dir=str(job_dir),
            input_filename=source_drawing_name,
            options=options,
            file_info=queued_file_info,
            owner=identity.as_owner_dict(),
        )
    except PersistenceError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise _persistence_http_error(exc) from exc
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "drawing_name": job.get("drawing_name"),
            "recognition_status": job.get("status"),
            "recognition_stage": job.get("stage"),
            "recognition_progress": job.get("progress"),
            "queue_position": job.get("queue_position"),
            "message": "Drawing uploaded and queued for background recognition.",
        },
    )


@app.get("/api/reviews")
def list_reviews(limit: int = 20, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    bounded_limit = min(max(limit, 1), 100)
    if REVIEW_PERSISTENCE.configured:
        try:
            reviews = REVIEW_PERSISTENCE.list_reviews(limit=bounded_limit, owner_user_id=identity.user_id)
            recognition_jobs = REVIEW_PERSISTENCE.list_recognition_jobs(limit=bounded_limit, owner_user_id=identity.user_id)
        except PersistenceError as exc:
            raise _persistence_http_error(exc) from exc
        reviews_by_id = {str(item.get("job_id")): item for item in reviews}
        for job in recognition_jobs:
            job_id = str(job.get("job_id") or "")
            if not job_id:
                continue
            existing = reviews_by_id.get(job_id)
            if existing is None:
                existing = {
                    "job_id": job_id,
                    "drawing_name": job.get("drawing_name"),
                    "drawing_no": None,
                    "spring_type": None,
                    "overall_status": None,
                    "revision": None,
                    "created_at": job.get("created_at"),
                    "updated_at": job.get("updated_at"),
                }
                reviews.append(existing)
                reviews_by_id[job_id] = existing
            existing.update(
                {
                    "recognition_status": job.get("status"),
                    "recognition_stage": job.get("stage"),
                    "recognition_progress": job.get("progress"),
                    "recognition_error": job.get("error_message"),
                    "queue_position": job.get("queue_position"),
                    "recognition_attempt_count": job.get("attempt_count"),
                    "updated_at": job.get("updated_at") or existing.get("updated_at"),
                }
            )
        reviews.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        reviews = reviews[:bounded_limit]
        for item in reviews:
            item["image_url"] = _review_preview_url(item["job_id"])
        return {
            "persistence": _persistence_response({"mode": "postgresql"}),
            "reviews": reviews,
        }

    return {
        "persistence": _persistence_response({"mode": "json_fallback"}),
        "reviews": _list_local_reviews(limit=bounded_limit, owner_user_id=identity.user_id),
    }


@app.post("/api/reviews/standardize")
async def standardize_review_payload(
    payload: dict[str, Any] | None = Body(None),
    _: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    body = payload or {}
    review = body.get("review")
    if not isinstance(review, dict):
        raise HTTPException(status_code=400, detail="standardize requires a review object.")
    warnings: list[str] = []
    llm_standardization_payload = await _run_standardization_stage(
        review,
        warnings,
        use_llm_standardization=bool(body.get("use_llm_standardization")),
    )
    return {
        "warnings": warnings,
        "llm_standardization": _llm_standardization_summary(llm_standardization_payload),
        "review": review,
    }


@app.post("/api/reviews/reasonableness")
def assess_review_reasonableness(
    payload: dict[str, Any] | None = Body(None),
    _: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    """Return a lightweight deterministic diagnostic for the caller's current review state."""
    review = (payload or {}).get("review")
    if not isinstance(review, dict):
        raise HTTPException(status_code=400, detail="reasonableness requires a review object.")
    assessment = assess_parameter_reasonableness(review)
    return {"parameter_reasonableness": assessment}


@app.post("/api/reviews/{job_id}/standardize")
async def standardize_existing_review(
    job_id: str,
    payload: dict[str, Any] | None = Body(None),
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    body = payload or {}
    review = body.get("review")
    _ensure_review_owned(job_id, review_path, identity)
    if not isinstance(review, dict):
        review, _ = _load_persisted_review(job_id, review_path, identity)

    warnings: list[str] = []
    llm_standardization_payload = await _run_standardization_stage(
        review,
        warnings,
        use_llm_standardization=bool(body.get("use_llm_standardization")),
        job_dir=job_dir,
    )
    persistence = _save_review_persistence(
        job_id,
        review,
        review_path=review_path,
        expected_revision=body.get("expected_revision"),
        identity=identity,
        events=[
            {
                "event_type": "standardization_completed",
                "source": "standardization_tool",
                "reason": "已根据当前审查参数生成标准化建议",
                "metadata": {"use_llm_standardization": bool(body.get("use_llm_standardization"))},
            }
        ],
    )
    if warnings:
        write_json(job_dir / "standardization_warnings.json", {"warnings": warnings})

    return {
        "job_id": job_id,
        "llm_standardization_url": _artifact_url(job_id, Path("llm_standardization_raw.json"))
        if llm_standardization_payload and llm_standardization_payload.get("standardization_results")
        else None,
        "warnings": warnings,
        "review_revision": persistence.get("revision"),
        "persistence": _persistence_response(persistence),
        "llm_standardization": _llm_standardization_summary(llm_standardization_payload),
        "review": review,
    }


@app.post("/api/reviews/standardization-chat")
async def standardization_chat_payload(
    payload: dict[str, Any] | None = Body(None),
    _: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    body = payload or {}
    review = body.get("review")
    message = str(body.get("message") or "").strip()
    if not isinstance(review, dict):
        raise HTTPException(status_code=400, detail="standardization chat requires a review object.")
    if not message:
        raise HTTPException(status_code=400, detail="standardization chat requires a message.")
    try:
        accuracy_request = parse_accuracy_standardization_request(message)
        accuracy_result = None
        if accuracy_request and accuracy_request.get("status") == "ready":
            accuracy_result = select_general_accuracy_grade(review, str(accuracy_request["requested_grade"]))
            warnings: list[str] = []
            llm_payload = await _run_standardization_stage(
                review,
                warnings,
                use_llm_standardization=True,
            )
            accuracy_result.update(
                {
                    "status": "completed",
                    "standardization_result_count": len(review.get("standardization_results") or []),
                    "warnings": warnings,
                    "llm_standardization": _llm_standardization_summary(llm_payload),
                }
            )
        context = await _prepare_standardization_chat_context(review, message)
        result = chat_about_standardization(
            review,
            message,
            use_llm=bool(body.get("use_llm")),
            supplements=body.get("supplements"),
            active_proposal_id=body.get("active_proposal_id"),
            review_revision=body.get("expected_revision"),
            accuracy_standardization=accuracy_result,
            standardization_batch_revision=None,
            generation_package_export_source="local",
            generation_package_export_revision=None,
        )
        return _attach_standardization_chat_context(result, context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/reviews/{job_id}/standardization-chat")
async def standardization_chat_existing_review(
    job_id: str,
    payload: dict[str, Any] | None = Body(None),
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    body = payload or {}
    review = body.get("review")
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="standardization chat requires a message.")
    persisted_review, current_revision = _load_persisted_review(job_id, review_path, identity)
    accuracy_request = parse_accuracy_standardization_request(message)
    is_accuracy_execution = bool(accuracy_request and accuracy_request.get("status") == "ready")
    if is_accuracy_execution:
        if body.get("expected_revision") in (None, ""):
            raise HTTPException(
                status_code=400,
                detail={"code": "expected_revision_required", "message": "精度标准化指令必须提供 expected_revision。"},
            )
        expected_revision = _expected_review_revision(body.get("expected_revision"))
        if expected_revision is not None and expected_revision != current_revision:
            raise HTTPException(
                status_code=409,
                detail={"message": "当前审查数据已被其他操作更新，请刷新后重试。", "current_revision": current_revision},
            )
        review = persisted_review
    elif not isinstance(review, dict):
        review = persisted_review
    try:
        accuracy_result = None
        if is_accuracy_execution:
            accuracy_result = select_general_accuracy_grade(review, str(accuracy_request["requested_grade"]))
            warnings: list[str] = []
            llm_payload = await _run_standardization_stage(
                review,
                warnings,
                use_llm_standardization=True,
                job_dir=job_dir,
            )
            accuracy_result.update(
                {
                    "status": "completed",
                    "standardization_result_count": len(review.get("standardization_results") or []),
                    "warnings": warnings,
                    "llm_standardization": _llm_standardization_summary(llm_payload),
                }
            )
        context = await _prepare_standardization_chat_context(review, message)
        result = chat_about_standardization(
            review,
            message,
            use_llm=bool(body.get("use_llm")),
            supplements=body.get("supplements"),
            active_proposal_id=body.get("active_proposal_id"),
            review_revision=current_revision,
            accuracy_standardization=accuracy_result,
            standardization_batch_revision=(current_revision + 1) if current_revision is not None else None,
            generation_package_export_source="server",
            generation_package_export_revision=(current_revision + 1) if current_revision is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = _attach_standardization_chat_context(result, context)
    audit_event = {
        "event_type": "standardization_chat_completed",
        "source": "ai_chat",
        "reason": "已完成一次标准化对话",
        "metadata": {"use_llm": bool(body.get("use_llm"))},
    }
    if accuracy_result:
        audit_event = {
            "event_type": "accuracy_standardization_completed",
            "target_field": "accuracy_grade",
            "source": "ai_chat",
            "reason": f"已按通用精度等级{accuracy_result['requested_grade']}重新生成标准化方案",
            "before_state": {"value": accuracy_result.get("previous_grade")},
            "after_state": {"value": accuracy_result.get("requested_grade")},
            "metadata": {
                "scope": "general",
                "selection_changed": accuracy_result.get("selection_changed"),
                "specialized_grades_retained": accuracy_result.get("specialized_grades_retained") or {},
                "standardization_result_count": accuracy_result.get("standardization_result_count"),
                "invalidated_proposal_ids": accuracy_result.get("invalidated_proposal_ids") or [],
            },
        }
    is_generation_package_export = (
        (result.get("intent") or {}).get("type") == "generation_package_export_request"
    )
    persistence = _save_review_persistence(
        job_id,
        result["review"],
        review_path=review_path,
        expected_revision=body.get("expected_revision"),
        identity=identity,
        events=[] if is_generation_package_export else [audit_event],
    )
    write_json(job_dir / "standardization_chat.json", {"turns": result["review"].get("standardization_chat", [])})
    return {
        "job_id": job_id,
        "review_revision": persistence.get("revision"),
        "persistence": _persistence_response(persistence),
        **result,
    }


@app.post("/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/apply")
def apply_review_parameter_change_proposal(
    job_id: str,
    proposal_id: str,
    payload: dict[str, Any] | None = Body(None),
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    body = payload or {}
    if body.get("expected_review_revision") in (None, ""):
        raise HTTPException(status_code=400, detail={"code": "expected_review_revision_required", "message": "expected_review_revision 为必填项。"})
    try:
        version = int(body.get("version"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "proposal_version_required", "message": "version 必须是正整数。"}) from exc
    if version <= 0:
        raise HTTPException(status_code=400, detail={"code": "proposal_version_required", "message": "version 必须是正整数。"})

    review_path = _job_dir(job_id) / "review.json"
    review, _ = _load_persisted_review(job_id, review_path, identity)
    try:
        applied_review, result = apply_parameter_change_proposal(review, proposal_id, version=version)
    except ParameterProposalError as exc:
        status_code = 404 if exc.code == "proposal_not_found" else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc), "proposal": exc.current},
        ) from exc
    persistence = _save_review_persistence(
        job_id,
        applied_review,
        review_path=review_path,
        expected_revision=body.get("expected_review_revision"),
        identity=identity,
        events=[
            {
                "event_type": "parameter_change_proposal_applied",
                "source": "ai_chat",
                "reason": "用户整体应用AI审图修改方案",
                "metadata": {
                    "proposal_id": proposal_id,
                    "proposal_version": version,
                    "changed_fields": [item.get("target_field") for item in result.get("patches") or []],
                    "technical_requirement_changes": result.get("technical_requirement_changes") or [],
                    "load_point_changes": result.get("load_point_changes") or [],
                },
            }
        ],
    )
    return {
        "job_id": job_id,
        "review_revision": persistence.get("revision"),
        "persistence": _persistence_response(persistence),
        "change_proposal": result["proposal"],
        "log_id": result["log_id"],
        "review": applied_review,
    }


@app.post("/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/discard")
def discard_review_parameter_change_proposal(
    job_id: str,
    proposal_id: str,
    payload: dict[str, Any] | None = Body(None),
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    body = payload or {}
    if body.get("expected_review_revision") in (None, ""):
        raise HTTPException(status_code=400, detail={"code": "expected_review_revision_required", "message": "expected_review_revision 为必填项。"})
    try:
        version = int(body.get("version"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "proposal_version_required", "message": "version 必须是正整数。"}) from exc
    if version <= 0:
        raise HTTPException(status_code=400, detail={"code": "proposal_version_required", "message": "version 必须是正整数。"})

    review_path = _job_dir(job_id) / "review.json"
    review, _ = _load_persisted_review(job_id, review_path, identity)
    try:
        proposal = discard_parameter_change_proposal(review, proposal_id, version=version)
    except ParameterProposalError as exc:
        status_code = 404 if exc.code == "proposal_not_found" else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc), "proposal": exc.current},
        ) from exc
    persistence = _save_review_persistence(
        job_id,
        review,
        review_path=review_path,
        expected_revision=body.get("expected_review_revision"),
        identity=identity,
        events=[
            {
                "event_type": "parameter_change_proposal_discarded",
                "source": "ai_chat",
                "reason": "用户放弃AI参数修改方案",
                "metadata": {"proposal_id": proposal_id, "proposal_version": version},
            }
        ],
    )
    return {
        "job_id": job_id,
        "review_revision": persistence.get("revision"),
        "persistence": _persistence_response(persistence),
        "change_proposal": proposal,
        "review": review,
    }


@app.patch("/api/reviews/{job_id}")
def save_existing_review(
    job_id: str,
    payload: dict[str, Any] | None = Body(None),
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    body = payload or {}
    review = body.get("review")
    if not isinstance(review, dict):
        raise HTTPException(status_code=400, detail="review must be an object.")
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    _ensure_review_owned(job_id, review_path, identity)
    persistence = _save_review_persistence(
        job_id,
        review,
        review_path=review_path,
        expected_revision=body.get("expected_revision"),
        events=_audit_events_from_payload(body),
        identity=identity,
    )
    return {
        "job_id": job_id,
        "review_revision": persistence.get("revision"),
        "persistence": _persistence_response(persistence),
        "events": persistence.get("events", []),
    }


@app.delete("/api/reviews/{job_id}")
def delete_existing_review(job_id: str, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    if REVIEW_PERSISTENCE.configured:
        try:
            task_result = REVIEW_PERSISTENCE.request_recognition_job_deletion(job_id, owner_user_id=identity.user_id)
            if task_result and task_result.get("action") == "cancelling":
                return {
                    "job_id": job_id,
                    "deleted": True,
                    "status": "cancelling",
                    "persistence": _persistence_response({"mode": "postgresql"}),
                    "artifact_cleanup": "pending_worker_cancellation",
                }
            deleted = REVIEW_PERSISTENCE.delete_review(job_id, owner_user_id=identity.user_id)
        except PersistenceError as exc:
            raise _persistence_http_error(exc) from exc
        if not deleted and task_result is None:
            raise HTTPException(status_code=404, detail="Review not found.")
        persistence = _persistence_response({"mode": "postgresql"})
    else:
        if not _local_job_owned(job_dir, identity.user_id):
            raise HTTPException(status_code=404, detail="Review not found.")
        persistence = _persistence_response({"mode": "json_fallback"})

    artifact_cleanup = "not_found"
    if job_dir.exists():
        try:
            shutil.rmtree(job_dir)
            artifact_cleanup = "deleted"
        except OSError:
            artifact_cleanup = "pending"

    return {
        "job_id": job_id,
        "deleted": True,
        "persistence": persistence,
        "artifact_cleanup": artifact_cleanup,
    }


@app.get("/api/reviews/{job_id}/recognition-status")
def get_recognition_status(job_id: str, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    if not REVIEW_PERSISTENCE.configured:
        raise HTTPException(status_code=404, detail="Recognition job not found.")
    try:
        job = REVIEW_PERSISTENCE.get_recognition_job(job_id, owner_user_id=identity.user_id)
    except PersistenceError as exc:
        raise _persistence_http_error(exc) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Recognition job not found.")
    # The frontend may open a review as soon as this poll reports completion,
    # before its history refresh has supplied the preview URL.
    if job.get("status") == "completed":
        job["image_url"] = _review_preview_url(job_id)
    return {"job_id": job_id, "recognition": job}


@app.post("/api/reviews/{job_id}/retry", status_code=202)
def retry_recognition_job(job_id: str, identity: IdentityContext = Depends(require_identity)) -> JSONResponse:
    if not REVIEW_PERSISTENCE.configured:
        raise HTTPException(status_code=404, detail="Recognition job not found.")
    try:
        job = REVIEW_PERSISTENCE.retry_recognition_job(job_id, owner_user_id=identity.user_id)
    except PersistenceError as exc:
        raise _persistence_http_error(exc) from exc
    if job is None:
        raise HTTPException(status_code=409, detail="Only failed recognition jobs can be retried.")
    return JSONResponse(status_code=202, content={"job_id": job_id, "recognition": job})


@app.get("/api/reviews/{job_id}/changes")
def get_review_changes(
    job_id: str,
    limit: int = 100,
    identity: IdentityContext = Depends(require_identity),
) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    if REVIEW_PERSISTENCE.configured:
        try:
            stored = REVIEW_PERSISTENCE.get_review(job_id, owner_user_id=identity.user_id)
            if stored is not None:
                return {
                    "job_id": job_id,
                    "review_revision": stored["revision"],
                    "persistence": _persistence_response({"mode": "postgresql", "revision": stored["revision"]}),
                    "events": REVIEW_PERSISTENCE.list_change_events(job_id, limit=limit, owner_user_id=identity.user_id),
                }
        except PersistenceError as exc:
            raise _persistence_http_error(exc) from exc
    if not _local_job_owned(job_dir, identity.user_id) or not review_path.exists():
        raise HTTPException(status_code=404, detail="Review not found.")
    review = read_json(review_path)
    history = review.get("change_history") if isinstance(review.get("change_history"), list) else []
    return {
        "job_id": job_id,
        "review_revision": None,
        "persistence": _persistence_response({"mode": "json_fallback", "revision": None}),
        "events": list(reversed(history[-min(max(limit, 1), 500) :])),
    }


@app.get("/api/reviews/{job_id}")
def get_review(job_id: str, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    if REVIEW_PERSISTENCE.configured:
        try:
            job = REVIEW_PERSISTENCE.get_recognition_job(job_id, owner_user_id=identity.user_id)
        except PersistenceError as exc:
            raise _persistence_http_error(exc) from exc
        if job is not None and job.get("status") != "completed":
            raise HTTPException(status_code=409, detail={"message": "Recognition is not complete.", "recognition": job})
    review, revision = _load_persisted_review(job_id, review_path, identity)
    if revision is not None:
        review["review_revision"] = revision
    return review


@app.get("/api/reviews/{job_id}/candidates")
def get_candidates(job_id: str, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    candidates_path = job_dir / "candidates.json"
    _ensure_review_owned(job_id, job_dir / "review.json", identity)
    if not candidates_path.exists():
        raise HTTPException(status_code=404, detail="Candidates not found.")
    return read_json(candidates_path)


@app.get("/api/reviews/{job_id}/download")
def download_review(job_id: str, identity: IdentityContext = Depends(require_identity)) -> FileResponse:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    _ensure_review_owned(job_id, review_path, identity)
    if not review_path.exists():
        raise HTTPException(status_code=404, detail="Review not found.")
    return FileResponse(str(review_path), filename=f"{job_id}_review.json")


@app.get("/api/reviews/{job_id}/artifacts/{relative_path:path}")
def get_review_artifact(
    job_id: str,
    relative_path: str,
    identity: IdentityContext = Depends(require_identity),
) -> FileResponse:
    job_dir = _job_dir(job_id)
    _ensure_review_owned(job_id, job_dir / "review.json", identity)
    requested = (job_dir / relative_path).resolve()
    try:
        requested.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found.") from exc
    if not requested.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(str(requested))


def _create_review_persistence(
    job_id: str,
    review: dict[str, Any],
    *,
    file_info: dict[str, Any],
    artifact_dir: str,
    identity: IdentityContext,
) -> dict[str, Any]:
    apply_generation_defaults(review)
    ensure_load_point_ids(review)
    ensure_technical_requirement_ids(review)
    try:
        return REVIEW_PERSISTENCE.create_review(
            job_id,
            review,
            file_info=file_info,
            artifact_dir=artifact_dir,
            owner=identity.as_owner_dict(),
            actor=identity.as_audit_actor(),
        )
    except PersistenceError as exc:
        raise _persistence_http_error(exc) from exc


def _load_persisted_review(
    job_id: str,
    review_path: Path,
    identity: IdentityContext,
) -> tuple[dict[str, Any], int | None]:
    if REVIEW_PERSISTENCE.configured:
        try:
            stored = REVIEW_PERSISTENCE.get_review(job_id, owner_user_id=identity.user_id)
        except PersistenceError as exc:
            raise _persistence_http_error(exc) from exc
        if stored is None:
            raise HTTPException(status_code=404, detail="Review not found.")
        review = stored["review"]
        apply_generation_defaults(review)
        ensure_load_point_ids(review)
        ensure_technical_requirement_ids(review)
        return review, stored["revision"]
    if not _local_job_owned(review_path.parent, identity.user_id) or not review_path.exists():
        raise HTTPException(status_code=404, detail="Review not found.")
    review = read_json(review_path)
    apply_generation_defaults(review)
    ensure_load_point_ids(review)
    ensure_technical_requirement_ids(review)
    return review, None


def _ensure_review_owned(job_id: str, review_path: Path, identity: IdentityContext) -> None:
    _load_persisted_review(job_id, review_path, identity)


def _save_review_persistence(
    job_id: str,
    review: dict[str, Any],
    *,
    review_path: Path,
    expected_revision: Any = None,
    events: list[dict[str, Any]] | None = None,
    identity: IdentityContext,
) -> dict[str, Any]:
    apply_generation_defaults(review)
    ensure_load_point_ids(review)
    ensure_technical_requirement_ids(review)
    revision = _expected_review_revision(expected_revision)
    audit_events = []
    for raw_event in events or []:
        event = dict(raw_event)
        event["actor"] = identity.as_audit_actor()
        audit_events.append(event)
    history_status = "saved" if REVIEW_PERSISTENCE.configured else "saved_local"
    fallback_events = _merge_audit_events_into_review_history(review, audit_events, status=history_status)
    try:
        result = REVIEW_PERSISTENCE.save_review(
            job_id,
            review,
            expected_revision=revision,
            events=audit_events,
            actor=identity.as_audit_actor(),
            artifact_dir=str(review_path.parent),
            owner=identity.as_owner_dict(),
        )
    except RevisionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "当前审查数据已被其他操作更新，请刷新后重试。",
                "current_revision": exc.current_revision,
            },
        ) from exc
    except ReviewAccessError as exc:
        raise HTTPException(status_code=404, detail="Review not found.") from exc
    except PersistenceError as exc:
        raise _persistence_http_error(exc) from exc
    if result.get("mode") == "json_fallback":
        result["events"] = fallback_events
    write_json(review_path, review)
    return result


def _expected_review_revision(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail="expected_revision must be an integer.")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="expected_revision must be an integer.") from exc
    if revision < 1:
        raise HTTPException(status_code=400, detail="expected_revision must be greater than zero.")
    return revision


def _audit_actor_from_payload(body: dict[str, Any]) -> dict[str, Any] | None:
    raw = body.get("actor")
    if not isinstance(raw, dict):
        return None
    allowed = ("erp_user_id", "username", "department_id", "display_name")
    actor = {
        key: str(raw[key]).strip()[:256]
        for key in allowed
        if raw.get(key) not in (None, "") and str(raw[key]).strip()
    }
    return actor or None


def _audit_events_from_payload(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw_events = body.get("events")
    if not isinstance(raw_events, list):
        return []
    events: list[dict[str, Any]] = []
    for raw in raw_events[:100]:
        if not isinstance(raw, dict):
            continue
        event_type = str(raw.get("event_type") or "manual_review_updated").strip()[:96]
        event: dict[str, Any] = {
            "event_type": event_type or "manual_review_updated",
            "target_field": _audit_text(raw.get("target_field"), 192),
            "source": _audit_text(raw.get("source"), 64) or "manual",
            "reason": _audit_text(raw.get("reason"), 2000),
            "before_state": raw.get("before_state") if isinstance(raw.get("before_state"), dict) else None,
            "after_state": raw.get("after_state") if isinstance(raw.get("after_state"), dict) else None,
            "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        }
        client_event_id = _audit_text(raw.get("client_event_id"), 128)
        if client_event_id:
            event["metadata"]["client_event_id"] = client_event_id
        events.append(event)
    return events


def _audit_text(value: Any, limit: int) -> str | None:
    text_value = str(value or "").strip()
    return text_value[:limit] if text_value else None


def _merge_audit_events_into_review_history(
    review: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    status: str,
) -> list[dict[str, Any]]:
    if not events:
        return []
    history = review.setdefault("change_history", [])
    if not isinstance(history, list):
        history = []
        review["change_history"] = history
    existing_by_client_id = {
        str(item.get("client_event_id")): item
        for item in history
        if isinstance(item, dict) and item.get("client_event_id")
    }
    normalized: list[dict[str, Any]] = []
    for event in events:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        client_event_id = metadata.get("client_event_id")
        item = {
            "client_event_id": client_event_id,
            "event_type": event.get("event_type"),
            "target_field": event.get("target_field"),
            "source": event.get("source"),
            "reason": event.get("reason"),
            "before_state": event.get("before_state"),
            "after_state": event.get("after_state"),
            "metadata": metadata,
            "actor": event.get("actor") if isinstance(event.get("actor"), dict) else None,
            "created_at": datetime.now(UTC).isoformat(),
            "sync_status": status,
        }
        existing = existing_by_client_id.get(str(client_event_id)) if client_event_id else None
        if existing is not None:
            existing["sync_status"] = status
            item = existing
        else:
            history.insert(0, item)
        normalized.append(item)
    return normalized


def _persistence_response(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": result.get("mode") or "json_fallback",
        "revision": result.get("revision"),
    }


def _persistence_http_error(exc: PersistenceError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="审查数据存储暂不可用，请检查 PostgreSQL 连接和数据库迁移。",
    )


async def run_recognition_job_record(
    job: dict[str, Any],
    *,
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    """Execute a durable queued job using the original recognition pipeline."""
    job_id = str(job.get("job_id") or "")
    job_dir = _job_dir(job_id)
    options = job.get("options") if isinstance(job.get("options"), dict) else {}
    owner = job.get("owner") if isinstance(job.get("owner"), dict) else {}
    identity = IdentityContext(
        user_id=str(owner.get("user_id") or ""),
        username=str(owner.get("username") or ""),
        real_name=str(owner.get("real_name") or owner.get("username") or ""),
        org_id=str(owner.get("org_id") or ""),
        org_name=str(owner.get("org_name") or ""),
        source="recognition_worker",
    )
    if not all((identity.user_id, identity.username, identity.org_id, identity.org_name)):
        raise RuntimeError("Recognition job is missing its ERP ownership context.")

    drawing_path = _job_relative_input_path(job_dir, options.get("drawing_path"))
    candidate_path = _job_relative_input_path(job_dir, options.get("candidate_json_path"), required=False)
    ocr_path = _job_relative_input_path(job_dir, options.get("ocr_json_path"), required=False)
    opened_files = []
    uploads: list[UploadFile] = []
    try:
        drawing_handle = drawing_path.open("rb")
        opened_files.append(drawing_handle)
        drawing_upload = UploadFile(filename=str(job.get("input_filename") or drawing_path.name), file=drawing_handle)
        uploads.append(drawing_upload)
        candidate_upload = None
        if candidate_path is not None:
            candidate_handle = candidate_path.open("rb")
            opened_files.append(candidate_handle)
            candidate_upload = UploadFile(filename=candidate_path.name, file=candidate_handle)
            uploads.append(candidate_upload)
        ocr_upload = None
        if ocr_path is not None:
            ocr_handle = ocr_path.open("rb")
            opened_files.append(ocr_handle)
            ocr_upload = UploadFile(filename=ocr_path.name, file=ocr_handle)
            uploads.append(ocr_upload)
        return await run_recognition_execution(
            drawing=drawing_upload,
            candidate_json=candidate_upload,
            ocr_json=ocr_upload,
            use_werk24=bool(options.get("use_werk24")),
            confirm_upload_to_werk24=bool(options.get("confirm_upload_to_werk24")),
            use_cached_werk24=bool(options.get("use_cached_werk24")),
            use_ocr=bool(options.get("use_ocr")),
            ocr_provider=_text_or_none(options.get("ocr_provider")),
            use_qwen=bool(options.get("use_qwen", True)),
            use_geometry=bool(options.get("use_geometry")),
            use_vlm=bool(options.get("use_vlm")),
            use_llm_standardization=bool(options.get("use_llm_standardization")),
            vision_provider=_text_or_none(options.get("vision_provider")) or "none",
            use_paddleocr=bool(options.get("use_paddleocr")),
            use_sample_ocr=bool(options.get("use_sample_ocr")),
            identity=identity,
            job_id=job_id,
            progress_callback=progress_callback,
        )
    finally:
        for upload in uploads:
            await upload.close()
        for handle in opened_files:
            if not handle.closed:
                handle.close()


def _job_relative_input_path(job_dir: Path, relative_path: Any, *, required: bool = True) -> Path | None:
    raw = str(relative_path or "").strip()
    if not raw:
        if required:
            raise RuntimeError("Recognition job is missing an uploaded drawing.")
        return None
    path = (job_dir / raw).resolve()
    try:
        path.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise RuntimeError("Recognition job input path is invalid.") from exc
    if not path.is_file():
        if required:
            raise RuntimeError("Recognition job upload is no longer available.")
        return None
    return path


def _report_recognition_progress(
    callback: Callable[[str, int], None] | None,
    stage: str,
    progress: int,
) -> None:
    if callback is not None:
        callback(stage, progress)


def _text_or_none(value: Any) -> str | None:
    text_value = str(value or "").strip()
    return text_value or None


async def _run_standardization_stage(
    review: dict[str, Any],
    warnings: list[str],
    *,
    use_llm_standardization: bool = False,
    job_dir: Path | None = None,
) -> dict[str, Any] | None:
    apply_standardization_to_review(review)
    llm_standardization_payload: dict[str, Any] | None = None
    if not use_llm_standardization:
        return llm_standardization_payload

    if _should_run_llm_standardization(review):
        try:
            llm_standardization_payload = await run_in_threadpool(
                LLMStandardizationEngine().standardize_review,
                review,
            )
            if llm_standardization_payload.get("standardization_results"):
                _merge_llm_standardization(review, llm_standardization_payload)
                if job_dir is not None:
                    write_json(job_dir / "llm_standardization_raw.json", llm_standardization_payload)
            else:
                warnings.append(
                    "LLM standardization skipped: "
                    f"{llm_standardization_payload.get('message') or llm_standardization_payload.get('reason') or 'no result'}"
                )
        except Exception as exc:
            warnings.append(f"LLM standardization failed: {type(exc).__name__}: {exc}")
    else:
        llm_standardization_payload = {
            "status": "skipped",
            "reason": "deterministic_results_available_or_no_standard",
            "message": "当前已有本地规则标准化结果，或未选择标准，未调用 LLM/RAG 标准化。",
        }
    return llm_standardization_payload


async def _prepare_standardization_chat_context(review: dict[str, Any], message: str) -> dict[str, Any]:
    context = standardization_chat_context_needs_refresh(review, message)
    if not context["required"]:
        return {**context, "status": "current", "warnings": []}

    warnings: list[str] = []
    await _run_standardization_stage(
        review,
        warnings,
        use_llm_standardization=False,
    )
    review["derived_parameters_stale"] = False
    review["standardization_apply_history"] = []
    return {
        **context,
        "status": "refreshed",
        "warnings": warnings,
        "selected_standard": (review.get("standard_selection") or {}).get("selected_standard"),
        "result_count": len(review.get("standardization_results") or []),
    }


def _attach_standardization_chat_context(result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    result["standardization_context"] = context
    turn = result.get("turn")
    if isinstance(turn, dict):
        turn["standardization_context"] = context
    return result


def _llm_standardization_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        "status": payload.get("status"),
        "model": payload.get("model"),
        "duration_ms": payload.get("duration_ms"),
        "result_count": len(payload.get("standardization_results") or []),
        "retrieved_chunk_count": len(payload.get("retrieved_chunks") or []),
        "reason": payload.get("reason"),
        "message": payload.get("message"),
    }


async def _save_upload(upload: UploadFile, path: Path) -> None:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"Uploaded file is empty: {upload.filename}")
    path.write_bytes(data)


def _make_preview_images(drawing_path: Path, page_dir: Path, warnings: list[str]) -> list[str]:
    suffix = drawing_path.suffix.lower()
    if suffix == ".pdf":
        try:
            return render_pdf_with_pdftoppm(drawing_path, page_dir, prefix="page", dpi=200)
        except Exception as exc:
            warnings.append(f"PDF preview rendering failed: {exc}")
            return []
    if suffix in IMAGE_EXTENSIONS:
        target = page_dir / f"source{suffix}"
        shutil.copyfile(drawing_path, target)
        return [str(target)]
    warnings.append(f"No preview renderer for file type: {suffix}")
    return []


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ".-_() " else "_" for ch in name)
    return cleaned.strip(" .") or "upload.bin"


def _candidate_list_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("candidates", [])
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Candidate JSON must be a list or contain candidates.")
    return payload


def _needs_dimension_grounding_ocr(
    candidates: list[dict[str, Any]],
    file_info: dict[str, Any],
    candidate_sources: list[str],
) -> bool:
    """Run local coordinate OCR only when Qwen leaves core dimensions ungrounded."""
    if file_info.get("kind") not in {"pdf", "image"}:
        return False
    if any("ocr" in str(source).lower() for source in candidate_sources):
        return False

    qwen_candidates = [
        candidate
        for candidate in candidates
        if "qwen" in str(candidate.get("source") or "").lower()
    ]
    if not qwen_candidates or not _looks_like_compression_drawing(qwen_candidates):
        return False

    outer_candidates = [item for item in qwen_candidates if item.get("field") == "outer_diameter"]
    free_candidates = [item for item in qwen_candidates if item.get("field") == "free_length"]
    if not outer_candidates or not free_candidates:
        return True
    if not any(_has_outer_dimension_anchor(item) for item in outer_candidates):
        return True
    if not any(_has_free_length_anchor(item) for item in free_candidates):
        return True

    outer_values = {str(item.get("value")) for item in outer_candidates if item.get("value") not in (None, "")}
    free_values = {str(item.get("value")) for item in free_candidates if item.get("value") not in (None, "")}
    return bool(outer_values and outer_values == free_values)


def _looks_like_compression_drawing(candidates: list[dict[str, Any]]) -> bool:
    text = " ".join(
        str(candidate.get(key) or "")
        for candidate in candidates
        for key in ("field", "value", "evidence", "suggested_region")
    )
    return (
        any(candidate.get("field") == "load_point" for candidate in candidates)
        or bool(re.search(r"(compression\s+spring|压缩弹簧|压簧|圆柱螺旋)", text, re.IGNORECASE))
    )


def _has_outer_dimension_anchor(candidate: dict[str, Any]) -> bool:
    if candidate.get("tolerance_upper") == 0 and candidate.get("tolerance_lower") not in (None, ""):
        return True
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("evidence", "suggested_region")
    )
    if re.search(r"(roughness|\b(?:ra|rz)\s*\d|粗糙度|表面粗糙|小三角|[▽▼⌕])", text, re.IGNORECASE):
        return False
    return bool(re.search(r"(outer\s*diameter|outer\s*dia|外径|直径|\bOD\b|[ΦØ]|0\s*/\s*-?0\.\d+)", text, re.IGNORECASE))


def _has_free_length_anchor(candidate: dict[str, Any]) -> bool:
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("evidence", "suggested_region")
    )
    return bool(re.search(r"(free\s*length|自由长度|自由长|轴向|两端|兩端|\bL0\b|\bLf\b)", text, re.IGNORECASE))


def _needs_ocr_fallback(
    candidates: list[dict[str, Any]],
    file_info: dict[str, Any],
    candidate_sources: list[str],
) -> bool:
    if not file_info.get("is_scanned_like"):
        return False
    if any(candidate.get("feature_type") != "dimension_evidence" for candidate in candidates):
        return False
    return not any("rapidocr" in str(source).lower() for source in candidate_sources)


def _should_run_llm_standardization(review: dict[str, Any]) -> bool:
    selection = review.get("standard_selection") or {}
    if not selection.get("selected_standard"):
        return False
    deterministic_results = [
        item
        for item in review.get("standardization_results", []) or []
        if str(item.get("metadata", {}).get("source") or "") != "llm_standardization"
    ]
    return selection.get("status") == "rules_pending" or not deterministic_results


def _merge_llm_standardization(review: dict[str, Any], payload: dict[str, Any]) -> None:
    results = payload.get("standardization_results") or []
    if not results:
        return
    review.setdefault("standardization_results", [])
    review["standardization_results"].extend(results)
    review.setdefault("llm_standardization_diagnostics", [])
    review["llm_standardization_diagnostics"].extend(payload.get("diagnostics") or [])
    review["llm_standardization"] = {
        "status": payload.get("status"),
        "model": payload.get("model"),
        "duration_ms": payload.get("duration_ms"),
        "retrieved_chunk_count": len(payload.get("retrieved_chunks") or []),
    }
    review["human_review_required"] = True
    review["erp_ready"] = False
    review["erp_block_reason"] = review.get("erp_block_reason") or "LLM/RAG 标准化建议需要人工确认。"
    review.setdefault("drawing_summary", {})
    review["drawing_summary"]["overall_status"] = "need_review"
    review["drawing_summary"]["summary"] = "已生成 LLM/RAG 标准化建议，需要人工确认后再导出。"


def _werk24_license_status() -> dict[str, str]:
    try:
        from werk24.utils.license import find_license

        find_license()
        return {"status": "found"}
    except ModuleNotFoundError:
        return {"status": "sdk_missing"}
    except Exception as exc:
        return {"status": "not_found", "detail": f"{type(exc).__name__}: {exc}"}


def _artifact_url(job_id: str, relative: Path) -> str:
    return "/api/reviews/" + quote(job_id, safe="") + "/artifacts/" + quote(relative.as_posix(), safe="/")


def _review_preview_url(job_id: str) -> str | None:
    job_dir = _job_dir(job_id)
    page_dir = job_dir / "pages"
    if not page_dir.exists():
        return None
    supported_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
    candidates = sorted(
        (
            path
            for path in page_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in supported_suffixes
        ),
        key=lambda path: path.as_posix(),
    )
    if not candidates:
        return None
    return _artifact_url(job_id, candidates[0].relative_to(job_dir))


def _list_local_reviews(*, limit: int, owner_user_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for review_path in API_RUN_ROOT.glob("*/review.json"):
        try:
            review = read_json(review_path)
        except (OSError, ValueError):
            continue
        if not isinstance(review, dict):
            continue
        job_id = review_path.parent.name
        if not _local_job_owned(review_path.parent, owner_user_id):
            continue
        summary = review.get("drawing_summary") if isinstance(review.get("drawing_summary"), dict) else {}
        modified_at = datetime.fromtimestamp(review_path.stat().st_mtime, UTC).isoformat()
        items.append(
            {
                "job_id": job_id,
                "drawing_no": summary.get("drawing_no"),
                "drawing_name": summary.get("drawing_name"),
                "spring_type": summary.get("spring_type"),
                "overall_status": summary.get("overall_status"),
                "revision": None,
                "created_at": modified_at,
                "updated_at": modified_at,
                "image_url": _review_preview_url(job_id),
            }
        )
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return items[:limit]


def _local_job_owned(job_dir: Path, owner_user_id: str) -> bool:
    owner_path = job_dir / "owner.json"
    if not owner_path.exists():
        return False
    try:
        owner = read_json(owner_path)
    except (OSError, ValueError):
        return False
    return isinstance(owner, dict) and str(owner.get("user_id") or "").strip() == owner_user_id


def _job_dir(job_id: str) -> Path:
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid job id.")
    job_dir = (API_RUN_ROOT / job_id).resolve()
    if not str(job_dir).lower().startswith(str(API_RUN_ROOT.resolve()).lower()):
        raise HTTPException(status_code=400, detail="Invalid job path.")
    return job_dir


def _load_generation_review(job_id: str, identity: IdentityContext) -> tuple[dict[str, Any], int | None]:
    review_path = _job_dir(job_id) / "review.json"
    review, revision = _load_persisted_review(job_id, review_path, identity)
    return review, revision


def _require_service_key(
    credentials: HTTPAuthorizationCredentials | None,
    env_name: str,
    label: str,
) -> None:
    expected = str(os.getenv(env_name) or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail=f"{label} API key is not configured.")
    worker_key = str(os.getenv("GENERATION_WORKER_API_KEY") or "").strip()
    admin_key = str(os.getenv("GENERATION_ADMIN_API_KEY") or "").strip()
    if worker_key and admin_key and secrets.compare_digest(worker_key, admin_key):
        raise HTTPException(status_code=503, detail="Generation worker and administrator API keys must be different.")
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail=f"Invalid {label.lower()} API key.")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "true" if default else "false") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _require_generation_database() -> None:
    if not _generation_database_available():
        raise HTTPException(
            status_code=503,
            detail={"code": "generation_queue_not_configured", "message": "Generation queues require PostgreSQL."},
        )


def _generation_database_available() -> bool:
    engine = getattr(REVIEW_PERSISTENCE, "_engine", None)
    dialect_name = str(getattr(getattr(engine, "dialect", None), "name", "") or "")
    sqlite_test_mode = dialect_name == "sqlite" and _env_flag("AI_REVIEW_ALLOW_SQLITE_GENERATION_TESTS", False)
    return bool(REVIEW_PERSISTENCE.configured and (dialect_name == "postgresql" or sqlite_test_mode))


def _generation_lease_seconds() -> int:
    try:
        return min(max(int(os.getenv("GENERATION_JOB_LEASE_SECONDS", "300")), 30), 3600)
    except (TypeError, ValueError):
        return 300


def _generation_max_artifact_bytes() -> int:
    try:
        megabytes = min(max(int(os.getenv("GENERATION_MAX_ARTIFACT_MB", "50")), 1), 1024)
    except (TypeError, ValueError):
        megabytes = 50
    return megabytes * 1024 * 1024


def _generation_artifact_path(relative_path: str) -> Path:
    root = (API_RUN_ROOT / "_generation_artifacts").resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid generation artifact path.") from exc
    return path


def _create_generation_pdf_preview(
    store: GenerationStore,
    *,
    generation_id: str,
    worker_id: str,
    pdf_artifact: dict[str, Any],
    pdf_path: Path,
) -> dict[str, Any] | None:
    job = store.get_job(generation_id, owner_user_id=None)
    if job is not None and any(item.get("artifact_type") == "png" for item in job.get("artifacts") or []):
        return None

    source_artifact_id = str(pdf_artifact["artifact_id"])
    preview_id = uuid.uuid4().hex[:16]
    render_dir = pdf_path.parent / f".{source_artifact_id}_preview"
    try:
        rendered = render_pdf_with_pdftoppm(
            pdf_path,
            render_dir,
            prefix="preview",
            dpi=160,
            first_page_only=True,
        )
        if not rendered:
            raise RuntimeError("PDF renderer did not produce a preview image.")
        content = Path(rendered[0]).read_bytes()
        if not content:
            raise RuntimeError("Generated PDF preview is empty.")
        if len(content) > _generation_max_artifact_bytes():
            raise RuntimeError("Generated PDF preview exceeds GENERATION_MAX_ARTIFACT_MB.")
        source_stem = Path(str(pdf_artifact.get("filename") or "drawing.pdf")).stem
        filename = _safe_filename(f"{source_stem}_preview.png")[:240]
        relative = Path(generation_id) / f"{preview_id}_{filename}"
        target = _generation_artifact_path(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        try:
            preview = store.add_artifact(
                {
                    "artifact_id": preview_id,
                    "generation_id": generation_id,
                    "artifact_type": "png",
                    "filename": filename,
                    "relative_path": relative.as_posix(),
                    "mime_type": "image/png",
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "is_mock": bool(pdf_artifact.get("is_mock")),
                },
                worker_id=worker_id,
                event_source="system",
                event_payload={"generated_from_artifact_id": source_artifact_id},
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if preview is None:
            target.unlink(missing_ok=True)
            raise RuntimeError("Worker lease changed while the PDF preview was being registered.")
        return preview
    finally:
        if render_dir.exists():
            shutil.rmtree(render_dir, ignore_errors=True)


def _generation_artifact_response(artifact: dict[str, Any]) -> dict[str, Any]:
    result = dict(artifact)
    result.pop("relative_path", None)
    result["url"] = (
        f"/api/generation-jobs/{quote(str(artifact['generation_id']), safe='')}"
        f"/artifacts/{quote(str(artifact['artifact_id']), safe='')}"
    )
    return result


def _generation_job_response(job: dict[str, Any]) -> dict[str, Any]:
    result = dict(job)
    result.pop("parameter_package", None)
    result["artifacts"] = [_generation_artifact_response(item) for item in job.get("artifacts") or []]
    result["is_stale"] = False
    if REVIEW_PERSISTENCE.configured:
        try:
            stored = REVIEW_PERSISTENCE.get_review(str(job.get("review_id") or ""), owner_user_id=None)
            if stored is not None:
                result["is_stale"] = int(stored.get("revision") or 0) != int(job.get("review_revision") or 0)
        except PersistenceError:
            pass
    return result


def _update_generation_worker_job(
    generation_id: str,
    worker_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
) -> dict[str, Any]:
    try:
        job = GenerationStore(REVIEW_PERSISTENCE).update_worker_job(
            generation_id,
            worker_id=worker_id,
            status=status,
            stage=stage,
            progress=progress,
            lease_seconds=_generation_lease_seconds(),
        )
    except PersistenceError as exc:
        raise _generation_http_error(exc) from exc
    if job is None:
        raise HTTPException(status_code=409, detail={"code": "worker_lease_or_state_conflict"})
    return _generation_job_response(job)


def _generation_http_error(exc: PersistenceError) -> HTTPException:
    message = str(exc)
    if "PostgreSQL is required" in message:
        return HTTPException(status_code=503, detail={"code": "generation_queue_not_configured", "message": message})
    if "not found" in message.lower():
        return HTTPException(status_code=404, detail={"code": "generation_resource_not_found", "message": message})
    return HTTPException(status_code=409, detail={"code": "generation_conflict", "message": message})
