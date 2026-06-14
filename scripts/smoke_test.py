from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.io_utils import project_path, read_json
from ai_design_review.workflow import DrawingReviewWorkflow


def main() -> None:
    payload = read_json(project_path("data", "samples", "spring_example_candidates.json"))
    rules = read_json(project_path("config", "factory_rules.json"))
    workflow = DrawingReviewWorkflow(rules)
    result = workflow.run(None, payload["candidates"])

    assert result["spring_parameters"]["wire_diameter"]["value"] == 1.5
    assert result["spring_parameters"]["outer_diameter"]["value"] == 25
    assert len(result["spring_parameters"]["load_points"]) == 2
    assert result["human_review_required"] is True
    assert result["erp_ready"] is False
    print("smoke test passed")


if __name__ == "__main__":
    main()
