from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.diameter_linkage import apply_diameter_linkage, GROUP, DIAMETERS
from ai_design_review.standardizers.diameters import apply_formula_compression_diameter_completion
from ai_design_review.accuracy_inference import refresh_accuracy_inference


def base():
    return {"drawing_summary": {"spring_type": "compression_spring", "drawing_no": "00123"},
            "spring_parameters": {f: {"value": v, "unit": "mm", "source": ["human_confirmed", "qwen_vision"],
                                      "need_human_review": False, "tolerance_upper": .1, "tolerance_lower": -.1,
                                      "evidence": "原图明确标注", "confirmation_snapshot": {"value": v}}
                                  for f, v in zip(GROUP, (2, 20, 16, 18))},
            "manual_confirmations": {f: {"confirmed": True, "value": v} for f, v in zip(GROUP, (2, 20, 16, 18))},
            "standardization_results": [{"status": "human_confirmed", "rule_id": "DIA"}]}


def fixtures():
    cases = []
    for driver, value in (("outer_diameter", 24), ("inner_diameter", 20), ("mean_diameter", 22)):
        for source in (["qwen_vision"], ["human_edited"], ["formula_calculation", "human_confirmed"]):
            r = base()
            for p in r["spring_parameters"].values(): p["source"] = source
            cases.append({"name": f"{driver}-{source}", "review": r, "edits": [[driver, value]]})
    for driver in DIAMETERS:
        for invalid in ("", "abc", 0, -1, None):
            cases.append({"name": f"invalid-{driver}-{invalid}", "review": base(), "edits": [[driver, invalid]]})
    cases += [
        {"name": "switch-driver-wire", "review": base(), "edits": [["outer_diameter", 24], ["inner_diameter", 18], ["wire_diameter", 3]]},
        {"name": "invalid-recovery", "review": base(), "edits": [["outer_diameter", 24], ["outer_diameter", 3], ["outer_diameter", 24]]},
        {"name": "wire-missing-recovery", "review": base(), "edits": [["wire_diameter", ""], ["mean_diameter", 22], ["wire_diameter", 2]]},
        {"name": "old-order-read", "review": base(), "edits": []},
    ]
    cm = base(); cm["spring_parameters"]["inner_diameter"]["unit"] = "cm"
    cases.append({"name": "mixed-units", "review": cm, "edits": [["outer_diameter", 24]]})
    for feature, value in (("spring_shape", "conical"), ("wire_section", "rectangular")):
        r = base(); r["spring_features"] = {feature: {"value": value}}
        cases.append({"name": f"unsupported-{value}", "review": r, "edits": [["outer_diameter", 24]]})
    r = base(); r["spring_parameters"]["wire_diameter"].update(source=["formula_calculation"], source_fields=["outer_diameter", "inner_diameter"])
    cases.append({"name": "freeze-derived-wire", "review": r, "edits": [["outer_diameter", 24], ["mean_diameter", 20], ["wire_diameter", 3]]})
    r = base(); r["spring_parameters"]["inner_diameter"]["unit"] = "bad-unit"
    cases.append({"name": "invalid-output-unit", "review": r, "edits": [["outer_diameter", 24]]})
    r = base(); r["spring_parameters"]["wire_diameter"]["value"] = .000001
    cases.append({"name": "rounded-zero-geometry", "review": r, "edits": [["mean_diameter", .000002]]})
    r = base(); refresh_accuracy_inference(r, initialize=True, standard="GB/T 1239.2-2009")
    cases.append({"name": "accuracy-linked-basis", "review": r, "edits": [["outer_diameter", 14], ["inner_diameter", 20], ["wire_diameter", 3]], "inference": True})
    for case in cases:
        r = deepcopy(case["review"])
        for field, value in case["edits"]:
            r["spring_parameters"][field]["value"] = value
            apply_diameter_linkage(r, field)
            if case.get("inference"): refresh_accuracy_inference(r)
        apply_diameter_linkage(r)
        if case.get("inference"): refresh_accuracy_inference(r)
        case["expected"] = r
    return cases


def main():
    cases = fixtures()
    if "--json" in sys.argv:
        print(json.dumps(cases, ensure_ascii=False)); return
    r = base(); original = deepcopy(r); apply_diameter_linkage(r)
    assert r == original, "Opening an old review must not activate linkage"
    for driver, value in (("outer_diameter", 24), ("inner_diameter", 20), ("mean_diameter", 22)):
        r = base(); p = r["spring_parameters"]; p[driver]["value"] = value
        result = apply_diameter_linkage(r, driver)
        assert [p[f]["value"] for f in DIAMETERS] == [24, 20, 22]
        assert len(result["changed_fields"]) == 3
        assert all(p[f]["need_human_review"] for f in DIAMETERS)
        assert all(not r["manual_confirmations"][f]["confirmed"] for f in DIAMETERS)
        assert all(p[f]["tolerance_upper"] == .1 for f in GROUP)
        for f in DIAMETERS: p[f]["need_human_review"] = False
        assert not apply_diameter_linkage(r)["changed_fields"]
        assert all(not p[f]["need_human_review"] for f in DIAMETERS)
        p["wire_diameter"]["value"] = 3
        apply_diameter_linkage(r, "wire_diameter")
        assert p[driver]["value"] == value
        assert p["outer_diameter"]["value"] - p["inner_diameter"]["value"] == 6
        before = deepcopy(p); apply_formula_compression_diameter_completion(p)
        assert p == before, "Legacy completion cannot reverse a linked edit"
    r = base(); p = r["spring_parameters"]; p["outer_diameter"]["value"] = 3
    apply_diameter_linkage(r, "outer_diameter")
    assert p["inner_diameter"]["value"] == 16 and p["inner_diameter"]["derived_value_stale"]
    p["outer_diameter"]["value"] = 20; apply_diameter_linkage(r, "outer_diameter")
    assert p["inner_diameter"]["value"] == 16 and p["inner_diameter"]["need_human_review"]
    # A generated nominal value must not replace the independent tolerance input.
    r = base(); refresh_accuracy_inference(r, initialize=True, standard="GB/T 1239.2-2009")
    independent = deepcopy(r["accuracy_inference"]["input_snapshot"]["inner_diameter"])
    r["spring_parameters"]["outer_diameter"]["value"] = 24
    apply_diameter_linkage(r, "outer_diameter"); refresh_accuracy_inference(r)
    assert r["accuracy_inference"]["input_snapshot"]["inner_diameter"]["value"] == independent["value"]
    assert r["accuracy_inference"]["input_snapshot"]["inner_diameter"]["upper"] == independent["upper"]
    r["spring_parameters"]["outer_diameter"]["value"] = 14
    apply_diameter_linkage(r, "outer_diameter"); refresh_accuracy_inference(r)
    diameter = next(row for row in r["accuracy_inference"]["results"] if row["field"] == "outer_diameter")
    assert diameter["limits"]["1级"] == .15, "Inference uses linked mean 12, not the old independently recognized mean 18"
    print(f"Diameter linkage: {len(cases)} shared fixtures, confirmation, invalid geometry, legacy completion and inference provenance passed")


if __name__ == "__main__": main()
