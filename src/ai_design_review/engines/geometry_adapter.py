from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from .base import RecognitionEngine
from ..io_utils import project_path
from ..preprocessing import IMAGE_EXTENSIONS, render_pdf_with_pdftoppm


class GeometryEngine(RecognitionEngine):
    """Extract low-level drawing geometry evidence from PDF/image inputs.

    The engine intentionally does not assign dimensions to spring fields by
    itself. It produces auditable geometry evidence for downstream mapping,
    optional VLM review, and human confirmation.
    """

    name = "geometry"

    def __init__(
        self,
        work_dir: str | Path | None = None,
        dpi: int = 200,
        max_image_side: int = 2600,
    ):
        self.work_dir = Path(work_dir) if work_dir else None
        self.dpi = dpi
        self.max_image_side = max_image_side

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        return self.extract_with_raw(file_path)["candidates"]

    def extract_with_raw(
        self,
        file_path: str | Path,
        image_paths: list[str | Path] | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path)
        warnings: list[str] = []
        evidence: list[dict[str, Any]] = []
        diagnostics: dict[str, Any] = {
            "engine": self.name,
            "file_path": str(path),
            "vector_pdf": {"status": "skipped"},
            "raster_pages": [],
        }

        if path.suffix.lower() == ".pdf":
            vector_evidence, vector_diag, vector_warnings = _extract_pdf_vector_evidence(path)
            evidence.extend(vector_evidence)
            diagnostics["vector_pdf"] = vector_diag
            warnings.extend(vector_warnings)

        try:
            prepared_images = [Path(item) for item in image_paths] if image_paths else self._prepare_images(path)
        except Exception as exc:
            prepared_images = []
            warnings.append(f"Geometry raster preparation failed: {type(exc).__name__}: {exc}")

        for page_number, image_path in enumerate(prepared_images, start=1):
            page_evidence, page_diag, page_warnings = _analyze_raster_page(
                image_path,
                page_number=page_number,
                max_side=self.max_image_side,
            )
            evidence.extend(page_evidence)
            diagnostics["raster_pages"].append(page_diag)
            warnings.extend(page_warnings)

        evidence = _deduplicate_evidence(evidence)
        candidates = [_evidence_to_candidate(item, index) for index, item in enumerate(evidence, start=1)]
        diagnostics["evidence_count"] = len(evidence)
        diagnostics["candidate_count"] = len(candidates)
        return {
            "engine": self.name,
            "dimension_evidence": evidence,
            "candidates": candidates,
            "diagnostics": diagnostics,
            "warnings": warnings,
        }

    def _prepare_images(self, file_path: Path) -> list[Path]:
        suffix = file_path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            return [file_path]
        if suffix != ".pdf":
            raise RuntimeError(f"Geometry analysis only supports PDF or image input: {suffix}")

        output_dir = self.work_dir or project_path(
            "outputs", "geometry_pages", f"{file_path.stem}_{uuid.uuid4().hex[:8]}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        return [
            Path(item)
            for item in render_pdf_with_pdftoppm(
                file_path,
                output_dir,
                prefix="page",
                dpi=self.dpi,
            )
        ]


def _extract_pdf_vector_evidence(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    diagnostics: dict[str, Any] = {"status": "running", "pages": []}
    warnings: list[str] = []
    evidence: list[dict[str, Any]] = []
    try:
        import fitz  # PyMuPDF
    except Exception as exc:
        diagnostics["status"] = "unavailable"
        diagnostics["detail"] = f"{type(exc).__name__}: {exc}"
        return [], diagnostics, ["PyMuPDF is not available; skipped vector PDF geometry."]

    try:
        doc = fitz.open(str(path))
        for page_index, page in enumerate(doc, start=1):
            page_diag = {"page": page_index, "drawing_count": 0, "text_block_count": 0}
            diagnostics["pages"].append(page_diag)

            for block in page.get_text("blocks") or []:
                if len(block) < 5:
                    continue
                text = str(block[4] or "").strip()
                if not text or not _looks_like_dimension_text(text):
                    continue
                page_diag["text_block_count"] += 1
                evidence.append(
                    _evidence(
                        kind="vector_text",
                        page=page_index,
                        position=_position_from_bbox(block[0], block[1], block[2], block[3]),
                        confidence=0.72,
                        suggested_region="PDF vector text",
                        metrics={"text": text[:120]},
                    )
                )

            for drawing in page.get_drawings() or []:
                page_diag["drawing_count"] += 1
                for item in drawing.get("items", []) or []:
                    evidence.extend(_vector_item_to_evidence(item, page_index))
        diagnostics["status"] = "success"
        diagnostics["evidence_count"] = len(evidence)
    except Exception as exc:
        diagnostics["status"] = "failed"
        diagnostics["detail"] = f"{type(exc).__name__}: {exc}"
        warnings.append(f"Vector PDF geometry failed: {type(exc).__name__}: {exc}")
    return evidence, diagnostics, warnings


def _vector_item_to_evidence(item: Any, page_number: int) -> list[dict[str, Any]]:
    if not isinstance(item, (list, tuple)) or not item:
        return []
    op = item[0]
    try:
        if op == "l" and len(item) >= 3:
            left, right = item[1], item[2]
            x1, y1 = float(left.x), float(left.y)
            x2, y2 = float(right.x), float(right.y)
            length = math.hypot(x2 - x1, y2 - y1)
            if length < 4:
                return []
            return [
                _evidence(
                    kind="vector_line",
                    page=page_number,
                    position=_position_from_line(x1, y1, x2, y2),
                    confidence=0.82,
                    suggested_region="PDF vector line",
                    metrics={"length": round(length, 2), "angle": round(_angle(x1, y1, x2, y2), 2)},
                )
            ]
        if op == "re" and len(item) >= 2:
            rect = item[1]
            width = float(rect.x1 - rect.x0)
            height = float(rect.y1 - rect.y0)
            if width < 4 or height < 4:
                return []
            return [
                _evidence(
                    kind="vector_rect",
                    page=page_number,
                    position=_position_from_bbox(rect.x0, rect.y0, rect.x1, rect.y1),
                    confidence=0.78,
                    suggested_region="PDF vector rectangle",
                    metrics={"width": round(width, 2), "height": round(height, 2)},
                )
            ]
    except Exception:
        return []
    return []


def _analyze_raster_page(
    image_path: Path,
    page_number: int,
    max_side: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    warnings: list[str] = []
    diagnostics: dict[str, Any] = {
        "page": page_number,
        "image_path": str(image_path),
        "status": "running",
    }
    try:
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("L")
            original_width, original_height = image.size
            scale = min(1.0, max_side / max(original_width, original_height))
            if scale < 1.0:
                image = image.resize(
                    (max(1, int(original_width * scale)), max(1, int(original_height * scale))),
                    Image.Resampling.LANCZOS,
                )
            array = np.asarray(image)
    except Exception as exc:
        diagnostics["status"] = "failed"
        diagnostics["detail"] = f"{type(exc).__name__}: {exc}"
        return [], diagnostics, [f"Geometry image load failed: {type(exc).__name__}: {exc}"]

    evidence: list[dict[str, Any]] = []
    dark = array < _threshold(array)
    diagnostics.update(
        {
            "status": "success",
            "original_size": [original_width, original_height],
            "analysis_size": [int(array.shape[1]), int(array.shape[0])],
            "scale": scale,
            "dark_pixel_ratio": round(float(np.mean(dark)), 5),
        }
    )

    content = _dark_pixel_bbox(dark, scale, page_number)
    if content:
        evidence.append(content)
        evidence.append(_title_block_evidence(content, page_number))

    cv2_evidence, cv2_diag, cv2_warnings = _opencv_geometry(array, dark, scale, page_number)
    diagnostics["opencv"] = cv2_diag
    evidence.extend(cv2_evidence)
    warnings.extend(cv2_warnings)
    if cv2_diag["status"] == "unavailable":
        fallback = _fallback_axis_lines(dark, scale, page_number)
        evidence.extend(fallback)
        diagnostics["fallback_axis_line_count"] = len(fallback)

    return evidence, diagnostics, warnings


def _opencv_geometry(
    array: np.ndarray,
    dark: np.ndarray,
    scale: float,
    page_number: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    diagnostics: dict[str, Any] = {"status": "running"}
    warnings: list[str] = []
    evidence: list[dict[str, Any]] = []
    try:
        import cv2
    except Exception as exc:
        diagnostics["status"] = "unavailable"
        diagnostics["detail"] = f"{type(exc).__name__}: {exc}"
        return [], diagnostics, []

    try:
        binary = (dark.astype(np.uint8) * 255)
        lines = cv2.HoughLinesP(binary, 1, np.pi / 180, threshold=65, minLineLength=28, maxLineGap=5)
        line_items = []
        if lines is not None:
            for line in lines[:, 0, :]:
                x1, y1, x2, y2 = [float(value) / scale for value in line]
                length = math.hypot(x2 - x1, y2 - y1)
                if length >= 18:
                    line_items.append((length, x1, y1, x2, y2))
        for length, x1, y1, x2, y2 in sorted(line_items, reverse=True)[:180]:
            evidence.append(
                _evidence(
                    kind="raster_line",
                    page=page_number,
                    position=_position_from_line(x1, y1, x2, y2),
                    confidence=0.68,
                    suggested_region="Raster line segment",
                    metrics={"length": round(length, 2), "angle": round(_angle(x1, y1, x2, y2), 2)},
                )
            )

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour_items = []
        arrow_items = []
        circle_items = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < 18:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 4 or h < 4:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True) if perimeter else contour
            circularity = 4 * math.pi * area / (perimeter * perimeter) if perimeter else 0.0
            bbox = [x / scale, y / scale, (x + w) / scale, (y + h) / scale]
            if len(approx) == 3 and 16 <= area <= 1800:
                arrow_items.append((area, bbox))
            elif circularity >= 0.42 and 8 <= min(w, h) <= 400:
                circle_items.append((area, bbox, circularity))
            elif area >= 60:
                contour_items.append((area, bbox, len(approx)))

        for area, bbox in sorted(arrow_items, reverse=True)[:60]:
            evidence.append(
                _evidence(
                    kind="arrowhead_candidate",
                    page=page_number,
                    position=_position_from_bbox(*bbox),
                    confidence=0.5,
                    suggested_region="Raster triangular contour",
                    metrics={"area": round(area, 2)},
                )
            )
        for area, bbox, circularity in sorted(circle_items, reverse=True)[:80]:
            evidence.append(
                _evidence(
                    kind="circle_candidate",
                    page=page_number,
                    position=_position_from_bbox(*bbox),
                    confidence=0.58,
                    suggested_region="Raster circle/arc contour",
                    metrics={"area": round(area, 2), "circularity": round(circularity, 3)},
                )
            )
        for area, bbox, vertices in sorted(contour_items, reverse=True)[:80]:
            evidence.append(
                _evidence(
                    kind="contour",
                    page=page_number,
                    position=_position_from_bbox(*bbox),
                    confidence=0.42,
                    suggested_region="Raster dark contour",
                    metrics={"area": round(area, 2), "vertices": vertices},
                )
            )

        diagnostics.update(
            {
                "status": "success",
                "line_count": len(line_items),
                "arrowhead_candidate_count": len(arrow_items),
                "circle_candidate_count": len(circle_items),
                "contour_count": len(contour_items),
            }
        )
    except Exception as exc:
        diagnostics["status"] = "failed"
        diagnostics["detail"] = f"{type(exc).__name__}: {exc}"
        warnings.append(f"OpenCV geometry failed: {type(exc).__name__}: {exc}")
    return evidence, diagnostics, warnings


def _fallback_axis_lines(dark: np.ndarray, scale: float, page_number: int) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    height, width = dark.shape
    row_counts = np.sum(dark, axis=1)
    col_counts = np.sum(dark, axis=0)
    for y in np.where(row_counts > width * 0.25)[0][:80]:
        evidence.append(
            _evidence(
                kind="horizontal_line_candidate",
                page=page_number,
                position=_position_from_line(0, y / scale, width / scale, y / scale),
                confidence=0.36,
                suggested_region="Raster horizontal dark run",
                metrics={"dark_pixels": int(row_counts[y])},
            )
        )
    for x in np.where(col_counts > height * 0.25)[0][:80]:
        evidence.append(
            _evidence(
                kind="vertical_line_candidate",
                page=page_number,
                position=_position_from_line(x / scale, 0, x / scale, height / scale),
                confidence=0.36,
                suggested_region="Raster vertical dark run",
                metrics={"dark_pixels": int(col_counts[x])},
            )
        )
    return evidence


def _threshold(array: np.ndarray) -> float:
    percentile = float(np.percentile(array, 25))
    return max(90.0, min(205.0, percentile + 40.0))


def _dark_pixel_bbox(dark: np.ndarray, scale: float, page_number: int) -> dict[str, Any] | None:
    ys, xs = np.where(dark)
    if len(xs) < 20 or len(ys) < 20:
        return None
    x0, x1 = float(xs.min()) / scale, float(xs.max()) / scale
    y0, y1 = float(ys.min()) / scale, float(ys.max()) / scale
    return _evidence(
        kind="drawing_content_bbox",
        page=page_number,
        position=_position_from_bbox(x0, y0, x1, y1),
        confidence=0.62,
        suggested_region="Raster drawing content bounding box",
        metrics={"dark_pixel_count": int(len(xs))},
    )


def _title_block_evidence(content: dict[str, Any], page_number: int) -> dict[str, Any]:
    position = content["position"]
    x0 = float(position["x"] - position["width"] / 2)
    y0 = float(position["y"] + position["height"] * 0.26)
    x1 = float(position["x"] + position["width"] / 2)
    y1 = float(position["y"] + position["height"] / 2)
    return _evidence(
        kind="title_block_candidate",
        page=page_number,
        position=_position_from_bbox(x0, y0, x1, y1),
        confidence=0.54,
        suggested_region="Bottom title block candidate",
        metrics={},
    )


def _evidence(
    kind: str,
    page: int,
    position: dict[str, Any],
    confidence: float,
    suggested_region: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "",
        "kind": kind,
        "page": page,
        "position": position,
        "confidence": round(float(confidence), 3),
        "source": "geometry",
        "suggested_region": suggested_region,
        "metrics": metrics,
    }


def _evidence_to_candidate(item: dict[str, Any], index: int) -> dict[str, Any]:
    evidence_id = item.get("id") or f"G{index:04d}"
    item = {**item, "id": evidence_id}
    return {
        "field": f"dimension_evidence_{evidence_id}",
        "feature_type": "dimension_evidence",
        "value": item,
        "source": "geometry",
        "evidence": f"{item.get('kind')} on page {item.get('page')}",
        "confidence": item.get("confidence", 0.4),
        "page": item.get("page", 1),
        "position": item.get("position"),
        "suggested_region": item.get("suggested_region", "Geometry evidence"),
    }


def _deduplicate_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        position = item.get("position") or {}
        key = (
            item.get("kind"),
            item.get("page"),
            round(float(position.get("x", 0)), 1),
            round(float(position.get("y", 0)), 1),
            round(float(position.get("width", 0)), 1),
            round(float(position.get("height", 0)), 1),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append({**item, "id": f"G{len(unique) + 1:04d}"})
    return unique


def _position_from_line(x1: float, y1: float, x2: float, y2: float) -> dict[str, Any]:
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    return {
        "coordinate_type": "pixel",
        "x": (x1 + x2) / 2,
        "y": (y1 + y2) / 2,
        "width": max(1.0, right - left),
        "height": max(1.0, bottom - top),
        "polygon": [[x1, y1], [x2, y2]],
    }


def _position_from_bbox(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    left, right = min(float(x0), float(x1)), max(float(x0), float(x1))
    top, bottom = min(float(y0), float(y1)), max(float(y0), float(y1))
    return {
        "coordinate_type": "pixel",
        "x": (left + right) / 2,
        "y": (top + bottom) / 2,
        "width": max(1.0, right - left),
        "height": max(1.0, bottom - top),
        "polygon": [[left, top], [right, top], [right, bottom], [left, bottom]],
    }


def _angle(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.degrees(math.atan2(y2 - y1, x2 - x1))


def _looks_like_dimension_text(text: str) -> bool:
    compact = text.strip()
    if len(compact) > 120:
        return False
    return any(token in compact for token in ("Φ", "φ", "Ø", "R", "H", "F", "±", "+", "-", "°")) or any(
        char.isdigit() for char in compact
    )
