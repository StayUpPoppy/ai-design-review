"""Quote-oriented accuracy inference from independent drawing/manual inputs.

The input snapshot survives standardization writes.  Human confirmation alone
never turns a generated tolerance into independent drawing evidence.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re
import struct
from typing import Any

VERSION = "compression-accuracy/v1"
FIELDS = ("wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "active_coils", "total_coils", "support_coils", "end_type", "end_grinding", "spring_rate", "controlled_diameter_field", "diameter_accuracy_grade", "free_length_accuracy_grade", "load_accuracy_grade", "stiffness_accuracy_grade")
SPECIFIC = {"diameter": "diameter_accuracy_grade", "free_length": "free_length_accuracy_grade", "load": "load_accuracy_grade", "stiffness": "stiffness_accuracy_grade"}
LENGTH = {"mm": 1, "cm": 10, "m": 1000, "in": 25.4, "inch": 25.4, "毫米": 1}
FORCE = {"n": 1, "kn": 1000, "kgf": 9.80665}
GENERATED = {"standardization", "system_generated", "human_suggestion_applied"}
_UNSET = object()


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or isinstance(value, str) and not value.strip():
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def grade(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in (1, 2, 3):
        return f"{int(value)}级"
    match = re.fullmatch(r"\s*([123])\s*[级級]?\s*", str(value or ""))
    return f"{match[1]}级" if match else None


def _item(item: dict, *, load: bool = False) -> dict:
    sources = item.get("source") or []
    if isinstance(sources, str):
        sources = [sources]
    formula = any(s in {"formula_calculation", "company_active_coil_rule"} for s in sources)
    return {
        "value": item.get("force" if load else "value"),
        "unit": item.get("force_unit" if load else "unit") or ("N" if load else ""),
        "upper": item.get("load_tolerance_upper" if load else "tolerance_upper"),
        "lower": item.get("load_tolerance_lower" if load else "tolerance_lower"),
        "percent": (item.get("force_tolerance_percent") if item.get("force_tolerance_percent") is not None else item.get("load_tolerance_percent")) if load else None,
        "invalid": bool(item.get("tolerance_input_draft") or item.get("derived_value_stale")),
        "system_value": item.get("accuracy_value_source") == "system" or formula and item.get("accuracy_value_source") != "human",
        "system_tolerance": item.get("tolerance_source") in GENERATED or formula and item.get("tolerance_source") != "human",
    }


def capture(review: dict) -> dict:
    params = review.get("spring_parameters") or {}
    result = {field: _item(params.get(field) or {}) for field in FIELDS}
    for index, point in enumerate(params.get("load_points") or []):
        key = str(point.get("load_point_id") or point.get("label") or index)
        result[f"load:{key}"] = _item(point, load=True)
    return result


def _fingerprint(value: Any) -> str:
    def normalize(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return {"$number": struct.pack(">d", float(v) if v else 0.0).hex()}
        if isinstance(v, dict):
            return {k: normalize(x) for k, x in sorted(v.items())}
        if isinstance(v, list):
            return [normalize(x) for x in v]
        return v
    raw = json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":"))
    hashed = 2166136261
    encoded = raw.encode("utf-16-le")
    for i in range(0, len(encoded), 2):
        hashed = ((hashed ^ int.from_bytes(encoded[i:i + 2], "little")) * 16777619) & 0xffffffff
    return f"{hashed:08x}"


def _scaled(item: dict, kind: str) -> tuple[float | None, float | None]:
    unit = str(item.get("unit") or ("N" if kind == "load" else "N/mm" if kind == "stiffness" else "turns" if kind == "coils" else "mm")).strip().lower()
    factor = FORCE.get(unit) if kind == "load" else {"n/mm": 1, "n/cm": .1, "kn/m": 1, "n/m": .001}.get(unit) if kind == "stiffness" else 1 if kind == "coils" and unit in {"turns", "turn", "圈"} else LENGTH.get(unit)
    value = number(item.get("value"))
    if item.get("invalid") or factor is None or value is None or value <= 0:
        return None, None
    return value * factor, factor


def analyze(snapshot: dict, standard: str | None, geometry_driver: str | None = None) -> dict:
    from .standardizers.compression import CompressionSpringStandardizer, load_compression_rules
    rules = load_compression_rules()
    calculator = CompressionSpringStandardizer(rules)
    supported = bool(re.fullmatch(r"GB\s*/?\s*T\s*1239\.2(?:-2009)?", str(standard or ""), re.I))
    def value(field, kind="length"):
        return _scaled(snapshot.get(field) or {}, kind)[0]
    wire, mean = value("wire_diameter"), value("mean_diameter")
    if (snapshot.get("mean_diameter") or {}).get("system_value"):
        mean = None
    if mean is None and wire is not None:
        outer, inner = value("outer_diameter"), value("inner_diameter")
        mean = outer - wire if outer is not None else inner + wire if inner is not None else None
    geometry = None
    if geometry_driver in {"outer_diameter", "inner_diameter", "mean_diameter"}:
        anchor = value(geometry_driver)
        if anchor is None or wire is None:
            mean = None
        elif geometry_driver == "outer_diameter":
            mean = anchor - wire
        elif geometry_driver == "inner_diameter":
            mean = anchor + wire
        else:
            mean = anchor
        geometry = {"mean_diameter": mean, "outer_diameter": mean + wire if mean is not None else None, "inner_diameter": mean - wire if mean is not None else None}
    spring_index = round(mean / wire, 4) if mean is not None and mean > 0 and wire else None
    active = value("active_coils", "coils")
    if (snapshot.get("active_coils") or {}).get("system_value"):
        from .standardizers.coil_counts import derive_active_coils
        inputs = {f: {"value": p.get("value"), "unit": p.get("unit") or None, "derived_value_stale": p.get("invalid", False)} for f, p in snapshot.items() if not f.startswith("load:")}
        inputs.pop("active_coils", None)
        active = number((derive_active_coils("compression_spring", inputs).get("active_coils") or {}).get("value"))
    selected_diameter = (snapshot.get("controlled_diameter_field") or {}).get("value")
    diameter_fields = [selected_diameter] if selected_diameter in {"outer_diameter", "inner_diameter"} else ["outer_diameter", "inner_diameter"]
    targets = [(f, "diameter") for f in diameter_fields] + [("free_length", "free_length"), ("spring_rate", "stiffness")] + [(f, "load") for f in snapshot if f.startswith("load:")]
    results = []
    for field, kind in targets:
        item = snapshot.get(field) or {}
        upper, lower, percent = number(item.get("upper")), number(item.get("lower")), number(item.get("percent"))
        explicit = grade((snapshot.get(SPECIFIC[kind]) or {}).get("value"))
        if upper is None and lower is None and percent is None and not explicit and item.get("value") in (None, ""):
            continue
        nominal, factor = _scaled(item, "load" if kind == "load" else "stiffness" if kind == "stiffness" else "length")
        if kind == "diameter" and geometry is not None:
            nominal = geometry.get(field)
            factor = LENGTH.get(str(item.get("unit") or "mm").strip().lower())
            if factor is None:
                nominal = None
        result = {"field": field, "kind": kind, "grade": None, "status": "missing_context", "limits": {}, "stricter_than_first": False}
        if not supported:
            result["status"] = "not_applicable"
        elif explicit:
            result.update(grade=explicit, status="drawing_grade")
        elif item.get("system_tolerance"):
            result["status"] = "generated_tolerance"
        elif upper is None and lower is None and percent is None:
            result["status"] = "missing_tolerance"
        elif nominal is not None:
            if kind == "load" and upper is None and lower is None and percent is not None and percent >= 0:
                upper, lower = nominal * percent / 100, -nominal * percent / 100
            else:
                upper = upper * factor if upper is not None else None
                lower = lower * factor if lower is not None else None
            if upper is not None and lower is not None and lower <= upper:
                for g in ("1", "2", "3"):
                    if kind in {"diameter", "free_length"}:
                        band = calculator._band_rule(f"{kind}_tolerance", spring_index) if spring_index is not None else None
                        limit = calculator._factor_tolerance(band, g, nominal) if band else None
                    else:
                        ratio = calculator._active_coil_ratio("load_tolerance" if kind == "load" else "stiffness_tolerance", active, g) if active is not None else None
                        limit = round(nominal * ratio, 4) if ratio is not None else None
                    if limit is not None:
                        result["limits"][f"{g}级"] = limit
                        if result["grade"] is None and round(upper - limit, 9) <= 0 and round(lower + limit, 9) >= 0:
                            result.update(grade=f"{g}级", status="matched")
                if result["limits"] and result["grade"] is None:
                    result["status"] = "outside_grades"
                first = result["limits"].get("1级")
                result["stricter_than_first"] = bool(result["grade"] == "1级" and first is not None and upper < first and lower > -first)
            else:
                result["status"] = "invalid_tolerance"
        results.append(result)
    grades = [r["grade"] for r in results if r["grade"]]
    return {"results": results, "inferred_grade": min(grades) if grades else None, "complete": bool(results) and all(r["grade"] for r in results), "standard_no": standard}


def refresh_accuracy_inference(review: dict, *, initialize: bool = False, standard: Any = _UNSET, previous: dict | None = None) -> bool:
    if (review.get("drawing_summary") or {}).get("spring_type") != "compression_spring":
        return False
    params = review.setdefault("spring_parameters", {})
    current = capture(review)
    accuracy = params.setdefault("accuracy_grade", {"value": None, "need_human_review": True})
    meta = review.get("accuracy_inference")
    old_meta = (previous or {}).get("accuracy_inference")
    if not isinstance(meta, dict):
        if isinstance(old_meta, dict):
            meta = review["accuracy_inference"] = deepcopy(old_meta)
        else:
            explicit = grade(accuracy.get("value")) and accuracy.get("default_source") != "company_default" and "company_default" not in (accuracy.get("source") or [])
            mode = "drawing" if initialize and explicit else "auto" if initialize else "legacy"
            meta = review["accuracy_inference"] = {"selection_mode": mode, "input_snapshot": deepcopy(current), "observed_inputs": deepcopy(current)}
    if isinstance(old_meta, dict) and old_meta.get("selection_mode") in {"manual", "drawing", "legacy"} and meta.get("selection_mode") == "auto":
        meta["selection_mode"] = old_meta["selection_mode"]
        params["accuracy_grade"] = accuracy = deepcopy((previous.get("spring_parameters") or {}).get("accuracy_grade") or accuracy)
    if meta.get("selection_mode") == "auto" and "human_selected" in (accuracy.get("source") or []):
        meta["selection_mode"] = "manual"
    observed = meta.setdefault("observed_inputs", {})
    snapshot = meta.setdefault("input_snapshot", {})
    for field in set(snapshot) - set(current):
        snapshot.pop(field, None)
    for field, item in current.items():
        if item == observed.get(field):
            continue
        saved = snapshot.setdefault(field, deepcopy(item))
        if not item["system_value"]:
            for key in ("value", "unit", "invalid", "system_value"):
                saved[key] = item[key]
        if not item["system_tolerance"]:
            for key in ("upper", "lower", "percent", "invalid", "system_tolerance"):
                saved[key] = item[key]
    meta["observed_inputs"] = deepcopy(current)
    selection = review.get("standard_selection") or {}
    if selection.get("selected_standard"):
        meta["standard_selection_source"] = selection.get("selection_source") or "selected"
    if standard is _UNSET:
        standard = selection.get("selected_standard") or meta.get("standard_no") or (params.get("standard_no") or {}).get("value")
        if meta.get("standard_selection_source") == "wire_diameter_threshold" and not (params.get("standard_no") or {}).get("value"):
            wire_mm = _scaled(snapshot.get("wire_diameter") or {}, "length")[0]
            standard = "GB/T 1239.2-2009" if wire_mm is not None and wire_mm < 8 else "GB/T 23934-2015" if wire_mm is not None else None
    previous_inferred = meta.get("inferred_grade")
    geometry_driver = (review.get("diameter_linkage") or {}).get("driver_field")
    analysis = analyze(snapshot, standard, geometry_driver)
    fingerprint_input = {"snapshot": snapshot, "standard": standard, "version": VERSION}
    if geometry_driver:
        fingerprint_input["geometry_driver"] = geometry_driver
    meta.update(analysis, rules_version=VERSION, calculation_fingerprint=_fingerprint(fingerprint_input))
    if meta.get("selection_mode") != "auto":
        return False
    selected = analysis["inferred_grade"] or "2级"
    changed = grade(accuracy.get("value")) != selected or bool(previous_inferred and not analysis["inferred_grade"])
    if changed:
        confirmations = review.setdefault("manual_confirmations", {})
        for key, entry in confirmations.items():
            if key == "accuracy_grade" or entry.get("target_field") == "accuracy_grade":
                entry.update(confirmed=False, revoke_reason="accuracy_inference_changed")
        accuracy.pop("confirmation_snapshot", None)
        accuracy["need_human_review"] = True
        for result in review.get("standardization_results") or []:
            dependencies = (result.get("metadata") or {}).get("source_fields")
            if not dependencies or "accuracy_grade" in dependencies:
                result.update(status="stale", need_human_review=True)
    accuracy["value"] = selected
    if analysis["inferred_grade"]:
        accuracy.update(source=[s for s in accuracy.get("source", []) if s != "company_default"] + ["tolerance_inference"], evidence="根据独立公差按等级限值反推，整体报价取最严格等级。")
        accuracy["source"] = list(dict.fromkeys(accuracy["source"]))
        accuracy.pop("default_source", None)
        accuracy.pop("default_reason", None)
    elif accuracy.get("need_human_review") is not False:
        accuracy.update(default_source="company_default", default_reason="无可用独立公差反推，按公司默认二级精度生成标准化建议。", evidence="无可用独立公差反推，按公司默认二级精度生成标准化建议。")
        accuracy["source"] = [s for s in accuracy.get("source", []) if s != "tolerance_inference"]
        if "company_default" not in accuracy["source"]:
            accuracy["source"].append("company_default")
    return changed


def select_manual_accuracy(review: dict) -> None:
    refresh_accuracy_inference(review)
    if isinstance(review.get("accuracy_inference"), dict):
        review["accuracy_inference"]["selection_mode"] = "manual"


def mark_accuracy_input(review: dict, target: str, *, generated: bool, tolerance: bool = False) -> None:
    params = review.get("spring_parameters") or {}
    match = re.fullmatch(r"load_points\.([^.]+)\.(force|height)", target)
    item = next((p for p in params.get("load_points", []) if str(p.get("label")) == match[1]), None) if match else params.get(target)
    if not isinstance(item, dict):
        return
    item["tolerance_source" if tolerance else "accuracy_value_source"] = "system_generated" if generated and tolerance else "system" if generated else "human"
    if generated and not tolerance:
        item["tolerance_source"] = "system_generated"
    refresh_accuracy_inference(review)
