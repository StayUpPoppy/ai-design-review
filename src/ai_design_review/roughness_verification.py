"""Original-document grounding, sharing the annotation OCR cache and budget."""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .surface_roughness import (
    ROUGHNESS_VERIFICATION_VERSION, SURFACE_ROUGHNESS_FIELD, apply_roughness_verification,
    grounded_roughness_evidence, positive_surface_roughness, verify_roughness_candidates, roughness_request_key,
)
from .standardizers.calculation_state import human_override


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _recognition_inputs(item: dict[str, Any]) -> dict[str, Any]:
    # Verification metadata is output, never part of the recognition claim.
    return {k: deepcopy(item[k]) for k in ("value", "unit", "source", "evidence", "page", "position", "surface_location", "location",
                                          "location_conflict", "location_candidates", "confidence", "need_human_review", "evidence_records",
                                          "roughness_model_claim", "roughness_page_known", "recognition_position") if k in item}


def _restore_model_provenance(claims, raw_payloads, job_dir):
    """Repair legacy parent/occurrence classification from saved responses only."""
    from .engines.qwen_vision_adapter import _surface_roughness_candidates
    payloads = [p.get("parsed") for p in raw_payloads.values() if isinstance(p, dict) and isinstance(p.get("parsed"), dict)]
    saved = _read(job_dir / "qwen_vision_raw.json").get("parsed")
    if isinstance(saved, dict):
        payloads.append(saved)
    originals = [c for payload in payloads for c in _surface_roughness_candidates(payload) if c.get("roughness_model_claim")]
    for claim in claims:
        if "qwen" not in str(claim.get("source") or "").lower():
            continue
        evidence = str(claim.get("evidence") or "").strip()
        matches = [c for c in originals if positive_surface_roughness(c.get("value")) == positive_surface_roughness(claim.get("value"))
                   and evidence in {str(c.get("evidence") or "").strip(), *[str(r.get("evidence") or "").strip() for r in c.get("evidence_records", [])]}]
        if matches:
            claim["roughness_model_claim"] = True


def _view_context(job_dir, pages):
    from PIL import Image, ImageOps
    from .annotation_ocr import _drawing_regions
    from .drawing_annotations import page_sort_key
    result = []
    eligible = {p["page"] for p in pages}
    for path in sorted((job_dir / "pages").glob("*")):
        page = page_sort_key(path)[0]
        if page not in eligible or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
            continue
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            result.append({"page": page, "width": image.width, "height": image.height, "regions": _drawing_regions(image)})
    return result


def verify_job_candidates(job_dir: Path, candidates: list[dict[str, Any]], raw_payloads: dict[str, Any],
                          url_for: Callable[[Path], str], *, review: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from .drawing_annotations import annotation_file_lock
    if not any(c.get("field") == SURFACE_ROUGHNESS_FIELD for c in candidates):
        return candidates
    if not job_dir.is_dir():
        return [*filter(lambda c: c.get("field") != SURFACE_ROUGHNESS_FIELD, candidates),
                *verify_roughness_candidates([c for c in candidates if c.get("field") == SURFACE_ROUGHNESS_FIELD], [], "unavailable",
                                             failure_reason="本地原图不可用，尚未完成独立核验。")]
    with annotation_file_lock(job_dir, "roughness_verification.lock"):
        try:
            return _verify_locked(job_dir, candidates, raw_payloads, url_for, review)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return [c for c in candidates if c.get("field") != SURFACE_ROUGHNESS_FIELD] + [
                {**c, "field": SURFACE_ROUGHNESS_FIELD} for c in verify_roughness_candidates(
                    [c for c in candidates if c.get("field") == SURFACE_ROUGHNESS_FIELD], [], "unavailable",
                    failure_reason=f"原图核验不可用：{type(exc).__name__}；候选仍保留供核对。")]


def _verify_locked(job_dir, candidates, raw_payloads, url_for, review):
    from .annotation_ocr import local_ocr_blocks
    from .drawing_annotations import annotation_source, atomic_annotation_write, ocr_blocks, pdf_blocks

    claims = [_recognition_inputs(c) for c in candidates if c.get("field") == SURFACE_ROUGHNESS_FIELD]
    _restore_model_provenance(claims, raw_payloads, job_dir)
    document, source = annotation_source(job_dir, url_for)
    document_id = document["source_document_id"]
    history = (review or {}).get("drawing_annotations") or {}
    historical_locations = [{**l, "original_value": a.get("original_value")} for a in history.get("annotations", [])
                            if a.get("field") == SURFACE_ROUGHNESS_FIELD for l in a.get("locations", [])
                            if l.get("source") in {"pdf_text", "ocr", "local_ocr", "manual"}] if history.get("source_document_id") == document_id else []
    dimensions = [c for c in candidates if c.get("field") != SURFACE_ROUGHNESS_FIELD]
    limit = max(1, int(os.getenv("QWEN_MAX_PAGES", "3")))
    pages = [p for p in document["pages"] if p["page"] <= limit]
    if len(document["pages"]) > 1:
        for claim in claims:
            if claim.get("page") is None or claim.get("roughness_page_known") is False:
                claim["page"] = None
    cache_path = job_dir / "roughness_verification.json"
    from .multi_spec import shared_ocr_dir, restrict_blocks
    ocr_path = shared_ocr_dir(job_dir) / "annotation_ocr_v3.json"
    signature = hashlib.sha256(json.dumps([ROUGHNESS_VERIFICATION_VERSION, document_id, claims,
                                           raw_payloads, historical_locations, dimensions, ocr_path.stat().st_mtime_ns if ocr_path.exists() else None],
                                          sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    cache = _read(cache_path)
    if cache.get("signature") == signature:
        verified = cache["candidates"]
    else:
        blocks, errors = [], []
        if source and source.suffix.lower() == ".pdf":
            try:
                blocks.extend(pdf_blocks(source, limit))
            except Exception as exc:
                errors.append(f"PDF文字不可用：{type(exc).__name__}")
        # A model/imported candidate payload is not an OCR execution receipt,
        # even when it contains fields called raw_pages or evidence_status.
        independent_payloads = {name: payload for name, payload in raw_payloads.items()
                                if name not in {"candidate_json", "ocr_json", "sample_ocr_json", "qwen_vision", "vlm", "geometry", "werk24", "cached_werk24"}
                                and isinstance(payload, dict) and (payload.get("provider") or payload.get("engine")) == "rapidocr"}
        blocks.extend(ocr_blocks(independent_payloads, pages))
        shared = _read(ocr_path)
        if shared.get("source_document_id") == document_id and shared.get("cache_format") == 4:
            blocks.extend(shared.get("blocks", []))
        blocks = restrict_blocks(review or {}, blocks, SURFACE_ROUGHNESS_FIELD)
        requests = []
        for claim in claims:
            page = claim.get("page") or 1
            refs, method, _ = grounded_roughness_evidence(claim, blocks, dimension_candidates=dimensions, historical_locations=historical_locations)
            if not refs:
                requests.append({"field": SURFACE_ROUGHNESS_FIELD, "original_value": claim.get("value"), "page": page,
                                 "position": claim.get("position"), "status": "unlocated", "evidence_pages": [page],
                                 "roughness_claim": claim,
                                 "request_key": roughness_request_key(claim)})
        if requests and pages:
            try:
                # Null official values and a missing/conflicted bubble do not
                # suppress this request. Both consumers share actual OCR runs.
                stub = review or {"drawing_summary": {"spring_type": "compression_spring"},
                                  "spring_parameters": {c["field"]: c for c in candidates if c.get("field") != SURFACE_ROUGHNESS_FIELD}}
                from .drawing_annotations import _local_ocr_blocks
                local, warnings, states = _local_ocr_blocks(job_dir, pages, document_id, stub, candidates, blocks, verification_requests=requests)
                blocks.extend(restrict_blocks(review or {}, local, SURFACE_ROUGHNESS_FIELD))
                if states.get(SURFACE_ROUGHNESS_FIELD) == "failed":
                    errors.append("本地OCR核验失败，可使用重新补定位重试。")
                if states.get(SURFACE_ROUGHNESS_FIELD) == "budget_exhausted":
                    errors.append("本页局部OCR预算已用完，仍未取得明确粗糙度标注。")
            except Exception as exc:
                errors.append(f"本地OCR核验不可用：{type(exc).__name__}: {exc}")
        if not source or not pages:
            errors.append("本地原图或对应页不可用，尚未完成独立核验。")
        views = []
        try:
            views = _view_context(job_dir, pages)
        except Exception:
            # Region detection failure cannot invalidate a verified scalar.
            pass
        verified = verify_roughness_candidates(claims, blocks, document_id, failure_reason="；".join(errors), dimension_candidates=dimensions, historical_locations=historical_locations, view_context=views)
        # The local OCR call may have changed the shared cache. Include that
        # revision, so the next ordinary read reuses this exact result.
        signature = hashlib.sha256(json.dumps([ROUGHNESS_VERIFICATION_VERSION, document_id, claims,
                                               raw_payloads, historical_locations, dimensions, ocr_path.stat().st_mtime_ns if ocr_path.exists() else None],
                                              sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        atomic_annotation_write(cache_path, {"verification_version": ROUGHNESS_VERIFICATION_VERSION,
                                             "source_document_id": document_id, "signature": signature,
                                             "candidates": verified, "errors": errors})
    return [c for c in candidates if c.get("field") != SURFACE_ROUGHNESS_FIELD] + [
        {**c, "field": SURFACE_ROUGHNESS_FIELD} for c in verified]


def verify_review_roughness(review: dict[str, Any], job_dir: Path, url_for: Callable[[Path], str]) -> bool:
    item = (review.get("spring_parameters") or {}).get(SURFACE_ROUGHNESS_FIELD)
    if not isinstance(item, dict):
        return False
    claims = [{**c, "field": SURFACE_ROUGHNESS_FIELD, "surface_location": None if c.get("location_conflict") else c.get("location") or c.get("surface_location")}
              for c in item.get("roughness_candidates") or [] if isinstance(c, dict)]
    if not human_override(item) and positive_surface_roughness(item.get("value")) is not None and not any(positive_surface_roughness(c.get("value")) == positive_surface_roughness(item["value"]) for c in claims):
        # Human values remain protected by apply_roughness_verification, but can
        # receive a warning when no original drawing evidence is available.
        claims.append({**_recognition_inputs(item), "field": SURFACE_ROUGHNESS_FIELD})
    if not claims:
        return False
    payload = _read(job_dir / "candidates.json")
    dimensions = [c for c in payload.get("candidates", []) if c.get("field") != SURFACE_ROUGHNESS_FIELD]
    verified = [c for c in verify_job_candidates(job_dir, [*dimensions, *claims], payload.get("raw_payloads") or {}, url_for, review=review)
                if c.get("field") == SURFACE_ROUGHNESS_FIELD]
    document_id = next((c.get("source_document_id") for c in verified), "unavailable")
    return apply_roughness_verification(review, verified, document_id)
