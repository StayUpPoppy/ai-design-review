from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RecognitionEngine
from ..io_utils import read_json


class OcrEngine(RecognitionEngine):
    """PaddleOCR adapter placeholder with dependency diagnostics."""

    name = "ocr"

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        try:
            import paddle  # noqa: F401
            from paddleocr import PaddleOCR  # noqa: F401
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Local PaddleOCR is not ready: the `paddle` inference engine is missing. "
                "Install paddlepaddle and OCR models, or provide OCR JSON from another service."
            ) from exc

        raise RuntimeError(
            "Local PaddleOCR runtime is detected but no model configuration is wired yet. "
            "Use OcrJsonEngine for Azure/PaddleOCR exported OCR blocks, or configure local model dirs."
        )


class OcrJsonEngine(RecognitionEngine):
    """Convert OCR text blocks from any provider to normalized candidates."""

    name = "ocr_json"

    def __init__(self, ocr_json_path: str | Path):
        self.ocr_json_path = Path(ocr_json_path)

    def extract(self, file_path: str | Path | None = None) -> list[dict[str, Any]]:
        payload = read_json(self.ocr_json_path)
        return ocr_payload_to_candidates(payload)


def ocr_payload_to_candidates(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = payload.get("texts", payload) if isinstance(payload, dict) else payload
    candidates: list[dict[str, Any]] = []
    full_text = "\n".join(str(block.get("text", "")) for block in blocks if block.get("text"))
    anchor = _best_anchor(blocks)

    candidates.extend(_extract_title_fields(blocks))
    candidates.extend(_extract_material(full_text, anchor))
    candidates.extend(_extract_wire_diameter(full_text, anchor))
    candidates.extend(_extract_total_coils(full_text, anchor))
    candidates.extend(_extract_handedness(full_text, anchor))
    candidates.extend(_extract_technical_requirements(full_text, anchor))
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


def _extract_technical_requirements(text: str, anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    candidates = []
    heat = _search(r"300\s*°?\s*C\s*\+?\s*10\s*°?\s*C?\s*/\s*20\s*min\s*\+?\s*1\s*min", text)
    if heat:
        candidates.append(_candidate("heat_treatment", heat.group(0), anchor, heat.group(0), 0.86))

    surface = _search(r"产品不可有油污[，,、\s]*研磨粉尘[，,、\s]*表面毛刺小于线径的?10%", text)
    if surface:
        candidates.append(_candidate("surface_requirement", surface.group(0), anchor, surface.group(0), 0.86))

    salt = _search(r"720\s*h\s*无红锈", text)
    if salt:
        candidates.append(_candidate("salt_spray", salt.group(0), anchor, salt.group(0), 0.9))

    environmental = _search(r"GB/T\s*30512-2014", text)
    if environmental:
        candidates.append(_candidate("environmental", "GB/T 30512-2014", anchor, environmental.group(0), 0.9))
    return candidates


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
