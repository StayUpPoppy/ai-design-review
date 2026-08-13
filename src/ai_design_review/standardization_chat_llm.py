from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

from .spring_templates import template_field_keys
from .standard_knowledge import chunk_reference, retrieve_standard_chunks


DEFAULT_STANDARDIZATION_CHAT_MODEL = "qwen3.7-plus"
DEFAULT_STANDARDIZATION_CHAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_STANDARDIZATION_CHAT_TIMEOUT_SECONDS = 180.0
DEFAULT_STANDARDIZATION_CHAT_MAX_RETRIES = 1
MAX_PROMPT_CHUNK_CONTENT_CHARS = 1000
MAX_RECENT_CHAT_TURNS = 2
ALLOWED_CHAT_ACTION_TYPES = {"propose_parameter_patch", "propose_tolerance_patch"}
FULL_PLAN_TARGET_FIELDS = [
    "standard_no",
    "accuracy_grade",
    "wire_diameter",
    "outer_diameter",
    "inner_diameter",
    "mean_diameter",
    "free_length",
    "total_coils",
    "spring_rate",
    "perpendicularity",
    "straightness",
]


class StandardizationChatLLMError(RuntimeError):
    """Raised when the standardization chat LLM cannot return usable JSON."""


CompletionFn = Callable[[dict[str, Any]], Any]


class StandardizationChatLLMEngine:
    """Interpret standardization chat requests as review-only structured actions."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        completion_fn: CompletionFn | None = None,
    ):
        self.api_key = api_key or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self.model = (
            model
            or os.getenv("STANDARDIZATION_CHAT_MODEL")
            or os.getenv("LLM_STANDARDIZATION_MODEL")
            or os.getenv("QWEN_MODEL")
            or DEFAULT_STANDARDIZATION_CHAT_MODEL
        )
        self.base_url = (
            base_url
            or os.getenv("STANDARDIZATION_CHAT_BASE_URL")
            or os.getenv("LLM_STANDARDIZATION_BASE_URL")
            or os.getenv("QWEN_BASE_URL")
            or DEFAULT_STANDARDIZATION_CHAT_BASE_URL
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("STANDARDIZATION_CHAT_TIMEOUT_SECONDS", str(DEFAULT_STANDARDIZATION_CHAT_TIMEOUT_SECONDS))
        )
        self.max_retries = (
            max(0, int(max_retries))
            if max_retries is not None
            else max(0, int(os.getenv("STANDARDIZATION_CHAT_MAX_RETRIES", str(DEFAULT_STANDARDIZATION_CHAT_MAX_RETRIES))))
        )
        self.completion_fn = completion_fn

    def chat(self, review: dict[str, Any], message: str, rule_result: dict[str, Any] | None = None) -> dict[str, Any]:
        chunks = _retrieve_chunks(review, message, rule_result or {})
        request = {
            "model": self.model,
            "message": message,
            "allowed_target_fields": _allowed_target_fields(review),
            "review": _compact_review(review),
            "rule_result": _compact_rule_result(rule_result or {}),
            "chunks": chunks,
            "prompt": _build_prompt(review, message, rule_result or {}, chunks),
        }
        started = time.monotonic()
        raw_content, raw_response = self._complete(request)
        parsed = parse_chat_json(raw_content)
        normalized = normalize_chat_payload(
            parsed,
            review=review,
            chunks=chunks,
            model=self.model,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        normalized["raw"] = raw_response
        return normalized

    def _complete(self, request: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if self.completion_fn:
            content = self.completion_fn(request)
            return content, {"provider": "injected", "content": content}
        if not _configured(self.api_key):
            raise StandardizationChatLLMError("Qwen API key is not configured for standardization chat.")

        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": STANDARDIZATION_CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": request["prompt"]},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        for attempt in range(self.max_retries + 1):
            try:
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
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    continue
                raise StandardizationChatLLMError(
                    "Qwen standardization chat timed out "
                    f"after {self.timeout_seconds:g}s x {self.max_retries + 1} attempt(s)."
                ) from exc
        raise StandardizationChatLLMError("Qwen standardization chat failed before receiving a response.")


STANDARDIZATION_CHAT_SYSTEM_PROMPT = """你是弹簧标准化对话 Agent。你负责理解用户对标准化结果的提问或修改意图，并输出严格 JSON。

要求：
1. 只输出 JSON，不要输出 Markdown。
2. 不要直接修改参数，不要声称已写回系统。
3. 只能把修改表达为 suggested_actions，apply_policy 必须是 manual_confirm_required。
4. target_field 只能使用 allowed_target_fields 中的字段；载荷测试点只能用 load_points.<label>.force。
5. 如果用户表达模糊，status=need_clarification，并在 reply 中追问。
6. 如果解释标准依据，只能引用输入 review.standardization_results 或 chunks，不要编造标准条款。
7. 如果需要重新标准化，要说明受影响字段，但不要自己调用工具。
8. 如果用户要求“完整标准化方案”，intent.type=full_standardization_plan；请结合 review、rule_result、chunks 输出多字段 suggested_actions。
9. 尺寸本体修改使用 propose_parameter_patch；公差/上下偏差建议使用 propose_tolerance_patch。
10. 对依据不足的字段不要硬算，改为在 reply 中说明缺少条件，并在 suggested_actions 中跳过该字段。
11. 如果用户明确要求导出、下载生图参数包或SolidWorks参数，intent.type=generation_package_export_request；不要生成参数包内容，不要添加suggested_actions，后端会重新校验并执行下载。

输出 JSON 结构：
{
  "reply": "给用户看的中文回复",
  "intent": {
    "type": "explanation|parameter_change_request|multi_constraint_change_request|full_standardization_plan|generation_package_export_request|confirmation|unknown",
    "target_field": "outer_diameter",
    "target_fields": ["outer_diameter"],
    "status": "answered|need_clarification|proposal_ready|manual_apply_required",
    "constraints": ["free_length unchanged"],
    "affected_fields": ["mean_diameter", "spring_index"]
  },
  "suggested_actions": [
    {
      "type": "propose_parameter_patch",
      "target_field": "outer_diameter",
      "proposed_value": 22,
      "unit": "mm",
      "reason": "用户要求外径改成22mm",
      "affected_fields": ["mean_diameter", "spring_index"],
      "apply_policy": "manual_confirm_required"
    },
    {
      "type": "propose_tolerance_patch",
      "target_field": "free_length",
      "suggested_tolerance_upper": 0.9,
      "suggested_tolerance_lower": -0.9,
      "unit": "mm",
      "reason": "依据 chunks 或 review.standardization_results 中的自由长度公差条款",
      "affected_fields": ["free_length_tolerance"],
      "apply_policy": "manual_confirm_required"
    }
  ],
  "references": [{"chunk_id": "...", "table_no": "..."}]
}
"""


def parse_chat_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        payload = content
    else:
        text = str(content or "").strip()
        if not text:
            raise StandardizationChatLLMError("Standardization chat response is empty.")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise StandardizationChatLLMError("Standardization chat response does not contain JSON.")
            payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise StandardizationChatLLMError("Standardization chat JSON must be an object.")
    return payload


def normalize_chat_payload(
    payload: dict[str, Any],
    *,
    review: dict[str, Any],
    chunks: list[dict[str, Any]],
    model: str,
    duration_ms: int,
) -> dict[str, Any]:
    allowed = set(_allowed_target_fields(review))
    diagnostics: list[dict[str, Any]] = []
    intent = dict(payload.get("intent") or {})
    target_field = str(intent.get("target_field") or "").strip()
    target_fields = _normalize_target_fields(intent.get("target_fields"), allowed, diagnostics)
    if target_field:
        if target_field in allowed:
            if target_field not in target_fields:
                target_fields.insert(0, target_field)
        else:
            diagnostics.append({"type": "invalid_intent_target", "target_field": target_field})
            target_field = ""
    elif target_fields:
        target_field = target_fields[0]

    intent["target_field"] = target_field
    intent["target_fields"] = target_fields
    intent.setdefault("type", "unknown")
    intent.setdefault("status", "need_clarification")
    intent["affected_fields"] = _string_list(intent.get("affected_fields"))
    intent["constraints"] = _string_list(intent.get("constraints"))

    actions = []
    for index, action in enumerate(payload.get("suggested_actions") or [], start=1):
        if not isinstance(action, dict):
            diagnostics.append({"type": "invalid_action", "index": index, "reason": "action is not object"})
            continue
        normalized = dict(action)
        action_type = str(normalized.get("type") or "").strip()
        normalized.setdefault("metadata", {})
        if action_type not in ALLOWED_CHAT_ACTION_TYPES:
            normalized["metadata"]["action_type_valid"] = False
            normalized["metadata"]["action_type_error"] = f"action type {action_type or '<empty>'} is not allowed"
            diagnostics.append({"type": "invalid_action_type", "index": index, "action_type": action_type})
        else:
            normalized["metadata"]["action_type_valid"] = True
        normalized["type"] = action_type or "unknown"
        action_target = str(normalized.get("target_field") or "").strip()
        if action_target and action_target not in allowed:
            normalized["metadata"]["target_field_valid"] = False
            normalized["metadata"]["target_field_error"] = f"target_field {action_target} is not allowed"
            diagnostics.append({"type": "invalid_action_target", "index": index, "target_field": action_target})
        else:
            normalized["metadata"]["target_field_valid"] = bool(action_target)
        if "tolerance_upper" in normalized and "suggested_tolerance_upper" not in normalized:
            normalized["suggested_tolerance_upper"] = normalized.get("tolerance_upper")
        if "tolerance_lower" in normalized and "suggested_tolerance_lower" not in normalized:
            normalized["suggested_tolerance_lower"] = normalized.get("tolerance_lower")
        _normalize_unchanged_load_value_action(normalized, review, diagnostics, index)
        normalized["apply_policy"] = "manual_confirm_required"
        normalized["affected_fields"] = _string_list(normalized.get("affected_fields"))
        actions.append(normalized)

    if not intent["target_fields"]:
        action_targets = [
            str(action.get("target_field") or "")
            for action in actions
            if action.get("metadata", {}).get("target_field_valid")
        ]
        intent["target_fields"] = list(dict.fromkeys(action_targets))
        if not intent["target_field"] and intent["target_fields"]:
            intent["target_field"] = intent["target_fields"][0]

    references = payload.get("references") if isinstance(payload.get("references"), list) else []
    if not references:
        references = _chunk_references(chunks)

    reply = str(payload.get("reply") or "").strip()
    if not reply:
        reply = "我已解析你的标准化需求，但模型没有给出可展示回复。请人工复核后再继续。"

    return {
        "reply": reply,
        "intent": intent,
        "suggested_actions": actions,
        "references": references,
        "diagnostics": diagnostics,
        "llm_chat": {
            "status": "generated",
            "model": model,
            "duration_ms": duration_ms,
            "retrieved_chunk_count": len(chunks),
        },
    }


def _normalize_unchanged_load_value_action(
    action: dict[str, Any],
    review: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    index: int,
) -> None:
    """Turn a no-op F-value patch into the matching deterministic tolerance patch.

    The model sometimes describes a load tolerance rule as a parameter patch whose
    proposed force is identical to the drawing force. Applying that action must not
    merely reconfirm the force while leaving the drawing tolerance untouched.
    """
    if action.get("type") != "propose_parameter_patch":
        return
    target = str(action.get("target_field") or "")
    match = re.fullmatch(r"load_points\.([^.]+)\.force", target)
    if not match:
        return
    point = next(
        (
            item
            for item in (review.get("spring_parameters") or {}).get("load_points", []) or []
            if isinstance(item, dict) and str(item.get("label") or "") == match.group(1)
        ),
        None,
    )
    if not isinstance(point, dict) or not _same_number(action.get("proposed_value"), point.get("force")):
        return
    result = next(
        (
            item
            for item in review.get("standardization_results", []) or []
            if isinstance(item, dict)
            and item.get("target_field") == target
            and item.get("suggested_tolerance_upper") is not None
            and item.get("suggested_tolerance_lower") is not None
            and item.get("status") in {"suggested", "llm_suggested", "human_confirmed"}
        ),
        None,
    )
    if not isinstance(result, dict):
        return

    action["type"] = "propose_tolerance_patch"
    action.pop("proposed_value", None)
    action["suggested_tolerance_upper"] = result.get("suggested_tolerance_upper")
    action["suggested_tolerance_lower"] = result.get("suggested_tolerance_lower")
    action["unit"] = result.get("unit") or point.get("force_unit") or "N"
    action["target_label"] = f"载荷测试点 {match.group(1)} 负荷公差"
    action["reason"] = result.get("basis") or action.get("reason") or "按当前标准化结果更新负荷公差。"
    action["affected_fields"] = [f"{target}_tolerance"]
    action.setdefault("metadata", {})["normalized_from_unchanged_force_patch"] = True
    diagnostics.append(
        {
            "type": "normalized_unchanged_load_value_action",
            "index": index,
            "target_field": target,
        }
    )


def _same_number(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-9
    except (TypeError, ValueError):
        return False


def standardization_chat_llm_runtime_status() -> dict[str, Any]:
    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    return {
        "status": "configured" if _configured(api_key) else "not_configured",
        "model": os.getenv("STANDARDIZATION_CHAT_MODEL")
        or os.getenv("LLM_STANDARDIZATION_MODEL")
        or os.getenv("QWEN_MODEL")
        or DEFAULT_STANDARDIZATION_CHAT_MODEL,
        "base_url": os.getenv("STANDARDIZATION_CHAT_BASE_URL")
        or os.getenv("LLM_STANDARDIZATION_BASE_URL")
        or os.getenv("QWEN_BASE_URL")
        or DEFAULT_STANDARDIZATION_CHAT_BASE_URL,
        "mode": "rag_intent_json",
        "timeout_seconds": float(
            os.getenv("STANDARDIZATION_CHAT_TIMEOUT_SECONDS", str(DEFAULT_STANDARDIZATION_CHAT_TIMEOUT_SECONDS))
        ),
        "max_retries": int(os.getenv("STANDARDIZATION_CHAT_MAX_RETRIES", str(DEFAULT_STANDARDIZATION_CHAT_MAX_RETRIES))),
    }


def _build_prompt(
    review: dict[str, Any],
    message: str,
    rule_result: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> str:
    payload = {
        "message": message,
        "allowed_target_fields": _allowed_target_fields(review),
        "review": _compact_review(review),
        "rule_result": _compact_rule_result(rule_result),
        "chunks": [
            {
                "chunk_id": chunk.get("chunk_id"),
                "title": chunk.get("title"),
                "content": _clip_text(chunk.get("content"), MAX_PROMPT_CHUNK_CONTENT_CHARS),
                "metadata": {
                    "standard_no": chunk.get("metadata", {}).get("standard_no"),
                    "rule_topic": chunk.get("metadata", {}).get("rule_topic"),
                    "table_no": chunk.get("metadata", {}).get("table_no"),
                    "target_fields": chunk.get("metadata", {}).get("target_fields", []),
                },
            }
            for chunk in chunks
        ],
        "recent_chat": _compact_recent_chat(review),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _compact_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "drawing_summary": review.get("drawing_summary") or {},
        "spring_features": review.get("spring_features") or {},
        "standard_selection": review.get("standard_selection") or {},
        "spring_parameters": _compact_parameters(review.get("spring_parameters") or {}),
        "derived_parameters": review.get("derived_parameters") or {},
        "parameter_reasonableness": review.get("parameter_reasonableness") or {},
        "standardization_results": [
            {
                key: item.get(key)
                for key in (
                    "target_field",
                    "suggested_value",
                    "suggested_tolerance_upper",
                    "suggested_tolerance_lower",
                    "unit",
                    "standard_no",
                    "rule_id",
                    "basis",
                    "status",
                )
            }
            for item in (review.get("standardization_results") or [])[:12]
            if isinstance(item, dict)
        ],
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
            for key in ("value", "unit", "tolerance_upper", "tolerance_lower", "need_human_review", "default_source")
            if value.get(key) not in (None, "")
        }
    return compact


def _compact_rule_result(rule_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "reply": rule_result.get("reply"),
        "intent": rule_result.get("intent"),
        "suggested_actions": rule_result.get("suggested_actions") or [],
        "references": rule_result.get("references") or [],
    }


def _compact_recent_chat(review: dict[str, Any]) -> list[dict[str, Any]]:
    turns = review.get("standardization_chat") or []
    compact = []
    for turn in turns[-MAX_RECENT_CHAT_TURNS:]:
        if not isinstance(turn, dict):
            continue
        compact.append(
            {
                "user": _clip_text(turn.get("user"), 260),
                "assistant": _clip_text(turn.get("assistant"), 360),
                "intent": turn.get("intent") or {},
                "suggested_actions": (turn.get("suggested_actions") or [])[:4],
            }
        )
    return compact


def _clip_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def _retrieve_chunks(review: dict[str, Any], message: str, rule_result: dict[str, Any]) -> list[dict[str, Any]]:
    selected_standard = (review.get("standard_selection") or {}).get("selected_standard")
    if not selected_standard:
        return []
    target_fields = _target_fields_for_retrieval(rule_result)
    return retrieve_standard_chunks(
        standard_no=selected_standard,
        spring_type=review.get("drawing_summary", {}).get("spring_type") or "compression_spring",
        spring_features=review.get("spring_features") or {},
        target_fields=target_fields,
        query=message,
        limit=6,
    )


def _target_fields_for_retrieval(rule_result: dict[str, Any]) -> list[str]:
    intent = rule_result.get("intent") or {}
    if intent.get("type") == "full_standardization_plan":
        return FULL_PLAN_TARGET_FIELDS
    fields = []
    for field in [intent.get("target_field"), *(intent.get("target_fields") or [])]:
        if field:
            fields.append(str(field).split(".")[0])
    for action in rule_result.get("suggested_actions") or []:
        if isinstance(action, dict) and action.get("target_field"):
            fields.append(str(action["target_field"]).split(".")[0])
    return list(dict.fromkeys(fields))


def _allowed_target_fields(review: dict[str, Any]) -> list[str]:
    spring_type = review.get("drawing_summary", {}).get("spring_type") or "unknown_spring"
    fields = list(template_field_keys(spring_type))
    parameters = review.get("spring_parameters") or {}
    for index, point in enumerate(parameters.get("load_points", []) or [], start=1):
        label = str(point.get("label") or f"F{index}").strip()
        if label:
            fields.append(f"load_points.{label}.force")
    return fields


def _normalize_target_fields(value: Any, allowed: set[str], diagnostics: list[dict[str, Any]]) -> list[str]:
    fields = _string_list(value)
    valid = []
    for field in fields:
        if field in allowed:
            valid.append(field)
        else:
            diagnostics.append({"type": "invalid_intent_target", "target_field": field})
    return list(dict.fromkeys(valid))


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _chunk_references(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [chunk_reference(chunk) for chunk in chunks]


def _message_content(raw_response: dict[str, Any]) -> Any:
    choices = raw_response.get("choices") or []
    if not choices:
        raise StandardizationChatLLMError("Standardization chat response does not contain choices.")
    message = choices[0].get("message") or {}
    return message.get("content")


def _chat_completions_endpoint(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url.rstrip('/')}/chat/completions"


def _configured(value: str | None) -> bool:
    return bool(value and value.strip() and "replace-with" not in value)
