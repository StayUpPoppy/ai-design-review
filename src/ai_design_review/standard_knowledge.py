from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .io_utils import project_path, read_json
from .ragflow_knowledge import RAGFlowKnowledgeClient, RAGFlowKnowledgeError, canonical_standard_no


DEFAULT_KNOWLEDGE_PATH = project_path("config", "standard_knowledge", "compression_spring_tolerance_chunks.json")


def retrieve_standard_chunks(
    *,
    standard_no: str | None = None,
    spring_type: str | None = None,
    spring_features: dict[str, Any] | None = None,
    target_fields: list[str] | tuple[str, ...] | set[str] | None = None,
    query: str | None = None,
    limit: int = 6,
    ragflow_client: RAGFlowKnowledgeClient | None = None,
) -> list[dict[str, Any]]:
    """Retrieve standard chunks from RAGFlow, with the local file as fallback."""

    target_set = {str(item) for item in target_fields or [] if item}
    features = spring_features or {}
    canonical_standard = canonical_standard_no(standard_no) if standard_no else None
    fallback_reason = _ragflow_fallback_reason(
        standard_no=canonical_standard,
        spring_type=spring_type,
        target_fields=target_set,
        query=query or "",
        limit=limit,
        client=ragflow_client,
    )
    if isinstance(fallback_reason, list):
        return fallback_reason

    chunks = []
    for chunk in load_standard_knowledge():
        metadata = chunk.get("metadata") or {}
        if canonical_standard and not _standard_matches(metadata, canonical_standard):
            continue
        if spring_type and metadata.get("spring_category") and metadata.get("spring_category") != spring_type:
            continue
        if not _features_match(metadata, features):
            continue
        score = _score_chunk(chunk, target_set, query or "")
        chunks.append(_public_chunk(chunk, score, fallback_reason=fallback_reason))
    chunks.sort(key=lambda item: item["score"], reverse=True)
    return chunks[: max(0, int(limit))]


def standard_references(
    standard_no: str | None,
    *,
    target_fields: list[str] | tuple[str, ...] | set[str] | None = None,
    spring_type: str | None = "compression_spring",
    spring_features: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    chunks = retrieve_standard_chunks(
        standard_no=standard_no,
        spring_type=spring_type,
        spring_features=spring_features,
        target_fields=target_fields,
        query="标准依据 公差 精度 等级",
        limit=limit,
    )
    return [chunk_reference(chunk, standard_no=standard_no) for chunk in chunks]


def chunk_reference(chunk: dict[str, Any], *, standard_no: str | None = None) -> dict[str, Any]:
    metadata = chunk.get("metadata") or {}
    return {
        "standard_no": metadata.get("standard_no") or standard_no,
        "chunk_id": chunk.get("chunk_id"),
        "title": chunk.get("title"),
        "table_no": metadata.get("table_no"),
        "rule_topic": metadata.get("rule_topic"),
        "target_fields": metadata.get("target_fields", []),
        "source": chunk.get("source") or "local_standard_knowledge",
        "status": chunk.get("retrieval_status") or "available",
        "score": chunk.get("score"),
        "dataset_id": chunk.get("dataset_id"),
        "dataset_name": chunk.get("dataset_name"),
        "document_id": chunk.get("document_id"),
        "document_name": chunk.get("document_name"),
        "positions": chunk.get("positions") or [],
        "similarity": chunk.get("similarity"),
        "retrieval_reason": chunk.get("retrieval_reason"),
        "metadata": {
            "rule_topic": metadata.get("rule_topic"),
            "table_no": metadata.get("table_no"),
            "target_fields": metadata.get("target_fields", []),
        },
    }


@lru_cache(maxsize=1)
def load_standard_knowledge(path: str | Path | None = None) -> list[dict[str, Any]]:
    payload = read_json(Path(path) if path else DEFAULT_KNOWLEDGE_PATH)
    chunks = payload.get("chunks", []) if isinstance(payload, dict) else []
    return [chunk for chunk in chunks if isinstance(chunk, dict)]


def _standard_matches(metadata: dict[str, Any], standard_no: str) -> bool:
    needle = canonical_standard_no(standard_no)
    candidates = [metadata.get("standard_no"), *(metadata.get("standard_aliases") or [])]
    if not any(candidates):
        return True
    return any(canonical_standard_no(candidate) == needle for candidate in candidates if candidate)


def _features_match(metadata: dict[str, Any], features: dict[str, Any]) -> bool:
    for field in ("spring_family", "spring_shape", "manufacturing_method", "wire_section", "pitch_type"):
        chunk_value = str(metadata.get(field) or "").strip()
        if not chunk_value:
            continue
        feature_value = _feature_value(features, field)
        if feature_value in ("", "unknown", None):
            continue
        if str(feature_value).strip() != chunk_value:
            return False
    return True


def _score_chunk(chunk: dict[str, Any], target_fields: set[str], query: str) -> float:
    metadata = chunk.get("metadata") or {}
    text = " ".join(
        str(item or "")
        for item in (
            chunk.get("chunk_id"),
            chunk.get("title"),
            chunk.get("content"),
            metadata.get("rule_topic"),
            metadata.get("table_no"),
            " ".join(metadata.get("target_fields") or []),
        )
    ).lower()
    score = 0.0
    target_overlap = target_fields & set(metadata.get("target_fields") or [])
    if target_overlap:
        score += 8.0 + len(target_overlap)
    elif target_fields and _is_general_chunk(metadata):
        score += 1.0
    for token in _tokens(query):
        if token and token in text:
            score += 1.0
    if metadata.get("table_no"):
        score += 0.5
    if metadata.get("rule_topic") == "symbol_definitions":
        score -= 1.5
    return round(score, 4)


def _public_chunk(chunk: dict[str, Any], score: float, *, fallback_reason: str | None = None) -> dict[str, Any]:
    result = {
        "chunk_id": chunk.get("chunk_id"),
        "title": chunk.get("title"),
        "content": chunk.get("content"),
        "metadata": chunk.get("metadata") or {},
        "score": score,
        "source": "local_standard_knowledge",
        "retrieval_status": "fallback" if fallback_reason else "available",
    }
    if fallback_reason:
        result["retrieval_reason"] = fallback_reason
    return result


def _tokens(text: str) -> list[str]:
    normalized = str(text or "").lower()
    raw_tokens = re.findall(r"[a-z0-9_.+-]+|[\u4e00-\u9fff]{2,}", normalized)
    tokens = []
    for token in raw_tokens:
        tokens.append(token)
        if len(token) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def ragflow_runtime_status(*, check_health: bool = False) -> dict[str, Any]:
    client = RAGFlowKnowledgeClient()
    if check_health:
        return client.health()
    config = client.config
    return {
        "status": "configured" if config.configured else "not_configured",
        "reason": config.configuration_reason,
        "dataset_name": config.dataset_name,
    }


def _ragflow_fallback_reason(
    *,
    standard_no: str | None,
    spring_type: str | None,
    target_fields: set[str],
    query: str,
    limit: int,
    client: RAGFlowKnowledgeClient | None,
) -> list[dict[str, Any]] | str | None:
    if spring_type not in (None, "compression_spring") or not standard_no:
        return "ragflow_not_applicable"
    ragflow = client or RAGFlowKnowledgeClient()
    try:
        chunks = ragflow.retrieve(
            standard_no=standard_no,
            query=_ragflow_query(standard_no, target_fields, query),
            limit=limit,
        )
    except RAGFlowKnowledgeError as exc:
        return str(exc)
    return chunks if chunks else "ragflow_no_relevant_chunks"


def _ragflow_query(standard_no: str, target_fields: set[str], query: str) -> str:
    labels = {
        "outer_diameter": "外径 内径 直径",
        "inner_diameter": "内径 外径 直径",
        "free_length": "自由高度 自由长度",
        "total_coils": "总圈数",
        "perpendicularity": "垂直度",
        "straightness": "直线度",
        "spring_rate": "刚度",
        "solid_height": "压并高度",
        "permanent_set_limit": "永久变形",
        "load_points": "载荷 指定高度 指定负荷",
    }
    terms = [labels[field] for field in target_fields if field in labels]
    return " ".join(part for part in (standard_no, " ".join(terms), query) if part).strip()


def _feature_value(features: dict[str, Any], field: str) -> Any:
    value = features.get(field)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _is_general_chunk(metadata: dict[str, Any]) -> bool:
    return metadata.get("rule_topic") in {"scope_accuracy_permanent_set", "symbol_definitions"}
