from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.spring_feasibility import assess_parameter_change_set
from ai_design_review.standardization_chat_agent import chat_about_standardization


def main() -> None:
    _assert_valid_change_has_derived_preview()
    _assert_impossible_diameter_is_blocked()
    _assert_out_of_table_spring_index_is_warning()
    _assert_invalid_coil_relationship_is_blocked()
    _assert_load_point_height_change_is_simulated()
    _assert_existing_end_condition_conflict_does_not_block_active_coils()
    _assert_new_end_condition_conflict_is_blocked()
    _assert_agent_attaches_blocking_validation()
    print("spring feasibility test passed")


def _assert_valid_change_has_derived_preview() -> None:
    result = assess_parameter_change_set(_review(), [_parameter_action("outer_diameter", 22)])
    assert result["status"] == "ready"
    assert result["derived_preview"]["mean_diameter"]["value"] == 20
    assert result["derived_preview"]["spring_index"]["value"] == 10


def _assert_impossible_diameter_is_blocked() -> None:
    result = assess_parameter_change_set(_review(), [_parameter_action("outer_diameter", 3)])
    assert result["status"] == "blocked"
    assert any("两倍线径" in item["message"] for item in result["issues"])


def _assert_out_of_table_spring_index_is_warning() -> None:
    result = assess_parameter_change_set(_review(), [_parameter_action("outer_diameter", 50)])
    assert result["status"] == "warning"
    assert any("3~22" in item["message"] for item in result["issues"])


def _assert_invalid_coil_relationship_is_blocked() -> None:
    result = assess_parameter_change_set(_review(), [_parameter_action("active_coils", 13)])
    assert result["status"] == "blocked"
    assert any("有效圈数不能大于总圈数" in item["message"] for item in result["issues"])


def _assert_load_point_height_change_is_simulated() -> None:
    review = _review()
    result = assess_parameter_change_set(review, [_parameter_action("load_points.F1.height", 45)])
    assert result["status"] == "blocked"
    assert any("F1 的试验高度不能大于自由长度" in item["message"] for item in result["issues"])


def _assert_existing_end_condition_conflict_does_not_block_active_coils() -> None:
    review = _solid_height_review(total_coils=10, active_coils=8)
    result = assess_parameter_change_set(review, [_parameter_action("active_coils", 7)])
    assert result["status"] == "ready"
    assert result["issues"] == []
    assert any(
        item["fields"] == ["solid_height", "load_points.F2.height"] and "10.925" in item["message"]
        for item in result["existing_issues"]
    )


def _assert_new_end_condition_conflict_is_blocked() -> None:
    review = _solid_height_review(total_coils=8, active_coils=7)
    result = assess_parameter_change_set(review, [_parameter_action("total_coils", 10)])
    assert result["status"] == "blocked"
    assert any(
        item["fields"] == ["solid_height", "load_points.F2.height"] and "10.925" in item["message"]
        for item in result["issues"]
    )


def _assert_agent_attaches_blocking_validation() -> None:
    review = _review()
    payload = chat_about_standardization(review, "外径改成3mm")
    action = payload["suggested_actions"][0]
    assert action["validation"]["status"] == "blocked"
    assert action["metadata"]["feasibility_can_apply"] is False
    assert payload["proposal_validation"]["status"] == "blocked"
    assert "变更预检未通过" in payload["reply"]


def _parameter_action(target_field: str, value: float) -> dict:
    return {
        "type": "propose_parameter_patch",
        "target_field": target_field,
        "proposed_value": value,
    }


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "standard_selection": {"selected_standard": "GB/T 1239.2-2009"},
        "spring_parameters": {
            "wire_diameter": {"value": 2, "unit": "mm"},
            "outer_diameter": {"value": 20, "unit": "mm"},
            "free_length": {"value": 40, "unit": "mm"},
            "total_coils": {"value": 12, "unit": "turns"},
            "active_coils": {"value": 10, "unit": "turns"},
            "end_grinding": {"value": "两端磨平"},
            "load_points": [{"label": "F1", "height": 25, "force": 100}],
        },
        "standardization_results": [],
        "derived_parameters": {},
    }


def _solid_height_review(total_coils: float, active_coils: float) -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "standard_selection": {"selected_standard": "GB/T 1239.2-2009"},
        "spring_parameters": {
            "wire_diameter": {"value": 0.9, "unit": "mm", "tolerance_upper": 0.05},
            "outer_diameter": {"value": 8.25, "unit": "mm"},
            "free_length": {"value": 30.25, "unit": "mm"},
            "total_coils": {"value": total_coils, "unit": "turns"},
            "active_coils": {"value": active_coils, "unit": "turns"},
            "end_grinding": {"value": "不磨"},
            "load_points": [{"label": "F2", "height": 9.668, "force": 35}],
        },
    }


if __name__ == "__main__":
    main()
