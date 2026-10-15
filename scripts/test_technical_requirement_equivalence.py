"""Whole engineering-note equivalence, recognition trace and order2 regression."""
from __future__ import annotations
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.technical_requirements import technical_requirements_are_duplicates, technical_requirement_equivalence_key, build_technical_requirements_text
from ai_design_review.technical_requirement_recognition import collect_technical_requirements, recovery_preview
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package, assess_generation_readiness
from ai_design_review.generation_schemas import GenerationParameterPackageV2
from ai_design_review.solidworks import build_solidworks_command, build_solidworks_technical_text
from test_solidworks_export import base_review


def pairs():
    rows = json.loads((Path(__file__).parent / "fixtures/technical_requirement_equivalence.json").read_text(encoding="utf-8"))
    for row in rows:
        row["a"] = {"type": row["type"], "content": row["left"], "application_scope": row.get("left_scope", ""), "recognition_key": row.get("left_key")}
        row["b"] = {"type": row.get("right_type", row["type"]), "content": row["right"], "application_scope": row.get("right_scope", ""), "recognition_key": row.get("right_key")}
    return rows


def order2_review():
    review = base_review()
    review["spring_parameters"]["load_points"] = review["spring_parameters"]["load_points"][:2]
    review["spring_parameters"]["load_points"][1].update(load_tolerance_percent=10)
    notes = [
        ("heat_treatment", "热处理要求：300°C+10°C/20min+1min"),
        ("surface", "产品不可有油污、研磨粉尘，表面毛刺小于线径的10%"),
        ("lifetime", "寿命测试：L1-L2-L1一秒钟一次，4万次内不可失效，力衰减保证10%之内"),
        ("salt_spray", "盐雾要求720h无红锈"),
        ("other", "未注尺寸以3D为准"),
        ("environmental", "材料环保要求：不含有害物质，符合环保要求"),
        ("surface", "表面处理：产品不可有油污、研磨粉尘，表面毛刺小于线径的10%。"),
        ("heat_treatment", "300 °C+10° C/20 min+1 min"),
        ("salt_spray", "720 h无红锈"),
    ]
    review["technical_requirements"] = [{"requirement_id": f"techreq_order2_{i}", "type": kind, "content": text,
        "page": 1 if i < 6 else 2, "recognition_key": f"note_order2_{i}", "need_human_review": False} for i, (kind, text) in enumerate(notes)]
    return review


def run():
    rows = pairs()
    for row in rows:
        assert technical_requirements_are_duplicates(row["a"], row["b"]) is row["same"], row
        row["key_a"] = technical_requirement_equivalence_key(row["a"])
        row["key_b"] = technical_requirement_equivalence_key(row["b"])
        row["text"] = build_technical_requirements_text([row["a"], row["b"]])
        assert len(row["text"].splitlines()) == (1 if row["same"] else 2), row

    original = {"content": "2.热处理要求：300℃/20min", "original_content": "2.热处理要求：300℃/20min", "page": 1, "position": [10, 20, 30, 40]}
    payload = {"parameters": {"heat_treatment": {**original, "value": original["content"]}},
               "technical_requirements": [{**original, "type": "heat_treatment"}]}
    raw = qwen_payload_to_candidates(payload)
    unchanged = deepcopy(raw)
    merged = collect_technical_requirements(raw)
    assert raw == unchanged and len(merged) == 1
    assert merged[0]["recognition_channel"] == "technical_requirements" and merged[0]["need_human_review"] is True
    assert len(merged[0]["recognition_aliases"]) == 1
    alias = merged[0]["recognition_aliases"][0]
    assert alias["original_content"] == original["original_content"] and alias["position"] == original["position"]
    alias_only = {**merged[0], **alias, "recognition_aliases": []}
    assert not recovery_preview({"technical_requirements": merged}, [alias_only])["items"]
    edited = deepcopy(merged)
    edited[0]["content"] = "人工修改后的工艺要求"
    assert not recovery_preview({"technical_requirements": edited}, [alias_only])["items"]
    assert not recovery_preview({"technical_requirements": [], "change_history": [{"event_type": "technical_requirement_deleted", "before_state": merged[0]}]}, [alias_only])["items"]
    assert json.loads(json.dumps(merged)) == merged, "save/reopen retains recognition aliases"

    # Different locations remain independent, even with the same source list number.
    payload["parameters"]["heat_treatment"]["position"] = [50, 60, 70, 80]
    assert len(collect_technical_requirements(qwen_payload_to_candidates(payload))) == 2
    payload["technical_requirements"].append({**original, "type": "heat_treatment", "position": [80, 90, 100, 110]})
    payload["parameters"]["heat_treatment"].pop("position")
    assert len(collect_technical_requirements(qwen_payload_to_candidates(payload))) == 3, "ambiguous occurrence cannot be assigned by wording"
    engine_a = {"field": "heat_treatment", "value": "300℃/20min", "original_content": "300℃/20min", "page": 1, "position": [1, 2, 3, 4], "source": ["ocr-a"]}
    engine_b = {**engine_a, "source": ["ocr-b"]}
    engines = collect_technical_requirements([engine_a, engine_b])
    assert len(engines) == 1 and engines[0]["source"] == ["ocr-a", "ocr-b"] and len(engines[0]["recognition_aliases"]) == 1

    # Matching uses initial recognized wording, not the later surface-term projection.
    surface = {"field": "surface_requirement", "value": "镀锌五彩", "source": ["ocr"], "page": 1, "position": [1, 2, 3, 4]}
    assert len(collect_technical_requirements([surface, surface])) == 1

    review = order2_review()
    package = build_generation_parameter_package(review)
    GenerationParameterPackageV2.model_validate(package)
    text = package["solidworks_preview"]["extraProperties"]["技术要求"]
    assert len(text.splitlines()) == 14, text
    assert package["solidworks_preview"]["titleBlockProperties"]["表面粗糙度"] == 12.5
    assert "粗糙度" not in text
    assert len(review["technical_requirements"]) == 9 and len(package["generation_parameters"]["technical_requirements"]) == 10
    for token in ["300", "720", "产品不可有油污"]:
        assert text.count(token) == 1, text
    assert "热处理：热处理要求" not in text
    for condition in ["研磨粉尘", "毛刺小于线径的10%", "20min+1min", "不含有害物质", "4万次内不可失效"]:
        assert condition in text
    assert not any("technical_requirements" in row["field"] for row in assess_generation_readiness(review)["pending_fields"])
    review["technical_requirements"][-1]["need_human_review"] = True
    assert any("technical_requirements" in row["field"] for row in assess_generation_readiness(review)["pending_fields"]), "duplicates do not acquire confirmation"
    review["technical_requirements"][-1]["need_human_review"] = False
    frozen = deepcopy(package)
    command = build_solidworks_command("1000000199", package, review)
    review["technical_requirements"][0]["content"] = "热处理：310℃/30min"
    assert build_solidworks_command("1000000199", package, review) == command and package == frozen

    legacy = {"generation_parameters": {"technical_requirements_text": "技术要求\n9.热处理：热处理要求：300℃/20min\n16.热处理300°C/20 min"}}
    assert build_solidworks_technical_text(legacy, {}) == "1.热处理：300℃/20min"
    scoped = {"generation_parameters": {"technical_requirements": [{"type": "surface", "content": "镀锌", "application_scope": scope} for scope in ["外圆", "两端面"]]}}
    assert len(build_solidworks_technical_text(scoped, {}).splitlines()) == 2
    return {"pairs": rows, "review": order2_review(), "package": package, "merged": merged}


if __name__ == "__main__":
    result = run()
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=True))
    else:
        print(f"PASS: {len(result['pairs'])} safe equivalence fixtures, order2 14 notes + title-block Ra, aliases, confirmation and frozen requests")
