from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .end_conditions import (
    END_GRINDING_GROUND,
    END_GRINDING_NOT_GROUND,
    END_TYPE_NOT_TIGHT,
    END_TYPE_TIGHT,
    normalize_end_grinding,
    normalize_end_type,
)
from .generation_contract import (
    COMPRESSION_GENERATION_INPUT_FIELDS,
    COMPRESSION_GENERATION_LABELS,
    GENERATION_SCHEMA_VERSION,
    generation_source_item,
)
from .generation_readiness import assess_generation_readiness
from .parameter_impact import assess_parameter_change_impact
from .parameter_change_proposal import (
    build_parameter_change_proposal,
    find_parameter_change_proposal,
    invalidate_open_parameter_change_proposals,
)
from .spring_feasibility import assess_parameter_change_set, assess_parameter_reasonableness
from .spring_templates import FIELD_LABELS
from .standard_knowledge import chunk_reference, retrieve_standard_chunks
from .standardization_batch import build_standardization_batch
from .standardization_chat_llm import StandardizationChatLLMEngine


FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "wire_diameter": ("线径", "钢丝直径", "丝径", "d"),
    "outer_diameter": ("外径", "外圈直径", "od"),
    "inner_diameter": ("内径", "id"),
    "mean_diameter": ("中径", "平均直径", "D"),
    "free_length": ("自由长度", "自由高度", "自由长", "H0"),
    "total_coils": ("总圈数", "圈数", "n1"),
    "active_coils": ("有效圈数", "工作圈数"),
    "support_coils": ("支承圈数", "支撑圈数", "单端支承圈数"),
    "solid_height": ("压并高度", "并紧高度"),
    "end_type": ("端部形式", "端圈压并", "端部", "端型", "不压并", "压并", "并紧", "不并紧", "闭口", "开口"),
    "handedness": ("旋向", "左旋", "右旋"),
    "end_grinding": ("端面磨削", "端面磨平", "两端磨平", "两端磨削", "两端不磨削", "磨平", "不磨"),
    "spring_rate": ("刚度", "弹簧刚度", "k"),
    "perpendicularity": ("垂直度",),
    "straightness": ("直线度",),
    "load_points": ("载荷", "负荷", "力值", "压力", "F1", "F2", "F3"),
    "accuracy_grade": ("精度", "精度等级", "等级"),
}

EXPLANATION_WORDS = ("为什么", "依据", "怎么", "如何", "怎么算", "哪里来", "来源", "标准", "公差")
CHANGE_WORDS = ("太小", "太大", "偏小", "偏大", "过小", "过大", "低了", "高了", "改", "调整", "设为", "设置", "换成", "增加", "减小", "降低", "提高", "不能超过", "不超过", "不得超过", "至少", "保持不变")
CONFIRM_WORDS = ("按你说", "就用", "确认", "应用", "采用", "可以")
FULL_PLAN_WORDS = (
    "完整标准化方案",
    "标准化方案",
    "完整方案",
    "整体标准化",
    "推荐进行标准化",
    "推荐标准化",
    "根据标准化手册",
    "根据手册",
    "按照标准手册",
    "按标准手册",
    "按手册",
    "进行标准化",
    "执行标准化",
    "帮我标准化",
    "开始标准化",
    "重新标准化",
)
GENERATION_READINESS_WORDS = ("可以重新生图", "能重新生图", "能生成图纸", "可以生成图纸", "还缺哪些参数", "还缺什么参数", "生成参数包", "图纸参数包", "生图参数")

REASONABLENESS_WORDS = ("不合理", "合理性", "是否合理", "哪些问题", "参数问题", "客户确认", "客户沟通", "图纸问题")

PLAN_TARGET_FIELDS = (
    "standard_no",
    "accuracy_grade",
    "wire_diameter",
    "outer_diameter",
    "inner_diameter",
    "mean_diameter",
    "free_length",
    "total_coils",
    "active_coils",
    "support_coils",
    "end_type",
    "end_grinding",
    "spring_rate",
    "perpendicularity",
    "straightness",
)

NUMERIC_SUPPLEMENT_FIELDS = {
    "wire_diameter",
    "outer_diameter",
    "inner_diameter",
    "mean_diameter",
    "free_length",
    "body_length",
    "solid_height",
    "total_coils",
    "active_coils",
    "end_coils",
    "support_coils",
    "pitch",
    "spring_rate",
    "perpendicularity",
    "straightness",
    "permanent_set_limit",
}

ACCURACY_GRADE_FIELDS = (
    "diameter_accuracy_grade",
    "free_length_accuracy_grade",
    "load_accuracy_grade",
    "stiffness_accuracy_grade",
)
ACCURACY_SPECIALIZED_TERMS = (
    "直径",
    "外径",
    "内径",
    "中径",
    "自由高度",
    "自由长度",
    "载荷",
    "负荷",
    "刚度",
)
ACCURACY_ACTION_TERMS = ("标准化", "重新出方案", "重新生成方案", "生成方案", "出方案")
ACCURACY_EXPLANATION_TERMS = ("区别", "差别", "不同", "哪个好", "如何选择", "什么意思", "是什么")
GENERATION_PACKAGE_EXPORT_ACTION_TERMS = ("导出", "下载", "保存", "生成文件", "生成", "导出来", "下下来")
GENERATION_PACKAGE_EXPORT_OBJECT_TERMS = (
    "参数包",
    "生图参数",
    "生成图纸参数",
    "solidworks参数",
    "solidworks建模参数",
    "solidworks 参数",
)
GENERATION_PACKAGE_EXPORT_EXPLANATION_TERMS = ("怎么", "如何", "在哪里", "去哪", "哪儿", "是什么", "什么意思")
GENERATION_PACKAGE_EXPORT_QUERY_TERMS = ("能不能", "能否", "是否可以", "可以吗", "能导出吗", "能下载吗")


def parse_accuracy_standardization_request(message: str) -> dict[str, Any] | None:
    """Parse an explicit general accuracy-standardization command without using an LLM."""

    text = str(message or "").strip()
    normalized = text.replace("級", "级").replace("壹", "一").replace("贰", "二").replace("叁", "三")
    has_action = any(term in normalized for term in ACCURACY_ACTION_TERMS)
    mentions_accuracy = "精度" in normalized
    if not has_action or not mentions_accuracy:
        return None
    if any(term in normalized for term in ACCURACY_EXPLANATION_TERMS):
        return None

    grade_map = {"一": "1级", "二": "2级", "三": "3级", "1": "1级", "2": "2级", "3": "3级"}
    tokens = re.findall(r"([一二三123])\s*级", normalized)
    grades = list(dict.fromkeys(grade_map[token] for token in tokens))
    invalid_tokens = re.findall(r"([四五六七八九零4567890])\s*级", normalized)
    specialized_terms = [term for term in ACCURACY_SPECIALIZED_TERMS if term in normalized]

    if invalid_tokens:
        return {
            "status": "invalid_grade",
            "requested_grade": None,
            "requested_grades": grades,
            "scope": "general",
            "message": "当前仅支持1级、2级或3级精度，请重新指定。",
        }
    if len(grades) > 1:
        return {
            "status": "need_clarification",
            "requested_grade": None,
            "requested_grades": grades,
            "scope": "general",
            "message": f"本次同时识别到{'、'.join(grades)}，请只选择一个通用精度等级。",
        }
    if not grades:
        return {
            "status": "need_clarification",
            "requested_grade": None,
            "requested_grades": [],
            "scope": "general",
            "message": "请明确选择1级、2级或3级精度后再进行标准化。",
        }
    if specialized_terms:
        return {
            "status": "specialized_not_supported",
            "requested_grade": grades[0],
            "requested_grades": grades,
            "scope": "specialized",
            "specialized_terms": specialized_terms,
            "message": "当前AI对话第一版只支持设置整图的通用精度；专项精度请暂时在参数页单独设置。",
        }
    return {
        "status": "ready",
        "requested_grade": grades[0],
        "requested_grades": grades,
        "scope": "general",
    }


def parse_generation_package_export_request(message: str) -> dict[str, Any] | None:
    """Recognize an explicit generation-package export request without building the package in the LLM."""

    text = str(message or "").strip()
    normalized = re.sub(r"[\s，。！？、：；,.!?;:_-]+", "", text).lower()
    has_action = any(term.replace(" ", "").lower() in normalized for term in GENERATION_PACKAGE_EXPORT_ACTION_TERMS)
    has_object = any(term.replace(" ", "").lower() in normalized for term in GENERATION_PACKAGE_EXPORT_OBJECT_TERMS)
    if not has_action or not has_object:
        return None
    if any(term in normalized for term in GENERATION_PACKAGE_EXPORT_EXPLANATION_TERMS):
        return {"status": "explain", "source": "local_rule"}
    if any(term in normalized for term in GENERATION_PACKAGE_EXPORT_QUERY_TERMS):
        return {"status": "query", "source": "local_rule"}
    return {"status": "execute", "source": "local_rule"}


def select_general_accuracy_grade(review: dict[str, Any], requested_grade: str) -> dict[str, Any]:
    """Apply the same confirmed general-grade selection used by the manual UI."""

    grade = str(requested_grade or "").strip()
    if grade not in {"1级", "2级", "3级"}:
        raise ValueError("requested_grade must be 1级, 2级, or 3级.")
    parameters = review.setdefault("spring_parameters", {})
    current = parameters.get("accuracy_grade")
    item = dict(current) if isinstance(current, dict) else {}
    previous_grade = _normalized_accuracy_grade(item.get("value"))
    raw_source = item.get("source")
    previous_source = [str(value) for value in raw_source] if isinstance(raw_source, list) else [str(raw_source)] if raw_source else []
    selection_changed = (
        previous_grade != grade
        or item.get("need_human_review") is not False
        or previous_source != ["human_selected"]
        or bool(item.get("default_source"))
    )
    specialized_retained = {
        field: str((parameters.get(field) or {}).get("value"))
        for field in ACCURACY_GRADE_FIELDS
        if isinstance(parameters.get(field), dict) and (parameters.get(field) or {}).get("value") not in (None, "")
    }
    item.update(
        {
            "value": grade,
            "need_human_review": False,
            "confidence": 0.99,
            "source": ["human_selected"],
            "evidence": f"用户通过AI对话选择通用精度等级：{grade}。",
        }
    )
    item.pop("default_source", None)
    item.pop("default_reason", None)
    parameters["accuracy_grade"] = item
    review.setdefault("manual_confirmations", {})["accuracy_grade"] = {
        "confirmed": True,
        "value": grade,
        "confirmed_at": _now(),
        "confirmation_source": "ai_accuracy_standardization",
    }
    invalidated = []
    if selection_changed:
        invalidated = invalidate_open_parameter_change_proposals(
            review,
            reason="通用精度等级已经变化，当前参数修改方案需要重新计算。",
        )
    return {
        "status": "selected",
        "requested_grade": grade,
        "previous_grade": previous_grade,
        "scope": "general",
        "selection_changed": selection_changed,
        "specialized_grades_retained": specialized_retained,
        "invalidated_proposal_ids": invalidated,
    }


def _normalized_accuracy_grade(value: Any) -> str | None:
    normalized = str(value or "").replace("級", "级")
    matched = re.search(r"([123])\s*级", normalized)
    return f"{matched.group(1)}级" if matched else None


def standardization_chat_context_needs_refresh(review: dict[str, Any], message: str) -> dict[str, Any]:
    """Decide whether a chat turn needs fresh deterministic standardization context."""
    text = str(message or "").strip()
    accuracy_request = parse_accuracy_standardization_request(text)
    if accuracy_request is not None:
        return {
            "required": False,
            "intent_type": "accuracy_standardization_request",
            "reasons": [],
            "result_count": len(review.get("standardization_results") or []),
            "stale_result_count": 0,
        }
    package_export_request = parse_generation_package_export_request(text)
    if package_export_request is not None:
        return {
            "required": False,
            "intent_type": "generation_package_export_request",
            "reasons": [],
            "result_count": len(review.get("standardization_results") or []),
            "stale_result_count": 0,
        }
    intent_type = _detect_intent_type(text)
    results = [item for item in review.get("standardization_results", []) or [] if isinstance(item, dict)]
    selection = review.get("standard_selection") or {}
    stale_count = sum(1 for item in results if item.get("status") == "stale")
    has_stale_context = bool(review.get("derived_parameters_stale")) or stale_count > 0
    needs_standardization_context = intent_type in {"full_plan", "explain", "change", "confirm"} or any(
        word in text for word in ("标准化", "手册", "公差", "标准")
    )
    reasons: list[str] = []
    if needs_standardization_context and not results:
        reasons.append("missing_standardization_results")
    if needs_standardization_context and has_stale_context:
        reasons.append("stale_parameters_or_results")
    if needs_standardization_context and not selection.get("selected_standard"):
        reasons.append("missing_standard_selection")
    return {
        "required": bool(reasons),
        "intent_type": intent_type,
        "reasons": reasons,
        "result_count": len(results),
        "stale_result_count": stale_count,
    }


def chat_about_standardization(
    review: dict[str, Any],
    message: str,
    *,
    use_llm: bool = False,
    llm_engine: Any | None = None,
    supplements: dict[str, Any] | None = None,
    active_proposal_id: str | None = None,
    review_revision: int | None = None,
    accuracy_standardization: dict[str, Any] | None = None,
    standardization_batch_revision: int | None = None,
    generation_package_export_source: str = "local",
    generation_package_export_revision: int | None = None,
) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        raise ValueError("message is required.")

    raw_supplements = supplements if isinstance(supplements, dict) else {}
    accuracy_request = parse_accuracy_standardization_request(text)
    package_export_request = parse_generation_package_export_request(text)
    if package_export_request is None:
        review["parameter_reasonableness"] = assess_parameter_reasonableness(review)
    target = _detect_target_field(text)
    intent_type = _detect_intent_type(text)
    missing_context = _missing_standardization_context(review)
    pending_fields = _pending_missing_context_fields(review)
    if intent_type == "unknown" and pending_fields:
        pending_target = target if target in pending_fields else pending_fields[0]
        pending_value, _ = _extract_requested_value(text, pending_target)
        if pending_value is not None:
            target = pending_target
            intent_type = "change"

    if raw_supplements:
        result = _handle_batch_supplements(review, raw_supplements)
    elif accuracy_request is not None:
        result = _handle_accuracy_standardization_request(
            accuracy_request,
            accuracy_standardization=accuracy_standardization,
        )
    elif package_export_request is not None:
        result = _handle_generation_package_export(
            review,
            package_export_request,
            source_mode=generation_package_export_source,
            review_revision=generation_package_export_revision,
        )
    elif intent_type == "parameter_reasonableness":
        result = _handle_parameter_reasonableness(review, text)
    elif intent_type == "generation_readiness":
        result = _handle_generation_readiness(review)
    elif intent_type == "full_plan" and missing_context:
        result = _handle_missing_context(review, missing_context)
    elif intent_type == "full_plan":
        result = _handle_full_plan(review, text)
    elif intent_type == "explain":
        result = _handle_explain(review, text, target)
    elif intent_type == "change":
        result = _handle_change(review, text, target)
    elif intent_type == "confirm":
        result = _handle_confirm(review, text, target)
    else:
        result = _handle_unknown(review, text, target)

    # Missing inputs are deterministic blocking conditions. Ask for them first
    # rather than allowing an LLM to produce a seemingly complete plan.
    if use_llm and not raw_supplements and result["intent"]["type"] not in {
        "accuracy_standardization_request",
        "generation_package_export_request",
        "missing_context",
        "generation_readiness",
        "parameter_reasonableness",
    }:
        result = _run_llm_chat(review, text, result, llm_engine=llm_engine)

    if (
        package_export_request is None
        and (result.get("intent") or {}).get("type") == "generation_package_export_request"
    ):
        llm_metadata = {key: result.get(key) for key in ("llm_chat", "diagnostics") if result.get(key) is not None}
        result = _handle_generation_package_export(
            review,
            {"status": "execute", "source": "llm"},
            source_mode=generation_package_export_source,
            review_revision=generation_package_export_revision,
        )
        result.update(llm_metadata)

    _attach_proposal_feasibility(review, result)

    proposal_actions = [
        item
        for item in result.get("suggested_actions", []) or []
        if isinstance(item, dict) and item.get("type") in {"propose_parameter_patch", "propose_tolerance_patch", "proposal_constraint"}
    ]
    selected_proposal_id = active_proposal_id or review.get("active_parameter_change_proposal_id")
    clarification = None
    if (
        not proposal_actions
        and (result.get("intent") or {}).get("type") == "parameter_change_request"
        and (result.get("intent") or {}).get("status") in {"need_clarification", "need_input"}
    ):
        clarification = str(result.get("reply") or "请补充明确的修改目标值。")
    change_proposal = None
    if proposal_actions or clarification:
        change_proposal = build_parameter_change_proposal(
            review,
            proposal_actions,
            user_goal=text,
            active_proposal_id=str(selected_proposal_id or "") or None,
            review_revision=review_revision,
            clarification=clarification,
        )
    if change_proposal:
        result["change_proposal"] = change_proposal

    result_intent = result.get("intent") or {}
    is_accuracy_execution = (
        result_intent.get("type") == "accuracy_standardization_request"
        and result_intent.get("status") == "completed"
    )
    is_full_standardization = result_intent.get("type") == "full_standardization_plan"
    if is_accuracy_execution or is_full_standardization:
        result["standardization_batch"] = build_standardization_batch(
            review,
            review_revision=standardization_batch_revision,
        )

    turn = {
        "created_at": _now(),
        "user": text,
        "assistant": result["reply"],
        "intent": result["intent"],
        "suggested_actions": result.get("suggested_actions", []),
        "references": result.get("references", []),
    }
    if result.get("proposal_validation"):
        turn["proposal_validation"] = result["proposal_validation"]
    if result.get("impact_preview"):
        turn["impact_preview"] = result["impact_preview"]
    if result.get("change_proposal"):
        turn["change_proposal"] = result["change_proposal"]
    if result.get("generation_readiness"):
        turn["generation_readiness"] = result["generation_readiness"]
    if result.get("accuracy_standardization"):
        turn["accuracy_standardization"] = result["accuracy_standardization"]
    if result.get("standardization_batch"):
        turn["standardization_batch"] = result["standardization_batch"]
    if result.get("generation_package_export"):
        turn["generation_package_export"] = result["generation_package_export"]
    if result.get("llm_chat"):
        turn["llm_chat"] = result["llm_chat"]
    if result.get("diagnostics"):
        turn["diagnostics"] = result["diagnostics"]
    review.setdefault("standardization_chat", [])
    review["standardization_chat"].append(turn)
    if result.get("change_proposal"):
        proposal = find_parameter_change_proposal(review, result["change_proposal"].get("proposal_id"))
        if proposal is not None:
            proposal["source_turn_created_at"] = turn["created_at"]
        result["change_proposal"]["source_turn_created_at"] = turn["created_at"]
        turn["change_proposal"]["source_turn_created_at"] = turn["created_at"]
    result["turn"] = turn
    result["review"] = review
    return result


def _handle_accuracy_standardization_request(
    request: dict[str, Any],
    *,
    accuracy_standardization: dict[str, Any] | None,
) -> dict[str, Any]:
    request_status = str(request.get("status") or "need_clarification")
    if request_status == "ready" and accuracy_standardization:
        completed = dict(accuracy_standardization)
        grade = str(completed.get("requested_grade") or request.get("requested_grade") or "")
        count = int(completed.get("standardization_result_count") or 0)
        retained = completed.get("specialized_grades_retained") or {}
        retained_text = ""
        if retained:
            retained_text = " 已有专项精度保持不变，并继续优先用于对应公差计算。"
        reply = (
            f"已按通用精度等级{grade}重新生成标准化方案，共生成{count}项建议。"
            f"{retained_text} 标准化建议尚未自动应用，请继续逐项核对或批量应用。"
        )
        result = _response(
            reply,
            intent_type="accuracy_standardization_request",
            target_field="accuracy_grade",
            status="completed",
            affected_fields=["accuracy_grade", "standardization_results"],
        )
        result["accuracy_standardization"] = completed
        return result

    if request_status == "ready":
        message = "已识别精度标准化指令，但当前调用未执行标准化，请重新提交。"
        status = "execution_required"
    else:
        message = str(request.get("message") or "请明确选择1级、2级或3级精度。")
        status = request_status
    result = _response(
        message,
        intent_type="accuracy_standardization_request",
        target_field="accuracy_grade",
        status=status,
        affected_fields=[],
    )
    result["accuracy_standardization"] = dict(request)
    return result


def _run_llm_chat(
    review: dict[str, Any],
    message: str,
    rule_result: dict[str, Any],
    *,
    llm_engine: Any | None = None,
) -> dict[str, Any]:
    try:
        engine = llm_engine or StandardizationChatLLMEngine()
        llm_result = engine.chat(review, message, rule_result)
    except Exception as exc:
        fallback = dict(rule_result)
        error_text = f"{type(exc).__name__}: {exc}"
        if (rule_result.get("intent") or {}).get("type") == "full_standardization_plan":
            fallback["reply"] = (
                "我已按当前参数自动更新本地标准化建议，但这次 LLM/RAG 没有返回多字段对话方案。"
                f"你仍可在标准化建议区批量应用规则结果，或稍后重试 AI 方案。错误：{error_text}"
            )
        else:
            fallback["reply"] = (
                f"{rule_result.get('reply') or '我已按规则解析这条标准化对话。'} "
                f"LLM/RAG 对话暂不可用，已降级为规则结果：{error_text}"
            )
        fallback["llm_chat"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        fallback["diagnostics"] = [
            *fallback.get("diagnostics", []),
            {"type": "llm_chat_failed", "error": f"{type(exc).__name__}: {exc}"},
        ]
        return fallback

    llm_result["rule_result"] = {
        "reply": rule_result.get("reply"),
        "intent": rule_result.get("intent"),
        "suggested_actions": rule_result.get("suggested_actions", []),
    }
    return llm_result


def _attach_proposal_feasibility(review: dict[str, Any], result: dict[str, Any]) -> None:
    actions = [item for item in result.get("suggested_actions", []) or [] if isinstance(item, dict)]
    applicable_actions = [
        item
        for item in actions
        if item.get("type") in {"propose_parameter_patch", "propose_tolerance_patch"}
    ]
    parameter_actions = [item for item in actions if item.get("type") == "propose_parameter_patch"]
    if not applicable_actions:
        return

    for action in applicable_actions:
        impact_preview = assess_parameter_change_impact(review, [action])
        action["impact_preview"] = impact_preview
        metadata = action.setdefault("metadata", {})
        metadata["impact_status"] = impact_preview["status"]
        metadata["impact_can_apply"] = impact_preview["status"] != "blocked"
        if action.get("type") == "propose_parameter_patch":
            validation = assess_parameter_change_set(review, [action])
            action["validation"] = validation
            metadata["feasibility_status"] = validation["status"]
            metadata["feasibility_can_apply"] = validation["status"] != "blocked"

    if parameter_actions:
        result["proposal_validation"] = assess_parameter_change_set(review, parameter_actions)
    impact_preview = assess_parameter_change_impact(review, applicable_actions)
    result["impact_preview"] = impact_preview
    if impact_preview["status"] == "blocked":
        result["reply"] = (
            f"{result.get('reply') or ''}\n\n"
            f"变更预检未通过：{impact_preview['summary']} 请调整目标值后再确认。"
        ).strip()
    elif impact_preview["status"] == "warning":
        result["reply"] = (
            f"{result.get('reply') or ''}\n\n"
            f"变更预检提示：{impact_preview['summary']}"
        ).strip()


def _handle_parameter_reasonableness(review: dict[str, Any], message: str) -> dict[str, Any]:
    assessment = review.get("parameter_reasonableness") or assess_parameter_reasonableness(review)
    issues = [item for item in assessment.get("issues", []) if isinstance(item, dict)]
    status = str(assessment.get("status") or "pass")
    if not issues:
        return _response(
            "当前已识别参数未发现明显几何矛盾或当前标准适用范围风险。仍建议人工确认识别值和客户工况。",
            intent_type="parameter_reasonableness",
            target_field="",
            status="pass",
        )

    sections = []
    for item in issues[:5]:
        sections.append(
            f"【{item.get('severity')}】{item.get('message') or ''}\n"
            f"原因：{item.get('explanation') or item.get('basis') or '需要人工复核。'}\n"
            f"建议向客户确认：{item.get('customer_question') or '请确认相关尺寸。'}"
        )
    prefix = "当前图纸存在不能直接采用的参数矛盾。" if status == "blocked" else "当前图纸有需要复核的参数。"
    if status == "needs_input":
        prefix = "当前图纸缺少完整判断所需的信息。"
    reply = f"{prefix}\n\n" + "\n\n".join(sections)
    if len(issues) > 5:
        reply += f"\n\n其余 {len(issues) - 5} 项请在参数合理性区域查看。"
    return _response(
        reply,
        intent_type="parameter_reasonableness",
        target_field=str((issues[0].get("fields") or [""])[0]),
        target_fields=[str(field) for item in issues for field in item.get("fields") or []],
        status=status,
        references=_retrieve_references(review, None, message),
    )


def _handle_generation_readiness(review: dict[str, Any]) -> dict[str, Any]:
    export_review = deepcopy(review)
    readiness = assess_generation_readiness(export_review)
    missing = readiness.get("missing_fields") or []
    pending = readiness.get("pending_fields") or []
    actions = [
        {
            "type": "request_missing_field",
            "target_field": item.get("field"),
            "target_label": item.get("label"),
            "reason": item.get("reason"),
            "status": "need_input",
            "apply_policy": "manual_input_required",
        }
        for item in [*missing, *pending]
        if item.get("field") and not str(item.get("field")).startswith("technical_requirements.")
    ]
    status = readiness.get("status")
    if status in {"ready", "ready_with_warnings"}:
        reply = "当前已具备重新生图的确认参数，可在“生图参数包”页导出独立 JSON。"
        if readiness.get("warnings"):
            reply += f" 另有 {len(readiness['warnings'])} 条风险提示，请在生图前复核。"
        intent_status = "ready"
    else:
        labels = "、".join(
            list(dict.fromkeys(str(item.get("label") or item.get("field") or "") for item in [*missing, *pending] if item.get("label") or item.get("field")))
        )
        reply = f"当前还不能生成最终图纸参数包：{readiness.get('summary') or '仍有待补充信息。'}"
        if labels:
            reply += f" 请补充或确认：{labels}。"
        intent_status = "need_input"
    response = _response(
        reply,
        intent_type="generation_readiness",
        target_field=str((missing or pending or [{}])[0].get("field") or ""),
        target_fields=[str(item.get("field") or "") for item in [*missing, *pending] if item.get("field")],
        status=intent_status,
        suggested_actions=actions,
        affected_fields=["generation_parameters"],
    )
    response["generation_readiness"] = readiness
    return response


def _handle_generation_package_export(
    review: dict[str, Any],
    request: dict[str, Any],
    *,
    source_mode: str,
    review_revision: int | None,
) -> dict[str, Any]:
    request_status = str(request.get("status") or "execute")
    if request_status == "explain":
        return _response(
            "正式审图可从服务端导出冻结的SolidWorks生图参数包；本地导入JSON也可以导出，但不能据此创建生图任务。请直接说“导出参数包”即可执行。",
            intent_type="generation_package_export_request",
            target_field="",
            status="explained",
            affected_fields=[],
        )

    export_review = deepcopy(review)
    readiness = assess_generation_readiness(export_review)
    readiness_status = str(readiness.get("status") or "needs_input")
    can_download = request_status == "execute" and readiness_status in {"ready", "ready_with_warnings"}
    if request_status == "query":
        if readiness_status in {"ready", "ready_with_warnings"}:
            reply = "当前参数已经可以导出生图参数包。需要下载时，请直接说“导出参数包”。"
        else:
            reply = f"当前还不能导出生图参数包：{readiness.get('summary') or '仍有内容需要处理。'}"
        response = _response(
            reply,
            intent_type="generation_package_export_request",
            target_field="",
            status="answered",
            affected_fields=[],
        )
        response["generation_readiness"] = readiness
        return response

    if can_download:
        reply = "已完成生图参数包校验，正在下载冻结的SolidWorks参数JSON。"
        if readiness_status == "ready_with_warnings":
            reply += f" 参数包仍可使用，但有 {len(readiness.get('warnings') or [])} 条非阻断警告，已在结果卡中列出。"
        intent_status = "ready"
    else:
        reply = f"当前暂时不能导出生图参数包：{readiness.get('summary') or '仍有内容需要处理。'}"
        intent_status = "blocked"

    parameters = export_review.get("spring_parameters") or {}
    field_summary = []
    baseline_parameter_fields = []
    for field in COMPRESSION_GENERATION_INPUT_FIELDS:
        item = generation_source_item(parameters, field)
        value = item.get("value") if isinstance(item, dict) else item
        unit = item.get("unit") if isinstance(item, dict) else None
        field_summary.append(
            {
                "field": field,
                "label": COMPRESSION_GENERATION_LABELS.get(field) or FIELD_LABELS.get(field) or field,
                "value": value,
                "unit": unit,
            }
        )
        baseline_parameter_fields.append(
            {
                "field": field,
                "value": value,
                "unit": unit,
                "tolerance_upper": item.get("tolerance_upper") if isinstance(item, dict) else None,
                "tolerance_lower": item.get("tolerance_lower") if isinstance(item, dict) else None,
                "need_human_review": bool(item.get("need_human_review", True)) if isinstance(item, dict) else True,
            }
        )

    baseline_requirements = [
        {
            "type": item.get("type"),
            "content": item.get("content"),
            "need_human_review": bool(item.get("need_human_review", True)),
            "confirmation_source": item.get("confirmation_source"),
        }
        for item in (export_review.get("technical_requirements") or [])
        if isinstance(item, dict) and item.get("content")
    ]

    export_action = {
        "status": readiness_status,
        "source_mode": "server" if source_mode == "server" else "local",
        "filename": "compression_spring_generation_parameters.json",
        "schema_version": GENERATION_SCHEMA_VERSION,
        "review_revision": review_revision,
        "can_download": can_download,
        "automatic_download": can_download,
        "action_type": "download_generation_package" if can_download else "resolve_generation_readiness",
        "parameter_fields": field_summary,
        "missing_fields": list(readiness.get("missing_fields") or []),
        "pending_fields": list(readiness.get("pending_fields") or []),
        "blocking_reasonableness": list(readiness.get("blocking_reasonableness") or []),
        "warnings": list(readiness.get("warnings") or []),
        "download_status": "pending" if can_download else "blocked",
        "downloaded_at": None,
        "failure_reason": "",
        "baseline_state": {
            "spring_type": (export_review.get("drawing_summary") or {}).get("spring_type"),
            "parameter_fields": baseline_parameter_fields,
            "technical_requirements": baseline_requirements,
        },
    }
    response = _response(
        reply,
        intent_type="generation_package_export_request",
        target_field="",
        status=intent_status,
        affected_fields=[],
    )
    response["generation_readiness"] = readiness
    response["generation_package_export"] = export_action
    return response


def _handle_batch_supplements(review: dict[str, Any], supplements: dict[str, Any]) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    invalid: list[str] = []
    for raw_target, raw_value in supplements.items():
        target = str(raw_target or "").strip()
        if not _supplement_target_exists(review, target):
            invalid.append(_target_label(target) or target)
            continue
        value = _coerce_supplement_value(target, raw_value)
        if value is None:
            invalid.append(_target_label(target) or target)
            continue
        actions.append(
            {
                "type": "propose_parameter_patch",
                "target_field": target,
                "target_label": _target_label(target),
                "current_value": _current_value(review, target),
                "proposed_value": value,
                "unit": _target_unit(review, target),
                "affected_fields": _affected_fields(target),
                "reason": "用户在缺失参数卡片中批量补充。",
                "apply_policy": "manual_confirm_required",
            }
        )

    if not actions:
        reply = "没有识别到可用的补充值。请检查本轮填写内容后再提交。"
        if invalid:
            reply += f" 未能解析：{'、'.join(dict.fromkeys(invalid))}。"
        return _response(
            reply,
            intent_type="batch_parameter_supplement",
            target_field="",
            status="need_clarification",
        )

    targets = [str(action["target_field"]) for action in actions]
    labels = _join_labels(targets)
    reply = (
        f"已收到本轮 {len(actions)} 项补充：{labels}。"
        "请核对下方建议；可以逐项应用，也可以一次应用本轮全部建议，随后只会重新标准化一次。"
    )
    if invalid:
        reply += f" 未能解析：{'、'.join(dict.fromkeys(invalid))}。"
    return _response(
        reply,
        intent_type="batch_parameter_supplement",
        target_field=targets[0],
        target_fields=targets,
        status="proposal_ready",
        suggested_actions=actions,
        affected_fields=list(dict.fromkeys(field for action in actions for field in action["affected_fields"])),
        references=_retrieve_plan_references(review, "批量补充标准化参数", targets),
    )


def _supplement_target_exists(review: dict[str, Any], target: str) -> bool:
    if target.startswith("load_points."):
        parts = target.split(".")
        if len(parts) != 3 or parts[2] not in {"force", "height"}:
            return False
        return any(
            str(point.get("label") or "").upper() == parts[1].upper()
            for point in review.get("spring_parameters", {}).get("load_points", []) or []
            if isinstance(point, dict)
        )
    return target in (review.get("spring_parameters") or {})


def _coerce_supplement_value(target: str, raw_value: Any) -> Any | None:
    text = str(raw_value if raw_value is not None else "").strip()
    if not text:
        return None
    if target.endswith("accuracy_grade"):
        grade = re.search(r"([123])\s*级", text)
        return f"{grade.group(1)}级" if grade else None
    if target == "end_grinding":
        return normalize_end_grinding(text)
    if target == "end_type":
        return normalize_end_type(text)
    if target in NUMERIC_SUPPLEMENT_FIELDS or target.startswith("load_points."):
        matched = re.search(r"-?\d+(?:\.\d+)?", text)
        return _to_number(matched.group(0)) if matched else None
    return text


def _missing_standardization_context(review: dict[str, Any]) -> list[dict[str, Any]]:
    missing_by_field: dict[str, dict[str, Any]] = {}
    for item in review.get("standardization_results", []) or []:
        if not isinstance(item, dict) or item.get("status") != "need_context":
            continue
        metadata = item.get("metadata") or {}
        fields = metadata.get("missing_fields") or []
        if not isinstance(fields, list):
            continue
        for field in fields:
            target_field = str(field or "").strip()
            if not target_field:
                continue
            entry = missing_by_field.setdefault(
                target_field,
                {
                    "target_field": target_field,
                    "target_label": _target_label(target_field),
                    "reason": str(item.get("basis") or "标准化计算缺少该字段。"),
                    "rule_ids": [],
                },
            )
            rule_id = str(item.get("rule_id") or "")
            if rule_id and rule_id not in entry["rule_ids"]:
                entry["rule_ids"].append(rule_id)
    return list(missing_by_field.values())


def _pending_missing_context_fields(review: dict[str, Any]) -> list[str]:
    for turn in reversed(review.get("standardization_chat", []) or []):
        if not isinstance(turn, dict):
            continue
        fields = [
            str(action.get("target_field") or "").strip()
            for action in turn.get("suggested_actions", []) or []
            if isinstance(action, dict)
            and action.get("type") == "request_missing_field"
            and action.get("status") == "need_input"
        ]
        if fields:
            return list(dict.fromkeys(field for field in fields if field))
    return []


def _handle_missing_context(review: dict[str, Any], missing_context: list[dict[str, Any]]) -> dict[str, Any]:
    target_fields = [item["target_field"] for item in missing_context]
    actions = [
        {
            "type": "request_missing_field",
            "target_field": item["target_field"],
            "target_label": item["target_label"],
            "reason": item["reason"],
            "rule_ids": item["rule_ids"],
            "status": "need_input",
            "apply_policy": "manual_input_required",
        }
        for item in missing_context
    ]
    labels = _join_labels(target_fields)
    reply = (
        f"要生成可确认的完整标准化方案，还需要补充：{labels}。"
        "请点击下方“去填写”直接录入，或在对话中回复“字段名 数值”，例如“有效圈数 8”。"
        "补充后再次发送标准化请求，我会按当前参数自动重新计算。"
    )
    return _response(
        reply,
        intent_type="missing_context",
        target_field=target_fields[0] if target_fields else "",
        target_fields=target_fields,
        status="need_input",
        suggested_actions=actions,
        affected_fields=["derived_parameters", "standardization_results"],
        references=_retrieve_plan_references(review, "补充标准化缺失参数", target_fields),
    )


def _handle_explain(review: dict[str, Any], message: str, target: str | None) -> dict[str, Any]:
    matched = _matching_standardization_results(review, target, message)
    if matched:
        item = matched[0]
        suggestion = _format_suggestion(item)
        references = _references_from_result(item)
        reply = (
            f"{_target_label(item.get('target_field'))}的标准化建议是 {suggestion}。"
            f"依据：{item.get('basis') or '当前结果缺少文字依据，需要人工复核。'}"
        )
        if item.get("standard_no"):
            reply += f" 适用标准：{item['standard_no']}。"
        if item.get("need_human_review"):
            reply += " 这条建议仍需要人工确认后才会写入最终参数。"
        return _response(
            reply,
            intent_type="explanation",
            target_field=str(item.get("target_field") or target or ""),
            status="answered",
            references=references,
        )

    references = _retrieve_references(review, target, message)
    if not review.get("standardization_results"):
        reply = "当前还没有标准化建议。请先点击“标准化”，我再根据生成的结果解释每个公差和依据。"
    elif target:
        reply = f"当前标准化结果里没有找到{_target_label(target)}的对应建议。你可以先补充相关尺寸或重新标准化。"
    else:
        reply = "我还没定位到你要解释的字段。可以这样问：为什么外径公差是这个值？或者自由长度公差依据是什么？"
    return _response(
        reply,
        intent_type="explanation",
        target_field=target or "",
        status="need_context",
        references=references,
    )


def _handle_change(review: dict[str, Any], message: str, target: str | None) -> dict[str, Any]:
    if not target:
        return _response(
            "我能感觉到你想调整尺寸，但还没定位到具体字段。请说明要改外径、内径、自由长度、线径、载荷测试点还是其他参数。",
            intent_type="parameter_change_request",
            target_field="",
            status="need_clarification",
        )

    constraints = _extract_proposal_constraints(review, message)
    if constraints:
        targets = [str(item["target_field"]) for item in constraints]
        return _response(
            f"已把你的要求记录为方案硬约束：{'、'.join(item['description'] for item in constraints)}。系统会从正式参数基线重新求解完整方案。",
            intent_type="parameter_change_request",
            target_field=targets[0],
            target_fields=targets,
            status="proposal_ready",
            suggested_actions=constraints,
            affected_fields=list(dict.fromkeys(field for target in targets for field in _affected_fields(target))),
        )

    requested_changes = _extract_multiple_requested_changes(message)
    if requested_changes:
        actions = []
        for requested_target, value, unit in requested_changes:
            actions.append(
                {
                    "type": "propose_parameter_patch",
                    "target_field": requested_target,
                    "target_label": _target_label(requested_target),
                    "current_value": _current_value(review, requested_target),
                    "proposed_value": value,
                    "unit": unit or _target_unit(review, requested_target),
                    "affected_fields": _affected_fields(requested_target),
                    "apply_policy": "proposal_only",
                }
            )
        targets = [str(action["target_field"]) for action in actions]
        return _response(
            f"已根据你的要求整理 {len(actions)} 项直接修改，并正在同步计算全部关联参数。方案确认前不会自动写回正式参数。",
            intent_type="parameter_change_request",
            target_field=targets[0],
            target_fields=targets,
            status="proposal_ready",
            suggested_actions=actions,
            affected_fields=list(dict.fromkeys(field for action in actions for field in action["affected_fields"])),
            references=_retrieve_plan_references(review, message, targets),
        )

    value, unit = _extract_requested_value(message, target)
    current_value = _current_value(review, target)
    affected = _affected_fields(target)
    references = _retrieve_references(review, target, message)
    if value is None:
        reply = (
            f"我识别到你觉得{_target_label(target)}需要调整，但缺少目标值。"
            f"当前值是 {_format_current_value(current_value)}。请告诉我希望改到多少，或者给出约束，比如“外径改成22mm，其他尽量不变”。"
        )
        return _response(
            reply,
            intent_type="parameter_change_request",
            target_field=target,
            status="need_clarification",
            affected_fields=affected,
            references=references,
        )

    action = {
        "type": "propose_parameter_patch",
        "target_field": target,
        "target_label": _target_label(target),
        "current_value": current_value,
        "proposed_value": value,
        "unit": unit or _target_unit(review, target),
        "affected_fields": affected,
        "apply_policy": "manual_confirm_required",
    }
    reply = (
        f"我识别到你想把{_target_label(target)}从 {_format_current_value(current_value)} 调整为 "
        f"{_format_value(value, action['unit'])}。已生成可审阅的修改建议，不会自动写回参数。"
        f"确认应用后会重新计算：{_join_labels(affected)}。"
    )
    if references:
        reply += " 我也找到了相关标准依据，后续重新标准化会继续引用这些条款。"
    return _response(
        reply,
        intent_type="parameter_change_request",
        target_field=target,
        status="proposal_ready",
        suggested_actions=[action],
        affected_fields=affected,
        references=references,
    )


def _handle_full_plan(review: dict[str, Any], message: str) -> dict[str, Any]:
    target_fields = _plan_target_fields(review)
    references = _retrieve_plan_references(review, message, target_fields)
    selected_standard = (review.get("standard_selection") or {}).get("selected_standard")
    if selected_standard:
        reply = (
            f"我会基于当前参数、{selected_standard} 和检索到的手册依据生成完整标准化方案；"
            "建议仍需人工确认后才写回。"
        )
    else:
        reply = (
            "我会先根据当前图纸参数自动完成标准选择，再结合手册依据生成完整标准化方案；"
            "如关键信息不足，会明确列出需要补充的字段。"
        )
    return _response(
        reply,
        intent_type="full_standardization_plan",
        target_field="",
        target_fields=target_fields,
        status="manual_apply_required" if selected_standard else "need_context",
        affected_fields=["standard_selection", "derived_parameters", "standardization_results"],
        references=references,
    )


def _handle_confirm(review: dict[str, Any], message: str, target: str | None) -> dict[str, Any]:
    return _response(
        "我理解你是在确认前面的建议。请点击建议卡片上的“应用建议”或“应用本轮全部建议”；系统会写回已确认的字段并自动重新标准化。",
        intent_type="confirmation",
        target_field=target or "",
        status="manual_apply_required",
    )


def _handle_unknown(review: dict[str, Any], message: str, target: str | None) -> dict[str, Any]:
    if target:
        return _response(
            f"我定位到你提到了{_target_label(target)}，但还不确定你是想解释依据还是修改尺寸。你可以说“为什么这个公差是这样”或“{_target_label(target)}改成xx”。",
            intent_type="unknown",
            target_field=target,
            status="need_clarification",
        )
    return _response(
        "我还没有识别出明确的标准化意图。你可以问“为什么自由长度公差是±0.9”，也可以说“外径改成22mm”。",
        intent_type="unknown",
        target_field="",
        status="need_clarification",
    )


def _response(
    reply: str,
    *,
    intent_type: str,
    target_field: str,
    status: str,
    target_fields: list[str] | None = None,
    suggested_actions: list[dict[str, Any]] | None = None,
    affected_fields: list[str] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_target_fields = list(dict.fromkeys(target_fields or ([target_field] if target_field else [])))
    return {
        "reply": reply,
        "intent": {
            "type": intent_type,
            "target_field": target_field,
            "target_fields": normalized_target_fields,
            "target_label": _target_label(target_field) if target_field else "",
            "status": status,
            "affected_fields": affected_fields or [],
        },
        "suggested_actions": suggested_actions or [],
        "references": references or [],
    }


def _detect_intent_type(text: str) -> str:
    normalized = text.lower()
    if any(word in text for word in REASONABLENESS_WORDS):
        return "parameter_reasonableness"
    if any(word in text for word in GENERATION_READINESS_WORDS):
        return "generation_readiness"
    if any(word in text for word in FULL_PLAN_WORDS):
        return "full_plan"
    if any(word in text for word in EXPLANATION_WORDS):
        return "explain"
    if any(word in text for word in CHANGE_WORDS):
        return "change"
    if any(word in text for word in CONFIRM_WORDS):
        return "confirm"
    if re.search(r"(改成|改为|设为|设置为|调整到)\s*-?\d", text):
        return "change"
    return "unknown"


def _detect_target_field(text: str) -> str | None:
    lowered = text.lower()
    load_target = _detect_load_point_target(text)
    if load_target:
        return load_target
    for field, words in FIELD_SYNONYMS.items():
        for word in words:
            needle = word.lower()
            if not needle:
                continue
            if re.fullmatch(r"[a-z0-9/]+", needle):
                if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lowered):
                    return field
                continue
            if needle in lowered:
                return field
    return None


def _detect_load_point_target(text: str) -> str | None:
    height_label = re.search(r"(?<![A-Za-z0-9])H(\d+)(?!\d)", text, re.IGNORECASE)
    if height_label:
        return f"load_points.F{height_label.group(1)}.height"

    load_label = re.search(r"(?<![A-Za-z0-9])F(\d+)(?!\d)", text, re.IGNORECASE)
    if not load_label:
        return None
    field = "height" if re.search(r"(?:高度|高程|压缩到|压缩高度|试验高度|测试高度)", text) else "force"
    return f"load_points.F{load_label.group(1)}.{field}"


def _matching_standardization_results(review: dict[str, Any], target: str | None, message: str) -> list[dict[str, Any]]:
    results = [item for item in review.get("standardization_results", []) or [] if isinstance(item, dict)]
    if not target:
        detected = _detect_target_field(message)
        target = detected
    if target:
        root = target.split(".")[0]
        matched = []
        for item in results:
            item_target = str(item.get("target_field") or "")
            if item_target == target or item_target.split(".")[0] == root:
                matched.append(item)
        if matched:
            return matched
    return results[:1] if len(results) == 1 else []


def _extract_requested_value(text: str, target: str) -> tuple[Any | None, str | None]:
    if target.endswith("accuracy_grade"):
        grade = re.search(r"([123])\s*级", text)
        if grade:
            return f"{grade.group(1)}级", None
    if target == "end_grinding":
        binary = re.search(r"(?:改成|改为|设置为|设为|调整到|为)?\s*([01])(?:\D|$)", text)
        if binary:
            return END_GRINDING_GROUND if binary.group(1) == "1" else END_GRINDING_NOT_GROUND, None
        return normalize_end_grinding(text), None
    if target == "end_type":
        binary = re.search(r"(?:改成|改为|设置为|设为|调整到|为)?\s*([01])(?:\D|$)", text)
        if binary:
            return END_TYPE_TIGHT if binary.group(1) == "1" else END_TYPE_NOT_TIGHT, None
        if "不压并" in text:
            return END_TYPE_NOT_TIGHT, None
        if "压并" in text:
            return END_TYPE_TIGHT, None
        return normalize_end_type(text), None
    if target == "handedness":
        if "左旋" in text or re.search(r"\bleft\b", text, re.IGNORECASE):
            return "left", None
        if "右旋" in text or re.search(r"\bright\b", text, re.IGNORECASE):
            return "right", None
        return None, None

    patterns = (
        r"(?:改成|改为|设置为|设为|调整到|调到|变成|换成|增加到|减小到|降低到|提高到)\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z/]+|毫米|mm|N/mm|N|圈)?",
        r"(?:到|为)\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z/]+|毫米|mm|N/mm|N|圈)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _to_number(match.group(1)), _normalize_unit(match.group(2))

    cleaned = re.sub(r"\b[fh]\d+\b", "", text, flags=re.IGNORECASE)
    numbers = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
    if len(numbers) == 1:
        unit_match = re.search(r"(N/mm|mm|毫米|N|圈)", text, re.IGNORECASE)
        return _to_number(numbers[0]), _normalize_unit(unit_match.group(1) if unit_match else None)
    return None, None


def _extract_multiple_requested_changes(text: str) -> list[tuple[str, Any, str | None]]:
    changes: list[tuple[str, Any, str | None]] = []
    for segment in re.split(r"[，,；;。\n]+", text):
        segment = segment.strip()
        if not segment:
            continue
        target = _detect_target_field(segment)
        if not target:
            continue
        value, unit = _extract_requested_value(segment, target)
        if value is None:
            continue
        changes.append((target, value, unit))
    deduped: dict[str, tuple[str, Any, str | None]] = {}
    for item in changes:
        deduped[item[0]] = item
    return list(deduped.values())


def _extract_proposal_constraints(review: dict[str, Any], text: str) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for segment in re.split(r"[，,；;。\n]+", text):
        target = _detect_target_field(segment)
        if not target:
            continue
        if "保持不变" in segment or "维持不变" in segment:
            value = _current_value(review, target)
            if value not in (None, ""):
                constraints.append(
                    {
                        "type": "proposal_constraint",
                        "target_field": target,
                        "operator": "equal",
                        "constraint_value": value,
                        "unit": _target_unit(review, target),
                        "description": f"{_target_label(target)}保持当前值 {_format_value(value, _target_unit(review, target))}",
                    }
                )
            continue
        match = re.search(r"(?:不能超过|不超过|不得超过|最多(?:为|到)?)\s*(-?\d+(?:\.\d+)?)", segment)
        operator = "max"
        if not match:
            match = re.search(r"(?:不能低于|不低于|至少(?:为|到)?)\s*(-?\d+(?:\.\d+)?)", segment)
            operator = "min"
        if not match:
            continue
        value = _to_number(match.group(1))
        unit_match = re.search(r"(N/mm|mm|毫米|N|圈)", segment, re.IGNORECASE)
        unit = _normalize_unit(unit_match.group(1) if unit_match else None) or _target_unit(review, target)
        constraints.append(
            {
                "type": "proposal_constraint",
                "target_field": target,
                "operator": operator,
                "constraint_value": value,
                "unit": unit,
                "description": f"{_target_label(target)}{'不超过' if operator == 'max' else '不低于'}{_format_value(value, unit)}",
            }
        )
    return constraints


def _retrieve_references(review: dict[str, Any], target: str | None, query: str) -> list[dict[str, Any]]:
    selected_standard = (review.get("standard_selection") or {}).get("selected_standard")
    if not selected_standard:
        return []
    target_fields = [target.split(".")[0]] if target else []
    chunks = retrieve_standard_chunks(
        standard_no=selected_standard,
        spring_type=review.get("drawing_summary", {}).get("spring_type") or "compression_spring",
        spring_features=review.get("spring_features") or {},
        target_fields=target_fields,
        query=query,
        limit=3,
    )
    return [chunk_reference(chunk, standard_no=selected_standard) for chunk in chunks]


def _retrieve_plan_references(review: dict[str, Any], query: str, target_fields: list[str]) -> list[dict[str, Any]]:
    selected_standard = (review.get("standard_selection") or {}).get("selected_standard")
    if not selected_standard:
        return []
    chunks = retrieve_standard_chunks(
        standard_no=selected_standard,
        spring_type=review.get("drawing_summary", {}).get("spring_type") or "compression_spring",
        spring_features=review.get("spring_features") or {},
        target_fields=target_fields,
        query=f"{query} 标准化 公差 精度 完整方案",
        limit=6,
    )
    return [chunk_reference(chunk, standard_no=selected_standard) for chunk in chunks]


def _plan_target_fields(review: dict[str, Any]) -> list[str]:
    parameters = review.get("spring_parameters") or {}
    result_targets = [
        str(item.get("target_field") or "").split(".")[0]
        for item in review.get("standardization_results", []) or []
        if isinstance(item, dict) and item.get("target_field")
    ]
    filled_fields = [
        field
        for field, value in parameters.items()
        if field != "load_points" and isinstance(value, dict) and value.get("value") not in (None, "")
    ]
    load_fields = [
        f"load_points.{point.get('label') or f'F{index}'}.force"
        for index, point in enumerate(parameters.get("load_points", []) or [], start=1)
        if isinstance(point, dict)
    ]
    return list(dict.fromkeys([*PLAN_TARGET_FIELDS, *filled_fields, *result_targets, *load_fields]))


def _references_from_result(item: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = item.get("metadata") or {}
    references = metadata.get("rag_references") or metadata.get("standard_references") or []
    return references if isinstance(references, list) else []


def _current_value(review: dict[str, Any], target: str) -> Any:
    if target.startswith("load_points."):
        parts = target.split(".")
        label = parts[1] if len(parts) > 1 else ""
        field = parts[2] if len(parts) > 2 else "force"
        for point in review.get("spring_parameters", {}).get("load_points", []) or []:
            if str(point.get("label") or "").upper() == label.upper():
                return point.get(field)
        return None
    value = review.get("spring_parameters", {}).get(target)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _target_unit(review: dict[str, Any], target: str) -> str | None:
    if target.startswith("load_points."):
        return "mm" if target.endswith(".height") else "N"
    value = review.get("spring_parameters", {}).get(target)
    if isinstance(value, dict):
        return value.get("unit")
    return None


def _affected_fields(target: str) -> list[str]:
    root = target.split(".")[0]
    mapping = {
        "wire_diameter": ["standard_selection", "mean_diameter", "spring_index", "solid_height", "diameter_tolerance"],
        "outer_diameter": ["mean_diameter", "spring_index", "diameter_tolerance"],
        "inner_diameter": ["mean_diameter", "spring_index", "diameter_tolerance"],
        "mean_diameter": ["spring_index", "slenderness_ratio", "diameter_tolerance"],
        "free_length": ["slenderness_ratio", "load_point_deflections", "free_length_tolerance", "perpendicularity"],
        "total_coils": ["total_coils_tolerance", "solid_height"],
        "active_coils": ["load_tolerance", "stiffness_tolerance"],
        "load_points": ["load_point_deflections", "load_tolerance"],
        "spring_rate": ["stiffness_tolerance"],
        "accuracy_grade": ["diameter_tolerance", "free_length_tolerance", "load_tolerance", "stiffness_tolerance"],
    }
    return mapping.get(root, ["standard_selection", "derived_parameters", "standardization_results"])


def _format_suggestion(item: dict[str, Any]) -> str:
    value = item.get("suggested_value")
    unit = item.get("unit") or ""
    upper = item.get("suggested_tolerance_upper")
    lower = item.get("suggested_tolerance_lower")
    value_text = _format_value(value, unit)
    if upper is None and lower is None:
        return value_text
    upper_number = _safe_float(upper)
    lower_number = _safe_float(lower)
    if upper_number is not None and lower_number is not None and upper_number == abs(lower_number):
        return f"{value_text} ±{abs(upper_number):g}{unit if value in (None, '') else ''}"
    return f"{value_text}，上偏差 {upper}，下偏差 {lower}"


def _format_current_value(value: Any) -> str:
    if value in (None, ""):
        return "当前未填写"
    return str(value)


def _format_value(value: Any, unit: str | None = None) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{unit or ''}"


def _join_labels(fields: list[str]) -> str:
    return "、".join(_target_label(field) for field in fields)


def _target_label(field: str | None) -> str:
    if not field:
        return ""
    if field.startswith("load_points."):
        parts = field.split(".")
        if len(parts) > 2 and parts[2] == "height":
            return f"载荷测试点 {parts[1]} 高度"
        if len(parts) > 2 and parts[2] == "force":
            return f"载荷测试点 {parts[1]} 力值"
        return f"载荷测试点 {parts[1]}" if len(parts) > 1 else "载荷测试点"
    labels = {
        "standard_selection": "标准选择",
        "derived_parameters": "派生参数",
        "standardization_results": "标准化建议",
        "diameter_tolerance": "直径公差",
        "free_length_tolerance": "自由长度公差",
        "total_coils_tolerance": "总圈数公差",
        "load_tolerance": "载荷公差",
        "stiffness_tolerance": "刚度公差",
        "load_point_deflections": "载荷变形量",
    }
    return FIELD_LABELS.get(field) or labels.get(field) or field


def _to_number(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    text = unit.strip()
    if text == "毫米":
        return "mm"
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
