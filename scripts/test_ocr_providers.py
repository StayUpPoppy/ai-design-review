from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ai_design_review.engines.ocr_providers import (  # noqa: E402
    OcrProviderError,
    UnifiedOcrEngine,
    baidu_paddleocr_vl_result_to_pages,
    baidu_result_to_text_blocks,
    normalize_ocr_provider,
    rapidocr_result_to_text_blocks,
)
from ai_design_review.api import _needs_ocr_fallback  # noqa: E402


class FailingProvider:
    name = "baidu_ocr"

    def recognize(self, image_paths, provider_diagnostics):
        raise RuntimeError("simulated cloud outage")


class SuccessfulProvider:
    name = "rapidocr"

    def recognize(self, image_paths, provider_diagnostics):
        return [
            {
                "page": 1,
                "image_path": str(image_paths[0]),
                "texts": [
                    {
                        "text": "SUS304",
                        "source": "rapidocr",
                        "confidence": 0.93,
                        "page": 1,
                        "position": {
                            "coordinate_type": "pixel",
                            "x": 50,
                            "y": 30,
                            "width": 80,
                            "height": 20,
                        },
                        "suggested_region": "RapidOCR text line",
                    }
                ],
                "raw": {"simulated": True},
            }
        ]


class ModernRapidResult:
    boxes = [[[10, 20], [110, 20], [110, 50], [10, 50]]]
    txts = ["SUS304"]
    scores = [0.96]


def main() -> None:
    test_provider_aliases()
    test_baidu_mapping()
    test_baidu_paddleocr_vl_mapping()
    test_rapidocr_mapping()
    test_auto_fallback()
    test_scanned_pdf_api_fallback_gate()
    test_all_providers_failed()
    print("ocr provider tests passed")


def test_provider_aliases() -> None:
    assert normalize_ocr_provider("baidu") == "baidu_ocr"
    assert normalize_ocr_provider("baidu_vl") == "baidu_paddleocr_vl"
    assert normalize_ocr_provider("paddleocr_vl") == "baidu_paddleocr_vl"
    assert normalize_ocr_provider("rapid") == "rapidocr"
    assert normalize_ocr_provider("paddleocr") == "auto"


def test_baidu_mapping() -> None:
    payload = {
        "words_result": [
            {
                "words": "SUS304",
                "probability": {"average": 0.98},
                "location": {"left": 10, "top": 20, "width": 100, "height": 30},
            }
        ]
    }
    blocks = baidu_result_to_text_blocks(payload, 2)
    assert len(blocks) == 1
    assert blocks[0]["source"] == "baidu_ocr"
    assert blocks[0]["page"] == 2
    assert blocks[0]["confidence"] == 0.98
    assert blocks[0]["position"]["x"] == 60


def test_baidu_paddleocr_vl_mapping() -> None:
    payload = {
        "pages": [
            {
                "page_num": 0,
                "layouts": [
                    {
                        "type": "text",
                        "text": "fallback layout text",
                        "position": [10, 20, 100, 30],
                        "span_boxes": [
                            {"text": "SUS304", "location": [12, 22, 70, 18]},
                        ],
                    },
                    {
                        "type": "paragraph_title",
                        "text": "Technical requirements",
                        "position": [10, 70, 180, 20],
                    },
                ],
                "tables": [
                    {
                        "position": [200, 100, 220, 160],
                        "cells": [{"text": "H1=20", "position": [210, 110, 60, 20]}],
                    }
                ],
            }
        ]
    }
    pages = baidu_paddleocr_vl_result_to_pages(payload, Path("drawing.pdf"))
    assert len(pages) == 1
    blocks = pages[0]["texts"]
    assert pages[0]["page"] == 1
    assert [item["text"] for item in blocks] == [
        "SUS304",
        "Technical requirements",
        "H1=20",
    ]
    assert blocks[0]["source"] == "baidu_paddleocr_vl"
    assert blocks[0]["position"]["x"] == 47
    assert blocks[2]["suggested_region"] == "PaddleOCR-VL table cell"


def test_rapidocr_mapping() -> None:
    blocks = rapidocr_result_to_text_blocks(ModernRapidResult(), 1)
    assert len(blocks) == 1
    assert blocks[0]["source"] == "rapidocr"
    assert blocks[0]["confidence"] == 0.96
    assert blocks[0]["position"]["width"] == 100


def test_auto_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image_path = root / "drawing.png"
        Image.new("RGB", (240, 160), "white").save(image_path)
        diagnostics_path = root / "ocr_diagnostics.json"
        engine = UnifiedOcrEngine(
            provider="auto",
            work_dir=root / "work",
            diagnostics_path=diagnostics_path,
            providers={
                "baidu_ocr": FailingProvider(),
                "rapidocr": SuccessfulProvider(),
            },
        )
        payload = engine.extract_with_raw(image_path)
        assert payload["provider"] == "rapidocr"
        assert payload["candidates"][0]["field"] == "material"
        assert payload["warnings"]
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        assert diagnostics["status"] == "success"
        assert diagnostics["selected_provider"] == "rapidocr"
        assert [item["status"] for item in diagnostics["providers"]] == ["failed", "success"]


def test_scanned_pdf_api_fallback_gate() -> None:
    scanned = {"is_scanned_like": True}
    text_pdf = {"is_scanned_like": False}
    assert _needs_ocr_fallback([], scanned, []) is True
    assert _needs_ocr_fallback([{"feature_type": "dimension_evidence"}], scanned, []) is True
    assert _needs_ocr_fallback([{"field": "material", "value": "SUS304"}], scanned, []) is False
    assert _needs_ocr_fallback([], scanned, ["rapidocr"]) is False
    assert _needs_ocr_fallback([], text_pdf, []) is False


def test_all_providers_failed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image_path = root / "drawing.png"
        Image.new("RGB", (120, 80), "white").save(image_path)
        diagnostics_path = root / "ocr_diagnostics.json"
        engine = UnifiedOcrEngine(
            provider="auto",
            work_dir=root / "work",
            diagnostics_path=diagnostics_path,
            providers={
                "baidu_ocr": FailingProvider(),
                "rapidocr": FailingProvider(),
            },
        )
        try:
            engine.extract_with_raw(image_path)
        except OcrProviderError as exc:
            assert "baidu_ocr" in str(exc)
            assert "rapidocr" in str(exc)
        else:
            raise AssertionError("Expected OcrProviderError")
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        assert diagnostics["status"] == "failed"
        assert len(diagnostics["providers"]) == 2


if __name__ == "__main__":
    main()
