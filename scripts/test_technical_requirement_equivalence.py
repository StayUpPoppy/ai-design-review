"""Whole engineering-note equivalence, recognition trace and order2 regression."""
from __future__ import annotations
import json
import re
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.technical_requirements import technical_requirements_are_duplicates, technical_requirement_equivalence_key, build_technical_requirements_text, format_technical_requirement
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


def hardness_review():
    review = base_review()
    review["drawing_summary"].update(drawing_no="2454BN-57", drawing_name="压缩弹簧9")
    p = review["spring_parameters"]
    for field, value in {"material": "65Mn", "wire_diameter": 1.6, "mean_diameter": 10.4,
                         "free_length": 55.6, "total_coils": 16, "active_coils": 14, "pitch": 3.8}.items():
        p[field]["value"] = value
    p["solid_height"].update(value=24.8, source=["manual"], value_kind="input_height")
    p["support_coils"]["evidence"] = "每端支承圈数：1圈"
    p["load_points"] = [{"label": "P", "height": 45.6, "force": 30, "need_human_review": False}]
    review["technical_requirements"] = [{"requirement_id": f"hardness_{i}", "type": kind, "content": body,
        "original_content": body, "page": 1, "evidence": "原图硬度/表面处理参数表", "recognition_key": f"hardness_note_{i}", "need_human_review": False}
        for i, (kind, body) in enumerate((("hardness", "硬度 HRC45-50"), ("surface", "防锈处理"), ("hardness", "HRC45-50")))]
    return review


def eight_category_review(rows):
    review = base_review()
    review["spring_parameters"]["load_points"] = review["spring_parameters"]["load_points"][:2]
    review["spring_parameters"]["solid_height"].update(source=["manual"], value_kind="input_height")
    review["technical_requirements"] = []
    for kind in ("hardness", "heat_treatment", "surface", "salt_spray", "lifetime", "environmental", "process", "other"):
        pair = next(row for row in rows if row["type"] == kind and row["same"] and (kind != "other" or "未知检验" in row["left"]) and (kind != "surface" or row["left"] == "镀锌"))
        for n, item in enumerate((pair["a"], pair["b"])):
            review["technical_requirements"].append({**deepcopy(item), "requirement_id": f"eight_{kind}_{n}", "original_content": item["content"],
                "evidence": f"八类离线样例：{kind}/{n}", **({"normalization_status": "matched"} if kind == "surface" else {}), "page": n + 1, "recognition_key": f"eight_source_{kind}_{n}", "need_human_review": n == 0})
    return review


def run():
    rows = pairs()
    for row in rows:
        assert technical_requirements_are_duplicates(row["a"], row["b"]) is row["same"], row
        row["key_a"] = technical_requirement_equivalence_key(row["a"])
        row["key_b"] = technical_requirement_equivalence_key(row["b"])
        row["text"] = build_technical_requirements_text([row["a"], row["b"]])
        assert len(row["text"].splitlines()) == (1 if row["same"] else 2), row
        if row["type"] != "surface_roughness":
            structured = {"generation_parameters": {"technical_requirements": [row["a"], row["b"]]}}
            row["sw_text"] = build_solidworks_technical_text(structured, {})
            expected_sw = re.sub(r"(?m)^(\d+\.)(?:其他要求\s*[:：]\s*)+", r"\1", row["text"])
            assert row["sw_text"] == expected_sw, row
        assert (row["a"]["content"], row["b"]["content"]) == (row["left"], row["right"]), "Comparison never rewrites records"

    assert format_technical_requirement({"type": "hardness", "content": "硬度 ＨＲＣ４５－５０"}) == "硬度要求：ＨＲＣ４５－５０"
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
    hard = hardness_review()
    original_hard = deepcopy(hard["technical_requirements"])
    hard_package = build_generation_parameter_package(hard)
    hard_notes = hard_package["solidworks_preview"]["extraProperties"]["技术要求"]
    assert len(hard_notes.splitlines()) == 9 and hard_notes.count("硬度要求：") == 1, hard_notes
    assert "8.硬度要求：HRC45-50" in hard_notes
    assert hard["technical_requirements"] == original_hard and len(original_hard) == 3
    legacy_hard = {"generation_parameters": {"technical_requirements_text": "技术要求\n8.硬度要求：硬度 HRC45-50\n10.硬度要求：HRC45~50"}}
    assert build_solidworks_technical_text(legacy_hard, {}) == "1.硬度要求：HRC45-50"
    old_hard = deepcopy(hard_package)
    old_hard["solidworks_preview"]["extraProperties"]["技术要求"] += "\n10.硬度要求：HRC45-50"
    frozen_hard = deepcopy(old_hard)
    assert build_solidworks_command("1000000199", old_hard, hard)["models"][0]["extraProperties"]["技术要求"].count("硬度要求：") == 2
    assert old_hard == frozen_hard, "Historical duplicate notes are not rewritten"
    # Recovery uses engineering equivalence, while retaining every original condition.
    for row in rows:
        first, second = {**row["a"], "requirement_id": "legacy_note", "recognition_key": None, "need_human_review": False}, {**row["b"], "recognition_key": "new_note", "page": 1}
        candidate = {**second, "original_content": second["content"], "recognized_content": second["content"], "original_number": None, "source_order": 1}
        recovered = recovery_preview({"technical_requirements": [first]}, [candidate])["items"]
        assert bool(recovered) is not row["same"], row
    engine_hard = [
        {"field": "hardness", "value": body, "source": [f"ocr-{i}"], "page": 1, "position": [1, 2, 3, 4]}
        for i, body in enumerate(("硬度 HRC45-50", "HRC45~50"))]
    recognized_hard = collect_technical_requirements(engine_hard)
    assert len(recognized_hard) == 1 and len(recognized_hard[0]["recognition_aliases"]) == 1
    engine_hard[1]["page"] = 2
    assert len(collect_technical_requirements(engine_hard)) == 2, "Independent pages stay separate"
    eight = eight_category_review(rows)
    confirmed_eight = deepcopy(eight)
    for item in confirmed_eight["technical_requirements"]:
        item["need_human_review"] = False
    eight_package = build_generation_parameter_package(confirmed_eight)
    assert len(eight_package["solidworks_preview"]["extraProperties"]["技术要求"].splitlines()) == 16
    return {"pairs": rows, "review": order2_review(), "package": package, "merged": merged,
            "hardness_review": hard, "hardness_package": hard_package, "eight_review": eight, "eight_package": eight_package, "eight_pending_package": build_generation_parameter_package(eight)}


if __name__ == "__main__":
    result = run()
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=True))
    else:
        print(f"PASS: {len(result['pairs'])} safe equivalence fixtures, order2 14 notes + title-block Ra, aliases, confirmation and frozen requests")
