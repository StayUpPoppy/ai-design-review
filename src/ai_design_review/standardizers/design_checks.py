"""Nominal geometry and read-only design results for round compression springs."""
from __future__ import annotations

import copy
import math
import re
from typing import Any

from ..end_conditions import normalize_end_grinding, normalize_end_type
from ..material_catalog import load_material_catalog, match_material_catalog
from .stiffness import spring_rate_from_geometry
from .coil_counts import apply_company_simple_active_coils
from .coil_counts import derive_active_coils
from .compression import calculate_compression_solid_height
from .calculation_state import solid_height_kind, preserve_candidate

VERSION = "compression-design-v2"
PITCH_FIELDS = ["free_length", "wire_diameter", "active_coils", "total_coils", "support_coils", "end_type", "end_grinding", "pitch_type"]
SUPPORT_FIELDS = ["total_coils", "active_coils", "end_type"]
LENGTH_UNITS = {"mm": 1, "毫米": 1, "cm": 10, "m": 1000, "in": 25.4, "inch": 25.4, "英寸": 25.4}
FORCE_UNITS = {"n": 1, "牛": 1, "kn": 1000, "kgf": 9.80665}


def _raw(item: Any) -> Any:
    return item.get("value") if isinstance(item, dict) else item


def _empty(value: Any) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or _empty(value):
        return None
    if isinstance(value, str) and not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value.strip()):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe(calculate: Any) -> float | None:
    try:
        return _number(calculate())
    except (ArithmeticError, ValueError):
        return None


def _sources(item: dict[str, Any]) -> list[str]:
    value = item.get("source") or []
    return [str(v).lower() for v in (value if isinstance(value, list) else [value])]


def _human_override(item: dict[str, Any]) -> bool:
    return bool(item.get("human_modified")) or any(
        s.startswith("human") and s != "human_confirmed" or s in {"manual", "manual_input", "standardization_chat", "ai_chat"}
        for s in _sources(item)
    )


def _fresh(parameters: dict[str, Any], field: str, path: tuple[str, ...] = ()) -> bool:
    if field in path:
        return False
    item = parameters.get(field)
    if not isinstance(item, dict):
        return True
    if item.get("derived_value_stale") or item.get("formula_recommendation_stale") and not _human_override(item):
        return False
    if any(s in {"formula_calculation", "derived"} for s in _sources(item)) and not _human_override(item):
        for source in item.get("source_fields") or []:
            if source == "pitch_type":
                continue
            parent = parameters.get(source)
            if field != "pitch" and (source not in parameters or _empty(_raw(parent))):
                return False
            if field != "pitch" and source in {"wire_diameter", "mean_diameter", "outer_diameter", "inner_diameter", "free_length", "active_coils", "total_coils", "support_coils"}:
                number = _number(_raw(parent))
                if number is None or number <= 0:
                    return False
                unit = str(parent.get("unit") or ("turns" if "coils" in source else "mm")).lower() if isinstance(parent, dict) else ("turns" if "coils" in source else "mm")
                if unit.strip() not in ({"turns", "turn", "圈"} if "coils" in source else LENGTH_UNITS):
                    return False
            if not _fresh(parameters, source, (*path, field)):
                return False
        return True
    return True


def _input(parameters: dict[str, Any], field: str, notes: dict[str, str], *, length: bool = False) -> float | None:
    item = parameters.get(field)
    if not _fresh(parameters, field):
        notes[field] = f"{field} 的推导值已失效或存在循环依赖"
        return None
    value = _number(_raw(item))
    if value is None or value <= 0:
        notes[field] = f"待补充 {field}" if _empty(_raw(item)) else f"{field} 必须为有限正数"
        return None
    unit = str(item.get("unit") or ("mm" if length else "turns")).strip().lower() if isinstance(item, dict) else ("mm" if length else "turns")
    factor = LENGTH_UNITS.get(unit) if length else (1 if unit in {"turns", "turn", "圈", ""} else None)
    if factor is None:
        notes[field] = f"{field} 不支持单位 {unit}"
        return None
    value *= factor
    if not math.isfinite(value):
        notes[field] = f"{field} 超出计算范围"
        return None
    return value


def _context(parameters: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    notes: dict[str, str] = {}
    fields = {f: _input(parameters, f, notes, length=f not in {"active_coils", "total_coils", "support_coils"})
              for f in ("wire_diameter", "mean_diameter", "outer_diameter", "inner_diameter", "free_length", "active_coils", "total_coils", "support_coils", "pitch")}
    # Only an absent mean diameter permits an alternative geometry source.
    if fields["mean_diameter"] is None and _empty(_raw(parameters.get("mean_diameter"))) and _fresh(parameters, "mean_diameter"):
        d, outer, inner = (fields[f] for f in ("wire_diameter", "outer_diameter", "inner_diameter"))
        mean = _safe(lambda: outer / 2 + inner / 2) if outer is not None and inner is not None else _safe(lambda: outer - d) if outer is not None and d is not None else _safe(lambda: inner + d) if inner is not None and d is not None else None
        if mean is not None and mean > 0:
            fields["mean_diameter"] = mean
            notes.pop("mean_diameter", None)
    end_type = normalize_end_type(_raw(parameters.get("end_type")))
    end_grinding = normalize_end_grinding(_raw(parameters.get("end_grinding")))
    if fields["active_coils"] is None and _empty(_raw(parameters.get("active_coils"))) and _fresh(parameters, "active_coils"):
        active = (derive_active_coils("compression_spring", parameters).get("active_coils") or {}).get("value") if not _human_override(parameters.get("active_coils") or {}) else None
        if active is not None and active > 0:
            fields["active_coils"] = active
            notes.pop("active_coils", None)
    reason = ""
    for field, allowed in {"spring_family": {"helical"}, "spring_shape": {"cylindrical"}, "wire_section": {"round", "circular"}, "pitch_type": {"constant"}}.items():
        value = str(_raw(features.get(field)) or "unknown").lower()
        if value not in allowed | {"unknown", ""}:
            reason = f"普通圆丝圆柱等节距模型不适用于 {field}={value}"
            break
    return {**fields, "notes": notes, "end_type": end_type, "end_grinding": end_grinding, "incompatible": reason,
            "pitch_type": _raw(features.get("pitch_type")) or "unknown"}


def _result(value: float | None, unit: str, formula: str, fields: list[str], context: dict[str, Any], *, basis: str = "理论计算", reason: str = "", estimated: bool = False) -> dict[str, Any]:
    if value is not None and not math.isfinite(value):
        value, reason = None, "数值超出计算范围"
    return {"value": value, "unit": unit, "formula": formula, "status": ("estimated" if estimated else "calculated") if value is not None else "missing_context",
            "reason": reason or (("；".join(dict.fromkeys(context["notes"].get(f, f"待补充 {f}") for f in fields if context.get(f) is None)) or "计算输入失效或超出数值范围") if value is None else ""),
            "basis": basis, "source_fields": fields, "inputs": {f: context.get(f) for f in fields}}


def _independent_coil_source(parameters: dict[str, Any], field: str, path: tuple[str, ...] = ()) -> bool:
    """Do not reverse a company default or a count already derived from support."""
    if field in path:
        return False
    item = parameters.get(field)
    if not isinstance(item, dict) or _human_override(item):
        return True
    sources = _sources(item)
    if "company_active_coil_rule" in sources:
        return False
    if "solidworks_protocol_default" in sources and item.get("need_human_review") is not False:
        return False
    parents = item.get("source_fields") or []
    if any(s in {"formula_calculation", "derived", "parameter_change_proposal_derived"} for s in sources) and not parents:
        return False
    return all(source not in {"support_coils", "total_coils", "active_coils"} and _independent_coil_source(parameters, source, (*path, field)) for source in parents)


def calculate_support_coils(parameters: dict[str, Any]) -> dict[str, Any]:
    notes: dict[str, str] = {}
    total = _input(parameters, "total_coils", notes)
    active = _input(parameters, "active_coils", notes)
    end = normalize_end_type(_raw(parameters.get("end_type")))
    value, reason = None, ""
    if end != "两端并紧":
        reason = "需明确两端并紧结构，才能由圈数推导单端支承圈数"
    elif not all(_independent_coil_source(parameters, f) for f in ("total_coils", "active_coils")):
        reason = "需要独立的总圈数和有效圈数；不能反推公司默认值或形成循环依赖"
    elif total is not None and active is not None:
        value = (total - active) / 2
        if value <= 0:
            value, reason = None, "总圈数必须大于有效圈数，请核对圈数"
    c = {"total_coils": total, "active_coils": active, "end_type": end, "notes": notes}
    return _result(value, "turns", "单端支承圈数 = (n1 - n) / 2", SUPPORT_FIELDS, c, reason=reason, basis="由独立总圈数和有效圈数推导；待人工确认")


def apply_formula_support_coils(review: dict[str, Any]) -> None:
    parameters = review.get("spring_parameters") or {}
    old = parameters.get("support_coils")
    item = old if isinstance(old, dict) else {"value": old}
    formula = item.get("formula_calculation_kind") == "support_coils"
    calculated = calculate_support_coils(parameters)
    if _human_override(item):
        if formula:
            item.pop("derived_value_stale", None)
            item.pop("formula_recommendation_stale", None)
        return
    if formula and item.get("need_human_review") is False:
        preserve_candidate(item, calculated)
        return
    if item.get("need_human_review") is False or not formula and not _empty(item.get("value")):
        return
    if calculated["value"] is None and not formula:
        return
    target = old if isinstance(old, dict) else parameters.setdefault("support_coils", {})
    if not isinstance(target, dict):
        target = parameters["support_coils"] = {}
    value = round(calculated["value"], 4) if calculated["value"] is not None else None
    target.update({"field": "support_coils", "value": value, "unit": "turns", "source": ["formula_calculation"], "need_human_review": True,
                   "confidence": 0.88, "formula": calculated["formula"], "evidence": calculated["basis"], "source_fields": SUPPORT_FIELDS,
                   "formula_calculation_kind": "support_coils", "formula_calculation_status": calculated["status"],
                   "formula_calculation_inputs": calculated["inputs"], "formula_calculation_reason": calculated["reason"],
                   "derived_value_stale": value is None, "formula_recommendation_stale": False})


def _geometry(c: dict[str, Any]) -> dict[str, Any]:
    """Choose a complete end model independently of an available pitch value."""
    a = None
    support = c["support_coils"]
    if support is not None:
        options = [(1.5, 1), (2, 1.5), (2.5, 2)] if c["end_grinding"] == "两端磨削" else [(2, 3), (2.5, 3.5)] if c["end_grinding"] == "两端不磨削" else []
        a = next((offset for count, offset in options if math.isclose(2 * support, count, abs_tol=1e-9, rel_tol=0)), None)
    reason = c["incompatible"]
    end, grinding, total, n = (c[f] for f in ("end_type", "end_grinding", "total_coils", "active_coils"))
    model = "book_table" if end == "两端并紧" else "open_end" if end == "两端不并紧" else "unknown"
    if not reason and (model == "unknown" or grinding is None):
        reason = "需明确端部形式与端面磨削方式"
    if not reason and model == "book_table":
        if a is None:
            reason = "需明确端面磨削方式与单端支承圈数，并符合图片公式分档"
        elif n is not None and total is not None and not math.isclose(total, n + 2 * support, rel_tol=0, abs_tol=1e-4):
            reason = "总圈数、有效圈数与支承圈数不一致，请核对"
    if not reason and model == "open_end":
        if total is None or n is None:
            reason = (c["notes"].get("total_coils") if total is None else c["notes"].get("active_coils")) or "缺少有效圈数或总圈数"
        elif not math.isclose(n, total - (1 if grinding == "两端磨削" else 0), rel_tol=0, abs_tol=1e-4):
            reason = "有效圈数与不并紧端型关系不一致，请核对"
    fields = PITCH_FIELDS if model == "book_table" else ["free_length", "wire_diameter", "total_coils", "active_coils", "end_type", "end_grinding", "pitch_type"]
    solid_fields = ["wire_diameter", "active_coils", "support_coils", "end_type", "end_grinding"] if model == "book_table" else ["wire_diameter", "total_coils", "active_coils", "end_type", "end_grinding"]
    pitch_formula = "t = (H0 - a*d) / n" if model == "book_table" else "t = H0 / n1" if grinding == "两端磨削" else "t = (H0 - d) / n1"
    solid_formula = "Hb = d*(n+a)" if model == "book_table" else "Hb = n1*d" if grinding == "两端磨削" else "Hb = (n1+1)*d"
    return {"a": a, "model_id": model, "reason": reason or "", "pitch_fields": fields, "solid_fields": solid_fields, "pitch_formula": pitch_formula, "solid_formula": solid_formula}


def calculate_pitch(parameters: dict[str, Any], features: dict[str, Any] | None = None) -> dict[str, Any]:
    c = _context(parameters, features or {})
    geometry = _geometry(c)
    value, reason = None, geometry["reason"]
    h, d, n, total = (c[f] for f in ("free_length", "wire_diameter", "active_coils", "total_coils"))
    if not reason and h is not None and d is not None:
        if geometry["model_id"] == "book_table" and n is not None:
            value = _safe(lambda: (h - geometry["a"] * d) / n)
        elif geometry["model_id"] == "open_end" and total is not None:
            value = _safe(lambda: (h - (0 if c["end_grinding"] == "两端磨削" else d)) / total)
    if value is not None:
        if not math.isfinite(value) or value <= d:
            value, reason = None, "推算节距必须大于线径，请核对自由高度、圈数与端部结构"
    result = _result(value, "mm", geometry["pitch_formula"], geometry["pitch_fields"], c, reason=reason)
    result["inputs"] = {f: c.get(f) for f in geometry["pitch_fields"]}
    result["inputs"].update(a=geometry["a"] if geometry["model_id"] == "book_table" else None, model_version=VERSION)
    result["model_id"] = geometry["model_id"]
    result["basis"] = "书页公式补算；支承圈数按两端合计；待人工确认" if geometry["model_id"] == "book_table" else "不并紧补充公式；Victory Spring 表7.1；待人工确认"
    return result


def calculate_nominal_solid_height(parameters: dict[str, Any], features: dict[str, Any] | None = None) -> dict[str, Any]:
    c = _context(parameters, features or {})
    geometry = _geometry(c)
    d, n, total = (c[f] for f in ("wire_diameter", "active_coils", "total_coils"))
    value = None
    if not geometry["reason"] and d is not None:
        if geometry["model_id"] == "book_table" and n is not None:
            value = _safe(lambda: d * (n + geometry["a"]))
        elif geometry["model_id"] == "open_end" and total is not None:
            value = _safe(lambda: d * (total + (0 if c["end_grinding"] == "两端磨削" else 1)))
    result = _result(value, "mm", geometry["solid_formula"], geometry["solid_fields"], c,
                     reason=geometry["reason"], estimated=True,
                     basis="名义估算；书页公式" if geometry["model_id"] == "book_table" else "名义估算；不并紧补充公式；Victory Spring 表7.1")
    result["inputs"].update(a=geometry["a"] if geometry["model_id"] == "book_table" else None)
    result.update(model_id=geometry["model_id"], height_source="book_nominal" if geometry["model_id"] == "book_table" else "open_nominal")
    return result


def apply_formula_nominal_solid_height(review: dict[str, Any]) -> None:
    parameters = review.get("spring_parameters") or {}
    old = parameters.get("solid_height")
    kind = solid_height_kind(old)
    if kind in {"input_height", "unknown"}:
        return
    calculation = calculate_nominal_solid_height(parameters, review.get("spring_features") or {})
    if kind == "nominal_estimate" and old.get("need_human_review") is False:
        preserve_candidate(old, calculation)
        return
    target = old if isinstance(old, dict) else {}
    # The old upper-limit confirmation must never confirm a different nominal value.
    if kind == "reference_limit":
        legacy = copy.deepcopy(target)
        confirmation = (review.get("manual_confirmations") or {}).pop("solid_height", None)
        if confirmation is not None:
            legacy["manual_confirmation"] = confirmation
        target.clear()
        target["legacy_reference_limit"] = legacy
    value = round(calculation["value"], 4) if calculation["value"] is not None else None
    target.update(field="solid_height", value=value, unit="mm", tolerance_upper=None, tolerance_lower=None,
                  source=["formula_calculation"], value_kind="nominal_estimate", need_human_review=True,
                  confidence=0.88, formula=calculation["formula"], evidence=calculation["basis"],
                  source_fields=calculation["source_fields"], formula_calculation_kind="nominal_solid_height",
                  formula_calculation_status="calculated" if value is not None else calculation["status"], formula_calculation_inputs=calculation["inputs"],
                  formula_calculation_reason=calculation["reason"], derived_value_stale=value is None,
                  formula_recommendation_stale=False)
    target.pop("formula_recalculation_candidate", None)
    parameters["solid_height"] = target


def apply_formula_pitch(review: dict[str, Any]) -> None:
    parameters = review.get("spring_parameters") or {}
    old = parameters.get("pitch")
    item = old if isinstance(old, dict) else {"value": old}
    formula = item.get("formula_calculation_kind") == "pitch"
    calculated = calculate_pitch(parameters, review.get("spring_features") or {})
    if _human_override(item):
        if formula:
            item.pop("derived_value_stale", None)
            item.pop("formula_recommendation_stale", None)
        return
    if formula and item.get("need_human_review") is False:
        preserve_candidate(item, calculated)
        return
    if item.get("need_human_review") is False or not formula and not _empty(item.get("value")):
        return
    if calculated["value"] is None and not formula:
        return
    if isinstance(old, dict):
        target = old
    else:
        target = {}
        parameters["pitch"] = target
    value = round(calculated["value"], 4) if calculated["value"] is not None else None
    target.update({"field": "pitch", "value": value, "unit": "mm", "source": ["formula_calculation"], "need_human_review": True,
                   "confidence": 0.88, "formula": calculated["formula"], "evidence": calculated["basis"], "source_fields": calculated["source_fields"],
                   "formula_calculation_kind": "pitch", "formula_calculation_status": calculated["status"],
                   "formula_calculation_inputs": calculated["inputs"], "formula_calculation_reason": calculated["reason"],
                   "derived_value_stale": value is None, "formula_recommendation_stale": False})
    target.pop("formula_recalculation_candidate", None)


def calculate_design_checks(parameters: dict[str, Any], features: dict[str, Any] | None = None) -> dict[str, Any]:
    c = _context(parameters, features or {})
    profile = match_material_catalog(_raw(parameters.get("material")))
    c["material"] = _raw(parameters.get("material")) if profile else None
    c["G"] = profile["shear_modulus_mpa"] if profile else None
    c["rho"] = profile.get("density_g_cm3") if profile else None
    c["notes"]["material"] = "请选择已配置的材料"
    d, mean, h, n, total, pitch = (c[f] for f in ("wire_diameter", "mean_diameter", "free_length", "active_coils", "total_coils", "pitch"))
    index = _safe(lambda: mean / d) if mean is not None and d is not None else None
    b = _safe(lambda: h / mean) if h is not None and mean is not None else None
    K = _safe(lambda: (4 * index - 1) / (4 * index - 4) + 0.615 / index) if index is not None and index > 1 else None
    rate = spring_rate_from_geometry(c["G"], d, mean, n)
    alpha = math.atan2(pitch, math.pi * mean) if pitch is not None and mean is not None else None
    length = _safe(lambda: math.pi * mean * total / math.cos(alpha)) if alpha is not None and total is not None else None
    mass = _safe(lambda: math.pi * d**2 / 4 * length * c["rho"] * 1e-6) if d is not None and length is not None and c["rho"] is not None else None
    pc = calculate_pitch(parameters, features)
    geometry = _geometry(c)
    nominal_result = calculate_nominal_solid_height(parameters, features)
    nominal = nominal_result["value"]
    reference = calculate_compression_solid_height(parameters)
    reference_result = _result(reference["value"], "mm", reference["formula"].replace(" = ", " ≤ "), reference["source_fields"], c,
                               reason=reference["reason"], basis=reference["basis"])
    reference_result["inputs"] = reference["inputs"]
    reference_result.update(model_id="gbt_1239_2_limit", height_source="reference_limit")
    hb_item = parameters.get("solid_height")
    kind = solid_height_kind(hb_item)
    hb = None
    hb_reason = ""
    height_source = "unknown"
    if kind in {"reference_limit", "missing"}:
        hb, hb_reason, height_source = nominal, nominal_result["reason"], nominal_result["height_source"]
    elif kind == "nominal_estimate":
        hb = _input(parameters, "solid_height", c["notes"], length=True)
        if hb is not None:
            hb = nominal
        height_source = nominal_result["height_source"]
        if hb is None:
            hb_reason = c["notes"].get("solid_height") or nominal_result["reason"] or "名义压并高度无效，请核对"
    elif kind == "input_height":
        hb = _input(parameters, "solid_height", c["notes"], length=True)
        height_source = "manual" if _human_override(hb_item or {}) else "drawing"
        if hb is None:
            hb_reason = "人工主动清空压并高度，未自动替换" if _empty(_raw(hb_item)) else c["notes"].get("solid_height", "压并高度无效")
    else:
        hb_reason = "压并高度用途无法确认，请核对来源"
    if hb is not None and h is not None and (hb <= 0 or hb >= h):
        hb, hb_reason = None, "估算压并高度必须满足 0 < Hb < H0，请核对"
    c["solid_height"] = hb
    height_basis = {"manual": "人工输入高度", "drawing": "图纸标注高度", "book_nominal": "书页名义高度", "open_nominal": "不并紧名义高度", "unknown": "高度来源待核对"}[height_source]
    metrics = {
        "spring_index": _result(index, "", "C = Dm / d", ["mean_diameter", "wire_diameter"], c),
        "slenderness_ratio": _result(b, "", "b = H0 / Dm", ["free_length", "mean_diameter"], c),
        "curvature_factor": _result(K, "", "K = (4C-1)/(4C-4) + 0.615/C", ["mean_diameter", "wire_diameter"], c, reason="旋绕比必须大于 1" if index is not None and index <= 1 else ""),
        "helix_angle": _result(math.degrees(alpha) if alpha is not None else None, "°", "α = atan(t / (π*Dm))", ["pitch", "mean_diameter"], c),
        "wire_length": _result(length, "mm", "L ≈ π*Dm*n1 / cos(α)", ["pitch", "mean_diameter", "total_coils"], c, estimated=True, basis="展开长度近似值"),
        "theoretical_spring_rate": _result(rate, "N/mm", "P′ = G*d^4 / (8*Dm^3*n)", ["material", "wire_diameter", "mean_diameter", "active_coils"], c),
        "unit_mass": _result(mass, "kg", "Q ≈ π*d²*L*ρ/4 × 10⁻⁶", ["material", "wire_diameter", "mean_diameter", "total_coils", "pitch"], c, estimated=True, basis="单件重量估算"),
        "nominal_solid_height": nominal_result,
        "reference_solid_height_limit": reference_result,
        "solid_height_used": _result(hb, "mm", "用于 Pb = P′*(H0-Hb)", ["solid_height"], c, reason=hb_reason, estimated=height_source.endswith("nominal"), basis=height_basis),
    }
    metrics["solid_height_used"].update(height_source=height_source, model_id=geometry["model_id"] if height_source.endswith("nominal") else "input_height")
    points = parameters.get("load_points") or []
    solid_points = [point for point in points if _is_solid_point(point)]
    def stress(point: dict[str, Any], *, solid: bool = False) -> dict[str, Any]:
        force = None
        estimated = False
        reason = ""
        if not _empty(point.get("force")):
            force = _number(point.get("force"))
            unit = str(point.get("force_unit") or "N").lower().strip()
            factor = FORCE_UNITS.get(unit)
            if force is None or force < 0:
                force, reason = None, "力值必须为有限非负数"
            elif factor is None:
                force, reason = None, f"不支持力值单位 {unit}"
            else:
                force *= factor
        else:
            estimated = True
            height = hb if solid else _input({"height": {"value": point.get("height"), "unit": point.get("height_unit") or "mm"}}, "height", c["notes"], length=True)
            if height is None:
                reason = (hb_reason or "缺少可用压并高度") if solid else c["notes"].get("height", "缺少有效高度")
            elif h is not None and (height > h or hb is not None and height < hb or solid and height >= h):
                reason = "高度超出有效压缩范围，请核对"
            elif rate is not None and h is not None:
                force = rate * (h - height)
            else:
                reason = "缺少理论刚度或自由高度，无法估算力值"
        value = _safe(lambda: 8 * force * mean * K / (math.pi * d**3)) if force is not None and mean is not None and d is not None and K is not None else None
        if value is None and not reason:
            reason = metrics["curvature_factor"]["reason"] or "缺少中径、线径或可用曲度系数"
        result = _result(value, "MPa", "τ = 8*P*Dm*K / (π*d³)", ["mean_diameter", "wire_diameter", "load_points"], c, reason=reason,
                         estimated=estimated, basis="估算载荷；P=P′*(H0-H)" if estimated else "已有载荷")
        result.update({"force_n": force if force is not None and math.isfinite(force) else None, "load_point_id": point.get("load_point_id"), "label": point.get("label") or ""})
        result["inputs"].update({"force_n": result["force_n"], "curvature_factor": K, "free_length_mm": h,
                                "theoretical_spring_rate": rate if estimated else None, "solid_height_mm": hb if solid else None,
                                "test_height": point.get("height"), "test_height_unit": point.get("height_unit") or "mm"})
        if solid:
            result.update(height_source=height_source if estimated else None, model_id=geometry["model_id"] if estimated and height_source.endswith("nominal") else "input_height" if estimated else "provided_load")
            result["inputs"]["solid_height_mm"] = hb if estimated else None
            result["basis"] = "估算压并载荷；" + height_basis if estimated else "已有压并载荷"
        return result
    if len(solid_points) > 1:
        solid = _result(None, "MPa", "τb = 8*Pb*Dm*K / (π*d³)", [], c, reason="存在多个压并载荷点，请核对")
        solid["status"] = "ambiguous"
    else:
        solid = stress(solid_points[0] if solid_points else {}, solid=True)
        solid["formula"] = "τb = 8*Pb*Dm*K / (π*d³)"
    metrics["solid_stress"] = solid
    if len(solid_points) > 1 or solid_points and not _empty(solid_points[0].get("force")):
        metrics["solid_height_used"].update(value=None, status="not_required", reason="已有明确压并力值时不通过高度估算载荷" if len(solid_points) == 1 else "压并载荷点存在歧义")
    work = [stress(point) for point in points if not _is_solid_point(point)]
    if c["incompatible"]:
        for result in [*metrics.values(), *work]:
            if result not in (metrics["spring_index"], metrics["slenderness_ratio"]):
                result.update({"value": None, "status": "not_applicable", "reason": c["incompatible"]})
    return {"version": VERSION, "material_catalog_version": load_material_catalog()["version"], "material_properties": profile,
            "metrics": metrics, "work_stresses": work, "pitch_calculation": pc}


def _is_solid_point(point: dict[str, Any]) -> bool:
    label = str(point.get("label") or "").strip().lower().replace(" ", "").replace("_", "")
    return label in {"fb", "pb", "压并载荷", "压并负荷", "压并力"}


def refresh_design_checks(review: dict[str, Any]) -> None:
    if (review.get("drawing_summary") or {}).get("spring_type") != "compression_spring":
        review.pop("design_checks", None)
        return
    parameters = review.get("spring_parameters") or {}
    apply_company_simple_active_coils("compression_spring", parameters)
    apply_formula_support_coils(review)
    apply_formula_nominal_solid_height(review)
    apply_formula_pitch(review)
    review["design_checks"] = calculate_design_checks(review.get("spring_parameters") or {}, review.get("spring_features") or {})
