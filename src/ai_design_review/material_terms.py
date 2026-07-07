from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .io_utils import project_path, read_json


DEFAULT_MATERIAL_TERMS_PATH = project_path("config", "material_terms.json")


def normalize_material(value: Any, terms_config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = str(value or "").strip()
    if not raw:
        return _result("", "", "unmatched", "none", 0.0, "未识别到材质内容。")

    config = terms_config or load_material_terms()
    terms = [str(item).strip() for item in config.get("terms", []) if str(item).strip()]
    term_set = set(terms)
    if raw in term_set:
        return _result(raw, raw, "matched", "material_terms", 1.0, "命中标准材质。")

    normalized_raw = normalize_material_key(raw)
    normalized_terms: dict[str, list[str]] = {}
    for term in terms:
        normalized_terms.setdefault(normalize_material_key(term), []).append(term)

    matches = normalized_terms.get(normalized_raw, [])
    if len(matches) == 1:
        return _result(raw, matches[0], "matched", "material_terms", 0.98, "清洗后唯一命中标准材质。")
    if len(matches) > 1:
        return _result(raw, "", "unmatched", "none", 0.0, "清洗后命中多个标准材质，保持图纸原文。")
    return _result(raw, "", "unmatched", "none", 0.0, "未命中材质标准表，保持图纸原文。")


@lru_cache(maxsize=1)
def load_material_terms(path: str | Path | None = None) -> dict[str, Any]:
    terms_path = Path(path) if path else DEFAULT_MATERIAL_TERMS_PATH
    if not terms_path.exists():
        return {"terms": [], "version": "missing"}
    payload = read_json(terms_path)
    payload.setdefault("terms", [])
    return payload


def normalize_material_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]", "", text)


def _result(
    raw: str,
    standard: str,
    status: str,
    source: str,
    confidence: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "raw_value": raw,
        "standard_value": standard,
        "value": standard or raw,
        "normalization_status": status,
        "normalization_source": source,
        "normalization_confidence": round(confidence, 3),
        "normalization_reason": reason,
    }
