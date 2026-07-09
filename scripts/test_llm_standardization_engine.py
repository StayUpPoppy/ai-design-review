from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.llm_standardization_engine import LLMStandardizationEngine


def main() -> None:
    _assert_engine_generates_hot_coiled_suggestions_from_rag_chunks()
    print("llm standardization engine test passed")


def _assert_engine_generates_hot_coiled_suggestions_from_rag_chunks() -> None:
    seen_request = {}

    def fake_completion(request: dict) -> dict:
        seen_request.update(request)
        chunk_ids = [chunk["chunk_id"] for chunk in request["chunks"]]
        assert "gbt_23934_2015__free_length_tolerance__table_4_9" in chunk_ids
        assert "free_length" in request["allowed_target_fields"]
        return {
            "standardization_results": [
                {
                    "target_field": "free_length",
                    "suggested_value": 300,
                    "suggested_tolerance_upper": 6,
                    "suggested_tolerance_lower": -6,
                    "unit": "mm",
                    "standard_no": "GB/T 23934-2015",
                    "rule_id": "LLM-RAG-HOT-FREE",
                    "basis": "依据 gbt_23934_2015__free_length_tolerance__table_4_9：2级自由高度极限偏差 ±max(0.02H0, 3.0)，H0=300，结果 ±6mm。",
                    "status": "suggested",
                    "need_human_review": True,
                    "confidence": 0.82,
                    "references": [{"chunk_id": "gbt_23934_2015__free_length_tolerance__table_4_9", "table_no": "表4-9"}],
                }
            ]
        }

    review = _hot_review()
    payload = LLMStandardizationEngine(completion_fn=fake_completion).standardize_review(review)
    assert payload["status"] == "generated"
    assert payload["retrieved_chunks"]
    assert seen_request["standard_no"] == "GB/T 23934-2014"

    item = payload["standardization_results"][0]
    assert item["target_field"] == "free_length"
    assert item["status"] == "llm_suggested"
    assert item["need_human_review"] is True
    assert item["metadata"]["source"] == "llm_standardization"
    assert item["metadata"]["target_field_valid"] is True
    assert item["metadata"]["rag_references"]


def _hot_review() -> dict:
    return {
        "drawing_summary": {
            "spring_type": "compression_spring",
            "spring_type_label": "压缩弹簧",
        },
        "spring_features": {
            "spring_family": {"value": "helical"},
            "spring_shape": {"value": "cylindrical"},
            "manufacturing_method": {"value": "hot_coiled"},
            "wire_section": {"value": "round"},
            "pitch_type": {"value": "constant"},
        },
        "standard_selection": {
            "selected_standard": "GB/T 23934-2014",
            "status": "rules_pending",
            "need_human_review": True,
        },
        "spring_parameters": {
            "wire_diameter": {"value": 12, "unit": "mm"},
            "outer_diameter": {"value": 96, "unit": "mm"},
            "mean_diameter": {"value": 84, "unit": "mm"},
            "free_length": {"value": 300, "unit": "mm"},
            "total_coils": {"value": 8, "unit": "turns"},
            "active_coils": {"value": 6, "unit": "turns"},
            "accuracy_grade": {"value": "2级"},
            "load_points": [{"label": "F1", "height": 240, "height_unit": "mm", "force": 1000, "force_unit": "N"}],
        },
        "derived_parameters": {
            "spring_index": {"value": 7},
            "slenderness_ratio": {"value": 3.5714},
            "load_point_deflections": [{"label": "F1", "deflection": 60}],
        },
        "standardization_results": [],
    }


if __name__ == "__main__":
    main()
