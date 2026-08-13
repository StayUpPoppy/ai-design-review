from __future__ import annotations

import hashlib
import json
from typing import Any

from .spring_templates import FIELD_LABELS


APPLICABLE_STATUSES = {"suggested", "llm_suggested"}


def build_standardization_batch(
    review: dict[str, Any],
    *,
    review_revision: int | None = None,
) -> dict[str, Any]:
    """Build an immutable, UI-oriented snapshot of applicable standardization results."""
    results = [item for item in review.get("standardization_results", []) or [] if isinstance(item, dict)]
    applicable_groups: dict[str, list[int]] = {}
    for index, item in enumerate(results):
        if _is_applicable(item):
            target = str(item.get("target_field") or "").strip()
            if target:
                applicable_groups.setdefault(target, []).append(index)
    conflict_targets = {target for target, indexes in applicable_groups.items() if len(indexes) > 1}

    items: list[dict[str, Any]] = []
    skipped_items: list[dict[str, Any]] = []
    baseline_targets: dict[str, Any] = {}
    result_signatures: list[dict[str, Any]] = []
    for index, item in enumerate(results):
        target = str(item.get("target_field") or "").strip()
        before = _current_target_state(review, target)
        if target:
            baseline_targets[target] = before
        result_signatures.append(_result_signature(item))

        reason = _skip_reason(item, target, conflict_targets)
        if not reason and _parse_load_target(target) and not before.get("exists"):
            reason = "对应的载荷测试点不存在，无法安全写入。"
        if reason:
            if item.get("status") != "human_confirmed":
                skipped_items.append(_batch_item(index, item, before, before, [], can_apply=False, reason=reason))
            continue

        after = _proposed_target_state(before, item)
        change_types = _change_types(before, after)
        if not change_types:
            continue
        items.append(_batch_item(index, item, before, after, change_types, can_apply=True, reason=""))

    baseline = {
        "targets": baseline_targets,
        "standardization_results": result_signatures,
    }
    fingerprint = _stable_hash(baseline)
    status = "ready" if items else "no_changes"
    return {
        "batch_id": f"standardization_batch_{fingerprint[:20]}",
        "status": status,
        "review_revision": review_revision,
        "baseline_fingerprint": fingerprint,
        "result_fingerprint": _stable_hash(result_signatures),
        "applicable_count": len(items),
        "skipped_count": len(skipped_items),
        "items": items,
        "skipped_items": skipped_items,
        "baseline_state": baseline,
        "applied_count": 0,
        "applied_at": None,
    }


def _batch_item(
    index: int,
    item: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    change_types: list[str],
    *,
    can_apply: bool,
    reason: str,
) -> dict[str, Any]:
    target = str(item.get("target_field") or "").strip()
    return {
        "result_index": index,
        "target_field": target,
        "label": _target_label(target),
        "rule_id": str(item.get("rule_id") or ""),
        "standard_no": str(item.get("standard_no") or ""),
        "unit": str(item.get("unit") or after.get("unit") or before.get("unit") or ""),
        "before": before,
        "after": after,
        "change_types": change_types,
        "can_apply": can_apply,
        "reason": reason,
        "basis": str(item.get("basis") or ""),
    }


def _is_applicable(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "")
    target = str(item.get("target_field") or "").strip()
    metadata = item.get("metadata") or {}
    if metadata.get("target_field_valid") is False or metadata.get("target_field_error"):
        return False
    return bool(target) and status in APPLICABLE_STATUSES


def _skip_reason(item: dict[str, Any], target: str, conflict_targets: set[str]) -> str:
    status = str(item.get("status") or "")
    metadata = item.get("metadata") or {}
    if not target:
        return "缺少目标字段，无法写入参数栏位。"
    if metadata.get("target_field_valid") is False or metadata.get("target_field_error"):
        return "目标字段不受支持，无法安全写入。"
    if target in conflict_targets:
        return "该字段存在多个标准化方案，请逐项选择。"
    if status == "stale":
        return "参数已经变化，这条标准化结果已过期。"
    if status == "need_context":
        missing = [str(field) for field in metadata.get("missing_fields", []) or [] if field]
        if missing:
            labels = "、".join(_target_label(field) for field in missing)
            return f"缺少{labels}，暂时无法计算。"
        return "缺少计算条件，暂时无法应用。"
    if status == "not_applicable":
        return "当前参数不在该标准规则的适用范围内。"
    if status == "human_confirmed":
        return ""
    if not _is_applicable(item):
        return "当前结果状态不允许批量应用。"
    return ""


def _current_target_state(review: dict[str, Any], target: str) -> dict[str, Any]:
    parameters = review.get("spring_parameters") or {}
    load_target = _parse_load_target(target)
    if load_target:
        label = load_target[0]
        point = next(
            (
                candidate
                for candidate in parameters.get("load_points", []) or []
                if isinstance(candidate, dict) and str(candidate.get("label") or "") == label
            ),
            None,
        )
        if point is None:
            return {"exists": False, "value": None, "tolerance_upper": None, "tolerance_lower": None, "unit": "", "confirmed": False}
        return {
            "exists": True,
            "value": point.get("force"),
            "tolerance_upper": point.get("load_tolerance_upper"),
            "tolerance_lower": point.get("load_tolerance_lower"),
            "unit": point.get("force_unit") or "N",
            "confirmed": not bool(point.get("need_human_review")),
        }

    param = parameters.get(target)
    if not isinstance(param, dict):
        return {"exists": False, "value": None, "tolerance_upper": None, "tolerance_lower": None, "unit": "", "confirmed": False}
    return {
        "exists": True,
        "value": param.get("value"),
        "tolerance_upper": param.get("tolerance_upper"),
        "tolerance_lower": param.get("tolerance_lower"),
        "unit": param.get("unit") or "",
        "confirmed": not bool(param.get("need_human_review")),
    }


def _proposed_target_state(before: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    has_tolerance = item.get("suggested_tolerance_upper") is not None or item.get("suggested_tolerance_lower") is not None
    return {
        "exists": True,
        "value": item.get("suggested_value") if item.get("suggested_value") is not None else before.get("value"),
        "tolerance_upper": item.get("suggested_tolerance_upper") if has_tolerance else before.get("tolerance_upper"),
        "tolerance_lower": item.get("suggested_tolerance_lower") if has_tolerance else before.get("tolerance_lower"),
        "unit": item.get("unit") or before.get("unit") or "",
        "confirmed": True,
    }


def _change_types(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    if not before.get("exists"):
        changes.append("created")
    if before.get("value") != after.get("value"):
        changes.append("value")
    if before.get("tolerance_upper") != after.get("tolerance_upper") or before.get("tolerance_lower") != after.get("tolerance_lower"):
        changes.append("tolerance")
    if not before.get("confirmed") and after.get("confirmed"):
        changes.append("confirmation")
    return changes


def _result_signature(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    return {
        "target_field": item.get("target_field"),
        "rule_id": item.get("rule_id"),
        "status": item.get("status"),
        "suggested_value": item.get("suggested_value"),
        "suggested_tolerance_upper": item.get("suggested_tolerance_upper"),
        "suggested_tolerance_lower": item.get("suggested_tolerance_lower"),
        "unit": item.get("unit"),
        "target_field_valid": metadata.get("target_field_valid"),
        "target_field_error": metadata.get("target_field_error"),
    }


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_load_target(target: str) -> tuple[str, str] | None:
    parts = str(target or "").split(".")
    if len(parts) == 3 and parts[0] == "load_points" and parts[2] == "force":
        return parts[1], parts[2]
    return None


def _target_label(target: str) -> str:
    load_target = _parse_load_target(target)
    if load_target:
        return f"载荷测试点 {load_target[0]} 力值"
    return FIELD_LABELS.get(target) or target or "未知字段"
