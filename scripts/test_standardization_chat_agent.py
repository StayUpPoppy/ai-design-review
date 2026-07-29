from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardization_chat_agent import (
    chat_about_standardization,
    standardization_chat_context_needs_refresh,
)


def main() -> None:
    _assert_explains_existing_standardization_result()
    _assert_asks_for_missing_target_value()
    _assert_proposes_patch_without_applying()
    _assert_detects_full_plan_without_hardcoded_actions()
    _assert_requests_missing_context_before_full_plan()
    _assert_recognizes_natural_standardization_request()
    _assert_uses_pending_question_to_parse_a_direct_value()
    _assert_proposes_load_point_height_patch()
    _assert_proposes_load_point_force_patch()
    _assert_proposes_multiple_structured_supplements()
    _assert_context_refresh_detects_missing_or_stale_results()
    _assert_full_plan_timeout_fallback_is_explicit()
    print("standardization chat agent test passed")


def _assert_explains_existing_standardization_result() -> None:
    review = _review()
    payload = chat_about_standardization(review, "为什么自由长度公差是±0.9")
    assert payload["intent"]["type"] == "explanation"
    assert payload["intent"]["target_field"] == "free_length"
    assert "表3-12" in payload["reply"]
    assert review["standardization_chat"]


def _assert_asks_for_missing_target_value() -> None:
    review = _review()
    payload = chat_about_standardization(review, "外径太小了")
    assert payload["intent"]["type"] == "parameter_change_request"
    assert payload["intent"]["target_field"] == "outer_diameter"
    assert payload["intent"]["status"] == "need_clarification"
    assert "缺少目标值" in payload["reply"]


def _assert_proposes_patch_without_applying() -> None:
    review = _review()
    payload = chat_about_standardization(review, "外径改成22mm，其他尽量不变")
    action = payload["suggested_actions"][0]
    assert payload["intent"]["status"] == "proposal_ready"
    assert action["target_field"] == "outer_diameter"
    assert action["proposed_value"] == 22
    assert action["unit"] == "mm"
    assert review["spring_parameters"]["outer_diameter"]["value"] == 20
    assert "不会自动写回" in payload["reply"]
    assert action["validation"]["status"] == "ready"


def _assert_detects_full_plan_without_hardcoded_actions() -> None:
    review = _review()
    payload = chat_about_standardization(review, "请根据标准化手册推荐完整标准化方案")
    assert payload["intent"]["type"] == "full_standardization_plan"
    assert payload["intent"]["status"] == "manual_apply_required"
    assert "outer_diameter" in payload["intent"]["target_fields"]
    assert payload["suggested_actions"] == []
    assert "当前参数" in payload["reply"]


def _assert_requests_missing_context_before_full_plan() -> None:
    review = _review()
    review["standardization_results"] = [
        {
            "target_field": "load_points",
            "rule_id": "GBT1239.2-LOAD",
            "basis": "缺少载荷精度等级或有效圈数，无法计算指定高度负荷极限偏差。",
            "status": "need_context",
            "metadata": {"missing_fields": ["active_coils"]},
        },
        {
            "target_field": "solid_height",
            "rule_id": "GBT1239.2-SOLID",
            "basis": "缺少端面磨削方式，无法选择压并高度参考公式。",
            "status": "need_context",
            "metadata": {"missing_fields": ["end_grinding"]},
        },
    ]
    payload = chat_about_standardization(review, "请根据标准化手册推荐完整标准化方案", use_llm=True)
    assert payload["intent"]["type"] == "missing_context"
    assert payload["intent"]["status"] == "need_input"
    assert [action["target_field"] for action in payload["suggested_actions"]] == ["active_coils", "end_grinding"]
    assert all(action["type"] == "request_missing_field" for action in payload["suggested_actions"])
    assert "llm_chat" not in payload


def _assert_recognizes_natural_standardization_request() -> None:
    review = _review()
    review["standardization_results"] = [
        {
            "target_field": "load_points",
            "rule_id": "GBT1239.2-LOAD",
            "basis": "缺少有效圈数，无法计算指定高度负荷极限偏差。",
            "status": "need_context",
            "metadata": {"missing_fields": ["active_coils"]},
        }
    ]
    payload = chat_about_standardization(review, "请按照标准手册进行标准化", use_llm=True)
    assert payload["intent"]["type"] == "missing_context"
    assert payload["intent"]["status"] == "need_input"
    assert [action["target_field"] for action in payload["suggested_actions"]] == ["active_coils"]
    assert "llm_chat" not in payload


def _assert_uses_pending_question_to_parse_a_direct_value() -> None:
    review = _review()
    review["standardization_chat"] = [
        {
            "suggested_actions": [
                {"type": "request_missing_field", "target_field": "active_coils", "status": "need_input"},
            ]
        }
    ]
    payload = chat_about_standardization(review, "8")
    assert payload["intent"]["type"] == "parameter_change_request"
    assert payload["intent"]["target_field"] == "active_coils"
    assert payload["suggested_actions"][0]["proposed_value"] == 8


def _assert_proposes_load_point_height_patch() -> None:
    review = _review()
    payload = chat_about_standardization(review, "将H1改为18mm")
    action = payload["suggested_actions"][0]
    assert action["target_field"] == "load_points.F1.height"
    assert action["proposed_value"] == 18
    assert action["unit"] == "mm"


def _assert_proposes_load_point_force_patch() -> None:
    review = _review()
    payload = chat_about_standardization(review, "将F1力值改为120N")
    action = payload["suggested_actions"][0]
    assert action["target_field"] == "load_points.F1.force"
    assert action["proposed_value"] == 120
    assert action["unit"] == "N"


def _assert_proposes_multiple_structured_supplements() -> None:
    review = _review()
    review["spring_parameters"]["active_coils"] = {"value": None, "unit": "turns"}
    review["spring_parameters"]["end_grinding"] = {"value": None, "unit": ""}
    payload = chat_about_standardization(
        review,
        "supplement active coils and end grinding",
        supplements={"active_coils": "8", "end_grinding": "两端磨平"},
        use_llm=True,
    )
    assert payload["intent"]["type"] == "batch_parameter_supplement"
    assert payload["intent"]["status"] == "proposal_ready"
    assert [action["target_field"] for action in payload["suggested_actions"]] == [
        "active_coils",
        "end_grinding",
    ]
    assert [action["proposed_value"] for action in payload["suggested_actions"]] == [8, "两端磨削"]
    assert "llm_chat" not in payload
    assert review["spring_parameters"]["active_coils"]["value"] is None


def _assert_context_refresh_detects_missing_or_stale_results() -> None:
    missing = _review()
    missing["standardization_results"] = []
    context = standardization_chat_context_needs_refresh(missing, "请根据标准化手册推荐完整标准化方案")
    assert context["required"] is True
    assert "missing_standardization_results" in context["reasons"]

    stale = _review()
    stale["standardization_results"][0]["status"] = "stale"
    context = standardization_chat_context_needs_refresh(stale, "外径改成22mm")
    assert context["required"] is True
    assert "stale_parameters_or_results" in context["reasons"]


def _assert_full_plan_timeout_fallback_is_explicit() -> None:
    class TimeoutEngine:
        def chat(self, review: dict, message: str, rule_result: dict) -> dict:
            raise TimeoutError("simulated timeout")

    review = _review()
    payload = chat_about_standardization(
        review,
        "请根据标准化手册推荐完整标准化方案",
        use_llm=True,
        llm_engine=TimeoutEngine(),
    )
    assert payload["intent"]["type"] == "full_standardization_plan"
    assert payload["suggested_actions"] == []
    assert payload["llm_chat"]["status"] == "failed"
    assert "自动更新本地标准化建议" in payload["reply"]


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_features": {
            "spring_family": {"value": "helical"},
            "spring_shape": {"value": "cylindrical"},
            "manufacturing_method": {"value": "cold_coiled"},
            "wire_section": {"value": "round"},
            "pitch_type": {"value": "constant"},
        },
        "standard_selection": {
            "selected_standard": "GB/T 1239.2-2009",
            "status": "applicable",
        },
        "spring_parameters": {
            "wire_diameter": {"value": 2, "unit": "mm"},
            "outer_diameter": {"value": 20, "unit": "mm"},
            "free_length": {"value": 30, "unit": "mm"},
            "total_coils": {"value": 12, "unit": "turns"},
            "accuracy_grade": {"value": "2级"},
            "load_points": [{"label": "F1", "height": 20, "force": 100}],
        },
        "standardization_results": [
            {
                "target_field": "free_length",
                "suggested_value": 30,
                "suggested_tolerance_upper": 0.9,
                "suggested_tolerance_lower": -0.9,
                "unit": "mm",
                "standard_no": "GB/T 1239.2-2009",
                "rule_id": "GBT1239.2-FREE",
                "basis": "表3-12：C=9，2级，±max(0.03H0, 0.5mm)。",
                "status": "suggested",
                "need_human_review": True,
            }
        ],
    }


if __name__ == "__main__":
    main()
