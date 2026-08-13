from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.parameter_change_proposal import (  # noqa: E402
    ParameterProposalError,
    apply_parameter_change_proposal,
    build_parameter_change_proposal,
    discard_parameter_change_proposal,
    parameter_state_hash,
)
from ai_design_review.standardization_chat_agent import chat_about_standardization  # noqa: E402


def main() -> None:
    _assert_mean_change_synchronizes_and_applies_atomically()
    _assert_each_diameter_direction_and_multi_change()
    _assert_conflicting_explicit_diameters_are_blocked()
    _assert_vague_request_and_multi_turn_update()
    _assert_design_goal_needs_choice()
    _assert_stale_and_discard_guards()
    _assert_non_geometry_change_and_invalid_coils()
    _assert_end_condition_keeps_protocol_field_in_sync()
    _assert_calculated_and_load_dependencies_are_included()
    _assert_multi_turn_constraints()
    _assert_dynamic_standardization_does_not_expire_proposal()
    print("parameter change proposal tests passed")


def _assert_mean_change_synchronizes_and_applies_atomically() -> None:
    review = _review()
    original_parameters = deepcopy(review["spring_parameters"])
    proposal = build_parameter_change_proposal(
        review,
        [_patch("mean_diameter", 26, "mm")],
        user_goal="中径改成26mm",
        review_revision=3,
    )
    assert proposal and proposal["status"] in {"ready", "warning"}, proposal
    assert review["spring_parameters"] == original_parameters
    synchronized = {item["field"]: item for item in proposal["synchronized_changes"]}
    assert synchronized["outer_diameter"]["after"] == 32
    assert synchronized["inner_diameter"]["after"] == 20

    applied, result = apply_parameter_change_proposal(
        review,
        proposal["proposal_id"],
        version=proposal["version"],
    )
    values = {field: applied["spring_parameters"][field]["value"] for field in (
        "wire_diameter", "mean_diameter", "outer_diameter", "inner_diameter"
    )}
    assert values == {"wire_diameter": 6, "mean_diameter": 26, "outer_diameter": 32, "inner_diameter": 20}
    assert "human_confirmed" in applied["spring_parameters"]["mean_diameter"]["source"]
    assert "parameter_change_proposal_derived" in applied["spring_parameters"]["outer_diameter"]["source"]
    assert result["proposal"]["status"] == "applied"
    assert review["spring_parameters"] == original_parameters


def _assert_each_diameter_direction_and_multi_change() -> None:
    outer_review = _review()
    outer = build_parameter_change_proposal(outer_review, [_patch("outer_diameter", 34, "mm")], user_goal="外径34")
    synced = {item["field"]: item["after"] for item in outer["synchronized_changes"]}
    assert synced["mean_diameter"] == 28
    assert synced["inner_diameter"] == 22

    inner_review = _review()
    inner = build_parameter_change_proposal(inner_review, [_patch("inner_diameter", 18, "mm")], user_goal="内径18")
    synced = {item["field"]: item["after"] for item in inner["synchronized_changes"]}
    assert synced["mean_diameter"] == 24
    assert synced["outer_diameter"] == 30

    wire_review = _review()
    wire = build_parameter_change_proposal(wire_review, [_patch("wire_diameter", 5, "mm")], user_goal="线径5")
    synced = {item["field"]: item["after"] for item in wire["synchronized_changes"]}
    assert synced["outer_diameter"] == 47
    assert synced["inner_diameter"] == 37

    first = _review()
    second = _review()
    actions = [_patch("wire_diameter", 5, "mm"), _patch("mean_diameter", 28, "mm")]
    a = build_parameter_change_proposal(first, actions, user_goal="线径5，中径28")
    b = build_parameter_change_proposal(second, list(reversed(actions)), user_goal="中径28，线径5")
    a_sync = {(item["field"], item["after"]) for item in a["synchronized_changes"]}
    b_sync = {(item["field"], item["after"]) for item in b["synchronized_changes"]}
    assert a_sync == b_sync == {("outer_diameter", 33), ("inner_diameter", 23)}

    pair_review = _review()
    pair = build_parameter_change_proposal(
        pair_review,
        [_patch("outer_diameter", 34, "mm"), _patch("inner_diameter", 24, "mm")],
        user_goal="外径34，内径24",
    )
    pair_sync = {item["field"]: item["after"] for item in pair["synchronized_changes"]}
    assert pair_sync == {"wire_diameter": 5, "mean_diameter": 29}


def _assert_conflicting_explicit_diameters_are_blocked() -> None:
    proposal = build_parameter_change_proposal(
        _review(),
        [
            _patch("wire_diameter", 6, "mm"),
            _patch("mean_diameter", 26, "mm"),
            _patch("outer_diameter", 35, "mm"),
        ],
        user_goal="冲突的直径组合",
    )
    assert proposal["status"] == "blocked", proposal
    assert any(item.get("code") == "diameter_constraint_conflict" for item in proposal["blocking_issues"])


def _assert_vague_request_and_multi_turn_update() -> None:
    review = _review()
    first = chat_about_standardization(review, "中径太大了，想改小点", use_llm=False, review_revision=1)
    proposal = first["change_proposal"]
    assert proposal["status"] == "needs_input"
    assert proposal["clarifying_questions"]
    before = deepcopy(review["spring_parameters"])

    second = chat_about_standardization(
        review,
        "中径改成26mm",
        use_llm=False,
        active_proposal_id=proposal["proposal_id"],
        review_revision=2,
    )
    updated = second["change_proposal"]
    assert updated["proposal_id"] == proposal["proposal_id"]
    assert updated["version"] == 2
    assert updated["status"] in {"ready", "warning"}
    assert review["spring_parameters"] == before


def _assert_design_goal_needs_choice() -> None:
    proposal = build_parameter_change_proposal(
        _review(),
        [_patch("spring_rate", 2.5, "N/mm")],
        user_goal="刚度改成2.5",
    )
    assert proposal["status"] == "needs_input"
    assert proposal["recommendations"][0]["field"] == "spring_rate"
    assert "允许调整哪些建模参数" in proposal["clarifying_questions"][0]


def _assert_stale_and_discard_guards() -> None:
    review = _review()
    proposal = build_parameter_change_proposal(review, [_patch("free_length", 65, "mm")], user_goal="自由长度65")
    review["spring_parameters"]["free_length"]["value"] = 66
    try:
        apply_parameter_change_proposal(review, proposal["proposal_id"], version=proposal["version"])
    except ParameterProposalError as exc:
        assert exc.code == "proposal_stale"
    else:
        raise AssertionError("stale proposal should not apply")

    discard_review = _review()
    discard = build_parameter_change_proposal(discard_review, [_patch("free_length", 60, "mm")], user_goal="自由长度60")
    discarded = discard_parameter_change_proposal(discard_review, discard["proposal_id"], version=discard["version"])
    assert discarded["status"] == "discarded"
    assert discard_review["spring_parameters"]["free_length"]["value"] == 70


def _assert_non_geometry_change_and_invalid_coils() -> None:
    handedness = build_parameter_change_proposal(
        _review(),
        [_patch("handedness", "left")],
        user_goal="改为左旋",
    )
    assert handedness["status"] in {"ready", "warning"}
    assert handedness["synchronized_changes"] == []

    invalid = build_parameter_change_proposal(
        _review(),
        [_patch("total_coils", 7), _patch("active_coils", 8)],
        user_goal="总圈数7，有效圈数8",
    )
    assert invalid["status"] == "blocked"
    assert any("有效圈数不能大于总圈数" in item.get("message", "") for item in invalid["blocking_issues"])


def _assert_end_condition_keeps_protocol_field_in_sync() -> None:
    review = _review()
    proposal = build_parameter_change_proposal(
        review,
        [_patch("end_type", "两端不并紧")],
        user_goal="端圈不压并",
    )
    synchronized = {item["field"]: item["after"] for item in proposal["synchronized_changes"]}
    assert synchronized["end_coils_closed"] == 0
    applied, _ = apply_parameter_change_proposal(review, proposal["proposal_id"], version=proposal["version"])
    assert applied["spring_parameters"]["end_type"]["value"] == "两端不并紧"
    assert applied["spring_parameters"]["end_coils_closed"]["value"] == 0


def _assert_calculated_and_load_dependencies_are_included() -> None:
    review = _review()
    review["spring_parameters"]["material"] = _param("SUS304")
    review["spring_parameters"]["end_grinding"] = _param("两端磨削")
    review["spring_parameters"]["load_points"] = [
        {"label": "F1", "height": 50, "height_unit": "mm", "force": 100, "force_unit": "N", "need_human_review": False}
    ]
    proposal = build_parameter_change_proposal(
        review,
        [_patch("wire_diameter", 5, "mm"), _patch("free_length", 65, "mm")],
        user_goal="线径5，自由长度65",
    )
    synchronized = {item["field"]: item for item in proposal["synchronized_changes"]}
    assert synchronized["solid_height"]["after"] == 50
    assert synchronized["spring_rate"]["after"] > 0
    derived = {item["field"]: item for item in proposal["derived_changes"]}
    assert derived["load_points.F1.deflection"]["before"] == 20
    assert derived["load_points.F1.deflection"]["after"] == 15


def _assert_multi_turn_constraints() -> None:
    review = _review()
    first = chat_about_standardization(review, "中径改成26mm", use_llm=False, review_revision=1)
    proposal = first["change_proposal"]
    within = chat_about_standardization(
        review,
        "外径不能超过32mm",
        use_llm=False,
        active_proposal_id=proposal["proposal_id"],
        review_revision=2,
    )["change_proposal"]
    assert within["version"] == 2
    assert within["status"] in {"ready", "warning"}
    assert within["constraints"][0]["operator"] == "max"

    apply_review = deepcopy(review)
    applied, _ = apply_parameter_change_proposal(
        apply_review,
        within["proposal_id"],
        version=within["version"],
    )
    assert applied["spring_parameters"]["mean_diameter"]["value"] == 26
    assert applied["spring_parameters"]["outer_diameter"]["value"] == 32

    unrelated_review = deepcopy(review)
    unrelated = chat_about_standardization(
        unrelated_review,
        "为什么自由长度会影响细长比？",
        use_llm=False,
        active_proposal_id=proposal["proposal_id"],
        review_revision=3,
    )
    assert "change_proposal" not in unrelated
    stored = next(
        item
        for item in unrelated_review["parameter_change_proposals"]
        if item["proposal_id"] == proposal["proposal_id"]
    )
    assert stored["version"] == 2

    violated = chat_about_standardization(
        review,
        "外径不能超过30mm",
        use_llm=False,
        active_proposal_id=proposal["proposal_id"],
        review_revision=3,
    )["change_proposal"]
    assert violated["version"] == 3
    assert violated["status"] == "needs_input"
    assert "允许调整哪些关联参数" in violated["clarifying_questions"][0]


def _assert_dynamic_standardization_does_not_expire_proposal() -> None:
    review = _review()
    review["spring_parameters"]["accuracy_grade"] = _param("2级")
    baseline = parameter_state_hash(review)
    proposal = build_parameter_change_proposal(
        review,
        [_patch("mean_diameter", 26, "mm")],
        user_goal="中径改成26mm",
    )
    review["standardization_results"] = [{"rule_id": "DIA", "status": "suggested", "basis": "动态建议"}]
    review["spring_parameters"]["mean_diameter"]["confidence"] = 0.55
    review["spring_parameters"]["mean_diameter"]["evidence"] = "刷新后的说明"
    review["spring_parameters"]["mean_diameter"]["source"] = ["formula_calculation"]
    assert parameter_state_hash(review) == baseline
    updated = build_parameter_change_proposal(
        review,
        [{"type": "proposal_constraint", "target_field": "outer_diameter", "operator": "max", "constraint_value": 32}],
        user_goal="外径不能超过32mm",
        active_proposal_id=proposal["proposal_id"],
    )
    assert updated["version"] == 2
    assert updated["status"] in {"ready", "warning"}


def _patch(field: str, value: object, unit: str | None = None) -> dict:
    return {
        "type": "propose_parameter_patch",
        "target_field": field,
        "proposed_value": value,
        "unit": unit,
        "apply_policy": "proposal_only",
    }


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_parameters": {
            "wire_diameter": _param(6, "mm"),
            "mean_diameter": _param(42, "mm"),
            "outer_diameter": _param(48, "mm"),
            "inner_diameter": _param(36, "mm"),
            "free_length": _param(70, "mm"),
            "total_coils": _param(10, "turns"),
            "active_coils": _param(8, "turns"),
            "handedness": _param("right"),
            "end_grinding": _param(1),
            "end_coils_closed": _param(1),
            "load_points": [],
        },
        "technical_requirements": [],
        "standard_selection": {},
        "standardization_results": [],
        "derived_parameters": {},
        "manual_confirmations": {},
    }


def _param(value: object, unit: str | None = None) -> dict:
    return {
        "value": value,
        "unit": unit,
        "need_human_review": False,
        "source": ["human_confirmed"],
    }


if __name__ == "__main__":
    main()
