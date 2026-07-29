from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from ..io_utils import project_path, read_json
from ..end_conditions import normalize_end_grinding
from .coil_counts import COMPANY_ACTIVE_COIL_RULE, derive_active_coils
from .diameters import apply_formula_compression_diameter_completion
from .stiffness import apply_formula_compression_spring_rate


STANDARD_PATH = project_path("config", "spring_standards", "gbt_1239_2_2009.json")
FORMULA_CALCULATION_SOURCE = "formula_calculation"
SOLID_HEIGHT_FORMULA_GROUND = "Hb = n1 * dmax"
SOLID_HEIGHT_FORMULA_NOT_GROUND = "Hb = (n1 + 1.5) * dmax"


def apply_formula_compression_solid_height(spring_parameters: dict[str, Any]) -> dict[str, Any]:
    """Populate a reference solid height only when the drawing has no manual value."""
    existing = spring_parameters.get("solid_height")
    result = calculate_compression_solid_height(spring_parameters)
    if not _can_replace_formula_solid_height(existing):
        return {**result, "applied": False, "preserved_existing_value": True}

    if result["status"] != "calculated":
        if isinstance(existing, dict):
            existing.update(
                {
                    "value": None,
                    "unit": "mm",
                    "source": [],
                    "evidence": "",
                    "suggested_region": "",
                    "formula_calculation_kind": "solid_height",
                    "formula_calculation_status": result["status"],
                    "formula_calculation_missing_fields": result["missing_fields"],
                    "formula_calculation_reason": result["reason"],
                }
            )
        return {**result, "applied": False}

    spring_parameters["solid_height"] = {
        "field": "solid_height",
        "value": result["value"],
        "unit": "mm",
        "tolerance_upper": None,
        "tolerance_lower": None,
        "source": [FORMULA_CALCULATION_SOURCE],
        "evidence": result["basis"],
        "confidence": 0.88,
        "page": 1,
        "position": None,
        "suggested_region": "formula_computed_solid_height",
        "need_human_review": True,
        "formula": result["formula"],
        "source_fields": result["source_fields"],
        "formula_calculation_kind": "solid_height",
        "formula_calculation_status": result["status"],
        "formula_calculation_inputs": result["inputs"],
    }
    return {**result, "applied": True}


def calculate_compression_solid_height(spring_parameters: dict[str, Any]) -> dict[str, Any]:
    """Calculate the GB/T 1239.2 reference solid height from drawing inputs."""
    total = _number(_param_value(spring_parameters, "total_coils"))
    wire = _number(_param_value(spring_parameters, "wire_diameter"))
    end_mode = solid_height_mode(_param_value(spring_parameters, "end_grinding"))

    missing_fields: list[str] = []
    if total is None or total <= 0:
        missing_fields.append("total_coils")
    if wire is None or wire <= 0:
        missing_fields.append("wire_diameter")
    if not end_mode:
        missing_fields.append("end_grinding")
    if missing_fields:
        return {
            "status": "missing_context",
            "value": None,
            "unit": "mm",
            "formula": "",
            "basis": "缺少总圈数、线径或端面磨削方式，无法计算压并高度参考值。",
            "missing_fields": missing_fields,
            "reason": "缺少压并高度公式输入：" + ", ".join(missing_fields),
            "source_fields": [],
            "inputs": {},
        }

    wire_item = spring_parameters.get("wire_diameter") or {}
    wire_upper = _number(wire_item.get("tolerance_upper")) if isinstance(wire_item, dict) else None
    max_wire = wire + max(0, wire_upper or 0)
    if end_mode == "ground":
        formula = SOLID_HEIGHT_FORMULA_GROUND
        value = total * max_wire
        basis = "端面磨削：压并高度参考 Hb = n1 * dmax。"
    else:
        formula = SOLID_HEIGHT_FORMULA_NOT_GROUND
        value = (total + 1.5) * max_wire
        basis = "两端不磨：压并高度参考 Hb = (n1 + 1.5) * dmax。"

    return {
        "status": "calculated",
        "value": _round(value),
        "unit": "mm",
        "formula": formula,
        "basis": f"{basis} n1={total:g}, dmax={max_wire:g} mm。",
        "missing_fields": [],
        "reason": "",
        "source_fields": ["total_coils", "wire_diameter", "end_grinding"],
        "inputs": {
            "total_coils": _round(total),
            "wire_diameter_mm": _round(wire),
            "wire_tolerance_upper_mm": _round(wire_upper or 0),
            "max_wire_diameter_mm": _round(max_wire),
            "end_mode": end_mode,
        },
    }


def standardize_compression_spring(
    spring_parameters: dict[str, Any],
    spring_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    apply_formula_compression_diameter_completion(spring_parameters)
    apply_formula_compression_solid_height(spring_parameters)
    apply_formula_compression_spring_rate(spring_parameters, spring_features)
    rules = load_compression_rules()
    derived = derive_compression_parameters(spring_parameters)
    results = CompressionSpringStandardizer(rules).standardize(spring_parameters, derived)
    return {
        "derived_parameters": derived,
        "standardization_results": results,
    }


def derive_compression_parameters(spring_parameters: dict[str, Any]) -> dict[str, Any]:
    wire = _number(_param_value(spring_parameters, "wire_diameter"))
    outer = _number(_param_value(spring_parameters, "outer_diameter"))
    inner = _number(_param_value(spring_parameters, "inner_diameter"))
    recognized_mean = _number(_param_value(spring_parameters, "mean_diameter"))
    free_length = _number(_param_value(spring_parameters, "free_length"))
    derived: dict[str, Any] = {}
    derived.update(derive_active_coils("compression_spring", spring_parameters))

    mean_diameter = recognized_mean
    source_fields: list[str] = ["mean_diameter"] if recognized_mean is not None else []
    formula = "drawing_or_manual_mean_diameter" if recognized_mean is not None else ""
    if recognized_mean is None and wire is not None and outer is not None:
        mean_diameter = outer - wire
        source_fields = ["outer_diameter", "wire_diameter"]
        formula = "outer_diameter - wire_diameter"
    elif recognized_mean is None and wire is not None and inner is not None:
        mean_diameter = inner + wire
        source_fields = ["inner_diameter", "wire_diameter"]
        formula = "inner_diameter + wire_diameter"

    if mean_diameter is not None and source_fields:
        derived["mean_diameter"] = _derived_param(
            "mean_diameter",
            _round(mean_diameter),
            "mm",
            formula,
            source_fields,
        )

    if mean_diameter is not None and wire not in (None, 0):
        derived["spring_index"] = _derived_param(
            "spring_index",
            _round(mean_diameter / wire),
            None,
            "mean_diameter / wire_diameter",
            ["mean_diameter", "wire_diameter"],
        )

    if free_length is not None and mean_diameter not in (None, 0):
        derived["slenderness_ratio"] = _derived_param(
            "slenderness_ratio",
            _round(free_length / mean_diameter),
            None,
            "free_length / mean_diameter",
            ["free_length", "mean_diameter"],
        )

    load_derivations = []
    for index, point in enumerate(spring_parameters.get("load_points", []) or [], start=1):
        height = _number(point.get("height"))
        if free_length is None or height is None:
            continue
        load_derivations.append(
            {
                "label": point.get("label") or f"F{index}",
                "height": height,
                "height_unit": point.get("height_unit", "mm"),
                "deflection": _round(free_length - height),
                "deflection_unit": "mm",
                "formula": "free_length - load_point.height",
                "source_fields": ["free_length", "load_points"],
            }
        )
    if load_derivations:
        derived["load_point_deflections"] = load_derivations

    return derived


class CompressionSpringStandardizer:
    def __init__(self, rules: dict[str, Any]):
        self.rules = rules
        self.standard_no = str(rules.get("standard_no") or "GB/T 1239.2-2009")

    def standardize(
        self,
        spring_parameters: dict[str, Any],
        derived_parameters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        results.append(self._standard_context_result(spring_parameters))
        results.append(self._diameter_result(spring_parameters, derived_parameters))
        results.append(self._free_length_result(spring_parameters, derived_parameters))
        results.append(self._total_coils_result(spring_parameters))
        results.append(self._perpendicularity_result(spring_parameters, derived_parameters))
        straightness = self._straightness_result(spring_parameters, derived_parameters)
        if straightness:
            results.append(straightness)
        results.append(self._solid_height_result(spring_parameters))
        results.extend(self._load_results(spring_parameters, derived_parameters))
        stiffness = self._stiffness_result(spring_parameters, derived_parameters)
        if stiffness:
            results.append(stiffness)
        permanent_set = self._permanent_set_result(spring_parameters)
        if permanent_set:
            results.append(permanent_set)
        return [item for item in results if item]

    def _standard_context_result(self, spring_parameters: dict[str, Any]) -> dict[str, Any]:
        value = _param_value(spring_parameters, "standard_no")
        status = "suggested" if value else "need_context"
        return _result(
            target_field="standard_no",
            rule_id="GBT1239.2-CTX",
            standard_no=self.standard_no,
            basis="压缩弹簧第一版仅接入 GB/T 1239.2-2009；未识别标准号时需人工确认。",
            status=status,
            suggested_value=value or self.standard_no,
            need_human_review=not bool(value),
            # A selected standard can still be used for calculation when it has not
            # yet been written back to the drawing parameter. Do not ask for it as
            # a blocking input in the conversational completion loop.
            metadata={"missing_fields": []},
        )

    def _diameter_result(self, spring_parameters: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any]:
        target_field = str(_param_value(spring_parameters, "controlled_diameter_field") or "").strip()
        if target_field not in {"outer_diameter", "inner_diameter"}:
            target_field = "outer_diameter" if _number(_param_value(spring_parameters, "outer_diameter")) is not None else "inner_diameter"
        value = _number(_param_value(spring_parameters, target_field))
        spring_index = _number(_param_value(derived, "spring_index"))
        grade = _grade(spring_parameters, "diameter_accuracy_grade")
        if value is None or spring_index is None:
            missing_fields = [target_field] if value is None else []
            missing_fields.extend(self._spring_index_missing_fields(spring_parameters, derived))
            return self._need_context(
                target_field,
                "GBT1239.2-DIA",
                "缺少受控直径或旋绕比，无法计算内径/外径标准公差。",
                missing_fields=missing_fields,
            )
        if not grade:
            return self._need_context(
                target_field,
                "GBT1239.2-DIA",
                "缺少直径精度等级，需人工选择 1/2/3 级。",
                value,
                missing_fields=["accuracy_grade"],
            )
        item = self._band_rule("diameter_tolerance", spring_index)
        if not item:
            return self._not_applicable(target_field, "GBT1239.2-DIA", f"旋绕比 C={spring_index:g} 超出 GB/T 1239.2 表 3-11 的 3~22 范围。", value)
        tol = self._factor_tolerance(item, grade, value)
        if tol is None:
            return self._need_context(
                target_field,
                "GBT1239.2-DIA",
                f"直径精度等级 {grade} 不在规则表中。",
                value,
                missing_fields=["accuracy_grade"],
            )
        return _symmetric_result(
            target_field=target_field,
            rule_id="GBT1239.2-DIA",
            standard_no=self.standard_no,
            value=value,
            tolerance=tol,
            basis=f"表3-11：C={spring_index:g}，{grade}级，±max({item['grades'][grade]['factor']}D, {item['grades'][grade]['minimum']}mm)。",
        )

    def _free_length_result(self, spring_parameters: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any]:
        value = _number(_param_value(spring_parameters, "free_length"))
        spring_index = _number(_param_value(derived, "spring_index"))
        grade = _grade(spring_parameters, "free_length_accuracy_grade")
        if value is None or spring_index is None:
            missing_fields = ["free_length"] if value is None else []
            missing_fields.extend(self._spring_index_missing_fields(spring_parameters, derived))
            return self._need_context(
                "free_length",
                "GBT1239.2-FREE",
                "缺少自由高度或旋绕比，无法计算自由高度标准公差。",
                missing_fields=missing_fields,
            )
        if not grade:
            return self._need_context(
                "free_length",
                "GBT1239.2-FREE",
                "缺少自由高度精度等级，需人工选择 1/2/3 级。",
                value,
                missing_fields=["accuracy_grade"],
            )
        item = self._band_rule("free_length_tolerance", spring_index)
        if not item:
            return self._not_applicable("free_length", "GBT1239.2-FREE", f"旋绕比 C={spring_index:g} 超出 GB/T 1239.2 表 3-12 的 3~22 范围。", value)
        tol = self._factor_tolerance(item, grade, value)
        if tol is None:
            return self._need_context(
                "free_length",
                "GBT1239.2-FREE",
                f"自由高度精度等级 {grade} 不在规则表中。",
                value,
                missing_fields=["accuracy_grade"],
            )
        return _symmetric_result(
            target_field="free_length",
            rule_id="GBT1239.2-FREE",
            standard_no=self.standard_no,
            value=value,
            tolerance=tol,
            basis=f"表3-12：C={spring_index:g}，{grade}级，±max({item['grades'][grade]['factor']}H0, {item['grades'][grade]['minimum']}mm)。",
        )

    def _total_coils_result(self, spring_parameters: dict[str, Any]) -> dict[str, Any]:
        value = _number(_param_value(spring_parameters, "total_coils"))
        if value is None:
            return self._need_context(
                "total_coils",
                "GBT1239.2-COILS",
                "缺少总圈数，无法给出总圈数极限偏差。",
                missing_fields=["total_coils"],
            )
        for item in self.rules.get("total_coils_tolerance", []):
            min_value = item.get("min")
            max_value = item.get("max")
            if (min_value is None or value > float(min_value)) and (max_value is None or value <= float(max_value)):
                tolerance = float(item["tolerance"])
                return _symmetric_result(
                    target_field="total_coils",
                    rule_id="GBT1239.2-COILS",
                    standard_no=self.standard_no,
                    value=value,
                    tolerance=tolerance,
                    basis=f"表3-13：总圈数 n1={value:g}，极限偏差 ±{tolerance:g} 圈；有特性要求时总圈数作为参考。",
                )
        return self._not_applicable("total_coils", "GBT1239.2-COILS", f"总圈数 n1={value:g} 超出规则表范围。", value)

    def _perpendicularity_result(self, spring_parameters: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any]:
        free_length = _number(_param_value(spring_parameters, "free_length"))
        grade = _grade(spring_parameters, "accuracy_grade")
        if free_length is None:
            return self._need_context(
                "perpendicularity",
                "GBT1239.2-PERP",
                "缺少自由高度，无法计算垂直度限值。",
                missing_fields=["free_length"],
            )
        if not grade:
            return self._need_context(
                "perpendicularity",
                "GBT1239.2-PERP",
                "缺少垂直度精度等级，需人工选择 1/2/3 级。",
                missing_fields=["accuracy_grade"],
            )
        item = (self.rules.get("perpendicularity") or {}).get(grade)
        if not item:
            return self._need_context(
                "perpendicularity",
                "GBT1239.2-PERP",
                f"垂直度精度等级 {grade} 不在规则表中。",
                missing_fields=["accuracy_grade"],
            )
        value = _round(float(item["factor"]) * free_length)
        slenderness = _number(_param_value(derived, "slenderness_ratio"))
        review = slenderness is not None and slenderness >= 5
        basis = f"表3-14：{grade}级垂直度 {item['factor']}H0，约 {item.get('angle_degree')}°。"
        if review:
            basis += " 细长比 b>=5，标准建议由供需双方协商，可改考核直线度。"
        return _result(
            target_field="perpendicularity",
            rule_id="GBT1239.2-PERP",
            standard_no=self.standard_no,
            basis=basis,
            status="suggested",
            suggested_value=value,
            suggested_tolerance_upper=value,
            suggested_tolerance_lower=0,
            unit="mm",
            need_human_review=review,
        )

    def _straightness_result(self, spring_parameters: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any] | None:
        slenderness = _number(_param_value(derived, "slenderness_ratio"))
        free_length = _number(_param_value(spring_parameters, "free_length"))
        grade = _grade(spring_parameters, "accuracy_grade")
        if slenderness is None or slenderness < 5 or free_length is None or not grade:
            return None
        item = (self.rules.get("perpendicularity") or {}).get(grade)
        if not item:
            return None
        perpendicularity = float(item["factor"]) * free_length
        value = _round(perpendicularity / 2)
        return _result(
            target_field="straightness",
            rule_id="GBT1239.2-STRAIGHT",
            standard_no=self.standard_no,
            basis=f"表3-14注：细长比 b={slenderness:g}>=5 时建议考核直线度，直线度为理论垂直度之半。",
            status="suggested",
            suggested_value=value,
            suggested_tolerance_upper=value,
            suggested_tolerance_lower=0,
            unit="mm",
            need_human_review=True,
        )

    def _solid_height_result(self, spring_parameters: dict[str, Any]) -> dict[str, Any]:
        calculation = calculate_compression_solid_height(spring_parameters)
        if calculation["status"] != "calculated":
            return self._need_context(
                "solid_height",
                "GBT1239.2-SOLID",
                calculation["basis"],
                missing_fields=calculation["missing_fields"],
            )
        return _result(
            target_field="solid_height",
            rule_id="GBT1239.2-SOLID",
            standard_no=self.standard_no,
            basis=calculation["basis"],
            status="suggested",
            suggested_value=calculation["value"],
            unit="mm",
        )

    def _load_results(self, spring_parameters: dict[str, Any], derived: dict[str, Any]) -> list[dict[str, Any]]:
        grade = _grade(spring_parameters, "load_accuracy_grade")
        active, active_source = _active_coils(spring_parameters, derived)
        active_note = _active_coil_note(active_source, derived)
        load_points = spring_parameters.get("load_points", []) or []
        if not load_points:
            return []
        if not grade or active is None:
            missing_fields = []
            if active is None:
                missing_fields.append("active_coils")
            if not grade:
                missing_fields.append("accuracy_grade")
            return [
                self._need_context(
                    "load_points",
                    "GBT1239.2-LOAD",
                    "缺少载荷精度等级或有效圈数，无法计算指定高度负荷极限偏差。",
                    missing_fields=missing_fields,
                )
            ]
        ratio = self._active_coil_ratio("load_tolerance", active, grade)
        if ratio is None:
            return [self._not_applicable("load_points", "GBT1239.2-LOAD", f"有效圈数 n={active:g} 不满足载荷公差规则。")]
        results = []
        deflections = {
            str(item.get("label")): item.get("deflection")
            for item in derived.get("load_point_deflections", [])
        }
        for index, point in enumerate(load_points, start=1):
            force = _number(point.get("force"))
            label = str(point.get("label") or f"F{index}")
            if force is None:
                continue
            tolerance = _round(force * ratio)
            results.append(
                _result(
                    target_field=f"load_points.{label}.force",
                    rule_id="GBT1239.2-LOAD",
                    standard_no=self.standard_no,
                    basis=f"表3-15：有效圈数 n={active:g}，{grade}级，指定高度负荷极限偏差 ±{ratio:g}F。{active_note}",
                    status="suggested",
                    suggested_value=force,
                    suggested_tolerance_upper=tolerance,
                    suggested_tolerance_lower=-tolerance,
                    unit=point.get("force_unit", "N"),
                    metadata={
                        "deflection": deflections.get(label),
                        "active_coils_source": active_source,
                    },
                )
            )
        return results

    def _stiffness_result(
        self,
        spring_parameters: dict[str, Any],
        derived: dict[str, Any],
    ) -> dict[str, Any] | None:
        stiffness = _number(_param_value(spring_parameters, "spring_rate"))
        if stiffness is None:
            return None
        active, active_source = _active_coils(spring_parameters, derived)
        active_note = _active_coil_note(active_source, derived)
        grade = _grade(spring_parameters, "stiffness_accuracy_grade")
        if not grade or active is None:
            missing_fields = []
            if active is None:
                missing_fields.append("active_coils")
            if not grade:
                missing_fields.append("accuracy_grade")
            return self._need_context(
                "spring_rate",
                "GBT1239.2-STIFF",
                "缺少刚度精度等级或有效圈数，无法计算刚度极限偏差。",
                stiffness,
                missing_fields=missing_fields,
            )
        ratio = self._active_coil_ratio("stiffness_tolerance", active, grade)
        if ratio is None:
            return self._not_applicable("spring_rate", "GBT1239.2-STIFF", f"有效圈数 n={active:g} 不满足刚度公差规则。", stiffness)
        tolerance = _round(stiffness * ratio)
        return _result(
            target_field="spring_rate",
            rule_id="GBT1239.2-STIFF",
            standard_no=self.standard_no,
            basis=f"表3-16：有效圈数 n={active:g}，{grade}级，刚度极限偏差 ±{ratio:g}F'。{active_note}",
            status="suggested",
            suggested_value=stiffness,
            suggested_tolerance_upper=tolerance,
            suggested_tolerance_lower=-tolerance,
            unit="N/mm",
            metadata={"active_coils_source": active_source},
        )

    def _permanent_set_result(self, spring_parameters: dict[str, Any]) -> dict[str, Any] | None:
        free_length = _number(_param_value(spring_parameters, "free_length"))
        if free_length is None:
            return None
        ratio = float((self.rules.get("permanent_set") or {}).get("max_free_length_ratio", 0.003))
        value = _round(free_length * ratio)
        return _result(
            target_field="permanent_set_limit",
            rule_id="GBT1239.2-PSET",
            standard_no=self.standard_no,
            basis=f"永久变形不得大于自由高度的 {ratio * 100:g}%。",
            status="suggested",
            suggested_value=value,
            suggested_tolerance_upper=value,
            suggested_tolerance_lower=0,
            unit="mm",
        )

    def _band_rule(self, key: str, spring_index: float) -> dict[str, Any] | None:
        for item in self.rules.get(key, []):
            lower = float(item["spring_index_min"])
            upper = float(item["spring_index_max"])
            lower_ok = spring_index >= lower if item.get("include_min") else spring_index > lower
            upper_ok = spring_index <= upper if item.get("include_max") else spring_index < upper
            if lower_ok and upper_ok:
                return item
        return None

    def _factor_tolerance(self, item: dict[str, Any], grade: str, base_value: float) -> float | None:
        grade_rule = (item.get("grades") or {}).get(grade)
        if not grade_rule:
            return None
        return _round(max(float(grade_rule["factor"]) * base_value, float(grade_rule["minimum"])))

    def _active_coil_ratio(self, key: str, active_coils: float, grade: str) -> float | None:
        table = self.rules.get(key) or {}
        if 3 <= active_coils <= 10:
            return _number((table.get("3_to_10") or {}).get(grade))
        if active_coils > 10:
            return _number((table.get("gt_10") or {}).get(grade))
        return None

    def _spring_index_missing_fields(
        self,
        spring_parameters: dict[str, Any],
        derived_parameters: dict[str, Any],
    ) -> list[str]:
        if _number(_param_value(derived_parameters, "spring_index")) is not None:
            return []
        missing_fields: list[str] = []
        if _number(_param_value(spring_parameters, "wire_diameter")) is None:
            missing_fields.append("wire_diameter")
        has_outer = _number(_param_value(spring_parameters, "outer_diameter")) is not None
        has_inner = _number(_param_value(spring_parameters, "inner_diameter")) is not None
        if not has_outer and not has_inner:
            missing_fields.append("outer_diameter")
        return missing_fields

    def _need_context(
        self,
        target_field: str,
        rule_id: str,
        basis: str,
        value: Any = None,
        *,
        missing_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        return _result(
            target_field=target_field,
            rule_id=rule_id,
            standard_no=self.standard_no,
            basis=basis,
            status="need_context",
            suggested_value=value,
            need_human_review=True,
            metadata={"missing_fields": list(dict.fromkeys(missing_fields or []))},
        )

    def _not_applicable(self, target_field: str, rule_id: str, basis: str, value: Any = None) -> dict[str, Any]:
        return _result(
            target_field=target_field,
            rule_id=rule_id,
            standard_no=self.standard_no,
            basis=basis,
            status="not_applicable",
            suggested_value=value,
            need_human_review=True,
        )


@lru_cache(maxsize=1)
def load_compression_rules(path: str | Path | None = None) -> dict[str, Any]:
    return read_json(Path(path) if path else STANDARD_PATH)


def _active_coils(
    spring_parameters: dict[str, Any],
    derived_parameters: dict[str, Any],
) -> tuple[float | None, str | None]:
    direct_item = spring_parameters.get("active_coils")
    direct = _number(_param_value(spring_parameters, "active_coils"))
    if direct is not None:
        if isinstance(direct_item, dict) and direct_item.get("derived_rule_id") == COMPANY_ACTIVE_COIL_RULE:
            return direct, "company_end_condition_rule"
        return direct, "drawing_or_manual"
    derived = _number(_param_value(derived_parameters, "active_coils"))
    return (derived, "company_end_condition_rule") if derived is not None else (None, None)


def _active_coil_note(active_source: str | None, derived_parameters: dict[str, Any]) -> str:
    if active_source != "company_end_condition_rule":
        return ""
    basis = str((derived_parameters.get("active_coils") or {}).get("basis") or "")
    return basis


def _derived_param(field: str, value: Any, unit: str | None, formula: str, source_fields: list[str]) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "source": ["derived"],
        "formula": formula,
        "source_fields": source_fields,
        "confidence": 0.99,
        "need_human_review": False,
    }


def _symmetric_result(
    target_field: str,
    rule_id: str,
    standard_no: str,
    value: float,
    tolerance: float,
    basis: str,
) -> dict[str, Any]:
    return _result(
        target_field=target_field,
        rule_id=rule_id,
        standard_no=standard_no,
        basis=basis,
        status="suggested",
        suggested_value=_round(value),
        suggested_tolerance_upper=tolerance,
        suggested_tolerance_lower=-tolerance,
        unit="mm" if target_field != "total_coils" else "turns",
    )


def _result(
    target_field: str,
    rule_id: str,
    standard_no: str,
    basis: str,
    status: str,
    suggested_value: Any = None,
    suggested_tolerance_upper: Any = None,
    suggested_tolerance_lower: Any = None,
    unit: str | None = None,
    need_human_review: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "target_field": target_field,
        "suggested_value": suggested_value,
        "suggested_tolerance_upper": suggested_tolerance_upper,
        "suggested_tolerance_lower": suggested_tolerance_lower,
        "unit": unit,
        "standard_no": standard_no,
        "rule_id": rule_id,
        "basis": basis,
        "status": status,
        "need_human_review": bool(status != "suggested") if need_human_review is None else need_human_review,
        "metadata": metadata or {},
    }


def _param_value(mapping: dict[str, Any], field: str) -> Any:
    value = mapping.get(field)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _can_replace_formula_solid_height(existing: Any) -> bool:
    if not isinstance(existing, dict):
        return existing in (None, "")
    if existing.get("value") in (None, ""):
        return True
    sources = _source_values(existing.get("source"))
    return (
        FORMULA_CALCULATION_SOURCE in sources
        and existing.get("formula_calculation_kind") in (None, "solid_height")
    )


def _source_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item or "").strip().lower() for item in values if item]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _grade(spring_parameters: dict[str, Any], specific_field: str) -> str | None:
    for field in (specific_field, "accuracy_grade"):
        value = str(_param_value(spring_parameters, field) or "").strip()
        if not value:
            continue
        for candidate in ("1", "2", "3"):
            if candidate in value:
                return candidate
    return None


def solid_height_mode(value: Any) -> str | None:
    normalized_end_grinding = normalize_end_grinding(value)
    if normalized_end_grinding == "两端不磨削":
        return "not_ground"
    if normalized_end_grinding == "两端磨削":
        return "ground"
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.lower().replace("-", "_").replace(" ", "")
    if normalized in {"not_ground", "notground", "unground", "no", "false"}:
        return "not_ground"
    if normalized in {"ground", "grounded", "yes", "true", "closed_and_ground"}:
        return "ground"
    if "不磨" in text or "未磨" in text:
        return "not_ground"
    if "磨" in text:
        return "ground"
    return None


def _round(value: float) -> float:
    rounded = round(float(value), 4)
    return int(rounded) if rounded.is_integer() else rounded
