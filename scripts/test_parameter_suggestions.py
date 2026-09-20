from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.parameter_suggestions import (  # noqa: E402
    build_parameter_suggestions,
    dependency_snapshot,
    dependency_token,
)
from ai_design_review.spring_feasibility import assess_parameter_reasonableness  # noqa: E402


def main() -> None:
    _assert_formula_suggestions_do_not_mutate_manual_values()
    _assert_matching_formula_is_informational_even_when_parameter_is_pending()
    _assert_applied_formula_reappears_after_manual_change()
    _assert_recognized_matching_values_are_verifications()
    _assert_standardization_conflicts_and_stale_status()
    _assert_applied_standardization_reappears_after_manual_change()
    _assert_identical_formula_and_standardization_suggestions_share_application()
    _assert_non_actionable_standardization_result_is_diagnostic_only()
    _assert_unique_system_standard_can_be_applied_with_other_suggestions()
    _assert_dependency_token_changes_with_formula_input()
    print("parameter suggestion tests passed")


def _review() -> dict:
    def param(value, unit="mm", **extra):
        return {
            "value": value,
            "unit": unit,
            "need_human_review": False,
            "source": ["human_confirmed"],
            **extra,
        }

    return {
        "review_revision": 7,
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_parameters": {
            "material": param("SUS304", ""),
            "wire_diameter": param(3, tolerance_upper=0.05, tolerance_lower=-0.05),
            "outer_diameter": param(32),
            "inner_diameter": param(26),
            "mean_diameter": param(29),
            "free_length": param(50),
            "solid_height": param(35),
            "total_coils": param(9, "turns"),
            "active_coils": param(4, "turns"),
            "end_type": param("两端并紧", ""),
            "end_grinding": param("两端不磨削", ""),
            "spring_rate": param(8.5, "N/mm"),
            "load_points": [],
        },
        "spring_features": {},
        "standardization_results": [],
    }


def _by_rule(suggestions: list[dict], rule_id: str) -> dict:
    return next(item for item in suggestions if item["rule_id"] == rule_id)


def _assert_formula_suggestions_do_not_mutate_manual_values() -> None:
    review = _review()
    before = deepcopy(review["spring_parameters"])
    assessment = assess_parameter_reasonableness(review, based_on_revision=7)
    assert review["spring_parameters"] == before
    solid = _by_rule(assessment["suggestions"], "FORMULA-SOLID-HEIGHT")
    assert solid["current_value"] == 35
    assert solid["suggested_value"] == 32.025
    assert solid["status"] == "available"
    assert solid["application_mode"] == "value"
    assert solid["source_fields"] == ["total_coils", "wire_diameter", "end_grinding"]
    assert solid["based_on_revision"] == 7
    assert solid["dependency_token"].startswith("fnv1a32:")
    assert _by_rule(assessment["suggestions"], "FORMULA-SPRING-INDEX")["status"] == "informational"


def _assert_matching_formula_is_informational_even_when_parameter_is_pending() -> None:
    review = _review()
    review["spring_parameters"]["solid_height"].update({
        "value": 32.025,
        "need_human_review": True,
        "source": ["formula_calculation"],
    })
    solid = _by_rule(build_parameter_suggestions(review), "FORMULA-SOLID-HEIGHT")
    assert solid["current_value"] == solid["suggested_value"] == 32.025
    assert solid["status"] == "informational"


def _assert_applied_formula_reappears_after_manual_change() -> None:
    review = _review()
    first = _by_rule(build_parameter_suggestions(review), "FORMULA-SOLID-HEIGHT")
    review["spring_parameters"]["solid_height"].update({
        "value": first["suggested_value"],
        "last_applied_suggestion_id": first["suggestion_id"],
    })
    matching = _by_rule(build_parameter_suggestions(review), "FORMULA-SOLID-HEIGHT")
    assert matching["status"] == "informational"

    # A stale audit marker must never suppress the recommendation when the
    # current value is edited away from the formula result.
    review["spring_parameters"]["solid_height"]["value"] = 35
    changed = _by_rule(build_parameter_suggestions(review), "FORMULA-SOLID-HEIGHT")
    assert changed["suggestion_id"] == first["suggestion_id"]
    assert changed["current_value"] == 35
    assert changed["status"] == "available"


def _assert_recognized_matching_values_are_verifications() -> None:
    review = _review()
    parameters = review["spring_parameters"]
    parameters["material"]["value"] = "65Mn弹簧钢丝"
    parameters["wire_diameter"].update({"value": 2, "tolerance_upper": None, "tolerance_lower": None})
    parameters["outer_diameter"]["value"] = 28
    parameters["inner_diameter"].update({"value": 24, "need_human_review": True, "source": ["formula_calculation"]})
    parameters["mean_diameter"].update({"value": 26, "need_human_review": True, "source": ["formula_calculation"]})
    parameters["free_length"]["value"] = 80
    parameters["solid_height"].update({"value": 18, "need_human_review": True, "source": ["formula_calculation"]})
    parameters["total_coils"]["value"] = 9
    parameters["active_coils"].update({"value": 7, "need_human_review": True, "source": ["formula_calculation"]})
    parameters["end_type"]["value"] = "两端并紧"
    parameters["end_grinding"]["value"] = "两端磨削"
    parameters.pop("spring_rate", None)
    suggestions = build_parameter_suggestions(review)
    application_items = [item for item in suggestions if item["application_mode"] != "none"]
    assert application_items
    assert all(item["status"] == "informational" for item in application_items)


def _assert_standardization_conflicts_and_stale_status() -> None:
    review = _review()
    review["standardization_results"] = [
        {
            "target_field": "free_length",
            "suggested_value": 48,
            "unit": "mm",
            "rule_id": "FREE-A",
            "basis": "方案 A",
            "status": "suggested",
        },
        {
            "target_field": "free_length",
            "suggested_value": 52,
            "unit": "mm",
            "rule_id": "FREE-B",
            "basis": "方案 B",
            "status": "suggested",
        },
        {
            "target_field": "total_coils",
            "suggested_tolerance_upper": 0.25,
            "suggested_tolerance_lower": -0.25,
            "unit": "turns",
            "rule_id": "COILS",
            "basis": "圈数公差",
            "status": "stale",
        },
    ]
    suggestions = build_parameter_suggestions(review)
    free = [item for item in suggestions if item["target_field"] == "free_length" and item["source"] == "standardization"]
    assert len(free) == 2
    assert {item["status"] for item in free} == {"conflict"}
    coils = _by_rule(suggestions, "COILS")
    assert coils["status"] == "stale"
    assert coils["application_mode"] == "tolerance"


def _assert_applied_standardization_reappears_after_manual_change() -> None:
    review = _review()
    review["standardization_results"] = [{
        "target_field": "free_length",
        "suggested_value": 48,
        "unit": "mm",
        "rule_id": "FREE-STANDARD",
        "basis": "标准推荐自由长度。",
        "status": "human_confirmed",
    }]
    review["spring_parameters"]["free_length"].update({
        "value": 48,
        "last_applied_suggestion_id": "historical-application",
    })
    matching = _by_rule(build_parameter_suggestions(review), "FREE-STANDARD")
    assert matching["status"] == "informational"

    review["spring_parameters"]["free_length"]["value"] = 50
    changed = _by_rule(build_parameter_suggestions(review), "FREE-STANDARD")
    assert changed["current_value"] == 50
    assert changed["suggested_value"] == 48
    assert changed["status"] == "available"


def _assert_dependency_token_changes_with_formula_input() -> None:
    review = _review()
    fields = ["total_coils", "wire_diameter", "end_grinding"]
    first = dependency_token(dependency_snapshot(review["spring_parameters"], fields))
    review["spring_parameters"]["total_coils"]["value"] = 10
    second = dependency_token(dependency_snapshot(review["spring_parameters"], fields))
    assert first != second


def _assert_non_actionable_standardization_result_is_diagnostic_only() -> None:
    review = _review()
    review["standardization_results"] = [{
        "target_field": "perpendicularity",
        "suggested_value": None,
        "suggested_tolerance_upper": None,
        "suggested_tolerance_lower": None,
        "rule_id": "PERP-CONTEXT",
        "basis": "缺少垂直度等级。",
        "status": "need_context",
        "metadata": {"missing_fields": ["accuracy_grade"]},
    }]
    assessment = assess_parameter_reasonableness(review)
    assert not any(item.get("rule_id") == "PERP-CONTEXT" for item in assessment["suggestions"])
    diagnostic = next(item for item in assessment["issues"] if item.get("rule_id") == "PERP-CONTEXT")
    assert diagnostic["severity"] == "needs_input"
    assert diagnostic["fields"] == ["accuracy_grade"]


def _assert_unique_system_standard_can_be_applied_with_other_suggestions() -> None:
    review = _review()
    review["spring_parameters"]["standard_no"] = {"value": None, "need_human_review": True, "source": []}
    review["standard_selection"] = {
        "selected_standard": "GB/T 1239.2-2009",
        "rules_available": True,
        "metadata": {"conflicts": []},
    }
    review["standardization_results"] = [{
        "target_field": "standard_no",
        "suggested_value": "GB/T 1239.2-2009",
        "rule_id": "GBT1239.2-CTX",
        "status": "need_context",
        "metadata": {"source_fields": ["standard_no", "wire_diameter"]},
    }]
    suggestion = _by_rule(build_parameter_suggestions(review), "GBT1239.2-CTX")
    assert suggestion["status"] == "available"
    assert suggestion["based_on_revision"] == 7
    assert suggestion["current_value"] is None
    assert suggestion["suggested_value"] == "GB/T 1239.2-2009"

    review["standard_selection"]["metadata"]["conflicts"] = ["制造方式存在冲突"]
    assert _by_rule(build_parameter_suggestions(review), "GBT1239.2-CTX")["status"] == "informational"
    review["standard_selection"]["metadata"]["conflicts"] = []
    review["standardization_results"].append({
        "target_field": "standard_no",
        "suggested_value": "GB/T 23934-2015",
        "rule_id": "OTHER-STANDARD",
        "status": "need_context",
    })
    assert _by_rule(build_parameter_suggestions(review), "GBT1239.2-CTX")["status"] == "informational"


def _assert_identical_formula_and_standardization_suggestions_share_application() -> None:
    review = _review()
    review["spring_parameters"]["solid_height"]["value"] = 32.025
    review["standardization_results"] = [{
        "target_field": "solid_height",
        "suggested_value": 32.025,
        "unit": "mm",
        "rule_id": "STANDARD-SOLID-HEIGHT",
        "basis": "标准公式与确定性公式一致。",
        "status": "suggested",
    }]
    suggestion = _by_rule(build_parameter_suggestions(review), "FORMULA-SOLID-HEIGHT")
    assert suggestion["supporting_sources"] == ["formula", "standardization"]
    assert suggestion["standardization_result_indexes"] == [0]
    assert suggestion["status"] == "informational"


if __name__ == "__main__":
    main()
