"""Deterministic load-height chains. Original dimensions never become displacements twice."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

VERSION = "load-height/v1"
KINDS = {"absolute_height", "free_deflection", "incremental_deflection", "unknown"}
LENGTH_UNITS = {"mm": 1., "毫米": 1., "cm": 10., "厘米": 10., "m": 1000., "米": 1000., "in": 25.4, "inch": 25.4}


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)) or str(value).strip() == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def millimeters(value: Any, unit: Any) -> float | None:
    value, factor = number(value), LENGTH_UNITS.get(str(unit or "").strip().lower())
    return round(value * factor, 12) if value is not None and factor is not None else None


def normalize_relation(value: Any, *, trusted: bool = False) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind") if value.get("kind") in KINDS else "unknown"
    result = {"version": VERSION, "kind": kind, "mode": "manual" if trusted and value.get("mode") == "manual" else "automatic",
              "value": number(value.get("value")), "unit": str(value.get("unit") or ""),
              "base_label": str(value.get("base_label") or "").strip(),
              "base_point_id": str(value.get("base_point_id") or ""),
              "reference_only": bool(value.get("reference_only")), "evidence": str(value.get("evidence") or ""),
              "verified": bool(trusted and value.get("verified")),
              "evidence_refs": deepcopy(value.get("evidence_refs") or []),
              "page": value.get("page", 1), "scope": str(value.get("scope") or "")}
    for key in ("last_inputs", "formula", "status", "reason", "verification_method", "source_document_id", "preserve_existing_value"):
        if trusted and key in value:
            result[key] = deepcopy(value[key])
    return result


def relation_snapshot(point: dict[str, Any]) -> dict[str, Any] | None:
    relation = point.get("height_relation")
    if not isinstance(relation, dict):
        return None
    return {key: deepcopy(relation.get(key)) for key in ("version", "kind", "mode", "value", "unit", "base_point_id", "reference_only", "verified", "last_inputs", "status")}


def mark_manual_height(point: dict[str, Any]) -> None:
    if isinstance(point.get("height_relation"), dict):
        point["height_relation"].update(mode="manual", status="manual", reason="", formula="")


def _same_scope(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ra, rb = a.get("height_relation") or {}, b.get("height_relation") or {}
    return (ra.get("page", a.get("page", 1)) == rb.get("page", b.get("page", 1))
            and ra.get("scope", "") == rb.get("scope", ""))


def adopt_structured_deflections(review):
    """Migrate existing explicit deflection calculations, never reverse-engineer a height."""
    for point in (review.get("spring_parameters") or {}).get("load_points", []):
        calculation=point.get("height_calculation") or {}
        sources=point.get("source") or []
        sources=[sources] if isinstance(sources,str) else sources
        if point.get("height_relation") or calculation.get("formula")!="H0-deflection" or any(str(s).startswith(("human_edited","manual","human_added")) for s in sources):
            continue
        delta=millimeters(point.get("deflection"),point.get("deflection_unit"))
        old_h0=number(calculation.get("free_length"))
        height=millimeters(point.get("height"),point.get("height_unit"))
        if delta is None or old_h0 is None or height is None or abs(height-(old_h0-delta))>1e-9:
            continue
        point["height_relation"]={"version":VERSION,"kind":"free_deflection","mode":"automatic","value":delta,"unit":"mm",
            "verified":True,"verification_method":"structured_deflection","page":point.get("page",1),
            "scope":str((review.get("multi_spec_origin") or {}).get("variant_id") or ""),"reference_only":bool(point.get("reference_only")),
            "evidence":point.get("evidence") or "原规格表明确的变形量",
            "last_inputs":{"free_length_mm":old_h0,"dimension_mm":delta,"kind":"free_deflection","reference_only":bool(point.get("reference_only"))}}


def refresh_load_heights(review: dict[str, Any]) -> list[dict[str, Any]]:
    """Refresh automatic relations only. Confirmation, manual blanks and old points are protected."""
    if (review.get("drawing_summary") or {}).get("spring_type") not in (None, "compression_spring"):
        return []
    adopt_structured_deflections(review)
    parameters = review.get("spring_parameters") or {}
    points = parameters.get("load_points") or []
    free = parameters.get("free_length") or {}
    free_height = millimeters(free.get("value"), free.get("unit")) if isinstance(free, dict) else None
    by_id = {p.get("load_point_id"): p for p in points if isinstance(p, dict) and p.get("load_point_id")}
    changes, visited, visiting = [], {}, set()

    def resolve(point):
        key = point.get("load_point_id") or id(point)
        if key in visited:
            return visited[key]
        relation = point.get("height_relation")
        if not isinstance(relation, dict) or relation.get("mode") == "manual":
            value = millimeters(point.get("height"), point.get("height_unit"))
            return value if value is not None and value > 0 else None
        if relation.get("preserve_existing_value") and not relation.get("verified"):
            value=millimeters(point.get("height"),point.get("height_unit"))
            if value is not None and value>0:
                return value
        before = {"height": point.get("height"), "height_unit": point.get("height_unit"), "need_human_review": point.get("need_human_review"), "height_relation": deepcopy(relation)}
        reason, value, inputs, formula = "", None, {}, ""
        kind = relation.get("kind")
        if key in visiting:
            return None
        visiting.add(key)
        distance = millimeters(relation.get("value"), relation.get("unit"))
        if not relation.get("verified") or kind == "unknown":
            reason = "高度尺寸的起止关系尚未核实，请核对原图"
        elif distance is None or distance < 0:
            reason = "原始高度/行程的数值或单位无效"
        elif point.get("load_height_conflict"):
            reason = "原图高度或公差证据存在冲突，请核对"
        elif kind == "absolute_height":
            value, formula = distance, "H = 原图工作高度"
        elif kind == "free_deflection":
            if free_height is None or free_height <= 0:
                reason = "缺少有效自由高度，工作高度保持空值"
            elif free.get("derived_value_stale") or free.get("formula_recommendation_stale"):
                reason = "自由高度已失效，请先核对"
            else:
                value, formula = free_height - distance, "H = H0 - S"
                inputs["free_length_mm"] = free_height
        elif kind == "incremental_deflection":
            base_id = relation.get("base_point_id")
            if base_id:
                base = by_id.get(base_id)
            else:
                candidates = [p for p in points if str(p.get("label") or "").strip().casefold() == str(relation.get("base_label") or "").casefold() and _same_scope(point, p)]
                base = candidates[0] if len(candidates) == 1 else None
                if base:
                    relation["base_point_id"] = base.get("load_point_id") or ""
            if not base or not _same_scope(point, base):
                reason = "追加行程的参考载荷点未唯一确定或已删除"
            else:
                base_height = resolve(base)
                if base_height is None:
                    reason = "参考载荷点高度未确定或存在循环依赖"
                else:
                    value, formula = base_height - distance, "H = H参考点 - ΔS"
                    inputs.update(base_point_id=base.get("load_point_id"), base_height_mm=base_height,
                                  base_inputs=deepcopy((base.get("height_relation") or {}).get("last_inputs")))
        inputs.update(dimension_mm=distance, kind=kind, reference_only=bool(relation.get("reference_only") or (inputs.get("base_inputs") or {}).get("reference_only")))
        if value is not None:
            value = round(value, 12)
            if not math.isfinite(value) or value <= 0 or kind != "absolute_height" and free_height is not None and free_height > 0 and value > free_height:
                value, reason = None, "换算工作高度须为正数且不能超过自由高度"
        changed = point.get("height") != value or point.get("height_unit") != "mm" or relation.get("last_inputs") != inputs
        point.update(height=value, height_unit="mm")
        relation.update(status="calculated" if value is not None else "pending", reason=reason, formula=formula, last_inputs=inputs)
        if changed:
            point["need_human_review"] = True
            confirmations = review.get("manual_confirmations") or {}
            confirmations.pop(f"load_point_{point.get('load_point_id')}", None)
            for index, candidate in enumerate(points):
                if candidate is point:
                    confirmations.pop(f"load_points_{index}", None)
            changes.append({"load_point_id": point.get("load_point_id"), "before": before, "after": deepcopy(point)})
        visiting.remove(key)
        visited[key] = value
        return value

    for point in points:
        if isinstance(point, dict):
            resolve(point)
    # This check never changes values or confirmation, and never reconstructs a chain.
    for point in points:
        relation = point.get("height_relation") or {}
        base = by_id.get(relation.get("base_point_id"))
        if base and relation.get("status") == "calculated":
            delta = millimeters(relation.get("value"), relation.get("unit"))
            a, b = number(base.get("force")), number(point.get("force"))
            if delta and a is not None and b is not None and base.get("force_unit") == point.get("force_unit") == "N":
                rate=round((b-a)/delta, 8)
                point["height_relation"]["secant_rate"] = rate
                warning="行程增加但载荷未增加，请核对" if rate<=0 else ""
                declared=parameters.get("spring_rate") or {}
                original_sources=declared.get("source") or []
                original_sources=[original_sources] if isinstance(original_sources,str) else original_sources
                k,up,down=(number(declared.get(f)) for f in ("value","tolerance_upper","tolerance_lower"))
                independent=not any("formula" in str(s) or "derived" in str(s) for s in original_sources)
                if independent and declared.get("unit")=="N/mm" and k is not None and up is not None and down is not None and not k+down-1e-9<=rate<=k+up+1e-9:
                    warning="尺寸链换算刚度与原图刚度公差不一致，请核对"
                if warning:point["height_relation"]["check_warning"]=warning
                else:point["height_relation"].pop("check_warning",None)
    return changes


def prepare_load_height_save(review: dict[str, Any], previous: dict[str, Any]) -> list[dict[str, Any]]:
    """Client edits cannot certify an original dimension or replace another point's evidence."""
    old_points = {p.get("load_point_id"): p for p in (previous.get("spring_parameters") or {}).get("load_points", [])}
    expected = deepcopy(review)
    for p in expected.get("spring_parameters", {}).get("load_points", []):
        old = old_points.get(p.get("load_point_id"))
        if old and old.get("height_relation"):
            p["height_relation"] = deepcopy(old["height_relation"])
    refresh_load_heights(expected)
    calculated = {p.get("load_point_id"): p for p in expected.get("spring_parameters", {}).get("load_points", [])}
    for p in review.get("spring_parameters", {}).get("load_points", []):
        old = old_points.get(p.get("load_point_id"))
        if not old or not old.get("height_relation"):
            if p.get("height_relation"):
                p["height_relation"] = normalize_relation(p["height_relation"])
                mark_manual_height(p)
            continue
        manual = (p.get("height_relation") or {}).get("mode") == "manual"
        changed = p.get("height") != old.get("height") or p.get("height_unit") != old.get("height_unit")
        matches_calculation = p.get("height") == calculated[p["load_point_id"]].get("height") and p.get("height_unit") == "mm"
        p["height_relation"] = deepcopy(old["height_relation"])
        if manual or changed and not matches_calculation:
            mark_manual_height(p)
    return refresh_load_heights(review)
