from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.io_utils import read_json
from ai_design_review.llm_standardization import LLM_STANDARDIZATION_FIELD
from ai_design_review.workflow import DrawingReviewWorkflow


def main() -> None:
    _assert_qwen_payload_carries_llm_standardization_results()
    _assert_workflow_maps_llm_standardization_results()
    print("llm standardization mapping test passed")


def _assert_qwen_payload_carries_llm_standardization_results() -> None:
    candidates = qwen_payload_to_candidates(
        {
            "spring_type": {"value": "compression_spring", "label": "压缩弹簧", "confidence": 0.9},
            "parameters": {
                "wire_diameter": {"value": 2, "unit": "mm", "confidence": 0.9},
            },
            "standardization_results": [
                {
                    "target_field": "outer_diameter",
                    "suggested_value": 20,
                    "suggested_tolerance_upper": 0.4,
                    "suggested_tolerance_lower": -0.4,
                    "unit": "mm",
                    "standard_no": "GB/T 1239.2-2009",
                    "rule_id": "LLM-DIA",
                    "basis": "RAG chunk: 表3-11。",
                    "status": "suggested",
                }
            ],
        }
    )
    field = next(item for item in candidates if item["field"] == LLM_STANDARDIZATION_FIELD)
    assert field["value"][0]["target_field"] == "outer_diameter"
    assert field["source"] == "qwen_vision"


def _assert_workflow_maps_llm_standardization_results() -> None:
    rules = read_json("config/factory_rules.json")
    workflow = DrawingReviewWorkflow(rules)
    review = workflow.run(
        None,
        [
            _candidate("document_text_qwen", "压缩弹簧", confidence=0.9),
            _candidate("material", "SUS304", confidence=0.96),
            _candidate("wire_diameter", 1.5, unit="mm", confidence=0.96),
            _candidate("outer_diameter", 25, unit="mm", confidence=0.9),
            _candidate("free_length", 15, unit="mm", confidence=0.9),
            _candidate("total_coils", 4, unit="turns", confidence=0.9),
            _candidate("active_coils", 3, unit="turns", confidence=0.9),
            _candidate("end_grinding", "两端磨平", confidence=0.9),
            {
                "field": "load_point",
                "value": {
                    "label": "F1",
                    "height": 11,
                    "height_unit": "mm",
                    "force": 10,
                    "force_unit": "N",
                },
                "source": "test",
                "evidence": "F1=10N",
                "confidence": 0.9,
                "page": 1,
            },
            {
                "field": LLM_STANDARDIZATION_FIELD,
                "value": [
                    {
                        "target_field": "outer_diameter",
                        "suggested_value": 25,
                        "suggested_tolerance_upper": 0.5,
                        "suggested_tolerance_lower": -0.5,
                        "unit": "mm",
                        "standard_no": "GB/T 1239.2-2009",
                        "rule_id": "LLM-DIA",
                        "basis": "RAG chunk: 表3-11，LLM 计算外径公差。",
                        "status": "suggested",
                        "confidence": 0.82,
                    },
                    {
                        "target_field": "load_points.F1.force",
                        "suggested_value": 10,
                        "suggested_tolerance_upper": 1,
                        "suggested_tolerance_lower": -1,
                        "unit": "N",
                        "standard_no": "GB/T 1239.2-2009",
                        "rule_id": "LLM-LOAD",
                        "basis": "RAG chunk: 表3-15，LLM 计算载荷公差。",
                        "status": "suggested",
                    },
                    {
                        "target_field": "outer_diameter_mm",
                        "suggested_value": 25,
                        "suggested_tolerance_upper": 0.5,
                        "suggested_tolerance_lower": -0.5,
                        "unit": "mm",
                        "rule_id": "LLM-UNKNOWN",
                        "basis": "字段名故意错误。",
                        "status": "suggested",
                    },
                ],
                "source": "llm_standardization",
                "evidence": "LLM standardization JSON",
                "confidence": 0.85,
                "page": 1,
            },
        ],
    )

    llm_diameter = next(item for item in review["standardization_results"] if item["rule_id"] == "LLM-DIA")
    assert llm_diameter["status"] == "llm_suggested"
    assert llm_diameter["need_human_review"] is True
    assert llm_diameter["metadata"]["target_field_valid"] is True
    assert llm_diameter["metadata"]["source"] == "llm_standardization"

    llm_load = next(item for item in review["standardization_results"] if item["rule_id"] == "LLM-LOAD")
    assert llm_load["target_field"] == "load_points.F1.force"
    assert llm_load["metadata"]["target_field_valid"] is True

    unmapped = next(item for item in review["standardization_results"] if item["rule_id"] == "LLM-UNKNOWN")
    assert unmapped["status"] == "unmapped"
    assert unmapped["metadata"]["target_field_valid"] is False
    assert review["llm_standardization_diagnostics"][0]["target_field"] == "outer_diameter_mm"


def _candidate(field: str, value, *, unit: str | None = None, confidence: float = 0.9) -> dict:
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "source": "test",
        "evidence": f"{field}={value}",
        "confidence": confidence,
        "page": 1,
    }


if __name__ == "__main__":
    main()
