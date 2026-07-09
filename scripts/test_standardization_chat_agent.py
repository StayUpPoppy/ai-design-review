from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardization_chat_agent import chat_about_standardization


def main() -> None:
    _assert_explains_existing_standardization_result()
    _assert_asks_for_missing_target_value()
    _assert_proposes_patch_without_applying()
    _assert_detects_full_plan_without_hardcoded_actions()
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
    assert "暂不自动写回" in payload["reply"]


def _assert_detects_full_plan_without_hardcoded_actions() -> None:
    review = _review()
    payload = chat_about_standardization(review, "请根据标准化手册推荐完整标准化方案")
    assert payload["intent"]["type"] == "full_standardization_plan"
    assert payload["intent"]["status"] == "manual_apply_required"
    assert "outer_diameter" in payload["intent"]["target_fields"]
    assert payload["suggested_actions"] == []
    assert "LLM理解" in payload["reply"]


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
    assert "没有生成多字段方案" in payload["reply"]


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
