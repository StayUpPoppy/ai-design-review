from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.generation_readiness import build_generation_parameter_package  # noqa: E402
from ai_design_review.generation_service import match_generation_template  # noqa: E402


def main() -> None:
    review = {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_parameters": {
            "material": confirmed("60Si2MnA"),
            "wire_diameter": confirmed(2.0),
            "mean_diameter": confirmed(18.0),
            "free_length": confirmed(50.0),
            "total_coils": confirmed(10.0),
            "active_coils": confirmed(8.0),
            "handedness": confirmed("right"),
            "end_type": confirmed("closed_and_ground"),
            "end_grinding": confirmed("ground"),
        },
        "standard_selection": {"selected_standard": "GB/T 1239.2-2009", "human_confirmed": True},
    }
    package = build_generation_parameter_package(review)
    base = {
        "template_code": "compression/general",
        "version": "v1",
        "drawing_type": "compression_spring",
        "label": "通用压簧",
        "priority": 10,
        "enabled": True,
        "is_mock": False,
        "required_fields": ["wire_diameter", "mean_diameter", "free_length"],
        "match_rules": {"ranges": {"wire_diameter": [0.5, 8.0]}},
        "parameter_mapping": {},
        "worker_capability": "solidworks_compression_v1",
    }
    selected = match_generation_template(review, package, [base])
    assert selected["status"] == "selected"
    assert selected["selected_template"]["template_code"] == "compression/general"

    disabled = {**base, "enabled": False}
    assert match_generation_template(review, package, [disabled])["status"] == "template_not_found"
    wrong_type = {**base, "drawing_type": "extension_spring"}
    assert match_generation_template(review, package, [wrong_type])["status"] == "template_not_found"
    missing_required = {**base, "required_fields": ["mandrel_diameter"]}
    assert match_generation_template(review, package, [missing_required])["status"] == "template_not_found"

    tied = deepcopy(base)
    tied["template_code"] = "compression/alternate"
    conflict = match_generation_template(review, package, [base, tied])
    assert conflict["status"] == "template_selection_required"
    requested = match_generation_template(review, package, [base, tied], requested_code="compression/alternate")
    assert requested["status"] == "selected"
    assert requested["selected_template"]["template_code"] == "compression/alternate"

    out_of_range = deepcopy(base)
    out_of_range["match_rules"] = {"ranges": {"wire_diameter": [3.0, 8.0]}}
    assert match_generation_template(review, package, [out_of_range])["status"] == "template_not_found"
    print("generation template matching tests passed")


def confirmed(value: object) -> dict[str, object]:
    return {"value": value, "need_human_review": False}


if __name__ == "__main__":
    main()
