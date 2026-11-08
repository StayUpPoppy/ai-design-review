"""Shared fixtures for explanations, root-cause navigation and legacy records."""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.execution_standards import stamp_results
from ai_design_review.spring_feasibility import assess_parameter_reasonableness
from ai_design_review.standardization_diagnostics import diagnostic_groups
from ai_design_review.standardizers.hot_coiled import standardize
from ai_design_review.standardizers.stiffness import calculate_compression_spring_rate


def review():
    def p(value, unit="mm"):
        return {"value": value, "unit": unit}
    return {"drawing_summary": {"spring_type": "compression_spring"}, "standard_selection": {"selected_standard": "GB/T 23934-2015"},
            "spring_parameters": {"material": p("SUS304", ""), "wire_diameter": p(3), "outer_diameter": p(30), "mean_diameter": p(27),
                "free_length": p(50), "active_coils": p(None, "turns"), "total_coils": p(None, "turns"), "spring_rate": p(None, "N/mm"),
                "accuracy_grade": {"value": "2级", "source": ["human_selected"]},
                "load_points": [{"label": "F1", "height": 40, "force": 100, "force_tolerance_percent": 10},
                                {"label": "F2", "height": 30, "force": 200, "load_tolerance_upper": 4, "load_tolerance_lower": -2}]},
            "standardization_results": [{"target_field": f"load_points.F{i}.force", "status": "need_context", "rule_id": "GBT23934-LOAD",
                                         "basis": "缺少有效计算依据，请补充参数或手填公差。", "metadata": {"missing_fields": ["spring_rate"]}} for i in (1, 2)]}


def fixtures():
    cases = []
    def add(name, r):
        before = deepcopy(r["spring_parameters"])
        stamp_results(r)
        issues = diagnostic_groups(r)
        assert r["spring_parameters"] == before
        cases.append({"name": name, "review": r, "rate_calculation": calculate_compression_spring_rate(r["spring_parameters"], r.get("spring_features")), "expected": issues})
        return issues

    r = review()
    issues = add("hot active coils root", r)
    assert len(issues) == 1 and issues[0]["fields"] == ["active_coils"]
    assert issues[0]["affected_fields"] == ["load_points.F1.force", "load_points.F2.force"]
    assert "F1、F2" in issues[0]["message"] and "缺少有效圈数" in issues[0]["message"]
    assert "直接填写刚度" in issues[0]["resolution"] and not issues[0]["basis"]
    assert all(item["metadata"]["missing_fields"] == ["spring_rate"] and item["metadata"]["root_missing_fields"] == ["active_coils"] for item in r["standardization_results"])
    saved = deepcopy(r["spring_parameters"])
    assessment = assess_parameter_reasonableness(r)
    assert [item for item in assessment["issues"] if item["category"] == "standardization"] == issues
    assert r["spring_parameters"] == saved
    assert "有效圈数" in assessment["summary"] and "缺少有效计算依据" not in assessment["summary"]

    r = review()
    for field in ("wire_diameter", "mean_diameter", "outer_diameter", "material"):
        r["spring_parameters"][field]["value"] = None
    issues = add("multiple formula inputs", r)
    assert set(issues[0]["fields"]) == {"wire_diameter", "mean_diameter", "active_coils", "material"}

    r = review()
    r["spring_parameters"]["active_coils"]["value"] = 8
    r["spring_parameters"]["material"]["value"] = "UNKNOWN"
    issues = add("material not configured", r)
    assert issues[0]["fields"] == ["material"] and "未匹配可用剪切模量" in issues[0]["calculation"]

    r = review()
    r["spring_parameters"]["active_coils"]["value"] = 8
    issues = add("formula available but stiffness not adopted", r)
    assert issues[0]["fields"] == ["spring_rate"]
    assert not issues[0]["via_spring_rate"]

    r = review()
    r["spring_parameters"]["spring_rate"] = {"value": 10, "unit": "N/mm", "source": ["human_input"]}
    r["standardization_results"] = standardize(r["spring_parameters"])["standardization_results"]
    assert add("manual stiffness without active coils", r) == []

    r = review()
    r["standardization_results"] = [{"target_field": "load_points", "status": "need_context", "rule_id": "GBT1239.2-LOAD", "metadata": {"missing_fields": ["active_coils"]}}]
    issues = add("legacy collection target", r)
    assert issues[0]["fields"] == ["active_coils"] and len(issues[0]["affected_fields"]) == 2

    r = review()
    stamp_results(r)
    for item in r["standardization_results"]:
        del item["metadata"]["root_missing_fields"]
    cases.append({"name": "legacy roots resolved on read", "review": r, "rate_calculation": calculate_compression_spring_rate(r["spring_parameters"]), "expected": diagnostic_groups(r)})
    assert cases[-1]["expected"][0]["fields"] == ["active_coils"]

    r = review()
    r["standardization_results"][1]["metadata"]["missing_fields"] = ["load_points.F2.force"]
    r["spring_parameters"]["load_points"][1]["force"] = None
    issues = add("different load failures stay separate", r)
    assert len(issues) == 2

    r = review()
    r["standardization_results"][0].update(status="not_applicable", basis="有效圈数超出载荷公差查表范围，请手填公差。", metadata={})
    issues = add("unknown cause keeps rule and target", r)
    assert issues[0]["fields"] == ["load_points.F1.force"] and "查表范围" in issues[0]["message"]

    r = review()
    stamp_results(r)
    r["spring_parameters"]["active_coils"]["value"] = 8
    cases.append({"name": "changed inputs suppress old reasons", "review": r, "rate_calculation": calculate_compression_spring_rate(r["spring_parameters"]), "expected": []})
    assert diagnostic_groups(r) == []
    return cases


if __name__ == "__main__":
    cases = fixtures()
    if "--json" in sys.argv:
        print(json.dumps(cases, ensure_ascii=False))
    else:
        print(f"Standardization diagnostics: {len(cases)} root, merge, material, manual stiffness, legacy and freshness cases passed")
