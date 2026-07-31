from __future__ import annotations

import shutil
import uuid
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
from .llm_standardization_engine import LLMStandardizationEngine, llm_standardization_runtime_status
from .preprocessing import IMAGE_EXTENSIONS, probe_file, render_pdf_with_pdftoppm
from .review_persistence import PersistenceError, ReviewAccessError, ReviewPersistence, RevisionConflictError
from .standard_knowledge import ragflow_runtime_status, retrieve_standard_chunks
from .standardization_chat_agent import chat_about_standardization, standardization_chat_context_needs_refresh
from .standardization_chat_llm import standardization_chat_llm_runtime_status
from .spring_feasibility import assess_parameter_reasonableness
from .workflow import DrawingReviewWorkflow, apply_standardization_to_review


PROJECT_ROOT = project_path()
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
API_RUN_ROOT = OUTPUT_ROOT / "api_runs"
TMP_PDF_ROOT = PROJECT_ROOT / "tmp_pdf_pages"
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

app = FastAPI(title="AI Spring Drawing Review API", version="0.1.0")
RAGFLOW_STARTUP_STATUS = ragflow_runtime_status()
REVIEW_PERSISTENCE = ReviewPersistence()
DATABASE_STARTUP_STATUS = REVIEW_PERSISTENCE.health()
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_RUN_ROOT.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def refresh_runtime_startup_status() -> None:
    global RAGFLOW_STARTUP_STATUS, DATABASE_STARTUP_STATUS
    RAGFLOW_STARTUP_STATUS = ragflow_runtime_status(check_health=True)
    DATABASE_STARTUP_STATUS = REVIEW_PERSISTENCE.health(check_connection=True)


@app.on_event("shutdown")
def close_runtime_resources() -> None:
    REVIEW_PERSISTENCE.dispose()


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ai-design-review-api",
        "health": "/api/health",
        "docs": "/docs",
    }


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


@app.get("/api/session")
def get_session(identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    return {"identity": identity.as_public_dict()}


@app.get("/api/samples/mixed-review")
def get_mixed_review_sample(identity: IdentityContext = Depends(require_identity)) -> FileResponse:
    sample_path = OUTPUT_ROOT / "mixed_review.json"
    if not sample_path.is_file():
        raise HTTPException(status_code=404, detail="Sample review not found.")
    return FileResponse(str(sample_path), media_type="application/json")


@app.get("/api/samples/spring-preview")
def get_spring_preview_sample(identity: IdentityContext = Depends(require_identity)) -> FileResponse:
    sample_path = TMP_PDF_ROOT / "spring_example_rotated.png"
    if not sample_path.is_file():
        raise HTTPException(status_code=404, detail="Sample preview not found.")
    return FileResponse(str(sample_path))


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


@app.post("/api/reviews")
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
) -> dict[str, Any]:
    if use_werk24 and not confirm_upload_to_werk24:
        raise HTTPException(
            status_code=400,
            detail="Werk24 upload requires confirm_upload_to_werk24=true.",
        )

    job_id = uuid.uuid4().hex[:12]
    job_dir = API_RUN_ROOT / job_id
    input_dir = job_dir / "inputs"
    page_dir = job_dir / "pages"
    input_dir.mkdir(parents=True, exist_ok=True)
    page_dir.mkdir(parents=True, exist_ok=True)

    drawing_path = input_dir / _safe_filename(drawing.filename or "drawing")
    await _save_upload(drawing, drawing_path)

    warnings: list[str] = []
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
        try:
            werk24_payload = await run_in_threadpool(Werk24Engine().extract_with_raw, drawing_path)
            candidates.extend(werk24_payload.get("candidates", []))
            raw_payloads["werk24"] = werk24_payload
            candidate_sources.append("werk24")
        except Exception as exc:
            warnings.append(f"Werk24 extraction failed: {exc}")

    if use_qwen:
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

    rules = read_json(project_path("config", "factory_rules.json"))
    review = DrawingReviewWorkflow(rules).run(str(drawing_path), candidates, run_standardization=False)
    llm_standardization_payload: dict[str, Any] | None = None
    if use_llm_standardization:
        warnings.append("LLM/RAG 标准化已改为点击“标准化”按钮后执行，本次上传仅完成识别。")

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


@app.get("/api/reviews")
def list_reviews(limit: int = 20, identity: IdentityContext = Depends(require_identity)) -> dict[str, Any]:
    bounded_limit = min(max(limit, 1), 100)
    if REVIEW_PERSISTENCE.configured:
        try:
            reviews = REVIEW_PERSISTENCE.list_reviews(limit=bounded_limit, owner_user_id=identity.user_id)
        except PersistenceError as exc:
            raise _persistence_http_error(exc) from exc
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
        context = await _prepare_standardization_chat_context(review, message)
        result = chat_about_standardization(
            review,
            message,
            use_llm=bool(body.get("use_llm")),
            supplements=body.get("supplements"),
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
    _ensure_review_owned(job_id, review_path, identity)
    if not isinstance(review, dict):
        review, _ = _load_persisted_review(job_id, review_path, identity)
    try:
        context = await _prepare_standardization_chat_context(review, message)
        result = chat_about_standardization(
            review,
            message,
            use_llm=bool(body.get("use_llm")),
            supplements=body.get("supplements"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = _attach_standardization_chat_context(result, context)
    persistence = _save_review_persistence(
        job_id,
        result["review"],
        review_path=review_path,
        expected_revision=body.get("expected_revision"),
        identity=identity,
        events=[
            {
                "event_type": "standardization_chat_completed",
                "source": "ai_chat",
                "reason": "已完成一次标准化对话",
                "metadata": {"use_llm": bool(body.get("use_llm"))},
            }
        ],
    )
    write_json(job_dir / "standardization_chat.json", {"turns": result["review"].get("standardization_chat", [])})
    return {
        "job_id": job_id,
        "review_revision": persistence.get("revision"),
        "persistence": _persistence_response(persistence),
        **result,
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
            deleted = REVIEW_PERSISTENCE.delete_review(job_id, owner_user_id=identity.user_id)
        except PersistenceError as exc:
            raise _persistence_http_error(exc) from exc
        if not deleted:
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
        return stored["review"], stored["revision"]
    if not _local_job_owned(review_path.parent, identity.user_id) or not review_path.exists():
        raise HTTPException(status_code=404, detail="Review not found.")
    return read_json(review_path), None


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
