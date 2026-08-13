from __future__ import annotations

from copy import deepcopy
from typing import Any

from .generation_contract import (
    COMPRESSION_GENERATION_INPUT_FIELDS,
    COMPRESSION_GENERATION_LABELS,
    export_generation_parameters,
    generation_source_item,
)
from .generation_readiness import assess_generation_readiness
from .spring_templates import FIELD_LABELS
from .standardizers.compression import calculate_compression_solid_height, derive_compression_parameters


APPLICABLE_ACTION_TYPES = {"propose_parameter_patch", "propose_tolerance_patch"}


def assess_parameter_change_impact(review: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulate AI chat patches and describe their deterministic downstream effects."""

    baseline_state = build_impact_baseline_state(review)
    applicable = [
        action
        for action in actions
        if isinstance(action, dict)
        and action.get("type") in APPLICABLE_ACTION_TYPES
        and action.get("target_field")
        and _has_action_value(action)
    ]
    if not applicable:
        return _empty_impact(
            "not_applicable",
            "本次建议没有可模拟的参数或公差修改。",
            baseline_state,
        )

    before_review = deepcopy(review)
    after_review = deepcopy(review)
    direct_changes: list[dict[str, Any]] = []
    for action in applicable:
        change = _apply_action(after_review, action)
        if change:
            direct_changes.append(change)

    if not direct_changes:
        return _empty_impact(
            "blocked",
            "建议指向的参数或载荷测试点不存在，无法计算影响。",
            baseline_state,
        )

    # Applying a parameter through the UI invalidates the old standardization
    # context until the automatic recalculation finishes. Model that immediate
    # workflow state so readiness warnings match what the user will see.
    _mark_standardization_stale(after_review)

    before_readiness = assess_generation_readiness(before_review)
    after_readiness = assess_generation_readiness(after_review)
    before_derived = _impact_derived_snapshot(before_review)
    after_derived = _impact_derived_snapshot(after_review)
    derived_changes = _changed_derived_values(before_derived, after_derived)

    before_issues = _readiness_issues(before_readiness)
    after_issues = _readiness_issues(after_readiness)
    before_issue_map = {_issue_key(item): item for item in before_issues}
    after_issue_map = {_issue_key(item): item for item in after_issues}
    introduced = [item for key, item in after_issue_map.items() if key not in before_issue_map]
    resolved = [item for key, item in before_issue_map.items() if key not in after_issue_map]
    unchanged_count = sum(1 for key in after_issue_map if key in before_issue_map)

    before_package = export_generation_parameters(before_review.get("spring_parameters") or {})
    after_package = export_generation_parameters(after_review.get("spring_parameters") or {})
    package_changed = before_package != after_package
    frozen_changes = [
        field
        for field in COMPRESSION_GENERATION_INPUT_FIELDS
        if before_package.get(field) != after_package.get(field)
    ]

    status = _impact_status(introduced)
    summary = _impact_summary(status, introduced, resolved, package_changed)
    impact_count = len(direct_changes) + len(derived_changes) + len(introduced) + len(resolved)
    return {
        "status": status,
        "summary": summary,
        "impact_count": impact_count,
        "direct_changes": direct_changes,
        "derived_changes": derived_changes,
        "risk_delta": {
            "introduced": introduced,
            "resolved": resolved,
            "unchanged_count": unchanged_count,
        },
        "generation_readiness": {
            "before_status": before_readiness.get("status"),
            "after_status": after_readiness.get("status"),
            "before_summary": before_readiness.get("summary"),
            "after_summary": after_readiness.get("summary"),
            "parameter_package_changed": package_changed,
            "changed_frozen_fields": frozen_changes,
        },
        "workflow_effects": {
            "standardization_recalculation_required": True,
            "new_generation_required": package_changed,
        },
        "baseline_state": baseline_state,
    }


def build_impact_baseline_state(review: dict[str, Any]) -> dict[str, Any]:
    """Return the exact review slices that make a previously computed preview stale."""

    summary = review.get("drawing_summary") or {}
    return {
        "drawing_summary": {"spring_type": summary.get("spring_type")},
        "spring_parameters": deepcopy(review.get("spring_parameters") or {}),
        "technical_requirements": deepcopy(review.get("technical_requirements") or []),
        "standard_selection": deepcopy(review.get("standard_selection") or {}),
        "standardization_results": deepcopy(review.get("standardization_results") or []),
        "derived_parameters_stale": bool(review.get("derived_parameters_stale")),
    }


def _apply_action(review: dict[str, Any], action: dict[str, Any]) -> dict[str, Any] | None:
    parameters = review.setdefault("spring_parameters", {})
    target = str(action.get("target_field") or "")
    load_target = _load_target(target)
    if load_target:
        label, field = load_target
        point = next(
            (
                item
                for item in parameters.get("load_points") or []
                if isinstance(item, dict) and str(item.get("label") or "") == label
            ),
            None,
        )
        if not isinstance(point, dict):
            return None
        if action.get("type") == "propose_tolerance_patch":
            before = {
                "upper": point.get("load_tolerance_upper"),
                "lower": point.get("load_tolerance_lower"),
            }
            after = _action_tolerance(action, before)
            point["load_tolerance_upper"] = after["upper"]
            point["load_tolerance_lower"] = after["lower"]
            point["need_human_review"] = False
            return _direct_change(action, target, before, after, point.get("force_unit") or "N")
        before = point.get(field)
        after = action.get("proposed_value")
        point[field] = after
        point["need_human_review"] = False
        unit = (point.get("height_unit") or "mm") if field == "height" else (point.get("force_unit") or "N")
        return _direct_change(action, target, before, after, unit)

    current = parameters.get(target)
    item = dict(current) if isinstance(current, dict) else {}
    unit = action.get("unit") or item.get("unit")
    if action.get("type") == "propose_tolerance_patch":
        before = {"upper": item.get("tolerance_upper"), "lower": item.get("tolerance_lower")}
        after = _action_tolerance(action, before)
        item["tolerance_upper"] = after["upper"]
        item["tolerance_lower"] = after["lower"]
    else:
        before = item.get("value")
        after = action.get("proposed_value")
        item["value"] = after
    item["need_human_review"] = False
    if unit:
        item["unit"] = unit
    parameters[target] = item
    return _direct_change(action, target, before, after, unit)


def _direct_change(
    action: dict[str, Any],
    target: str,
    before: Any,
    after: Any,
    unit: Any,
) -> dict[str, Any]:
    return {
        "field": target,
        "label": _field_label(target),
        "change_type": "tolerance" if action.get("type") == "propose_tolerance_patch" else "value",
        "before": before,
        "after": after,
        "unit": unit,
        "confirmation_after": "human_confirmed",
    }


def _impact_derived_snapshot(review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parameters = review.get("spring_parameters") or {}
    derived = derive_compression_parameters(parameters)
    wire = _number(_parameter_value(parameters, "wire_diameter"))
    mean_item = generation_source_item(parameters, "mean_diameter")
    mean = _number(mean_item.get("value")) if isinstance(mean_item, dict) else None
    snapshot: dict[str, dict[str, Any]] = {}

    if mean is not None:
        snapshot["mean_diameter"] = _derived_value(
            mean,
            "mm",
            str((mean_item or {}).get("formula") or "drawing_or_manual_mean_diameter"),
        )
    if wire is not None and mean is not None:
        snapshot["outer_diameter"] = _derived_value(mean + wire, "mm", "mean_diameter + wire_diameter")
        snapshot["inner_diameter"] = _derived_value(mean - wire, "mm", "mean_diameter - wire_diameter")

    for field in ("spring_index", "slenderness_ratio"):
        item = derived.get(field)
        if isinstance(item, dict) and item.get("value") is not None:
            snapshot[field] = _derived_value(item.get("value"), item.get("unit"), str(item.get("formula") or ""))

    solid_height = calculate_compression_solid_height(parameters)
    if solid_height.get("value") is not None:
        snapshot["solid_height"] = _derived_value(
            solid_height.get("value"),
            solid_height.get("unit"),
            str(solid_height.get("formula") or ""),
        )
    return snapshot


def _changed_derived_values(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    ordered_fields = (
        "outer_diameter",
        "mean_diameter",
        "inner_diameter",
        "spring_index",
        "slenderness_ratio",
        "solid_height",
    )
    for field in ordered_fields:
        before_item = before.get(field) or {}
        after_item = after.get(field) or {}
        if before_item.get("value") == after_item.get("value"):
            continue
        changes.append(
            {
                "field": field,
                "label": _field_label(field),
                "before": before_item.get("value"),
                "after": after_item.get("value"),
                "unit": after_item.get("unit") or before_item.get("unit"),
                "formula": after_item.get("formula") or before_item.get("formula"),
            }
        )
    return changes


def _readiness_issues(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        *((readiness.get("parameter_reasonableness") or {}).get("issues") or []),
        *(readiness.get("blocking_reasonableness") or []),
    ]
    unique: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        unique.setdefault(_issue_key(item), deepcopy(item))
    return list(unique.values())


def _issue_key(issue: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    rule_or_message = str(issue.get("rule_id") or issue.get("message") or issue.get("reason") or "")
    return (
        rule_or_message,
        str(issue.get("severity") or ""),
        tuple(str(field) for field in issue.get("fields") or ([issue.get("field")] if issue.get("field") else [])),
    )


def _impact_status(introduced: list[dict[str, Any]]) -> str:
    if any(item.get("severity") == "blocked" for item in introduced):
        return "blocked"
    if any(item.get("severity") in {"warning", "needs_input"} for item in introduced):
        return "warning"
    return "ready"


def _impact_summary(
    status: str,
    introduced: list[dict[str, Any]],
    resolved: list[dict[str, Any]],
    package_changed: bool,
) -> str:
    if status == "blocked":
        blocking = next((item for item in introduced if item.get("severity") == "blocked"), None)
        first = blocking.get("message") if blocking else "修改后出现阻断问题。"
        return f"修改后不可应用：{first}"
    if status == "warning":
        warning = next((item for item in introduced if item.get("severity") in {"warning", "needs_input"}), None)
        first = warning.get("message") if warning else "修改后存在需要复核的风险。"
        return f"修改后可应用，但需复核：{first}"
    if resolved:
        return f"修改后未发现新增风险，并消除 {len(resolved)} 项原有问题。"
    if not package_changed:
        return "修改后未发现新增风险，且不会改变当前 SolidWorks 建模参数。"
    return "修改后未发现新增阻断问题，SolidWorks 参数包将随之更新。"


def _mark_standardization_stale(review: dict[str, Any]) -> None:
    review["derived_parameters_stale"] = True
    for item in review.get("standardization_results") or []:
        if not isinstance(item, dict):
            continue
        item["status"] = "stale"
        item["need_human_review"] = True


def _empty_impact(status: str, summary: str, baseline_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "impact_count": 0,
        "direct_changes": [],
        "derived_changes": [],
        "risk_delta": {"introduced": [], "resolved": [], "unchanged_count": 0},
        "generation_readiness": {
            "before_status": None,
            "after_status": None,
            "parameter_package_changed": False,
            "changed_frozen_fields": [],
        },
        "workflow_effects": {
            "standardization_recalculation_required": False,
            "new_generation_required": False,
        },
        "baseline_state": baseline_state,
    }


def _has_action_value(action: dict[str, Any]) -> bool:
    if action.get("type") == "propose_tolerance_patch":
        return any(
            key in action
            for key in ("suggested_tolerance_upper", "suggested_tolerance_lower", "tolerance_upper", "tolerance_lower")
        )
    return action.get("proposed_value") not in (None, "")


def _action_tolerance(action: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    upper = action.get("suggested_tolerance_upper", action.get("tolerance_upper", previous.get("upper")))
    lower = action.get("suggested_tolerance_lower", action.get("tolerance_lower", previous.get("lower")))
    return {"upper": upper, "lower": lower}


def _load_target(target: str) -> tuple[str, str] | None:
    parts = target.split(".")
    if len(parts) == 3 and parts[0] == "load_points" and parts[2] in {"height", "force"}:
        return parts[1], parts[2]
    return None


def _field_label(field: str) -> str:
    load_target = _load_target(field)
    if load_target:
        label, kind = load_target
        return f"载荷测试点 {label} {'高度' if kind == 'height' else '力值'}"
    return COMPRESSION_GENERATION_LABELS.get(field) or FIELD_LABELS.get(field) or field


def _parameter_value(parameters: dict[str, Any], field: str) -> Any:
    item = parameters.get(field)
    return item.get("value") if isinstance(item, dict) else item


def _derived_value(value: Any, unit: Any, formula: str) -> dict[str, Any]:
    number = _number(value)
    normalized = round(number, 4) if number is not None else value
    if isinstance(normalized, float) and normalized.is_integer():
        normalized = int(normalized)
    return {"value": normalized, "unit": unit, "formula": formula}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
