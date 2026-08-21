from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.parameter_change_proposal import (  # noqa: E402
    apply_parameter_change_proposal,
    build_parameter_change_proposal,
)
from ai_design_review.standardization_chat_agent import chat_about_standardization  # noqa: E402
from ai_design_review.standardization_chat_llm import StandardizationChatLLMEngine  # noqa: E402
from ai_design_review.technical_requirements import (  # noqa: E402
    ensure_technical_requirement_ids,
    technical_requirement_confirmation_key,
)


def main() -> None:
    _assert_legacy_ids_are_stable_and_migrate_confirmation()
    _assert_add_update_delete_apply_as_confirmed()
    _assert_duplicate_and_conflicting_operations_are_blocked()
    _assert_mixed_parameter_and_requirement_scheme_is_atomic()
    _assert_chat_builds_mixed_parameter_and_requirement_scheme()
    _assert_local_rule_precedes_llm_and_ambiguity_needs_input()
    _assert_llm_receives_ids_and_returns_controlled_action()
    print("technical requirement proposal tests passed")


def _assert_legacy_ids_are_stable_and_migrate_confirmation() -> None:
    first = _review()
    first["technical_requirements"][0].pop("requirement_id", None)
    first["manual_confirmations"] = {"technical_0": {"confirmed": True, "value": "盐雾试验72小时。"}}
    second = deepcopy(first)
    assert ensure_technical_requirement_ids(first) is True
    assert ensure_technical_requirement_ids(second) is True
    first_id = first["technical_requirements"][0]["requirement_id"]
    second_id = second["technical_requirements"][0]["requirement_id"]
    assert first_id == second_id
    assert first["manual_confirmations"][technical_requirement_confirmation_key(first_id)]["confirmed"] is True


def _assert_add_update_delete_apply_as_confirmed() -> None:
    review = _review()
    add = build_parameter_change_proposal(
        review,
        [{
            "type": "propose_technical_requirement_add",
            "requirement_type": "surface",
            "content": "表面镀锌。",
        }],
        user_goal="新增表面镀锌",
    )
    assert add and add["status"] in {"ready", "warning"}, add
    assert add["technical_requirement_changes"][0]["operation"] == "add"
    assert len(review["technical_requirements"]) == 1
    applied_add, add_result = apply_parameter_change_proposal(review, add["proposal_id"], version=add["version"])
    assert len(applied_add["technical_requirements"]) == 2
    added = applied_add["technical_requirements"][1]
    assert added["need_human_review"] is False
    assert added["normalization_status"] == "human_confirmed"
    assert {"ai_chat", "human_confirmed"}.issubset(set(added["source"]))
    assert add_result["technical_requirement_changes"][0]["after"]["content"] == "表面镀锌。"
    assert applied_add["agent_actions"][-1]["restandardized"] is False
    assert "technical_requirements" in applied_add["agent_actions"][-1]["rollback"]["full_state"]

    existing_id = applied_add["technical_requirements"][0]["requirement_id"]
    update = build_parameter_change_proposal(
        applied_add,
        [{
            "type": "propose_technical_requirement_update",
            "requirement_id": existing_id,
            "requirement_type": "salt_spray",
            "content": "盐雾试验96小时。",
        }],
        user_goal="盐雾改为96小时",
    )
    updated_review, _ = apply_parameter_change_proposal(applied_add, update["proposal_id"], version=update["version"])
    updated = next(item for item in updated_review["technical_requirements"] if item["requirement_id"] == existing_id)
    assert updated["content"] == "盐雾试验96小时。"
    assert updated["need_human_review"] is False

    delete = build_parameter_change_proposal(
        updated_review,
        [{"type": "propose_technical_requirement_delete", "requirement_id": existing_id}],
        user_goal="删除盐雾要求",
    )
    deleted_review, _ = apply_parameter_change_proposal(updated_review, delete["proposal_id"], version=delete["version"])
    assert all(item["requirement_id"] != existing_id for item in deleted_review["technical_requirements"])


def _assert_duplicate_and_conflicting_operations_are_blocked() -> None:
    review = _review()
    duplicate = build_parameter_change_proposal(
        review,
        [{
            "type": "propose_technical_requirement_add",
            "requirement_type": "salt_spray",
            "content": "盐雾试验72小时。",
        }],
        user_goal="重复新增",
    )
    assert duplicate["status"] == "blocked"
    assert any(item.get("code") == "technical_requirement_duplicate" for item in duplicate["blocking_issues"])

    requirement_id = review["technical_requirements"][0]["requirement_id"]
    conflict = build_parameter_change_proposal(
        review,
        [
            {
                "type": "propose_technical_requirement_update",
                "requirement_id": requirement_id,
                "content": "盐雾试验96小时。",
            },
            {"type": "propose_technical_requirement_delete", "requirement_id": requirement_id},
        ],
        user_goal="同时修改和删除",
    )
    assert conflict["status"] == "blocked"
    assert any(item.get("code") == "technical_requirement_operation_conflict" for item in conflict["blocking_issues"])


def _assert_mixed_parameter_and_requirement_scheme_is_atomic() -> None:
    review = _review()
    requirement_id = review["technical_requirements"][0]["requirement_id"]
    proposal = build_parameter_change_proposal(
        review,
        [
            {"type": "propose_parameter_patch", "target_field": "free_length", "proposed_value": 65, "unit": "mm"},
            {
                "type": "propose_technical_requirement_update",
                "requirement_id": requirement_id,
                "content": "盐雾试验120小时。",
            },
        ],
        user_goal="自由长度65，盐雾120小时",
    )
    assert proposal["status"] in {"ready", "warning"}, proposal
    assert review["spring_parameters"]["free_length"]["value"] == 70
    assert review["technical_requirements"][0]["content"] == "盐雾试验72小时。"
    applied, _ = apply_parameter_change_proposal(review, proposal["proposal_id"], version=proposal["version"])
    assert applied["spring_parameters"]["free_length"]["value"] == 65
    assert applied["technical_requirements"][0]["content"] == "盐雾试验120小时。"
    assert applied["agent_actions"][-1]["restandardized"] is True


def _assert_chat_builds_mixed_parameter_and_requirement_scheme() -> None:
    review = _review()
    result = chat_about_standardization(
        review,
        "中径调整到25mm，并新增一条表面镀锌。",
        use_llm=False,
    )
    proposal = result["change_proposal"]
    assert result["intent"]["type"] == "multi_constraint_change_request"
    assert any(item.get("field") == "mean_diameter" for item in proposal["direct_changes"])
    assert proposal["technical_requirement_changes"][0]["operation"] == "add"
    applied, _ = apply_parameter_change_proposal(review, proposal["proposal_id"], version=proposal["version"])
    assert applied["spring_parameters"]["mean_diameter"]["value"] == 25
    assert any(str(item.get("content") or "").startswith("表面镀锌") for item in applied["technical_requirements"])

    note_named_like_parameter = _review()
    note_named_like_parameter["technical_requirements"][0].update(
        {"type": "process", "content": "两端磨平。"}
    )
    delete_result = chat_about_standardization(note_named_like_parameter, "删除两端磨平这条要求", use_llm=False)
    delete_proposal = delete_result["change_proposal"]
    assert not delete_proposal["direct_changes"]
    assert delete_proposal["technical_requirement_changes"][0]["operation"] == "delete"


def _assert_local_rule_precedes_llm_and_ambiguity_needs_input() -> None:
    class MustNotRun:
        def chat(self, *_: object, **__: object) -> dict:
            raise AssertionError("clear local technical-requirement command must not call LLM")

    review = _review()
    result = chat_about_standardization(
        review,
        "增加一条表面镀锌。",
        use_llm=True,
        llm_engine=MustNotRun(),
    )
    assert result["intent"]["type"] == "technical_requirement_change_request"
    assert result["change_proposal"]["technical_requirement_changes"][0]["operation"] == "add"

    ambiguous_review = _review()
    ambiguous_review["technical_requirements"].append(
        {
            "requirement_id": "techreq_salt_second",
            "type": "salt_spray",
            "content": "盐雾试验144小时。",
            "need_human_review": False,
        }
    )
    ambiguous = chat_about_standardization(ambiguous_review, "删除盐雾试验这条要求", use_llm=False)
    assert ambiguous["intent"]["status"] == "need_clarification"
    assert ambiguous["change_proposal"]["status"] == "needs_input"
    assert len(ambiguous_review["technical_requirements"]) == 2


def _assert_llm_receives_ids_and_returns_controlled_action() -> None:
    seen: dict = {}

    def fake_completion(request: dict) -> dict:
        seen.update(request)
        requirement = request["review"]["technical_requirements"][0]
        assert requirement["requirement_id"]
        return {
            "reply": "已形成盐雾试验修改方案。",
            "intent": {
                "type": "technical_requirement_change_request",
                "target_fields": ["technical_requirements"],
                "status": "proposal_ready",
            },
            "suggested_actions": [{
                "type": "propose_technical_requirement_update",
                "requirement_id": requirement["requirement_id"],
                "requirement_type": "salt_spray",
                "content": "盐雾试验96小时。",
            }],
        }

    payload = StandardizationChatLLMEngine(completion_fn=fake_completion).chat(
        _review(),
        "把原来的盐雾时长调整一下",
        {"intent": {"type": "technical_requirement_change_request"}},
    )
    action = payload["suggested_actions"][0]
    assert seen["review"]["technical_requirements"][0]["requirement_id"] == action["requirement_id"]
    assert action["metadata"]["technical_requirement_action"] is True
    assert action["apply_policy"] == "manual_confirm_required"


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
        "technical_requirements": [{
            "requirement_id": "techreq_salt_first",
            "type": "salt_spray",
            "content": "盐雾试验72小时。",
            "need_human_review": False,
            "source": ["human_confirmed"],
        }],
        "standard_selection": {},
        "standardization_results": [],
        "derived_parameters": {},
        "manual_confirmations": {},
    }


def _param(value: object, unit: str | None = None) -> dict:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["human_confirmed"]}


if __name__ == "__main__":
    main()
