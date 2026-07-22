from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.ragflow_knowledge import RAGFlowKnowledgeClient, RAGFlowKnowledgeConfig
from ai_design_review.standard_knowledge import retrieve_standard_chunks


COLD_STANDARD = "GB/T 1239.2-2009"
HOT_STANDARD = "GB/T 23934-2015"
COLD_DOCUMENT_ID = "cold-document"
HOT_DOCUMENT_ID = "hot-document"


def main() -> None:
    _assert_ragflow_retrieval_is_document_scoped()
    _assert_configuration_and_request_failures_fall_back_to_local_knowledge()
    _assert_empty_ragflow_result_falls_back_to_local_knowledge()
    _assert_health_status_does_not_expose_credentials()
    print("ragflow knowledge test passed")


def _config() -> RAGFlowKnowledgeConfig:
    return RAGFlowKnowledgeConfig(
        base_url="http://ragflow.example",
        api_key="secret-for-test-only",
        compression_dataset_id="compression-dataset",
        standard_document_ids={COLD_STANDARD: COLD_DOCUMENT_ID, HOT_STANDARD: HOT_DOCUMENT_ID},
        dataset_name="压缩弹簧",
    )


def _assert_ragflow_retrieval_is_document_scoped() -> None:
    seen_payload: dict = {}

    def request(method: str, url: str, **kwargs: object) -> dict:
        assert method == "POST"
        assert url.endswith("/api/v1/retrieval")
        seen_payload.update(kwargs["json"])
        return {
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "id": "cold-chunk",
                        "content": "GB/T 1239.2-2009 表3-11 外径极限偏差。",
                        "document_id": COLD_DOCUMENT_ID,
                        "document_name": "冷卷圆柱螺旋压缩弹簧公差标准摘录.md",
                        "positions": [[3, 0, 0, 0, 0]],
                        "similarity": 0.91,
                    },
                    {
                        "id": "hot-chunk-should-be-filtered",
                        "content": "GB/T 23934-2015 表4-8。",
                        "document_id": HOT_DOCUMENT_ID,
                        "document_name": "热卷圆柱螺旋压缩弹簧公差标准摘录.md",
                        "similarity": 0.99,
                    },
                ]
            },
        }

    chunks = retrieve_standard_chunks(
        standard_no=COLD_STANDARD,
        spring_type="compression_spring",
        target_fields=["outer_diameter"],
        query="外径公差",
        ragflow_client=RAGFlowKnowledgeClient(_config(), request),
    )
    assert seen_payload["dataset_ids"] == ["compression-dataset"]
    assert seen_payload["document_ids"] == [COLD_DOCUMENT_ID]
    assert chunks and chunks[0]["source"] == "ragflow"
    assert chunks[0]["document_id"] == COLD_DOCUMENT_ID
    assert chunks[0]["metadata"]["table_no"] == "表3-11"


def _assert_configuration_and_request_failures_fall_back_to_local_knowledge() -> None:
    unconfigured = RAGFlowKnowledgeClient(
        RAGFlowKnowledgeConfig(None, None, None, {}),
    )
    chunks = retrieve_standard_chunks(
        standard_no=COLD_STANDARD,
        spring_type="compression_spring",
        target_fields=["outer_diameter"],
        ragflow_client=unconfigured,
    )
    assert chunks and chunks[0]["source"] == "local_standard_knowledge"
    assert chunks[0]["retrieval_status"] == "fallback"
    assert chunks[0]["retrieval_reason"] == "ragflow_credentials_missing"

    def timeout(*_args: object, **_kwargs: object) -> dict:
        raise TimeoutError("simulated timeout")

    chunks = retrieve_standard_chunks(
        standard_no=COLD_STANDARD,
        spring_type="compression_spring",
        target_fields=["outer_diameter"],
        ragflow_client=RAGFlowKnowledgeClient(_config(), timeout),
    )
    assert chunks[0]["retrieval_status"] == "fallback"
    assert chunks[0]["retrieval_reason"] == "ragflow_request_failed:TimeoutError"


def _assert_empty_ragflow_result_falls_back_to_local_knowledge() -> None:
    def empty(*_args: object, **_kwargs: object) -> dict:
        return {"code": 0, "data": {"chunks": []}}

    chunks = retrieve_standard_chunks(
        standard_no=HOT_STANDARD,
        spring_type="compression_spring",
        target_fields=["free_length"],
        ragflow_client=RAGFlowKnowledgeClient(_config(), empty),
    )
    assert chunks and chunks[0]["source"] == "local_standard_knowledge"
    assert chunks[0]["retrieval_reason"] == "ragflow_no_relevant_chunks"


def _assert_health_status_does_not_expose_credentials() -> None:
    status = RAGFlowKnowledgeClient(RAGFlowKnowledgeConfig(None, None, None, {})).health()
    assert status["status"] == "not_configured"
    assert "api_key" not in status


if __name__ == "__main__":
    main()
