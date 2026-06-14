from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.io_utils import read_json
from ai_design_review.semantic import apply_spring_semantic_mapping


def main() -> None:
    payload = read_json("outputs/werk24_candidates.json")
    candidates = apply_spring_semantic_mapping(payload["candidates"])
    by_field = {}
    load_points = []
    for candidate in candidates:
        if candidate.get("field") == "load_point":
            load_points.append(candidate)
        else:
            by_field[candidate.get("field")] = candidate

    assert by_field["material"]["value"] == "SUS304"
    assert by_field["wire_diameter"]["value"] == 1.5
    assert by_field["outer_diameter"]["value"] == 25
    assert by_field["free_length"]["value"] == 15
    assert len(load_points) == 2
    assert load_points[0]["value"]["force_tolerance_percent"] == 10
    assert load_points[1]["value"]["force_tolerance_percent"] == 10
    print("semantic mapping test passed")


if __name__ == "__main__":
    main()
