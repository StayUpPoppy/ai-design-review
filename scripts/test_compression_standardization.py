from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.io_utils import project_path, read_json
from ai_design_review.standardizers.compression import standardize_compression_spring
from ai_design_review.workflow import DrawingReviewWorkflow, apply_standardization_to_review


def main() -> None:
    _assert_derived_parameters()
    _assert_gbt_1239_2_suggestions()
    _assert_missing_grade_requires_human_review()
    _assert_workflow_defaults_accuracy_and_standardizes()
    _assert_workflow_can_defer_standardization()
    print("compression standardization test passed")


def _base_parameters() -> dict:
    return {
        "wire_diameter": {"value": 2, "unit": "mm", "tolerance_upper": 0.05, "tolerance_lower": -0.05},
        "outer_diameter": {"value": 20, "unit": "mm"},
        "free_length": {"value": 30, "unit": "mm"},
        "total_coils": {"value": 12, "unit": "turns"},
        "active_coils": {"value": 8, "unit": "turns"},
        "accuracy_grade": {"value": "2级"},
        "diameter_accuracy_grade": {"value": "1级"},
        "free_length_accuracy_grade": {"value": "2级"},
        "load_accuracy_grade": {"value": "1级"},
        "stiffness_accuracy_grade": {"value": "3级"},
        "end_grinding": {"value": "两端磨平"},
        "spring_rate": {"value": 5, "unit": "N/mm"},
        "load_points": [
            {"label": "F1", "height": 20, "height_unit": "mm", "force": 100, "force_unit": "N"},
        ],
    }


def _assert_derived_parameters() -> None:
    payload = standardize_compression_spring(_base_parameters())
    derived = payload["derived_parameters"]
    assert derived["mean_diameter"]["value"] == 18
    assert derived["spring_index"]["value"] == 9
    assert derived["slenderness_ratio"]["value"] == 1.6667
    assert derived["load_point_deflections"][0]["deflection"] == 10


def _assert_gbt_1239_2_suggestions() -> None:
    payload = standardize_compression_spring(_base_parameters())
    results = {item["rule_id"]: item for item in payload["standardization_results"]}
    assert results["GBT1239.2-DIA"]["suggested_tolerance_upper"] == 0.3
    assert results["GBT1239.2-FREE"]["suggested_tolerance_upper"] == 0.9
    assert results["GBT1239.2-COILS"]["suggested_tolerance_upper"] == 0.5
    assert results["GBT1239.2-PERP"]["suggested_value"] == 1.5
    assert results["GBT1239.2-SOLID"]["suggested_value"] == 24.6
    assert results["GBT1239.2-STIFF"]["suggested_tolerance_upper"] == 0.75

    load = next(item for item in payload["standardization_results"] if item["target_field"] == "load_points.F1.force")
    assert load["suggested_tolerance_upper"] == 5
    assert load["suggested_tolerance_lower"] == -5


def _assert_missing_grade_requires_human_review() -> None:
    parameters = _base_parameters()
    for field in (
        "accuracy_grade",
        "diameter_accuracy_grade",
        "free_length_accuracy_grade",
        "load_accuracy_grade",
        "stiffness_accuracy_grade",
    ):
        parameters.pop(field, None)
    results = standardize_compression_spring(parameters)["standardization_results"]
    diameter = next(item for item in results if item["rule_id"] == "GBT1239.2-DIA")
    free_length = next(item for item in results if item["rule_id"] == "GBT1239.2-FREE")
    assert diameter["status"] == "need_context"
    assert diameter["need_human_review"] is True
    assert free_length["status"] == "need_context"
    assert free_length["need_human_review"] is True
    assert all("2级" not in str(item.get("basis", "")) for item in results if item["status"] == "need_context")


def _assert_workflow_defaults_accuracy_and_standardizes() -> None:
    rules = read_json(project_path("config", "factory_rules.json"))
    workflow = DrawingReviewWorkflow(rules)
    result = workflow.run(
        None,
        [
            _candidate("drawing_name", "压缩弹簧", confidence=0.96),
            _candidate("material", "SUS304", confidence=0.96),
            _candidate("wire_diameter", 1.5, unit="mm", confidence=0.96),
            _candidate("outer_diameter", 25, unit="mm", confidence=0.9),
            _candidate("free_length", 15, unit="mm", confidence=0.9),
            _candidate("total_coils", 4, unit="turns", confidence=0.9),
            _candidate("active_coils", 3, unit="turns", confidence=0.9),
            _candidate("handedness", "右旋", confidence=0.9),
            _candidate("end_grinding", "两端磨平", confidence=0.86),
            {
                "field": "load_point",
                "value": {
                    "label": "F1",
                    "height": 11,
                    "height_unit": "mm",
                    "force": 10,
                    "force_unit": "N",
                },
                "source": "test",
                "evidence": "F1=10N",
                "confidence": 0.9,
                "page": 1,
            },
        ],
    )
    accuracy = result["spring_parameters"]["accuracy_grade"]
    assert accuracy["value"] == "2级"
    assert accuracy["default_source"] == "company_default"
    assert accuracy["need_human_review"] is True
    selection = result["standard_selection"]
    assert selection["selected_standard"] == "GB/T 1239.2-2009"
    assert selection["selection_source"] == "wire_diameter_threshold"
    assert selection["metadata"]["wire_diameter_mm"] == 1.5
    results = {item["rule_id"]: item for item in result["standardization_results"]}
    assert results["GBT1239.2-DIA"]["status"] == "suggested"
    assert results["GBT1239.2-DIA"]["need_human_review"] is True
    assert results["GBT1239.2-DIA"]["metadata"]["accuracy_grade_source"] == "company_default"
    assert "公司默认2级" in results["GBT1239.2-DIA"]["basis"]


def _assert_workflow_can_defer_standardization() -> None:
    rules = read_json(project_path("config", "factory_rules.json"))
    workflow = DrawingReviewWorkflow(rules)
    result = workflow.run(
        None,
        [
            _candidate("drawing_name", "压缩弹簧", confidence=0.96),
            _candidate("material", "SUS304", confidence=0.96),
            _candidate("wire_diameter", 1.5, unit="mm", confidence=0.96),
            _candidate("outer_diameter", 25, unit="mm", confidence=0.9),
            _candidate("free_length", 15, unit="mm", confidence=0.9),
            _candidate("total_coils", 4, unit="turns", confidence=0.9),
            _candidate("handedness", "右旋", confidence=0.9),
        ],
        run_standardization=False,
    )
    assert result["standard_selection"]["status"] == "not_started"
    assert result["standardization_results"] == []
    assert result["derived_parameters"] == {}

    apply_standardization_to_review(result)
    assert result["standard_selection"]["selected_standard"] == "GB/T 1239.2-2009"
    assert result["standard_selection"]["selection_source"] == "wire_diameter_threshold"
    assert result["derived_parameters"]["mean_diameter"]["value"] == 23.5
    assert any(item["rule_id"] == "GBT1239.2-DIA" for item in result["standardization_results"])


def _candidate(field: str, value, *, unit: str | None = None, confidence: float = 0.9) -> dict:
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "source": "test",
        "evidence": f"{field}={value}",
        "confidence": confidence,
        "page": 1,
    }


if __name__ == "__main__":
    main()
