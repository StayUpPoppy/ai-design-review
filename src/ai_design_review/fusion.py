from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any

from .technical_translation import TRANSLATION_KEYS
from . import flattening
from . import load_point_identity as load_identity
from .standardizers.support_coils import classify_support_candidate
from .technical_requirement_recognition import TECHNICAL_FIELD_TYPES, collect_technical_requirements
from .surface_roughness import ROUGHNESS_VERIFICATION_VERSION, merge_roughness_candidates, verified_roughness_candidate, roughness_selection, selected_roughness_location


SOURCE_PRIORITY = {
    "original_diameter_role": 0.995,
    "local_load_evidence": 0.995,
    "human": 1.0,
    "manual": 0.98,
    "cad": 0.95,
    "dxf": 0.95,
    "dwg": 0.95,
    "dimension_role_ranker": 0.94,
    "werk24": 0.86,
    "qwen_vision": 0.88,
    "baidu_paddleocr_vl": 0.84,
    "baidu_ocr": 0.82,
    "pdf_text_layer": 0.8,
    "rapidocr": 0.78,
    "ocr": 0.78,
    "azure": 0.78,
    "paddle": 0.78,
    "vision": 0.62,
    "openai": 0.62,
    "inference": 0.45,
}


NORMALIZATION_KEYS = (
    "raw_value",
    "standard_value",
    "normalization_status",
    "normalization_source",
    "normalization_confidence",
    "normalization_reason",
)

SURFACE_ROUGHNESS_KEYS = (
    "surface_location",
    "roughness_candidates",
    "roughness_conflict",
)


def source_weight(source: str) -> float:
    lowered = source.lower()
    for key, weight in SOURCE_PRIORITY.items():
        if key in lowered:
            return weight
    return 0.5


def fuse_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = flattening.prepare_candidates(candidates)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    load_points: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for candidate in candidates:
        candidate = classify_support_candidate(candidate)
        field = candidate.get("field")
        if not field:
            continue
        if field == "load_point":
            load_points.append(_normalize_load_point(candidate))
        else:
            grouped[field].append(candidate)

    fields: dict[str, dict[str, Any]] = {}
    for field, items in grouped.items():
        ordered = sorted(items, key=lambda item: (item.get("support_coils_origin") == "drawing_single_end", _candidate_score(item)), reverse=True) if field == "support_coils" else sorted(items, key=_candidate_score, reverse=True)
        selected = _merge_field(field, ordered)
        fields[field] = selected
        conflict = _detect_conflict(field, ordered) if field not in TECHNICAL_FIELD_TYPES and field != "surface_roughness_ra" else None
        if conflict:
            conflicts.append(conflict)
            if ordered[0].get("source") == "original_diameter_role":
                selected["diameter_role_conflict"] = True

    load_points = _merge_load_points(load_points, conflicts)

    return {
        "fields": fields,
        "load_points": load_points,
        "conflicts": conflicts,
        "technical_requirements": collect_technical_requirements([
            {**item, "need_human_review": _needs_human_review(item, [item])}
            if item.get("field") in TECHNICAL_FIELD_TYPES else item
            for item in candidates
        ], preserve_confirmation_policy=True),
    }


def _candidate_score(candidate: dict[str, Any]) -> float:
    confidence = float(candidate.get("confidence", 0) or 0)
    return confidence * _candidate_source_weight(candidate)


def _candidate_source_weight(candidate: dict[str, Any]) -> float:
    source = candidate.get("source", "")
    sources = source if isinstance(source, list) else [source]
    return max((source_weight(str(item)) for item in sources), default=0.5)


def _merge_field(field: str, ordered: list[dict[str, Any]]) -> dict[str, Any]:
    best = ordered[0]
    sources = [item.get("source", "unknown") for item in ordered]
    evidence = " | ".join(
        str(item.get("evidence", "")).strip()
        for item in ordered
        if item.get("evidence")
    )
    confidence = min(
        0.99,
        max(float(best.get("confidence", 0) or 0), _combined_confidence(ordered)),
    )

    merged = {
        "field": field,
        "value": best.get("value"),
        "unit": best.get("unit"),
        "tolerance_upper": best.get("tolerance_upper"),
        "tolerance_lower": best.get("tolerance_lower"),
        "source": sources,
        "evidence": evidence,
        "confidence": round(confidence, 3),
        "page": best.get("page", 1),
        "position": best.get("position"),
        "suggested_region": best.get("suggested_region", ""),
        "need_human_review": _needs_human_review(best, ordered),
        **{key: best[key] for key in ("engineering_source", "unit_pending") if key in best},
    }
    for key in (*NORMALIZATION_KEYS, *TRANSLATION_KEYS, "surface_mapping", "raw_content", "standard_content", "diameter_role_evidence"):
        if key in best:
            merged[key] = best[key]
    if field == "support_coils":
        for key in ("support_coils_origin", "support_coils_original"):
            if key in best:
                merged[key] = best[key]
        # Keep the selected evidence separate from other engines' arithmetic.
        merged["evidence"] = best.get("evidence") or ""
    if field == "flattening":
        flattening.merge_candidates(merged, ordered)
        if not flattening.human(best):
            merged["need_human_review"] = True
    if field == "surface_roughness_ra":
        candidates = _surface_roughness_candidates(ordered)
        merged["roughness_candidates"] = candidates
        if candidates and all(c.get("verification_version") == ROUGHNESS_VERIFICATION_VERSION for c in candidates):
            merged["verification_version"] = ROUGHNESS_VERIFICATION_VERSION
            merged["source_document_id"] = candidates[0].get("source_document_id")
        accepted, conflict, recognition_state = roughness_selection(candidates)
        merged["recognition_state"] = recognition_state
        merged["value_verified"] = bool(accepted) and not conflict
        merged["need_human_review"] = True
        if conflict:
            merged["value"] = None
            merged["roughness_conflict"] = True
            merged["need_human_review"] = True
        elif accepted:
            merged["value"] = accepted[0]["value"]
            merged["surface_location"] = selected_roughness_location(accepted)
            first = next((c for c in accepted if verified_roughness_candidate(c)), accepted[0])
            merged["page"], merged["position"] = first.get("page", 1), first.get("position") if verified_roughness_candidate(first) else None
        else:
            merged["value"] = None
            merged["surface_location"] = None
            merged["need_human_review"] = True
        for key in SURFACE_ROUGHNESS_KEYS:
            if key in best and key not in merged:
                merged[key] = best[key]
    return merged


def _surface_roughness_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return merge_roughness_candidates(items)


def _normalize_load_point(candidate: dict[str, Any]) -> dict[str, Any]:
    value = dict(candidate.get("value") or {})
    return {
        "field": "load_point",
        "value": value,
        "source": candidate.get("source") if isinstance(candidate.get("source"), list) else [candidate.get("source", "unknown")],
        "evidence": candidate.get("evidence", ""),
        "confidence": float(candidate.get("confidence", 0) or 0),
        "page": candidate.get("page", 1),
        "position": candidate.get("position"),
        "suggested_region": candidate.get("suggested_region", ""),
        "need_human_review": _candidate_source_weight(candidate) < 0.98,
        "source_context": load_identity.context(candidate),
        **({"reported_units": candidate["reported_units"]} if "reported_units" in candidate else {}),
    }


def _merge_load_points(load_points: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = load_identity.group_load_points(load_points)
    groups.sort(key=lambda group: min(map(load_identity.diagram_order, group)))
    names = [_station_names(group) for group in groups]
    original_names = [dict(item) for item in names]
    load_identity.assign_load_names(names)
    aliases = defaultdict(set)
    for group, assigned in zip(groups, names):
        for point in group:
            if old_label := point["value"].get("label"):
                for source in load_identity.sources(point):
                    aliases[load_identity.scope(point), source, str(old_label).casefold()].add(assigned["label"])

    result = []
    for group, assigned, originals in zip(groups, names, original_names):
        adjusted = []
        for point in group:
            height_relation = load_identity.relation(point)
            base = str(height_relation.get("base_label") or "").casefold()
            targets = {target for source in load_identity.sources(point)
                       for target in aliases[load_identity.scope(point), source, base]} if base else set()
            if len(targets) == 1:
                point = {**point, "value": {**point["value"], "height_relation": {**height_relation, "base_label": next(iter(targets))}}}
            adjusted.append(point)
        fused = _merge_load_point(assigned["label"], adjusted, conflicts)
        fused["value"].update(assigned)
        fused["source_context"].update(force_label_inferred=not originals["label"], height_label_inferred=not originals["height_label"])
        result.append(fused)
    return result


def _station_names(points):
    preferred = sorted(points, key=lambda point: ("local_load_evidence" in load_identity.sources(point), _candidate_score(point)), reverse=True)
    return {field: next((label for point in preferred if (label := load_identity.explicit_label(point, field))), "")
            for field in ("label", "height_label")}


def _merge_load_point(
    label: str,
    points: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    from .load_height_relations import millimeters, model_load_relation
    ordered = sorted(points, key=_candidate_score, reverse=True)
    best = ordered[0]
    merged_value: dict[str, Any] = {}
    value_keys = (
        "label",
        "height",
        "height_unit",
        "force",
        "force_unit",
        "force_tolerance_percent",
        "load_tolerance_upper",
        "load_tolerance_lower",
        "load_tolerance_percent",
        "test_height_type", "deflection", "deflection_unit", "height_calculation", "height_relation", "load_role",
    )
    for key in value_keys:
        merged_value[key] = _first_load_point_value(ordered, key)
    force_points = [p for p in ordered if (p.get("value") or {}).get("force") is not None]
    local_force = [p for p in force_points if "local_load_evidence" in load_identity.sources(p)]
    verified_force = [p for p in local_force if p["value"].get("force_evidence_verified") is True]
    located_together = any(load_identity.same_station(a, b) for i, a in enumerate(ordered) for b in ordered[i+1:])
    comparable_force = force_points if located_together else verified_force
    force_identities = {round(force, 8) for p in comparable_force if (force := load_identity.readings(p)[0]) is not None}
    force_conflict = len(force_identities)>1 or any(p["value"].get("load_force_conflict") for p in local_force)
    if force_conflict:
        merged_value["load_force_conflict"] = True
        display_unit = (verified_force or local_force or force_points)[0]["value"].get("force_unit")
        factor = load_identity.force_newtons(1, display_unit) or 1
        alternatives = {round(force / factor, 8) for force in force_identities}
        alternatives.update(n for p in local_force for n in p["value"].get("force_alternatives", []) if p["value"].get("force_unit") == display_unit)
        merged_value["force_alternatives"] = sorted(alternatives)
        conflicts.append({"field":f"load_points.{label}.force","message":"同一原图载荷标注有多个力值读数，请核对",
                          "need_human_review":True})
    elif verified_force:
        merged_value["force_evidence_verified"] = True
    if force_points:
        force_bundle = (verified_force or local_force or force_points)[0]["value"]
        tolerance_keys=("load_tolerance_upper","load_tolerance_lower","load_tolerance_percent","force_tolerance_percent")
        if not verified_force and not force_conflict and all(force_bundle.get(k) is None for k in tolerance_keys):
            base_force = load_identity.force_newtons(force_bundle.get("force"), force_bundle.get("force_unit"))
            for candidate in force_points[1:]:
                bundle=candidate["value"]
                other_force = load_identity.force_newtons(bundle.get("force"), bundle.get("force_unit"))
                if base_force is not None and other_force is not None and abs(base_force-other_force)<=1e-9 and any(bundle.get(k) is not None for k in tolerance_keys):
                    force_bundle=bundle
                    break
        for key in ("force", "force_unit", "load_tolerance_upper", "load_tolerance_lower", "load_tolerance_percent", "force_tolerance_percent", "force_tolerance_status"):
            merged_value[key] = force_bundle.get(key)
    relations = [p["value"]["height_relation"] for p in ordered if isinstance(p.get("value", {}).get("height_relation"), dict)]
    trusted_height_sources=("local_load_evidence", "rapidocr", "baidu", "pdf_text_layer", "ocr")
    verified = [p for p in ordered if isinstance(p.get("value", {}).get("height_relation"), dict) and p["value"]["height_relation"].get("verified")
                and "qwen" not in str(p.get("source")) and any(name in str(p.get("source")) for name in trusted_height_sources)]
    provisional = None
    if not verified:
        drafts=[r for p in ordered if p["value"].get("force")==merged_value["force"]
                and str(p["value"].get("force_unit") or "").casefold()==str(merged_value["force_unit"] or "").casefold()
                if (r:=model_load_relation(p))]
        if len({millimeters(r["value"],r["unit"]) for r in drafts})==1:
            provisional=drafts[0]
    if relations:
        from .load_height_dimension import HEIGHT_FIELDS
        from .load_height_relations import normalize_relation
        selected = verified[0] if verified else next((p for p in ordered if isinstance(p.get("value", {}).get("height_relation"), dict) and p["value"]["height_relation"].get("kind")!="unknown"),
                                                   next(p for p in ordered if isinstance(p.get("value", {}).get("height_relation"), dict)))
        merged_value["height_relation"] = provisional or normalize_relation(selected["value"]["height_relation"], trusted=selected in verified)
        if selected in verified:
            merged_value.update({key:selected["value"][key] for key in HEIGHT_FIELDS if key in selected["value"]})
        local_identity = next((p["value"] for p in ordered if "local_load_evidence" in str(p.get("source"))), {})
        if local_identity.get("height_label"):
            merged_value.setdefault("height_label",local_identity["height_label"])
    if any(p.get("value",{}).get("load_height_conflict") for p in ordered):
        merged_value["load_height_conflict"]=True
        conflicts.append({"field":f"load_points.{label}.height_relation","message":"原图存在不同的工作高度，请核对","need_human_review":True})
    credible = [p["value"]["height_relation"] for p in verified]
    if len(credible)>1:
        signatures={(r.get("kind"),millimeters(r.get("value"),r.get("unit")),r.get("base_label") or r.get("base_point_id") or "") for r in credible}
        if len(signatures)>1:
            merged_value["load_height_conflict"]=True
            conflicts.append({"field":f"load_points.{label}.height_relation","message":"载荷高度存在不同的原图尺寸关系，请核对","need_human_review":True})
    heights = sorted({round(height, 8) for point in ordered if (height := load_identity.readings(point)[1]) is not None})
    if located_together and len(heights) > 1:
        merged_value["load_height_conflict"] = True
        reason = "高度待核对（" + " / ".join(f"{height:g}" for height in heights) + " mm）"
        if merged_value.get("height_relation"):
            merged_value["height_relation"]["verification_failure"] = reason
        conflicts.append({"field": f"load_points.{label}.height_relation", "message": reason, "values": heights, "need_human_review": True})
    merged_value["label"] = label
    merged_value["reference_only"] = all(bool((item.get("value") or {}).get("reference_only")) for item in ordered)

    for key, display_name in (("height", "height"), ("force", "force")):
        if key=="height" and (verified or merged_value.get("load_height_conflict")) or key=="force" and (verified_force or force_conflict):
            continue
        values = [load_identity.readings(item)[0 if key == "force" else 1] for item in ordered]
        values = [value for value in values if value not in (None, "")]
        if len(values) > 1 and any(not _values_close(values[0], value) for value in values[1:]):
            conflicts.append(
                {
                    "field": f"load_points.{label}.{key}",
                    "values": values,
                    "sources": _all_sources(ordered),
                    "message": f"Load point {label} has conflicting {display_name} values from multiple sources.",
                    "need_human_review": True,
                }
            )

    bundles = [p["value"] for p in (verified_force or ordered) if any((p.get("value") or {}).get(k) is not None for k in ("load_tolerance_upper", "load_tolerance_lower", "load_tolerance_percent", "force_tolerance_percent"))]
    if len(bundles)>1 and any(any(b.get(k)!=bundles[0].get(k) for k in ("load_tolerance_upper","load_tolerance_lower","load_tolerance_percent","force_tolerance_percent")) for b in bundles[1:]):
        conflicts.append({"field": f"load_points.{label}.tolerance", "message": "载荷点存在不同力值公差，请核对原图", "need_human_review": True})
        merged_value["load_relation_conflict"] = True
    confidence = min(0.99, max(float(best.get("confidence", 0) or 0), _combined_confidence(ordered)))
    has_conflict = any(
        item.get("field", "").startswith(f"load_points.{label}.")
        for item in conflicts
    )
    return {
        "field": "load_point",
        "value": merged_value,
        "source": _all_sources(ordered),
        "evidence": _join_evidence(ordered),
        "confidence": round(confidence, 3),
        "page": best.get("page", 1),
        "position": best.get("position"),
        "suggested_region": best.get("suggested_region", ""),
        "need_human_review": bool(provisional) or has_conflict or any("local_load_evidence" in str(p.get("source")) for p in ordered) or _needs_human_review(best, ordered),
        "source_context": dict(next((point["source_context"] for point in ordered if point.get("source_context")), {})),
    }


def _first_load_point_value(points: list[dict[str, Any]], key: str) -> Any:
    for point in points:
        value = _load_point_value(point, key)
        if value not in (None, ""):
            return value
    return None


def _load_point_value(point: dict[str, Any], key: str) -> Any:
    return (point.get("value") or {}).get(key)


def _all_sources(items: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    for item in items:
        source = item.get("source", "unknown")
        raw_sources = source if isinstance(source, list) else [source]
        for value in raw_sources:
            text = str(value or "unknown")
            if text not in sources:
                sources.append(text)
    return sources


def _join_evidence(items: list[dict[str, Any]]) -> str:
    evidence: list[str] = []
    for item in items:
        value = str(item.get("evidence", "")).strip()
        if value and value not in evidence:
            evidence.append(value)
    return " | ".join(evidence)


def _number_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _combined_confidence(items: list[dict[str, Any]]) -> float:
    if len(items) == 1:
        return float(items[0].get("confidence", 0) or 0)
    score = 1.0
    for item in items[:3]:
        score *= 1 - min(0.95, _candidate_score(item))
    return 1 - score


def _needs_human_review(best: dict[str, Any], ordered: list[dict[str, Any]]) -> bool:
    if best.get("source") == "original_diameter_role":
        return True
    confidence = float(best.get("confidence", 0) or 0)
    if _candidate_source_weight(best) >= 0.98 and confidence >= 0.95:
        return False
    if len(ordered) < 2:
        return True
    return confidence < 0.9


def _detect_conflict(field: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(items) < 2:
        return None
    values = [item.get("value") for item in items]
    first = values[0]
    if items[0].get("source") == "original_diameter_role":
        for item in items[1:]:
            if any(items[0].get(key) is not None and item.get(key) is not None
                   and not _values_close(items[0][key], item[key]) for key in ("tolerance_upper", "tolerance_lower")):
                return {"field": field, "values": values, "sources": [item.get("source", "unknown") for item in items],
                        "message": f"{field} 多条原图尺寸的公差不一致，需要人工确认。", "need_human_review": True}
    for value in values[1:]:
        if not _values_close(first, value):
            return {
                "field": field,
                "values": values,
                "sources": [item.get("source", "unknown") for item in items],
                "message": f"{field} 多个来源识别结果不一致，需要人工确认。",
                "need_human_review": True,
            }
    return None


def _values_close(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-6
    return str(left).strip() == str(right).strip()
