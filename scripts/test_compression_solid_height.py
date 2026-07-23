from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardizers.compression import (  # noqa: E402
    apply_formula_compression_solid_height,
    calculate_compression_solid_height,
    standardize_compression_spring,
)


def main() -> None:
    _assert_ground_formula_parameter()
    _assert_not_ground_formula()
    _assert_drawing_and_manual_values_are_preserved()
    _assert_missing_inputs_do_not_invent_a_value()
    _assert_standardization_populates_the_parameter()
    print("compression solid height test passed")


def _parameters(end_grinding: str = "两端磨平") -> dict:
    return {
        "wire_diameter": {"value": 0.9, "unit": "mm", "tolerance_upper": 0.05},
        "total_coils": {"value": 10, "unit": "turns"},
        "end_grinding": {"value": end_grinding},
    }


def _assert_ground_formula_parameter() -> None:
    parameters = _parameters()
    result = apply_formula_compression_solid_height(parameters)
    solid = parameters["solid_height"]
    assert result["status"] == "calculated"
    assert result["applied"] is True
    assert solid["value"] == 9.5
    assert solid["source"] == ["formula_calculation"]
    assert solid["formula"] == "Hb = n1 * dmax"
    assert solid["formula_calculation_inputs"]["max_wire_diameter_mm"] == 0.95

    parameters["wire_diameter"]["value"] = 1
    apply_formula_compression_solid_height(parameters)
    assert parameters["solid_height"]["value"] == 10.5


def _assert_not_ground_formula() -> None:
    result = calculate_compression_solid_height(_parameters("两端不磨"))
    assert result["status"] == "calculated"
    assert result["value"] == 10.925
    assert result["formula"] == "Hb = (n1 + 1.5) * dmax"


def _assert_drawing_and_manual_values_are_preserved() -> None:
    drawing_parameters = _parameters()
    drawing_parameters["solid_height"] = {"value": 12, "unit": "mm", "source": ["qwen"]}
    drawing_result = apply_formula_compression_solid_height(drawing_parameters)
    assert drawing_result["applied"] is False
    assert drawing_parameters["solid_height"]["value"] == 12

    manual_parameters = _parameters()
    manual_parameters["solid_height"] = {"value": 13, "unit": "mm", "source": ["human_edited"]}
    manual_result = apply_formula_compression_solid_height(manual_parameters)
    assert manual_result["applied"] is False
    assert manual_parameters["solid_height"]["value"] == 13


def _assert_missing_inputs_do_not_invent_a_value() -> None:
    parameters = _parameters()
    parameters.pop("end_grinding")
    result = apply_formula_compression_solid_height(parameters)
    assert result["status"] == "missing_context"
    assert result["applied"] is False
    assert "solid_height" not in parameters
    assert result["missing_fields"] == ["end_grinding"]


def _assert_standardization_populates_the_parameter() -> None:
    parameters = _parameters()
    payload = standardize_compression_spring(parameters)
    assert parameters["solid_height"]["value"] == 9.5
    solid_result = next(item for item in payload["standardization_results"] if item["rule_id"] == "GBT1239.2-SOLID")
    assert solid_result["suggested_value"] == 9.5


if __name__ == "__main__":
    main()
