from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardizers.diameters import apply_formula_compression_diameter_completion  # noqa: E402


def main() -> None:
    _assert_inferred_outer_is_refreshed_from_inner_and_wire()
    _assert_missing_diameters_are_completed()
    _assert_direct_drawing_dimensions_are_preserved()
    _assert_human_value_is_preserved()
    print("compression diameter completion tests passed")


def _assert_inferred_outer_is_refreshed_from_inner_and_wire() -> None:
    parameters = {
        "wire_diameter": {"value": 2.3, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注线径 φ2.3"},
        "inner_diameter": {"value": 16, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注内径 φ16"},
        "mean_diameter": {"value": 18.3, "unit": "mm", "source": ["qwen_vision"], "evidence": "由内径16+线径2.3计算得出"},
        "outer_diameter": {
            "value": 16,
            "unit": "mm",
            "source": ["dimension_role_ranker", "qwen_vision"],
            "evidence": "候选依据：φ16 | 由内径16+2×线径2.3计算得出，图纸未直接标注外径",
        },
    }

    result = apply_formula_compression_diameter_completion(parameters)

    assert result["applied_fields"] == ["outer_diameter", "mean_diameter"]
    assert parameters["outer_diameter"]["value"] == 20.6
    assert parameters["outer_diameter"]["source"] == ["formula_calculation"]
    assert parameters["outer_diameter"]["formula"] == "Do = Di + 2d"
    assert parameters["mean_diameter"]["value"] == 18.3


def _assert_missing_diameters_are_completed() -> None:
    parameters = {
        "wire_diameter": {"value": 2, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注线径 φ2"},
        "inner_diameter": {"value": 16, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注内径 φ16"},
    }
    apply_formula_compression_diameter_completion(parameters)
    assert parameters["outer_diameter"]["value"] == 20
    assert parameters["mean_diameter"]["value"] == 18


def _assert_direct_drawing_dimensions_are_preserved() -> None:
    parameters = {
        "wire_diameter": {"value": 7, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注线径 φ7"},
        "inner_diameter": {"value": 40, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注内径 φ40"},
        "outer_diameter": {"value": 47, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注外径 φ47"},
    }
    result = apply_formula_compression_diameter_completion(parameters)
    assert result["applied_fields"] == ["mean_diameter"]
    assert parameters["outer_diameter"]["value"] == 47
    assert parameters["inner_diameter"]["value"] == 40
    assert parameters["mean_diameter"]["value"] == 43.5


def _assert_human_value_is_preserved() -> None:
    parameters = {
        "wire_diameter": {"value": 2.3, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注线径 φ2.3"},
        "inner_diameter": {"value": 16, "unit": "mm", "source": ["qwen_vision"], "evidence": "图纸标注内径 φ16"},
        "outer_diameter": {"value": 21, "unit": "mm", "source": ["human_edited"], "evidence": "人工确认"},
    }
    apply_formula_compression_diameter_completion(parameters)
    assert parameters["outer_diameter"]["value"] == 21
    assert parameters["outer_diameter"]["source"] == ["human_edited"]


if __name__ == "__main__":
    main()
