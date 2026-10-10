from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.qwen_vision_adapter import QWEN_SYSTEM_PROMPT, qwen_payload_to_candidates
from ai_design_review.io_utils import read_json
from ai_design_review.material_catalog import load_material_catalog
from ai_design_review.parameter_change_proposal import build_parameter_change_proposal, apply_parameter_change_proposal
from ai_design_review.workflow import DrawingReviewWorkflow, apply_standardization_to_review


ROOT = Path(__file__).resolve().parents[1]


def recognized(material: str | None, *, alternatives: list | None = None,
               primaries: list | None = None, requirements: list | None = None,
               notes: str = "", spring_type: str = "compression_spring") -> dict:
    payload = {
        "spring_type": {"value": spring_type, "confidence": 0.95},
        "parameters": {
            "material": {"value": material, "confidence": 0.99, "evidence": str(material or "")},
            "wire_diameter": {"value": 0.9, "unit": "mm", "confidence": 0.95},
            "outer_diameter": {"value": 8.25, "unit": "mm", "confidence": 0.95},
            "mean_diameter": {"value": 7.35, "unit": "mm", "confidence": 0.95},
            "free_length": {"value": 30.25, "unit": "mm", "confidence": 0.95},
            "total_coils": {"value": 10, "unit": "turns", "confidence": 0.95},
            "active_coils": {"value": 8, "unit": "turns", "confidence": 0.95},
        },
        "material_alternatives": alternatives or [],
        "primary_materials": primaries or [],
        "technical_requirements": requirements or [],
        "notes": notes,
    }
    candidates = qwen_payload_to_candidates(payload)
    return DrawingReviewWorkflow(read_json(ROOT / "config/factory_rules.json")).run(
        None, candidates, run_standardization=False,
    )


def alternative(value: str, *, allowed: bool = True) -> dict:
    return {"value": value, "evidence": f"允许换用 {value}" if allowed else value,
            "page": 1, "explicitly_allowed": allowed}


def assert_catalog_recognition() -> None:
    assert "material_alternatives" in QWEN_SYSTEM_PROMPT
    for entry in load_material_catalog()["items"]:
        result = recognized(entry["standard_value"])["spring_parameters"]["material"]
        assert result["value"] == entry["display_name"], result
        assert result["standard_value"] == entry["standard_value"]
        assert result["raw_value"] == entry["standard_value"]
        assert result["need_human_review"] is True
        assert result["material_selection_source"] == "drawing"
    for unknown in ("ХН70МВТЮБ ГОСТ 5632-72", "SUS316L", "55CrSiA"):
        result = recognized(unknown)["spring_parameters"]["material"]
        assert result["value"] == "", result
        assert result["raw_value"] == unknown
    result = recognized(None)["spring_parameters"]["material"]
    assert not result["value"]
    # Existing spring families retain their old material normalization.
    result = recognized("65Mn", spring_type="torsion_spring")["spring_parameters"]["material"]
    assert result["value"] == "65Mn", result


def assert_alternatives_and_conflicts() -> None:
    original = "ХН70МВТЮБ ГОСТ 5632-72"
    requirement = {"type": "other", "content": "允许换用 INCONEL 750 或类似材料",
                   "original_content": "Допускается замена материала на INCONEL 750 или аналоги",
                   "page": 1, "original_number": 14}
    review = recognized(original, alternatives=[alternative("INCONEL 750")], requirements=[requirement])
    material = review["spring_parameters"]["material"]
    assert material["value"] == "Inconel X750 镍基合金钢", material
    assert material["raw_value"] == original
    assert material["need_human_review"] is True
    assert material["material_selection_source"] == "drawing_substitute"
    assert material["material_substitution_evidence"]["evidence"]
    assert any("INCONEL 750" in item["content"] for item in review["technical_requirements"])
    # Existing raw notes/requirements suffice; no additional model call is made.
    assert recognized(original, requirements=[requirement])["spring_parameters"]["material"]["value"] == material["value"]
    assert recognized(original, notes="允许换用 INCONEL 750")["spring_parameters"]["material"]["value"] == material["value"]
    primary = recognized("SUS304", alternatives=[alternative("INCONEL 750")])["spring_parameters"]["material"]
    assert primary["value"] == "SUS304 不锈钢"
    assert primary["material_selection_source"] == "drawing"
    multi = recognized(original, alternatives=[alternative("INCONEL 750"), alternative("SUS304")])["spring_parameters"]["material"]
    assert not multi["value"] and multi["material_match_status"] == "conflict", multi
    for primaries in ([{"value": "SUS304"}, {"value": "SUS316"}],
                      [{"value": original}, {"value": "SUS304"}]):
        multi = recognized(None, primaries=primaries)["spring_parameters"]["material"]
        assert not multi["value"] and multi["material_match_status"] == "conflict", multi
    for alternatives, notes in (([alternative("SUS304", allowed=False)], ""), ([], "可选类似材料")):
        assert not recognized(original, alternatives=alternatives, notes=notes)["spring_parameters"]["material"]["value"]


def proposal_review() -> dict:
    def param(value: object, unit: str | None = None) -> dict:
        return {"value": value, "unit": unit, "need_human_review": False, "source": ["human_confirmed"]}
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_parameters": {
            "material": {**param("SUS304"), "raw_value": "原图材质 SUS304", "standard_value": "SUS304"},
            "wire_diameter": param(0.9, "mm"), "mean_diameter": param(7.35, "mm"),
            "outer_diameter": param(8.25, "mm"), "inner_diameter": param(6.45, "mm"),
            "free_length": param(30.25, "mm"), "total_coils": param(10, "turns"),
            "active_coils": param(8, "turns"), "handedness": param("right"),
            "end_grinding": param(1), "end_coils_closed": param(1), "load_points": [],
        },
        "technical_requirements": [], "standard_selection": {}, "standardization_results": [],
        "derived_parameters": {}, "manual_confirmations": {"material": {"confirmed": True, "value": "SUS304"}},
    }


def assert_proposal_material_selection() -> None:
    review = proposal_review()
    before = deepcopy(review["spring_parameters"])
    proposal = build_parameter_change_proposal(review, [{
        "type": "propose_parameter_patch", "target_field": "material", "proposed_value": "INCONEL 718",
    }], user_goal="材料改成 INCONEL 718")
    assert proposal["status"] in {"ready", "warning"}, proposal
    assert review["spring_parameters"] == before
    change = next(item for item in proposal["direct_changes"] if item["field"] == "material")
    assert change["after"] == "Inconel 718 镍基合金钢"
    applied, _ = apply_parameter_change_proposal(review, proposal["proposal_id"], version=proposal["version"])
    material = applied["spring_parameters"]["material"]
    assert material["value"] == "Inconel 718 镍基合金钢"
    assert material["standard_value"] == "Inconel 718"
    assert material["raw_value"] == "原图材质 SUS304"
    assert material["material_selection_source"] == "ai"
    assert material["need_human_review"] is False  # User applied the complete proposal.
    assert "material" not in applied["manual_confirmations"]
    assert applied["manual_confirmations"]["parameter_change_proposal_material"]["raw_value"] == material["raw_value"]
    apply_standardization_to_review(applied)
    assert applied["spring_parameters"]["material"]["standard_value"] == material["standard_value"]
    for invalid in ("ХН70МВТЮБ", "SUS316L", "SUS304 or SUS316"):
        baseline = proposal_review()
        proposal = build_parameter_change_proposal(baseline, [{
            "type": "propose_parameter_patch", "target_field": "material", "proposed_value": invalid,
        }], user_goal="修改材料")
        assert proposal["status"] == "blocked", proposal
        assert any(item["code"] == "material_not_in_catalog" for item in proposal["blocking_issues"])
        assert baseline["spring_parameters"]["material"]["value"] == "SUS304"


def main() -> None:
    assert_catalog_recognition()
    assert_alternatives_and_conflicts()
    assert_proposal_material_selection()
    print("material recognition and AI proposal integration tests passed")


if __name__ == "__main__":
    main()
