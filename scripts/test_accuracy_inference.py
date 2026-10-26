from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.accuracy_inference import refresh_accuracy_inference, mark_accuracy_input, select_manual_accuracy


def base(tolerance=.6):
    def p(v, unit="mm", **extra):
        return {"value": v, "unit": unit, **extra}
    return {"drawing_summary": {"spring_type": "compression_spring"},
            "standard_selection": {"selected_standard": "GB/T 1239.2-2009"},
            "spring_parameters": {"wire_diameter": p(2), "mean_diameter": p(12), "outer_diameter": p(14),
                "free_length": p(40, tolerance_upper=tolerance, tolerance_lower=-tolerance), "active_coils": p(8, "turns")}}


def fixtures():
    cases = []
    def add(name, review, expected, status=None):
        original = deepcopy(review)
        refresh_accuracy_inference(review, initialize=True)
        assert review["accuracy_inference"]["inferred_grade"] == expected, (name, review["accuracy_inference"])
        if status:
            assert next(x for x in review["accuracy_inference"]["results"] if x["field"] == "free_length")["status"] == status, name
        cases.append({"name": name, "review": original, "expected": review})
    for value, expected in [(.00000001, "1级"), (.2, "1级"), (.4, "1级"), (.4001, "2级"), (.6, "2级"), (.8, "2级"), (.8001, "3级"), (1.2, "3级"), (1.2001, None)]:
        add(f"height {value}", base(value), expected)
    for upper, lower, expected in [(.5, -.1, "2级"), (.3, 0, "1级"), (0, -.6, "2级"), (None, -.1, None), (.2, .3, None), (True, -.1, None), ("bad", -.1, None)]:
        r = base(); r["spring_parameters"]["free_length"].update(tolerance_upper=upper, tolerance_lower=lower)
        add(f"asymmetric {upper}/{lower}", r, expected)
    r = base(); r["spring_parameters"]["free_length"].update(value=4, unit="cm", tolerance_upper=.06, tolerance_lower=-.06)
    add("centimeters", r, "2级")
    r = base(); r["spring_parameters"]["outer_diameter"].update(tolerance_upper=.15, tolerance_lower=-.15)
    r["spring_parameters"]["load_points"] = [{"label": "F1", "force": 100, "force_unit": "N", "force_tolerance_percent": 15}]
    add("strictest quote grade", r, "1级")
    r = base(.2); r["spring_parameters"]["accuracy_grade"] = {"value": "3级", "source": ["qwen_vision"]}
    add("drawing grade takes precedence", r, "1级")
    assert cases[-1]["expected"]["spring_parameters"]["accuracy_grade"]["value"] == "3级"
    for c in (3, 8, 8.0001, 15, 15.0001, 22, 22.0001):
        r = base(.1); r["spring_parameters"]["mean_diameter"]["value"] = c * 2
        add(f"spring index {c}", r, "1级" if c <= 22 else None)
    for n in (2.9, 3, 10, 10.0001, 14):
        for percent in (4, 5, 8, 10, 12, 15, 16):
            r = base(); r["spring_parameters"]["free_length"].update(tolerance_upper=None, tolerance_lower=None)
            r["spring_parameters"]["active_coils"]["value"] = n
            r["spring_parameters"]["load_points"] = [{"load_point_id": "stable-f1", "label": "F1", "force": .1, "force_unit": "kN", "force_tolerance_percent": percent}]
            limits = (5, 10, 15) if n <= 10 else (4, 8, 12)
            expected = next((f"{i + 1}级" for i, limit in enumerate(limits) if percent <= limit), None) if n >= 3 else None
            add(f"load n={n}, {percent}%", r, expected)
    r = base(); r["spring_parameters"]["free_length"].update(tolerance_upper=None, tolerance_lower=None)
    r["spring_parameters"]["outer_diameter"].update(value=15.625, tolerance_upper=.15625, tolerance_lower=-.15625)
    add("Python rounding exact halfway", r, "2级")
    r = base(); r["spring_parameters"].update(total_coils={"value": 10, "unit": "turns"}, support_coils={"value": 1, "unit": "turns"}, end_type={"value": "两端并紧"})
    r["spring_parameters"]["active_coils"]["source"] = ["company_active_coil_rule"]
    r["spring_parameters"]["free_length"].update(tolerance_upper=None, tolerance_lower=None)
    r["spring_parameters"]["load_points"] = [{"label": "F1", "force": 100, "force_unit": "N", "force_tolerance_percent": 4.5}]
    add("derived active coil dependency", r, "1级")
    r = base(.2); refresh_accuracy_inference(r, initialize=True)
    r["accuracy_inference"]["standard_selection_source"] = "wire_diameter_threshold"
    r["standard_selection"] = {"selected_standard": None, "status": "not_started"}
    add("deferred upload retains applicability", r, "1级")
    r = base(.2); r["standard_selection"]["selected_standard"] = "GB/T 99999-2000"
    add("unsupported standard", r, None, "not_applicable")
    r = base(.2); r["spring_parameters"]["free_length"]["tolerance_source"] = "standardization"
    add("generated tolerance is not evidence", r, None, "generated_tolerance")
    r = base(); r["spring_parameters"]["free_length"].update(tolerance_upper=None, tolerance_lower=None)
    r["spring_parameters"]["spring_rate"] = {"value": 10, "unit": "N/mm", "tolerance_upper": 1, "tolerance_lower": -1}
    add("stiffness", r, "2级")
    hot_fixtures(add)
    return cases


def hot_base():
    def p(value, unit="mm", **extra):
        return {"value": value, "unit": unit, "source": ["qwen_vision"], "need_human_review": True, **extra}
    return {"drawing_summary": {"spring_type": "compression_spring"},
        "standard_selection": {"selected_standard": "GB/T 23934-2015"},
        "spring_parameters": {"wire_diameter": p(28), "inner_diameter": p(75, tolerance_upper=1, tolerance_lower=0),
            "mean_diameter": p(103), "outer_diameter": p(131), "free_length": p(274, tolerance_upper=4.5, tolerance_lower=-4.5),
            "active_coils": p(6, "turns"), "total_coils": p(7.5, "turns"), "pitch": p(41), "spring_rate": p(878.9, "N/mm"),
            "controlled_diameter_field": p("inner_diameter", "")}}


def hot_fixtures(add):
    r = hot_base(); add("hot row13 strictest T", r, "T级", "matched")
    # Independent expected limits around each actual height-band boundary.
    for height, minimum in [(250, .8), (250.0001, 1), (500, 1.6), (500.0001, 1.6)]:
        for tolerance, expected in [(minimum, "T级"), (minimum+.0002, "1级")]:
            r = hot_base(); p = r["spring_parameters"]
            p["wire_diameter"]["value"] = 40; p["mean_diameter"]["value"] = 200
            p["inner_diameter"].update(value=160, tolerance_upper=tolerance, tolerance_lower=0)
            p["free_length"].update(value=height, tolerance_upper=None, tolerance_lower=None)
            # At mean200 factors dominate at <=250 as well.
            if height <= 250: p["mean_diameter"]["value"] = 100; p["wire_diameter"]["value"] = 28
            elif height <= 500 and height < 400: p["mean_diameter"]["value"] = 103; p["wire_diameter"]["value"] = 28
            add(f"hot band {height} tolerance {tolerance}", r, expected)
    for field, value in [("wire_diameter", 7.9), ("mean_diameter", 80), ("active_coils", 2.9), ("pitch", 52), ("free_length", 420)]:
        r = hot_base(); r["spring_parameters"][field]["value"] = value
        add(f"hot outside scope {field}", r, None, "outside_scope")
    for field in ("pitch", "active_coils", "wire_diameter"):
        r = hot_base(); r["spring_parameters"].pop(field)
        add(f"hot missing context {field}", r, None, "missing_context")
    r = hot_base(); r["spring_parameters"]["inner_diameter"].update(tolerance_upper=None, tolerance_lower=None)
    add("hot free height grade2", r, "2级")
    for upper, lower, expected in [(1, 0, "T级"), (0, -1, "T级"), (1.01, -1, "1级"), (3, -3, None), (1, None, None)]:
        r = hot_base(); p=r["spring_parameters"]; p["inner_diameter"].update(tolerance_upper=upper, tolerance_lower=lower)
        p["free_length"].update(tolerance_upper=None,tolerance_lower=None)
        add(f"hot single/asymmetric {upper}/{lower}",r,expected)
    for force, stiffness, tolerance, expected in [(100, 10, 15, "T级"), (100, 10, 15.0001, "1级"), (1000, 1, 30, "T级"), (1000, 1, 50, "1级"), (1000, 1, 100, "2级"), (1000, 1, 151, None)]:
        r=hot_base(); p=r["spring_parameters"]
        for field in ("inner_diameter","free_length"): p[field].update(tolerance_upper=None,tolerance_lower=None)
        p["spring_rate"]["value"]=stiffness
        p["load_points"]=[{"label":"F1","height":200,"force":force,"force_unit":"N","load_tolerance_upper":tolerance,"load_tolerance_lower":-tolerance}]
        add(f"hot load {force}/{stiffness}/{tolerance}",r,expected)
    r=hot_base(); r["spring_parameters"]["inner_diameter"].update(value=7.5,unit="cm",tolerance_upper=.1,tolerance_lower=0)
    add("hot units",r,"T级")


def lifecycle():
    r = base(.2); refresh_accuracy_inference(r, initialize=True)
    r["manual_confirmations"] = {"accuracy_grade": {"confirmed": True}}
    r["spring_parameters"]["accuracy_grade"]["need_human_review"] = False
    r["spring_parameters"]["free_length"].update(tolerance_upper=.6, tolerance_lower=-.6)
    mark_accuracy_input(r, "free_length", generated=False, tolerance=True)
    assert r["spring_parameters"]["accuracy_grade"]["value"] == "2级"
    assert not r["manual_confirmations"]["accuracy_grade"]["confirmed"]
    r["spring_parameters"]["accuracy_grade"]["need_human_review"] = False
    refresh_accuracy_inference(r)
    assert not r["spring_parameters"]["accuracy_grade"]["need_human_review"]
    before = deepcopy(r["accuracy_inference"]["input_snapshot"])
    r["spring_parameters"]["free_length"].update(value=50, tolerance_upper=1.5, tolerance_lower=-1.5)
    mark_accuracy_input(r, "free_length", generated=True)
    assert r["accuracy_inference"]["input_snapshot"] == before
    assert r["accuracy_inference"]["inferred_grade"] == "2级"
    select_manual_accuracy(r)
    r["spring_parameters"]["accuracy_grade"]["value"] = "3级"
    r["spring_parameters"]["free_length"].update(tolerance_upper=.1, tolerance_lower=-.1)
    mark_accuracy_input(r, "free_length", generated=False, tolerance=True)
    for _ in range(5):
        r = json.loads(json.dumps(r)); refresh_accuracy_inference(r)
        assert r["spring_parameters"]["accuracy_grade"]["value"] == "3级"
        assert r["accuracy_inference"]["inferred_grade"] == "1级"
    legacy = base(.2); legacy["spring_parameters"]["accuracy_grade"] = {"value": "2级", "need_human_review": False}
    refresh_accuracy_inference(legacy)
    assert legacy["accuracy_inference"]["selection_mode"] == "legacy"
    assert legacy["spring_parameters"]["accuracy_grade"]["value"] == "2级"
    default = base(); default["spring_parameters"]["free_length"].update(tolerance_upper=None, tolerance_lower=None)
    refresh_accuracy_inference(default, initialize=True)
    default["spring_parameters"]["accuracy_grade"].update(need_human_review=False, source=["human_confirmed"])
    default["spring_parameters"]["accuracy_grade"].pop("default_source", None)
    default["spring_parameters"]["accuracy_grade"].pop("default_reason", None)
    refresh_accuracy_inference(default)
    assert "default_source" not in default["spring_parameters"]["accuracy_grade"]
    # A stale auto-mode save cannot unlock an already persisted human selection.
    incoming = deepcopy(r); incoming["accuracy_inference"]["selection_mode"] = "auto"
    incoming["spring_parameters"]["accuracy_grade"]["value"] = "1级"
    refresh_accuracy_inference(incoming, previous=r)
    assert incoming["spring_parameters"]["accuracy_grade"]["value"] == "3级"


if __name__ == "__main__":
    cases = fixtures(); lifecycle()
    if "--json" in sys.argv:
        print(json.dumps(cases, ensure_ascii=False))
    else:
        print(f"Accuracy inference: {len(cases)} shared fixtures and lifecycle checks passed")
