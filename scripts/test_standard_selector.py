from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standard_selector import select_standard
from ai_design_review.standardizers import standardize_spring


def main() -> None:
    _assert_cold_standard_no_selects_local_rules()
    _assert_hot_standard_no_is_rules_pending()
    _assert_wire_diameter_threshold_selects_standard()
    _assert_wire_diameter_boundary()
    _assert_standard_no_conflict_requires_review()
    _assert_low_confidence_wire_requires_review()
    _assert_llm_low_confidence_requires_review()
    _assert_non_cylindrical_is_not_applicable()
    print("standard selector test passed")


def _base_parameters(
    standard_no: str | None = None,
    *,
    wire_diameter: float | None = 2,
    wire_confidence: float = 0.96,
    wire_need_review: bool = False,
) -> dict:
    params = {
        "outer_diameter": {"value": 20, "unit": "mm"},
        "free_length": {"value": 30, "unit": "mm"},
        "total_coils": {"value": 12, "unit": "turns"},
        "active_coils": {"value": 8, "unit": "turns"},
        "accuracy_grade": {"value": "2级"},
        "diameter_accuracy_grade": {"value": "2级"},
        "free_length_accuracy_grade": {"value": "2级"},
        "load_accuracy_grade": {"value": "2级"},
        "end_grinding": {"value": "两端磨平"},
        "load_points": [],
    }
    if wire_diameter is not None:
        params["wire_diameter"] = {
            "value": wire_diameter,
            "unit": "mm",
            "confidence": wire_confidence,
            "need_human_review": wire_need_review,
        }
    if standard_no:
        params["standard_no"] = {"value": standard_no}
    return params


def _features(**overrides: str) -> dict:
    base = {
        "spring_family": {"value": "helical", "confidence": 0.9, "evidence": "圆柱螺旋压缩弹簧"},
        "spring_shape": {"value": "cylindrical", "confidence": 0.9, "evidence": "圆柱螺旋压缩弹簧"},
        "manufacturing_method": {"value": "unknown", "confidence": 0.3, "evidence": ""},
        "wire_section": {"value": "round", "confidence": 0.75, "evidence": "圆线"},
        "pitch_type": {"value": "constant", "confidence": 0.7, "evidence": "等节距"},
    }
    for key, value in overrides.items():
        base[key] = {"value": value, "confidence": 0.9, "evidence": value}
    return base


def _assert_cold_standard_no_selects_local_rules() -> None:
    selection = select_standard("compression_spring", _base_parameters("GB/T 1239.2-2009"), _features())
    assert selection["selected_standard"] == "GB/T 1239.2-2009"
    assert selection["status"] == "applicable"
    assert selection["rules_available"] is True
    assert selection["need_human_review"] is False

    payload = standardize_spring("compression_spring", _base_parameters("GB/T 1239.2-2009"), _features())
    assert payload["standard_selection"]["status"] == "applicable"
    assert payload["standardization_results"]


def _assert_hot_standard_no_is_rules_pending() -> None:
    payload = standardize_spring("compression_spring", _base_parameters("GB/T 23934-2014"), _features())
    assert payload["standard_selection"]["selected_standard"] == "GB/T 23934-2015"
    assert payload["standard_selection"]["status"] == "rules_pending"
    assert payload["standardization_results"] == []
    assert payload["derived_parameters"]["mean_diameter"]["value"] == 18


def _assert_wire_diameter_threshold_selects_standard() -> None:
    selection = select_standard("compression_spring", _base_parameters(wire_diameter=1.5), _features())
    assert selection["selected_standard"] == "GB/T 1239.2-2009"
    assert selection["status"] == "applicable"
    assert selection["selection_source"] == "wire_diameter_threshold"
    assert selection["metadata"]["wire_diameter_mm"] == 1.5
    assert selection["metadata"]["wire_diameter_threshold_mm"] == 8.0


def _assert_wire_diameter_boundary() -> None:
    cold = select_standard("compression_spring", _base_parameters(wire_diameter=7.99), _features())
    hot_at_boundary = select_standard("compression_spring", _base_parameters(wire_diameter=8), _features())
    hot = select_standard("compression_spring", _base_parameters(wire_diameter=12), _features())
    assert cold["selected_standard"] == "GB/T 1239.2-2009"
    assert hot_at_boundary["selected_standard"] == "GB/T 23934-2015"
    assert hot_at_boundary["status"] == "rules_pending"
    assert hot["selected_standard"] == "GB/T 23934-2015"


def _assert_standard_no_conflict_requires_review() -> None:
    selection = select_standard("compression_spring", _base_parameters("GB/T 1239.2-2009", wire_diameter=12), _features())
    assert selection["selected_standard"] == "GB/T 1239.2-2009"
    assert selection["status"] == "need_review"
    assert selection["need_human_review"] is True
    assert selection["metadata"]["conflicts"]


def _assert_low_confidence_wire_requires_review() -> None:
    selection = select_standard(
        "compression_spring",
        _base_parameters(wire_diameter=1.5, wire_confidence=0.62, wire_need_review=True),
        _features(),
    )
    assert selection["selected_standard"] == "GB/T 1239.2-2009"
    assert selection["status"] == "need_review"
    assert selection["need_human_review"] is True


def _assert_llm_low_confidence_requires_review() -> None:
    selection = select_standard(
        "compression_spring",
        _base_parameters(wire_diameter=None),
        _features(),
        {
            "value": {
                "selected_standard": "GB/T 1239.2-2009",
                "manufacturing_method": "cold_coiled",
                "confidence": 0.55,
                "evidence": ["线径较小，倾向冷卷"],
                "reason": "未识别到标准号，仅为模型推断",
                "need_human_review": True,
            }
        },
    )
    assert selection["selected_standard"] == "GB/T 1239.2-2009"
    assert selection["status"] == "need_review"
    assert selection["need_human_review"] is True


def _assert_non_cylindrical_is_not_applicable() -> None:
    selection = select_standard("compression_spring", _base_parameters(), _features(spring_shape="conical"))
    assert selection["status"] == "not_applicable"
    assert selection["selected_standard"] is None
    assert selection["need_human_review"] is True


if __name__ == "__main__":
    main()
