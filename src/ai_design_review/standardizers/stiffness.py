from __future__ import annotations

from functools import lru_cache
from math import isclose, isfinite
from pathlib import Path
from typing import Any

from ..io_utils import project_path, read_json
from ..material_terms import normalize_material_key
from ..material_catalog import load_material_catalog, match_material_catalog
from .coil_counts import derive_active_coils


MATERIAL_STIFFNESS_PATH = project_path("config", "material_stiffness_properties.json")
FORMULA_CALCULATION_SOURCE = "formula_calculation"
FORMULA = "G * d^4 / (8 * D^3 * n)"


def refresh_compression_spring_rate_freshness(
    spring_parameters: dict[str, Any],
    spring_features: dict[str, Any] | None = None,
) -> bool:
    """Flag explicitly obsolete company-G formula evidence without changing values.

    Recorded old G is required: an old version alone is not evidence that the
    numeric result changed. Human edits and actual drawing stiffness stay intact.
    """
    existing = spring_parameters.get("spring_rate")
    if not isinstance(existing, dict):
        return False
    sources = _source_values(existing.get("source"))
    if FORMULA_CALCULATION_SOURCE not in sources or any(
        source in {"human_edited", "human_modified", "manual", "manual_input", "standardization_chat", "ai_chat"}
        for source in sources
    ):
        return False
    old_inputs = existing.get("formula_calculation_inputs") or {}
    old_g = _number(old_inputs.get("shear_modulus_mpa")) if isinstance(old_inputs, dict) else None
    if old_g is None or not isfinite(old_g) or old_g <= 0:
        return False
    current = calculate_compression_spring_rate(spring_parameters, spring_features)
    if current["status"] != "calculated" or current["config_version"] != load_material_catalog()["version"]:
        return False
    old_version = existing.get("formula_calculation_config_version")
    if old_version == current["config_version"]:
        return False
    new_g = current["inputs"]["shear_modulus_mpa"]
    old_value = _number(existing.get("value"))
    changed = (not isclose(old_g, new_g, rel_tol=1e-10, abs_tol=1e-8)
               and old_value is not None and isfinite(old_value)
               and not isclose(old_value, float(current["value"]), rel_tol=1e-10, abs_tol=1e-8))
    if changed:
        existing.update({
            "formula_recommendation_stale": True,
            "formula_material_catalog_stale": True,
            "formula_calculation_reason": (
                f"公司材料表剪切模量已更新：G 由 {old_g:g} 更新为 {new_g:g} MPa；"
                f"当前公式参考刚度为 {current['value']:g} N/mm，请核对并应用最新公式建议。"
            ),
        })
    elif existing.get("formula_material_catalog_stale"):
        existing.pop("formula_material_catalog_stale", None)
        existing.pop("formula_recommendation_stale", None)
        existing.pop("formula_calculation_reason", None)
    return changed


def apply_formula_compression_spring_rate(
    spring_parameters: dict[str, Any],
    spring_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Populate spring_rate only when it is absent or was calculated earlier."""
    existing = spring_parameters.get("spring_rate")
    result = calculate_compression_spring_rate(spring_parameters, spring_features)
    if not _can_replace(existing):
        return {**result, "applied": False, "preserved_existing_value": True}

    if result["status"] != "calculated":
        if isinstance(existing, dict):
            existing.update(
                {
                    "value": None,
                    "unit": "N/mm",
                    "source": [],
                    "evidence": "",
                    "suggested_region": "",
                    "formula_calculation_status": result["status"],
                    "formula_calculation_missing_fields": result["missing_fields"],
                    "formula_calculation_reason": result["reason"],
                }
            )
        return {**result, "applied": False}

    spring_parameters["spring_rate"] = {
        "field": "spring_rate",
        "value": result["value"],
        "unit": "N/mm",
        "tolerance_upper": None,
        "tolerance_lower": None,
        "source": [FORMULA_CALCULATION_SOURCE],
        "evidence": result["basis"],
        "confidence": 0.88,
        "page": 1,
        "position": None,
        "suggested_region": "formula_computed_spring_rate",
        "need_human_review": True,
        "formula": FORMULA,
        "source_fields": result["source_fields"],
        "formula_calculation_status": result["status"],
        "formula_calculation_inputs": result["inputs"],
        "formula_calculation_material": result["material"],
        "formula_calculation_config_version": result["config_version"],
    }
    return {**result, "applied": True}


def calculate_compression_spring_rate(
    spring_parameters: dict[str, Any],
    spring_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate theoretical stiffness for a cylindrical helical round-wire compression spring."""
    incompatible_reason = _incompatible_feature_reason(spring_features or {})
    if incompatible_reason:
        return _result("not_applicable", reason=incompatible_reason)

    wire = _number(_param_value(spring_parameters, "wire_diameter"))
    mean, mean_sources = _mean_diameter(spring_parameters, wire)
    active, active_sources = _active_coils(spring_parameters)
    material = _material_profile(spring_parameters)
    material_value = _material_value(spring_parameters)

    missing_fields = []
    if wire is None or wire <= 0:
        missing_fields.append("wire_diameter")
    if mean is None or mean <= 0:
        missing_fields.append("mean_diameter")
    if active is None or active <= 0:
        missing_fields.append("active_coils")
    if not material_value:
        missing_fields.append("material")
    if missing_fields:
        return _result(
            "missing_context",
            missing_fields=missing_fields,
            reason="缺少刚度公式输入：" + ", ".join(missing_fields),
        )
    if not material:
        return _result(
            "material_not_configured",
            missing_fields=["material"],
            reason=f"当前剪切模量配置未覆盖材料：{material_value}。",
        )

    shear_modulus = float(material["shear_modulus_mpa"])
    value = shear_modulus * wire**4 / (8 * mean**3 * active)
    inputs = {
        "shear_modulus_mpa": shear_modulus,
        "wire_diameter_mm": _round(wire),
        "mean_diameter_mm": _round(mean),
        "active_coils": _round(active),
    }
    source_fields = ["material", "wire_diameter", *mean_sources, *active_sources]
    source_fields = list(dict.fromkeys(source_fields))
    basis = (
        "公式计算：k=G*d^4/(8*D^3*n)；"
        f"G={shear_modulus:g} MPa, d={wire:g} mm, D={mean:g} mm, n={active:g}."
    )
    if material.get("property_source"):
        basis += f" {material['property_source']}。"
    return _result(
        "calculated",
        value=_round(value),
        source_fields=source_fields,
        inputs=inputs,
        material=material["display_name"],
        config_version=material["config_version"],
        basis=basis,
    )


@lru_cache(maxsize=1)
def load_material_stiffness_properties(path: str | Path | None = None) -> dict[str, Any]:
    return read_json(Path(path) if path else MATERIAL_STIFFNESS_PATH)


def _can_replace(existing: Any) -> bool:
    if not isinstance(existing, dict):
        return existing in (None, "")
    if existing.get("need_human_review") is False:
        return False
    sources = _source_values(existing.get("source"))
    if any(
        source.startswith("human") or source in {"manual", "manual_input", "standardization_chat"}
        for source in sources
    ):
        return False
    if existing.get("value") in (None, ""):
        return True
    return FORMULA_CALCULATION_SOURCE in sources


def _incompatible_feature_reason(features: dict[str, Any]) -> str:
    expected = {
        "spring_family": {"helical"},
        "spring_shape": {"cylindrical"},
        "wire_section": {"round", "circular"},
    }
    for field, values in expected.items():
        value = str(_feature_value(features, field) or "").strip().lower()
        if not value or value == "unknown":
            continue
        if value not in values:
            return f"当前刚度公式不适用于 {field}={value}。"
    return ""


def _mean_diameter(parameters: dict[str, Any], wire: float | None) -> tuple[float | None, list[str]]:
    recognized = _number(_param_value(parameters, "mean_diameter"))
    if recognized is not None:
        return recognized, ["mean_diameter"]
    if wire is None:
        return None, []
    outer = _number(_param_value(parameters, "outer_diameter"))
    if outer is not None:
        return outer - wire, ["outer_diameter", "wire_diameter"]
    inner = _number(_param_value(parameters, "inner_diameter"))
    if inner is not None:
        return inner + wire, ["inner_diameter", "wire_diameter"]
    return None, []


def _active_coils(parameters: dict[str, Any]) -> tuple[float | None, list[str]]:
    active = _number(_param_value(parameters, "active_coils"))
    if active is not None:
        return active, ["active_coils"]
    derived = derive_active_coils("compression_spring", parameters).get("active_coils") or {}
    value = _number(derived.get("value"))
    return value, list(derived.get("source_fields") or ["active_coils"])


def _material_profile(parameters: dict[str, Any]) -> dict[str, Any] | None:
    # Only the current selection is authoritative. Drawing raw_value and old
    # standard_value remain evidence, never a fallback for the current modulus.
    value = _material_value(parameters)
    if not value:
        return None
    entry = match_material_catalog(value)
    if entry:
        catalog = load_material_catalog()
        return {**entry, "config_version": catalog["version"], "property_source": catalog["source"]}
    keys = {normalize_material_key(value)}
    config = load_material_stiffness_properties()
    for profile in config.get("materials", []):
        values = profile.get("standard_values") or []
        if keys & {normalize_material_key(value) for value in values}:
            return {**profile, "config_version": config.get("version", "unknown")}
    return None


def _material_value(parameters: dict[str, Any]) -> str:
    material = parameters.get("material")
    item = material if isinstance(material, dict) else {"value": material}
    return str(item.get("value") or "").strip()


def _result(
    status: str,
    *,
    value: float | None = None,
    missing_fields: list[str] | None = None,
    reason: str = "",
    source_fields: list[str] | None = None,
    inputs: dict[str, Any] | None = None,
    material: str = "",
    config_version: str = "",
    basis: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "value": value,
        "unit": "N/mm",
        "formula": FORMULA,
        "missing_fields": missing_fields or [],
        "reason": reason,
        "source_fields": source_fields or [],
        "inputs": inputs or {},
        "material": material,
        "config_version": config_version,
        "basis": basis,
    }


def _param_value(parameters: dict[str, Any], field: str) -> Any:
    item = parameters.get(field)
    return item.get("value") if isinstance(item, dict) else item


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float | int:
    rounded = round(value, 4)
    return int(rounded) if rounded.is_integer() else rounded


def _feature_value(features: dict[str, Any], field: str) -> Any:
    value = features.get(field)
    return value.get("value") if isinstance(value, dict) else value


def _source_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item or "").strip().lower() for item in values if item]
