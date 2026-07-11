from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.dimension_roles import apply_compression_dimension_role_ranking  # noqa: E402
from ai_design_review.fusion import fuse_candidates  # noqa: E402


def main() -> None:
    test_reassigns_vertical_diameter_and_axis_length()
    test_preserves_explicit_labeled_dimensions()
    test_skips_non_compression_context()
    print("dimension role tests passed")


def test_reassigns_vertical_diameter_and_axis_length() -> None:
    candidates = [
        _note(
            """
            UQD06外弹簧(钢珠型)
            F2=15.3N±10%
            F1=11.9N±10%
            9.474
            11.414
            15
            12.5
            25
            技术要求
            4.力值要求: H1压缩到11.414mm/F1=11.9N±10%; H2压缩到9.474mm/F2=15.3N±10%
            """
        ),
        _candidate("load_point", {"label": "F1", "height": 11.414, "force": 11.9}, "ocr", "H1/F1", 0.78),
        _candidate("load_point", {"label": "F2", "height": 9.474, "force": 15.3}, "ocr", "H2/F2", 0.78),
        _candidate("outer_diameter", 12.5, "qwen_vision", "局部竖向尺寸 12.5", 0.78),
        _candidate("free_length", 25, "rapidocr", "OCR 将竖排外径数字误归为自由长度 25", 0.62),
        _candidate(
            "outer_diameter",
            25,
            "rapidocr",
            "竖排直径数字 25 / 0/-0.02",
            0.66,
            tolerance_upper=0,
            tolerance_lower=-0.02,
        ),
    ]

    fused = fuse_candidates(apply_compression_dimension_role_ranking(candidates))
    assert fused["fields"]["outer_diameter"]["value"] == 25, fused["fields"]["outer_diameter"]
    assert fused["fields"]["free_length"]["value"] == 15, fused["fields"]["free_length"]
    assert "dimension_role_ranker" in fused["fields"]["outer_diameter"]["source"]
    assert "dimension_role_ranker" in fused["fields"]["free_length"]["source"]


def test_preserves_explicit_labeled_dimensions() -> None:
    candidates = [
        _note("压缩弹簧 H1=18mm/F1=5N 外径12.5 自由长度20"),
        _candidate("load_point", {"label": "F1", "height": 18, "force": 5}, "ocr", "H1/F1", 0.78),
        _candidate("outer_diameter", 12.5, "ocr", "外径12.5", 0.82),
        _candidate("free_length", 20, "ocr", "自由长度20", 0.82),
    ]

    fused = fuse_candidates(apply_compression_dimension_role_ranking(candidates))
    assert fused["fields"]["outer_diameter"]["value"] == 12.5, fused["fields"]["outer_diameter"]
    assert fused["fields"]["free_length"]["value"] == 20, fused["fields"]["free_length"]


def test_skips_non_compression_context() -> None:
    candidates = [
        _note("扭簧 臂长20 工作角35°"),
        _candidate("outer_diameter", 12.5, "ocr", "12.5", 0.82),
    ]
    enriched = apply_compression_dimension_role_ranking(candidates)
    assert len(enriched) == len(candidates)


def _note(text: str) -> dict:
    return {
        "field": "document_text_1",
        "feature_type": "note",
        "value": text,
        "source": "ocr",
        "evidence": text,
        "confidence": 0.74,
    }


def _candidate(
    field: str,
    value,
    source: str,
    evidence: str,
    confidence: float,
    *,
    tolerance_upper=None,
    tolerance_lower=None,
) -> dict:
    return {
        "field": field,
        "feature_type": "dimension",
        "value": value,
        "unit": "mm",
        "source": source,
        "evidence": evidence,
        "confidence": confidence,
        "tolerance_upper": tolerance_upper,
        "tolerance_lower": tolerance_lower,
    }


if __name__ == "__main__":
    main()
