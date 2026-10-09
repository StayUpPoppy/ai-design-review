from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.fusion import fuse_candidates
from ai_design_review.technical_requirement_recognition import collect_technical_requirements, recovery_preview
from ai_design_review.technical_requirements import technical_requirements_are_duplicates
from ai_design_review.technical_translation import validate_translation
from ai_design_review.workflow import DrawingReviewWorkflow
from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command
from test_generation_readiness import _ready_review


def main():
    payload = {"spring_type": "compression_spring", "parameters": {"wire_diameter": {"value": 1.8}, "total_coils": {"value": 10}}, "technical_requirements": [
        {"type": "process", "content": "施加力 F3 并保持负载不少于 6 h", "original_content": "9. Заневолить силой F3 6 h", "original_number": "9", "source_order": 9, "page": 1},
        {"type": "process", "content": "强压后检查残余变形", "original_number": "10", "source_order": 10, "page": 1},
        {"type": "other", "content": "未注尺寸以3D为准", "original_number": "2", "source_order": 11, "page": 1},
        {"type": "other", "content": "允许使用 INCONEL 750", "original_number": "2", "source_order": 12, "page": 1},
        {"type": "other", "content": "未注尺寸以3D为准", "page": 2},
    ]}
    candidates = qwen_payload_to_candidates(payload)
    fused = fuse_candidates(candidates)
    notes = fused["technical_requirements"]
    assert len(notes) == 5 and len({note["requirement_id"] for note in notes}) == 5
    assert [note["type"] for note in notes] == ["process", "process", "other", "other", "other"]
    assert [note["original_number"] for note in notes[:4]] == ["9", "10", "2", "2"]
    assert notes[-1]["original_number"] is None
    repeated = qwen_payload_to_candidates({"technical_requirements": [
        {"type": "other", "content": "去除毛刺", "original_number": "2", "source_order": 2},
        {"type": "other", "content": "去除毛刺", "original_number": "2", "source_order": 2}]})
    assert len(collect_technical_requirements(repeated)) == 2, "duplicate source numbers are not unique identities"
    assert all(note["need_human_review"] for note in notes)
    assert not any(conflict.get("field") in {"process_requirement", "other_requirement"} for conflict in fused["conflicts"])
    assert len(collect_technical_requirements([*candidates, *candidates])) == 5, "same occurrence deduplicates"
    assert len(collect_technical_requirements(qwen_payload_to_candidates(payload))) == 5
    assert not technical_requirements_are_duplicates(notes[2], notes[4]), "identical words at distinct positions remain independent"
    built = DrawingReviewWorkflow({}).run(None, candidates, run_standardization=False)
    assert len(built["technical_requirements"]) == 5
    assert built["spring_parameters"]["wire_diameter"]["value"] == 1.8
    assert built["spring_parameters"]["total_coils"]["value"] == 10
    assert validate_translation("9. Load F3=2850 N", "载荷 F3=2850 N") is None
    assert validate_translation("12.5 mm", "5 mm"), "decimal engineering numbers remain protected"

    review = _ready_review()
    review["technical_requirements"] = copy.deepcopy(notes[1:3])
    original = copy.deepcopy(review)
    preview = recovery_preview(review, notes)
    assert len(preview["items"]) == 3 and review == original
    assert all(row["status"] == "available" for row in preview["items"])
    legacy = copy.deepcopy(notes[1])
    legacy.pop("recognition_key")
    legacy["content"] = "用户修改后的工艺要求"
    legacy["need_human_review"] = False
    legacy["original_content"] = notes[1]["original_content"]
    review["technical_requirements"] = [legacy]
    preview = recovery_preview(review, notes)
    assert all(row["requirement"]["recognition_key"] != notes[1]["recognition_key"] for row in preview["items"])
    review["change_history"] = [{"event_type": "technical_requirement_deleted", "before_state": notes[0], "metadata": {"requirement_id": notes[0]["requirement_id"]}}]
    assert all(row["requirement"]["recognition_key"] != notes[0]["recognition_key"] for row in recovery_preview(review, notes)["items"])
    review["change_history"].append({"event_type": "technical_requirement_restored", "after_state": notes[0], "metadata": {"requirement_id": notes[0]["requirement_id"]}})
    assert all(row["requirement"]["recognition_key"] != notes[0]["recognition_key"] for row in recovery_preview(review, notes)["items"]), "old restore does not cancel a newer deletion"
    review["change_history"] = []
    review["agent_actions"] = [{"technical_requirement_changes": [{"operation": "delete", "requirement_id": notes[0]["requirement_id"], "before": {"content": "人工修改后再删除的正文"}}],
                                "rollback": {"full_state": {"technical_requirements": [notes[0]]}}}]
    assert all(row["requirement"]["recognition_key"] != notes[0]["recognition_key"] for row in recovery_preview(review, notes)["items"]), "AI-deleted notes are not missing recognition"
    review["agent_actions"][0]["reverted"] = True
    assert any(row["requirement"]["recognition_key"] == notes[0]["recognition_key"] for row in recovery_preview(review, notes)["items"]), "a reverted AI deletion is not a tombstone"

    ready = _ready_review()
    ready["technical_requirements"] = [copy.deepcopy(notes[2]), copy.deepcopy(notes[4])]
    for note in ready["technical_requirements"]:
        note["need_human_review"] = False
    assert not any("重复" in issue["message"] for issue in assess_generation_readiness(ready).get("pending_fields", []))
    package = build_generation_parameter_package(ready)
    text = package["generation_parameters"]["technical_requirements_text"]
    assert text == "1.其他要求：未注尺寸以3D为准\n2.其他要求：未注尺寸以3D为准"
    numbered = copy.deepcopy(ready)
    numbered["technical_requirements"] = [{"type": "other", "content": "9.未注尺寸以3D为准", "original_number": "9", "need_human_review": False}]
    assert build_generation_parameter_package(numbered)["generation_parameters"]["technical_requirements_text"] == "1.其他要求：未注尺寸以3D为准"
    numbered["technical_requirements"][0].pop("original_number")
    assert build_generation_parameter_package(numbered)["generation_parameters"]["technical_requirements_text"] == "1.其他要求：未注尺寸以3D为准", "legacy source numbering must not produce a second output number"
    frozen = copy.deepcopy(package)
    package["generation_parameters"]["technical_requirements_text"] = "技术要求\n" + text
    assert build_solidworks_command("1000000001", package, ready)["models"][0]["extraProperties"]["技术要求"] == text
    assert package["generation_parameters"]["technical_requirements_text"].startswith("技术要求\n"), "sending must not rewrite frozen package"
    assert frozen["solidworks_preview"]["modelParameters"] == build_solidworks_command("1000000002", package, ready)["models"][0]["modelParameters"]
    print("PASS: occurrence-based notes, order, identities, non-mutating recovery and unchanged SW geometry")


if __name__ == "__main__":
    main()
