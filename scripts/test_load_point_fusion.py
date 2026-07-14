from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.fusion import fuse_candidates  # noqa: E402


def main() -> None:
    _assert_duplicate_load_points_are_merged()
    _assert_conflicting_load_points_are_merged_and_flagged()
    print("load point fusion tests passed")


def _assert_duplicate_load_points_are_merged() -> None:
    result = fuse_candidates(
        [
            _point("F1", 21.15, 16, "qwen_vision", 0.92),
            _point("f1", 21.15, 16, "rapidocr", 0.88),
            _point("F2", 9.668, 35, "qwen_vision", 0.92),
            _point("F2", 9.668, 35, "rapidocr", 0.88),
        ]
    )
    assert len(result["load_points"]) == 2
    by_label = {item["value"]["label"]: item for item in result["load_points"]}
    assert set(by_label) == {"F1", "F2"}
    assert by_label["F1"]["value"]["height"] == 21.15
    assert by_label["F1"]["value"]["force"] == 16
    assert set(by_label["F1"]["source"]) == {"qwen_vision", "rapidocr"}
    assert result["conflicts"] == []


def _assert_conflicting_load_points_are_merged_and_flagged() -> None:
    result = fuse_candidates(
        [
            _point("F1", 21.15, 16, "qwen_vision", 0.92),
            _point("F1", 20, 16, "rapidocr", 0.88),
        ]
    )
    assert len(result["load_points"]) == 1
    point = result["load_points"][0]
    assert point["value"]["height"] == 21.15
    assert point["need_human_review"] is True
    assert result["conflicts"][0]["field"] == "load_points.F1.height"


def _point(label: str, height: float, force: float, source: str, confidence: float) -> dict:
    return {
        "field": "load_point",
        "value": {
            "label": label,
            "height": height,
            "height_unit": "mm",
            "force": force,
            "force_unit": "N",
        },
        "source": source,
        "evidence": f"{label}: H={height}, F={force}",
        "confidence": confidence,
        "page": 1,
    }


if __name__ == "__main__":
    main()
