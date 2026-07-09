from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .io_utils import project_path, read_json


DEFAULT_KNOWLEDGE_PATH = project_path("config", "standard_knowledge", "compression_spring_tolerance_chunks.json")


def retrieve_standard_chunks(
    *,
    standard_no: str | None = None,
    spring_type: str | None = None,
    spring_features: dict[str, Any] | None = None,
    target_fields: list[str] | tuple[str, ...] | set[str] | None = None,
    query: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Retrieve standard manual chunks with metadata filters and lexical scoring.

    This is the local MVP retrieval layer. It deliberately keeps the chunk
    schema close to a vector DB payload so the backend can later swap the
    scoring implementation for embeddings without changing callers.
    """

    target_set = {str(item) for item in target_fields or [] if item}
    features = spring_features or {}
    chunks = []
    for chunk in load_standard_knowledge():
        metadata = chunk.get("metadata") or {}
        if standard_no and not _standard_matches(metadata, standard_no):
            continue
        if spring_type and metadata.get("spring_category") and metadata.get("spring_category") != spring_type:
            continue
        if not _features_match(metadata, features):
            continue
        score = _score_chunk(chunk, target_set, query or "")
        chunks.append(_public_chunk(chunk, score))
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
    return [
        {
            "standard_no": chunk["metadata"].get("standard_no") or standard_no,
            "chunk_id": chunk["chunk_id"],
            "title": chunk["title"],
            "source": "local_standard_knowledge",
            "status": "available",
            "score": chunk["score"],
            "metadata": {
                "rule_topic": chunk["metadata"].get("rule_topic"),
                "table_no": chunk["metadata"].get("table_no"),
                "target_fields": chunk["metadata"].get("target_fields", []),
            },
        }
        for chunk in chunks
    ]


@lru_cache(maxsize=1)
def load_standard_knowledge(path: str | Path | None = None) -> list[dict[str, Any]]:
    payload = read_json(Path(path) if path else DEFAULT_KNOWLEDGE_PATH)
    chunks = payload.get("chunks", []) if isinstance(payload, dict) else []
    return [chunk for chunk in chunks if isinstance(chunk, dict)]


def _standard_matches(metadata: dict[str, Any], standard_no: str) -> bool:
    needle = _normalize_standard_no(standard_no)
    candidates = [metadata.get("standard_no"), *(metadata.get("standard_aliases") or [])]
    return any(_normalize_standard_no(candidate) == needle for candidate in candidates if candidate)


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


def _public_chunk(chunk: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "chunk_id": chunk.get("chunk_id"),
        "title": chunk.get("title"),
        "content": chunk.get("content"),
        "metadata": chunk.get("metadata") or {},
        "score": score,
    }


def _tokens(text: str) -> list[str]:
    normalized = str(text or "").lower()
    raw_tokens = re.findall(r"[a-z0-9_.+-]+|[\u4e00-\u9fff]{2,}", normalized)
    tokens = []
    for token in raw_tokens:
        tokens.append(token)
        if len(token) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _normalize_standard_no(value: Any) -> str:
    text = str(value or "").upper()
    text = text.replace("—", "-").replace("–", "-").replace(" ", "")
    text = text.replace("GBT", "GB/T")
    text = re.sub(r"[^A-Z0-9/.-]", "", text)
    return text


def _feature_value(features: dict[str, Any], field: str) -> Any:
    value = features.get(field)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _is_general_chunk(metadata: dict[str, Any]) -> bool:
    return metadata.get("rule_topic") in {"scope_accuracy_permanent_set", "symbol_definitions"}
