from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_RETRIEVAL_TIMEOUT_SECONDS = 12.0
DEFAULT_SIMILARITY_THRESHOLD = 0.1
DEFAULT_VECTOR_SIMILARITY_WEIGHT = 0.3
DEFAULT_TOP_K = 30


class RAGFlowKnowledgeError(RuntimeError):
    """Raised when RAGFlow cannot provide a trustworthy retrieval response."""


RequestFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class RAGFlowKnowledgeConfig:
    base_url: str | None
    api_key: str | None
    compression_dataset_id: str | None
    standard_document_ids: dict[str, str]
    timeout_seconds: float = DEFAULT_RETRIEVAL_TIMEOUT_SECONDS
    dataset_name: str = "压缩弹簧"

    @classmethod
    def from_env(cls) -> "RAGFlowKnowledgeConfig":
        return cls(
            base_url=_configured_value(os.getenv("RAGFLOW_BASE_URL")),
            api_key=_configured_value(os.getenv("RAGFLOW_API_KEY")),
            compression_dataset_id=_configured_value(os.getenv("RAGFLOW_COMPRESSION_DATASET_ID")),
            standard_document_ids=_document_id_map(os.getenv("RAGFLOW_STANDARD_DOCUMENT_IDS")),
            timeout_seconds=_positive_float(
                os.getenv("RAGFLOW_TIMEOUT_SECONDS"),
                DEFAULT_RETRIEVAL_TIMEOUT_SECONDS,
            ),
            dataset_name=str(os.getenv("RAGFLOW_COMPRESSION_DATASET_NAME") or "压缩弹簧").strip() or "压缩弹簧",
        )

    def document_id_for(self, standard_no: str | None) -> str | None:
        return self.standard_document_ids.get(canonical_standard_no(standard_no))

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.compression_dataset_id and self.standard_document_ids)

    @property
    def configuration_reason(self) -> str | None:
        if not self.base_url or not self.api_key:
            return "ragflow_credentials_missing"
        if not self.compression_dataset_id:
            return "ragflow_compression_dataset_missing"
        if not self.standard_document_ids:
            return "ragflow_standard_document_map_missing"
        return None


class RAGFlowKnowledgeClient:
    """Small, server-side-only adapter for the RAGFlow retrieval API."""

    def __init__(
        self,
        config: RAGFlowKnowledgeConfig | None = None,
        request_fn: RequestFn | None = None,
    ) -> None:
        self.config = config or RAGFlowKnowledgeConfig.from_env()
        self.request_fn = request_fn

    def health(self) -> dict[str, Any]:
        if not self.config.configured:
            return {
                "status": "not_configured",
                "reason": self.config.configuration_reason,
                "dataset_name": self.config.dataset_name,
            }
        try:
            self._request("GET", "/api/v1/system/healthz")
        except RAGFlowKnowledgeError as exc:
            return {
                "status": "unavailable",
                "reason": _safe_error_reason(exc),
                "dataset_name": self.config.dataset_name,
            }
        return {
            "status": "available",
            "dataset_name": self.config.dataset_name,
            "dataset_id": self.config.compression_dataset_id,
        }

    def retrieve(
        self,
        *,
        standard_no: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.config.configured:
            raise RAGFlowKnowledgeError(self.config.configuration_reason or "ragflow_not_configured")
        canonical_standard = canonical_standard_no(standard_no)
        document_id = self.config.document_id_for(canonical_standard)
        if not document_id:
            raise RAGFlowKnowledgeError(f"ragflow_document_not_configured:{canonical_standard}")

        payload = {
            "question": query,
            "dataset_ids": [self.config.compression_dataset_id],
            "document_ids": [document_id],
            "similarity_threshold": DEFAULT_SIMILARITY_THRESHOLD,
            "vector_similarity_weight": DEFAULT_VECTOR_SIMILARITY_WEIGHT,
            "top_k": max(DEFAULT_TOP_K, int(limit)),
            "page_size": max(8, int(limit)),
            "keyword": True,
        }
        response = self._request("POST", "/api/v1/retrieval", payload)
        chunks = []
        for index, item in enumerate(_response_chunks(response), start=1):
            if not isinstance(item, dict):
                continue
            # The document filter is enforced twice: once in the request and once
            # here before a result can become a citation.
            if str(item.get("document_id") or "") != document_id:
                continue
            chunks.append(_normalize_chunk(
                item,
                index=index,
                standard_no=canonical_standard,
                dataset_id=self.config.compression_dataset_id or "",
                dataset_name=self.config.dataset_name,
            ))
        chunks.sort(key=lambda item: item["score"], reverse=True)
        return chunks[: max(0, int(limit))]

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.base_url or not self.config.api_key:
            raise RAGFlowKnowledgeError("ragflow_credentials_missing")
        url = f"{self.config.base_url.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        try:
            if self.request_fn is not None:
                body = self.request_fn(method, url, headers=headers, json=payload, timeout=self.config.timeout_seconds)
            else:
                import httpx

                with httpx.Client(timeout=self.config.timeout_seconds, follow_redirects=True) as client:
                    response = client.request(method, url, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
        except Exception as exc:
            raise RAGFlowKnowledgeError(f"ragflow_request_failed:{type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise RAGFlowKnowledgeError("ragflow_invalid_response")
        code = body.get("code")
        if code not in (None, 0, "0"):
            raise RAGFlowKnowledgeError(f"ragflow_api_code:{code}")
        return body


def canonical_standard_no(value: Any) -> str:
    text = str(value or "").upper().replace(" ", "")
    text = text.replace("—", "-").replace("–", "-").replace("－", "-")
    text = text.replace("GBT", "GB/T")
    if re.search(r"GB/?T?1239\.?2", text):
        return "GB/T 1239.2-2009"
    if re.search(r"GB/?T?23934", text):
        return "GB/T 23934-2015"
    return re.sub(r"[^A-Z0-9/.-]", "", text)


def _normalize_chunk(
    item: dict[str, Any],
    *,
    index: int,
    standard_no: str,
    dataset_id: str,
    dataset_name: str,
) -> dict[str, Any]:
    content = str(item.get("content") or item.get("text") or "").strip()
    metadata = dict(item.get("document_metadata") or item.get("metadata") or {})
    metadata["standard_no"] = canonical_standard_no(metadata.get("standard_no") or standard_no)
    metadata.setdefault("target_fields", [])
    table_no = _table_no(content)
    if table_no:
        metadata.setdefault("table_no", table_no)
    similarity = _number(item.get("similarity"), default=0.0)
    return {
        "chunk_id": str(item.get("id") or item.get("chunk_id") or f"ragflow-{index}"),
        "title": str(item.get("document_name") or item.get("document_keyword") or standard_no),
        "content": content,
        "metadata": metadata,
        "score": similarity,
        "source": "ragflow",
        "retrieval_status": "available",
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "document_id": str(item.get("document_id") or ""),
        "document_name": str(item.get("document_name") or item.get("document_keyword") or ""),
        "positions": item.get("positions") or [],
        "similarity": similarity,
        "vector_similarity": _number(item.get("vector_similarity"), default=None),
        "term_similarity": _number(item.get("term_similarity"), default=None),
    }


def _response_chunks(response: dict[str, Any]) -> list[Any]:
    data = response.get("data", response)
    if isinstance(data, dict):
        chunks = data.get("chunks")
        if isinstance(chunks, list):
            return chunks
        nested = data.get("data")
        if isinstance(nested, dict) and isinstance(nested.get("chunks"), list):
            return nested["chunks"]
    if isinstance(response.get("chunks"), list):
        return response["chunks"]
    return []


def _document_id_map(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        canonical_standard_no(standard_no): str(document_id).strip()
        for standard_no, document_id in payload.items()
        if canonical_standard_no(standard_no) and str(document_id).strip()
    }


def _configured_value(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text or "replace-with" in text:
        return None
    return text


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


def _number(value: Any, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _table_no(content: str) -> str | None:
    match = re.search(r"表\s*([0-9]+\s*[-－—]\s*[0-9]+)", content)
    return f"表{match.group(1).replace(' ', '').replace('－', '-').replace('—', '-')}" if match else None


def _safe_error_reason(error: Exception) -> str:
    message = str(error)
    return message[:160] if message else type(error).__name__
