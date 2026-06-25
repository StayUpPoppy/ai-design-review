from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .io_utils import project_path, read_json


DEFAULT_SURFACE_TERMS_PATH = project_path("config", "surface_terms.json")
DEFAULT_QWEN_MODEL = "qwen3.7-plus"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_AUTO_CONFIDENCE_THRESHOLD = 0.85


DEFAULT_AUTO_ALIASES = {
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


HIGH_RISK_BROAD_TERMS = {
    "喷塑",
    "电泳",
    "电泳漆",
    "电泳涂装",
    "油漆",
    "涂漆",
    "喷漆",
    "锌",
    "黑",
    "白",
    "蓝",
    "彩",
}


SURFACE_LABEL_RE = re.compile(r"^(?:表面处理|表面處理|表面要求|外观要求|外觀要求)\s*[:：]?\s*")


SurfaceLlmDecider = Callable[[dict[str, Any]], dict[str, Any]]


def normalize_surface_requirement(
    value: Any,
    terms_config: dict[str, Any] | None = None,
    llm_decider: SurfaceLlmDecider | None = None,
    enable_llm: bool | None = None,
) -> dict[str, Any]:
    raw = _clean_raw_text(value)
    if not raw:
        return _result("", "", "unmatched", "none", 0.0, [], "未识别到表面处理内容。")

    config = terms_config or load_surface_terms()
    terms = [str(item).strip() for item in config.get("terms", []) if str(item).strip()]
    auto_aliases = _auto_aliases(config)
    term_set = set(terms)
    normalized_terms = {_normalize_key(term): term for term in terms}

    alias_value = _match_alias(raw, auto_aliases, term_set, normalized_terms)
    if alias_value:
        return _result(
            raw,
            alias_value,
            "alias_matched",
            "alias",
            0.96,
            _candidate_terms(alias_value, terms),
            f"命中自动别名：{raw}",
        )

    if raw in term_set:
        return _result(raw, raw, "matched", "rule", 0.98, _candidate_terms(raw, terms), "命中标准术语。")

    normalized_raw = _normalize_key(raw)
    if normalized_raw in normalized_terms:
        standard = normalized_terms[normalized_raw]
        return _result(raw, standard, "matched", "rule", 0.94, _candidate_terms(standard, terms), "去符号后命中标准术语。")

    candidates = _suggest_terms(raw, terms, limit=8)
    high_risk = _is_high_risk_input(raw)
    if candidates and not high_risk and _llm_enabled(enable_llm):
        llm_result = _decide_with_llm(raw, candidates, llm_decider)
        accepted = _accepted_llm_standard(llm_result, candidates)
        if accepted:
            return _result(
                raw,
                accepted["standard_content"],
                "llm_auto_matched",
                "qwen",
                accepted["confidence"],
                candidates,
                accepted["reason"],
            )

    reason = "规则和 Qwen 未给出可靠标准术语，保持图纸原文。"
    if high_risk:
        reason = "命中高风险大类词，缺少颜色或细分工艺，保持图纸原文。"
    return _result(raw, "", "unmatched", "none", 0.0, candidates, reason)


@lru_cache(maxsize=1)
def load_surface_terms(path: str | Path | None = None) -> dict[str, Any]:
    terms_path = Path(path) if path else DEFAULT_SURFACE_TERMS_PATH
    if not terms_path.exists():
        return {"terms": [], "auto_aliases": DEFAULT_AUTO_ALIASES, "aliases": DEFAULT_AUTO_ALIASES, "version": "missing"}
    payload = read_json(terms_path)
    payload.setdefault("terms", [])
    payload.setdefault("aliases", {})
    payload.setdefault("auto_aliases", payload.get("aliases", {}))
    return payload


def _clean_raw_text(value: Any) -> str:
    text = str(value or "").strip()
    text = SURFACE_LABEL_RE.sub("", text).strip()
    text = re.sub(r"\s+", "", text)
    text = text.strip("：:;；,，。|")
    return text


def _auto_aliases(config: dict[str, Any]) -> dict[str, str]:
    configured = config.get("auto_aliases") or config.get("aliases") or {}
    return {**DEFAULT_AUTO_ALIASES, **{str(k): str(v) for k, v in configured.items()}}


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


def _valid_standard(standard: str, term_set: set[str], normalized_terms: dict[str, str]) -> str | None:
    if standard in term_set:
        return standard
    return normalized_terms.get(_normalize_key(standard))


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


def _is_high_risk_input(raw: str) -> bool:
    normalized = _normalize_key(raw)
    return normalized in {_normalize_key(term) for term in HIGH_RISK_BROAD_TERMS}


def _llm_enabled(enable_llm: bool | None) -> bool:
    if enable_llm is not None:
        return enable_llm
    flag = os.getenv("QWEN_SURFACE_NORMALIZER", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _decide_with_llm(raw: str, candidates: list[dict[str, Any]], llm_decider: SurfaceLlmDecider | None) -> dict[str, Any]:
    payload = {
        "raw_content": raw,
        "standard_candidates": candidates,
        "confidence_threshold": _confidence_threshold(),
        "risk": {
            "high_risk_broad_term": False,
            "blocked_reason": "",
        },
        "instruction": "只能从 standard_candidates 里选择；不确定时返回 unmatched。",
    }
    if llm_decider:
        return llm_decider(payload) or {}
    return _qwen_surface_decider(payload)


def _accepted_llm_standard(llm_result: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    action = str(llm_result.get("action") or "").strip().lower()
    standard = str(llm_result.get("standard_content") or "").strip()
    confidence = _float_or_zero(llm_result.get("confidence"))
    candidate_terms = {str(item.get("term") or "").strip() for item in candidates}
    if action not in {"auto_match", "match", "matched"}:
        return None
    if not standard or standard not in candidate_terms:
        return None
    if confidence < _confidence_threshold():
        return None
    return {
        "standard_content": standard,
        "confidence": confidence,
        "reason": str(llm_result.get("reason") or "Qwen 高置信选择标准术语。"),
    }


def _qwen_surface_decider(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not _configured(api_key):
        return {"action": "unmatched", "reason": "Qwen API key is not configured."}

    import httpx

    model = os.getenv("QWEN_SURFACE_MODEL") or os.getenv("QWEN_MODEL") or DEFAULT_QWEN_MODEL
    base_url = (os.getenv("QWEN_BASE_URL") or DEFAULT_QWEN_BASE_URL).rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    prompt = _surface_prompt(payload)
    request = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    timeout = float(os.getenv("QWEN_SURFACE_TIMEOUT_SECONDS", "20"))
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=request,
            )
            if response.status_code in {400, 422} and "response_format" in response.text:
                request.pop("response_format", None)
                response = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=request,
                )
            response.raise_for_status()
            content = _message_content(response.json())
            return _parse_json_object(content)
    except Exception as exc:
        return {"action": "unmatched", "reason": f"Qwen surface normalization failed: {type(exc).__name__}: {exc}"}


def _surface_prompt(payload: dict[str, Any]) -> str:
    return (
        "你是弹簧图纸表面处理术语标准化助手。"
        "你只能从 standard_candidates 的 term 中选择标准术语，不能自造术语。"
        "如果原文缺少颜色、材料或细分工艺导致不确定，返回 unmatched。"
        "只输出严格 JSON："
        '{"action":"auto_match|unmatched","standard_content":"","confidence":0.0,"reason":""}\n'
        f"输入：{json.dumps(payload, ensure_ascii=False)}"
    )


def _message_content(raw_response: dict[str, Any]) -> Any:
    choices = raw_response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or ""


def _parse_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        return json.loads(match.group(0))


def _configured(value: str | None) -> bool:
    return bool(value and value.strip() and "replace-with" not in value)


def _confidence_threshold() -> float:
    return _float_or_zero(os.getenv("QWEN_SURFACE_CONFIDENCE_THRESHOLD")) or LLM_AUTO_CONFIDENCE_THRESHOLD


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _result(
    raw: str,
    standard: str,
    status: str,
    source: str,
    confidence: float,
    candidates: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return {
        "raw_content": raw,
        "standard_content": standard,
        "content": standard or raw,
        "normalization_status": status,
        "normalization_source": source,
        "normalization_confidence": round(confidence, 3),
        "normalization_reason": reason,
        "standard_candidates": candidates,
        "need_human_review": False,
    }
