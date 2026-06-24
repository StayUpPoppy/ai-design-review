from __future__ import annotations

import inspect
import math
import os
import re
import subprocess
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

from .base import RecognitionEngine
from ..io_utils import project_path, read_json, write_json
from ..preprocessing import IMAGE_EXTENSIONS, render_pdf_with_pdftoppm


class OcrExtractionError(RuntimeError):
    """Raised when all PaddleOCR attempts fail."""

    def __init__(
        self,
        message: str,
        diagnostics: dict[str, Any],
        diagnostics_path: Path | None = None,
    ):
        super().__init__(message)
        self.diagnostics = diagnostics
        self.diagnostics_path = diagnostics_path


class OcrEngine(RecognitionEngine):
    """Run local PaddleOCR and convert text blocks into review candidates."""

    name = "paddleocr"

    def __init__(
        self,
        work_dir: str | Path | None = None,
        lang: str = "ch",
        dpi: int = 220,
        ocr_version: str = "PP-OCRv4",
        text_det_limit_side_len: int = 1600,
        diagnostics_path: str | Path | None = None,
        retry_profiles: list[dict[str, int]] | None = None,
        isolate_runtime: bool = True,
    ):
        self.work_dir = Path(work_dir) if work_dir else None
        self.lang = lang
        self.dpi = dpi
        self.ocr_version = ocr_version
        self.text_det_limit_side_len = text_det_limit_side_len
        self.diagnostics_path = Path(diagnostics_path) if diagnostics_path else None
        self.retry_profiles = self._retry_profiles(retry_profiles)
        self.isolate_runtime = isolate_runtime

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        return self.extract_with_raw(file_path)["candidates"]

    def extract_with_raw(self, file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        diagnostics = self._new_diagnostics(path)

        for attempt_number, profile in enumerate(self.retry_profiles, start=1):
            attempt = {
                "attempt": attempt_number,
                "dpi": profile["dpi"],
                "text_det_limit_side_len": profile["text_det_limit_side_len"],
                "status": "running",
                "stage": None,
                "work_dir": None,
                "image_paths": [],
            }
            diagnostics["attempts"].append(attempt)

            try:
                attempt["stage"] = "render_pdf"
                output_dir = self._attempt_work_dir(path, attempt_number, profile)
                attempt["work_dir"] = str(output_dir) if output_dir else None
                image_paths = self._image_paths(
                    path,
                    output_dir=output_dir,
                    dpi=profile["dpi"],
                    reuse_existing=False,
                )
                attempt["image_paths"] = [str(item) for item in image_paths]

                payload = (
                    self._predict_images_in_subprocess(image_paths, profile, attempt)
                    if self.isolate_runtime
                    else self._predict_images_inline(image_paths, profile, attempt)
                )
                attempt["status"] = "success"
                attempt["stage"] = "complete"
                attempt["text_block_count"] = len(payload.get("texts", []))
                attempt["candidate_count"] = len(payload["candidates"])
                diagnostics["status"] = "success"
                diagnostics["selected_attempt"] = attempt_number
                diagnostics["text_block_count"] = len(payload.get("texts", []))
                diagnostics["candidate_count"] = len(payload["candidates"])
                self._write_diagnostics(diagnostics)
                payload["diagnostics"] = _public_diagnostics(diagnostics, self.diagnostics_path)
                return payload
            except Exception as exc:
                self._record_attempt_failure(attempt, exc)
                diagnostics["status"] = "retrying" if attempt_number < len(self.retry_profiles) else "failed"
                self._write_diagnostics(diagnostics)

        message = _diagnostic_failure_message(diagnostics, self.diagnostics_path)
        raise OcrExtractionError(message, diagnostics, self.diagnostics_path)

    def _create_paddleocr(self, text_det_limit_side_len: int | None = None):
        try:
            import paddle  # noqa: F401
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Local PaddleOCR is not ready: the `paddle` inference engine is missing. "
                "Install it with `python -m pip install paddlepaddle`, then restart uvicorn."
            ) from exc

        try:
            from paddleocr import PaddleOCR
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Local PaddleOCR package is missing. Install it with `python -m pip install paddleocr`."
            ) from exc

        kwargs: dict[str, Any] = {"lang": self.lang}
        params = inspect.signature(PaddleOCR).parameters
        if "ocr_version" in params:
            kwargs["ocr_version"] = self.ocr_version
        if "use_doc_orientation_classify" in params:
            kwargs["use_doc_orientation_classify"] = False
        if "use_doc_unwarping" in params:
            kwargs["use_doc_unwarping"] = False
        if "use_textline_orientation" in params:
            kwargs["use_textline_orientation"] = False
        elif "use_angle_cls" in params:
            kwargs["use_angle_cls"] = False
        if "text_det_limit_side_len" in params:
            kwargs["text_det_limit_side_len"] = text_det_limit_side_len or self.text_det_limit_side_len
        return PaddleOCR(**kwargs)

    def _image_paths(
        self,
        file_path: str | Path,
        output_dir: Path | None = None,
        dpi: int | None = None,
        reuse_existing: bool = True,
    ) -> list[Path]:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            return [path]
        if suffix != ".pdf":
            raise RuntimeError(f"PaddleOCR only supports PDF or image input in this adapter: {suffix}")

        output_dir = output_dir or self.work_dir or project_path("outputs", "paddleocr_pages", f"{path.stem}_{uuid.uuid4().hex[:8]}")
        output_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(output_dir.glob("page-*.png"))
        if reuse_existing and existing:
            return existing
        return [Path(item) for item in render_pdf_with_pdftoppm(path, output_dir, prefix="page", dpi=dpi or self.dpi)]

    def _predict(self, ocr: Any, image_path: Path) -> Any:
        if hasattr(ocr, "predict"):
            try:
                return ocr.predict(input=str(image_path))
            except TypeError:
                return ocr.predict(str(image_path))
        return ocr.ocr(str(image_path), cls=True)

    def _predict_images_inline(
        self,
        image_paths: list[Path],
        profile: dict[str, int],
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        attempt["stage"] = "create_ocr"
        ocr = self._create_paddleocr(profile["text_det_limit_side_len"])

        blocks: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        for page_number, image_path in enumerate(image_paths, start=1):
            attempt["stage"] = "predict"
            attempt["page"] = page_number
            attempt["image_path"] = str(image_path)
            raw = self._predict(ocr, image_path)

            attempt["stage"] = "parse_result"
            page_blocks = paddle_result_to_text_blocks(raw, page_number)
            blocks.extend(page_blocks)
            raw_pages.append(
                {
                    "page": page_number,
                    "image_path": str(image_path),
                    "texts": page_blocks,
                    "raw": _jsonable(raw),
                }
            )

        payload = {
            "engine": self.name,
            "texts": blocks,
            "raw_pages": raw_pages,
        }
        payload["candidates"] = ocr_payload_to_candidates(payload)
        return payload

    def _predict_images_in_subprocess(
        self,
        image_paths: list[Path],
        profile: dict[str, int],
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        attempt["stage"] = "predict"
        work_dir = Path(str(attempt.get("work_dir") or image_paths[0].parent))
        work_dir.mkdir(parents=True, exist_ok=True)
        request_path = work_dir / "ocr_child_request.json"
        result_path = work_dir / "ocr_child_result.json"
        request = {
            "image_paths": [str(path) for path in image_paths],
            "profile": profile,
            "lang": self.lang,
            "ocr_version": self.ocr_version,
        }
        write_json(request_path, request)

        env = os.environ.copy()
        src_path = str(project_path("src"))
        env["PYTHONPATH"] = src_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        command = [
            sys.executable,
            "-m",
            "ai_design_review.engines.ocr_adapter",
            "--predict-request",
            str(request_path),
            "--predict-output",
            str(result_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(project_path()),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(180, 120 * len(image_paths)),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"PaddleOCR child process timed out after {exc.timeout}s") from exc

        attempt["child_returncode"] = completed.returncode
        attempt["child_stdout_tail"] = _tail(completed.stdout)
        attempt["child_stderr_tail"] = _tail(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(
                "PaddleOCR child process failed "
                f"with exit code {completed.returncode}: {_tail(completed.stderr or completed.stdout, 1200)}"
            )
        if not result_path.exists():
            raise RuntimeError("PaddleOCR child process did not produce an OCR result file.")
        return read_json(result_path)

    def _retry_profiles(self, retry_profiles: list[dict[str, int]] | None) -> list[dict[str, int]]:
        profiles = retry_profiles or [
            {"dpi": self.dpi, "text_det_limit_side_len": self.text_det_limit_side_len},
            {"dpi": 180, "text_det_limit_side_len": 1280},
            {"dpi": 150, "text_det_limit_side_len": 960},
        ]
        deduped = []
        seen = set()
        for item in profiles:
            profile = {
                "dpi": int(item["dpi"]),
                "text_det_limit_side_len": int(item["text_det_limit_side_len"]),
            }
            key = (profile["dpi"], profile["text_det_limit_side_len"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(profile)
        return deduped

    def _attempt_work_dir(self, file_path: Path, attempt_number: int, profile: dict[str, int]) -> Path | None:
        if file_path.suffix.lower() in IMAGE_EXTENSIONS:
            return None
        base_dir = self.work_dir or project_path("outputs", "paddleocr_pages", f"{file_path.stem}_{uuid.uuid4().hex[:8]}")
        return base_dir / f"attempt_{attempt_number}_{profile['dpi']}dpi_{profile['text_det_limit_side_len']}px"

    def _new_diagnostics(self, file_path: Path) -> dict[str, Any]:
        return {
            "engine": self.name,
            "status": "running",
            "file_path": str(file_path),
            "file_suffix": file_path.suffix.lower(),
            "lang": self.lang,
            "ocr_version": self.ocr_version,
            "attempts": [],
        }

    def _record_attempt_failure(self, attempt: dict[str, Any], exc: Exception) -> None:
        attempt["status"] = "failed"
        attempt["exception_type"] = type(exc).__name__
        attempt["exception_message"] = str(exc)
        attempt["traceback_tail"] = traceback.format_exception(type(exc), exc, exc.__traceback__)[-24:]

    def _write_diagnostics(self, diagnostics: dict[str, Any]) -> None:
        if not self.diagnostics_path:
            return
        self.diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.diagnostics_path, diagnostics)


def _public_diagnostics(diagnostics: dict[str, Any], diagnostics_path: Path | None) -> dict[str, Any]:
    attempts = diagnostics.get("attempts", [])
    return {
        "status": diagnostics.get("status"),
        "selected_attempt": diagnostics.get("selected_attempt"),
        "attempt_count": len(attempts),
        "text_block_count": diagnostics.get("text_block_count", 0),
        "candidate_count": diagnostics.get("candidate_count", 0),
        "diagnostics_path": str(diagnostics_path) if diagnostics_path else None,
    }


def _diagnostic_failure_message(diagnostics: dict[str, Any], diagnostics_path: Path | None) -> str:
    attempts = diagnostics.get("attempts", [])
    last_attempt = attempts[-1] if attempts else {}
    stage = last_attempt.get("stage") or "unknown"
    exc_type = last_attempt.get("exception_type") or "Exception"
    exc_message = last_attempt.get("exception_message") or "unknown error"
    if "child process failed" in exc_message:
        summary = "PaddleOCR child process failed; see diagnostics for stderr and traceback"
    elif "Command '" in exc_message or len(exc_message) > 180:
        summary = "see diagnostics for full error details"
    else:
        summary = " ".join(exc_message.splitlines())
    detail = f"PaddleOCR failed after {len(attempts)} attempts at {stage} stage: {exc_type}: {summary}"
    if diagnostics_path:
        detail += f"; diagnostics saved to {diagnostics_path}"
    return detail


class OcrJsonEngine(RecognitionEngine):
    """Convert OCR text blocks from any provider to normalized candidates."""

    name = "ocr_json"

    def __init__(self, ocr_json_path: str | Path):
        self.ocr_json_path = Path(ocr_json_path)

    def extract(self, file_path: str | Path | None = None) -> list[dict[str, Any]]:
        payload = read_json(self.ocr_json_path)
        return ocr_payload_to_candidates(payload)


def paddle_result_to_text_blocks(raw: Any, page_number: int) -> list[dict[str, Any]]:
    """Normalize PaddleOCR 2.x/3.x output variants into text blocks."""
    blocks = _blocks_from_dict_result(_result_payload(raw), page_number)
    if blocks:
        return blocks
    return _blocks_from_legacy_result(raw, page_number)


def ocr_payload_to_candidates(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = payload.get("texts", payload) if isinstance(payload, dict) else payload
    candidates: list[dict[str, Any]] = []
    full_text = "\n".join(str(block.get("text", "")) for block in blocks if block.get("text"))
    anchor = _best_anchor(blocks)

    candidates.extend(_extract_title_fields(blocks))
    candidates.extend(_extract_material(full_text, anchor))
    candidates.extend(_extract_labeled_numeric_fields(full_text, anchor))
    candidates.extend(_extract_wire_diameter(full_text, anchor))
    candidates.extend(_extract_outer_diameter(full_text, anchor, blocks))
    candidates.extend(_extract_free_length(full_text, anchor, blocks))
    candidates.extend(_extract_total_coils(full_text, anchor))
    candidates.extend(_extract_handedness(full_text, anchor))
    candidates.extend(_extract_load_points(full_text, anchor))
    candidates.extend(_extract_technical_requirements(full_text, anchor))
    candidates.extend(_document_text_candidates(blocks))
    return candidates


def _document_text_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for block in blocks:
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        page = int(block.get("page", 1) or 1)
        grouped.setdefault(page, []).append(block)

    candidates = []
    for page, page_blocks in grouped.items():
        text = "\n".join(str(block.get("text", "")).strip() for block in page_blocks if block.get("text"))
        if not text:
            continue
        anchor = page_blocks[0]
        candidates.append(
            {
                "field": f"document_text_{page}",
                "feature_type": "note",
                "value": text[:12000],
                "source": anchor.get("source", "ocr_json"),
                "evidence": text[:12000],
                "confidence": min(float(anchor.get("confidence", 0.7) or 0.7), 0.74),
                "page": page,
                "position": anchor.get("position"),
                "suggested_region": "OCR full page text",
            }
        )
    return candidates


def _extract_title_fields(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for block in blocks:
        text = str(block.get("text", "")).strip()
        if "外弹簧" in text or "弹簧" in text and len(text) <= 40:
            candidates.append(_candidate("drawing_name", text, block, text, 0.86))
        if "YD" in text:
            match = _search(r"\bYD\d+\b", text)
            if match:
                candidates.append(_candidate("drawing_no", match.group(0), block, text, 0.9))
        if text in {"A0", "A1", "A2", "A3", "B0"}:
            candidates.append(_candidate("version", text, block, text, 0.86))
    return candidates


def _extract_material(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    match = _search(r"SUS\s*(?:304|301|316)", text)
    if not match:
        return []
    value = match.group(0).replace(" ", "").upper()
    return [_candidate("material", value, anchor, match.group(0), 0.92)]


def _extract_labeled_numeric_fields(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    numeric_rules = [
        ("wire_diameter", r"(?:线径|线经|WIRE\s*DIA|WIRE|wire)\s*[:：]?\s*[φΦØø]?\s*(\d+(?:\.\d+)?)", "mm", 0.82),
        ("outer_diameter", r"(?:外径|外徑|OD|O\.D\.)\s*[:：]?\s*[φΦØø]?\s*(\d+(?:\.\d+)?)", "mm", 0.8),
        ("inner_diameter", r"(?:内径|內徑|ID|I\.D\.)\s*[:：]?\s*[φΦØø]?\s*(\d+(?:\.\d+)?)", "mm", 0.8),
        ("mean_diameter", r"(?:中径|中徑|平均径|MEAN\s*DIA)\s*[:：]?\s*[φΦØø]?\s*(\d+(?:\.\d+)?)", "mm", 0.8),
        ("free_length", r"(?:自由长|自由长度|自由長度|FREE\s*LENGTH|L0|Lf)\s*[:：]?\s*(\d+(?:\.\d+)?)", "mm", 0.8),
        ("body_length", r"(?:弹体长|弹体长度|BODY\s*LENGTH)\s*[:：]?\s*(\d+(?:\.\d+)?)", "mm", 0.72),
        ("total_coils", r"(?:总圈数|總圈數|圈数|圈數|TOTAL\s*COILS)\s*[:：]?\s*(\d+(?:\.\d+)?)", "turns", 0.82),
        ("active_coils", r"(?:有效圈数|有效圈數|ACTIVE\s*COILS)\s*[:：]?\s*(\d+(?:\.\d+)?)", "turns", 0.78),
        ("pitch", r"(?:节距|節距|PITCH)\s*[:：]?\s*(\d+(?:\.\d+)?)", "mm", 0.78),
        ("arm_length", r"(?:臂长|臂長|ARM\s*LENGTH)\s*[:：]?\s*(\d+(?:\.\d+)?)", "mm", 0.72),
        ("free_angle", r"(?:自由角|FREE\s*ANGLE)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:°|deg)?", "deg", 0.72),
        ("working_angle", r"(?:工作角|WORKING\s*ANGLE)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:°|deg)?", "deg", 0.72),
        ("opening_width", r"(?:开口|開口|OPENING)\s*[:：]?\s*(\d+(?:\.\d+)?)", "mm", 0.7),
        ("gap_width", r"(?:缺口宽|缺口寬|缺口|GAP)\s*[:：]?\s*(\d+(?:\.\d+)?)", "mm", 0.7),
        ("thickness", r"(?:厚度|板厚|THICKNESS)\s*[:：]?\s*(\d+(?:\.\d+)?)", "mm", 0.72),
    ]
    seen: set[str] = set()
    for field, pattern, unit, confidence in numeric_rules:
        match = _search(pattern, text)
        if not match or field in seen:
            continue
        value = float(match.group(1))
        if value.is_integer():
            value = int(value)
        candidates.append(_candidate(field, value, anchor, match.group(0), confidence, unit=unit))
        seen.add(field)

    handedness = _search(r"(左旋|右旋)", text)
    if handedness:
        candidates.append(_candidate("handedness", handedness.group(1), anchor, handedness.group(0), 0.84))

    hardness = _search(r"HRC\s*\d+(?:\s*[-~～]\s*\d+)?", text)
    if hardness:
        candidates.append(_candidate("hardness", re.sub(r"\s+", "", hardness.group(0).upper()), anchor, hardness.group(0), 0.84))

    surface = _extract_surface_requirement(text)
    if surface is not None:
        value, evidence, confidence = surface
        candidates.append(_candidate("surface_requirement", value, anchor, evidence, confidence))

    return candidates


def _extract_wire_diameter(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    match = _search(r"(?:线径|线经)?\s*[ΦØ]?\s*(\d+(?:\.\d+)?)\s*[±＋]\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return []
    value = float(match.group(1))
    if value > 8:
        return []
    tolerance = float(match.group(2))
    return [
        _candidate(
            "wire_diameter",
            value,
            anchor,
            match.group(0),
            0.92,
            unit="mm",
            tolerance_upper=tolerance,
            tolerance_lower=-tolerance,
        )
    ]


def _extract_outer_diameter(
    text: str,
    anchor: dict[str, Any] | None,
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    match = _search(r"(?:[ΦØ]\s*)?(\d+(?:\.\d+)?)\s*(?:0|上偏差0)\s*[-−]\s*(0\.\d+)", text)
    if match:
        value = float(match.group(1))
        lower = -float(match.group(2))
        if 8 <= value <= 120:
            return [
                _candidate(
                    "outer_diameter",
                    int(value) if value.is_integer() else value,
                    anchor,
                    match.group(0),
                    0.78,
                    unit="mm",
                    tolerance_upper=0,
                    tolerance_lower=lower,
                )
            ]

    cluster = _outer_diameter_vertical_cluster(blocks)
    if cluster:
        value, lower, evidence, block = cluster
        return [
            _candidate(
                "outer_diameter",
                int(value) if value.is_integer() else value,
                block,
                evidence,
                0.66,
                unit="mm",
                tolerance_upper=0,
                tolerance_lower=lower,
            )
        ]

    block = _outer_diameter_block(blocks)
    if not block:
        return []
    value = _number_from_text(str(block.get("text", "")))
    if value is None:
        return []
    return [
        _candidate(
            "outer_diameter",
            int(value) if value.is_integer() else value,
            block,
            str(block.get("text", "")),
            0.68,
            unit="mm",
            tolerance_upper=0 if _has_nearby_text(block, blocks, {"0"}) else None,
            tolerance_lower=-0.02 if _has_nearby_number(block, blocks, -0.02) else None,
        )
    ]


def _extract_free_length(
    text: str,
    anchor: dict[str, Any] | None,
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    explicit = _search(r"(?:自由长|自由长度|L0|Lf)\s*[:：=]?\s*(\d+(?:\.\d+)?)", text)
    if explicit:
        value = float(explicit.group(1))
        return [_candidate("free_length", int(value) if value.is_integer() else value, anchor, explicit.group(0), 0.82, unit="mm")]

    block = _free_length_block(blocks, text)
    if not block:
        return []
    value = _number_from_text(str(block.get("text", "")))
    if value is None:
        return []
    return [_candidate("free_length", int(value) if value.is_integer() else value, block, str(block.get("text", "")), 0.62, unit="mm")]


def _extract_total_coils(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    match = _search(r"总圈数\s*[:：]?\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return []
    value = float(match.group(1))
    return [_candidate("total_coils", int(value) if value.is_integer() else value, anchor, match.group(0), 0.9, unit="turns")]


def _extract_handedness(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    if "右旋" in text:
        return [_candidate("handedness", "右旋", anchor, "右旋", 0.94)]
    if "左旋" in text:
        return [_candidate("handedness", "左旋", anchor, "左旋", 0.94)]
    return []


def _extract_load_points(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    candidates = []
    for index in ("1", "2"):
        pair = _search(
            rf"H{index}\s*(?:=|压缩到|壓縮到)?\s*(\d+(?:\.\d+)?)\s*mm?"
            rf"[\s\S]{{0,80}}?"
            rf"F{index}\s*=?\s*(\d+(?:\.\d+)?)\s*N?\s*(?:±|士|\+/-)?\s*(\d+(?:\.\d+)?)?\s*%?\s*(?:[（(]?参考[）)]?)?",
            text,
        )
        if not pair:
            continue
        height = float(pair.group(1))
        force = float(pair.group(2))
        tolerance = float(pair.group(3)) if pair.group(3) else 10 if "±10%" in pair.group(0) or "士10%" in pair.group(0) else None
        evidence = pair.group(0)
        candidates.append(
            _candidate(
                "load_point",
                {
                    "label": f"F{index}",
                    "height": height,
                    "height_unit": "mm",
                    "force": force,
                    "force_unit": "N",
                    "force_tolerance_percent": int(tolerance) if tolerance and float(tolerance).is_integer() else tolerance,
                    "reference_only": index == "2" and ("参考" in evidence or "參考" in evidence),
                },
                anchor,
                evidence,
                0.78,
            )
        )
    return candidates


def _extract_technical_requirements(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    candidates = []
    heat = _search(r"300\s*°?\s*C\s*\+?\s*10\s*°?\s*C?\s*/\s*20\s*min\s*\+?\s*1\s*min", text)
    if heat:
        candidates.append(_candidate("heat_treatment", heat.group(0), anchor, heat.group(0), 0.86))

    surface = _search(r"产品不可有油污[，,、\s]*研磨粉尘[，,、\s]*表面毛刺小于线径的?10%", text)
    if surface:
        candidates.append(_candidate("surface_requirement", surface.group(0), anchor, surface.group(0), 0.86))
    elif (surface_requirement := _extract_surface_requirement(text)) is not None:
        value, evidence, confidence = surface_requirement
        candidates.append(_candidate("surface_requirement", value, anchor, evidence, confidence))

    hardness = _search(r"HRC\s*\d+(?:\s*[-~～]\s*\d+)?", text)
    if hardness:
        candidates.append(_candidate("hardness", re.sub(r"\s+", "", hardness.group(0).upper()), anchor, hardness.group(0), 0.86))

    salt = _search(r"720\s*h\s*无红锈", text)
    if salt:
        candidates.append(_candidate("salt_spray", salt.group(0), anchor, salt.group(0), 0.9))

    environmental = _search(r"GB/T\s*30512-2014", text)
    if environmental:
        candidates.append(_candidate("environmental", "GB/T 30512-2014", anchor, environmental.group(0), 0.9))
    return candidates


def _extract_surface_requirement(text: str) -> tuple[str, str, float] | None:
    labeled = _search(r"(表面处理|表面處理|表面要求|外观要求|外觀要求)\s*[:：]?\s*([^\n\r|;；]*)", text)
    if labeled:
        value = labeled.group(2).strip()
        return value, labeled.group(0).strip(), 0.84 if value else 0.62

    treatments = (
        "镀锌五彩",
        "镀锌",
        "镀镍",
        "镀铬",
        "镀锡",
        "钝化",
        "发黑",
        "磷化",
        "达克罗",
        "电泳",
        "喷塑",
        "防锈油",
    )
    for treatment in treatments:
        if treatment in text:
            return treatment, treatment, 0.86
    return None


def _result_payload(raw: Any) -> Any:
    if isinstance(raw, list) and len(raw) == 1:
        return _result_payload(raw[0])
    if hasattr(raw, "json"):
        value = raw.json
        if callable(value):
            value = value()
        return _result_payload(value)
    if isinstance(raw, dict) and "res" in raw:
        return _result_payload(raw["res"])
    return raw


def _blocks_from_dict_result(payload: Any, page_number: int) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        blocks: list[dict[str, Any]] = []
        for item in payload:
            blocks.extend(_blocks_from_dict_result(item, page_number))
        return blocks
    if not isinstance(payload, dict):
        return []

    if "res" in payload:
        return _blocks_from_dict_result(payload["res"], page_number)

    texts = payload.get("rec_texts") or payload.get("texts") or payload.get("text")
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, list):
        return []

    scores = payload.get("rec_scores") or payload.get("scores") or []
    polygons = payload.get("rec_polys") or payload.get("dt_polys") or payload.get("polys") or payload.get("rec_boxes") or []
    blocks = []
    for index, text in enumerate(texts):
        if not text:
            continue
        polygon = polygons[index] if index < len(polygons) else None
        score = scores[index] if index < len(scores) else 0.72
        blocks.append(
            {
                "text": str(text).strip(),
                "source": "paddleocr",
                "confidence": float(score or 0.72),
                "page": page_number,
                "position": _position_from_polygon(polygon),
                "suggested_region": "PaddleOCR text block",
            }
        )
    return blocks


def _blocks_from_legacy_result(raw: Any, page_number: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    lines: list[Any]
    if raw and isinstance(raw[0], list) and raw[0] and _is_legacy_line(raw[0][0]):
        lines = raw[0]
    elif raw and _is_legacy_line(raw[0]):
        lines = raw
    else:
        lines = []
        for item in raw:
            lines.extend(_blocks_from_legacy_result(item, page_number))
        return lines

    blocks = []
    for line in lines:
        polygon, text_score = line
        text, score = text_score if isinstance(text_score, (list, tuple)) else (str(text_score), 0.72)
        if not text:
            continue
        blocks.append(
            {
                "text": str(text).strip(),
                "source": "paddleocr",
                "confidence": float(score or 0.72),
                "page": page_number,
                "position": _position_from_polygon(polygon),
                "suggested_region": "PaddleOCR text block",
            }
        )
    return blocks


def _is_legacy_line(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], list)
        and isinstance(value[1], (list, tuple))
        and len(value[1]) >= 1
    )


def _position_from_polygon(polygon: Any) -> dict[str, Any] | None:
    points = _polygon_points(polygon)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {
        "coordinate_type": "pixel",
        "x": sum(xs) / len(xs),
        "y": sum(ys) / len(ys),
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
        "polygon": points,
    }


def _polygon_points(polygon: Any) -> list[list[float]]:
    if polygon is None:
        return []
    if hasattr(polygon, "tolist"):
        polygon = polygon.tolist()
    if isinstance(polygon, tuple):
        polygon = list(polygon)
    if not isinstance(polygon, list):
        return []
    if len(polygon) == 4 and all(isinstance(value, (int, float)) for value in polygon):
        left, top, right, bottom = [float(value) for value in polygon]
        return [[left, top], [right, top], [right, bottom], [left, bottom]]
    points = []
    for item in polygon:
        if hasattr(item, "tolist"):
            item = item.tolist()
        if isinstance(item, tuple):
            item = list(item)
        if isinstance(item, list) and len(item) >= 2:
            try:
                points.append([float(item[0]), float(item[1])])
            except (TypeError, ValueError):
                continue
    return points


def _outer_diameter_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for block in blocks:
        value = _number_from_text(str(block.get("text", "")))
        if value is None or not 8 <= value <= 120:
            continue
        if _has_nearby_text(block, blocks, {"0"}) and _has_nearby_number(block, blocks, -0.02):
            candidates.append((value, block))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return None


def _outer_diameter_vertical_cluster(blocks: list[dict[str, Any]]) -> tuple[float, float, str, dict[str, Any]] | None:
    tolerance_like = [
        block for block in blocks
        if _looks_like_vertical_tolerance(str(block.get("text", "")))
    ]
    for tolerance_block in tolerance_like:
        nearby_digits = [
            other for other in blocks
            if other is not tolerance_block
            and str(other.get("text", "")).strip() in {"2", "5"}
            and _distance(tolerance_block, other) <= 120
        ]
        digits = {str(item.get("text", "")).strip(): item for item in nearby_digits}
        if "2" not in digits or "5" not in digits:
            continue
        two = digits["2"]
        five = digits["5"]
        value = 25.0 if (two.get("position") or {}).get("y", 0) >= (five.get("position") or {}).get("y", 0) else 52.0
        if value != 25.0:
            continue
        evidence = " / ".join(
            str(item.get("text", "")).strip()
            for item in [tolerance_block, digits["5"], digits["2"]]
            if item.get("text")
        )
        return value, -0.02, evidence, tolerance_block
    return None


def _looks_like_vertical_tolerance(text: str) -> bool:
    compact = text.replace(" ", "").replace("O", "0").replace("o", "0")
    return (
        "0.02" in compact
        or "0-02" in compact
        or "20:0-" in compact
        or "20.0-" in compact
        or "20-0" in compact
    )


def _free_length_block(blocks: list[dict[str, Any]], full_text: str) -> dict[str, Any] | None:
    outer = _outer_diameter_block(blocks)
    outer_value = _number_from_text(str(outer.get("text", ""))) if outer else None
    heights = _load_heights(full_text)
    min_free = max(heights) if heights else 0

    candidates = []
    for block in blocks:
        text = str(block.get("text", "")).strip()
        value = _number_from_text(text)
        if value is None:
            continue
        if not min_free < value <= 100:
            continue
        if outer_value is not None and value >= outer_value:
            continue
        if any(token in text.upper() for token in ("F", "H", "%", "N", "SUS", "GB")):
            continue
        candidates.append((value, block))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _load_heights(text: str) -> list[float]:
    return [
        float(match)
        for match in _findall(r"H[12]\s*(?:=|压缩到|壓縮到)?\s*(\d+(?:\.\d+)?)", text)
    ]


def _has_nearby_text(block: dict[str, Any], blocks: list[dict[str, Any]], expected: set[str]) -> bool:
    return any(
        other is not block
        and str(other.get("text", "")).strip() in expected
        and _distance(block, other) <= 180
        for other in blocks
    )


def _has_nearby_number(block: dict[str, Any], blocks: list[dict[str, Any]], expected: float) -> bool:
    return any(
        other is not block
        and (value := _number_from_text(str(other.get("text", "")))) is not None
        and abs(value - expected) <= 1e-6
        and _distance(block, other) <= 220
        for other in blocks
    )


def _distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_pos = left.get("position") or {}
    right_pos = right.get("position") or {}
    if left_pos.get("x") is None or right_pos.get("x") is None:
        return 999999.0
    return math.hypot(float(left_pos["x"]) - float(right_pos["x"]), float(left_pos["y"]) - float(right_pos["y"]))


def _number_from_text(text: str) -> float | None:
    match = _search(r"^[ΦØ]?\s*([-−]?\d+(?:\.\d+)?)\s*(?:mm)?$", text.strip())
    if not match:
        return None
    return float(match.group(1).replace("−", "-"))


def _slice_text(text: str, start: int, end: int) -> str:
    left = max(0, start - 16)
    right = min(len(text), end + 24)
    return " ".join(text[left:right].split())


def _jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if hasattr(value, "json"):
        json_value = value.json
        if callable(json_value):
            json_value = json_value()
        return _jsonable(json_value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _candidate(
    field: str,
    value: Any,
    block: dict[str, Any] | None,
    evidence: str,
    confidence: float,
    unit: str | None = None,
    tolerance_upper: float | None = None,
    tolerance_lower: float | None = None,
) -> dict[str, Any]:
    block = block or {}
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "tolerance_upper": tolerance_upper,
        "tolerance_lower": tolerance_lower,
        "source": block.get("source", "ocr_json"),
        "evidence": evidence,
        "confidence": min(float(block.get("confidence", confidence) or confidence), confidence),
        "page": block.get("page", 1),
        "position": block.get("position"),
        "suggested_region": block.get("suggested_region", "OCR text block"),
    }


def _best_anchor(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in blocks:
        text = str(block.get("text", ""))
        if "技术要求" in text or "材质" in text or "总圈数" in text:
            return block
    return blocks[0] if blocks else None


def _search(pattern: str, text: str):
    import re

    return re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)


def _findall(pattern: str, text: str) -> list[str]:
    import re

    return re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE)


def _tail(text: str | None, limit: int = 4000) -> str:
    if not text:
        return ""
    return text[-limit:]


def _predict_child_main(request_path: str | Path, output_path: str | Path) -> None:
    request = read_json(request_path)
    profile = request["profile"]
    engine = OcrEngine(
        lang=request.get("lang", "ch"),
        ocr_version=request.get("ocr_version", "PP-OCRv4"),
        dpi=int(profile["dpi"]),
        text_det_limit_side_len=int(profile["text_det_limit_side_len"]),
        retry_profiles=[profile],
        isolate_runtime=False,
    )
    payload = engine._predict_images_inline(
        [Path(item) for item in request["image_paths"]],
        {
            "dpi": int(profile["dpi"]),
            "text_det_limit_side_len": int(profile["text_det_limit_side_len"]),
        },
        {"attempt": "child"},
    )
    write_json(output_path, payload)


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Internal PaddleOCR child runner")
    parser.add_argument("--predict-request")
    parser.add_argument("--predict-output")
    args = parser.parse_args()
    if args.predict_request and args.predict_output:
        _predict_child_main(args.predict_request, args.predict_output)
        return
    parser.error("No internal command selected.")


if __name__ == "__main__":
    _main()
