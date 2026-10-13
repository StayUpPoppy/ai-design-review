from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any


TECHNICAL_REQUIREMENT_TYPES = (
    "surface",
    "surface_roughness",
    "hardness",
    "heat_treatment",
    "salt_spray",
    "environmental",
    "lifetime",
    "process",
    "other",
)

TECHNICAL_REQUIREMENT_TYPE_LABELS = {
    "surface": "表面处理",
    "surface_roughness": "表面粗糙度",
    "hardness": "硬度要求",
    "heat_treatment": "热处理",
    "salt_spray": "盐雾试验",
    "environmental": "环保要求",
    "lifetime": "寿命要求",
    "process": "工艺要求",
    "other": "其他要求",
}

TECHNICAL_REQUIREMENTS_TITLE = "技术要求"

# Strip labels only at the start and only when their boundary is explicit.
# These are presentation labels, never arbitrary words in the process body.
_PREFIX_TYPES = {
    "热处理要求": "heat_treatment", "热处理": "heat_treatment",
    "盐雾要求": "salt_spray", "盐雾试验": "salt_spray", "盐雾测试": "salt_spray",
    "表面处理要求": "surface", "表面处理": "surface",
    "硬度要求": "hardness", "材料环保要求": "environmental", "环保要求": "environmental",
    "寿命要求": "lifetime", "寿命测试": "lifetime",
    "工艺要求": "process", "其他要求": "other",
}
_PREFIX_PATTERN = re.compile(r"^(" + "|".join(_PREFIX_TYPES) + r")\s*(?::\s*|(?=[+\-±]?\d))")


def normalize_technical_text(value: Any) -> str:
    """Formatting normalization without changing engineering tokens or case."""
    text = str(value or "").strip()
    text = "".join(chr(ord(char) - 0xFEE0) if 0xFF01 <= ord(char) <= 0xFF5E else char for char in text)
    text = text.replace("\u3000", " ").replace("℃", "°C").replace("µm", "μm")
    text = text.replace("。", ".").replace("，", ",").replace("；", ";").replace("−", "-")
    return re.sub(r"\s+", " ", text).strip()


def technical_requirement_body(value: Any) -> tuple[str, str | None]:
    text = normalize_technical_text(value)
    text = re.sub(r"^\d+\s*[.、)]\s*(?=[^\d\s])", "", text)
    kind = None
    while match := _PREFIX_PATTERN.match(text):
        label_kind = _PREFIX_TYPES[match[1]]
        if label_kind not in {"other", "process"} or kind is None:
            kind = label_kind
        text = text[match.end():].strip()
    return text.rstrip(".").strip(), kind


def _comparison_text(value: Any) -> str:
    text = normalize_technical_text(value).rstrip(".")
    # Keep whitespace separating numbers/words: '1 6' must never become '16'.
    text = re.sub(r"(?<![A-Za-z0-9])\s+|\s+(?![A-Za-z0-9])", "", text)
    # Explicit symbol/unit boundaries commonly acquire spaces during OCR.
    text = re.sub(r"(?<![A-Za-z0-9_])(Ra|Hb|H\d+|F\d+)\s+(?=[+\-±]?\d)", r"\1", text)
    text = re.sub(r"(?<=\d)\s+(?=(?:mm|cm|μm|min|MPa|N|h|s|kg)(?![A-Za-z0-9_]))", "", text)
    return text


def technical_requirement_equivalence_key(item: dict[str, Any]) -> tuple[str, str, str]:
    body, prefix_kind = technical_requirement_body(_single_line_technical_requirement_content(technical_requirement_output_content(item)))
    kind = prefix_kind or normalize_technical_requirement_type(item.get("type"), default="other") or "other"
    if kind == "process":
        kind = "other"
    return kind, _comparison_text(body), _comparison_text(item.get("application_scope"))


def format_technical_requirement(item: dict[str, Any]) -> str:
    content = _single_line_technical_requirement_content(technical_requirement_output_content(item))
    if not content:
        return ""
    _, prefix_kind = technical_requirement_body(content)
    kind = prefix_kind or normalize_technical_requirement_type(item.get("type"), default="other") or "other"
    # Preserve the user's punctuation and units; normalization is for comparison.
    text = re.sub(r"^\d+\s*[.．、)]\s*(?=[^\d\s])", "", content)
    pattern = re.compile(r"^(" + "|".join(_PREFIX_TYPES) + r")\s*(?:[:：]\s*|(?=[+\-±]?\d))")
    while match := pattern.match(text):
        text = text[match.end():].strip()
    if not text:
        return ""
    scope = str(item.get("application_scope") or "").strip()
    if scope and scope not in text:
        text = f"{text.rstrip('。.')}（作用范围：{scope}）"
    if kind == "surface_roughness":
        return text
    return f"{TECHNICAL_REQUIREMENT_TYPE_LABELS.get(kind, '其他要求')}：{text}"


def strip_technical_requirements_title(text: Any) -> str:
    """Remove only a standalone leading legacy title, never note numbering."""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    first_line, separator, rest = normalized.partition("\n")
    if first_line.strip().rstrip("：:") == TECHNICAL_REQUIREMENTS_TITLE:
        body = rest.strip() if separator else ""
        return body
    return normalized


def ensure_technical_requirements_title(text: Any) -> str:
    """Legacy helper retained for callers outside the generation path."""
    body = strip_technical_requirements_title(text)
    return f"{TECHNICAL_REQUIREMENTS_TITLE}\n{body}" if body else ""


def build_technical_requirements_text(requirements: list[Any]) -> str:
    """Format ordered generation notes as one SolidWorks-ready text block.

    The structured array remains the source of truth.  This deterministic
    projection only makes it easier for a drawing worker to put the complete
    note block into a title block without knowing the internal type codes.
    """

    lines: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for item in requirements:
        if not isinstance(item, dict):
            continue
        content = format_technical_requirement(item)
        key = technical_requirement_equivalence_key(item)
        if not content or key in seen:
            continue
        seen.add(key)
        lines.append(f"{len(lines) + 1}.{content}")
    return "\n".join(lines)


def technical_requirement_output_content(item: dict[str, Any]) -> str:
    """Keep original numbering in metadata, not inside a second output number."""
    content = str(item.get("content") or "").strip()
    # A clear integer list prefix is presentation metadata. Decimal values and
    # an integer followed by another number are deliberately left untouched.
    return re.sub(r"^\s*[0-9０-９]+\s*[.．、)）]\s*(?=[^0-9０-９\s])", "", content, count=1)


def _single_line_technical_requirement_content(value: Any) -> str:
    content = str(value or "").strip()
    if not content:
        return ""
    content = re.sub(r"(?:\s*(?:\r\n?|\n)\s*)+", "；", content)
    content = re.sub(r"[\t ]+", " ", content).strip()
    return re.sub(r"；{2,}", "；", content)


_TYPE_ALIASES = {
    "surface_requirement": "surface",
    "surface_treatment": "surface",
    "roughness": "surface_roughness",
    "surface_finish": "surface_roughness",
    "表面粗糙度": "surface_roughness",
    "hardness_requirement": "hardness",
    "heat": "heat_treatment",
    "heat-treatment": "heat_treatment",
    "salt": "salt_spray",
    "salt_spray_test": "salt_spray",
    "environment": "environmental",
    "environmental_requirement": "environmental",
    "life": "lifetime",
    "process_requirement": "process",
}


def new_technical_requirement_id() -> str:
    return f"techreq_{uuid.uuid4().hex}"


def normalize_technical_requirement_type(value: Any, *, default: str | None = None) -> str | None:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    normalized = _TYPE_ALIASES.get(normalized, normalized)
    if normalized in TECHNICAL_REQUIREMENT_TYPES:
        return normalized
    return default


def technical_requirement_confirmation_key(requirement_id: str) -> str:
    return f"technical_requirement_{requirement_id}"


def ensure_technical_requirement_ids(review: dict[str, Any]) -> bool:
    """Add stable internal IDs to legacy technical requirements in-place.

    Legacy IDs are deterministic for unchanged input, so a read-only load does not
    produce a different identifier on every request. Once the review is saved the
    identifier remains stable even if the requirement content is edited later.
    """

    requirements = review.get("technical_requirements")
    if not isinstance(requirements, list):
        if requirements in (None, ""):
            review["technical_requirements"] = []
            return requirements is not None
        return False

    changed = False
    used: set[str] = set()
    confirmations = review.setdefault("manual_confirmations", {})
    if not isinstance(confirmations, dict):
        confirmations = {}
        review["manual_confirmations"] = confirmations
        changed = True

    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            continue
        requirement_id = _valid_requirement_id(item.get("requirement_id"))
        if not requirement_id or requirement_id in used:
            requirement_id = _legacy_technical_requirement_id(item, index, used)
            item["requirement_id"] = requirement_id
            changed = True
        used.add(requirement_id)

        stable_key = technical_requirement_confirmation_key(requirement_id)
        legacy_key = f"technical_{index}"
        if stable_key not in confirmations and isinstance(confirmations.get(legacy_key), dict):
            confirmations[stable_key] = dict(confirmations[legacy_key])
            confirmations[stable_key]["requirement_id"] = requirement_id
            changed = True
    return changed


def technical_requirement_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_id": str(item.get("requirement_id") or ""),
        "type": normalize_technical_requirement_type(item.get("type"), default="other"),
        "content": str(item.get("content") or "").strip(),
        "need_human_review": bool(item.get("need_human_review", True)),
    }


def canonical_technical_requirement_key(requirement_type: Any, content: Any) -> tuple[str, str]:
    kind, body, _ = technical_requirement_equivalence_key({"type": requirement_type, "content": content})
    return kind, body


def technical_requirements_are_duplicates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Output equivalence is independent of recognition occurrence identity."""
    return bool(str(left.get("content") or "").strip()) and technical_requirement_equivalence_key(left) == technical_requirement_equivalence_key(right)


def _valid_requirement_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 96 or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return None
    return text


def _legacy_technical_requirement_id(item: dict[str, Any], index: int, used: set[str]) -> str:
    seed = "|".join(
        (
            str(index),
            str(item.get("type") or "other").strip(),
            str(item.get("content") or "").strip(),
            str(item.get("page") or ""),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    candidate = f"techreq_{digest}"
    suffix = 2
    while candidate in used:
        candidate = f"techreq_{digest}_{suffix}"
        suffix += 1
    return candidate
