from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_design_review.standardizers.design_checks import refresh_design_checks, calculate_design_checks
from ai_design_review.material_catalog import load_material_catalog
from ai_design_review.standardizers.compression import apply_formula_compression_solid_height


def near(actual, expected):
    if isinstance(expected, (float, int)):
        assert actual is not None and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-12), (actual, expected)
    else:
        assert actual == expected, (actual, expected)


def fixture_results():
    fixture = json.loads((ROOT / "data/test/compression_design_checks.json").read_text(encoding="utf-8"))
    results = []
    for case in fixture["cases"]:
        review = copy.deepcopy(fixture["base"])
        for field, value in case.get("overrides", {}).items():
            if isinstance(value, dict):
                review["spring_parameters"].setdefault(field, {}).update(value)
            else:
                review["spring_parameters"][field] = value
        review["spring_features"].update(case.get("features", {}))
        refresh_design_checks(review)
        checks = review["design_checks"]
        for key, expected in case["expected"].items():
            try:
                if key == "pitch":
                    near((review["spring_parameters"].get("pitch") or {}).get("value"), expected)
                elif key == "work":
                    assert len(checks["work_stresses"]) == len(expected)
                    for result, value in zip(checks["work_stresses"], expected):
                        near(result["value"], value)
                else:
                    near(checks["metrics"][key]["value"], expected)
            except AssertionError as error:
                raise AssertionError(case["name"], key, error) from error
        assert review["spring_parameters"]["spring_rate"]["value"] == 99
        json.dumps(checks, allow_nan=False)
        results.append({"name": case["name"], "review": review, "checks": checks})
    return fixture, results


def protections(fixture):
    r = copy.deepcopy(fixture["base"])
    refresh_design_checks(r)
    pitch = r["spring_parameters"]["pitch"]
    pitch.update(need_human_review=False, source=["formula_calculation", "human_confirmed"])
    r["spring_parameters"]["free_length"]["value"] = 40
    refresh_design_checks(r)
    assert pitch["value"] == 3.3 and pitch["derived_value_stale"]
    assert r["design_checks"]["metrics"]["unit_mass"]["value"] is None

    r["spring_parameters"]["free_length"]["value"] = 36
    refresh_design_checks(r)
    assert not pitch["derived_value_stale"]
    pitch.update(value=4, source=["formula_calculation", "human_edited"], need_human_review=True)
    refresh_design_checks(r)
    assert pitch["value"] == 4
    pitch["value"] = ""
    refresh_design_checks(r)
    assert pitch["value"] == ""
    r = copy.deepcopy(fixture["base"])
    r["spring_parameters"]["mean_diameter"].update(source=["derived"], source_fields=["outer_diameter"])
    r["spring_parameters"]["outer_diameter"] = {"value":20,"source":["derived"],"source_fields":["mean_diameter"]}
    refresh_design_checks(r)
    assert r["design_checks"]["metrics"]["theoretical_spring_rate"]["value"] is None
    r["design_checks"] = {"forged":True}
    refresh_design_checks(r)
    assert "forged" not in r["design_checks"]
    persisted = json.loads(json.dumps(r))
    refresh_design_checks(persisted)
    assert persisted["design_checks"] == r["design_checks"]
    r = copy.deepcopy(fixture["base"])
    r["spring_parameters"]["mean_diameter"].update(source=["formula_calculation"], source_fields=["outer_diameter", "wire_diameter"])
    refresh_design_checks(r)
    assert r["design_checks"]["metrics"]["theoretical_spring_rate"]["value"] is None, "Missing sources cannot leave an old automatic diameter usable"
    r = copy.deepcopy(fixture["base"])
    r["spring_parameters"]["support_coils"]["value"] = None
    refresh_design_checks(r)
    support = r["spring_parameters"]["support_coils"]
    assert support["value"] == 1 and support["need_human_review"]
    support.update(need_human_review=False, source=["formula_calculation", "human_confirmed"])
    r["spring_parameters"]["active_coils"]["value"] = 9
    refresh_design_checks(r)
    assert support["value"] == 1 and support["derived_value_stale"]
    assert r["design_checks"]["metrics"]["unit_mass"]["value"] is None
    r["spring_parameters"]["active_coils"]["value"] = 10
    refresh_design_checks(r)
    assert not support["derived_value_stale"]
    support.update(value="", source=["human_edited"])
    refresh_design_checks(r)
    assert support["value"] == ""
    assert r["design_checks"]["metrics"]["unit_mass"]["value"] is None


def height_and_model_protections(fixture):
    r = copy.deepcopy(fixture["base"])
    case = next(c for c in fixture["cases"] if c["name"] == "book-order2-baseline")
    for field, item in case["overrides"].items():
        if isinstance(item, dict):
            r["spring_parameters"].setdefault(field, {}).update(item)
        else:
            r["spring_parameters"][field] = item
    params = r["spring_parameters"]
    params["end_grinding"]["value"] = "两端不磨削"
    apply_formula_compression_solid_height(params)
    params["solid_height"].update(need_human_review=False, source=["formula_calculation", "human_confirmed"])
    r["manual_confirmations"] = {"solid_height": {"confirmed": True, "value": 10.175}}
    refresh_design_checks(r)
    height = params["solid_height"]
    near(height["value"], 9)
    assert height["value_kind"] == "nominal_estimate" and height["need_human_review"]
    assert height["legacy_reference_limit"]["value"] == 10.175
    assert height["legacy_reference_limit"]["manual_confirmation"]["confirmed"]
    assert "solid_height" not in r["manual_confirmations"]
    height.update(need_human_review=False, source=["formula_calculation", "human_confirmed"])
    old_snapshot = copy.deepcopy(height["formula_calculation_inputs"])
    params["end_grinding"]["value"] = "两端磨削"
    refresh_design_checks(r)
    assert height["value_kind"] == "nominal_estimate" and height["derived_value_stale"]
    near(height["value"], 9)
    near(height["formula_recalculation_candidate"]["value"], 6.3)
    assert height["formula_calculation_inputs"] == old_snapshot
    checks = r["design_checks"]["metrics"]
    near(checks["reference_solid_height_limit"]["value"], 7.4)
    assert checks["solid_height_used"]["value"] is None and checks["solid_stress"]["value"] is None
    near(checks["nominal_solid_height"]["value"], 6.3)
    assert checks["solid_stress"]["height_source"] == "book_nominal"
    params["end_grinding"]["value"] = "两端不磨削"
    refresh_design_checks(r)
    assert not height["derived_value_stale"] and "formula_recalculation_candidate" not in height
    # Version changes alone must not invalidate an unchanged book calculation.
    pitch = params["pitch"]
    pitch.update(need_human_review=False, source=["formula_calculation", "human_confirmed"])
    pitch["formula_calculation_inputs"]["model_version"] = "compression-design-v1"
    refresh_design_checks(r)
    assert not pitch["derived_value_stale"]
    params["free_length"]["value"] = 20
    refresh_design_checks(r)
    assert pitch["derived_value_stale"]
    assert r["design_checks"]["metrics"]["unit_mass"]["value"] is None
    assert r["design_checks"]["metrics"]["solid_stress"]["value"] is not None
    # Open-end coil derivations depend on grinding, but never on support coils.
    params["end_type"]["value"] = "两端不并紧"
    params["active_coils"] = {"value":None}
    params.pop("pitch")
    refresh_design_checks(r)
    active = params["active_coils"]
    active.update(need_human_review=False, source=["company_active_coil_rule", "human_confirmed"])
    assert active["value"] == 4
    params["support_coils"]["value"] = 100
    refresh_design_checks(r)
    assert not active["derived_value_stale"]
    params["end_grinding"]["value"] = "两端磨削"
    refresh_design_checks(r)
    assert active["value"] == 4 and active["derived_value_stale"]
    assert active["formula_recalculation_candidate"]["value"] == 3
    params["end_grinding"]["value"] = "两端不磨削"
    refresh_design_checks(r)
    assert not active["derived_value_stale"]


def main():
    fixture, results = fixture_results()
    if "--json" in sys.argv:
        print(json.dumps(results, ensure_ascii=True, allow_nan=False))
        return
    protections(fixture)
    height_and_model_protections(fixture)
    catalog = load_material_catalog()
    expected = [(2200,78000,206000,7.85,990,.4),(2100,78000,206000,7.85,945,.4),(1760,78000,206000,7.85,792,.5),(520,71500,193000,7.93,310,.4),(520,71500,193000,8,310,.4),(1030,73500,198000,7.93,465,.4),(1120,78000,206000,7.85,672,.4),(1570,78000,206000,7.85,745,.4),(1270,78000,206000,7.85,745,.4),(1250,79000,210000,8.28,500,.4),(1100,79000,206000,7.85,440,.4),(1570,79000,206000,7.85,628,.4),(1310,76000,196000,7.8,524,.4),(1570,75500,203000,7.93,628,.4),(1520,77200,200000,8.24,578,.4)]
    keys = ["tensile_strength_mpa","shear_modulus_mpa","elastic_modulus_mpa","density_g_cm3","allowable_shear_stress_mpa","allowable_stress_coefficient"]
    for item, values in zip(catalog["items"], expected):
        assert tuple(item[k] for k in keys) == values
    print(f"compression design values: {len(results)} shared cases, material properties, protections and persistence passed")


if __name__ == "__main__":
    main()
