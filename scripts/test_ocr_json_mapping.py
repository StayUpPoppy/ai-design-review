from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.ocr_adapter import OcrJsonEngine


def main() -> None:
    candidates = OcrJsonEngine("data/samples/ocr_example.json").extract()
    fields = {candidate["field"]: candidate for candidate in candidates}
    assert fields["material"]["value"] == "SUS304"
    assert fields["wire_diameter"]["value"] == 1.5
    assert fields["handedness"]["value"] == "右旋"
    assert fields["drawing_no"]["value"] == "YD4765020175"
    assert fields["surface_requirement"]["value"]
    print("ocr json mapping test passed")


if __name__ == "__main__":
    main()
