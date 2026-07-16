from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.generation_readiness import assess_generation_readiness
from ai_design_review.spring_feasibility import assess_parameter_reasonableness
from ai_design_review.standardization_chat_agent import chat_about_standardization


def main() -> None:
    _assert_baseline_passes()
    _assert_impossible_diameter_is_blocked()
    _assert_inconsistent_diameters_are_a_warning()
    _assert_cold_standard_scope_is_a_warning()
    _assert_load_height_needs_end_context()
    _assert_load_trend_is_a_warning()
    _assert_generation_is_blocked_by_reasonableness()
    _assert_chat_explains_current_drawing_risks()
    print("parameter reasonableness test passed")


def _assert_baseline_passes() -> None:
    result = assess_parameter_reasonableness(_review())
    assert result["status"] == "pass"
    assert result["issues"] == []


def _assert_impossible_diameter_is_blocked() -> None:
    review = _review()
    review["spring_parameters"]["outer_diameter"]["value"] = 3
    result = assess_parameter_reasonableness(review)
    assert result["status"] == "blocked"
    issue = next(item for item in result["issues"] if item["rule_id"] == "SPRING-GEO-OUTER-INNER")
    assert issue["calculation"].endswith("-1 mm")
    assert issue["customer_question"]


def _assert_inconsistent_diameters_are_a_warning() -> None:
    review = _review()
    review["spring_parameters"]["inner_diameter"] = {"value": 15, "unit": "mm"}
    result = assess_parameter_reasonableness(review)
    assert result["status"] == "warning"
    assert any(item["rule_id"] == "SPRING-GEO-DIAMETER-CONSISTENCY" for item in result["issues"])


def _assert_cold_standard_scope_is_a_warning() -> None:
    review = _review()
    review["spring_parameters"]["outer_diameter"]["value"] = 50
    result = assess_parameter_reasonableness(review)
    assert result["status"] == "warning"
    assert any(item["rule_id"] == "GBT1239.2-SCOPE-SPRING-INDEX" for item in result["issues"])


def _assert_load_height_needs_end_context() -> None:
    review = _review()
    review["spring_parameters"].pop("end_grinding")
    result = assess_parameter_reasonableness(review)
    assert result["status"] == "needs_input"
    assert any(item["rule_id"] == "SPRING-CONTEXT-END-CONDITION" for item in result["issues"])


def _assert_load_trend_is_a_warning() -> None:
    review = _review()
    review["spring_parameters"]["load_points"] = [
        {"label": "F1", "height": 30, "force": 10},
        {"label": "F2", "height": 25, "force": 5},
    ]
    result = assess_parameter_reasonableness(review)
    assert result["status"] == "warning"
    assert any(item["rule_id"] == "SPRING-LOAD-MONOTONICITY" for item in result["issues"])


def _assert_generation_is_blocked_by_reasonableness() -> None:
    review = _review()
    review["spring_parameters"]["outer_diameter"]["value"] = 3
    review["parameter_reasonableness"] = {"status": "pass", "summary": "过期结果", "issues": []}
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "blocked"
    assert readiness["blocking_reasonableness"]


def _assert_chat_explains_current_drawing_risks() -> None:
    review = _review()
    review["spring_parameters"]["outer_diameter"]["value"] = 3
    result = chat_about_standardization(review, "当前图纸有哪些不合理参数")
    assert result["intent"]["type"] == "parameter_reasonableness"
    assert "建议向客户确认" in result["reply"]
    assert result["review"]["parameter_reasonableness"]["status"] == "blocked"


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "standard_selection": {"selected_standard": "GB/T 1239.2-2009"},
        "spring_parameters": {
            "material": {"value": "SUS304", "need_human_review": False},
            "wire_diameter": {"value": 2, "unit": "mm", "need_human_review": False},
            "outer_diameter": {"value": 20, "unit": "mm", "need_human_review": False},
            "free_length": {"value": 40, "unit": "mm", "need_human_review": False},
            "total_coils": {"value": 12, "unit": "turns", "need_human_review": False},
            "active_coils": {"value": 10, "unit": "turns", "need_human_review": False},
            "handedness": {"value": "right", "need_human_review": False},
            "end_grinding": {"value": "两端磨平", "need_human_review": False},
            "load_points": [{"label": "F1", "height": 25, "force": 100, "need_human_review": False}],
        },
        "standardization_results": [],
        "derived_parameters": {},
        "technical_requirements": [],
    }


if __name__ == "__main__":
    main()
