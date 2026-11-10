"""Offline flattening contract, recognition and history regression; emits shared browser fixtures."""
from copy import deepcopy
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_generation_readiness import _ready_review
from ai_design_review import flattening
from ai_design_review.generation_contract import apply_generation_defaults, COMPRESSION_GENERATION_INPUT_FIELDS
from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.generation_schemas import GenerationParameterPackageV1, GenerationParameterPackageV2
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.engines.ocr_adapter import ocr_payload_to_candidates
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.fusion import fuse_candidates
from ai_design_review.parameter_change_proposal import _normalize_action, _apply_action, build_parameter_change_proposal, apply_parameter_change_proposal
from ai_design_review.balloons import generate_balloons
from ai_design_review.standardization_chat_agent import _extract_requested_value


def fixtures():
    samples = []
    for name, item in [
        ("missing", None), ("pending-zero", {"value": 0, "need_human_review": True}),
        ("pending-one", {"value": 1, "need_human_review": True}),
        ("confirmed-zero", {"value": 0, "need_human_review": False}),
        ("confirmed-one", {"value": 1, "need_human_review": False}),
        ("invalid", {"value": 2, "need_human_review": False}),
        ("conflict", {"value": 0, "flattening_conflict": True, "need_human_review": False}),
        ("human-clear", {"value": None, "source": ["human_edited"], "need_human_review": True}),
        ("raw-zero", {"value": None, "raw_value": 0, "need_human_review": True}),
        ("invalid-snapshot", {"value": 0, "need_human_review": False, "confirmation_snapshot": "legacy"}),
        ("stale-snapshot", {"value": 1, "need_human_review": False, "confirmation_snapshot": {"value": 0}}),
    ]:
        review = _ready_review()
        review["spring_parameters"]["material"]["value"] = "SUS304"
        review["spring_parameters"].pop("flattening")
        if item is not None: review["spring_parameters"]["flattening"] = item
        package = build_generation_parameter_package(review)
        samples.append({"name": name, "review": review, "package": package})
    return samples


def main():
    review = _ready_review(); del review["spring_parameters"]["flattening"]
    assert apply_generation_defaults(review) == ["flattening"]
    default = deepcopy(review["spring_parameters"]["flattening"])
    assert default["value"] == 0 and default["need_human_review"] and default["default_source"] == flattening.DEFAULT_SOURCE
    assert not apply_generation_defaults(review)
    for item in ({"value": None, "source": ["manual"]}, {"value": None, "flattening_conflict": True}, {"value": 1}, {"value": 2}):
        review["spring_parameters"]["flattening"] = deepcopy(item)
        assert not flattening.ensure(review)
        assert review["spring_parameters"]["flattening"] == item
    del review["spring_parameters"]["flattening"]
    review["conflicts"] = [{"field": "flattening"}]
    assert not flattening.ensure(review) and review["spring_parameters"]["flattening"]["value"] is None
    review["drawing_summary"]["spring_type"] = "extension_spring"
    review["spring_parameters"].pop("flattening")
    assert not flattening.ensure(review) and "flattening" not in review["spring_parameters"]
    for text, expected in [("两端制扁", 1), ("两端不制扁", 0), ("无需制扁", 0), ("不要制扁", 0), ("不需要 制扁", 0), ("NO FLATTENING", 0), ("non-flattened", 0), ("是否制扁：否", 0), ("端面磨平，两端并紧", None)]:
        ocr = ocr_payload_to_candidates({"texts": [{"text": text, "page": 1}]})
        selected = fuse_candidates(ocr)["fields"].get("flattening")
        assert (selected["value"] if selected else None) == expected, (text, selected)
        qwen = qwen_payload_to_candidates({"parameters": {"flattening": {"value": 1, "evidence": text}}})
        selected = fuse_candidates(qwen)["fields"]["flattening"]
        assert selected["value"] == expected and selected["need_human_review"], (text, selected)
    mixed = fuse_candidates([{"field": "flattening", "value": v, "source": "ocr", "evidence": text, "confidence": .9}
                            for v, text in [(0, "不制扁"), (1, "制扁")]])["fields"]["flattening"]
    assert mixed["flattening_conflict"] and mixed["value"] is None
    for text, expected in [("是否制扁改为否", 0), ("是否制扁改为1", 1), ("不制扁", 0)]:
        assert _extract_requested_value(text, "flattening")[0] == expected
    review = _ready_review()
    action = _normalize_action({"type": "propose_parameter_patch", "target_field": "flattening", "proposed_value": "制扁"})
    _apply_action(review, action, confirmation_source="human_confirmed")
    assert review["spring_parameters"]["flattening"]["value"] == 1
    assert review["spring_parameters"]["flattening"]["need_human_review"]
    proposal_review = _ready_review()
    proposal = build_parameter_change_proposal(proposal_review, [action], user_goal="改为制扁")
    assert proposal and proposal["status"] in {"ready", "warning"}, proposal
    applied, _ = apply_parameter_change_proposal(proposal_review, proposal["proposal_id"], version=proposal["version"])
    assert applied["spring_parameters"]["flattening"]["need_human_review"]
    assert not applied["manual_confirmations"]["parameter_change_proposal_flattening"]["confirmed"]
    assert all(entry.get("field") != "flattening" for entry in generate_balloons(applied["spring_parameters"], [], []))
    assert all(flattening.normalize(value) is None for value in [2, float("inf"), {}, [1], "制扁2", "0/1"])
    previous = _ready_review()
    omitted = deepcopy(previous); omitted["spring_parameters"].pop("flattening")
    flattening.prepare_save(omitted, previous=previous)
    assert omitted["spring_parameters"]["flattening"]["value"] == 0 and omitted["spring_parameters"]["flattening"]["need_human_review"] is False
    cleared = deepcopy(previous); cleared["spring_parameters"]["flattening"] = {"value": None}
    flattening.prepare_save(cleared, [{"event_type": "parameter_value_updated", "target_field": "flattening"}], previous=previous)
    assert cleared["spring_parameters"]["flattening"]["value"] is None and cleared["spring_parameters"]["flattening"]["need_human_review"]
    samples = fixtures()
    for sample in samples:
        item = sample["review"]["spring_parameters"].get("flattening")
        package = sample["package"]
        expected = sample["name"] in {"confirmed-zero", "confirmed-one"}
        exported = package["generation_parameters"]["spring_parameters"]
        model = package["solidworks_preview"]["modelParameters"]
        assert ("flattening" in exported) == expected and ("是否制扁" in model) == expected, sample["name"]
        state = assess_generation_readiness(deepcopy(sample["review"]))
        assert state["status"] in {"ready", "ready_with_warnings"} and state["confirmed_core_count"] == 8
        assert not any(x["field"] == "flattening" for x in state["pending_fields"] + state["missing_fields"])
        assert any(x["field"] == "flattening" for x in state["warnings"]) != expected
        if expected:
            assert type(model["是否制扁"]) is int and model["是否制扁"] == item["value"]
            assert all(exported["flattening"][key] is None for key in ("unit", "tolerance_upper", "tolerance_lower"))
        GenerationParameterPackageV2.model_validate(package)
    frozen = deepcopy(samples[0]["package"])
    old_command = build_solidworks_command("1000000001", frozen, _ready_review())
    assert "是否制扁" not in old_command["models"][0]["modelParameters"]
    old_v1 = deepcopy(frozen); old_v1["schema_version"] = "spring_generation_parameters/v1"
    old_v1["export_policy"]["parameter_filter"] = "frozen_compression_inputs_v1_human_confirmed_only"
    old_v1["generation_parameters"]["spring_parameters"].pop("material"); old_v1.pop("solidworks_preview")
    GenerationParameterPackageV1.model_validate(old_v1)
    assert "是否制扁" not in build_solidworks_command("1000000002", old_v1, _ready_review())["models"][0]["modelParameters"]
    assert len(COMPRESSION_GENERATION_INPUT_FIELDS) == 8
    assert samples[0]["package"]["derived_parameters"] == samples[3]["package"]["derived_parameters"]
    assert samples[0]["package"]["solidworks_preview"]["extraProperties"] == samples[3]["package"]["solidworks_preview"]["extraProperties"]
    print("PASS flattening: defaults, negative/conflict evidence, manual clear, AI edits, optional readiness, confirmed 0/1 export, frozen V1/V2 and unchanged calculations")

if __name__ == "__main__":
    if "--json" in sys.argv: print(json.dumps(fixtures()))
    else: main()
