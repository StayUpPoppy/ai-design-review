"""Versioned hot-coiled limits shared by inference and suggestion generation."""
from functools import lru_cache
import re
from ..io_utils import project_path, read_json
from .calculation_state import number, LENGTH_UNITS

STANDARD = "GB/T 23934-2015"


@lru_cache(maxsize=1)
def rules():
    return read_json(project_path("config", "spring_standards", "gbt_23934_2015.json"))


def is_hot(standard):
    return bool(re.fullmatch(r"GB\s*/?\s*T\s*23934(?:[-—－](?:2014|2015))?", str(standard or ""), re.I))


def scope(context):
    r = rules()["scope"]
    missing = [f for f in ("wire_diameter", "mean_diameter", "free_length", "active_coils", "pitch") if context.get(f) is None]
    d, mean, h, n, pitch = (context.get(f) for f in ("wire_diameter", "mean_diameter", "free_length", "active_coils", "pitch"))
    checks = [((d is not None and not r["wire_min"] <= d <= r["wire_max"]), "线径超出8～60 mm"),
              ((mean is not None and not 0 < mean <= r["mean_max"]), "中径超出适用范围"),
              ((h is not None and not 0 < h <= r["height_max"]), "自由高度超出适用范围"),
              ((d is not None and d > 0 and mean is not None and not r["index_min"] <= mean/d <= r["index_max"]), "旋绕比超出3～12"),
              ((mean is not None and mean > 0 and h is not None and not r["slenderness_min"] <= h/mean <= r["slenderness_max"]), "高径比超出0.8～4"),
              ((n is not None and n < r["active_min"]), "有效圈数小于3"),
              ((pitch is not None and mean is not None and not 0 < pitch <= r["pitch_mean_ratio_max"]*mean), "节距超出适用范围")]
    violations = [reason for invalid, reason in checks if invalid]
    return {"status": "outside_scope" if violations else "missing_context" if missing else "applicable", "missing_fields": missing, "violations": violations}


def limit(kind, grade, context, nominal=None):
    r = rules()
    if grade not in r["accuracy_grades"] or scope(context)["status"] != "applicable":
        return None
    if kind == "diameter":
        band = next(b for b in r["diameter_tolerance"] if b["height_max"] is None or context["free_length"] <= b["height_max"])
        entry = band["grades"][grade]
        value = max(entry["factor"]*context["mean_diameter"], entry["minimum"])
    elif kind == "free_length":
        entry = r["free_length_tolerance"][grade]
        value = max(entry["factor"]*context["free_length"], entry["minimum"])
    elif kind == "load" and nominal is not None and nominal > 0 and context.get("spring_rate") is not None and context["spring_rate"] > 0:
        entry = r["load_tolerance"][grade]
        value = max(entry["factor"]*nominal, entry["minimum_deflection"]*context["spring_rate"])
    else:
        return None
    return round(value, 4)


def context_from_parameters(parameters):
    def value(field):
        p = parameters.get(field) or {}
        if not isinstance(p, dict) or p.get("derived_value_stale"):
            return None
        v = number(p.get("value"))
        unit = str(p.get("unit") or ("turns" if field == "active_coils" else "N/mm" if field == "spring_rate" else "mm")).lower()
        factor = {"n/mm": 1, "n/cm": .1, "kn/m": 1, "n/m": .001}.get(unit) if field == "spring_rate" else 1 if field == "active_coils" and unit in {"turns", "turn", "圈"} else LENGTH_UNITS.get(unit)
        return v*factor if v is not None and factor is not None and v > 0 else None
    c = {f: value(f) for f in ("wire_diameter", "mean_diameter", "free_length", "active_coils", "pitch", "spring_rate")}
    if c["mean_diameter"] is None and c["wire_diameter"] is not None:
        outer, inner = value("outer_diameter"), value("inner_diameter")
        c["mean_diameter"] = outer-c["wire_diameter"] if outer else inner+c["wire_diameter"] if inner else None
    return c


def standardize(parameters):
    from .compression import derive_compression_parameters, _symmetric_result, _result
    from ..accuracy_inference import grade
    context = context_from_parameters(parameters)
    applicability = scope(context)
    selected = str((parameters.get("controlled_diameter_field") or {}).get("value") or "")
    if selected not in {"inner_diameter", "outer_diameter"}:
        selected = next((f for f in ("inner_diameter", "outer_diameter") if (parameters.get(f) or {}).get("tolerance_upper") is not None), "outer_diameter")
    targets = [(selected, "diameter", parameters.get(selected) or {}, "diameter_accuracy_grade"),
               ("free_length", "free_length", parameters.get("free_length") or {}, "free_length_accuracy_grade")]
    targets += [(f"load_points.{p['label']}.force", "load", p, "load_accuracy_grade") for p in parameters.get("load_points") or [] if p.get("label")]
    results = []
    for target, kind, item, specific in targets:
        g = grade((parameters.get(specific) or {}).get("value")) or grade((parameters.get("accuracy_grade") or {}).get("value"))
        nominal = number(item.get("force" if kind == "load" else "value"))
        unit = str(item.get("force_unit" if kind == "load" else "unit") or ("N" if kind == "load" else "mm")).lower()
        factor = {"n": 1, "kn": 1000, "kgf": 9.80665}.get(unit) if kind == "load" else LENGTH_UNITS.get(unit)
        nominal = nominal*factor if nominal is not None and factor is not None else None
        tolerance = limit(kind, g[:-1] if g else None, context, nominal)
        height = number(item.get("height"))
        height_factor = LENGTH_UNITS.get(str(item.get("height_unit") or "mm").lower())
        if kind == "load" and (height is None or height_factor is None or not 0 < height*height_factor <= (context.get("free_length") or 0)):
            tolerance = None
        rule_id = "GBT23934-" + {"diameter": "DIA", "free_length": "FREE", "load": "LOAD"}[kind]
        deps = ["wire_diameter", "mean_diameter", "inner_diameter", "outer_diameter", "free_length", "pitch", "active_coils", "accuracy_grade", specific]
        if kind == "load": deps += ["spring_rate", "load_points"]
        metadata = {"source_fields": deps, "rules_version": rules()["version"], "source_document": rules()["source_document"], "applicability": applicability}
        basis = rules()["references"][kind]
        if tolerance is not None and nominal is not None and nominal > 0:
            result = _symmetric_result(target_field=target, rule_id=rule_id, standard_no=STANDARD, value=nominal, tolerance=tolerance, basis=f"{basis}，{g}，按版本规则计算。")
            result["unit"] = "N" if kind == "load" else "mm"
        else:
            reason = "；".join(applicability["violations"]) or "缺少有效计算依据或热卷精度等级"
            result = _result(target_field=target, rule_id=rule_id, standard_no=STANDARD, status="not_applicable" if applicability["status"] == "outside_scope" else "need_context", basis=reason, need_human_review=True)
            metadata["missing_fields"] = applicability["missing_fields"] + (["accuracy_grade"] if not g else []) + (["spring_rate"] if kind == "load" and context.get("spring_rate") is None else [])
        result.setdefault("metadata", {}).update(metadata)
        results.append(result)
    return {"derived_parameters": derive_compression_parameters(parameters), "standardization_results": results}
