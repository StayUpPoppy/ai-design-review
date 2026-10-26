"""Bounded, cached local OCR in the displayed page coordinate system."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def _drawing_regions(image: Image.Image) -> list[tuple[float, float, float, float]]:
    """Find connected drawing content, excluding borders and title-block grids."""
    import cv2
    import numpy as np

    thumb = image.copy()
    thumb.thumbnail((1500, 1500))
    gray = np.array(thumb.convert("L"))
    mask = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    height, width = gray.shape
    regions = []
    for x, y, w, h, ink in stats[1:count]:
        box = (x / width, y / height, (x + w) / width, (y + h) / height)
        if .06 < w / width < .85 and .035 < h / height < .55 and y / height < .7 and ink > width * height * .0008:
            if min(box[0], box[1]) < .008 or max(box[2], box[3]) > .992:
                continue
            regions.append((ink * (1 - box[1]), box))
    regions.sort(key=lambda item: (-item[0], item[1]))
    return [(max(0, b[0] - .025), max(0, b[1] - .025), min(1, b[2] + .025), min(1, b[3] + .025)) for _, b in regions[:2]]


def crop_regions(image: Image.Image, blocks: list[dict[str, Any]], missing: list[dict[str, Any]], page: int) -> list[tuple[float, float, float, float, int]]:
    from .drawing_annotations import _identity

    content = _drawing_regions(image)
    proposals: list[tuple[float, float, float, float]] = []
    # A connected view gives vertical symbols a crop even when every dimension
    # on that view is still unlocated. No dependency on two successful anchors.
    if content:
        proposals.append(content[0])
    vertical = []
    labels = []
    for block in blocks:
        if block["page"] != page:
            continue
        b = block["position"]
        if b["height"] > b["width"] * 1.05 and re.search(r"\d|[φΦϕøØ⌀]", block["text"]):
            if not content or any(c[0] <= b["x"] <= c[2] and c[1] <= b["y"] <= c[3] for c in content):
                vertical.append((max(0, b["x"] - .035), max(0, b["y"] - .04), min(1, b["x"] + b["width"] + .035), min(1, b["y"] + b["height"] + .04)))
        if any(_identity(a["field"], block["text"]) for a in missing):
            labels.append((max(0, b["x"] - .01), max(0, b["y"] - .015), min(1, b["x"] + b["width"] + .23), min(1, b["y"] + b["height"] + .015)))
    # Prefer large vertical runs; single-glyph PDF fragments are handled by the
    # whole view, leaving budget for a genuinely unread vertical symbol.
    vertical.sort(key=lambda r: (-(r[3] - r[1]), r[0], r[1]))
    proposals.extend(vertical)
    proposals.extend(labels)
    proposals.extend(content[1:])
    if not proposals:
        # Content-relative fallback when there are no readable labels or views.
        proposals = [(0, 0, .55, .55), (.45, 0, 1, .55), (0, .45, .55, 1), (.45, .45, 1, 1)]
    unique = []
    for r in proposals:
        if not any(sum(abs(a - b) for a, b in zip(r, old)) < .045 for old in unique):
            unique.append(r)
    return [(*region, angle) for region in unique[:4] for angle in (0, 90, 270)]


def local_ocr_blocks(job_dir: Path, pages: list[dict[str, Any]], document_id: str,
                     review: dict[str, Any], candidates: list[dict[str, Any]], existing: list[dict[str, Any]],
                     *, retry: bool = False, verification_requests: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    from .drawing_annotations import annotation_file_lock
    with annotation_file_lock(job_dir, "annotation_ocr.lock"):
        return _local_ocr_blocks_locked(job_dir, pages, document_id, review, candidates, existing,
                                        retry=retry, verification_requests=verification_requests or [])


def _local_ocr_blocks_locked(job_dir, pages, document_id, review, candidates, existing, *, retry, verification_requests):
    from .drawing_annotations import ALGORITHM_VERSION, _unique_blocks, atomic_annotation_write, locate_fields, ocr_blocks, page_sort_key
    from .engines.ocr_providers import RapidOcrProvider
    from .multi_spec import location_policy, location_regions
    policy = location_policy(review)

    path = job_dir / "annotation_ocr_v3.json"
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if cache.get("source_document_id") != document_id or cache.get("algorithm_version") != ALGORITHM_VERSION or cache.get("cache_format") != 4:
        cache = {"source_document_id": document_id, "algorithm_version": ALGORITHM_VERSION, "cache_format": 4, "blocks": [], "full": {}, "regions": {}, "handled_fields": {}, "warnings": []}
    cache.setdefault("handled_fields", {})
    cache.setdefault("errors", {})
    protected = {a["field"] for a in (review.get("drawing_annotations") or {}).get("annotations", []) if a.get("locations") and
                 (not policy or any(l.get("source") not in {"ocr", "pdf_text", "candidate", "local_ocr"} for l in a["locations"]))} if retry else set()
    protected.discard("surface_roughness_ra")
    def missing_requests(blocks):
        from .surface_roughness import grounded_roughness_evidence
        ordinary = [a for a in locate_fields(review, candidates, blocks)
                    if a["status"] == "unlocated" and a["original_value"] is not None and a["field"] not in protected]
        for request in verification_requests:
            claim = request.get("roughness_claim") or {"value": request["original_value"], "page": request["page"]}
            if not grounded_roughness_evidence(claim, blocks, dimension_candidates=candidates)[0]:
                ordinary.append(request)
        return ordinary
    unresolved = missing_requests(_unique_blocks(existing + cache["blocks"]))
    if not unresolved:
        return cache["blocks"], [], {field: "located" for field in protected}
    requested_pages = {number for a in unresolved for number in a.get("evidence_pages", [1])}
    folder = job_dir / "annotation_ocr_pages"
    folder.mkdir(exist_ok=True)
    sources = {page_sort_key(p)[0]: p for p in sorted((job_dir / "pages").glob("*"), key=page_sort_key) if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}}
    prepared = {}

    def canonical(number):
        if number not in prepared:
            target = folder / f"page-{number}.png"
            with Image.open(sources[number]) as image:
                ImageOps.exif_transpose(image).convert("RGB").save(target)
            prepared[number] = target
        return prepared[number]

    for page in pages:
        number = page["page"]
        if number not in requested_pages:
            continue
        key = str(number)
        state = cache["full"].get(key)
        if any(b["page"] == number and b["source"] == "ocr" for b in existing) or state and not (retry and state == "failed"):
            continue
        try:
            raw = RapidOcrProvider().recognize([canonical(number)], {})
            raw[0]["page"] = number
            for block in ocr_blocks({"local": {"raw_pages": raw}}, pages):
                block["source"] = "local_ocr"
                cache["blocks"].append(block)
            cache["full"][key] = "completed"
        except Exception as exc:
            cache["full"][key] = "failed"
            cache["errors"][f"full:{key}"] = f"{type(exc).__name__}: {exc}"

    combined = _unique_blocks(existing + cache["blocks"])
    annotations = missing_requests(combined)
    states = {}
    for page in pages:
        number = page["page"]
        missing = [a for a in annotations if a["status"] == "unlocated" and a["original_value"] is not None and number in a.get("evidence_pages", [number]) and a["field"] not in protected]
        if not missing:
            continue
        fields = sorted(a["field"] for a in missing)
        for field in fields:
            states[field] = "not_run"
        request_keys = sorted({(policy["version"] + ":" + policy["fingerprint"] + ":" if policy else "") + a.get("request_key", a["field"]) for a in missing})
        if not retry and set(request_keys) <= set(cache["handled_fields"].get(str(number), [])):
            for field in fields:
                states[field] = cache.get("field_states", {}).get(field, "completed_unmatched")
            continue
        try:
            with Image.open(canonical(number)) as image:
                width, height = image.size
                regions = crop_regions(image, combined, missing, number)
                hints = [a.get("position") for a in missing if a.get("position")]
                hinted = []
                for b in hints:
                    if b.get("coordinate_type") == "normalized":
                        hinted.extend((max(0, b["x"] - .025), max(0, b["y"] - .025), min(1, b["x"] + b["width"] + .025), min(1, b["y"] + b["height"] + .025), angle) for angle in (0, 90, 270))
                regions = list(dict.fromkeys([*hinted, *regions]))
                if policy:
                    allowed = [r for field in fields for group in location_regions(review, field) for r in group if r.get("page", 1) == number]
                    clipped = [(max(x0, r["x"]), max(y0, r["y"]), min(x1, r["x"]+r["width"]), min(y1, r["y"]+r["height"]), angle)
                               for x0, y0, x1, y1, angle in regions for r in allowed]
                    scoped = [(*bounds, angle) for r in allowed for bounds in [(r["x"], r["y"], r["x"]+r["width"], r["y"]+r["height"])] for angle in (0, 90, 270)]
                    regions = list(dict.fromkeys(scoped + [r for r in clipped if r[2] > r[0] and r[3] > r[1]]))
                inputs, transforms, records = [], [], []
                for x0, y0, x1, y1, angle in regions:
                    if len(inputs) >= 12:
                        break
                    bounds = (int(x0 * width), int(y0 * height), min(width, math.ceil(x1 * width)), min(height, math.ceil(y1 * height)))
                    signature = hashlib.sha256(json.dumps([number, bounds, angle]).encode()).hexdigest()[:16]
                    record = cache["regions"].get(signature)
                    if record and (not retry or record["status"] == "completed"):
                        for field in fields:
                            states[field] = "failed" if record["status"] == "failed" else "completed_unmatched"
                        continue
                    # The cap is per invocation/page, not a lifetime cache cap.
                    crop = image.crop(bounds)
                    crop = crop.resize((crop.width * 2, crop.height * 2)).rotate(angle, expand=True)
                    target = folder / f"crop-{signature}.png"
                    crop.save(target)
                    inputs.append(target)
                    transforms.append((bounds, angle, signature))
                    records.append({"page": number, "bounds": list(bounds), "angle": angle, "fields": fields, "status": "failed"})
                if inputs:
                    # A real request is recorded; an empty proposal list never
                    # becomes a completed page. Failures retain their signature.
                    for (_, _, signature), record in zip(transforms, records):
                        cache["regions"][signature] = record
                    cache["handled_fields"][str(number)] = sorted(set(cache["handled_fields"].get(str(number), []) + request_keys))
                    raw_pages = RapidOcrProvider().recognize(inputs, {})
                    for raw, (bounds, angle, signature) in zip(raw_pages, transforms):
                        cache["regions"][signature]["status"] = "completed"
                        for block in ocr_blocks({"local": {"raw_pages": [raw]}}, [{"page": raw["page"]}]):
                            box = block["position"]
                            points = []
                            for u, v in ((box["x"], box["y"]), (box["x"] + box["width"], box["y"]), (box["x"], box["y"] + box["height"]), (box["x"] + box["width"], box["y"] + box["height"])):
                                if angle == 90:
                                    u, v = 1 - v, u
                                elif angle == 270:
                                    u, v = v, 1 - u
                                points.append(((bounds[0] + u * (bounds[2] - bounds[0])) / width, (bounds[1] + v * (bounds[3] - bounds[1])) / height))
                            xs, ys = zip(*points)
                            position = {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
                            cache["blocks"].append({"page": number, "text": block["text"], "position": position, "source": "local_ocr", "reading_angle": angle, "region_id": signature})
                    for field in fields:
                        states[field] = "failed" if any(cache["regions"][signature]["status"] == "failed" for _, _, signature in transforms) else "completed_unmatched"
        except Exception as exc:
            cache["errors"][f"regions:{number}"] = f"{type(exc).__name__}: {exc}"
            for field in fields:
                states[field] = "failed"
    combined = _unique_blocks(existing + cache["blocks"])
    for a in locate_fields(review, candidates, combined):
        if a["locations"]:
            states[a["field"]] = "located"
    warnings = []
    if "failed" in states.values() or "failed" in cache["full"].values():
        warnings.append("部分本地OCR补定位失败，可点击重新补定位重试；原参数和人工位置保留。")
    cache["warnings"] = warnings
    cache["field_states"] = states
    atomic_annotation_write(path, cache)
    return cache["blocks"], warnings, states
