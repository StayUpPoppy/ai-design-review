from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


ROLE_SOURCE = "dimension_role_ranker"

# A numeric value placed beside a surface-finish symbol is a technical
# requirement, not a spring geometry dimension.
_SURFACE_ROUGHNESS_RE = re.compile(
    r"(?:roughness|surface\s*(?:finish|roughness)|\b(?:ra|rz)\s*\d|"
    r"\u7c97\u7cd9\u5ea6|\u8868\u9762\u7c97\u7cd9|\u5c0f\u4e09\u89d2|\u8868\u9762\u7b26\u53f7|"
    r"[\u25bd\u25bc\u2315])",
    re.IGNORECASE,
)

CORE_DIMENSION_FIELDS = {
    "outer_diameter",
    "inner_diameter",
    "mean_diameter",
    "free_length",
    "body_length",
    "solid_height",
    "wire_diameter",
}


def apply_compression_dimension_role_ranking(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add role-aware compression spring dimension candidates before fusion.

    OCR/VLM often sees the right numbers but assigns a drawing dimension to the
    wrong spring field. This pass does not delete recognizer output; it appends
    stronger candidates when the surrounding evidence is consistent enough.
    Fusion can then pick the role-aware candidate while still preserving the
    original candidates as conflict evidence.
    """
    enriched = [deepcopy(candidate) for candidate in candidates]
    if not _looks_like_compression_spring(enriched):
        return enriched

    text = _combined_text(enriched)
    load_heights = _load_heights(enriched, text)
    outer_choice = _select_outer_diameter(enriched, text, load_heights)
    if outer_choice and outer_choice["score"] >= 0.86:
        enriched.append(
            _role_candidate(
                "outer_diameter",
                outer_choice,
                reason="按压缩弹簧尺寸角色重排：优先采用带直径/竖排/外径公差证据的外径候选。",
            )
        )

    free_choice = _select_free_length(enriched, text, load_heights, outer_choice)
    if free_choice and free_choice["score"] >= 0.82:
        enriched.append(
            _role_candidate(
                "free_length",
                free_choice,
                reason="按压缩弹簧尺寸角色重排：自由长度应优先采用轴向长度，并应大于载荷测试高度。",
            )
        )

    return enriched


def _looks_like_compression_spring(candidates: list[dict[str, Any]]) -> bool:
    fields = {str(candidate.get("field") or "") for candidate in candidates}
    if "load_point" in fields:
        return True
    text = _combined_text(candidates)
    if re.search(r"\bH[12]\b[\s\S]{0,80}\bF[12]\b", text, re.IGNORECASE):
        return True
    if re.search(r"(压缩弹簧|压簧|压力弹簧|圆柱螺旋压缩|compression\s+spring)", text, re.IGNORECASE):
        return True
    return False


def _select_outer_diameter(
    candidates: list[dict[str, Any]],
    text: str,
    load_heights: list[float],
) -> dict[str, Any] | None:
    pool = [
        _choice(candidate, _number(candidate.get("value")), field=str(candidate.get("field") or ""))
        for candidate in candidates
        if _is_eligible_outer_candidate(candidate)
    ]
    pool = [item for item in pool if item["value"] is not None and 5 <= float(item["value"]) <= 200]
    pool.extend(_diameter_text_choices(text))
    if not pool:
        return None

    max_load_height = max(load_heights) if load_heights else None
    has_geometry_anchored_candidate = any(
        _has_outer_geometry_anchor(item["candidate"])
        for item in pool
    )
    scored: list[dict[str, Any]] = []
    for item in pool:
        candidate = item["candidate"]
        value = float(item["value"])
        evidence = _candidate_text(candidate)
        score = float(candidate.get("confidence", item.get("confidence", 0.55)) or 0.55)
        marker = _has_diameter_marker(candidate)
        if item["field"] == "outer_diameter":
            score += 0.18
        elif item["field"] in {"mean_diameter", "inner_diameter"}:
            score -= 0.08
        elif item["field"] == "free_length":
            score -= 0.28
        if marker:
            score += 0.38
        if _has_outer_tolerance(candidate):
            score += 0.24
        if _has_outer_geometry_anchor(candidate):
            score += 0.16
        elif has_geometry_anchored_candidate:
            # The assigned field is not sufficient evidence when another
            # candidate is tied to a dimension marker or tolerance.
            score -= 0.66
        if max_load_height is not None and value <= max_load_height + max(1.2, max_load_height * 0.08) and not marker:
            score -= 0.28
        if re.search(r"\b[HF][12]\b|力值|载荷|负荷|\d+\s*N|%", evidence, re.IGNORECASE):
            score -= 0.3
        item["score"] = round(score, 3)
        scored.append(item)

    best = max(scored, key=lambda item: item["score"])
    if not _has_outer_geometry_anchor(best["candidate"]):
        return None
    return best


def _is_eligible_outer_candidate(candidate: dict[str, Any]) -> bool:
    field = str(candidate.get("field") or "")
    if field not in {"outer_diameter", "mean_diameter", "inner_diameter", "free_length"}:
        return False
    if _is_surface_roughness_candidate(candidate):
        return False
    # A dimension explicitly labelled as inner or mean diameter is not an
    # ambiguous OCR number and must not be reclassified as an outer diameter.
    return not (
        field in {"inner_diameter", "mean_diameter"}
        and _has_explicit_diameter_role_anchor(candidate, field)
    )


def _select_free_length(
    candidates: list[dict[str, Any]],
    text: str,
    load_heights: list[float],
    outer_choice: dict[str, Any] | None,
) -> dict[str, Any] | None:
    pool = [
        _choice(candidate, _number(candidate.get("value")), field=str(candidate.get("field") or ""))
        for candidate in candidates
        if str(candidate.get("field") or "") in {"free_length", "body_length", "outer_diameter"}
        and not _is_surface_roughness_candidate(candidate)
    ]
    pool = [item for item in pool if item["value"] is not None and 2 <= float(item["value"]) <= 300]
    pool.extend(_free_length_text_choices(text, load_heights, outer_choice))
    if not pool:
        return None

    max_load_height = max(load_heights) if load_heights else None
    outer_value = float(outer_choice["value"]) if outer_choice and outer_choice.get("value") is not None else None
    outer_is_strong = bool(outer_choice and (_has_diameter_marker(outer_choice["candidate"]) or _has_outer_tolerance(outer_choice["candidate"])))

    has_axis_length_candidate = any(_has_axis_length_anchor(item["candidate"]) for item in pool)

    scored: list[dict[str, Any]] = []
    for item in pool:
        candidate = item["candidate"]
        value = float(item["value"])
        evidence = _candidate_text(candidate)
        score = float(candidate.get("confidence", item.get("confidence", 0.55)) or 0.55)
        if item["field"] == "free_length":
            score += 0.26
        elif item["field"] == "body_length":
            score += 0.08
        elif item["field"] == "outer_diameter":
            score -= 0.38
        if _has_axis_length_anchor(candidate):
            score += 0.24
        elif has_axis_length_candidate:
            score -= 0.58
        if re.search(r"(自由长|自由长度|自由高度|FREE\s*LENGTH|L0|Lf)", evidence, re.IGNORECASE):
            score += 0.42
        if max_load_height is not None:
            if value <= max_load_height:
                score -= 1.2
            else:
                score += 0.3
                diff = value - max_load_height
                if diff >= max(1.5, max_load_height * 0.12):
                    score += 0.16
                elif diff <= max(0.8, max_load_height * 0.05):
                    score -= 0.24
        if outer_value is not None and abs(value - outer_value) <= 1e-6 and outer_is_strong:
            score -= 0.62
        if _has_diameter_marker(candidate) or _has_outer_tolerance(candidate):
            score -= 0.36
        if re.search(r"\bF[12]\b|力值|载荷|负荷|\d+\s*N|%", evidence, re.IGNORECASE):
            score -= 0.32
        item["score"] = round(score, 3)
        scored.append(item)

    best = max(scored, key=lambda item: item["score"])
    if max_load_height is not None and float(best["value"]) <= max_load_height:
        return None
    return best


def _diameter_text_choices(text: str) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    patterns = [
        r"(?:外径|外徑|OD|O\.D\.|[ΦØ])\s*(\d+(?:\.\d+)?)\s*(?:0|上偏差0)?\s*[-−/]?\s*(0\.\d+)?",
        r"(\d+(?:\.\d+)?)\s*(?:0|上偏差0)\s*[-−/]\s*(0\.\d+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            context = text[max(0, match.start() - 12) : min(len(text), match.end() + 12)]
            if _has_inner_or_mean_dimension_text(context):
                continue
            value = _number(match.group(1))
            if value is None or not 5 <= value <= 200:
                continue
            lower = -float(match.group(2)) if match.lastindex and match.group(2) else None
            choices.append(
                _synthetic_choice(
                    "outer_diameter",
                    value,
                    match.group(0),
                    confidence=0.72,
                    tolerance_upper=0 if lower is not None else None,
                    tolerance_lower=lower,
                )
            )
    return choices


def _free_length_text_choices(
    text: str,
    load_heights: list[float],
    outer_choice: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for match in re.finditer(r"(?:自由长|自由长度|自由高度|FREE\s*LENGTH|L0|Lf)\s*[:：=]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE):
        value = _number(match.group(1))
        if value is not None:
            choices.append(_synthetic_choice("free_length", value, match.group(0), confidence=0.78))

    if not load_heights:
        return choices

    max_height = max(load_heights)
    excluded_values = set(_rounded_numbers(load_heights))
    if outer_choice and outer_choice.get("value") is not None:
        excluded_values.add(round(float(outer_choice["value"]), 3))

    for match in re.finditer(r"(?<![A-Za-z])(\d+(?:\.\d+)?)(?!\s*(?:N|%|°|℃|C|min|h|级|級))", text):
        value = _number(match.group(1))
        if value is None or not max_height < value <= 160:
            continue
        if round(value, 3) in excluded_values:
            continue
        context = text[max(0, match.start() - 18) : min(len(text), match.end() + 18)]
        if re.search(r"[HF][12]\s*=?\s*$|F[12]\s*=?|力值|载荷|负荷|温度|热处理|盐雾|GB\s*/?\s*T", context, re.IGNORECASE):
            continue
        if re.search(r"[±＋]\s*\d|[-−]\s*0\.\d", context):
            continue
        choices.append(_synthetic_choice("free_length", value, f"全文轴向长度候选 {match.group(0)}", confidence=0.64))
    return _dedupe_choices(choices)


def _role_candidate(field: str, choice: dict[str, Any], reason: str) -> dict[str, Any]:
    source = choice["candidate"]
    value = choice["value"]
    confidence = min(0.89, max(0.72, float(choice.get("score", 0.82)) - 0.03))
    evidence = str(source.get("evidence") or source.get("value") or value)
    return {
        "field": field,
        "feature_type": "dimension",
        "value": int(value) if isinstance(value, float) and value.is_integer() else value,
        "unit": source.get("unit") or "mm",
        "tolerance_upper": source.get("tolerance_upper"),
        "tolerance_lower": source.get("tolerance_lower"),
        "source": ROLE_SOURCE,
        "evidence": f"{reason} 候选依据：{evidence}",
        "confidence": confidence,
        "page": source.get("page", 1),
        "position": source.get("position"),
        "suggested_region": "Compression spring dimension role ranking",
    }


def _choice(candidate: dict[str, Any], value: float | None, field: str) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "candidate": candidate,
        "score": 0.0,
    }


def _synthetic_choice(
    field: str,
    value: float,
    evidence: str,
    *,
    confidence: float,
    tolerance_upper: float | None = None,
    tolerance_lower: float | None = None,
) -> dict[str, Any]:
    candidate = {
        "field": field,
        "feature_type": "dimension",
        "value": int(value) if float(value).is_integer() else value,
        "unit": "mm",
        "source": ROLE_SOURCE,
        "evidence": evidence,
        "confidence": confidence,
        "page": 1,
        "position": None,
        "suggested_region": "OCR full text dimension role candidate",
        "tolerance_upper": tolerance_upper,
        "tolerance_lower": tolerance_lower,
    }
    return _choice(candidate, value, field)


def _combined_text(candidates: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for candidate in candidates:
        for key in ("value", "evidence", "suggested_region"):
            value = candidate.get(key)
            if isinstance(value, (str, int, float)):
                parts.append(str(value))
    return "\n".join(parts)


def _load_heights(candidates: list[dict[str, Any]], text: str) -> list[float]:
    heights: list[float] = []
    for candidate in candidates:
        if candidate.get("field") != "load_point":
            continue
        value = candidate.get("value")
        if isinstance(value, dict):
            number = _number(value.get("height"))
            if number is not None:
                heights.append(number)
    for match in re.finditer(r"H[12]\s*(?:=|压缩到|壓縮到)?\s*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE):
        number = _number(match.group(1))
        if number is not None:
            heights.append(number)
    return sorted(set(heights))


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("evidence", "value", "suggested_region", "source")
    )


def _is_surface_roughness_candidate(candidate: dict[str, Any]) -> bool:
    field = str(candidate.get("field") or "")
    if field in {"surface_requirement", "surface", "roughness"}:
        return True
    return bool(_SURFACE_ROUGHNESS_RE.search(_candidate_text(candidate)))


def _has_outer_geometry_anchor(candidate: dict[str, Any]) -> bool:
    return not _is_surface_roughness_candidate(candidate) and (
        _has_diameter_marker(candidate) or _has_outer_tolerance(candidate)
    )


def _has_axis_length_anchor(candidate: dict[str, Any]) -> bool:
    if _is_surface_roughness_candidate(candidate):
        return False
    text = _candidate_text(candidate)
    if re.search(r"(自由长|自由长度|自由高度|FREE\s*LENGTH|\bL0\b|\bLf\b|轴向|兩端)", text, re.IGNORECASE):
        return True
    if str(candidate.get("field") or "") not in {"free_length", "body_length"}:
        return False
    width, height = _position_size(candidate.get("position"))
    return width is not None and height is not None and width >= height * 1.35


def _has_explicit_diameter_role_anchor(candidate: dict[str, Any], field: str) -> bool:
    text = _candidate_text(candidate)
    patterns = {
        "inner_diameter": r"(?:\u5185\u5f84|\u5167\u5f91|\bID\b|\bI\.D\.)",
        "mean_diameter": r"(?:\u4e2d\u5f84|\u4e2d\u5f91|MEAN\s*DIA|AVERAGE\s*DIA)",
    }
    return bool(re.search(patterns.get(field, r"$^"), text, re.IGNORECASE))


def _has_inner_or_mean_dimension_text(text: str) -> bool:
    return bool(
        re.search(
            r"(?:\u5185\u5f84|\u5167\u5f91|\u4e2d\u5f84|\u4e2d\u5f91|\bID\b|\bI\.D\.|MEAN\s*DIA)",
            text,
            re.IGNORECASE,
        )
    )


def _position_size(position: Any) -> tuple[float | None, float | None]:
    if not isinstance(position, dict):
        return None, None
    width = _number(position.get("width"))
    height = _number(position.get("height"))
    if width is not None and height is not None:
        return abs(width), abs(height)

    polygon = position.get("polygon")
    if not isinstance(polygon, list) or len(polygon) < 2:
        return None, None
    points = [
        (float(point[0]), float(point[1]))
        for point in polygon
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]
    if len(points) < 2:
        return None, None
    xs, ys = zip(*points)
    return max(xs) - min(xs), max(ys) - min(ys)


def _has_diameter_marker(candidate: dict[str, Any]) -> bool:
    text = _candidate_text(candidate)
    return bool(
        re.search(
            r"(外径|外徑|OD|O\.D\.|[ΦØ]|直径|直徑|竖排|豎排|vertical|diameter)",
            text,
            re.IGNORECASE,
        )
    )


def _has_outer_tolerance(candidate: dict[str, Any]) -> bool:
    upper = _number(candidate.get("tolerance_upper"))
    lower = _number(candidate.get("tolerance_lower"))
    text = _candidate_text(candidate)
    return (
        (upper == 0 and lower is not None and lower < 0)
        or bool(re.search(r"(上偏差\s*0|0\s*[-−/]\s*0\.\d+|0/-0\.\d+)", text))
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    match = re.search(r"[-−]?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace("−", "-"))
    except ValueError:
        return None


def _rounded_numbers(values: list[float]) -> list[float]:
    return [round(float(value), 3) for value in values]


def _dedupe_choices(choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, float]] = set()
    result: list[dict[str, Any]] = []
    for choice in choices:
        key = (choice["field"], round(float(choice["value"]), 3))
        if key in seen:
            continue
        seen.add(key)
        result.append(choice)
    return result
