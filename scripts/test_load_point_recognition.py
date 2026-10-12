from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.load_point_recognition import classify_load_candidate, partition_load_candidates
from ai_design_review.load_units import in_base_units
from ai_design_review.workflow import DrawingReviewWorkflow
from ai_design_review.rules import _check_free_length_vs_load_heights, _check_load_monotonicity
from ai_design_review.spring_feasibility import _append_load_point_issues, _append_load_relation_issues
from ai_design_review.generation_readiness import assess_generation_readiness
from ai_design_review.load_points import ensure_load_point_ids


def point(evidence="", **values):
    return {"field": "load_point", "source": "qwen_vision", "page": 1, "confidence": .9,
            "evidence": evidence, "value": {"label": "F1", "height": 30, "force": 315, "height_unit": "mm", "force_unit": "N", **values}}


def main():
    good = ["H1=14.284mm/F1=13.2N±10%", "H2=12.284mm/F2=18.9N±10%", "F3=0 N",
            "Fb=100 N", "当弹簧工作高度为30 mm时，对应工作载荷为315 N。", "H=21.15, F=16", "压并载荷Fb=100N时"]
    for evidence in good:
        assert classify_load_candidate(point(evidence))[0] == "accepted", evidence
    # Normal numeric magnitudes, tolerance columns, and missing components are not a blacklist.
    table = point("30 315 ±10%")
    table["source_context"] = {"kind": "table", "table_title": "载荷及公差", "headers": ["高度(mm)", "力值(N)", "公差(%)"], "row_text": "30 315 ±10%"}
    assert classify_load_candidate(table)[0] == "accepted"
    assert classify_load_candidate(point("F1=13.2N", height=None))[0] == "accepted"
    assert classify_load_candidate(point("H1=14.284mm/F1=13.2N", force=None))[0] == "accepted"
    inherited = point("Fb=100", height=None)
    inherited["source_context"] = {"unit_evidence": "图纸明确：力值单位 N"}
    assert classify_load_candidate(inherited)[0] == "accepted"
    inherited.pop("source_context")
    assert classify_load_candidate(inherited)[0] == "pending"  # Stored default N is not evidence.
    tol = point("未注尺寸公差：大于30，小于等于120，公差0.3")
    assert classify_load_candidate(tol)[0] == "excluded"
    conflict = copy.deepcopy(table)
    conflict["source_context"]["table_title"] = "未注尺寸公差 ≥ ≤"
    assert classify_load_candidate(conflict)[0] == "pending"
    for evidence in ["参数表载荷列第一行：高度30，负荷315", "2000 3200", "载荷表第一行：高度30，力值315 N", ""]:
        assert classify_load_candidate(point(evidence))[0] == "pending", evidence
    human = copy.deepcopy(tol)
    human["source"] = ["human_confirmed"]
    assert classify_load_candidate(human)[0] == "accepted"
    for source in ["cad", "dxf", "dwg", "werk24"]:
        candidate = point()
        candidate["source"] = source
        assert classify_load_candidate(candidate)[0] == "accepted"
    accepted, diagnostics = partition_load_candidates([table, tol, tol, conflict])
    assert accepted == [table] and len(diagnostics) == 2
    assert diagnostics == partition_load_candidates([table, tol, tol, conflict])[1]
    assert partition_load_candidates([point("", force=float("nan"))])[1][0]["original_candidate"]["value"]["force"] == "nan"
    json.dumps(diagnostics, allow_nan=False)

    payload = {"spring_type": {"value": "compression_spring", "confidence": .95, "evidence": "压缩弹簧"},
               "parameters": {field: {"value": value, "unit": "mm", "confidence": .95, "evidence": evidence}
                              for field, value, evidence in [("free_length", 80, "轴向总长度80"), ("outer_diameter", 28, "外径φ28"), ("wire_diameter", 2, "线径φ2")]},
               "load_points": [{"label": f"F{i}", "height": height, "force": force, "height_unit": "mm", "force_unit": "N", "evidence": "参数表载荷列第1行",
                                "source_context": {"kind": "table", "table_title": "无标示尺寸", "headers": ["≥", "≤", "公差"], "row_text": f"{height} {force} 0.3"}}
                               for i, (height, force) in enumerate([(30, 315), (120, 1000), (2000, 3200)], 1)]}
    workflow = DrawingReviewWorkflow(json.loads(Path("config/factory_rules.json").read_text(encoding="utf-8")))
    review = workflow.run(None, qwen_payload_to_candidates(payload), run_standardization=False)
    assert review["spring_parameters"]["free_length"]["value"] == 80
    assert review["spring_parameters"]["load_points"] == []
    assert review["design_checks"]["work_stresses"] == []
    assert [item["status"] for item in review["load_point_diagnostics"]] == ["excluded"] * 3
    payload["load_points"] = [{"label": "F1", "height": 14.284, "force": 13.2, "evidence": good[0], "height_unit": "mm", "force_unit": "N", "force_tolerance_percent": 10},
                              {"label": "F2", "height": 12.284, "force": 18.9, "evidence": good[1], "height_unit": "mm", "force_unit": "N"}]
    payload["parameters"]["free_length"].update(value=19, evidence="轴向总长19")
    review = workflow.run(None, qwen_payload_to_candidates(payload), run_standardization=False)
    by_label = {p["label"]: p for p in review["spring_parameters"]["load_points"]}
    assert set(by_label) == {"F1", "F2"} and by_label["F1"]["height"] == 14.284 and by_label["F2"]["force"] == 18.9
    assert by_label["F1"]["force_tolerance_percent"] == 10
    assert review["load_point_diagnostics"] == []
    # An unrelated tolerance table note does not suppress a genuine point.
    payload["notes"] = "未注尺寸公差表 ≥ ≤ 公差"
    assert len(workflow.run(None, qwen_payload_to_candidates(payload), run_standardization=False)["spring_parameters"]["load_points"]) == 2
    ensure_load_point_ids(review)
    before = copy.deepcopy(review)
    review.pop("load_point_diagnostics")
    assess_generation_readiness(review)
    assert review["spring_parameters"]["load_points"] == before["spring_parameters"]["load_points"]

    assert in_base_units(1, "in") == 25.4 and in_base_units(1, "kgf", force=True) == 9.80665
    params = {"free_length": {"value": 2, "unit": "cm"}, "load_points": [
        {"height": 1.5, "height_unit": "cm", "force": .01, "force_unit": "kN", "label": "F1"},
        {"height": 10, "height_unit": "mm", "force": 20, "force_unit": "N", "label": "F2"}]}
    original = copy.deepcopy(params)
    assert _check_free_length_vs_load_heights(params)["status"] == "pass"
    assert _check_load_monotonicity(params)["status"] == "pass"
    issues = []
    _append_load_point_issues(issues, params["load_points"], 20, 8)
    _append_load_relation_issues(issues, params["load_points"])
    assert issues == [] and params == original
    print("load recognition: normal annotations/tables, tolerance isolation, partial/zero/Fb, mixed evidence, stable diagnostics, workflow baselines and unit checks passed")


if __name__ == "__main__":
    main()
