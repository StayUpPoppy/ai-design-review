from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any


SPRING_TYPE_UNKNOWN = "unknown_spring"


SPRING_TEMPLATES: dict[str, dict[str, Any]] = {
    "compression_spring": {
        "spring_type": "compression_spring",
        "label": "压缩弹簧",
        "fields": [
            {"key": "material", "label": "材料", "required": True},
            {"key": "wire_diameter", "label": "线径", "unit": "mm", "required": True},
            {"key": "outer_diameter", "label": "外径", "unit": "mm", "required": True},
            {"key": "inner_diameter", "label": "内径", "unit": "mm"},
            {"key": "mean_diameter", "label": "中径", "unit": "mm"},
            {"key": "free_length", "label": "自由长度", "unit": "mm", "required": True},
            {"key": "body_length", "label": "弹体长度", "unit": "mm"},
            {"key": "solid_height", "label": "压并高度", "unit": "mm"},
            {"key": "total_coils", "label": "总圈数", "unit": "turns", "required": True},
            {"key": "active_coils", "label": "有效圈数", "unit": "turns"},
            {"key": "end_coils", "label": "端圈数", "unit": "turns"},
            {"key": "support_coils", "label": "支承圈数", "unit": "turns"},
            {"key": "handedness", "label": "旋向", "required": True},
            {"key": "pitch", "label": "节距", "unit": "mm"},
            {"key": "end_type", "label": "端部形式"},
        ],
        "collections": [{"key": "load_points", "label": "载荷点"}],
    },
    "torsion_spring": {
        "spring_type": "torsion_spring",
        "label": "扭转弹簧",
        "fields": [
            {"key": "material", "label": "材料", "required": True},
            {"key": "wire_diameter", "label": "线径", "unit": "mm", "required": True},
            {"key": "outer_diameter", "label": "外径", "unit": "mm"},
            {"key": "inner_diameter", "label": "内径", "unit": "mm"},
            {"key": "mean_diameter", "label": "中径", "unit": "mm", "required": True},
            {"key": "total_coils", "label": "总圈数", "unit": "turns", "required": True},
            {"key": "active_coils", "label": "有效圈数", "unit": "turns"},
            {"key": "handedness", "label": "旋向", "required": True},
            {"key": "coil_body_length", "label": "卷绕体长度", "unit": "mm"},
            {"key": "arm_length", "label": "臂长", "unit": "mm"},
            {"key": "short_arm_length", "label": "短臂长", "unit": "mm"},
            {"key": "long_arm_length", "label": "长臂长", "unit": "mm"},
            {"key": "leg1_length", "label": "第一臂长度", "unit": "mm"},
            {"key": "leg2_length", "label": "第二臂长度", "unit": "mm"},
            {"key": "free_angle", "label": "自由角", "unit": "deg"},
            {"key": "working_angle", "label": "工作角", "unit": "deg"},
            {"key": "leg1_angle", "label": "第一臂角度", "unit": "deg"},
            {"key": "leg2_angle", "label": "第二臂角度", "unit": "deg"},
            {"key": "bend_radius", "label": "折弯半径", "unit": "mm"},
            {"key": "leg_end_type", "label": "臂端形式"},
            {"key": "mandrel_diameter", "label": "芯轴直径", "unit": "mm"},
            {"key": "torque", "label": "扭矩", "unit": "Nmm"},
        ],
        "collections": [{"key": "torque_points", "label": "扭矩点"}],
    },
    "extension_spring": {
        "spring_type": "extension_spring",
        "label": "拉伸弹簧",
        "fields": [
            {"key": "material", "label": "材料", "required": True},
            {"key": "wire_diameter", "label": "线径", "unit": "mm", "required": True},
            {"key": "outer_diameter", "label": "外径", "unit": "mm"},
            {"key": "inner_diameter", "label": "内径", "unit": "mm"},
            {"key": "mean_diameter", "label": "中径", "unit": "mm", "required": True},
            {"key": "free_length", "label": "自由长度", "unit": "mm", "required": True},
            {"key": "body_length", "label": "弹体长度", "unit": "mm"},
            {"key": "total_coils", "label": "总圈数", "unit": "turns", "required": True},
            {"key": "active_coils", "label": "有效圈数", "unit": "turns"},
            {"key": "hook_type", "label": "钩型"},
            {"key": "hook_outer_diameter", "label": "钩环外径", "unit": "mm"},
            {"key": "hook_inner_diameter", "label": "钩环内径", "unit": "mm"},
            {"key": "hook_gap", "label": "钩口间隙", "unit": "mm"},
            {"key": "hook1_type", "label": "左端钩型"},
            {"key": "hook2_type", "label": "右端钩型"},
            {"key": "hook1_length", "label": "左端钩长度", "unit": "mm"},
            {"key": "hook2_length", "label": "右端钩长度", "unit": "mm"},
            {"key": "hook1_outer_diameter", "label": "左钩外径", "unit": "mm"},
            {"key": "hook2_outer_diameter", "label": "右钩外径", "unit": "mm"},
            {"key": "hook1_inner_diameter", "label": "左钩内径", "unit": "mm"},
            {"key": "hook2_inner_diameter", "label": "右钩内径", "unit": "mm"},
            {"key": "hook1_opening", "label": "左钩开口", "unit": "mm"},
            {"key": "hook2_opening", "label": "右钩开口", "unit": "mm"},
            {"key": "hook_orientation", "label": "钩环方向"},
            {"key": "center_to_center_length", "label": "中心距", "unit": "mm"},
            {"key": "initial_tension", "label": "初拉力", "unit": "N"},
        ],
        "collections": [{"key": "load_points", "label": "拉力点"}],
    },
    "retaining_ring": {
        "spring_type": "retaining_ring",
        "label": "卡簧/挡圈",
        "fields": [
            {"key": "material", "label": "材料", "required": True},
            {"key": "ring_type", "label": "类型"},
            {"key": "wire_diameter", "label": "线径", "unit": "mm"},
            {"key": "thickness", "label": "厚度", "unit": "mm"},
            {"key": "outer_diameter", "label": "外径", "unit": "mm"},
            {"key": "inner_diameter", "label": "内径", "unit": "mm", "required": True},
            {"key": "free_diameter", "label": "自由状态直径", "unit": "mm"},
            {"key": "opening_width", "label": "开口宽度", "unit": "mm"},
            {"key": "gap_width", "label": "缺口宽度", "unit": "mm"},
            {"key": "notch_depth", "label": "缺口深度", "unit": "mm"},
            {"key": "groove_diameter", "label": "槽径", "unit": "mm"},
            {"key": "groove_width", "label": "槽宽", "unit": "mm"},
            {"key": "lug_hole_diameter", "label": "耳孔直径", "unit": "mm"},
            {"key": "lug_center_distance", "label": "耳孔中心距", "unit": "mm"},
            {"key": "opening_angle", "label": "开口角度", "unit": "deg"},
            {"key": "section_width", "label": "剖面宽度", "unit": "mm"},
            {"key": "section_height", "label": "剖面高度", "unit": "mm"},
            {"key": "chamfer", "label": "倒角"},
            {"key": "corner_radius", "label": "圆角R", "unit": "mm"},
        ],
        "collections": [],
    },
    SPRING_TYPE_UNKNOWN: {
        "spring_type": SPRING_TYPE_UNKNOWN,
        "label": "未知弹簧",
        "fields": [
            {"key": "material", "label": "材料"},
            {"key": "wire_diameter", "label": "线径", "unit": "mm"},
            {"key": "outer_diameter", "label": "外径", "unit": "mm"},
            {"key": "inner_diameter", "label": "内径", "unit": "mm"},
            {"key": "mean_diameter", "label": "中径", "unit": "mm"},
            {"key": "free_length", "label": "自由长度", "unit": "mm"},
            {"key": "body_length", "label": "弹体长度", "unit": "mm"},
            {"key": "total_coils", "label": "总圈数", "unit": "turns"},
            {"key": "handedness", "label": "旋向"},
            {"key": "pitch", "label": "节距", "unit": "mm"},
            {"key": "arm_length", "label": "臂长", "unit": "mm"},
            {"key": "working_angle", "label": "工作角", "unit": "deg"},
            {"key": "hook_type", "label": "钩型"},
            {"key": "opening_width", "label": "开口宽度", "unit": "mm"},
            {"key": "thickness", "label": "厚度", "unit": "mm"},
        ],
        "collections": [{"key": "load_points", "label": "载荷点"}],
    },
}


FIELD_LABELS = {
    field["key"]: field.get("label", field["key"])
    for template in SPRING_TEMPLATES.values()
    for field in template["fields"]
}


def classify_spring_type(candidates: list[dict[str, Any]], file_info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify spring type from title text, recognized fields, and drawing hints."""
    scores = {
        "compression_spring": 0.0,
        "torsion_spring": 0.0,
        "extension_spring": 0.0,
        "retaining_ring": 0.0,
    }
    evidence: list[dict[str, Any]] = []
    text = _combined_text(candidates, file_info)

    def add(kind: str, points: float, reason: str, source: str = "text") -> None:
        scores[kind] += points
        evidence.append({"spring_type": kind, "points": points, "reason": reason, "source": source})

    keyword_rules = [
        ("retaining_ring", 1.1, ("内卡簧", "外卡簧", "卡簧", "挡圈", "扣环", "止动环", "孔用", "轴用", "retaining ring", "circlip")),
        ("extension_spring", 1.0, ("拉伸弹簧", "拉簧", "圆柱螺旋拉伸", "extension spring")),
        ("torsion_spring", 0.95, ("扭转弹簧", "扭簧", "扭矩", "torsion spring")),
        ("compression_spring", 0.95, ("压缩弹簧", "压簧", "压力弹簧", "compression spring")),
    ]
    for kind, points, words in keyword_rules:
        matched = _first_contains(text, words)
        if matched:
            add(kind, points, f"keyword:{matched}", "title_or_ocr")

    if re.search(r"\bH[12]\b|\bF[12]\b", text, re.IGNORECASE):
        add("compression_spring", 0.85, "load point labels H/F", "dimension_text")
    if re.search(r"\b\d+(?:\.\d+)?\s*N\b", text, re.IGNORECASE):
        add("compression_spring", 0.25, "force value present", "dimension_text")
    if _has_feature_angle(text):
        add("torsion_spring", 0.28, "angle dimensions present", "dimension_text")
    if _first_contains(text, ("臂长", "短臂", "长臂", "展开长度", "工作角", "自由角", "第一角")):
        add("torsion_spring", 0.32, "arm or angle wording", "dimension_text")
    if _first_contains(text, ("钩", "吊环", "挂钩", "钩环", "拉力", "初拉力")):
        add("extension_spring", 0.38, "hook or pull wording", "dimension_text")
    if _first_contains(text, ("缺口", "开口", "A-A", "a-a", "剖面", "截面")):
        add("retaining_ring", 0.38, "slot/section wording", "dimension_text")

    fields = {str(candidate.get("field") or "") for candidate in candidates}
    if "load_point" in fields:
        add("compression_spring", 0.45, "recognized load_point field", "candidate_field")
    if fields & {
        "torque",
        "free_angle",
        "working_angle",
        "arm_length",
        "short_arm_length",
        "long_arm_length",
        "leg1_length",
        "leg2_length",
        "leg1_angle",
        "leg2_angle",
        "bend_radius",
        "mandrel_diameter",
    }:
        add("torsion_spring", 0.45, "recognized torsion field", "candidate_field")
    if fields & {
        "hook_type",
        "hook_outer_diameter",
        "hook_inner_diameter",
        "hook_gap",
        "hook1_type",
        "hook2_type",
        "hook1_length",
        "hook2_length",
        "hook1_opening",
        "hook2_opening",
        "center_to_center_length",
        "initial_tension",
    }:
        add("extension_spring", 0.45, "recognized extension field", "candidate_field")
    if fields & {
        "ring_type",
        "opening_width",
        "gap_width",
        "notch_depth",
        "section_width",
        "section_height",
        "thickness",
        "groove_diameter",
        "groove_width",
        "lug_hole_diameter",
        "lug_center_distance",
        "opening_angle",
    }:
        add("retaining_ring", 0.45, "recognized retaining-ring field", "candidate_field")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = min(0.98, best_score / 1.4) if best_score else 0.0
    if best_score < 0.45 or best_score - runner_up < 0.12:
        best_type = SPRING_TYPE_UNKNOWN
        confidence = min(confidence, 0.45)

    return {
        "spring_type": best_type,
        "label": template_for(best_type)["label"],
        "confidence": round(confidence, 3),
        "scores": {key: round(value, 3) for key, value in scores.items()},
        "evidence": sorted(evidence, key=lambda item: item["points"], reverse=True)[:8],
        "need_human_review": best_type == SPRING_TYPE_UNKNOWN or confidence < 0.72,
    }


def template_for(spring_type: str | None) -> dict[str, Any]:
    template = SPRING_TEMPLATES.get(str(spring_type or ""), SPRING_TEMPLATES[SPRING_TYPE_UNKNOWN])
    return deepcopy(template)


def template_field_keys(spring_type: str | None) -> list[str]:
    return [field["key"] for field in template_for(spring_type)["fields"]]


def required_field_keys(spring_type: str | None) -> list[str]:
    return [
        field["key"]
        for field in template_for(spring_type)["fields"]
        if field.get("required")
    ]


def field_default_unit(spring_type: str | None, field: str) -> str | None:
    for item in template_for(spring_type)["fields"]:
        if item["key"] == field:
            return item.get("unit")
    return None


def _combined_text(candidates: list[dict[str, Any]], file_info: dict[str, Any] | None) -> str:
    parts: list[str] = []
    if file_info:
        path = file_info.get("path")
        if path:
            parts.append(Path(str(path)).name)
        if file_info.get("pdf_text"):
            parts.append(str(file_info["pdf_text"]))
    for candidate in candidates:
        parts.extend(
            str(candidate.get(key) or "")
            for key in ("field", "value", "evidence", "suggested_region")
        )
    return "\n".join(parts)


def _first_contains(text: str, words: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for word in words:
        if word.lower() in lowered:
            return word
    return None


def _has_feature_angle(text: str) -> bool:
    for match in re.findall(r"(\d+(?:\.\d+)?)\s*(?:°|deg|DEG)(?!\s*C)", text, re.IGNORECASE):
        value = float(match)
        if value not in {1.0, 360.0} and 2 <= value <= 180:
            return True
    return False
