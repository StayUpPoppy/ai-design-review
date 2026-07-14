from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.api import _needs_dimension_grounding_ocr  # noqa: E402


def main() -> None:
    file_info = {"kind": "pdf"}

    unanchored = [
        _candidate("spring_type", "compression_spring", "compression spring", 0.9),
        _candidate("outer_diameter", 12.5, "roughness triangle 12.5", 0.88),
        _candidate("free_length", 25, "overall size 25", 0.82),
    ]
    assert _needs_dimension_grounding_ocr(unanchored, file_info, ["qwen_vision"])

    anchored = [
        _candidate("spring_type", "compression_spring", "compression spring", 0.9),
        _candidate(
            "outer_diameter",
            25,
            "vertical diameter 25 / 0/-0.02",
            0.9,
            tolerance_upper=0,
            tolerance_lower=-0.02,
        ),
        _candidate("free_length", 15, "axial free length between ends 15", 0.9),
    ]
    assert not _needs_dimension_grounding_ocr(anchored, file_info, ["qwen_vision"])
    assert not _needs_dimension_grounding_ocr(unanchored, file_info, ["qwen_vision", "rapidocr"])
    print("dimension grounding OCR tests passed")


def _candidate(
    field: str,
    value,
    evidence: str,
    confidence: float,
    *,
    tolerance_upper=None,
    tolerance_lower=None,
) -> dict:
    return {
        "field": field,
        "value": value,
        "source": "qwen_vision",
        "evidence": evidence,
        "suggested_region": "Qwen vision recognition",
        "confidence": confidence,
        "tolerance_upper": tolerance_upper,
        "tolerance_lower": tolerance_lower,
    }


if __name__ == "__main__":
    main()
