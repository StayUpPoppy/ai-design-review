from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardization_chat_agent import (
    chat_about_standardization,
    parse_accuracy_standardization_request,
    parse_generation_package_export_request,
    select_general_accuracy_grade,
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
    _assert_accuracy_standardization_intent_variants()
    _assert_accuracy_standardization_rejects_ambiguous_or_specialized_requests()
    _assert_accuracy_standardization_selects_only_general_grade()
    _assert_generation_package_export_intent_variants()
    _assert_generation_package_export_readiness_gate()
    _assert_generation_package_export_llm_fallback_is_deterministic()
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
    assert action["impact_preview"]["status"] == "ready"
    assert action["impact_preview"]["generation_readiness"]["parameter_package_changed"] is True
    assert payload["impact_preview"] == payload["turn"]["impact_preview"]
    assert payload["turn"]["suggested_actions"][0]["impact_preview"]["baseline_state"]


def _assert_detects_full_plan_without_hardcoded_actions() -> None:
    review = _review()
    payload = chat_about_standardization(review, "请根据标准化手册推荐完整标准化方案")
    assert payload["intent"]["type"] == "full_standardization_plan"
    assert payload["intent"]["status"] == "manual_apply_required"
    assert "outer_diameter" in payload["intent"]["target_fields"]
    assert payload["suggested_actions"] == []
    assert "当前参数" in payload["reply"]
    assert payload["standardization_batch"]["applicable_count"] == 1
    assert payload["turn"]["standardization_batch"]["items"][0]["label"] == "自由长度"


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
    assert payload["impact_preview"]["impact_count"] >= 2
    assert all(action.get("impact_preview") for action in payload["suggested_actions"])


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


def _assert_accuracy_standardization_intent_variants() -> None:
    variants = {
        "按一级精度标准化": "1级",
        "按一級精度标准化": "1级",
        "使用二级精度重新出方案": "2级",
        "以2级精度重新生成方案": "2级",
        "以三级精度进行标准化": "3级",
        "以3级精度进行标准化": "3级",
    }
    for message, expected in variants.items():
        parsed = parse_accuracy_standardization_request(message)
        assert parsed and parsed["status"] == "ready", (message, parsed)
        assert parsed["requested_grade"] == expected

    review = _review()
    execution = {
        "status": "completed",
        "requested_grade": "1级",
        "previous_grade": "2级",
        "scope": "general",
        "selection_changed": True,
        "specialized_grades_retained": {},
        "standardization_result_count": 6,
        "warnings": [],
    }
    payload = chat_about_standardization(
        review,
        "按一级精度标准化",
        use_llm=True,
        accuracy_standardization=execution,
    )
    assert payload["intent"] == {
        "type": "accuracy_standardization_request",
        "target_field": "accuracy_grade",
        "target_fields": ["accuracy_grade"],
        "target_label": "通用精度等级",
        "status": "completed",
        "affected_fields": ["accuracy_grade", "standardization_results"],
    }
    assert payload["suggested_actions"] == []
    assert payload["accuracy_standardization"]["requested_grade"] == "1级"
    assert payload["turn"]["accuracy_standardization"] == payload["accuracy_standardization"]
    assert payload["standardization_batch"]["applicable_count"] == 1
    assert payload["turn"]["standardization_batch"]["batch_id"] == payload["standardization_batch"]["batch_id"]
    assert "llm_chat" not in payload


def _assert_accuracy_standardization_rejects_ambiguous_or_specialized_requests() -> None:
    assert parse_accuracy_standardization_request("一级和二级精度有什么区别") is None
    missing = parse_accuracy_standardization_request("按精度进行标准化")
    assert missing and missing["status"] == "need_clarification"
    multiple = parse_accuracy_standardization_request("按一级或二级精度标准化")
    assert multiple and multiple["status"] == "need_clarification"
    invalid = parse_accuracy_standardization_request("按四级精度标准化")
    assert invalid and invalid["status"] == "invalid_grade"
    specialized = parse_accuracy_standardization_request("直径按一级精度标准化")
    assert specialized and specialized["status"] == "specialized_not_supported"


def _assert_accuracy_standardization_selects_only_general_grade() -> None:
    review = _review()
    review["spring_parameters"]["accuracy_grade"].update(
        {"source": ["company_default"], "default_source": "company_default", "need_human_review": True}
    )
    review["spring_parameters"]["diameter_accuracy_grade"] = {"value": "2级", "need_human_review": False}
    result = select_general_accuracy_grade(review, "1级")
    general = review["spring_parameters"]["accuracy_grade"]
    assert general["value"] == "1级"
    assert general["source"] == ["human_selected"]
    assert general["need_human_review"] is False
    assert "default_source" not in general
    assert review["spring_parameters"]["diameter_accuracy_grade"]["value"] == "2级"
    assert result["specialized_grades_retained"] == {"diameter_accuracy_grade": "2级"}


def _assert_generation_package_export_intent_variants() -> None:
    for message in (
        "导出参数包",
        "帮我把生图参数导出来",
        "下载SolidWorks参数包",
        "生成一个生图参数文件",
    ):
        parsed = parse_generation_package_export_request(message)
        assert parsed and parsed["status"] == "execute", (message, parsed)
    assert parse_generation_package_export_request("参数包怎么导出")["status"] == "explain"
    assert parse_generation_package_export_request("能否下载生图参数包")["status"] == "query"
    assert parse_generation_package_export_request("导出确认版") is None


def _assert_generation_package_export_readiness_gate() -> None:
    review = _ready_export_review()
    payload = chat_about_standardization(
        review,
        "导出参数包",
        generation_package_export_source="server",
        generation_package_export_revision=9,
    )
    action = payload["generation_package_export"]
    assert payload["intent"]["type"] == "generation_package_export_request"
    assert action["status"] == "ready_with_warnings"
    assert action["can_download"] is True
    assert action["automatic_download"] is True
    assert action["source_mode"] == "server"
    assert action["review_revision"] == 9
    assert [item["field"] for item in action["parameter_fields"]] == [
        "wire_diameter", "mean_diameter", "free_length", "total_coils",
        "active_coils", "handedness", "end_grinding", "end_coils_closed",
    ]
    assert action["parameter_fields"][1]["value"] == 23
    assert action["baseline_state"]["technical_requirements"][0]["content"] == "两端磨平"
    assert payload["turn"]["generation_package_export"] == action

    blocked_review = _ready_export_review()
    blocked_review["spring_parameters"]["handedness"]["need_human_review"] = True
    blocked = chat_about_standardization(blocked_review, "下载生图参数")
    blocked_action = blocked["generation_package_export"]
    assert blocked_action["status"] == "needs_confirmation"
    assert blocked_action["can_download"] is False
    assert blocked_action["automatic_download"] is False
    assert any(item["field"] == "handedness" for item in blocked_action["pending_fields"])


def _assert_generation_package_export_llm_fallback_is_deterministic() -> None:
    class ExportIntentEngine:
        def chat(self, review: dict, message: str, rule_result: dict) -> dict:
            return {
                "reply": "准备导出。",
                "intent": {
                    "type": "generation_package_export_request",
                    "target_field": "",
                    "target_fields": [],
                    "target_label": "",
                    "status": "ready",
                    "affected_fields": [],
                },
                "suggested_actions": [],
                "references": [],
                "llm_chat": {"status": "generated"},
            }

    payload = chat_about_standardization(
        _ready_export_review(),
        "把要交给CAD那边的数据文件给我",
        use_llm=True,
        llm_engine=ExportIntentEngine(),
    )
    assert payload["generation_package_export"]["can_download"] is True
    assert payload["generation_package_export"]["source_mode"] == "local"
    assert "parameter_package" not in payload["generation_package_export"]
    assert payload["llm_chat"]["status"] == "generated"


def _ready_export_review() -> dict:
    confirmed = lambda value, unit=None: {"value": value, "unit": unit, "need_human_review": False}
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "standard_selection": {"selected_standard": None, "human_confirmed": False},
        "spring_parameters": {
            "wire_diameter": confirmed(3, "mm"),
            "mean_diameter": confirmed(23, "mm"),
            "free_length": confirmed(45, "mm"),
            "total_coils": confirmed(10),
            "active_coils": confirmed(8),
            "handedness": confirmed("right"),
            "end_grinding": confirmed(1),
            "end_coils_closed": confirmed(1),
        },
        "technical_requirements": [
            {"type": "process", "content": "两端磨平", "need_human_review": False},
        ],
        "standardization_results": [],
        "parameter_reasonableness": {"status": "ready", "issues": []},
    }


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
