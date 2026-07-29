from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardizers.compression import standardize_compression_spring  # noqa: E402
from ai_design_review.standardizers.stiffness import (  # noqa: E402
    apply_formula_compression_spring_rate,
    calculate_compression_spring_rate,
)
from ai_design_review.workflow import DrawingReviewWorkflow  # noqa: E402
from ai_design_review.io_utils import project_path, read_json  # noqa: E402


def main() -> None:
    _assert_material_profiles()
    _assert_geometry_resolution()
    _assert_missing_and_inapplicable_context()
    _assert_source_precedence_and_refresh()
    _assert_standardization_uses_formula_rate()
    _assert_deferred_workflow_populates_formula_rate()
    print("compression stiffness tests passed")


def _assert_material_profiles() -> None:
    profiles = {
        "SUS304": 71000,
        "SUS316": 71000,
        "17-7PH": 78000,
        "Inconel X750": 79000,
        "Inconel 718": 78500,
    }
    for material, shear_modulus in profiles.items():
        result = calculate_compression_spring_rate(_parameters(material=material))
        expected = round(shear_modulus / (8 * 9**3 * 5), 4)
        assert result["status"] == "calculated"
        assert result["value"] == expected
        assert result["inputs"]["shear_modulus_mpa"] == shear_modulus


def _assert_geometry_resolution() -> None:
    recognized_mean = _parameters(material="SUS304", mean=7)
    result = calculate_compression_spring_rate(recognized_mean)
    assert result["inputs"]["mean_diameter_mm"] == 7
    assert result["source_fields"] == ["material", "wire_diameter", "mean_diameter", "active_coils"]

    inner_only = _parameters(material="SUS304", outer=None, inner=8)
    result = calculate_compression_spring_rate(inner_only)
    assert result["inputs"]["mean_diameter_mm"] == 9
    assert "inner_diameter" in result["source_fields"]

    active_default = _parameters(material="SUS304", active=None, total=7, end_type="两端并紧")
    result = calculate_compression_spring_rate(active_default)
    assert result["inputs"]["active_coils"] == 5
    assert "total_coils" in result["source_fields"]


def _assert_missing_and_inapplicable_context() -> None:
    missing = calculate_compression_spring_rate(_parameters(material=None))
    assert missing["status"] == "missing_context"
    assert missing["missing_fields"] == ["material"]

    unknown_material = calculate_compression_spring_rate(_parameters(material="SWP-B"))
    assert unknown_material["status"] == "material_not_configured"

    incompatible = calculate_compression_spring_rate(
        _parameters(material="SUS304"),
        {"wire_section": {"value": "rectangular"}},
    )
    assert incompatible["status"] == "not_applicable"


def _assert_source_precedence_and_refresh() -> None:
    drawing = _parameters(material="SUS304")
    drawing["spring_rate"] = {"value": 9, "unit": "N/mm", "source": ["qwen_vision"]}
    preserved = apply_formula_compression_spring_rate(drawing)
    assert preserved["applied"] is False
    assert drawing["spring_rate"]["value"] == 9

    formula = _parameters(material="SUS304")
    first = apply_formula_compression_spring_rate(formula)
    assert first["applied"] is True
    first_value = formula["spring_rate"]["value"]
    formula["outer_diameter"]["value"] = 12
    refreshed = apply_formula_compression_spring_rate(formula)
    assert refreshed["applied"] is True
    assert formula["spring_rate"]["value"] != first_value

    formula["spring_rate"]["source"] = ["formula_calculation", "human_confirmed"]
    formula["outer_diameter"]["value"] = 13
    confirmed_refresh = apply_formula_compression_spring_rate(formula)
    assert confirmed_refresh["applied"] is True

    formula["spring_rate"]["value"] = 22
    formula["spring_rate"]["source"] = ["formula_calculation", "human_edited"]
    preserved_manual = apply_formula_compression_spring_rate(formula)
    assert preserved_manual["applied"] is False
    assert formula["spring_rate"]["value"] == 22

    missing_after_formula = _parameters(material="SUS304")
    apply_formula_compression_spring_rate(missing_after_formula)
    missing_after_formula["material"]["value"] = None
    missing_after_formula["material"]["standard_value"] = None
    missing_after_formula["material"]["source"] = ["human_edited"]
    cleared = apply_formula_compression_spring_rate(missing_after_formula)
    assert cleared["status"] == "missing_context"
    assert missing_after_formula["spring_rate"]["value"] is None
    assert missing_after_formula["spring_rate"]["evidence"] == ""


def _assert_standardization_uses_formula_rate() -> None:
    parameters = _parameters(material="SUS304")
    parameters["accuracy_grade"] = {"value": "2级"}
    payload = standardize_compression_spring(parameters)
    stiffness = next(item for item in payload["standardization_results"] if item["rule_id"] == "GBT1239.2-STIFF")
    assert parameters["spring_rate"]["source"] == ["formula_calculation"]
    assert stiffness["suggested_value"] == parameters["spring_rate"]["value"]
    assert math.isclose(stiffness["suggested_tolerance_upper"], parameters["spring_rate"]["value"] * 0.1, abs_tol=0.0001)


def _assert_deferred_workflow_populates_formula_rate() -> None:
    workflow = DrawingReviewWorkflow(read_json(project_path("config", "factory_rules.json")))
    review = workflow.run(
        None,
        [
            _candidate("drawing_name", "压缩弹簧"),
            _candidate("material", "SUS304"),
            _candidate("wire_diameter", 1, unit="mm"),
            _candidate("outer_diameter", 10, unit="mm"),
            _candidate("free_length", 20, unit="mm"),
            _candidate("total_coils", 7, unit="turns"),
            _candidate("end_type", "两端并紧"),
            _candidate("handedness", "右旋"),
        ],
        run_standardization=False,
    )
    rate = review["spring_parameters"]["spring_rate"]
    assert rate["value"] == round(71000 / (8 * 9**3 * 5), 4)
    assert rate["source"] == ["formula_calculation"]
    assert review["standardization_results"] == []


def _parameters(
    *,
    material: str | None,
    outer: float | None = 10,
    inner: float | None = None,
    mean: float | None = None,
    total: float = 7,
    active: float | None = 5,
    end_type: str | None = None,
) -> dict:
    parameters = {
        "material": {"value": material, "standard_value": material},
        "wire_diameter": {"value": 1, "unit": "mm"},
        "total_coils": {"value": total, "unit": "turns"},
    }
    if outer is not None:
        parameters["outer_diameter"] = {"value": outer, "unit": "mm"}
    if inner is not None:
        parameters["inner_diameter"] = {"value": inner, "unit": "mm"}
    if mean is not None:
        parameters["mean_diameter"] = {"value": mean, "unit": "mm"}
    if active is not None:
        parameters["active_coils"] = {"value": active, "unit": "turns"}
    if end_type is not None:
        parameters["end_type"] = {"value": end_type}
    return parameters


def _candidate(field: str, value, *, unit: str | None = None) -> dict:
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "source": "test",
        "evidence": f"{field}={value}",
        "confidence": 0.95,
        "page": 1,
    }


if __name__ == "__main__":
    main()
