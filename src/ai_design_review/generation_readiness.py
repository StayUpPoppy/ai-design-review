from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from .generation_contract import (
    COMPRESSION_GENERATION_LABELS,
    COMPRESSION_GENERATION_INPUT_FIELDS,
    GENERATION_SCHEMA_VERSION,
    apply_generation_defaults,
    export_generation_parameters,
    generation_parameter_state,
    validate_generation_parameters,
)
from .spring_templates import FIELD_LABELS
from .spring_feasibility import assess_parameter_reasonableness
from .load_points import (
    canonical_load_point_label,
    ensure_load_point_ids,
    load_point_is_complete,
    load_point_is_confirmed,
    normalize_load_point_label,
)
from .technical_requirements import canonical_technical_requirement_key


def assess_generation_readiness(review: dict[str, Any]) -> dict[str, Any]:
    """Check whether confirmed review data can be safely handed to a drawing generator."""
    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "unknown_spring")
    if spring_type != "compression_spring":
        return {
            "status": "not_applicable",
            "summary": "当前仅支持圆柱螺旋压缩弹簧生成参数包。",
            "missing_fields": [],
            "pending_fields": [],
            "warnings": [],
            "confirmed_core_count": 0,
            "core_field_count": 0,
        }

    defaulted_fields = apply_generation_defaults(review)
    ensure_load_point_ids(review)
    parameters = review.get("spring_parameters") or {}
    # Generation export is a release boundary, so always recalculate instead of
    # trusting a diagnostic that may predate an external/manual parameter edit.
    reasonableness = assess_parameter_reasonableness(review)
    blocking_reasonableness = [
        item for item in reasonableness.get("issues", [])
        if isinstance(item, dict) and item.get("severity") == "blocked"
    ]
    blocking_reasonableness.extend(validate_generation_parameters(parameters))
    missing: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    confirmed_count = 0

    for field in COMPRESSION_GENERATION_INPUT_FIELDS:
        state = generation_parameter_state(parameters, field)
        if state == "missing":
            missing.append(_field_issue(field, "缺少重新生图所需的核心参数。"))
        elif state == "pending":
            pending.append(_field_issue(field, "参数已有值，但仍需人工确认。"))
        elif state == "invalid":
            continue
        else:
            confirmed_count += 1

    _append_standardization_warnings(review, warnings)
    _append_technical_requirement_state(review, pending)
    _append_load_point_state(review, pending)

    if blocking_reasonableness:
        status = "blocked"
        summary = reasonableness.get("summary") or "存在无法直接采用的参数矛盾。"
    elif missing:
        status = "needs_input"
        summary = f"还缺少 {len(missing)} 项生成必填信息。"
    elif pending:
        status = "needs_confirmation"
        summary = f"核心尺寸已齐，但还有 {len(pending)} 项需要人工确认。"
    elif warnings:
        status = "ready_with_warnings"
        summary = "参数包可以生成，但存在需要在生图前知悉的风险提示。"
    else:
        status = "ready"
        summary = "核心参数和技术要求均已确认，可生成参数包。"

    return {
        "status": status,
        "summary": summary,
        "missing_fields": missing,
        "pending_fields": pending,
        "warnings": warnings,
        "confirmed_core_count": confirmed_count,
        "core_field_count": len(COMPRESSION_GENERATION_INPUT_FIELDS),
        "defaulted_fields": defaulted_fields,
        "parameter_reasonableness": reasonableness,
        "blocking_reasonableness": blocking_reasonableness,
    }


def build_generation_parameter_package(review: dict[str, Any]) -> dict[str, Any]:
    """Build a compact drawing package from the fields the reviewer has confirmed."""

    apply_generation_defaults(review)
    ensure_load_point_ids(review)
    parameters = review.get("spring_parameters") or {}
    confirmed_parameters = export_generation_parameters(parameters)
    technical_requirements = [
        _generation_requirement(item)
        for item in review.get("technical_requirements") or []
        if _technical_requirement_is_confirmed(item)
    ]
    load_points: list[dict[str, Any]] = []
    exported_load_point_labels: set[str] = set()
    for item in parameters.get("load_points") or []:
        if not load_point_is_complete(item) or not load_point_is_confirmed(item):
            continue
        canonical_label = canonical_load_point_label(item.get("label"))
        if not canonical_label or canonical_label in exported_load_point_labels:
            continue
        exported_load_point_labels.add(canonical_label)
        load_points.append(_generation_load_point(item))
    selection = review.get("standard_selection") or {}
    summary = review.get("drawing_summary") or {}
    return {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "package_type": "confirmed_compression_spring_generation_input",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "export_policy": {
            "parameter_filter": "frozen_compression_inputs_v1_human_confirmed_only",
            "readiness_is_advisory": True,
        },
        "source": {
            "drawing_no": summary.get("drawing_no"),
            "drawing_name": summary.get("drawing_name"),
            "spring_type": summary.get("spring_type"),
            "spring_type_label": summary.get("spring_type_label"),
        },
        "standard_context": {
            "selected_standard": selection.get("selected_standard"),
            "selection_status": selection.get("status"),
            "human_confirmed": bool(selection.get("human_confirmed")),
        },
        "generation_parameters": {
            "spring_parameters": confirmed_parameters,
            "load_points": load_points,
            "technical_requirements": technical_requirements,
        },
        "derived_parameters": _export_derived_parameters(review, parameters),
    }


def _append_standardization_warnings(
    review: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    selection = review.get("standard_selection") or {}
    if not selection.get("selected_standard"):
        warnings.append(_field_issue("standard_no", "未执行或未完成标准化检查；本次可按当前人工确认参数直接生图。"))
    elif not selection.get("human_confirmed"):
        warnings.append(_field_issue("standard_no", "适用技术标准尚未人工确认；本次可按当前人工确认参数直接生图。"))

    if review.get("derived_parameters_stale"):
        warnings.append(_field_issue("standardization", "参数修改后标准化结果已过期；本次可按当前人工确认参数直接生图。", label="标准化结果"))

    for item in review.get("standardization_results") or []:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target_field") or "")
        status = str(item.get("status") or "")
        if status in {"stale", "need_context"}:
            warnings.append(_field_issue(target or "standardization", item.get("basis") or "标准化结果仍需补充或重新计算；可按当前人工确认参数直接生图。", label=_label(target) if target else "标准化结果"))
        elif status == "not_applicable":
            warnings.append(_field_issue(target or "standardization", item.get("basis") or "当前标准规则不适用，需作为特殊设计复核。", label=_label(target) if target else "标准风险"))
        elif status in {"suggested", "llm_suggested", "rules_pending", "unmapped"} or item.get("need_human_review"):
            warnings.append(_field_issue(target or "standardization", item.get("basis") or "标准化建议尚未处理；未应用的建议不会进入生图参数包。", label=_label(target) if target else "标准化建议"))


def _append_technical_requirement_state(review: dict[str, Any], pending: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(review.get("technical_requirements") or [], start=1):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        requirement_type = str(item.get("type") or "other")
        canonical = canonical_technical_requirement_key(requirement_type, content)
        duplicate = bool(content) and canonical in seen
        if content:
            seen.add(canonical)
        if content and _technical_requirement_is_confirmed(item) and not duplicate:
            continue
        if duplicate:
            reason = f"技术要求“{_technical_label(requirement_type)}”与已有内容重复，请修改或删除重复项。"
        elif content:
            reason = f"技术要求“{_technical_label(requirement_type)}”尚未人工确认。"
        else:
            reason = f"技术要求“{_technical_label(requirement_type)}”内容为空，请补充内容或删除该项。"
        issue = _field_issue(
            f"technical_requirements.{index}",
            reason,
            label=_technical_label(requirement_type),
        )
        requirement_id = str(item.get("requirement_id") or "").strip()
        if requirement_id:
            issue["requirement_id"] = requirement_id
        pending.append(issue)


def _technical_requirement_is_confirmed(item: Any) -> bool:
    """Only an explicit review decision releases a note to SolidWorks.

    Treating a missing ``need_human_review`` flag as confirmed used to make
    legacy or partially constructed notes leak into the generation package.
    New and migrated review data must explicitly store ``False`` after the
    reviewer confirms the note.
    """

    return (
        isinstance(item, dict)
        and bool(str(item.get("content") or "").strip())
        and item.get("need_human_review") is False
    )


def _append_load_point_state(review: dict[str, Any], pending: list[dict[str, Any]]) -> None:
    parameters = review.get("spring_parameters") or {}
    seen: set[str] = set()
    for index, item in enumerate(parameters.get("load_points") or [], start=1):
        if not isinstance(item, dict):
            pending.append(_field_issue(f"load_points.{index}", "载荷测试点格式无效，请删除后重新添加。", label="载荷测试点"))
            continue
        label = normalize_load_point_label(item.get("label"))
        field = f"load_points.{label or index}"
        canonical = canonical_load_point_label(label)
        duplicate = bool(canonical) and canonical in seen
        if canonical:
            seen.add(canonical)
        if duplicate:
            reason = f"载荷测试点编号“{label}”重复，请修改或删除重复项。"
        elif not label:
            reason = "载荷测试点缺少编号，请补充唯一编号或删除该项。"
        elif not load_point_is_complete(item):
            reason = f"载荷测试点“{label}”的高度和力值必须完整且有效。"
        elif not load_point_is_confirmed(item):
            reason = f"载荷测试点“{label}”尚未人工确认。"
        else:
            continue
        issue = _field_issue(field, reason, label=f"载荷测试点 {label or index}")
        point_id = str(item.get("load_point_id") or "").strip()
        if point_id:
            issue["load_point_id"] = point_id
        pending.append(issue)


def _parameter_state(parameters: dict[str, Any], field: str) -> str:
    item = parameters.get(field)
    if not isinstance(item, dict) or item.get("value") in (None, ""):
        return "missing"
    return "pending" if item.get("need_human_review") else "confirmed"


def _export_derived_parameters(review: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    """Refresh geometry-derived values from confirmed source fields at export time."""
    derived = deepcopy(review.get("derived_parameters") or {})
    for field in ("mean_diameter", "spring_index", "slenderness_ratio"):
        derived.pop(field, None)

    wire = _confirmed_number(parameters, "wire_diameter")
    outer = _confirmed_number(parameters, "outer_diameter")
    inner = _confirmed_number(parameters, "inner_diameter")
    recognized_mean = _confirmed_number(parameters, "mean_diameter")
    free_length = _confirmed_number(parameters, "free_length")

    mean = recognized_mean
    mean_formula = "drawing_or_manual_mean_diameter" if recognized_mean is not None else ""
    mean_sources = ["mean_diameter"] if recognized_mean is not None else []
    if mean is None and wire is not None and outer is not None:
        mean = outer - wire
        mean_formula = "outer_diameter - wire_diameter"
        mean_sources = ["outer_diameter", "wire_diameter"]
    elif mean is None and wire is not None and inner is not None:
        mean = inner + wire
        mean_formula = "inner_diameter + wire_diameter"
        mean_sources = ["inner_diameter", "wire_diameter"]

    if mean is not None:
        derived["mean_diameter"] = _export_derived_parameter(
            "mean_diameter", mean, "mm", mean_formula, mean_sources
        )
    if mean is not None and wire not in (None, 0):
        derived["spring_index"] = _export_derived_parameter(
            "spring_index",
            mean / wire,
            None,
            "mean_diameter / wire_diameter",
            ["mean_diameter", "wire_diameter"],
        )
    if mean not in (None, 0) and free_length is not None:
        derived["slenderness_ratio"] = _export_derived_parameter(
            "slenderness_ratio",
            free_length / mean,
            None,
            "free_length / mean_diameter",
            ["free_length", "mean_diameter"],
        )
    return derived


def _confirmed_number(parameters: dict[str, Any], field: str) -> float | None:
    if _parameter_state(parameters, field) != "confirmed":
        return None
    try:
        value = float(parameters[field]["value"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _export_derived_parameter(
    field: str,
    value: float,
    unit: str | None,
    formula: str,
    source_fields: list[str],
) -> dict[str, Any]:
    rounded = round(float(value), 4)
    return {
        "field": field,
        "value": int(rounded) if rounded.is_integer() else rounded,
        "unit": unit,
        "source": ["derived", "generation_export"],
        "formula": formula,
        "source_fields": source_fields,
        "confidence": 0.99,
        "need_human_review": False,
    }


def _generation_requirement(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": item.get("type"),
        "content": str(item.get("content") or "").strip(),
        "confirmation_source": "human_confirmed",
    }


def _generation_load_point(item: dict[str, Any]) -> dict[str, Any]:
    def number(value: Any) -> float:
        rounded = round(float(value), 3)
        return int(rounded) if rounded.is_integer() else rounded

    def optional_number(value: Any) -> float | int | None:
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            return None
        return number(candidate) if isfinite(candidate) else None

    return {
        "label": normalize_load_point_label(item.get("label")),
        "height": {"value": number(item.get("height")), "unit": "mm"},
        "force": {
            "value": number(item.get("force")),
            "unit": "N",
            "tolerance_upper": optional_number(item.get("load_tolerance_upper")),
            "tolerance_lower": optional_number(item.get("load_tolerance_lower")),
        },
        "confirmation_source": "human_confirmed",
    }


def _field_issue(field: str, reason: Any, *, label: str | None = None, alternatives: list[str] | None = None) -> dict[str, Any]:
    item = {"field": field, "label": label or _label(field), "reason": str(reason)}
    if alternatives:
        item["alternatives"] = alternatives
    return item


def _label(field: str) -> str:
    return COMPRESSION_GENERATION_LABELS.get(field, FIELD_LABELS.get(field, field))


def _technical_label(value: str) -> str:
    labels = {
        "heat_treatment": "热处理",
        "surface": "表面处理",
        "salt_spray": "盐雾",
        "lifetime": "寿命",
        "environmental": "环保",
        "hardness": "硬度",
        "process": "工艺",
        "other": "其他技术要求",
    }
    return labels.get(value, value)
