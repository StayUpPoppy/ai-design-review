"""Separate supported load evidence from numeric tables before dimension ranking."""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any


_TOLERANCE_TITLE = re.compile(r"未注(?:明)?|未标注|无标(?:示|注)?尺寸|一般公差|通用公差|general\s+tolerances?|un(?:marked|specified)\s+dimensions?", re.I)
_RANGE = re.compile(r"[≥≤<>～~]|大于|小于|尺寸(?:分档|范围)|(?:\d+(?:\.\d+)?)\s*[-—]\s*\d")
_TOLERANCE = re.compile(r"公差|tolerance", re.I)
_HEIGHT = re.compile(r"高度|长度|压缩量|变形量|height|length|deflection", re.I)
_FORCE = re.compile(r"载荷|负荷|力值|荷重|load|force", re.I)
_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_H_SYMBOL = re.compile(rf"(?<![A-Za-z0-9_])H\s*(?:\d+|b)?\s*(?:=|＝|:|：|压缩到)?\s*{_NUMBER}", re.I)
_F_SYMBOL = re.compile(rf"(?<![A-Za-z0-9_])[FP]\s*(?:\d+|b)?\s*(?:=|＝|:|：)\s*{_NUMBER}|(?<![A-Za-z0-9_])[FP](?:\d+|b)\s+{_NUMBER}", re.I)
_FORCE_UNIT = re.compile(rf"{_NUMBER}\s*(?:kN|N|kgf|牛顿|牛)(?![A-Za-z])", re.I)
_DECLARED_FORCE_UNIT = re.compile(r"(?<![A-Za-z])(?:kN|N|kgf|牛顿|牛)(?![A-Za-z])", re.I)
_GENERIC_TABLE = re.compile(r"参数表载荷|(?:载荷表|载荷列|表格|参数表).{0,12}第[一二三四五六七八九十\d]+[行列]", re.I)


def normalize_source_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {key: str(value[key]) for key in ("kind", "table_title", "row_text", "unit_evidence") if value.get(key)}
    headers = value.get("headers")
    if isinstance(headers, list):
        result["headers"] = [str(item) for item in headers]
    elif headers:
        result["headers"] = [str(headers)]
    return result


def classify_load_candidate(candidate: dict[str, Any]) -> tuple[str, str, str]:
    sources = candidate.get("source") or []
    sources = sources if isinstance(sources, list) else [sources]
    if any(re.search(r"human|manual", str(source), re.I) for source in sources):
        return "accepted", "LOAD-HUMAN", "人工输入沿用现有确认机制。"
    context = normalize_source_context(candidate.get("source_context"))
    evidence = str(candidate.get("evidence") or "")
    local = "\n".join([evidence, context.get("table_title", ""), *context.get("headers", []), context.get("row_text", ""), context.get("unit_evidence", "")])
    # Only candidate-local evidence is used. A tolerance table elsewhere on the
    # same page must not suppress an unrelated, genuine load annotation.
    negative = bool(_TOLERANCE_TITLE.search(local) and _RANGE.search(local) and _TOLERANCE.search(local))
    headers = " ".join(context.get("headers", []))
    declared_force_unit = bool(_DECLARED_FORCE_UNIT.search(" ".join([headers, context.get("unit_evidence", "")])))
    table_load = bool(_HEIGHT.search(headers) and _FORCE.search(headers) and re.search(_NUMBER, context.get("row_text", "")))
    annotation_load = bool(_F_SYMBOL.search(evidence) and (_H_SYMBOL.search(evidence) or _FORCE_UNIT.search(evidence) or declared_force_unit))
    sentence_load = bool(not _GENERIC_TABLE.search(evidence) and _HEIGHT.search(evidence) and _FORCE.search(evidence)
                         and re.search(r"当|压缩(?:到|至)|压至|工作|试验|测试|when|compressed|test|working|height", evidence, re.I)
                         and re.search(_NUMBER, evidence) and (_FORCE_UNIT.search(evidence) or _H_SYMBOL.search(evidence) or declared_force_unit))
    positive = table_load or annotation_load or sentence_load
    if negative and positive:
        return "pending", "LOAD-EVIDENCE-CONFLICT", "载荷标注与尺寸公差表证据矛盾，请核对原图归属。"
    if negative:
        return "excluded", "LOAD-TOLERANCE-TABLE", "来自未注尺寸公差表：区间边界及公差不是载荷测试点。"
    if positive:
        return "accepted", "LOAD-EVIDENCE-SUPPORTED", "原图包含明确载荷标注、载荷要求或高度/载荷表头。"
    if any(re.search(r"^(?:cad|dxf|dwg|werk24)$", str(source), re.I) for source in sources):
        return "accepted", "LOAD-STRUCTURED-SOURCE", "来自结构化工程载荷字段。"
    return "pending", "LOAD-EVIDENCE-INSUFFICIENT", "缺少明确载荷标注或对应表头；仅凭数字、自动编号和默认单位不能确定载荷。"


def partition_load_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted, diagnostics = [], []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.get("field") != "load_point":
            accepted.append(candidate)
            continue
        status, code, reason = classify_load_candidate(candidate)
        if status == "accepted":
            accepted.append(candidate)
            continue
        original = _json_safe(deepcopy(candidate))
        digest = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:24]
        candidate_id = f"loadcand_{digest}"
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        diagnostics.append({"candidate_id": candidate_id, "status": status, "original_candidate": original,
                            "page": candidate.get("page", 1), "evidence": str(candidate.get("evidence") or ""),
                            "source_context": normalize_source_context(candidate.get("source_context")),
                            "reason_code": code, "reason": reason})
    return accepted, diagnostics


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
