from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .end_conditions import normalize_end_grinding, normalize_end_type
from .generation_readiness import assess_generation_readiness
from .spring_feasibility import assess_parameter_change_set, assess_parameter_reasonableness
from .spring_templates import FIELD_LABELS
from .standard_knowledge import chunk_reference, retrieve_standard_chunks
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
    "end_type": ("端部形式", "端部", "端型", "并紧", "不并紧", "闭口", "开口"),
    "end_grinding": ("端面磨削", "端面磨平", "两端磨平", "两端磨削", "两端不磨削", "磨平", "不磨"),
    "spring_rate": ("刚度", "弹簧刚度", "k"),
    "perpendicularity": ("垂直度",),
    "straightness": ("直线度",),
    "load_points": ("载荷", "负荷", "力值", "压力", "F1", "F2", "F3"),
    "accuracy_grade": ("精度", "精度等级", "等级"),
}

EXPLANATION_WORDS = ("为什么", "依据", "怎么", "如何", "怎么算", "哪里来", "来源", "标准", "公差")
CHANGE_WORDS = ("太小", "太大", "偏小", "偏大", "过小", "过大", "低了", "高了", "改", "调整", "设为", "设置", "换成", "增加", "减小", "降低", "提高")
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


def standardization_chat_context_needs_refresh(review: dict[str, Any], message: str) -> dict[str, Any]:
    """Decide whether a chat turn needs fresh deterministic standardization context."""
    text = str(message or "").strip()
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
) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        raise ValueError("message is required.")

    review["parameter_reasonableness"] = assess_parameter_reasonableness(review)

    raw_supplements = supplements if isinstance(supplements, dict) else {}
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
        "missing_context",
        "generation_readiness",
        "parameter_reasonableness",
    }:
        result = _run_llm_chat(review, text, result, llm_engine=llm_engine)

    _attach_proposal_feasibility(review, result)

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
    if result.get("generation_readiness"):
        turn["generation_readiness"] = result["generation_readiness"]
    if result.get("llm_chat"):
        turn["llm_chat"] = result["llm_chat"]
    if result.get("diagnostics"):
        turn["diagnostics"] = result["diagnostics"]
    review.setdefault("standardization_chat", [])
    review["standardization_chat"].append(turn)
    result["turn"] = turn
    result["review"] = review
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
    parameter_actions = [item for item in actions if item.get("type") == "propose_parameter_patch"]
    if not parameter_actions:
        return

    for action in parameter_actions:
        validation = assess_parameter_change_set(review, [action])
        action["validation"] = validation
        metadata = action.setdefault("metadata", {})
        metadata["feasibility_status"] = validation["status"]
        metadata["feasibility_can_apply"] = validation["status"] != "blocked"

    proposal_validation = assess_parameter_change_set(review, parameter_actions)
    result["proposal_validation"] = proposal_validation
    if proposal_validation["status"] == "blocked":
        result["reply"] = (
            f"{result.get('reply') or ''}\n\n"
            f"变更预检未通过：{proposal_validation['summary']} 请调整目标值后再确认。"
        ).strip()
    elif proposal_validation["status"] == "warning":
        result["reply"] = (
            f"{result.get('reply') or ''}\n\n"
            f"变更预检提示：{proposal_validation['summary']}"
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
    readiness = assess_generation_readiness(review)
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
        return normalize_end_grinding(text), None
    if target == "end_type":
        return normalize_end_type(text), None

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
