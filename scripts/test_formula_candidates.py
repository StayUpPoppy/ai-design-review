"""Shared authoritative candidate fixtures, also consumed by JS/browser tests."""
import json
import sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.parameter_suggestions import build_parameter_suggestions
from ai_design_review.formula_candidates import candidate_snapshots
from ai_design_review.standardizers.design_checks import calculate_pitch, calculate_nominal_solid_height, refresh_design_checks
from ai_design_review.standardizers.compression import calculate_compression_solid_height


def fixtures():
    def param(value, unit="mm", **extra):
        return dict(value=value, unit=unit, source=["qwen_vision"], need_human_review=False, **extra)
    review = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_features": {}, "review_revision": 7,
              "spring_parameters": {"free_length": param(28.9), "wire_diameter": param(1.8),
                  "total_coils": param(8, "turns"), "active_coils": param(7, "turns"), "support_coils": param(1, "turns"),
                  "end_type": param("两端不并紧", None), "end_grinding": param("两端磨削", None),
                  "solid_height": param(14.4), "pitch": param(3.4438)}, "manual_confirmations": {},
              "standardization_results": [], "parameter_reasonableness": {"status": "pass", "suggestions": []}}
    p = review["spring_parameters"]
    p["pitch"].update(source=["formula_calculation"], formula_calculation_kind="pitch",
                      formula_calculation_inputs={**calculate_pitch(p)["inputs"], "free_length": 27.5504})
    cases = [("screenshot-pitch", deepcopy(review))]
    forged = deepcopy(review); forged["spring_parameters"]["pitch"]["formula_recalculation_candidate"] = {"value": 999}
    cases.append(("cached-value-not-trusted", forged))
    same = deepcopy(review)
    same["spring_parameters"]["pitch"]["value"] = 3.6125
    cases.append(("same-value-new-inputs", same))
    invalid = deepcopy(review); invalid["spring_parameters"]["free_length"]["value"] = None
    cases.append(("invalid-input", invalid))
    restored = deepcopy(review); restored["spring_parameters"]["pitch"]["formula_calculation_inputs"] = calculate_pitch(p)["inputs"]
    cases.append(("restored-inputs", restored))
    manual = deepcopy(review); manual["spring_parameters"]["pitch"]["human_modified"] = True
    cases.append(("manual-protected", manual))
    support = deepcopy(review); support["spring_parameters"]["support_coils"].update(derived_value_stale=True, formula_recalculation_candidate={"value": 2})
    cases.append(("support-excluded", support))
    active = deepcopy(review); active["spring_parameters"]["active_coils"].update(source=["company_active_coil_rule"], value=6, formula_calculation_inputs={"total_coils": 7})
    cases.append(("active", active))
    nominal = deepcopy(review); target = nominal["spring_parameters"]["solid_height"]
    target.update(value=12.6, value_kind="nominal_estimate", source=["formula_calculation"], formula_calculation_kind="nominal_solid_height", formula_calculation_inputs={"wire_diameter": 1.6})
    cases.append(("nominal", nominal))
    reference = deepcopy(review); reference["spring_parameters"]["solid_height"].update(value=12.6, value_kind="reference_limit", source=["formula_calculation"], formula_calculation_kind="solid_height", formula_calculation_inputs={"wire_diameter_mm": 1.6}, formula_purpose_preserved=True)
    cases.append(("reference", reference))
    units = deepcopy(review); units["spring_parameters"]["free_length"].update(value=2.89, unit="cm")
    cases.append(("converted-units", units))
    conflict = deepcopy(review); conflict["standardization_results"] = [{"target_field": "pitch", "suggested_value": 3.7, "source_fields": ["free_length"], "rule_id": "OTHER-PITCH", "status": "suggested"}]
    cases.append(("conflict", conflict))
    duplicate = deepcopy(active); duplicate["standardization_results"] = [{"target_field": "active_coils", "suggested_value": 7, "source_fields": ["total_coils"], "rule_id": "SAME-ACTIVE", "status": "suggested"}]
    cases.append(("duplicate", duplicate))
    return [{"name": name, "review": item, "suggestions": build_parameter_suggestions(item, based_on_revision=7)} for name, item in cases]


def test():
    cases = fixtures()
    by_name = {c["name"]: c for c in cases}
    candidates = lambda name: [s for s in by_name[name]["suggestions"] if s.get("suggestion_kind") == "formula_candidate"]
    assert candidates("screenshot-pitch")[0]["suggested_value"] == 3.6125
    assert candidates("cached-value-not-trusted")[0]["suggested_value"] == 3.6125
    assert candidates("same-value-new-inputs")[0]["status"] == "available"
    for name in ("invalid-input", "restored-inputs", "manual-protected"):
        assert not candidates(name), name
    assert not any(c["target_field"] == "support_coils" for c in candidates("support-excluded"))
    active = [c for c in by_name["duplicate"]["suggestions"] if c["target_field"] == "active_coils" and c["application_mode"] != "none"]
    assert len(active) == 1 and active[0]["suggestion_kind"] == "formula_candidate", active
    assert all(s["status"] == "conflict" for s in by_name["conflict"]["suggestions"] if s["target_field"] == "pitch")
    for case in cases:
        before = deepcopy(case["review"])
        candidate_snapshots(case["review"])
        assert before == case["review"], "Projection must be read-only"
    ref = deepcopy(by_name["reference"]["review"])
    refresh_design_checks(ref)
    assert ref["spring_parameters"]["solid_height"]["value_kind"] == "reference_limit"
    if "--json" in sys.argv:
        print(json.dumps(cases, ensure_ascii=True))
    else:
        print(f"formula candidate backend tests passed ({len(cases)} shared fixtures)")


if __name__ == "__main__":
    if "--assess" in sys.argv:
        payload = json.load(sys.stdin)
        print(json.dumps({"status": "pass", "issues": [], "suggestions": build_parameter_suggestions(payload["review"], based_on_revision=payload.get("review_revision"))}, ensure_ascii=True))
    else:
        test()
