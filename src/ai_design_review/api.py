from __future__ import annotations

import shutil
import uuid
import os
import re
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
from .io_utils import project_path, read_json, write_json
from .llm_standardization_engine import LLMStandardizationEngine, llm_standardization_runtime_status
from .preprocessing import IMAGE_EXTENSIONS, probe_file, render_pdf_with_pdftoppm
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_RUN_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_ROOT)), name="outputs")
if TMP_PDF_ROOT.exists():
    app.mount("/tmp_pdf_pages", StaticFiles(directory=str(TMP_PDF_ROOT)), name="tmp_pdf_pages")
app.mount("/artifacts", StaticFiles(directory=str(API_RUN_ROOT)), name="artifacts")


@app.on_event("startup")
def refresh_ragflow_startup_status() -> None:
    global RAGFLOW_STARTUP_STATUS
    RAGFLOW_STARTUP_STATUS = ragflow_runtime_status(check_health=True)


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
        "ocr_runtime": ocr_runtime_status(),
        "geometry_runtime": {"status": "ready", "engine": "geometry"},
        "vlm_runtime": {"status": "not_configured", "mode": "optional_review_only"},
        "paddleocr_runtime": {"status": "deprecated", "replacement": "ocr_runtime"},
    }


@app.get("/api/standard-knowledge/search")
def search_standard_knowledge(
    standard_no: str | None = None,
    spring_type: str | None = "compression_spring",
    target_fields: str | None = None,
    query: str | None = None,
    limit: int = 6,
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
        "review": review,
    }


@app.post("/api/reviews/standardize")
async def standardize_review_payload(payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
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
def assess_review_reasonableness(payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
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
) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    body = payload or {}
    review = body.get("review")
    if not isinstance(review, dict):
        if not review_path.exists():
            raise HTTPException(status_code=404, detail="Review not found.")
        review = read_json(review_path)

    warnings: list[str] = []
    llm_standardization_payload = await _run_standardization_stage(
        review,
        warnings,
        use_llm_standardization=bool(body.get("use_llm_standardization")),
        job_dir=job_dir,
    )
    write_json(review_path, review)
    if warnings:
        write_json(job_dir / "standardization_warnings.json", {"warnings": warnings})

    return {
        "job_id": job_id,
        "llm_standardization_url": _artifact_url(job_id, Path("llm_standardization_raw.json"))
        if llm_standardization_payload and llm_standardization_payload.get("standardization_results")
        else None,
        "warnings": warnings,
        "llm_standardization": _llm_standardization_summary(llm_standardization_payload),
        "review": review,
    }


@app.post("/api/reviews/standardization-chat")
async def standardization_chat_payload(payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
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
) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    body = payload or {}
    review = body.get("review")
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="standardization chat requires a message.")
    if not isinstance(review, dict):
        if not review_path.exists():
            raise HTTPException(status_code=404, detail="Review not found.")
        review = read_json(review_path)
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
    write_json(review_path, result["review"])
    write_json(job_dir / "standardization_chat.json", {"turns": result["review"].get("standardization_chat", [])})
    return {
        "job_id": job_id,
        **result,
    }


@app.get("/api/reviews/{job_id}")
def get_review(job_id: str) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    if not review_path.exists():
        raise HTTPException(status_code=404, detail="Review not found.")
    return read_json(review_path)


@app.get("/api/reviews/{job_id}/candidates")
def get_candidates(job_id: str) -> dict[str, Any]:
    job_dir = _job_dir(job_id)
    candidates_path = job_dir / "candidates.json"
    if not candidates_path.exists():
        raise HTTPException(status_code=404, detail="Candidates not found.")
    return read_json(candidates_path)


@app.get("/api/reviews/{job_id}/download")
def download_review(job_id: str) -> FileResponse:
    job_dir = _job_dir(job_id)
    review_path = job_dir / "review.json"
    if not review_path.exists():
        raise HTTPException(status_code=404, detail="Review not found.")
    return FileResponse(str(review_path), filename=f"{job_id}_review.json")


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
    return "/artifacts/" + job_id + "/" + relative.as_posix()


def _job_dir(job_id: str) -> Path:
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid job id.")
    job_dir = (API_RUN_ROOT / job_id).resolve()
    if not str(job_dir).lower().startswith(str(API_RUN_ROOT.resolve()).lower()):
        raise HTTPException(status_code=400, detail="Invalid job path.")
    return job_dir
