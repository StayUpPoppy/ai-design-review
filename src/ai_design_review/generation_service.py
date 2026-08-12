from __future__ import annotations

import hashlib
import json
from typing import Any


READY_STATUSES = {"ready", "ready_with_warnings"}
DEFAULT_ARTIFACT_TYPES = ["sldprt", "slddrw", "pdf", "png"]


def stable_payload_hash(payload: dict[str, Any]) -> str:
    stable = {key: value for key, value in payload.items() if key != "generated_at"}
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def request_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def match_generation_template(
    review: dict[str, Any],
    parameter_package: dict[str, Any],
    templates: list[dict[str, Any]],
    *,
    requested_code: str | None = None,
) -> dict[str, Any]:
    spring_type = str((review.get("drawing_summary") or {}).get("spring_type") or "unknown_spring")
    parameters = ((parameter_package.get("generation_parameters") or {}).get("spring_parameters") or {})
    values = {
        field: item.get("value") if isinstance(item, dict) else item
        for field, item in parameters.items()
    }
    candidates: list[dict[str, Any]] = []
    for template in templates:
        if not template.get("enabled") or template.get("drawing_type") != spring_type:
            continue
        if requested_code and template.get("template_code") != requested_code:
            continue
        missing = [field for field in template.get("required_fields") or [] if values.get(field) in (None, "")]
        if missing:
            continue
        matched, specificity = _rules_match(values, template.get("match_rules") or {})
        if not matched:
            continue
        candidate = {
            **template,
            "match_score": int(template.get("priority") or 0) * 1000 + specificity,
            "match_specificity": specificity,
        }
        candidates.append(candidate)

    candidates.sort(key=lambda item: (-item["match_score"], item["template_code"], item["version"]))
    if not candidates:
        return {
            "status": "template_not_found",
            "selected_template": None,
            "candidates": [],
            "reason": "没有启用且满足当前图纸类型、必填参数和匹配规则的生图模板。",
        }
    best_score = candidates[0]["match_score"]
    best = [item for item in candidates if item["match_score"] == best_score]
    if len(best) > 1 and not requested_code:
        return {
            "status": "template_selection_required",
            "selected_template": None,
            "candidates": [_public_candidate(item) for item in best],
            "reason": "存在多个同优先级模板，需要人工选择。",
        }
    selected = best[0]
    return {
        "status": "selected",
        "selected_template": _public_candidate(selected),
        "candidates": [_public_candidate(item) for item in candidates],
        "reason": "已按图纸类型、必填参数、匹配规则和优先级选择模板。",
    }


def _rules_match(values: dict[str, Any], rules: dict[str, Any]) -> tuple[bool, int]:
    specificity = 0
    field_rules = rules.get("fields") if isinstance(rules.get("fields"), dict) else {}
    for field, expected in field_rules.items():
        actual = values.get(field)
        allowed = expected if isinstance(expected, list) else [expected]
        if actual not in allowed:
            return False, 0
        specificity += 1

    range_rules = rules.get("ranges") if isinstance(rules.get("ranges"), dict) else {}
    for field, bounds in range_rules.items():
        if not isinstance(bounds, list) or len(bounds) != 2:
            return False, 0
        try:
            actual = float(values.get(field))
            low = float(bounds[0])
            high = float(bounds[1])
        except (TypeError, ValueError):
            return False, 0
        if not low <= actual <= high:
            return False, 0
        specificity += 1
    return True, specificity


def _public_candidate(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "template_code": template.get("template_code"),
        "version": template.get("version"),
        "drawing_type": template.get("drawing_type"),
        "label": template.get("label"),
        "priority": template.get("priority"),
        "is_mock": bool(template.get("is_mock")),
        "worker_capability": template.get("worker_capability"),
        "match_score": template.get("match_score"),
    }
