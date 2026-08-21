from __future__ import annotations

import hashlib
import json
import math
import uuid
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
from .generation_contract import apply_generation_defaults
from .generation_readiness import assess_generation_readiness
from .parameter_impact import assess_parameter_change_impact
from .spring_feasibility import assess_parameter_reasonableness
from .spring_templates import FIELD_LABELS
from .surface_terms import normalize_surface_requirement
from .standardizers import derive_active_coils
from .standardizers.coil_counts import apply_company_simple_active_coils
from .standardizers.compression import (
    apply_formula_compression_solid_height,
    calculate_compression_solid_height,
    derive_compression_parameters,
)
from .standardizers.diameters import apply_formula_compression_diameter_completion
from .standardizers.stiffness import apply_formula_compression_spring_rate
from .standardizers.stiffness import calculate_compression_spring_rate
from .technical_requirements import (
    TECHNICAL_REQUIREMENT_TYPE_LABELS,
    TECHNICAL_REQUIREMENT_TYPES,
    canonical_technical_requirement_key,
    ensure_technical_requirement_ids,
    new_technical_requirement_id,
    normalize_technical_requirement_type,
    technical_requirement_confirmation_key,
    technical_requirement_snapshot,
)
from .workflow import apply_standardization_to_review


TECHNICAL_REQUIREMENT_ACTION_TYPES = {
    "propose_technical_requirement_add",
    "propose_technical_requirement_update",
    "propose_technical_requirement_delete",
}
APPLICABLE_ACTION_TYPES = {
    "propose_parameter_patch",
    "propose_tolerance_patch",
    "proposal_constraint",
    *TECHNICAL_REQUIREMENT_ACTION_TYPES,
}
DIAMETER_FIELDS = ("wire_diameter", "mean_diameter", "outer_diameter", "inner_diameter")
DESIGN_GOAL_FIELDS = {"spring_index", "slenderness_ratio", "solid_height", "spring_rate"}
PROPOSAL_APPLYABLE_STATUSES = {"ready", "warning"}
PROPOSAL_HISTORY_LIMIT = 20

PARAMETER_RELATION_REGISTRY: dict[str, tuple[dict[str, Any], ...]] = {
    "compression_spring": (
        {"code": "diameter_group", "strategy": "automatic", "fields": list(DIAMETER_FIELDS)},
        {"code": "coil_count_relation", "strategy": "validate_only", "fields": ["total_coils", "active_coils"]},
        {"code": "active_coils_from_end", "strategy": "automatic_or_needs_choice", "fields": ["total_coils", "end_type", "support_coils", "active_coils"]},
        {"code": "solid_height", "strategy": "automatic", "fields": ["wire_diameter", "total_coils", "end_grinding"]},
        {"code": "spring_rate", "strategy": "automatic", "fields": ["material", "wire_diameter", "mean_diameter", "active_coils"]},
        {"code": "generation_contract", "strategy": "validate_only", "fields": ["handedness", "end_grinding", "end_coils_closed"]},
    ),
}


class ParameterProposalError(ValueError):
    def __init__(self, code: str, message: str, *, current: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.current = current


def parameter_state_hash(review: dict[str, Any]) -> str:
    """Hash only formal review state; chat turns and proposal drafts are excluded."""

    normalized_review = deepcopy(review)
    apply_generation_defaults(normalized_review)
    ensure_technical_requirement_ids(normalized_review)
    payload = {
        "spring_type": (normalized_review.get("drawing_summary") or {}).get("spring_type"),
        "spring_parameters": _formal_state(normalized_review.get("spring_parameters") or {}),
        "spring_features": _formal_state(normalized_review.get("spring_features") or {}),
        "technical_requirements": _formal_state(normalized_review.get("technical_requirements") or []),
        "manual_confirmations": _formal_state(normalized_review.get("manual_confirmations") or {}),
        "standard_selection": {
            "selected_standard": (normalized_review.get("standard_selection") or {}).get("selected_standard"),
            "need_human_review": (normalized_review.get("standard_selection") or {}).get("need_human_review"),
        },
    }
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def invalidate_open_parameter_change_proposals(review: dict[str, Any], *, reason: str) -> list[str]:
    """Expire open drafts after a formal input changes outside the proposal workflow."""

    invalidated: list[str] = []
    for proposal in review.get("parameter_change_proposals") or []:
        if not isinstance(proposal, dict) or proposal.get("status") not in {"needs_input", "ready", "warning", "blocked"}:
            continue
        proposal["status"] = "stale"
        proposal["summary"] = reason
        proposal["updated_at"] = _now()
        invalidated.append(str(proposal.get("proposal_id") or ""))
        _sync_proposal_turn_snapshots(review, proposal)
    if invalidated:
        review["active_parameter_change_proposal_id"] = None
    return [item for item in invalidated if item]


_VOLATILE_FORMAL_KEYS = {
    "confidence",
    "evidence",
    "formula",
    "formula_calculation_kind",
    "formula_calculation_status",
    "page",
    "position",
    "source",
    "source_fields",
    "suggested_region",
    "confirmed_at",
    "created_at",
    "updated_at",
}


def _formal_state(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _formal_state(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in _VOLATILE_FORMAL_KEYS
        }
    if isinstance(value, list):
        return [_formal_state(item) for item in value]
    return value


def build_parameter_change_proposal(
    review: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    user_goal: str,
    active_proposal_id: str | None = None,
    review_revision: int | None = None,
    clarification: str | None = None,
) -> dict[str, Any] | None:
    ensure_technical_requirement_ids(review)
    normalized_actions = [_normalize_action(deepcopy(item)) for item in actions if _is_applicable_action(item)]
    applicable = [item for item in normalized_actions if _is_applicable_action(item)]
    existing = find_parameter_change_proposal(review, active_proposal_id) if active_proposal_id else None
    if existing and existing.get("status") not in {"needs_input", "ready", "warning", "blocked"}:
        existing = None

    baseline_hash = parameter_state_hash(review)
    if existing and existing.get("baseline_hash") != baseline_hash:
        existing["status"] = "stale"
        existing["summary"] = "正式参数已经变化，当前方案需要重新计算。"
        existing["updated_at"] = _now()
        review["active_parameter_change_proposal_id"] = None
        return _public_proposal(existing)

    cumulative_actions = _merge_actions(existing.get("explicit_actions") or [], applicable) if existing else applicable
    if not cumulative_actions and not clarification and not existing:
        return None

    proposal_id = str(existing.get("proposal_id")) if existing else f"proposal_{uuid.uuid4().hex}"
    version = int(existing.get("version") or 0) + 1 if existing else 1
    proposal = _resolve_proposal(
        review,
        cumulative_actions,
        proposal_id=proposal_id,
        version=version,
        baseline_hash=baseline_hash,
        user_goal=user_goal,
        review_revision=review_revision,
        clarification=clarification,
    )
    if existing:
        history = list(existing.get("version_history") or [])
        history.append(_proposal_history_entry(existing))
        proposal["version_history"] = history[-PROPOSAL_HISTORY_LIMIT:]
        _replace_proposal(review, proposal)
    else:
        review.setdefault("parameter_change_proposals", []).append(proposal)
    review["active_parameter_change_proposal_id"] = proposal_id
    return _public_proposal(proposal)


def find_parameter_change_proposal(review: dict[str, Any], proposal_id: str | None) -> dict[str, Any] | None:
    if not proposal_id:
        return None
    return next(
        (
            item
            for item in review.get("parameter_change_proposals") or []
            if isinstance(item, dict) and str(item.get("proposal_id") or "") == str(proposal_id)
        ),
        None,
    )


def apply_parameter_change_proposal(
    review: dict[str, Any],
    proposal_id: str,
    *,
    version: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ensure_technical_requirement_ids(review)
    stored = find_parameter_change_proposal(review, proposal_id)
    if not stored:
        raise ParameterProposalError("proposal_not_found", "参数修改方案不存在。")
    if int(stored.get("version") or 0) != int(version):
        raise ParameterProposalError("proposal_version_conflict", "方案版本已经变化，请查看最新方案。", current=_public_proposal(stored))
    if stored.get("status") not in PROPOSAL_APPLYABLE_STATUSES:
        raise ParameterProposalError("proposal_not_applyable", "当前方案状态不允许应用。", current=_public_proposal(stored))
    if stored.get("baseline_hash") != parameter_state_hash(review):
        stored["status"] = "stale"
        stored["summary"] = "正式参数已经变化，当前方案需要重新计算。"
        stored["updated_at"] = _now()
        raise ParameterProposalError("proposal_stale", stored["summary"], current=_public_proposal(stored))

    refreshed = _resolve_proposal(
        review,
        list(stored.get("explicit_actions") or []),
        proposal_id=proposal_id,
        version=version,
        baseline_hash=str(stored.get("baseline_hash")),
        user_goal=str(stored.get("user_goal") or ""),
        review_revision=stored.get("baseline_review_revision"),
    )
    if refreshed.get("status") not in PROPOSAL_APPLYABLE_STATUSES:
        raise ParameterProposalError("proposal_revalidation_failed", "重新校验后方案已不可应用。", current=_public_proposal(refreshed))

    before = _rollback_state(review)
    applied_review = deepcopy(review)
    _apply_resolved_changes(applied_review, refreshed)
    parameter_change_count = len(refreshed.get("direct_changes") or []) + len(refreshed.get("synchronized_changes") or [])
    technical_change_count = len(refreshed.get("technical_requirement_changes") or [])
    if parameter_change_count:
        _refresh_review_after_apply(applied_review)
    else:
        applied_review["parameter_reasonableness"] = assess_parameter_reasonableness(applied_review)
        applied_review["parameter_reasonableness_stale"] = False

    applied = find_parameter_change_proposal(applied_review, proposal_id)
    if applied is None:
        raise ParameterProposalError("proposal_not_found", "参数修改方案不存在。")
    applied.update(refreshed)
    applied["status"] = "applied"
    applied["applied_at"] = _now()
    applied["summary"] = f"已应用审图修改方案，共更新 {parameter_change_count + technical_change_count} 项参数或技术要求。"
    applied_review["active_parameter_change_proposal_id"] = None
    _sync_proposal_turn_snapshots(applied_review, applied)

    patches = []
    for change in [*(refreshed.get("direct_changes") or []), *(refreshed.get("synchronized_changes") or [])]:
        patch = {
            "target_field": change.get("field"),
            "target_label": change.get("label"),
            "previous_value": change.get("before"),
            "proposed_value": change.get("after"),
            "unit": change.get("unit"),
            "action_type": change.get("action_type") or "propose_parameter_patch",
        }
        if patch["action_type"] == "propose_tolerance_patch" and isinstance(change.get("after"), dict):
            patch["suggested_tolerance_upper"] = change["after"].get("upper")
            patch["suggested_tolerance_lower"] = change["after"].get("lower")
        patches.append(patch)
    log_id = f"parameter_change_proposal_{uuid.uuid4().hex}"
    applied_review.setdefault("agent_actions", []).append(
        {
            "id": log_id,
            "source": "standardization_chat",
            "action_type": "apply_parameter_change_proposal",
            "proposal_id": proposal_id,
            "proposal_version": version,
            "user_message": stored.get("user_goal") or "",
            "applied_at": applied["applied_at"],
            "applied_patches": patches,
            "technical_requirement_changes": deepcopy(refreshed.get("technical_requirement_changes") or []),
            "rollback": {
                "turn_created_at": stored.get("source_turn_created_at"),
                "proposal_id": proposal_id,
                "full_state": before,
                "field_states": [],
                "action_states": [],
            },
            "turn_created_at": stored.get("source_turn_created_at"),
            "restandardized": bool(parameter_change_count),
            "restandardization_status": "completed" if parameter_change_count else "not_required",
        }
    )
    return applied_review, {
        "proposal": _public_proposal(applied),
        "log_id": log_id,
        "patches": patches,
        "technical_requirement_changes": deepcopy(refreshed.get("technical_requirement_changes") or []),
    }


def discard_parameter_change_proposal(review: dict[str, Any], proposal_id: str, *, version: int) -> dict[str, Any]:
    proposal = find_parameter_change_proposal(review, proposal_id)
    if not proposal:
        raise ParameterProposalError("proposal_not_found", "参数修改方案不存在。")
    if int(proposal.get("version") or 0) != int(version):
        raise ParameterProposalError("proposal_version_conflict", "方案版本已经变化，请查看最新方案。", current=_public_proposal(proposal))
    if proposal.get("status") == "applied":
        raise ParameterProposalError("proposal_already_applied", "已经应用的方案不能放弃。", current=_public_proposal(proposal))
    proposal["status"] = "discarded"
    proposal["discarded_at"] = _now()
    proposal["updated_at"] = proposal["discarded_at"]
    proposal["summary"] = "已放弃参数修改方案，正式参数没有变化。"
    if review.get("active_parameter_change_proposal_id") == proposal_id:
        review["active_parameter_change_proposal_id"] = None
    _sync_proposal_turn_snapshots(review, proposal)
    return _public_proposal(proposal)


def _resolve_proposal(
    review: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    proposal_id: str,
    version: int,
    baseline_hash: str,
    user_goal: str,
    review_revision: int | None,
    clarification: str | None = None,
) -> dict[str, Any]:
    candidate = deepcopy(review)
    direct_changes: list[dict[str, Any]] = []
    technical_requirement_changes: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    questions: list[str] = []

    actionable: list[dict[str, Any]] = []
    technical_actions: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    for action in actions:
        if action.get("type") == "proposal_constraint":
            constraints.append(action)
            continue
        if action.get("type") in TECHNICAL_REQUIREMENT_ACTION_TYPES:
            technical_actions.append(action)
            continue
        target = str(action.get("target_field") or "")
        root = target.split(".")[0]
        if root in DESIGN_GOAL_FIELDS and action.get("type") == "propose_parameter_patch":
            recommendations.append(
                {
                    "field": target,
                    "label": _field_label(target),
                    "requested_value": action.get("proposed_value"),
                    "unit": action.get("unit"),
                    "reason": "该字段由多个建模参数共同决定，不能直接覆盖。",
                }
            )
            questions.append(f"{_field_label(target)}存在多种反求方案，请说明允许调整哪些建模参数。")
            continue
        actionable.append(action)
        change = _apply_action(candidate, action, confirmation_source="human_confirmed")
        if change:
            direct_changes.append(change)

    technical_requirement_changes, technical_questions, technical_blocking = _resolve_technical_requirement_actions(
        candidate,
        technical_actions,
    )
    questions.extend(technical_questions)
    blocking.extend(technical_blocking)

    synchronized_changes, diameter_issues = _solve_diameter_group(review, candidate, actionable)
    for issue in diameter_issues:
        (questions if issue.get("kind") == "needs_input" else blocking).append(issue.get("message") if issue.get("kind") == "needs_input" else issue)
    synchronized_changes.extend(_solve_end_condition_group(review, candidate, actionable))
    dependent_changes, dependent_questions = _solve_dependent_parameters(review, candidate, actionable)
    synchronized_changes.extend(dependent_changes)
    questions.extend(dependent_questions)
    constraint_issues = _validate_constraints(candidate, constraints)
    questions.extend(item["message"] for item in constraint_issues)

    if actionable:
        _refresh_review_after_apply(candidate, preview=True)
    reasonableness = assess_parameter_reasonableness(candidate)
    readiness = assess_generation_readiness(candidate)
    resolved_actions = [
        *actionable,
        *technical_actions,
        *[
            {
                "type": "propose_parameter_patch",
                "target_field": change["field"],
                "proposed_value": change["after"],
                "unit": change.get("unit"),
            }
            for change in synchronized_changes
        ],
    ]
    impact = assess_parameter_change_impact(review, resolved_actions) if resolved_actions else None
    if reasonableness.get("status") == "blocked":
        blocking.extend(item for item in reasonableness.get("issues") or [] if item.get("severity") == "blocked")

    if clarification:
        questions.append(clarification)
    if constraints and not actionable and not technical_actions and not questions:
        questions.append("当前约束已经满足；如需继续修改，请再提供一个明确目标参数。")
    if not actionable and not technical_actions and not constraints and not questions:
        questions.append("请提供需要修改的参数或技术要求，以及明确的目标内容。")

    if blocking:
        status = "blocked"
    elif questions:
        status = "needs_input"
    elif reasonableness.get("status") in {"warning", "needs_input"} or (impact and impact.get("status") == "warning"):
        status = "warning"
    else:
        status = "ready"

    count = len(direct_changes) + len(synchronized_changes) + len(technical_requirement_changes)
    covered_fields = {
        str(item.get("field") or "")
        for item in [*direct_changes, *synchronized_changes]
    }
    derived_changes = [
        item
        for item in (impact or {}).get("derived_changes") or []
        if str(item.get("field") or "") not in covered_fields
    ]
    derived_changes.extend(_load_deflection_changes(review, candidate))
    summary = {
        "ready": f"方案已完成整体校验，将更新 {count} 项参数或技术要求。",
        "warning": f"方案将更新 {count} 项参数或技术要求，但仍有风险提示。",
        "blocked": "方案存在冲突，不能应用。",
        "needs_input": "方案还缺少能够唯一确定结果的信息。",
    }[status]
    now = _now()
    return {
        "proposal_id": proposal_id,
        "version": version,
        "status": status,
        "summary": summary,
        "user_goal": user_goal,
        "baseline_hash": baseline_hash,
        "baseline_review_revision": review_revision,
        "explicit_actions": deepcopy(actions),
        "constraints": deepcopy(constraints),
        "direct_changes": direct_changes,
        "synchronized_changes": synchronized_changes,
        "technical_requirement_changes": technical_requirement_changes,
        "derived_changes": derived_changes,
        "recommendations": recommendations,
        "clarifying_questions": list(dict.fromkeys(str(item) for item in questions if item)),
        "blocking_issues": _dedupe_issues(blocking),
        "risk_delta": (impact or {}).get("risk_delta") or {"introduced": [], "resolved": [], "unchanged_count": 0},
        "generation_readiness": (impact or {}).get("generation_readiness") or {
            "before_status": assess_generation_readiness(review).get("status"),
            "after_status": readiness.get("status"),
            "parameter_package_changed": False,
            "changed_frozen_fields": [],
        },
        "workflow_effects": (impact or {}).get("workflow_effects") or {
            "standardization_recalculation_required": bool(actions),
            "new_generation_required": False,
        },
        "created_at": now,
        "updated_at": now,
    }


def _resolve_technical_requirement_actions(
    candidate: dict[str, Any],
    actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    if not actions:
        return [], [], []

    ensure_technical_requirement_ids(candidate)
    requirements = candidate.setdefault("technical_requirements", [])
    questions: list[str] = []
    blocking: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    operations_by_id: dict[str, set[str]] = {}
    for action in actions:
        requirement_id = str(action.get("requirement_id") or "").strip()
        if requirement_id:
            operations_by_id.setdefault(requirement_id, set()).add(str(action.get("type") or ""))
    for requirement_id, operations in operations_by_id.items():
        if "propose_technical_requirement_delete" in operations and len(operations) > 1:
            blocking.append(
                {
                    "code": "technical_requirement_operation_conflict",
                    "requirement_id": requirement_id,
                    "message": "同一条技术要求不能在一个方案中同时删除和修改或新增。",
                }
            )
    if blocking:
        return [], [], blocking

    for action in actions:
        action_type = str(action.get("type") or "")
        operation = action_type.removeprefix("propose_technical_requirement_")
        requirement_id = str(action.get("requirement_id") or "").strip()
        requested_type = action.get("requirement_type")
        requested_content = action.get("content")

        if action_type == "propose_technical_requirement_add":
            requirement_id = requirement_id or new_technical_requirement_id()
            requirement_type = normalize_technical_requirement_type(requested_type, default=None)
            content = str(requested_content or "").strip()
            if requirement_type is None:
                blocking.append(
                    {
                        "code": "technical_requirement_type_invalid",
                        "requirement_id": requirement_id,
                        "message": "新增技术要求的类型无效，请选择表面处理、硬度、热处理、盐雾、环保、寿命、工艺或其他。",
                    }
                )
                continue
            if not content:
                questions.append("请补充需要新增的技术要求具体内容。")
                continue
            if _find_technical_requirement_index(requirements, requirement_id) is not None:
                blocking.append(
                    {
                        "code": "technical_requirement_id_conflict",
                        "requirement_id": requirement_id,
                        "message": "新增技术要求的内部标识已经存在，请重新生成方案。",
                    }
                )
                continue
            if _has_duplicate_technical_requirement(requirements, requirement_type, content):
                blocking.append(
                    {
                        "code": "technical_requirement_duplicate",
                        "requirement_id": requirement_id,
                        "message": "相同类型和内容的技术要求已经存在，不能重复新增。",
                    }
                )
                continue
            added = _confirmed_technical_requirement(
                {},
                requirement_id=requirement_id,
                requirement_type=requirement_type,
                content=content,
            )
            requirements.append(added)
            changes.append(
                {
                    "operation": operation,
                    "requirement_id": requirement_id,
                    "type_label": TECHNICAL_REQUIREMENT_TYPE_LABELS[requirement_type],
                    "before": None,
                    "after": technical_requirement_snapshot(added),
                }
            )
            continue

        if not requirement_id:
            questions.append("请明确要修改或删除哪一条技术要求。")
            continue
        requirement_index = _find_technical_requirement_index(requirements, requirement_id)
        if requirement_index is None:
            questions.append(f"没有找到编号为 {requirement_id} 的技术要求，请重新选择目标。")
            continue
        current = requirements[requirement_index]
        before = technical_requirement_snapshot(current)

        if action_type == "propose_technical_requirement_delete":
            requirements.pop(requirement_index)
            changes.append(
                {
                    "operation": operation,
                    "requirement_id": requirement_id,
                    "type_label": TECHNICAL_REQUIREMENT_TYPE_LABELS.get(str(before.get("type"))) or "技术要求",
                    "before": before,
                    "after": None,
                }
            )
            continue

        requirement_type = (
            normalize_technical_requirement_type(requested_type, default=None)
            if requested_type not in (None, "")
            else normalize_technical_requirement_type(current.get("type"), default="other")
        )
        if requirement_type is None:
            blocking.append(
                {
                    "code": "technical_requirement_type_invalid",
                    "requirement_id": requirement_id,
                    "message": "修改后的技术要求类型无效。",
                }
            )
            continue
        if requested_content is not None and not str(requested_content).strip():
            questions.append("修改后的技术要求内容不能为空，请补充完整内容。")
            continue
        content = str(requested_content).strip() if requested_content is not None else str(current.get("content") or "").strip()
        if _has_duplicate_technical_requirement(
            requirements,
            requirement_type,
            content,
            exclude_requirement_id=requirement_id,
        ):
            blocking.append(
                {
                    "code": "technical_requirement_duplicate",
                    "requirement_id": requirement_id,
                    "message": "修改后会与另一条技术要求完全重复，不能应用。",
                }
            )
            continue
        updated = _confirmed_technical_requirement(
            current,
            requirement_id=requirement_id,
            requirement_type=requirement_type,
            content=content,
        )
        requirements[requirement_index] = updated
        after = technical_requirement_snapshot(updated)
        if before != after:
            changes.append(
                {
                    "operation": operation,
                    "requirement_id": requirement_id,
                    "type_label": TECHNICAL_REQUIREMENT_TYPE_LABELS[requirement_type],
                    "before": before,
                    "after": after,
                }
            )
    return changes, list(dict.fromkeys(questions)), _dedupe_issues(blocking)


def _confirmed_technical_requirement(
    current: dict[str, Any],
    *,
    requirement_id: str,
    requirement_type: str,
    content: str,
) -> dict[str, Any]:
    item = deepcopy(current)
    previous_type = normalize_technical_requirement_type(item.get("type"), default="other")
    item.update(
        {
            "requirement_id": requirement_id,
            "type": requirement_type,
            "content": content,
            "source": _merge_sources(item.get("source"), ["ai_chat", "human_confirmed"]),
            "evidence": "AI对话技术要求修改方案经用户整体确认",
            "confidence": 1.0,
            "need_human_review": False,
        }
    )
    surface_only_keys = (
        "raw_content",
        "standard_content",
        "normalization_status",
        "normalization_source",
        "normalization_confidence",
        "normalization_reason",
        "standard_candidates",
    )
    if requirement_type == "surface":
        normalized = normalize_surface_requirement(content)
        item.update(
            {
                "raw_content": str(current.get("raw_content") or current.get("content") or content),
                "standard_content": content,
                "normalization_status": "human_confirmed",
                "normalization_source": "human",
                "normalization_confidence": 1.0,
                "normalization_reason": "AI方案经用户整体确认",
                "standard_candidates": normalized.get("standard_candidates") or [],
            }
        )
    elif previous_type == "surface" or any(key in item for key in surface_only_keys):
        for key in surface_only_keys:
            item.pop(key, None)
    return item


def _find_technical_requirement_index(requirements: list[Any], requirement_id: str) -> int | None:
    return next(
        (
            index
            for index, item in enumerate(requirements)
            if isinstance(item, dict) and str(item.get("requirement_id") or "") == requirement_id
        ),
        None,
    )


def _has_duplicate_technical_requirement(
    requirements: list[Any],
    requirement_type: str,
    content: str,
    *,
    exclude_requirement_id: str | None = None,
) -> bool:
    expected = canonical_technical_requirement_key(requirement_type, content)
    return any(
        canonical_technical_requirement_key(item.get("type"), item.get("content")) == expected
        for item in requirements
        if isinstance(item, dict)
        and str(item.get("requirement_id") or "") != str(exclude_requirement_id or "")
    )


def _solve_diameter_group(
    baseline_review: dict[str, Any],
    candidate: dict[str, Any],
    actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    explicit = {
        str(action.get("target_field")): _number(action.get("proposed_value"))
        for action in actions
        if action.get("type") == "propose_parameter_patch" and str(action.get("target_field")) in DIAMETER_FIELDS
    }
    explicit = {field: value for field, value in explicit.items() if value is not None}
    if not explicit:
        return [], []

    baseline_parameters = baseline_review.get("spring_parameters") or {}
    candidate_parameters = candidate.setdefault("spring_parameters", {})
    issues: list[dict[str, Any]] = []
    solved: dict[str, float] | None = None
    fields = set(explicit)

    if len(fields) == 1:
        field = next(iter(fields))
        if field == "wire_diameter":
            mean = _parameter_number(candidate_parameters, "mean_diameter")
            if mean is None:
                return [], [{"kind": "needs_input", "message": "修改线径时还需要明确中径，才能唯一计算外径和内径。"}]
            solved = _diameters_from_wire_mean(explicit[field], mean)
        else:
            wire = _parameter_number(candidate_parameters, "wire_diameter")
            if wire is None:
                return [], [{"kind": "needs_input", "message": f"修改{_field_label(field)}时还需要明确线径。"}]
            solved = _diameters_from_pair(field, explicit[field], "wire_diameter", wire)
    else:
        pairs = (
            ("wire_diameter", "mean_diameter"),
            ("wire_diameter", "outer_diameter"),
            ("wire_diameter", "inner_diameter"),
            ("mean_diameter", "outer_diameter"),
            ("mean_diameter", "inner_diameter"),
            ("outer_diameter", "inner_diameter"),
        )
        for left, right in pairs:
            if left in explicit and right in explicit:
                solved = _diameters_from_pair(left, explicit[left], right, explicit[right])
                break

    if not solved:
        return [], [{"kind": "needs_input", "message": "当前直径修改条件不足，无法唯一计算其他关联直径。"}]

    for field, value in explicit.items():
        if not _numbers_close(value, solved.get(field)):
            issues.append(
                {
                    "kind": "blocked",
                    "code": "diameter_constraint_conflict",
                    "fields": sorted(fields),
                    "message": "用户提供的线径、外径、内径或中径不满足同一组弹簧直径关系。",
                }
            )
            return [], issues
    if solved["wire_diameter"] <= 0 or solved["mean_diameter"] <= solved["wire_diameter"] or solved["inner_diameter"] <= 0:
        return [], [
            {
                "kind": "blocked",
                "code": "diameter_geometry_invalid",
                "fields": list(DIAMETER_FIELDS),
                "message": "修改后的直径关系不能形成有效弹簧几何，必须满足中径大于线径且内径大于0。",
            }
        ]

    changes: list[dict[str, Any]] = []
    for field in DIAMETER_FIELDS:
        if field in explicit:
            continue
        before = _parameter_value(baseline_parameters, field)
        after = _rounded(solved[field])
        if _values_equal(before, after):
            continue
        _set_parameter(
            candidate_parameters,
            field,
            after,
            unit="mm",
            source=["parameter_change_proposal_derived"],
            source_fields=sorted(fields),
        )
        changes.append(
            {
                "field": field,
                "label": _field_label(field),
                "before": before,
                "after": after,
                "unit": "mm",
                "change_type": "value",
                "action_type": "propose_parameter_patch",
                "confirmation_after": "deterministic_derived",
                "source_fields": sorted(fields),
            }
        )
    return changes, issues


def _diameters_from_pair(left: str, left_value: float, right: str, right_value: float) -> dict[str, float] | None:
    values = {left: left_value, right: right_value}
    wire = values.get("wire_diameter")
    mean = values.get("mean_diameter")
    outer = values.get("outer_diameter")
    inner = values.get("inner_diameter")
    if wire is not None and mean is not None:
        return _diameters_from_wire_mean(wire, mean)
    if wire is not None and outer is not None:
        return _diameters_from_wire_mean(wire, outer - wire)
    if wire is not None and inner is not None:
        return _diameters_from_wire_mean(wire, inner + wire)
    if mean is not None and outer is not None:
        return _diameters_from_wire_mean(outer - mean, mean)
    if mean is not None and inner is not None:
        return _diameters_from_wire_mean(mean - inner, mean)
    if outer is not None and inner is not None:
        return _diameters_from_wire_mean((outer - inner) / 2, (outer + inner) / 2)
    return None


def _diameters_from_wire_mean(wire: float, mean: float) -> dict[str, float]:
    return {
        "wire_diameter": wire,
        "mean_diameter": mean,
        "outer_diameter": mean + wire,
        "inner_diameter": mean - wire,
    }


def _solve_end_condition_group(
    baseline_review: dict[str, Any],
    candidate: dict[str, Any],
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    end_action = next(
        (
            item
            for item in reversed(actions)
            if item.get("type") == "propose_parameter_patch" and item.get("target_field") == "end_type"
        ),
        None,
    )
    if not end_action:
        return []
    normalized = normalize_end_type(end_action.get("proposed_value"))
    if normalized not in {END_TYPE_TIGHT, END_TYPE_NOT_TIGHT}:
        return []
    binary = 1 if normalized == END_TYPE_TIGHT else 0
    baseline_parameters = baseline_review.get("spring_parameters") or {}
    candidate_parameters = candidate.setdefault("spring_parameters", {})
    before = _parameter_value(baseline_parameters, "end_coils_closed")
    _set_parameter(
        candidate_parameters,
        "end_coils_closed",
        binary,
        unit=None,
        source=["parameter_change_proposal_derived"],
        source_fields=["end_type"],
    )
    if _values_equal(before, binary):
        return []
    return [
        {
            "field": "end_coils_closed",
            "label": _field_label("end_coils_closed"),
            "before": before,
            "after": binary,
            "unit": None,
            "change_type": "value",
            "action_type": "propose_parameter_patch",
            "confirmation_after": "deterministic_derived",
            "source_fields": ["end_type"],
        }
    ]


def _solve_dependent_parameters(
    baseline_review: dict[str, Any],
    candidate: dict[str, Any],
    actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    explicit_fields = {
        str(action.get("target_field") or "")
        for action in actions
        if action.get("type") == "propose_parameter_patch"
    }
    changed_roots = {field.split(".")[0] for field in explicit_fields}
    parameters = candidate.setdefault("spring_parameters", {})
    baseline_parameters = baseline_review.get("spring_parameters") or {}
    changes: list[dict[str, Any]] = []
    questions: list[str] = []

    if changed_roots & {"total_coils", "end_type", "support_coils"} and "active_coils" not in explicit_fields:
        total = _parameter_number(parameters, "total_coils")
        end_type = _parameter_end_type(parameters)
        active: float | None = None
        source_fields = ["total_coils", "end_type"]
        if total is not None and end_type == END_TYPE_NOT_TIGHT:
            active = total
        elif total is not None and end_type == END_TYPE_TIGHT:
            support = _parameter_number(parameters, "support_coils")
            if support is None:
                questions.append("端部并紧后需要明确单端支承圈数或直接给出有效圈数，系统不会静默采用默认值。")
            else:
                active = total - 2 * support
                source_fields.append("support_coils")
        if active is not None and active > 0:
            change = _synchronize_parameter(
                parameters,
                baseline_parameters,
                "active_coils",
                _rounded(active),
                unit="turns",
                source_fields=source_fields,
            )
            if change:
                changes.append(change)

    changed_roots.update(str(item.get("field") or "") for item in changes)
    if changed_roots & {"wire_diameter", "total_coils", "end_grinding"} and "solid_height" not in explicit_fields:
        result = calculate_compression_solid_height(parameters)
        if result.get("status") == "calculated" and result.get("value") is not None:
            change = _synchronize_parameter(
                parameters,
                baseline_parameters,
                "solid_height",
                result.get("value"),
                unit=result.get("unit") or "mm",
                source_fields=list(result.get("source_fields") or []),
            )
            if change:
                changes.append(change)

    if changed_roots & {
        "material", "wire_diameter", "mean_diameter", "outer_diameter", "inner_diameter",
        "active_coils", "total_coils", "end_type", "support_coils",
    } and "spring_rate" not in explicit_fields:
        result = calculate_compression_spring_rate(parameters, candidate.get("spring_features") or {})
        if result.get("status") == "calculated" and result.get("value") is not None:
            change = _synchronize_parameter(
                parameters,
                baseline_parameters,
                "spring_rate",
                result.get("value"),
                unit="N/mm",
                source_fields=list(result.get("source_fields") or []),
            )
            if change:
                changes.append(change)
    return changes, questions


def _validate_constraints(review: dict[str, Any], constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    parameters = review.get("spring_parameters") or {}
    for constraint in constraints:
        field = str(constraint.get("target_field") or "")
        expected = constraint.get("constraint_value")
        actual = _parameter_value(parameters, field)
        operator = str(constraint.get("operator") or "equal")
        satisfied = False
        if operator == "equal":
            satisfied = _values_equal(actual, expected)
        else:
            actual_number = _number(actual)
            expected_number = _number(expected)
            if actual_number is not None and expected_number is not None:
                satisfied = actual_number <= expected_number + 0.02 if operator == "max" else actual_number >= expected_number - 0.02
        if satisfied:
            continue
        description = str(constraint.get("description") or f"{_field_label(field)}约束")
        issues.append(
            {
                "field": field,
                "operator": operator,
                "expected": expected,
                "actual": actual,
                "message": f"当前计算结果不满足“{description}”。请说明允许调整哪些关联参数。",
            }
        )
    return issues


def _load_deflection_changes(before_review: dict[str, Any], after_review: dict[str, Any]) -> list[dict[str, Any]]:
    before = derive_compression_parameters(before_review.get("spring_parameters") or {}).get("load_point_deflections") or []
    after = derive_compression_parameters(after_review.get("spring_parameters") or {}).get("load_point_deflections") or []
    before_by_label = {str(item.get("label") or ""): item for item in before if isinstance(item, dict)}
    after_by_label = {str(item.get("label") or ""): item for item in after if isinstance(item, dict)}
    changes: list[dict[str, Any]] = []
    for label in dict.fromkeys([*before_by_label, *after_by_label]):
        old = before_by_label.get(label) or {}
        new = after_by_label.get(label) or {}
        if _values_equal(old.get("deflection"), new.get("deflection")):
            continue
        changes.append(
            {
                "field": f"load_points.{label}.deflection",
                "label": f"载荷测试点 {label} 变形量",
                "before": old.get("deflection"),
                "after": new.get("deflection"),
                "unit": new.get("deflection_unit") or old.get("deflection_unit") or "mm",
            }
        )
    return changes


def _synchronize_parameter(
    parameters: dict[str, Any],
    baseline_parameters: dict[str, Any],
    field: str,
    value: Any,
    *,
    unit: str | None,
    source_fields: list[str],
) -> dict[str, Any] | None:
    before = _parameter_value(baseline_parameters, field)
    _set_parameter(
        parameters,
        field,
        value,
        unit=unit,
        source=["parameter_change_proposal_derived"],
        source_fields=source_fields,
    )
    if _values_equal(before, value):
        return None
    return {
        "field": field,
        "label": _field_label(field),
        "before": before,
        "after": value,
        "unit": unit,
        "change_type": "value",
        "action_type": "propose_parameter_patch",
        "confirmation_after": "deterministic_derived",
        "source_fields": source_fields,
    }


def _parameter_end_type(parameters: dict[str, Any]) -> str | None:
    normalized = normalize_end_type(_parameter_value(parameters, "end_type"))
    if normalized:
        return normalized
    binary = _binary_value(_parameter_value(parameters, "end_coils_closed"))
    return END_TYPE_TIGHT if binary == 1 else END_TYPE_NOT_TIGHT if binary == 0 else None


def _apply_action(review: dict[str, Any], action: dict[str, Any], *, confirmation_source: str) -> dict[str, Any] | None:
    parameters = review.setdefault("spring_parameters", {})
    target = str(action.get("target_field") or "")
    if not target:
        return None
    load_target = _parse_load_target(target)
    if load_target:
        label, field = load_target
        point = next((item for item in parameters.get("load_points") or [] if str(item.get("label") or "") == label), None)
        if not isinstance(point, dict):
            return None
        if action.get("type") == "propose_tolerance_patch":
            before = {"upper": point.get("load_tolerance_upper"), "lower": point.get("load_tolerance_lower")}
            after = _action_tolerance(action, before)
            point["load_tolerance_upper"] = after["upper"]
            point["load_tolerance_lower"] = after["lower"]
        else:
            before = point.get(field)
            after = action.get("proposed_value")
            point[field] = after
        point["need_human_review"] = False
        point["source"] = _merge_sources(point.get("source"), ["parameter_change_proposal", confirmation_source])
        unit = point.get("height_unit") if field == "height" else point.get("force_unit")
        return _change(action, target, before, after, unit)

    item = dict(parameters.get(target) or {})
    if action.get("type") == "propose_tolerance_patch":
        before = {"upper": item.get("tolerance_upper"), "lower": item.get("tolerance_lower")}
        after = _action_tolerance(action, before)
        item["tolerance_upper"] = after["upper"]
        item["tolerance_lower"] = after["lower"]
    else:
        before = item.get("value")
        after = action.get("proposed_value")
        item["value"] = after
    if action.get("unit"):
        item["unit"] = action.get("unit")
    item["need_human_review"] = False
    item["confidence"] = max(float(item.get("confidence") or 0), 0.99)
    item["source"] = _merge_sources(item.get("source"), ["parameter_change_proposal", confirmation_source])
    item["evidence"] = action.get("reason") or "AI对话参数修改方案经用户整体确认"
    parameters[target] = item
    return _change(action, target, before, after, item.get("unit"))


def _apply_resolved_changes(review: dict[str, Any], proposal: dict[str, Any]) -> None:
    for action in proposal.get("explicit_actions") or []:
        if action.get("type") == "proposal_constraint" or action.get("type") in TECHNICAL_REQUIREMENT_ACTION_TYPES:
            continue
        if str(action.get("target_field") or "").split(".")[0] in DESIGN_GOAL_FIELDS:
            continue
        _apply_action(review, action, confirmation_source="human_confirmed")
        target = str(action.get("target_field") or "")
        review.setdefault("manual_confirmations", {})[f"parameter_change_proposal_{target}"] = {
            "confirmed": True,
            "target_field": target,
            "proposal_id": proposal.get("proposal_id"),
            "proposal_version": proposal.get("version"),
            "confirmed_at": _now(),
        }
    parameters = review.setdefault("spring_parameters", {})
    for change in proposal.get("synchronized_changes") or []:
        _set_parameter(
            parameters,
            str(change.get("field") or ""),
            change.get("after"),
            unit=change.get("unit"),
            source=["parameter_change_proposal_derived"],
            source_fields=list(change.get("source_fields") or []),
        )
    _apply_technical_requirement_changes(review, proposal.get("technical_requirement_changes") or [], proposal)


def _apply_technical_requirement_changes(
    review: dict[str, Any],
    changes: list[dict[str, Any]],
    proposal: dict[str, Any],
) -> None:
    ensure_technical_requirement_ids(review)
    requirements = review.setdefault("technical_requirements", [])
    confirmations = review.setdefault("manual_confirmations", {})
    for change in changes:
        operation = str(change.get("operation") or "")
        requirement_id = str(change.get("requirement_id") or "")
        index = _find_technical_requirement_index(requirements, requirement_id)
        after = change.get("after")
        if operation == "delete":
            if index is not None:
                requirements.pop(index)
            confirmations.pop(technical_requirement_confirmation_key(requirement_id), None)
            continue
        if not isinstance(after, dict):
            continue
        current = requirements[index] if index is not None and isinstance(requirements[index], dict) else {}
        item = _confirmed_technical_requirement(
            current,
            requirement_id=requirement_id,
            requirement_type=normalize_technical_requirement_type(after.get("type"), default="other") or "other",
            content=str(after.get("content") or "").strip(),
        )
        if index is None:
            requirements.append(item)
        else:
            requirements[index] = item
        confirmations[technical_requirement_confirmation_key(requirement_id)] = {
            "confirmed": True,
            "requirement_id": requirement_id,
            "value": item.get("content"),
            "confirmation_source": "ai_parameter_change_proposal",
            "proposal_id": proposal.get("proposal_id"),
            "proposal_version": proposal.get("version"),
            "confirmed_at": _now(),
        }


def _refresh_review_after_apply(review: dict[str, Any], *, preview: bool = False) -> None:
    parameters = review.setdefault("spring_parameters", {})
    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "")
    had_standardization = bool((review.get("standard_selection") or {}).get("selected_standard") or review.get("standardization_results"))
    if spring_type == "compression_spring":
        apply_formula_compression_diameter_completion(parameters)
        apply_company_simple_active_coils(spring_type, parameters)
        apply_formula_compression_solid_height(parameters)
        apply_formula_compression_spring_rate(parameters, review.get("spring_features") or {})
    if had_standardization:
        apply_standardization_to_review(review)
    else:
        review["derived_parameters"] = (
            derive_compression_parameters(parameters)
            if spring_type == "compression_spring"
            else derive_active_coils(spring_type, parameters)
        )
        review["parameter_reasonableness"] = assess_parameter_reasonableness(review)
        review["parameter_reasonableness_stale"] = False
        review["derived_parameters_stale"] = False
    if not preview:
        review["standardization_apply_history"] = []


def _change(action: dict[str, Any], target: str, before: Any, after: Any, unit: Any) -> dict[str, Any]:
    return {
        "field": target,
        "label": _field_label(target),
        "before": before,
        "after": after,
        "unit": unit,
        "change_type": "tolerance" if action.get("type") == "propose_tolerance_patch" else "value",
        "action_type": action.get("type"),
        "confirmation_after": "human_confirmed",
    }


def _rollback_state(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "spring_parameters": deepcopy(review.get("spring_parameters") or {}),
        "technical_requirements": deepcopy(review.get("technical_requirements") or []),
        "manual_confirmations": deepcopy(review.get("manual_confirmations") or {}),
        "derived_parameters": deepcopy(review.get("derived_parameters") or {}),
        "parameter_reasonableness": deepcopy(review.get("parameter_reasonableness") or {}),
        "standard_selection": deepcopy(review.get("standard_selection") or {}),
        "standardization_results": deepcopy(review.get("standardization_results") or []),
    }


def _set_parameter(
    parameters: dict[str, Any],
    field: str,
    value: Any,
    *,
    unit: str | None,
    source: list[str],
    source_fields: list[str],
) -> None:
    existing = dict(parameters.get(field) or {})
    existing.update(
        {
            "field": field,
            "value": value,
            "unit": unit or existing.get("unit"),
            "need_human_review": False,
            "confidence": 1.0,
            "source": list(dict.fromkeys(source)),
            "source_fields": source_fields,
            "evidence": "根据已确认的方案参数自动同步计算。",
            "derived_value_stale": False,
        }
    )
    for stale_key in ("raw_value", "default_source", "default_reason", "confirmation_snapshot"):
        existing.pop(stale_key, None)
    parameters[field] = existing


def _public_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in proposal.items() if key not in {"explicit_actions", "version_history"}}


def _proposal_history_entry(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": proposal.get("version"),
        "status": proposal.get("status"),
        "summary": proposal.get("summary"),
        "updated_at": proposal.get("updated_at"),
        "direct_changes": deepcopy(proposal.get("direct_changes") or []),
        "synchronized_changes": deepcopy(proposal.get("synchronized_changes") or []),
        "technical_requirement_changes": deepcopy(proposal.get("technical_requirement_changes") or []),
    }


def _replace_proposal(review: dict[str, Any], proposal: dict[str, Any]) -> None:
    proposals = review.setdefault("parameter_change_proposals", [])
    for index, item in enumerate(proposals):
        if str(item.get("proposal_id") or "") == str(proposal.get("proposal_id") or ""):
            proposals[index] = proposal
            return
    proposals.append(proposal)


def _sync_proposal_turn_snapshots(review: dict[str, Any], proposal: dict[str, Any]) -> None:
    public = _public_proposal(proposal)
    for turn in review.get("standardization_chat") or []:
        snapshot = turn.get("change_proposal") if isinstance(turn, dict) else None
        if isinstance(snapshot, dict) and str(snapshot.get("proposal_id") or "") == str(proposal.get("proposal_id") or ""):
            turn["change_proposal"] = deepcopy(public)


def _merge_actions(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for action in [*previous, *current]:
        if not _is_applicable_action(action):
            continue
        action_type = str(action.get("type") or "")
        action_target = (
            str(action.get("requirement_id") or "")
            if action_type in TECHNICAL_REQUIREMENT_ACTION_TYPES
            else str(action.get("target_field") or "")
        )
        key = (action_type, action_target)
        if key not in merged:
            order.append(key)
        merged[key] = deepcopy(action)
    return [merged[key] for key in order]


def _normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    if action.get("type") in TECHNICAL_REQUIREMENT_ACTION_TYPES:
        if action.get("target_requirement_id") and not action.get("requirement_id"):
            action["requirement_id"] = action.get("target_requirement_id")
        if action.get("proposed_type") not in (None, "") and action.get("requirement_type") in (None, ""):
            action["requirement_type"] = action.get("proposed_type")
        if action.get("technical_requirement_type") not in (None, "") and action.get("requirement_type") in (None, ""):
            action["requirement_type"] = action.get("technical_requirement_type")
        if action.get("proposed_content") is not None and action.get("content") is None:
            action["content"] = action.get("proposed_content")
        if action.get("type") == "propose_technical_requirement_add" and not action.get("requirement_id"):
            action["requirement_id"] = new_technical_requirement_id()
        if action.get("requirement_id") is not None:
            action["requirement_id"] = str(action.get("requirement_id") or "").strip()
        if action.get("requirement_type") not in (None, ""):
            normalized_type = normalize_technical_requirement_type(action.get("requirement_type"), default=None)
            action["requirement_type"] = normalized_type or str(action.get("requirement_type") or "").strip()
        if action.get("content") is not None:
            action["content"] = str(action.get("content") or "").strip()
        return action
    if action.get("type") != "propose_parameter_patch":
        return action
    target = str(action.get("target_field") or "")
    value = action.get("proposed_value")
    if target == "end_coils_closed":
        action["target_field"] = "end_type"
        binary = _binary_value(value)
        action["proposed_value"] = END_TYPE_TIGHT if binary == 1 else END_TYPE_NOT_TIGHT if binary == 0 else normalize_end_type(value)
    elif target == "end_type":
        binary = _binary_value(value)
        action["proposed_value"] = END_TYPE_TIGHT if binary == 1 else END_TYPE_NOT_TIGHT if binary == 0 else normalize_end_type(value)
    elif target == "end_grinding":
        binary = _binary_value(value)
        action["proposed_value"] = END_GRINDING_GROUND if binary == 1 else END_GRINDING_NOT_GROUND if binary == 0 else normalize_end_grinding(value)
    elif target == "handedness":
        text = str(value or "").strip().lower()
        if text in {"左旋", "left", "left_hand", "l"}:
            action["proposed_value"] = "left"
        elif text in {"右旋", "right", "right_hand", "r"}:
            action["proposed_value"] = "right"
    return action


def _is_applicable_action(action: Any) -> bool:
    if not isinstance(action, dict) or action.get("type") not in APPLICABLE_ACTION_TYPES:
        return False
    if action.get("type") in TECHNICAL_REQUIREMENT_ACTION_TYPES:
        return True
    if not action.get("target_field"):
        return False
    if action.get("type") == "proposal_constraint":
        return action.get("constraint_value") not in (None, "") and action.get("operator") in {"min", "max", "equal"}
    if action.get("type") == "propose_tolerance_patch":
        return any(key in action for key in ("suggested_tolerance_upper", "suggested_tolerance_lower", "tolerance_upper", "tolerance_lower"))
    return action.get("proposed_value") not in (None, "")


def _binary_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if value in (0, 0.0, "0"):
        return 0
    if value in (1, 1.0, "1"):
        return 1
    return None


def _action_tolerance(action: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "upper": action.get("suggested_tolerance_upper", action.get("tolerance_upper", fallback.get("upper"))),
        "lower": action.get("suggested_tolerance_lower", action.get("tolerance_lower", fallback.get("lower"))),
    }


def _parse_load_target(target: str) -> tuple[str, str] | None:
    parts = target.split(".")
    if len(parts) == 3 and parts[0] == "load_points" and parts[2] in {"height", "force"}:
        return parts[1], parts[2]
    return None


def _field_label(field: str) -> str:
    load_target = _parse_load_target(field)
    if load_target:
        label, part = load_target
        return f"载荷测试点 {label} {'高度' if part == 'height' else '力值'}"
    return FIELD_LABELS.get(field) or field


def _parameter_value(parameters: dict[str, Any], field: str) -> Any:
    item = parameters.get(field)
    return item.get("value") if isinstance(item, dict) else item


def _parameter_number(parameters: dict[str, Any], field: str) -> float | None:
    return _number(_parameter_value(parameters, field))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float) -> int | float:
    rounded = round(float(value), 3)
    return int(rounded) if rounded.is_integer() else rounded


def _numbers_close(left: Any, right: Any) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return left_number is right_number
    return math.isclose(left_number, right_number, rel_tol=1e-6, abs_tol=0.02)


def _values_equal(left: Any, right: Any) -> bool:
    if _number(left) is not None and _number(right) is not None:
        return _numbers_close(left, right)
    return left == right


def _merge_sources(existing: Any, additional: list[str]) -> list[str]:
    values = list(existing) if isinstance(existing, list) else ([str(existing)] if existing else [])
    return list(dict.fromkeys([*additional, *values]))


def _dedupe_issues(issues: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in issues:
        item = raw if isinstance(raw, dict) else {"message": str(raw)}
        key = str(item.get("code") or item.get("message") or item)
        if key in seen:
            continue
        seen.add(key)
        result.append(deepcopy(item))
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
