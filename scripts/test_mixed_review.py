from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.ocr_adapter import OcrJsonEngine
from ai_design_review.io_utils import read_json
from ai_design_review.workflow import DrawingReviewWorkflow


def main() -> None:
    rules = read_json("config/factory_rules.json")
    werk24_payload = read_json("outputs/werk24_candidates.json")
    ocr_candidates = OcrJsonEngine("data/samples/ocr_example.json").extract()
    candidates = werk24_payload["candidates"] + ocr_candidates

    result = DrawingReviewWorkflow(rules).run(
        r"C:\Users\29580\Desktop\扫描全能王 2026-06-01 15.54(2).pdf",
        candidates,
    )

    assert result["missing_fields"] == []
    assert result["spring_parameters"]["handedness"]["value"] == "右旋"
    assert result["spring_parameters"]["wire_diameter"]["value"] == 1.5
    assert result["spring_parameters"]["outer_diameter"]["value"] == 25
    assert result["erp_ready"] is False
    print("mixed review test passed")


if __name__ == "__main__":
    main()
