from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

from .llm_standardization import normalize_llm_standardization_results
from .spring_templates import template_field_keys
from .standard_knowledge import retrieve_standard_chunks


DEFAULT_LLM_STANDARDIZATION_MODEL = "qwen3.7-plus"
DEFAULT_LLM_STANDARDIZATION_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class LLMStandardizationError(RuntimeError):
    """Raised when the LLM standardization engine cannot return usable JSON."""


CompletionFn = Callable[[dict[str, Any]], Any]


class LLMStandardizationEngine:
    """Generate review-only standardization suggestions from RAG chunks."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        completion_fn: CompletionFn | None = None,
    ):
        self.api_key = api_key or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self.model = model or os.getenv("LLM_STANDARDIZATION_MODEL") or os.getenv("QWEN_MODEL") or DEFAULT_LLM_STANDARDIZATION_MODEL
        self.base_url = (
            base_url
            or os.getenv("LLM_STANDARDIZATION_BASE_URL")
            or os.getenv("QWEN_BASE_URL")
            or DEFAULT_LLM_STANDARDIZATION_BASE_URL
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(os.getenv("LLM_STANDARDIZATION_TIMEOUT_SECONDS", "90"))
        self.completion_fn = completion_fn

    def standardize_review(self, review: dict[str, Any]) -> dict[str, Any]:
        standard_selection = review.get("standard_selection") or {}
        selected_standard = standard_selection.get("selected_standard")
        if not selected_standard:
            return _skipped("no_standard", "未选择标准，跳过 LLM/RAG 标准化。")

        spring_type = review.get("drawing_summary", {}).get("spring_type") or "unknown_spring"
        spring_features = review.get("spring_features") or {}
        target_fields = _retrieval_target_fields(review)
        chunks = retrieve_standard_chunks(
            standard_no=selected_standard,
            spring_type=spring_type,
            spring_features=spring_features,
            target_fields=target_fields,
            query=_retrieval_query(review),
            limit=8,
        )
        if not chunks:
            return _skipped("no_chunks", f"标准知识库未检索到 {selected_standard} 的相关条款。")

        request = {
            "model": self.model,
            "standard_no": selected_standard,
            "allowed_target_fields": _allowed_target_fields(review),
            "review": _compact_review(review),
            "chunks": chunks,
            "prompt": _build_prompt(review, chunks),
        }
        started = time.monotonic()
        raw_content, raw_response = self._complete(request)
        parsed = parse_llm_standardization_json(raw_content)
        normalized = normalize_llm_standardization_results(
            parsed,
            spring_type=spring_type,
            spring_parameters=review.get("spring_parameters") or {},
            standard_selection=standard_selection,
        )
        references = _chunk_references(chunks)
        for item in normalized["standardization_results"]:
            item.setdefault("metadata", {})
            item["metadata"]["rag_references"] = references
            item["metadata"]["llm_model"] = self.model
            item["metadata"]["llm_standardization_mode"] = "rag"
            if not item.get("basis"):
                item["basis"] = "LLM/RAG 标准化建议，需人工确认。"
        return {
            "status": "generated",
            "model": self.model,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "retrieved_chunks": chunks,
            "parsed": parsed,
            "standardization_results": normalized["standardization_results"],
            "diagnostics": normalized["diagnostics"],
            "raw": raw_response,
        }

    def _complete(self, request: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if self.completion_fn:
            content = self.completion_fn(request)
            return content, {"provider": "injected", "content": content}
        if not _configured(self.api_key):
            raise LLMStandardizationError("Qwen API key is not configured for LLM standardization.")

        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": LLM_STANDARDIZATION_SYSTEM_PROMPT},
                {"role": "user", "content": request["prompt"]},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                _chat_completions_endpoint(self.base_url),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code in {400, 422} and "response_format" in response.text:
                payload.pop("response_format", None)
                response = client.post(
                    _chat_completions_endpoint(self.base_url),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            response.raise_for_status()
            raw = response.json()
        return _message_content(raw), raw


LLM_STANDARDIZATION_SYSTEM_PROMPT = """你是弹簧标准化助手。你只根据输入的结构化参数和 RAG 标准条款生成标准化建议 JSON。

要求：
1. 只输出严格 JSON，不要输出 Markdown。
2. 只能使用 allowed_target_fields 中列出的 target_field，不要自造字段。
3. 只能依据 chunks 中给出的标准条款、表格和公式，不要引用外部知识。
4. 可以计算公差、限值或参考值；如果缺少必要参数，输出 status=need_context 并说明缺什么。
5. 所有结果都是待人工确认建议，不要声称已经正式通过。
6. 每条结果必须包含 target_field、suggested_value、suggested_tolerance_upper、suggested_tolerance_lower、unit、standard_no、rule_id、basis、status、need_human_review。
7. target_field 对载荷点只能使用 load_points.<label>.force。

输出 JSON 结构：
{
  "standardization_results": [
    {
      "target_field": "outer_diameter",
      "suggested_value": 20,
      "suggested_tolerance_upper": 0.4,
      "suggested_tolerance_lower": -0.4,
      "unit": "mm",
      "standard_no": "GB/T xxxx",
      "rule_id": "LLM-RAG-...",
      "basis": "引用chunk_id/表号，并说明计算过程。",
      "status": "suggested",
      "need_human_review": true,
      "confidence": 0.0,
      "references": [{"chunk_id": "...", "table_no": "..."}]
    }
  ]
}
"""


def parse_llm_standardization_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        payload = content
    else:
        text = str(content or "").strip()
        if not text:
            raise LLMStandardizationError("LLM standardization response is empty.")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise LLMStandardizationError("LLM standardization response does not contain JSON.")
            payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise LLMStandardizationError("LLM standardization JSON must be an object.")
    payload.setdefault("standardization_results", [])
    return payload


def llm_standardization_runtime_status() -> dict[str, Any]:
    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    return {
        "status": "configured" if _configured(api_key) else "not_configured",
        "model": os.getenv("LLM_STANDARDIZATION_MODEL") or os.getenv("QWEN_MODEL") or DEFAULT_LLM_STANDARDIZATION_MODEL,
        "base_url": os.getenv("LLM_STANDARDIZATION_BASE_URL") or os.getenv("QWEN_BASE_URL") or DEFAULT_LLM_STANDARDIZATION_BASE_URL,
        "mode": "rag_json",
    }


def _build_prompt(review: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    payload = {
        "allowed_target_fields": _allowed_target_fields(review),
        "review": _compact_review(review),
        "chunks": [
            {
                "chunk_id": chunk.get("chunk_id"),
                "title": chunk.get("title"),
                "content": chunk.get("content"),
                "metadata": {
                    "standard_no": chunk.get("metadata", {}).get("standard_no"),
                    "rule_topic": chunk.get("metadata", {}).get("rule_topic"),
                    "table_no": chunk.get("metadata", {}).get("table_no"),
                    "target_fields": chunk.get("metadata", {}).get("target_fields", []),
                },
            }
            for chunk in chunks
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _compact_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "drawing_summary": review.get("drawing_summary") or {},
        "spring_features": review.get("spring_features") or {},
        "standard_selection": review.get("standard_selection") or {},
        "spring_parameters": _compact_parameters(review.get("spring_parameters") or {}),
        "derived_parameters": review.get("derived_parameters") or {},
    }


def _compact_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for field, value in parameters.items():
        if field == "load_points":
            compact[field] = value
            continue
        if not isinstance(value, dict):
            compact[field] = value
            continue
        if value.get("value") in (None, "") and value.get("tolerance_upper") in (None, "") and value.get("tolerance_lower") in (None, ""):
            continue
        compact[field] = {
            key: value.get(key)
            for key in ("value", "unit", "tolerance_upper", "tolerance_lower", "default_source", "need_human_review")
            if value.get(key) not in (None, "")
        }
    return compact


def _retrieval_target_fields(review: dict[str, Any]) -> list[str]:
    parameters = review.get("spring_parameters") or {}
    fields = []
    for field in (
        "outer_diameter",
        "inner_diameter",
        "controlled_diameter_field",
        "free_length",
        "total_coils",
        "perpendicularity",
        "straightness",
        "spring_rate",
        "solid_height",
        "permanent_set_limit",
    ):
        if _has_value(parameters.get(field)) or field in {"perpendicularity", "straightness", "solid_height", "permanent_set_limit"}:
            fields.append(field)
    if parameters.get("load_points"):
        fields.append("load_points")
    return fields


def _retrieval_query(review: dict[str, Any]) -> str:
    selection = review.get("standard_selection") or {}
    fields = " ".join(_retrieval_target_fields(review))
    return f"{selection.get('selected_standard', '')} 标准化 公差 极限偏差 {fields}"


def _allowed_target_fields(review: dict[str, Any]) -> list[str]:
    spring_type = review.get("drawing_summary", {}).get("spring_type") or "unknown_spring"
    fields = list(template_field_keys(spring_type))
    parameters = review.get("spring_parameters") or {}
    for index, point in enumerate(parameters.get("load_points", []) or [], start=1):
        label = str(point.get("label") or f"F{index}").strip()
        if label:
            fields.append(f"load_points.{label}.force")
    return fields


def _chunk_references(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": chunk.get("chunk_id"),
            "title": chunk.get("title"),
            "standard_no": chunk.get("metadata", {}).get("standard_no"),
            "table_no": chunk.get("metadata", {}).get("table_no"),
            "rule_topic": chunk.get("metadata", {}).get("rule_topic"),
            "score": chunk.get("score"),
        }
        for chunk in chunks
    ]


def _message_content(raw_response: dict[str, Any]) -> Any:
    choices = raw_response.get("choices") or []
    if not choices:
        raise LLMStandardizationError("LLM standardization response does not contain choices.")
    message = choices[0].get("message") or {}
    return message.get("content")


def _chat_completions_endpoint(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url.rstrip('/')}/chat/completions"


def _configured(value: str | None) -> bool:
    return bool(value and value.strip() and "replace-with" not in value)


def _has_value(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("value") not in (None, "")
    return value not in (None, "")


def _skipped(reason: str, message: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": reason,
        "message": message,
        "retrieved_chunks": [],
        "standardization_results": [],
        "diagnostics": [],
        "raw": None,
    }
