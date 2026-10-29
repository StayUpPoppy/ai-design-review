from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .generation_contract import generation_source_item, handedness_label, normalize_generation_value
from .material_catalog import material_catalog_display_value
from .standardizers.calculation_state import number as strict_number, parameter_current, solid_height_kind
from .standardizers.design_checks import LENGTH_UNITS, calculate_design_checks
from .surface_roughness import confirmed_surface_roughness, surface_roughness_matches
from .technical_requirements import TECHNICAL_REQUIREMENT_TYPE_LABELS, format_technical_requirement, strip_technical_requirements_title, technical_requirement_output_content, technical_requirement_body, technical_requirement_equivalence_key

CALCULATED_PROPERTIES = {"P'": "theoretical_spring_rate", "C": "spring_index", "τ_b": "solid_stress"}
FROZEN_CALCULATION_METRICS = (*CALCULATED_PROPERTIES.values(), "unit_mass")
SOLID_LABELS = {"fb", "pb", "压并载荷", "压并负荷", "压并力"}
_SW_DIRECTION_LABEL = re.compile(r"^((?:(?:" + "|".join(TECHNICAL_REQUIREMENT_TYPE_LABELS.values()) + r")\s*[:：]\s*)*)绕制方向(?=\s*[:：])")


def _sw_technical_line(line: str) -> str:
    """Output labels only; keep engineering prose and stored review text intact."""
    line = re.sub(r"^(?:\s*其他要求\s*[:：]\s*)+", "", line)
    return _SW_DIRECTION_LABEL.sub(r"\1旋向", line) if line.strip() else ""


def build_solidworks_command(
    generation_id: str,
    parameter_package: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    """Translate the frozen review snapshot into SolidWorks' command format."""

    try:
        task_id = int(str(generation_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("SolidWorks TaskId must be a numeric generation id.") from exc
    if not 1_000_000_000 <= task_id <= 9_999_999_999:
        raise ValueError("SolidWorks TaskId must be a positive 10-digit Long value.")

    preview = parameter_package.get("solidworks_preview")
    if not isinstance(preview, dict) or not all(isinstance(preview.get(key), dict) for key in ("modelParameters", "customProperties", "extraProperties")) or "技术要求" not in preview["extraProperties"]:
        preview = build_solidworks_preview(parameter_package, review)
    source = parameter_package.get("source") or {}
    spring_label = str(source.get("spring_type_label") or "压缩弹簧")
    return {
        "TaskId": task_id,
        "models": [
            {
                "modelId": 1,
                "modelName": str(source.get("drawing_name") or spring_label),
                "modelLabel": spring_label,
                "materialCode": None,
                **deepcopy(preview),
            }
        ],
    }


def build_solidworks_model_parameters(
    parameter_package: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    """Build the same modelling fields for the export preview and SW request."""

    generation_parameters = parameter_package.get("generation_parameters") or {}
    spring_parameters = generation_parameters.get("spring_parameters") or {}
    model_parameters = {
        "线径": _parameter_value(spring_parameters.get("wire_diameter")),
        "中径": _parameter_value(spring_parameters.get("mean_diameter")),
        "自由高度": _parameter_value(spring_parameters.get("free_length")),
        "圈数": _parameter_value(spring_parameters.get("total_coils"), preserve_precision=True),
        "有效圈数n": _parameter_value(spring_parameters.get("active_coils"), preserve_precision=True),
        "是否磨平": _parameter_value(spring_parameters.get("end_grinding")),
        "是否并紧": _parameter_value(spring_parameters.get("end_coils_closed")),
    }
    if model_parameters["是否并紧"] == 0:
        del model_parameters["有效圈数n"]
    return model_parameters


def _parameter_value(item: Any, *, preserve_precision: bool = False) -> Any | None:
    if not isinstance(item, dict):
        return None
    if preserve_precision:
        number = _number(item.get("value"))
        return int(number) if number is not None and number.is_integer() else number
    return _finite_or_text(item.get("value"))


def _finite_or_text(value: Any) -> Any | None:
    number = _finite_number(value)
    if number is not None:
        return number
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 3)


def _optional_number(value: Any) -> float | None:
    # Match the browser's JSON-number spelling; do not coerce booleans or prose.
    if isinstance(value, str) and not value.strip().isascii():
        return None
    return strict_number(value)


def _confirmed_optional_mm(parameters: dict[str, Any], field: str, *, allow_zero: bool = False) -> tuple[dict[str, Any], float] | None:
    """Read optional SW dimensions without adopting suggestions or rounding small values."""
    item = parameters.get(field)
    if not isinstance(item, dict) or item.get("need_human_review") is not False:
        return None
    if any(item.get(key) for key in ("tolerance_input_draft", "derived_value_stale", "formula_recommendation_stale",
                                     "diameter_linkage_error", "conflict", "value_conflict", "tolerance_conflict")):
        return None
    if not parameter_current(parameters, field):
        return None
    snapshot = item.get("confirmation_snapshot")
    if snapshot is not None and (not isinstance(snapshot, dict) or snapshot.get("kind", "parameter") != "parameter"
                                or any(isinstance(snapshot.get(key), bool) != isinstance(item.get(key), bool) or snapshot.get(key) != item.get(key)
                                       for key in ("value", "tolerance_upper", "tolerance_lower"))
                                or "value_kind" in snapshot and snapshot["value_kind"] != item.get("value_kind")):
        return None
    value = _optional_number(item.get("value"))
    factor = LENGTH_UNITS.get(str(item.get("unit") or "mm").strip().lower())
    if value is None or factor is None or value < 0 or not allow_zero and value == 0 or not math.isfinite(value * factor):
        return None
    return item, value * factor


def _model_parameters_tolerance(review: dict[str, Any]) -> dict[str, float]:
    parameters = review.get("spring_parameters") or {}
    invalid_linkage = (review.get("diameter_linkage") or {}).get("status") == "invalid"
    result = {}
    for label, field in (("外径", "outer_diameter"), ("自由高度", "free_length"), ("中径", "mean_diameter")):
        if invalid_linkage and field in {"outer_diameter", "mean_diameter"}:
            continue
        confirmed = _confirmed_optional_mm(parameters, field)
        if confirmed is None:
            continue
        item, _ = confirmed
        upper, lower = _optional_number(item.get("tolerance_upper")), _optional_number(item.get("tolerance_lower"))
        # Do not turn asymmetric or one-sided engineering requirements into ± values.
        if upper is None or lower is None or upper < 0 or upper != -lower:
            continue
        value = upper * LENGTH_UNITS[str(item.get("unit") or "mm").strip().lower()]
        if math.isfinite(value):
            result[label] = 0 if value == 0 else value
    return result


def build_solidworks_preview(parameter_package: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Recalculate authoritative inputs and freeze their calculation basis."""
    checks = calculate_design_checks(review.get("spring_parameters") or {}, review.get("spring_features") or {})
    parameter_package.setdefault("derived_parameters", {})["solidworks_design_checks"] = {
        "version": checks["version"], "material_catalog_version": checks["material_catalog_version"],
        "material_properties": deepcopy(checks["material_properties"]),
        "metrics": {key: deepcopy(checks["metrics"][key]) for key in FROZEN_CALCULATION_METRICS},
    }
    parameters = (parameter_package.get("generation_parameters") or {}).get("spring_parameters") or {}
    extra: dict[str, Any] = {"技术要求": build_solidworks_technical_text(parameter_package, review)}
    for key, metric in CALCULATED_PROPERTIES.items():
        result = checks["metrics"][metric]
        number = _number(result.get("value"))
        if result.get("status") in {"calculated", "estimated"} and number is not None:
            extra[key] = _rounded(number, 4)
    title_block: dict[str, str | int | float] = {}
    material = _parameter_value(parameters.get("material"))
    if isinstance(material, str) and material:
        title_block["材料"] = material_catalog_display_value(material)
    mass = checks["metrics"]["unit_mass"]
    number = _number(mass.get("value"))
    if mass.get("status") in {"calculated", "estimated"} and mass.get("unit") == "kg" and number is not None and number > 0:
        title_block["重量"] = _rounded(number, 8)
    drawing_no = (parameter_package.get("source") or {}).get("drawing_no")
    if isinstance(drawing_no, str) and drawing_no.strip():
        title_block["客户图号"] = drawing_no.strip()
    perpendicularity = _confirmed_optional_mm(review.get("spring_parameters") or {}, "perpendicularity", allow_zero=True)
    if perpendicularity is not None:
        title_block["垂直度A"] = perpendicularity[1]
    roughness = confirmed_surface_roughness(review)
    if roughness is not None:
        title_block["表面粗糙度"] = roughness["value"]
    settings = parameter_package.get("generation_settings")
    tolerances = _model_parameters_tolerance(review)
    return {**({"DrawingModel": settings["drawing_model"], "Username": settings["username"]} if settings else {}),
            "modelParameters": build_solidworks_model_parameters(parameter_package, review),
            **({"modelParametersTolerance": tolerances} if tolerances else {}),
            "customProperties": {"旋向": handedness_label(_parameter_value(parameters.get("handedness")))},
            "extraProperties": extra, "titleBlockProperties": title_block}


def build_solidworks_technical_text(parameter_package: dict[str, Any], review: dict[str, Any]) -> str:
    generation = parameter_package.get("generation_parameters") or {}
    parameters = generation.get("spring_parameters") or {}
    lines: list[str] = []
    keys: set[tuple[str, str, str]] = set()
    roughness = confirmed_surface_roughness(review)
    from .surface_source_links import surface_output_source_keys, surface_source_key, surface_scope_key
    converted_sources = surface_output_source_keys(review)

    def append(line: str, scope: Any = None) -> None:
        if (surface_source_key(line), surface_scope_key(scope)) in converted_sources:
            return
        if surface_roughness_matches({"content": line, "application_scope": scope}, roughness):
            return
        line = _sw_technical_line(line)
        key = _sentence_key(line, scope)
        if line and key not in keys:
            keys.add(key)
            lines.append(line)

    end_note = _confirmed_end_note(parameters, review)
    if end_note:
        append(end_note)
    material = _parameter_value(parameters.get("material"))
    if material is not None:
        append(f"材料：{material_catalog_display_value(material)}。")
    handedness = handedness_label(_parameter_value(parameters.get("handedness")))
    if handedness:
        append(f"旋向：{handedness}。")
    requirements = generation.get("technical_requirements") or []
    remaining: list[dict[str, Any]] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        content = _content(item)
        if item.get("type") in {"surface_roughness", "roughness"} and content:
            append(_roughness_line(format_technical_requirement(item)), item.get("application_scope"))
        else:
            remaining.append(item)
    hb = _confirmed_solid_height(review)
    points = [point for point in generation.get("load_points") or [] if isinstance(point, dict)]
    solid = [point for point in points if _solid_label(point.get("label"))]
    fb = _number((solid[0].get("force") or {}).get("value")) if len(solid) == 1 else None
    fb_height = _number((solid[0].get("height") or {}).get("value")) if len(solid) == 1 else None
    fb_text = _force_text(solid[0]) if fb is not None and fb >= 0 else None
    if hb is not None and fb_text is not None and fb_height is not None and math.isclose(hb, fb_height, rel_tol=0, abs_tol=1e-9):
        append(f"当弹簧压并至高度 Hb = {_text_number(hb)} mm 时，对应压并载荷 Fb = {fb_text}。")
    else:
        if hb is not None:
            append(f"压并高度：Hb = {_text_number(hb)} mm。")
        if fb_text is not None:
            suffix = f"（载荷测试高度 {_text_number(fb_height)} mm）" if hb is not None and fb_height is not None else ""
            append(f"压并载荷：Fb = {fb_text}{suffix}。")
    for point in points:
        if _solid_label(point.get("label")):
            continue
        height = _number((point.get("height") or {}).get("value"))
        force = _number((point.get("force") or {}).get("value"))
        if height is None or height <= 0 or force is None or force < 0:
            continue
        label = str(point.get("label") or "").strip()
        match = re.fullmatch(r"[Ff](\d+)", label)
        if match:
            append(f"当弹簧工作高度 H{match[1]} = {_text_number(height)} mm 时，对应工作载荷 {label} = {_force_text(point)}。")
        else:
            append(f"载荷点 {label}：高度 {_text_number(height)} mm，力值 {_force_text(point)}。")
    for label, field in (("总圈数", "total_coils"), ("有效圈数", "active_coils")):
        if field == "active_coils" and _parameter_value(parameters.get("end_coils_closed")) == 0:
            continue
        value = _parameter_value(parameters.get(field), preserve_precision=True)
        if value is not None:
            append(f"{label}：{value} 圈。")
    # Only whole equivalent sentences are removed; composite/conflicting notes survive.
    requirement_keys: set[tuple[str, str, str]] = set()
    for item in remaining:
        # Match the frontend group before adding display labels or scope text.
        key = technical_requirement_equivalence_key(item)
        if key in requirement_keys:
            continue
        requirement_keys.add(key)
        append(format_technical_requirement(item), item.get("application_scope"))
    if not requirements:
        for line in strip_technical_requirements_title(generation.get("technical_requirements_text")).splitlines():
            body = technical_requirement_output_content({"content": line})
            if body:
                append(format_technical_requirement({"content": body}))
    return "\n".join(f"{index}.{line}" for index, line in enumerate(lines, 1))


def _confirmed_end_note(exported: dict[str, Any], review: dict[str, Any]) -> str | None:
    """Describe the same confirmed end conditions used by this generation snapshot."""
    parameters = review.get("spring_parameters") or {}
    values: list[int] = []
    for field in ("end_coils_closed", "end_grinding"):
        item = generation_source_item(parameters, field)
        source_field = "end_type" if field == "end_coils_closed" and item is parameters.get("end_type") else field
        if (not isinstance(item, dict) or item.get("need_human_review") is not False
                or item.get("formula_recommendation_stale") or not parameter_current(parameters, source_field)):
            return None
        output = exported.get(field)
        if not isinstance(output, dict):
            return None
        try:
            value = normalize_generation_value(field, item.get("value"))
            if value != normalize_generation_value(field, output.get("value")):
                return None
        except ValueError:
            return None
        values.append(value)
    return {
        (1, 1): "两端并紧磨平，每端磨270°。",
        (1, 0): "两端并紧，不磨平。",
        (0, 1): "两端不并紧，端面磨平。",
        (0, 0): "两端不并紧，不磨平。",
    }[tuple(values)]


def _confirmed_solid_height(review: dict[str, Any]) -> float | None:
    item = (review.get("spring_parameters") or {}).get("solid_height")
    if not isinstance(item, dict) or item.get("need_human_review") is not False:
        return None
    if not parameter_current(review.get("spring_parameters") or {}, "solid_height") or item.get("formula_recommendation_stale") or solid_height_kind(item) not in {"input_height", "nominal_estimate"}:
        return None
    value = _number(item.get("value"))
    factor = LENGTH_UNITS.get(str(item.get("unit") or "mm").strip().lower())
    normalized = value * factor if value is not None and factor is not None else None
    free = (review.get("spring_parameters") or {}).get("free_length") or {}
    free_value, free_factor = _number(free.get("value")), LENGTH_UNITS.get(str(free.get("unit") or "mm").strip().lower())
    if free_value is not None and free_factor is not None and normalized is not None and normalized >= free_value * free_factor:
        return None
    return normalized if normalized is not None and math.isfinite(normalized) and normalized > 0 else None


def _solid_label(value: Any) -> bool:
    return re.sub(r"[\s_]", "", str(value or "")).casefold() in SOLID_LABELS


def _force_text(point: dict[str, Any]) -> str:
    force = point.get("force") or {}
    text = f"{_text_number(force['value'])} N"
    percent = _number(force.get("tolerance_percent"))
    upper, lower = (_number(force.get(key)) for key in ("tolerance_upper", "tolerance_lower"))
    if percent is not None:
        return text + f"（允差 ±{_text_number(abs(percent))}%）"
    if upper is None and lower is None:
        return text
    if upper is not None and lower is not None and upper >= 0 and math.isclose(upper, -lower, rel_tol=0, abs_tol=1e-9):
        return text + f"（允差 ±{_text_number(upper)} N）"
    def signed(number: float) -> str:
        return ("+" if number > 0 else "") + _text_number(number)
    tolerance = "/".join(signed(number) for number in (upper, lower) if number is not None)
    return text + f"（允差 {tolerance} N）"


def _content(item: dict[str, Any]) -> str:
    content = technical_requirement_output_content(item)
    content = re.sub(r"(?:\s*(?:\r\n?|\n)\s*)+", "；", content)
    return re.sub(r"[\t ]+", " ", content).strip()


def _roughness_line(content: str) -> str:
    line = re.sub(r"粗糙度\s*[:：]?\s*Ra\s*", "表面粗糙度：Ra ", content, count=1)
    line = line.replace("表面表面粗糙度", "表面粗糙度")
    line = re.sub(r"(?<=\d)\s*[μµ]m", " μm", line)
    return line.rstrip("。.") + "。"


def _sentence_key(content: str, scope: Any = None) -> tuple[str, str, str]:
    key, kind = technical_requirement_body(content)
    material = re.fullmatch(r"(?:材质|材料)\s*[:：]?\s*(.+?)\s*[。.]*", key)
    if material:
        key = f"材料：{material_catalog_display_value(material[1])}"
    key = re.sub(r"^(?:材质|材料)", "材料", key)
    key = re.sub(r"^(?:旋向|绕制方向)", "绕制方向", key)
    key = re.sub(r"^(?:有效圈数n?|工作圈数)", "工作圈数", key)
    key = key.replace("表面粗糙度", "粗糙度")
    # Generic category headings do not change a template sentence's meaning.
    key = re.sub(r"^(材料|绕制方向|工作圈数)\s*:\s*", r"\1", key)
    return technical_requirement_equivalence_key({"type": kind if kind not in {None, "other", "process"} else "other", "content": key, "application_scope": scope})


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _rounded(number: float, digits: int) -> int | float:
    number = round(number, digits)
    return int(number) if number.is_integer() else number


def _text_number(value: Any) -> str:
    return str(_rounded(float(value), 4))
