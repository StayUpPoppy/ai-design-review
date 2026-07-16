from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standard_knowledge import retrieve_standard_chunks, standard_references
from ai_design_review.standard_selector import select_standard


def main() -> None:
    _assert_cold_diameter_chunk_retrieval()
    _assert_hot_alias_retrieval()
    _assert_formula_chunk_retrieval()
    _assert_standard_selector_references_are_available()
    print("standard knowledge test passed")


def _assert_cold_diameter_chunk_retrieval() -> None:
    chunks = retrieve_standard_chunks(
        standard_no="GB/T 1239.2-2009",
        spring_type="compression_spring",
        target_fields=["outer_diameter"],
        query="外径 内径 公差 表3-11",
        limit=3,
    )
    assert chunks
    assert chunks[0]["chunk_id"] == "gbt_1239_2_2009__diameter_tolerance__table_3_11"
    assert chunks[0]["metadata"]["table_no"] == "表3-11"


def _assert_hot_alias_retrieval() -> None:
    chunks = retrieve_standard_chunks(
        standard_no="GB/T 23934-2014",
        spring_type="compression_spring",
        spring_features={"manufacturing_method": {"value": "hot_coiled"}},
        target_fields=["free_length"],
        query="自由高度 极限偏差 表4-9",
        limit=3,
    )
    assert chunks
    assert chunks[0]["chunk_id"] == "gbt_23934_2015__free_length_tolerance__table_4_9"
    assert chunks[0]["metadata"]["standard_no"] == "GB/T 23934-2015"


def _assert_formula_chunk_retrieval() -> None:
    chunks = retrieve_standard_chunks(
        standard_no="GB/T 1239.2-2009",
        spring_type="compression_spring",
        spring_features={
            "spring_family": {"value": "helical"},
            "spring_shape": {"value": "cylindrical"},
            "wire_section": {"value": "round"},
        },
        target_fields=["spring_rate"],
        query="理论刚度 公式 G d D 有效圈数",
        limit=6,
    )
    assert any(item["chunk_id"] == "compression_spring__theoretical_stiffness_formula" for item in chunks)


def _assert_standard_selector_references_are_available() -> None:
    references = standard_references("GB/T 23934-2014", target_fields=["free_length"])
    assert references
    assert references[0]["source"] == "local_standard_knowledge"
    assert references[0]["status"] == "available"

    selection = select_standard(
        "compression_spring",
        {
            "wire_diameter": {"value": 12, "unit": "mm", "confidence": 0.96},
            "outer_diameter": {"value": 80, "unit": "mm"},
            "free_length": {"value": 200, "unit": "mm"},
            "total_coils": {"value": 8, "unit": "turns"},
        },
        {
            "spring_family": {"value": "helical"},
            "spring_shape": {"value": "cylindrical"},
            "manufacturing_method": {"value": "unknown"},
            "wire_section": {"value": "round"},
            "pitch_type": {"value": "constant"},
        },
    )
    assert selection["selected_standard"] == "GB/T 23934-2014"
    assert selection["references"]
    assert selection["references"][0]["status"] == "available"


if __name__ == "__main__":
    main()
