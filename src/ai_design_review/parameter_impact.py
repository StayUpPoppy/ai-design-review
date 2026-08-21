from __future__ import annotations

from copy import deepcopy
from typing import Any

from .generation_contract import (
    COMPRESSION_GENERATION_INPUT_FIELDS,
    COMPRESSION_GENERATION_LABELS,
    generation_source_item,
)
from .generation_readiness import assess_generation_readiness, build_generation_parameter_package
from .load_points import canonical_load_point_label, load_point_snapshot, new_load_point_id, normalize_load_point_label
from .spring_templates import FIELD_LABELS
from .standardizers.compression import calculate_compression_solid_height, derive_compression_parameters


PARAMETER_ACTION_TYPES = {"propose_parameter_patch", "propose_tolerance_patch"}
TECHNICAL_REQUIREMENT_ACTION_TYPES = {
    "propose_technical_requirement_add",
    "propose_technical_requirement_update",
    "propose_technical_requirement_delete",
}
LOAD_POINT_ACTION_TYPES = {"propose_load_point_add", "propose_load_point_update", "propose_load_point_delete"}
APPLICABLE_ACTION_TYPES = PARAMETER_ACTION_TYPES | TECHNICAL_REQUIREMENT_ACTION_TYPES | LOAD_POINT_ACTION_TYPES


def assess_parameter_change_impact(review: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulate AI chat patches and describe their deterministic downstream effects."""

    baseline_state = build_impact_baseline_state(review)
    applicable = [
        action
        for action in actions
        if isinstance(action, dict)
        and action.get("type") in APPLICABLE_ACTION_TYPES
        and _is_applicable_action(action)
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
    parameter_changes_applied = any(
        action.get("type") in PARAMETER_ACTION_TYPES
        for action in applicable
    )
    if parameter_changes_applied:
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

    before_generation_parameters = (
        build_generation_parameter_package(before_review).get("generation_parameters") or {}
    )
    after_generation_parameters = (
        build_generation_parameter_package(after_review).get("generation_parameters") or {}
    )
    before_package = before_generation_parameters.get("spring_parameters") or {}
    after_package = after_generation_parameters.get("spring_parameters") or {}
    package_changed = before_package != after_package
    before_requirements = before_generation_parameters.get("technical_requirements") or []
    after_requirements = after_generation_parameters.get("technical_requirements") or []
    technical_requirements_changed = before_requirements != after_requirements
    before_load_points = before_generation_parameters.get("load_points") or []
    after_load_points = after_generation_parameters.get("load_points") or []
    load_points_changed = before_load_points != after_load_points
    package_changed = package_changed or technical_requirements_changed or load_points_changed
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
            "technical_requirements_changed": technical_requirements_changed,
            "load_points_changed": load_points_changed,
        },
        "workflow_effects": {
            "standardization_recalculation_required": parameter_changes_applied,
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
    if action.get("type") in TECHNICAL_REQUIREMENT_ACTION_TYPES:
        return _apply_technical_requirement_action(review, action)
    if action.get("type") in LOAD_POINT_ACTION_TYPES:
        return _apply_load_point_action(review, action)

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


def _apply_technical_requirement_action(
    review: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any] | None:
    requirements = review.setdefault("technical_requirements", [])
    if not isinstance(requirements, list):
        requirements = []
        review["technical_requirements"] = requirements

    action_type = str(action.get("type") or "")
    requirement_id = str(
        action.get("requirement_id")
        or action.get("target_requirement_id")
        or ""
    ).strip()
    requirement_type = str(
        action.get("requirement_type")
        or action.get("proposed_type")
        or action.get("technical_requirement_type")
        or "other"
    ).strip() or "other"
    content = str(
        action.get("content")
        or action.get("proposed_content")
        or ""
    ).strip()

    if action_type == "propose_technical_requirement_add":
        if not content:
            return None
        if any(
            isinstance(item, dict)
            and str(item.get("type") or "other") == requirement_type
            and str(item.get("content") or "").strip() == content
            for item in requirements
        ):
            return None
        requirement_id = requirement_id or f"techreq_preview_add_{len(requirements) + 1}"
        after = {
            "requirement_id": requirement_id,
            "type": requirement_type,
            "content": content,
            "need_human_review": False,
            "confirmation_source": "human_confirmed",
        }
        requirements.append(after)
        return _technical_requirement_direct_change("add", requirement_id, None, after)

    target_index = next(
        (
            index
            for index, item in enumerate(requirements)
            if isinstance(item, dict)
            and str(item.get("requirement_id") or "").strip() == requirement_id
        ),
        None,
    )
    if target_index is None:
        return None
    current = requirements[target_index]
    before = deepcopy(current)

    if action_type == "propose_technical_requirement_delete":
        requirements.pop(target_index)
        return _technical_requirement_direct_change("delete", requirement_id, before, None)

    if not content and not any(
        key in action for key in ("requirement_type", "proposed_type", "technical_requirement_type")
    ):
        return None
    updated = deepcopy(current)
    if content:
        updated["content"] = content
    if any(key in action for key in ("requirement_type", "proposed_type", "technical_requirement_type")):
        updated["type"] = requirement_type
    updated["need_human_review"] = False
    updated["confirmation_source"] = "human_confirmed"
    requirements[target_index] = updated
    return _technical_requirement_direct_change("update", requirement_id, before, updated)


def _technical_requirement_direct_change(
    operation: str,
    requirement_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "field": f"technical_requirements.{requirement_id}",
        "label": "技术要求",
        "change_type": f"technical_requirement_{operation}",
        "operation": operation,
        "requirement_id": requirement_id,
        "before": _public_requirement_change_value(before),
        "after": _public_requirement_change_value(after),
        "unit": None,
        "confirmation_after": "human_confirmed" if after is not None else None,
    }


def _apply_load_point_action(review: dict[str, Any], action: dict[str, Any]) -> dict[str, Any] | None:
    parameters = review.setdefault("spring_parameters", {})
    points = parameters.setdefault("load_points", [])
    operation = str(action.get("type") or "").removeprefix("propose_load_point_")
    point_id = str(action.get("load_point_id") or action.get("target_load_point_id") or "").strip()
    if operation == "add":
        label = normalize_load_point_label(action.get("label"))
        if not label or action.get("height") in (None, "") or action.get("force") in (None, ""):
            return None
        if any(isinstance(item, dict) and canonical_load_point_label(item.get("label")) == canonical_load_point_label(label) for item in points):
            return None
        point_id = point_id or new_load_point_id()
        after = _preview_load_point({}, point_id, label, action)
        points.append(after)
        return _load_point_direct_change(operation, point_id, None, after)
    if not point_id:
        return None
    index = next((index for index, item in enumerate(points) if isinstance(item, dict) and str(item.get("load_point_id") or "") == point_id), None)
    if index is None:
        return None
    before = deepcopy(points[index])
    if operation == "delete":
        points.pop(index)
        return _load_point_direct_change(operation, point_id, before, None)
    after = _preview_load_point(before, point_id, str(before.get("label") or ""), action)
    points[index] = after
    return _load_point_direct_change(operation, point_id, before, after)


def _preview_load_point(current: dict[str, Any], point_id: str, label: str, action: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(current)
    for field in ("height", "force", "load_tolerance_upper", "load_tolerance_lower"):
        if field in action:
            item[field] = action.get(field)
    item.update({"load_point_id": point_id, "label": label, "height_unit": "mm", "force_unit": "N", "need_human_review": False})
    return item


def _load_point_direct_change(operation: str, point_id: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "field": f"load_points.{point_id}",
        "label": "载荷测试点",
        "change_type": f"load_point_{operation}",
        "operation": operation,
        "load_point_id": point_id,
        "before": load_point_snapshot(before) if isinstance(before, dict) else None,
        "after": load_point_snapshot(after) if isinstance(after, dict) else None,
        "unit": None,
        "confirmation_after": "human_confirmed" if after is not None else None,
    }


def _public_requirement_change_value(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "type": str(item.get("type") or "other"),
        "content": str(item.get("content") or "").strip(),
    }


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
            "technical_requirements_changed": False,
            "load_points_changed": False,
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


def _is_applicable_action(action: dict[str, Any]) -> bool:
    action_type = action.get("type")
    if action_type in PARAMETER_ACTION_TYPES:
        return bool(action.get("target_field")) and _has_action_value(action)
    if action_type == "propose_load_point_add":
        return True
    if action_type in {"propose_load_point_update", "propose_load_point_delete"}:
        return bool(action.get("load_point_id") or action.get("target_load_point_id"))
    if action_type == "propose_technical_requirement_add":
        return bool(str(action.get("content") or action.get("proposed_content") or "").strip())
    if action_type == "propose_technical_requirement_update":
        has_update = bool(str(action.get("content") or action.get("proposed_content") or "").strip()) or any(
            key in action for key in ("requirement_type", "proposed_type", "technical_requirement_type")
        )
        return bool(action.get("requirement_id") or action.get("target_requirement_id")) and has_update
    if action_type == "propose_technical_requirement_delete":
        return bool(action.get("requirement_id") or action.get("target_requirement_id"))
    return False


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
