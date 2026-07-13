from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardization_chat_agent import chat_about_standardization
from ai_design_review.standardization_chat_llm import StandardizationChatLLMEngine


def main() -> None:
    _assert_llm_engine_returns_structured_actions()
    _assert_llm_engine_returns_full_plan_tolerance_actions()
    _assert_unchanged_load_value_action_becomes_tolerance_patch()
    _assert_agent_uses_llm_when_requested()
    print("standardization chat llm test passed")


def _assert_llm_engine_returns_structured_actions() -> None:
    seen_request = {}

    def fake_completion(request: dict) -> dict:
        seen_request.update(request)
        assert "outer_diameter" in request["allowed_target_fields"]
        assert "load_points.F1.force" in request["allowed_target_fields"]
        return {
            "reply": "外径和载荷都可以作为修改意图处理，但需要人工确认后再写回。",
            "intent": {
                "type": "multi_constraint_change_request",
                "target_field": "outer_diameter",
                "target_fields": ["outer_diameter", "load_points.F1.force"],
                "status": "proposal_ready",
                "constraints": ["free_length unchanged"],
                "affected_fields": ["mean_diameter", "spring_index", "load_tolerance"],
            },
            "suggested_actions": [
                {
                    "type": "propose_parameter_patch",
                    "target_field": "outer_diameter",
                    "proposed_value": 22,
                    "unit": "mm",
                    "reason": "用户要求外径偏小，需要调大。",
                    "affected_fields": ["mean_diameter", "spring_index"],
                }
            ],
            "references": [{"chunk_id": "gbt_1239_2_2009__diameter_tolerance__table_3_11", "table_no": "表3-11"}],
        }

    payload = StandardizationChatLLMEngine(completion_fn=fake_completion).chat(
        _review(),
        "外径太小了，载荷也偏低，能不能在自由长不变的情况下调一下？",
        {"intent": {"target_field": "outer_diameter"}},
    )
    assert seen_request["chunks"]
    assert payload["llm_chat"]["status"] == "generated"
    assert payload["intent"]["type"] == "multi_constraint_change_request"
    assert payload["intent"]["target_fields"] == ["outer_diameter", "load_points.F1.force"]
    assert payload["suggested_actions"][0]["apply_policy"] == "manual_confirm_required"
    assert payload["suggested_actions"][0]["metadata"]["target_field_valid"] is True


def _assert_llm_engine_returns_full_plan_tolerance_actions() -> None:
    seen_request = {}

    def fake_completion(request: dict) -> dict:
        seen_request.update(request)
        assert request["rule_result"]["intent"]["type"] == "full_standardization_plan"
        assert "free_length" in request["rule_result"]["intent"]["target_fields"]
        return {
            "reply": "已根据手册依据形成完整标准化方案，以下公差建议需要人工确认后写回。",
            "intent": {
                "type": "full_standardization_plan",
                "target_fields": ["outer_diameter", "free_length"],
                "status": "proposal_ready",
                "affected_fields": ["diameter_tolerance", "free_length_tolerance"],
            },
            "suggested_actions": [
                {
                    "type": "propose_tolerance_patch",
                    "target_field": "free_length",
                    "suggested_tolerance_upper": 0.9,
                    "suggested_tolerance_lower": -0.9,
                    "unit": "mm",
                    "reason": "依据自由长度公差表。",
                    "affected_fields": ["free_length_tolerance"],
                }
            ],
            "references": [{"chunk_id": "gbt_1239_2_2009__free_length_tolerance__table_3_12", "table_no": "表3-12"}],
        }

    rule_result = {
        "intent": {
            "type": "full_standardization_plan",
            "target_fields": ["outer_diameter", "free_length", "total_coils"],
            "status": "manual_apply_required",
        }
    }
    payload = StandardizationChatLLMEngine(completion_fn=fake_completion).chat(
        _review(),
        "请根据标准化手册推荐完整标准化方案",
        rule_result,
    )
    action = payload["suggested_actions"][0]
    assert seen_request["chunks"]
    assert payload["intent"]["type"] == "full_standardization_plan"
    assert action["type"] == "propose_tolerance_patch"
    assert action["suggested_tolerance_upper"] == 0.9
    assert action["apply_policy"] == "manual_confirm_required"
    assert action["metadata"]["action_type_valid"] is True
    assert action["metadata"]["target_field_valid"] is True


def _assert_unchanged_load_value_action_becomes_tolerance_patch() -> None:
    review = _review()
    review["spring_parameters"]["load_points"][0].update({
        "force_tolerance_percent": 10,
        "load_tolerance_percent": 10,
    })
    review["standardization_results"].append({
        "target_field": "load_points.F1.force",
        "suggested_value": 100,
        "suggested_tolerance_upper": 5,
        "suggested_tolerance_lower": -5,
        "unit": "N",
        "standard_no": "GB/T 1239.2-2009",
        "rule_id": "GBT1239.2-LOAD",
        "basis": "表3-15：1级，负荷极限偏差 ±5%F。",
        "status": "suggested",
    })

    def fake_completion(_: dict) -> dict:
        return {
            "reply": "负荷保持不变，按1级推荐负荷公差。",
            "intent": {"type": "full_standardization_plan", "target_fields": ["load_points.F1.force"], "status": "proposal_ready"},
            "suggested_actions": [{
                "type": "propose_parameter_patch",
                "target_field": "load_points.F1.force",
                "proposed_value": 100,
                "unit": "N",
                "reason": "按表3-15推荐 ±5%F。",
            }],
        }

    payload = StandardizationChatLLMEngine(completion_fn=fake_completion).chat(
        review,
        "请按1级标准化负荷公差",
        {"intent": {"type": "full_standardization_plan"}},
    )
    action = payload["suggested_actions"][0]
    assert action["type"] == "propose_tolerance_patch"
    assert action["suggested_tolerance_upper"] == 5
    assert action["suggested_tolerance_lower"] == -5
    assert action["metadata"]["normalized_from_unchanged_force_patch"] is True


def _assert_agent_uses_llm_when_requested() -> None:
    class FakeEngine:
        def chat(self, review: dict, message: str, rule_result: dict) -> dict:
            return {
                "reply": "LLM 已理解为外径调整建议，暂不自动写回。",
                "intent": {
                    "type": "parameter_change_request",
                    "target_field": "outer_diameter",
                    "target_fields": ["outer_diameter"],
                    "status": "proposal_ready",
                    "affected_fields": ["mean_diameter", "spring_index"],
                },
                "suggested_actions": [
                    {
                        "type": "propose_parameter_patch",
                        "target_field": "outer_diameter",
                        "proposed_value": 22,
                        "apply_policy": "manual_confirm_required",
                    }
                ],
                "references": [],
                "diagnostics": [],
                "llm_chat": {"status": "generated", "model": "fake", "duration_ms": 1},
            }

    review = _review()
    payload = chat_about_standardization(review, "外径太小了", use_llm=True, llm_engine=FakeEngine())
    assert payload["llm_chat"]["status"] == "generated"
    assert payload["intent"]["status"] == "proposal_ready"
    assert review["spring_parameters"]["outer_diameter"]["value"] == 20
    assert review["standardization_chat"][0]["llm_chat"]["status"] == "generated"


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
        "derived_parameters": {
            "mean_diameter": {"value": 18, "unit": "mm"},
            "spring_index": {"value": 9},
        },
        "standardization_results": [
            {
                "target_field": "outer_diameter",
                "suggested_value": 20,
                "suggested_tolerance_upper": 0.3,
                "suggested_tolerance_lower": -0.3,
                "unit": "mm",
                "standard_no": "GB/T 1239.2-2009",
                "rule_id": "GBT1239.2-DIA",
                "basis": "表3-11：C=9，2级。",
                "status": "suggested",
            }
        ],
    }


if __name__ == "__main__":
    main()
