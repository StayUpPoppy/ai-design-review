from __future__ import annotations

import shutil
import uuid
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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
from .preprocessing import IMAGE_EXTENSIONS, probe_file, render_pdf_with_pdftoppm
from .workflow import DrawingReviewWorkflow


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
        "ocr_runtime": ocr_runtime_status(),
        "geometry_runtime": {"status": "ready", "engine": "geometry"},
        "vlm_runtime": {"status": "not_configured", "mode": "optional_review_only"},
        "paddleocr_runtime": {"status": "deprecated", "replacement": "ocr_runtime"},
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
    review = DrawingReviewWorkflow(rules).run(str(drawing_path), candidates)

    candidates_payload = {
        "job_id": job_id,
        "sources": candidate_sources,
        "candidates": candidates,
        "dimension_evidence": raw_payloads.get("geometry", {}).get("dimension_evidence", []),
        "raw_payloads": raw_payloads,
    }
    write_json(job_dir / "candidates.json", candidates_payload)
    write_json(job_dir / "review.json", review)
    write_json(job_dir / "file_info.json", probe_file(drawing_path))

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
        "geometry_url": _artifact_url(job_id, Path("geometry_evidence.json")) if "geometry" in raw_payloads else None,
        "warnings": warnings,
        "review": review,
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
