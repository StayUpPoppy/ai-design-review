from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.ocr_adapter import ocr_payload_to_candidates, paddle_result_to_text_blocks


def main() -> None:
    raw = [
        {
            "res": {
                "rec_texts": ["SUS304", "25"],
                "rec_scores": [0.91, 0.88],
                "rec_polys": [
                    [[10, 10], [100, 10], [100, 30], [10, 30]],
                    [[300, 200], [340, 200], [340, 230], [300, 230]],
                ],
            }
        }
    ]
    blocks = paddle_result_to_text_blocks(raw, 1)
    assert len(blocks) == 2
    assert blocks[0]["source"] == "paddleocr"
    assert blocks[1]["position"]["x"] == 320

    payload = {
        "texts": [
            _block("15", 180, 110),
            _block("25", 320, 220),
            _block("0", 340, 250),
            _block("-0.02", 340, 285),
            _block("1.材质:SUS304，线径Φ1.5±0.05", 100, 500),
            _block("2.总圈数:4，旋向:右旋", 100, 540),
            _block("5.力值要求: H1压缩到11.414mm/F1=11.9N±10% H2压缩到9.474mm/F2=15.3N±10%（参考）", 100, 580),
            _block("7.盐雾要求720h无红锈", 100, 620),
            _block("8.禁用物质符合GB/T 30512-2014", 100, 660),
        ]
    }
    candidates = ocr_payload_to_candidates(payload)
    by_field = {}
    load_points = []
    for candidate in candidates:
        if candidate["field"] == "load_point":
            load_points.append(candidate)
        else:
            by_field[candidate["field"]] = candidate

    assert by_field["material"]["value"] == "SUS304"
    assert by_field["wire_diameter"]["value"] == 1.5
    assert by_field["outer_diameter"]["value"] == 25
    assert by_field["outer_diameter"]["tolerance_lower"] == -0.02
    assert by_field["free_length"]["value"] == 15
    assert by_field["total_coils"]["value"] == 4
    assert by_field["handedness"]["value"] == "右旋"
    assert len(load_points) == 2
    assert load_points[0]["value"]["force"] == 11.9
    assert load_points[1]["value"]["reference_only"] is True
    assert by_field["salt_spray"]["value"] == "720h无红锈"
    assert by_field["environmental"]["value"] == "GB/T 30512-2014"
    print("paddleocr mapping test passed")


def _block(text: str, x: float, y: float) -> dict:
    return {
        "text": text,
        "source": "paddleocr",
        "confidence": 0.9,
        "page": 1,
        "position": {
            "coordinate_type": "pixel",
            "x": x,
            "y": y,
            "width": 40,
            "height": 20,
        },
        "suggested_region": "PaddleOCR text block",
    }


if __name__ == "__main__":
    main()
