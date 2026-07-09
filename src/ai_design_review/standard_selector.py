from __future__ import annotations

import re
from typing import Any

from .standard_knowledge import standard_references


COLD_COILED_STANDARD = "GB/T 1239.2-2009"
HOT_COILED_STANDARD = "GB/T 23934-2014"

COLD_COILED_LABEL = "冷卷圆柱螺旋压缩弹簧"
HOT_COILED_LABEL = "热卷圆柱螺旋压缩弹簧"
WIRE_DIAMETER_THRESHOLD_MM = 8.0

SUPPORTED_STANDARDS = {
    COLD_COILED_STANDARD: {
        "label": COLD_COILED_LABEL,
        "manufacturing_method": "cold_coiled",
        "rules_available": True,
    },
    HOT_COILED_STANDARD: {
        "label": HOT_COILED_LABEL,
        "manufacturing_method": "hot_coiled",
        "rules_available": False,
    },
}


def select_standard(
    spring_type: str,
    spring_parameters: dict[str, Any],
    spring_features: dict[str, Any] | None = None,
    llm_inference: dict[str, Any] | None = None,
    technical_requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    features = spring_features or {}
    inference = _inference_value(llm_inference)
    auxiliary = _auxiliary_context(features, inference, technical_requirements)
    wire_rule = _wire_diameter_rule(spring_parameters)
    evidence: list[str] = []
    candidate_standards = _candidate_standards()

    if spring_type != "compression_spring":
        return _selection(
            selected_standard=None,
            status="not_applicable",
            confidence=0,
            selection_source="spring_type",
            reason="当前标准选择器只支持压缩弹簧。",
            evidence=evidence,
            need_human_review=False,
            candidate_standards=candidate_standards,
            metadata={},
        )

    unsupported = _unsupported_scope(features)
    if unsupported:
        return _selection(
            selected_standard=None,
            status="not_applicable",
            confidence=unsupported["confidence"],
            selection_source=unsupported["source"],
            reason=unsupported["reason"],
            evidence=unsupported["evidence"],
            need_human_review=True,
            candidate_standards=candidate_standards,
            metadata={},
        )

    standard_no = _standard_no(_param_value(spring_parameters, "standard_no"))
    if standard_no:
        evidence.append(f"图纸标准号：{standard_no}")
        if _is_cold_standard(standard_no):
            conflicts = _method_conflicts("cold_coiled", wire_rule=wire_rule, auxiliary=auxiliary)
            need_review = bool(conflicts)
            return _selection(
                selected_standard=COLD_COILED_STANDARD,
                status="need_review" if need_review else "applicable",
                confidence=0.96,
                selection_source="drawing_standard_no",
                reason=_reason_with_conflicts("图纸标准号指向冷卷圆柱螺旋压缩弹簧标准。", conflicts),
                evidence=[*evidence, *auxiliary["evidence"]],
                need_human_review=need_review,
                candidate_standards=candidate_standards,
                metadata=_selection_metadata(wire_rule, auxiliary, conflicts),
            )
        if _is_hot_standard(standard_no):
            conflicts = _method_conflicts("hot_coiled", wire_rule=wire_rule, auxiliary=auxiliary)
            return _selection(
                selected_standard=HOT_COILED_STANDARD,
                status="rules_pending",
                confidence=0.96,
                selection_source="drawing_standard_no",
                reason=_reason_with_conflicts(
                    "图纸标准号指向热卷圆柱螺旋压缩弹簧标准；热卷 JSON 规则包尚未接入，暂不计算公差。",
                    conflicts,
                ),
                evidence=[*evidence, *auxiliary["evidence"]],
                need_human_review=True,
                candidate_standards=candidate_standards,
                metadata=_selection_metadata(wire_rule, auxiliary, conflicts),
            )
        return _selection(
            selected_standard=standard_no,
            status="not_applicable",
            confidence=0.88,
            selection_source="drawing_standard_no",
            reason="图纸标准号不在当前已支持的冷卷/热卷圆柱螺旋压缩弹簧标准范围内。",
            evidence=evidence,
            need_human_review=True,
            candidate_standards=candidate_standards,
            metadata={},
        )

    if wire_rule:
        return _by_wire_diameter(
            wire_rule,
            auxiliary=auxiliary,
            candidate_standards=candidate_standards,
        )

    method = _normalized_method(_feature_value(features, "manufacturing_method"))
    method_confidence = _feature_confidence(features, "manufacturing_method", default=0.7)
    if method in {"cold_coiled", "hot_coiled"}:
        evidence.append(_feature_evidence(features, "manufacturing_method") or f"制造方式：{method}")
        return _by_method(
            method,
            confidence=method_confidence,
            selection_source="recognized_feature",
            evidence=evidence,
            candidate_standards=candidate_standards,
            reason_suffix="来自图纸文字/语义识别。",
            metadata=_selection_metadata(None, auxiliary, []),
        )

    inferred_standard = _standard_no(inference.get("selected_standard") or inference.get("recommended_standard"))
    inferred_method = _normalized_method(inference.get("manufacturing_method"))
    inference_confidence = _confidence(inference.get("confidence"), default=0.0)
    inference_evidence = _list_text(inference.get("evidence"))
    if inference_evidence:
        evidence.extend(inference_evidence)
    reason = str(inference.get("reason") or "").strip()
    if reason:
        evidence.append(reason)

    if inferred_standard:
        if _is_cold_standard(inferred_standard):
            inferred_method = "cold_coiled"
        elif _is_hot_standard(inferred_standard):
            inferred_method = "hot_coiled"

    if inferred_method in {"cold_coiled", "hot_coiled"}:
        return _by_method(
            inferred_method,
            confidence=inference_confidence,
            selection_source="llm_inference",
            evidence=evidence,
            candidate_standards=candidate_standards,
            reason_suffix="来自 LLM 对冷卷/热卷的结构化判断。",
            llm_need_review=bool(inference.get("need_human_review")),
            metadata=_selection_metadata(None, auxiliary, []),
        )

    return _selection(
        selected_standard=None,
        status="need_review",
        confidence=0.0,
        selection_source="insufficient_context",
        reason="未识别到标准号，也没有可靠的冷卷/热卷判断，需人工选择适用标准。",
        evidence=[*evidence, *auxiliary["evidence"]],
        need_human_review=True,
        candidate_standards=candidate_standards,
        metadata=_selection_metadata(None, auxiliary, []),
    )


def _by_wire_diameter(
    wire_rule: dict[str, Any],
    *,
    auxiliary: dict[str, Any],
    candidate_standards: list[dict[str, Any]],
) -> dict[str, Any]:
    method = wire_rule["method"]
    selected_standard = COLD_COILED_STANDARD if method == "cold_coiled" else HOT_COILED_STANDARD
    rules_available = bool(SUPPORTED_STANDARDS[selected_standard]["rules_available"])
    conflicts = _method_conflicts(method, wire_rule=None, auxiliary=auxiliary)
    has_supporting_auxiliary = any(item == method for item in auxiliary["methods"])
    confidence = wire_rule["confidence"] + (0.05 if has_supporting_auxiliary else 0.0)
    confidence = min(0.95, confidence)
    need_human_review = bool(wire_rule["need_human_review"] or conflicts or not rules_available)
    status = "rules_pending" if not rules_available else ("need_review" if need_human_review else "applicable")
    if not rules_available:
        reason = f"{wire_rule['evidence']}，判断为{SUPPORTED_STANDARDS[selected_standard]['label']}；热卷 JSON 规则包尚未接入，暂不计算公差。"
    elif conflicts:
        reason = f"{wire_rule['evidence']}，但辅助证据存在冲突，需人工确认。"
    elif wire_rule["need_human_review"]:
        reason = f"{wire_rule['evidence']}，但线径识别置信度或确认状态不足，需人工确认。"
    else:
        reason = f"{wire_rule['evidence']}。"
    return _selection(
        selected_standard=selected_standard,
        status=status,
        confidence=confidence,
        selection_source="wire_diameter_threshold",
        reason=reason,
        evidence=[wire_rule["evidence"], *auxiliary["evidence"]],
        need_human_review=need_human_review,
        candidate_standards=candidate_standards,
        metadata=_selection_metadata(wire_rule, auxiliary, conflicts),
    )


def _by_method(
    method: str,
    *,
    confidence: float,
    selection_source: str,
    evidence: list[str],
    candidate_standards: list[dict[str, Any]],
    reason_suffix: str,
    llm_need_review: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_standard = COLD_COILED_STANDARD if method == "cold_coiled" else HOT_COILED_STANDARD
    rules_available = bool(SUPPORTED_STANDARDS[selected_standard]["rules_available"])
    status = "applicable" if rules_available else "rules_pending"
    need_human_review = bool(llm_need_review or confidence < 0.78 or not evidence or not rules_available)
    if not rules_available:
        reason = f"判断为{SUPPORTED_STANDARDS[selected_standard]['label']}，但对应 JSON 规则包尚未接入，暂不计算公差。"
    elif need_human_review:
        reason = f"推荐使用{selected_standard}；{reason_suffix} 但置信度或证据不足，需人工确认。"
        status = "need_review"
    else:
        reason = f"推荐使用{selected_standard}；{reason_suffix}"
    return _selection(
        selected_standard=selected_standard,
        status=status,
        confidence=confidence,
        selection_source=selection_source,
        reason=reason,
        evidence=evidence,
        need_human_review=need_human_review,
        candidate_standards=candidate_standards,
        metadata=metadata or {},
    )


def _unsupported_scope(features: dict[str, Any]) -> dict[str, Any] | None:
    checks = [
        ("spring_family", {"disc", "wave", "rubber", "gas"}, "识别到非螺旋类压缩弹簧，当前冷卷/热卷圆柱螺旋标准不适用。"),
        ("spring_shape", {"conical", "barrel", "hourglass"}, "识别到非圆柱压缩弹簧，当前仅支持圆柱螺旋压缩弹簧。"),
        ("wire_section", {"rectangular", "square"}, "识别到非圆截面弹簧，当前冷卷/热卷圆柱螺旋规则不适用。"),
        ("pitch_type", {"variable"}, "识别到变节距弹簧，当前冷卷/热卷圆柱螺旋规则暂不适用。"),
    ]
    for field, unsupported_values, reason in checks:
        value = _normalized_token(_feature_value(features, field))
        if value in unsupported_values:
            return {
                "reason": reason,
                "confidence": _feature_confidence(features, field, default=0.7),
                "source": f"spring_features.{field}",
                "evidence": [_feature_evidence(features, field) or f"{field}={value}"],
            }
    return None


def _selection(
    *,
    selected_standard: str | None,
    status: str,
    confidence: float,
    selection_source: str,
    reason: str,
    evidence: list[str],
    need_human_review: bool,
    candidate_standards: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    standard_info = SUPPORTED_STANDARDS.get(selected_standard or "", {})
    return {
        "selected_standard": selected_standard,
        "standard_label": standard_info.get("label", ""),
        "candidate_standards": candidate_standards,
        "status": status,
        "confidence": round(max(0.0, min(0.99, float(confidence or 0))), 3),
        "selection_source": selection_source,
        "reason": reason,
        "evidence": [item for item in evidence if item],
        "need_human_review": need_human_review,
        "rules_available": bool(standard_info.get("rules_available", False)),
        "references": _references(selected_standard),
        "metadata": metadata or {},
    }


def _wire_diameter_rule(spring_parameters: dict[str, Any]) -> dict[str, Any] | None:
    wire = _number(_param_value(spring_parameters, "wire_diameter"))
    if wire is None:
        return None
    method = "hot_coiled" if wire >= WIRE_DIAMETER_THRESHOLD_MM else "cold_coiled"
    operator = ">=" if method == "hot_coiled" else "<"
    method_label = "热卷" if method == "hot_coiled" else "冷卷"
    confidence = _param_confidence(spring_parameters, "wire_diameter", default=0.84)
    need_review = _param_need_review(spring_parameters, "wire_diameter") or confidence < 0.75
    if need_review:
        confidence = min(confidence, 0.74)
    return {
        "method": method,
        "wire_diameter_mm": wire,
        "threshold_mm": WIRE_DIAMETER_THRESHOLD_MM,
        "confidence": confidence,
        "need_human_review": need_review,
        "evidence": f"线径 d={wire:g}mm {operator} {WIRE_DIAMETER_THRESHOLD_MM:g}mm，按公司线径规则推荐{method_label}",
    }


def _auxiliary_context(
    features: dict[str, Any],
    inference: dict[str, Any],
    technical_requirements: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    evidence: list[str] = []
    methods: list[str] = []
    feature_method = _normalized_method(_feature_value(features, "manufacturing_method"))
    if feature_method in {"cold_coiled", "hot_coiled"}:
        methods.append(feature_method)
        evidence.append(_feature_evidence(features, "manufacturing_method") or f"制造方式辅助证据：{feature_method}")

    inferred_standard = _standard_no(inference.get("selected_standard") or inference.get("recommended_standard"))
    inferred_method = _normalized_method(inference.get("manufacturing_method"))
    if inferred_standard:
        if _is_cold_standard(inferred_standard):
            inferred_method = "cold_coiled"
        elif _is_hot_standard(inferred_standard):
            inferred_method = "hot_coiled"
    if inferred_method in {"cold_coiled", "hot_coiled"}:
        methods.append(inferred_method)
    evidence.extend(_list_text(inference.get("evidence")))
    reason = str(inference.get("reason") or "").strip()
    if reason:
        evidence.append(reason)

    for item in technical_requirements or []:
        content = str(item.get("content") or item.get("value") or "").strip()
        if not content:
            continue
        if item.get("type") in {"heat_treatment", "process", "other"}:
            evidence.append(f"{_requirement_type_label(item.get('type'))}：{content}")
        text_method = _method_from_text(content)
        if text_method:
            methods.append(text_method)

    return {
        "evidence": _dedupe(evidence),
        "methods": _dedupe(methods),
    }


def _method_conflicts(
    selected_method: str,
    *,
    wire_rule: dict[str, Any] | None,
    auxiliary: dict[str, Any],
) -> list[str]:
    conflicts: list[str] = []
    if wire_rule and wire_rule.get("method") and wire_rule["method"] != selected_method:
        conflicts.append(f"线径规则推荐{_method_label(wire_rule['method'])}，与当前选择{_method_label(selected_method)}不一致。")
    for method in auxiliary.get("methods", []):
        if method != selected_method:
            conflicts.append(f"辅助证据推荐{_method_label(method)}，与当前选择{_method_label(selected_method)}不一致。")
    return _dedupe(conflicts)


def _selection_metadata(
    wire_rule: dict[str, Any] | None,
    auxiliary: dict[str, Any],
    conflicts: list[str],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "threshold_mm": WIRE_DIAMETER_THRESHOLD_MM,
        "auxiliary_evidence": auxiliary.get("evidence", []),
        "conflicts": conflicts,
    }
    if wire_rule:
        metadata["wire_diameter_mm"] = wire_rule.get("wire_diameter_mm")
        metadata["wire_diameter_threshold_mm"] = wire_rule.get("threshold_mm")
        metadata["wire_diameter_method"] = wire_rule.get("method")
        metadata["wire_diameter_need_human_review"] = wire_rule.get("need_human_review")
    return metadata


def _reason_with_conflicts(reason: str, conflicts: list[str]) -> str:
    if not conflicts:
        return reason
    return f"{reason} 但存在辅助/线径证据冲突，需人工确认。"


def _candidate_standards() -> list[dict[str, Any]]:
    return [
        {
            "standard_no": standard_no,
            "label": info["label"],
            "manufacturing_method": info["manufacturing_method"],
            "rules_available": bool(info["rules_available"]),
        }
        for standard_no, info in SUPPORTED_STANDARDS.items()
    ]


def _references(standard_no: str | None) -> list[dict[str, Any]]:
    if not standard_no:
        return []
    references = standard_references(standard_no, limit=5)
    if references:
        return references
    return [
        {
            "standard_no": standard_no,
            "source": "local_standard_knowledge",
            "status": "missing",
            "note": "当前标准知识库未检索到对应标准条款。",
        }
    ]


def _param_value(mapping: dict[str, Any], field: str) -> Any:
    value = mapping.get(field)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _feature_value(features: dict[str, Any], field: str) -> Any:
    value = features.get(field)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _feature_confidence(features: dict[str, Any], field: str, default: float) -> float:
    value = features.get(field)
    if isinstance(value, dict):
        return _confidence(value.get("confidence"), default=default)
    return default


def _feature_evidence(features: dict[str, Any], field: str) -> str:
    value = features.get(field)
    if isinstance(value, dict):
        return str(value.get("evidence") or value.get("suggested_region") or "").strip()
    return ""


def _param_confidence(mapping: dict[str, Any], field: str, default: float) -> float:
    value = mapping.get(field)
    if isinstance(value, dict):
        return _confidence(value.get("confidence"), default=default)
    return default


def _param_need_review(mapping: dict[str, Any], field: str) -> bool:
    value = mapping.get(field)
    return bool(isinstance(value, dict) and value.get("need_human_review"))


def _inference_value(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    raw = value.get("value") if "value" in value else value
    return raw if isinstance(raw, dict) else {}


def _standard_no(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if _is_cold_standard(text):
        return COLD_COILED_STANDARD
    if _is_hot_standard(text):
        return HOT_COILED_STANDARD
    return text


def _is_cold_standard(text: str) -> bool:
    return bool(re.search(r"GB\s*/?\s*T\s*1239\.?2(?:\s*[-—－]?\s*2009)?", text, re.IGNORECASE))


def _is_hot_standard(text: str) -> bool:
    return bool(re.search(r"GB\s*/?\s*T\s*23934(?:\s*[-—－]?\s*2014)?", text, re.IGNORECASE))


def _normalized_method(value: Any) -> str:
    text = _normalized_token(value)
    mapping = {
        "cold": "cold_coiled",
        "cold_coil": "cold_coiled",
        "cold_coiled": "cold_coiled",
        "cold_formed": "cold_coiled",
        "hot": "hot_coiled",
        "hot_coil": "hot_coiled",
        "hot_coiled": "hot_coiled",
        "hot_formed": "hot_coiled",
        "冷卷": "cold_coiled",
        "冷绕": "cold_coiled",
        "冷成形": "cold_coiled",
        "热卷": "hot_coiled",
        "热绕": "hot_coiled",
        "热成形": "hot_coiled",
    }
    return mapping.get(text, text)


def _normalized_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    return text


def _confidence(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(0.99, number))


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _method_from_text(text: str) -> str | None:
    lowered = text.lower()
    if re.search(r"(热卷|热绕|热成形|hot\s*(?:coiled|formed|wound))", lowered):
        return "hot_coiled"
    if re.search(r"(冷卷|冷绕|冷成形|cold\s*(?:coiled|formed|wound))", lowered):
        return "cold_coiled"
    return None


def _method_label(method: str) -> str:
    return {
        "cold_coiled": "冷卷",
        "hot_coiled": "热卷",
    }.get(method, method)


def _requirement_type_label(value: Any) -> str:
    return {
        "heat_treatment": "热处理",
        "process": "工艺要求",
        "other": "其他要求",
    }.get(str(value or ""), "辅助证据")


def _dedupe(items: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        if item in (None, ""):
            continue
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
