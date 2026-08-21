from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.generation_readiness import build_generation_parameter_package  # noqa: E402
from ai_design_review.load_points import ensure_load_point_ids, load_point_confirmation_key  # noqa: E402
from ai_design_review.parameter_change_proposal import (  # noqa: E402
    apply_parameter_change_proposal,
    build_parameter_change_proposal,
)
from ai_design_review.standardization_chat_agent import chat_about_standardization  # noqa: E402
from ai_design_review.standardization_chat_llm import StandardizationChatLLMEngine  # noqa: E402


def main() -> None:
    _assert_legacy_ids_are_stable_and_confirmation_migrates()
    _assert_add_update_delete_are_atomic_and_exported()
    _assert_duplicate_and_missing_values_are_not_applyable()
    _assert_local_chat_builds_controlled_load_point_actions()
    _assert_llm_receives_load_point_ids_and_returns_controlled_action()
    print("load point proposal tests passed")


def _assert_legacy_ids_are_stable_and_confirmation_migrates() -> None:
    first = _review()
    first["spring_parameters"]["load_points"][0].pop("load_point_id", None)
    first["manual_confirmations"] = {"load_points_0": {"confirmed": True, "value": 100}}
    second = deepcopy(first)
    assert ensure_load_point_ids(first) is True
    assert ensure_load_point_ids(second) is True
    first_id = first["spring_parameters"]["load_points"][0]["load_point_id"]
    assert first_id == second["spring_parameters"]["load_points"][0]["load_point_id"]
    assert first["manual_confirmations"][load_point_confirmation_key(first_id)]["confirmed"] is True


def _assert_add_update_delete_are_atomic_and_exported() -> None:
    review = _review()
    added = build_parameter_change_proposal(
        review,
        [{
            "type": "propose_load_point_add",
            "label": "F2",
            "height": 30,
            "force": 150,
            "load_tolerance_upper": 6,
            "load_tolerance_lower": -6,
        }],
        user_goal="新增 F2",
    )
    assert added and added["status"] in {"ready", "warning"}, added
    assert added["load_point_changes"][0]["operation"] == "add"
    assert len(review["spring_parameters"]["load_points"]) == 1
    applied, result = apply_parameter_change_proposal(review, added["proposal_id"], version=added["version"])
    assert len(applied["spring_parameters"]["load_points"]) == 2
    point = next(item for item in applied["spring_parameters"]["load_points"] if item["label"] == "F2")
    assert point["need_human_review"] is False
    assert result["load_point_changes"][0]["after"]["force"] == 150
    package = build_generation_parameter_package(applied)
    exported = next(item for item in package["generation_parameters"]["load_points"] if item["label"] == "F2")
    assert exported == {
        "label": "F2",
        "height": {"value": 30, "unit": "mm"},
        "force": {"value": 150, "unit": "N", "tolerance_upper": 6, "tolerance_lower": -6},
        "confirmation_source": "human_confirmed",
    }
    assert "load_point_id" not in exported

    update = build_parameter_change_proposal(
        applied,
        [{"type": "propose_load_point_update", "load_point_id": point["load_point_id"], "height": 28, "force": 130}],
        user_goal="调整 F2",
    )
    updated, _ = apply_parameter_change_proposal(applied, update["proposal_id"], version=update["version"])
    changed = next(item for item in updated["spring_parameters"]["load_points"] if item["load_point_id"] == point["load_point_id"])
    assert changed["height"] == 28 and changed["force"] == 130 and changed["need_human_review"] is False

    delete = build_parameter_change_proposal(
        updated,
        [{"type": "propose_load_point_delete", "load_point_id": point["load_point_id"]}],
        user_goal="删除 F2",
    )
    deleted, _ = apply_parameter_change_proposal(updated, delete["proposal_id"], version=delete["version"])
    assert all(item["load_point_id"] != point["load_point_id"] for item in deleted["spring_parameters"]["load_points"])


def _assert_duplicate_and_missing_values_are_not_applyable() -> None:
    review = _review()
    duplicate = build_parameter_change_proposal(
        review,
        [{"type": "propose_load_point_add", "label": " f1 ", "height": 30, "force": 150}],
        user_goal="重复新增 F1",
    )
    assert duplicate["status"] == "blocked"
    assert any(item.get("code") == "load_point_label_duplicate" for item in duplicate["blocking_issues"])

    incomplete = build_parameter_change_proposal(
        review,
        [{"type": "propose_load_point_add", "label": "F2", "height": 30}],
        user_goal="新增不完整 F2",
    )
    assert incomplete["status"] == "needs_input"
    assert incomplete["clarifying_questions"]


def _assert_local_chat_builds_controlled_load_point_actions() -> None:
    class MustNotRun:
        def chat(self, *_: object, **__: object) -> dict:
            raise AssertionError("clear load-point command must not call LLM")

    review = _review()
    added = chat_about_standardization(
        review,
        "新增载荷测试点 F2，高度30mm，力值150N，公差±6N",
        use_llm=True,
        llm_engine=MustNotRun(),
    )
    assert added["intent"]["type"] == "load_point_change_request"
    proposal = added["change_proposal"]
    assert proposal["status"] in {"ready", "warning"}, proposal
    change = proposal["load_point_changes"][0]
    assert change["after"]["label"] == "F2"
    assert change["after"]["load_tolerance_upper"] == 6
    applied, _ = apply_parameter_change_proposal(review, proposal["proposal_id"], version=proposal["version"])
    f2 = next(item for item in applied["spring_parameters"]["load_points"] if item["label"] == "F2")

    update = chat_about_standardization(applied, "把载荷测试点 F2 高度改为28mm，力值改为130N", use_llm=False)
    assert update["change_proposal"]["load_point_changes"][0]["operation"] == "update"
    updated, _ = apply_parameter_change_proposal(
        applied,
        update["change_proposal"]["proposal_id"],
        version=update["change_proposal"]["version"],
    )
    delete = chat_about_standardization(updated, "删除载荷测试点 F2", use_llm=False)
    assert delete["change_proposal"]["load_point_changes"][0]["load_point_id"] == f2["load_point_id"]


def _assert_llm_receives_load_point_ids_and_returns_controlled_action() -> None:
    seen: dict = {}

    def fake_completion(request: dict) -> dict:
        seen.update(request)
        point = request["review"]["spring_parameters"]["load_points"][0]
        assert point["load_point_id"]
        return {
            "reply": "已形成 F1 修改方案。",
            "intent": {"type": "load_point_change_request", "target_fields": ["load_points"], "status": "proposal_ready"},
            "suggested_actions": [{
                "type": "propose_load_point_update",
                "load_point_id": point["load_point_id"],
                "height": 24,
                "force": 110,
            }],
        }

    payload = StandardizationChatLLMEngine(completion_fn=fake_completion).chat(
        _review(),
        "把 F1 的测试条件调整一下",
        {"intent": {"type": "load_point_change_request"}},
    )
    action = payload["suggested_actions"][0]
    assert seen["review"]["spring_parameters"]["load_points"][0]["load_point_id"] == action["load_point_id"]
    assert action["metadata"]["load_point_action"] is True
    assert action["apply_policy"] == "manual_confirm_required"


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_parameters": {
            "wire_diameter": _param(3, "mm"),
            "mean_diameter": _param(23, "mm"),
            "outer_diameter": _param(26, "mm"),
            "inner_diameter": _param(20, "mm"),
            "free_length": _param(45, "mm"),
            "total_coils": _param(10, "turns"),
            "active_coils": _param(8, "turns"),
            "handedness": _param("right"),
            "end_grinding": _param(1),
            "end_coils_closed": _param(1),
            "load_points": [{"label": "F1", "height": 25, "force": 100, "need_human_review": False, "source": ["human_confirmed"]}],
        },
        "technical_requirements": [],
        "standard_selection": {},
        "standardization_results": [],
        "derived_parameters": {},
        "manual_confirmations": {},
    }


def _param(value: object, unit: str | None = None) -> dict:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["human_confirmed"]}


if __name__ == "__main__":
    main()
