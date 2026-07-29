from __future__ import annotations

from typing import Any


END_GRINDING_GROUND = "两端磨削"
END_GRINDING_NOT_GROUND = "两端不磨削"
END_TYPE_TIGHT = "两端并紧"
END_TYPE_NOT_TIGHT = "两端不并紧"


def normalize_end_grinding(value: Any) -> str | None:
    """Map drawing wording for compression spring end grinding to one UI value."""
    text = _text(value)
    if not text:
        return None
    lowered = text.lower().replace("-", "_").replace(" ", "")
    if lowered in {"not_ground", "notground", "unground", "no", "false"}:
        return END_GRINDING_NOT_GROUND
    if lowered in {"ground", "grounded", "yes", "true", "closed_and_ground"}:
        return END_GRINDING_GROUND
    if any(token in text for token in ("不磨", "未磨", "不磨削", "未磨削")):
        return END_GRINDING_NOT_GROUND
    if any(token in text for token in ("磨削", "磨平", "端面磨", "两端磨", "磨")):
        return END_GRINDING_GROUND
    return None


def normalize_end_type(value: Any) -> str | None:
    """Map drawing wording for compression spring end condition to one UI value."""
    text = _text(value)
    if not text:
        return None
    lowered = text.lower().replace("-", "_").replace(" ", "")
    if lowered in {"not_tight", "nottight", "open", "open_end"}:
        return END_TYPE_NOT_TIGHT
    if lowered in {"tight", "closed", "closed_end"}:
        return END_TYPE_TIGHT
    # Check the negative wording first because it contains the positive token.
    if any(token in text for token in ("不并紧", "开口", "开放", "不闭口")):
        return END_TYPE_NOT_TIGHT
    if any(token in text for token in ("两端并紧", "双并紧", "并紧", "双闭口", "闭口", "闭合", "压紧")):
        return END_TYPE_TIGHT
    return None


def normalize_compression_end_conditions(parameters: dict[str, Any]) -> None:
    """Normalize persisted compression end fields while retaining raw evidence."""
    for field, normalizer in (
        ("end_grinding", normalize_end_grinding),
        ("end_type", normalize_end_type),
    ):
        item = parameters.get(field)
        if not isinstance(item, dict):
            continue
        raw_value = item.get("value")
        if raw_value in (None, ""):
            continue
        normalized = normalizer(raw_value)
        if normalized:
            if normalized != raw_value:
                item["raw_value"] = raw_value
            item["value"] = normalized
            item["normalization_status"] = "normalized"
            continue
        item["raw_value"] = raw_value
        item["value"] = None
        item["normalization_status"] = "needs_confirmation"
        item["need_human_review"] = True


def _text(value: Any) -> str:
    return str(value or "").strip()
