"""Support-coil reconciliation fixtures, offline replay and server-side protections."""
import sys
import json
from copy import deepcopy
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.standardizers.design_checks import apply_formula_support_coils, refresh_design_checks
from ai_design_review.standardizers.support_coils import classify_support_candidate
from ai_design_review.fusion import fuse_candidates
from ai_design_review.spring_feasibility import assess_parameter_reasonableness


def baseline():
    return {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {
        "total_coils": {"value": 16, "unit": "turns", "source": ["qwen_vision"], "need_human_review": True},
        "active_coils": {"value": 14, "unit": "turns", "source": ["qwen_vision"], "need_human_review": True},
        "support_coils": {"value": 2, "unit": "turns", "source": ["qwen_vision"], "need_human_review": True, "evidence": "总圈数16-有效圈数14=2"},
        "end_type": {"value": "两端并紧", "need_human_review": False},
        "end_grinding": {"value": "两端磨削", "need_human_review": False},
        "wire_diameter": {"value": 1.6, "unit": "mm"}, "free_length": {"value": 55.6, "unit": "mm"},
        "mean_diameter": {"value": 10.4, "unit": "mm"}, "pitch": {"value": 3.8, "unit": "mm", "source": ["qwen_vision"]}},
        "manual_confirmations": {}, "technical_requirements": [], "standardization_results": []}


def fixtures():
    cases = [("model-total-as-single", baseline())]
    for name, changes in [
        ("drawing-single", {"evidence": "每端支承圈数：2圈"}),
        ("drawing-total", {"evidence": "两端支承圈数合计2圈"}),
        ("ambiguous-model", {"evidence": "支承圈数2"}),
        ("grinding-not-support", {"evidence": "每端磨270°"}),
        ("manual", {"source": ["human_edited"], "need_human_review": False}),
        ("manual-cleared", {"value": "", "source": ["human_edited"]}),
        ("confirmed-model", {"need_human_review": False}),
    ]:
        r = baseline(); r["spring_parameters"]["support_coils"].update(changes); cases.append((name, r))
    for name, field, changes in [
        ("open", "end_type", {"value": "两端不并紧"}),
        ("legacy-end", "end_type", {"value": "closed_and_ground"}),
        ("missing", "total_coils", {"value": None}),
        ("invalid-unit", "active_coils", {"unit": "mm"}),
        ("equal-counts", "active_coils", {"value": 16}),
        ("invalid-number", "total_coils", {"value": "NaN"}),
        ("cyclic", "active_coils", {"source": ["company_active_coil_rule"], "source_fields": ["total_coils", "support_coils"]}),
        ("derived-cycle", "active_coils", {"source": ["formula_calculation"], "source_fields": ["support_coils"]}),
        ("asymmetric", "end_type", {"evidence": "两端支承结构不对称"}),
        ("asymmetric-numbers", "support_coils", {"evidence": "左端支承圈数0.5圈，右端支承圈数1.5圈"}),
    ]:
        r = baseline(); r["spring_parameters"][field].update(changes); cases.append((name, r))
    r = baseline(); r["technical_requirements"] = [{"content": "两端支承圈数不同"}]; cases.append(("asymmetric-requirement", r))
    for name, total, active in [("other-counts", 4, 2), ("fractional", 16.5, 14), ("third-counts", 22, 19)]:
        r = baseline(); r["spring_parameters"]["total_coils"]["value"] = total; r["spring_parameters"]["active_coils"]["value"] = active; cases.append((name, r))
    result = []
    for name, r in cases:
        before = deepcopy(r); apply_formula_support_coils(r)
        result.append({"name": name, "review": before, "expected": r})
    return result


def confirm_roots(r):
    for field in ("total_coils", "active_coils"):
        r["spring_parameters"][field]["need_human_review"] = False


def main():
    cases = fixtures(); by_name = {c["name"]: c["expected"]["spring_parameters"]["support_coils"] for c in cases}
    assert by_name["model-total-as-single"]["value"] == 1
    assert by_name["model-total-as-single"]["support_coils_original"]["value"] == 2
    for name in ("drawing-total", "ambiguous-model", "legacy-end", "other-counts"):
        assert by_name[name]["value"] == 1, name
    for name in ("drawing-single", "manual", "confirmed-model"):
        assert by_name[name]["value"] == 2, name
    assert by_name["manual-cleared"]["value"] == ""
    assert by_name["fractional"]["value"] == 1.25
    for name in ("open", "missing", "invalid-unit", "equal-counts", "invalid-number", "cyclic", "derived-cycle", "asymmetric", "asymmetric-numbers", "asymmetric-requirement"):
        assert by_name[name].get("derived_value_stale"), name
    r = baseline(); apply_formula_support_coils(r); confirm_roots(r)
    s = r["spring_parameters"]["support_coils"]; s["need_human_review"] = False
    s["confirmation_snapshot"] = {"value": 1}; r["manual_confirmations"]["support_coils"] = {"confirmed": True, "value": 1}
    p = r["spring_parameters"]; p["total_coils"].update(value=18, source=["human_edited"], need_human_review=True)
    apply_formula_support_coils(r)
    assert s["value"] == 1 and s["support_coils_waiting_confirmation"]
    assert s["formula_recalculation_candidate"]["value"] == 2
    p["total_coils"]["need_human_review"] = False; apply_formula_support_coils(r)
    assert s["value"] == 2 and s["need_human_review"] and not s["derived_value_stale"]
    assert "support_coils" not in r["manual_confirmations"] and "confirmation_snapshot" not in s
    # Same result with changed inputs still needs a new confirmation.
    s["need_human_review"] = False
    p["total_coils"].update(value=20, source=["human_edited"]); p["active_coils"].update(value=16, source=["human_edited"], need_human_review=False)
    apply_formula_support_coils(r); assert s["value"] == 2 and s["need_human_review"]
    s["need_human_review"] = False; before = deepcopy(s); apply_formula_support_coils(r); assert s == before
    # Confirming a default-derived count does not make it an independent input.
    cycle = deepcopy(next(c["review"] for c in cases if c["name"] == "cyclic")); confirm_roots(cycle)
    cycle["spring_parameters"]["active_coils"]["source"].insert(0, "human_confirmed")
    apply_formula_support_coils(cycle); assert cycle["spring_parameters"]["support_coils"]["derived_value_stale"]
    # A lower-confidence explicit single-end mark wins over model arithmetic.
    candidates = [{"field": "support_coils", "value": 2, "source": "qwen_vision", "evidence": "总圈数16-有效圈数14=2", "confidence": .99},
                  {"field": "support_coils", "value": 1, "source": "ocr", "evidence": "每端支承圈数1圈", "confidence": .7}]
    assert fuse_candidates(candidates)["fields"]["support_coils"]["value"] == 1
    assert candidates[0].get("support_coils_origin") is None, "Raw candidates remain untouched"
    explicit = deepcopy(next(c["expected"] for c in cases if c["name"] == "drawing-single"))
    assert any(i["rule_id"] == "SPRING-GEO-SUPPORT-COILS" for i in assess_parameter_reasonableness(explicit)["issues"])
    # Offline replay uses the saved local Qwen result and no recognizer/model calls.
    path = Path('outputs/api_runs/c24d3dfaed35/candidates.json')
    if path.exists():
        from ai_design_review.workflow import DrawingReviewWorkflow
        payload = json.loads(path.read_text(encoding='utf-8'))
        workflow = DrawingReviewWorkflow(json.loads(Path('config/factory_rules.json').read_text(encoding='utf-8')))
        replay = workflow.run(None, payload['candidates'], run_standardization=False)
        assert replay['spring_parameters']['support_coils']['value'] == 1
        assert replay['spring_parameters']['support_coils']['need_human_review']
    if '--json' in sys.argv:
        print(json.dumps(cases, ensure_ascii=True))
    elif '--assess' in sys.argv:
        data = json.load(sys.stdin); r = data['review']; refresh_design_checks(r)
        print(json.dumps({"review": r, "assessment": assess_parameter_reasonableness(r)}, ensure_ascii=True))
    else:
        print(f'Support coils: {len(cases)} shared fixtures, confirmed edits, provenance, conflicts, cycles and offline replay passed')


if __name__ == '__main__':
    main()
