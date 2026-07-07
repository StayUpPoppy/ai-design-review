from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .material_terms import normalize_material


def apply_spring_semantic_mapping(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add spring-specific candidates inferred from generic recognizer output."""
    enriched = [deepcopy(candidate) for candidate in candidates]
    existing_fields = {candidate.get("field") for candidate in enriched}

    notes_text = "\n".join(
        str(candidate.get("value") or candidate.get("evidence") or "")
        for candidate in enriched
        if candidate.get("feature_type") == "note" or str(candidate.get("field", "")).startswith("werk24_note")
    )
    note_anchor = _first_note(enriched)
    dimensions = [
        candidate for candidate in enriched
        if candidate.get("feature_type") == "dimension" and isinstance(candidate.get("value"), (int, float))
    ]

    material = _normalize_material_candidate(enriched)
    if material and "material" not in existing_fields:
        enriched.append(material)
        existing_fields.add("material")
    elif material and _needs_material_normalization(enriched):
        enriched.append(material)

    for candidate in _map_dimensions(dimensions):
        if candidate["field"] not in existing_fields:
            enriched.append(candidate)
            existing_fields.add(candidate["field"])

    for candidate in _extract_from_notes(notes_text, note_anchor, dimensions):
        if candidate["field"] == "load_point" or candidate["field"] not in existing_fields:
            enriched.append(candidate)
            existing_fields.add(candidate["field"])

    return enriched


def _map_dimensions(dimensions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    used_reference_ids: set[Any] = set()

    outer = _outer_diameter_candidate(dimensions)
    if outer:
        mapped.append(_semantic_candidate("outer_diameter", outer, confidence=0.88))
        used_reference_ids.add(outer.get("reference_id"))

    free = _free_length_candidate(dimensions, used_reference_ids)
    if free:
        mapped.append(_semantic_candidate("free_length", free, confidence=0.84))

    return mapped


def _outer_diameter_candidate(dimensions: list[dict[str, Any]]) -> dict[str, Any] | None:
    with_tolerance = [
        dim for dim in dimensions
        if dim.get("tolerance_upper") is not None or dim.get("tolerance_lower") is not None
    ]
    if with_tolerance:
        return max(with_tolerance, key=lambda item: float(item.get("value") or 0))

    larger = [dim for dim in dimensions if float(dim.get("value") or 0) >= 20]
    if larger:
        return max(larger, key=lambda item: float(item.get("value") or 0))
    return None


def _free_length_candidate(dimensions: list[dict[str, Any]], used_reference_ids: set[Any]) -> dict[str, Any] | None:
    available = [
        dim for dim in dimensions
        if dim.get("reference_id") not in used_reference_ids
    ]
    if not available:
        return None
    return max(available, key=lambda item: float(item.get("value") or 0))


def _extract_from_notes(
    notes_text: str,
    note_anchor: dict[str, Any] | None,
    dimensions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not notes_text:
        return []

    mapped: list[dict[str, Any]] = []
    wire = _parse_wire_diameter(notes_text, note_anchor)
    if wire:
        mapped.append(wire)

    total_coils = _parse_total_coils(notes_text, note_anchor)
    if total_coils:
        mapped.append(total_coils)

    handedness = _parse_handedness(notes_text, note_anchor)
    if handedness:
        mapped.append(handedness)

    mapped.extend(_parse_standard_context(notes_text, note_anchor))
    mapped.extend(_parse_load_points(notes_text, note_anchor, dimensions))
    mapped.extend(_parse_technical_requirements(notes_text, note_anchor))
    return mapped


def _parse_wire_diameter(text: str, note_anchor: dict[str, Any] | None) -> dict[str, Any] | None:
    match = re.search(r"(?:[ΦØ]?\s*)?(\d+(?:\.\d+)?)\s*[±＋]\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    value = float(match.group(1))
    tolerance = float(match.group(2))
    if value > 8:
        return None
    return _from_note(
        "wire_diameter",
        value,
        note_anchor,
        evidence=match.group(0),
        unit="mm",
        tolerance_upper=tolerance,
        tolerance_lower=-tolerance,
        confidence=0.78,
    )


def _parse_total_coils(text: str, note_anchor: dict[str, Any] | None) -> dict[str, Any] | None:
    explicit = re.search(r"(?:总圈数|圈数)\D*(\d+(?:\.\d+)?)", text)
    if explicit:
        evidence = explicit.group(0)
        value = float(explicit.group(1))
    else:
        line_match = re.search(r"(?m)^\s*2[,.，:：]?\s*(\d+(?:\.\d+)?)\b", text)
        if not line_match:
            return None
        evidence = line_match.group(0)
        value = float(line_match.group(1))
    return _from_note(
        "total_coils",
        int(value) if value.is_integer() else value,
        note_anchor,
        evidence=evidence,
        unit="turns",
        confidence=0.58 if "总圈数" not in evidence and "圈数" not in evidence else 0.84,
    )


def _parse_handedness(text: str, note_anchor: dict[str, Any] | None) -> dict[str, Any] | None:
    if "右旋" in text:
        value = "右旋"
    elif "左旋" in text:
        value = "左旋"
    else:
        return None
    return _from_note("handedness", value, note_anchor, evidence=value, confidence=0.84)


def _parse_load_points(
    text: str,
    note_anchor: dict[str, Any] | None,
    dimensions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mapped = []
    for label in ("F1", "F2"):
        index = label[-1]
        h_match = re.search(rf"H{index}\s*=?\s*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
        f_match = re.search(rf"{label}\s*=?\s*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
        if not h_match or not f_match:
            continue
        height = float(h_match.group(1))
        force = float(f_match.group(1))
        dim = _dimension_by_value(dimensions, height)
        evidence = _slice_evidence(text, min(h_match.start(), f_match.start()), max(h_match.end(), f_match.end()))
        mapped.append(
            {
                "field": "load_point",
                "value": {
                    "label": label,
                    "height": height,
                    "height_unit": "mm",
                    "force": force,
                    "force_unit": "N",
                    "force_tolerance_percent": _parse_force_tolerance_percent(evidence),
                    "load_tolerance_percent": _parse_force_tolerance_percent(evidence),
                    "test_height_type": "specified_height",
                    "reference_only": label == "F2" and ("参考" in text or "(*)" in text or "*)" in text),
                },
                "source": "werk24_semantic",
                "evidence": evidence,
                "confidence": 0.76,
                "page": (dim or note_anchor or {}).get("page", 1),
                "position": (dim or note_anchor or {}).get("position"),
                "suggested_region": "Werk24 note/dimension semantic mapping",
            }
        )
    return mapped


def _parse_standard_context(text: str, note_anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    standard = re.search(r"GB\s*/?\s*T\s*1239\.?2\s*[-—－]?\s*2009", text, re.IGNORECASE)
    if standard:
        mapped.append(_from_note("standard_no", "GB/T 1239.2-2009", note_anchor, standard.group(0), confidence=0.78))
        mapped.append(_from_note("manufacturing_method", "cold_coiled", note_anchor, standard.group(0), confidence=0.76))

    hot_standard = re.search(r"GB\s*/?\s*T\s*23934\s*[-—－]?\s*2014", text, re.IGNORECASE)
    if hot_standard:
        mapped.append(_from_note("standard_no", "GB/T 23934-2014", note_anchor, hot_standard.group(0), confidence=0.78))
        mapped.append(_from_note("manufacturing_method", "hot_coiled", note_anchor, hot_standard.group(0), confidence=0.76))

    if re.search(r"(圆柱螺旋|圆柱\s*压缩|cylindrical\s+compression)", text, re.IGNORECASE):
        mapped.append(_from_note("spring_family", "helical", note_anchor, "圆柱螺旋压缩弹簧", confidence=0.68))
        mapped.append(_from_note("spring_shape", "cylindrical", note_anchor, "圆柱螺旋压缩弹簧", confidence=0.68))
    if re.search(r"(冷卷|冷绕|冷成形|cold\s*(?:coiled|formed|wound))", text, re.IGNORECASE):
        mapped.append(_from_note("manufacturing_method", "cold_coiled", note_anchor, "冷卷/冷成形关键词", confidence=0.72))
    if re.search(r"(热卷|热绕|热成形|hot\s*(?:coiled|formed|wound))", text, re.IGNORECASE):
        mapped.append(_from_note("manufacturing_method", "hot_coiled", note_anchor, "热卷/热成形关键词", confidence=0.72))
    if re.search(r"(圆锥|锥形|conical)", text, re.IGNORECASE):
        mapped.append(_from_note("spring_shape", "conical", note_anchor, "圆锥/锥形关键词", confidence=0.72))
    if re.search(r"(鼓形|腰鼓|barrel|hourglass)", text, re.IGNORECASE):
        mapped.append(_from_note("spring_shape", "barrel", note_anchor, "鼓形/腰鼓关键词", confidence=0.7))
    if re.search(r"(矩形截面|方形截面|模具弹簧|rectangular\s*(?:wire|section))", text, re.IGNORECASE):
        mapped.append(_from_note("wire_section", "rectangular", note_anchor, "矩形截面关键词", confidence=0.72))
    if re.search(r"(变节距|不等节距|variable\s*pitch)", text, re.IGNORECASE):
        mapped.append(_from_note("pitch_type", "variable", note_anchor, "变节距关键词", confidence=0.72))

    general_grade = re.search(r"(?:精度等级|精度|等级|级别)\s*[:：]?\s*([123])\s*级?", text)
    if general_grade:
        mapped.append(_from_note("accuracy_grade", f"{general_grade.group(1)}级", note_anchor, general_grade.group(0), confidence=0.68))

    grade_rules = [
        ("diameter_accuracy_grade", r"(?:直径|外径|内径|中径)\s*(?:精度等级|精度|等级)\s*[:：]?\s*([123])\s*级?"),
        ("free_length_accuracy_grade", r"(?:自由长|自由长度|自由高度|H0)\s*(?:精度等级|精度|等级)\s*[:：]?\s*([123])\s*级?"),
        ("load_accuracy_grade", r"(?:负荷|载荷|力值|负载)\s*(?:精度等级|精度|等级)\s*[:：]?\s*([123])\s*级?"),
        ("stiffness_accuracy_grade", r"(?:刚度|剛度)\s*(?:精度等级|精度|等级)\s*[:：]?\s*([123])\s*级?"),
    ]
    for field, pattern in grade_rules:
        match = re.search(pattern, text)
        if match:
            mapped.append(_from_note(field, f"{match.group(1)}级", note_anchor, match.group(0), confidence=0.7))

    if re.search(r"外径\s*(?:控制|受控)", text):
        mapped.append(_from_note("controlled_diameter_field", "outer_diameter", note_anchor, "外径控制", confidence=0.68))
    elif re.search(r"内径\s*(?:控制|受控)", text):
        mapped.append(_from_note("controlled_diameter_field", "inner_diameter", note_anchor, "内径控制", confidence=0.68))

    end_grinding = re.search(r"(?:两端|端面|端部)?\s*(?:并紧)?\s*(不磨|未磨|磨削|磨平|磨)", text)
    if end_grinding:
        mapped.append(_from_note("end_grinding", end_grinding.group(0).strip(), note_anchor, end_grinding.group(0), confidence=0.66))

    spring_rate = re.search(r"(?:刚度|剛度|弹簧刚度|SPRING\s*RATE|RATE)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:N\s*/\s*mm|N/mm)?", text, re.IGNORECASE)
    if spring_rate:
        mapped.append(_from_note("spring_rate", float(spring_rate.group(1)), note_anchor, spring_rate.group(0), unit="N/mm", confidence=0.7))
    return mapped


def _parse_force_tolerance_percent(evidence: str) -> int | None:
    matches = re.findall(r"(?:±)?\s*(\d+(?:\.\d+)?)\s*%", evidence)
    non_zero = [int(float(match)) for match in matches if float(match) > 0]
    if non_zero:
        return non_zero[-1]
    if "10" in evidence:
        return 10
    return None


def _parse_technical_requirements(text: str, note_anchor: dict[str, Any] | None) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    heat = re.search(r"300\s*°?\s*C\s*\+?\s*10\s*°?\s*C?\s*/\s*20\s*min\s*\+?\s*1\s*min", text, re.IGNORECASE)
    if heat:
        mapped.append(_from_note("heat_treatment", heat.group(0), note_anchor, heat.group(0), confidence=0.74))

    surface = _parse_surface_requirement(text)
    if surface:
        value, evidence, confidence = surface
        mapped.append(_from_note("surface_requirement", value, note_anchor, evidence, confidence=confidence))

    hardness = re.search(r"HRC\s*\d+(?:\s*[-~～]\s*\d+)?", text, re.IGNORECASE)
    if hardness:
        mapped.append(_from_note("hardness", re.sub(r"\s+", "", hardness.group(0).upper()), note_anchor, hardness.group(0), confidence=0.76))

    salt = re.search(r"720\s*h", text, re.IGNORECASE)
    if salt:
        mapped.append(_from_note("salt_spray", "720h", note_anchor, salt.group(0), confidence=0.72))

    env = re.search(r"30512\s*-\s*2014", text)
    if env:
        mapped.append(
            _from_note(
                "environmental",
                "GB/T 30512-2014",
                note_anchor,
                env.group(0),
                confidence=0.7,
            )
        )
    return mapped


def _parse_surface_requirement(text: str) -> tuple[str, str, float] | None:
    labeled = re.search(r"(表面处理|表面處理|表面要求|外观要求|外觀要求)\s*[:：]?\s*([^\n\r|;；]*)", text)
    if labeled:
        value = labeled.group(2).strip()
        return value, labeled.group(0).strip(), 0.74 if value else 0.6
    for treatment in ("镀锌五彩", "镀锌", "镀镍", "镀铬", "镀锡", "钝化", "发黑", "磷化", "达克罗", "电泳", "喷塑", "防锈油"):
        if treatment in text:
            return treatment, treatment, 0.78
    return None


def _normalize_material_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("field") != "material":
            continue
        value = str(candidate.get("value") or candidate.get("evidence") or "")
        normalized = normalize_material(value)
        if normalized["normalization_status"] != "matched":
            continue
        mapped = deepcopy(candidate)
        mapped["value"] = normalized["value"]
        mapped["raw_value"] = normalized["raw_value"]
        mapped["standard_value"] = normalized["standard_value"]
        mapped["normalization_status"] = normalized["normalization_status"]
        mapped["normalization_source"] = normalized["normalization_source"]
        mapped["source"] = "werk24_semantic"
        mapped["confidence"] = max(float(mapped.get("confidence") or 0), 0.9)
        mapped["evidence"] = candidate.get("evidence") or value
        return mapped
    return None


def _needs_material_normalization(candidates: list[dict[str, Any]]) -> bool:
    return any(
        candidate.get("field") == "material"
        and _standard_material_value(candidate) not in (None, candidate.get("value"))
        for candidate in candidates
    )


def _standard_material_value(candidate: dict[str, Any]) -> str | None:
    normalized = normalize_material(candidate.get("value"))
    if normalized["normalization_status"] != "matched":
        return None
    return str(normalized["value"])


def _semantic_candidate(field: str, source: dict[str, Any], confidence: float) -> dict[str, Any]:
    mapped = {
        "field": field,
        "value": source.get("value"),
        "unit": source.get("unit"),
        "tolerance_upper": source.get("tolerance_upper"),
        "tolerance_lower": source.get("tolerance_lower"),
        "source": "werk24_semantic",
        "evidence": source.get("evidence", ""),
        "confidence": confidence,
        "page": source.get("page", 1),
        "position": source.get("position"),
        "suggested_region": f"semantic mapping from {source.get('field')}",
        "raw": source,
    }
    return mapped


def _from_note(
    field: str,
    value: Any,
    note_anchor: dict[str, Any] | None,
    evidence: str,
    unit: str | None = None,
    tolerance_upper: float | None = None,
    tolerance_lower: float | None = None,
    confidence: float = 0.7,
) -> dict[str, Any]:
    anchor = note_anchor or {}
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "tolerance_upper": tolerance_upper,
        "tolerance_lower": tolerance_lower,
        "source": "werk24_semantic",
        "evidence": evidence,
        "confidence": confidence,
        "page": anchor.get("page", 1),
        "position": anchor.get("position"),
        "suggested_region": "Werk24 note semantic mapping",
    }


def _first_note(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("feature_type") == "note" or str(candidate.get("field", "")).startswith("werk24_note"):
            return candidate
    return None


def _dimension_by_value(dimensions: list[dict[str, Any]], value: float) -> dict[str, Any] | None:
    for dimension in dimensions:
        if abs(float(dimension.get("value") or 0) - value) <= 1e-6:
            return dimension
    return None


def _slice_evidence(text: str, start: int, end: int) -> str:
    left = max(0, start - 8)
    right = min(len(text), end + 12)
    return " ".join(text[left:right].split())
