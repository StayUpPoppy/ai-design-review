from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .io_utils import project_path, read_json


DEFAULT_SURFACE_TERMS_PATH = project_path("config", "surface_terms.json")


DEFAULT_ALIASES = {
    "镀锌五彩": "电镀-镀彩锌",
    "五彩锌": "电镀-镀彩锌",
    "镀彩锌": "电镀-镀彩锌",
    "彩锌": "电镀-镀彩锌",
    "镀锌": "电镀-镀锌",
    "镀白锌": "电镀-镀白锌",
    "白锌": "电镀-镀白锌",
    "镀蓝锌": "电镀-镀蓝锌",
    "蓝锌": "电镀-镀蓝锌",
    "达克罗": "达克罗",
    "发黑": "发黑",
    "发蓝": "发蓝",
    "磷化": "磷化",
}


SURFACE_LABEL_RE = re.compile(r"^(?:表面处理|表面處理|表面要求|外观要求|外觀要求)\s*[:：]?\s*")


def normalize_surface_requirement(value: Any, terms_config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = _clean_raw_text(value)
    if not raw:
        return _result("", "", "unmatched", 0.0, [])

    config = terms_config or load_surface_terms()
    terms = [str(item).strip() for item in config.get("terms", []) if str(item).strip()]
    aliases = {**DEFAULT_ALIASES, **{str(k): str(v) for k, v in (config.get("aliases") or {}).items()}}
    term_set = set(terms)
    normalized_terms = {_normalize_key(term): term for term in terms}

    alias_value = _match_alias(raw, aliases, term_set, normalized_terms)
    if alias_value:
        return _result(raw, alias_value, "alias_matched", 0.96, _candidate_terms(alias_value, terms))

    if raw in term_set:
        return _result(raw, raw, "matched", 0.98, _candidate_terms(raw, terms))

    normalized_raw = _normalize_key(raw)
    if normalized_raw in normalized_terms:
        standard = normalized_terms[normalized_raw]
        return _result(raw, standard, "matched", 0.94, _candidate_terms(standard, terms))

    candidates = _suggest_terms(raw, terms, limit=5)
    if candidates and candidates[0]["score"] >= 0.82:
        standard = candidates[0]["term"]
        return _result(raw, standard, "suggested", candidates[0]["score"], candidates)

    return _result(raw, "", "unmatched", 0.0, candidates)


@lru_cache(maxsize=1)
def load_surface_terms(path: str | Path | None = None) -> dict[str, Any]:
    terms_path = Path(path) if path else DEFAULT_SURFACE_TERMS_PATH
    if not terms_path.exists():
        return {"terms": [], "aliases": DEFAULT_ALIASES, "version": "missing"}
    payload = read_json(terms_path)
    payload.setdefault("terms", [])
    payload.setdefault("aliases", {})
    return payload


def _clean_raw_text(value: Any) -> str:
    text = str(value or "").strip()
    text = SURFACE_LABEL_RE.sub("", text).strip()
    text = re.sub(r"\s+", "", text)
    text = text.strip("：:;；,，。|")
    return text


def _match_alias(
    raw: str,
    aliases: dict[str, str],
    term_set: set[str],
    normalized_terms: dict[str, str],
) -> str | None:
    if raw in aliases:
        return _valid_standard(aliases[raw], term_set, normalized_terms)
    normalized_raw = _normalize_key(raw)
    for alias, standard in aliases.items():
        if _normalize_key(alias) == normalized_raw:
            return _valid_standard(standard, term_set, normalized_terms)
    return None


def _valid_standard(standard: str, term_set: set[str], normalized_terms: dict[str, str]) -> str:
    if standard in term_set:
        return standard
    return normalized_terms.get(_normalize_key(standard), standard)


def _normalize_key(value: str) -> str:
    return re.sub(r"[\s\-_/\\（）()【】\[\]{}:：;；,，。.+＋]", "", value).lower()


def _suggest_terms(raw: str, terms: list[str], limit: int) -> list[dict[str, Any]]:
    normalized_raw = _normalize_key(raw)
    if not normalized_raw:
        return []
    scored: list[dict[str, Any]] = []
    for term in terms:
        normalized_term = _normalize_key(term)
        score = _similarity(normalized_raw, normalized_term)
        if normalized_raw in normalized_term or normalized_term in normalized_raw:
            score = max(score, min(len(normalized_raw), len(normalized_term)) / max(len(normalized_raw), len(normalized_term)))
        if score >= 0.45:
            scored.append({"term": term, "score": round(score, 3)})
    return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_chars = set(left)
    right_chars = set(right)
    overlap = len(left_chars & right_chars)
    union = len(left_chars | right_chars)
    return overlap / union if union else 0.0


def _candidate_terms(primary: str, terms: list[str]) -> list[dict[str, Any]]:
    candidates = [{"term": primary, "score": 1.0}] if primary else []
    seen = {primary}
    for item in _suggest_terms(primary, terms, limit=5):
        if item["term"] not in seen:
            candidates.append(item)
            seen.add(item["term"])
    return candidates[:5]


def _result(
    raw: str,
    standard: str,
    status: str,
    confidence: float,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "raw_content": raw,
        "standard_content": standard,
        "content": standard or raw,
        "normalization_status": status,
        "normalization_confidence": round(confidence, 3),
        "standard_candidates": candidates,
        "need_human_review": status in {"suggested", "unmatched"},
    }
