from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.parameter_impact import assess_parameter_change_impact  # noqa: E402


def main() -> None:
    _assert_mean_diameter_changes_protocol_geometry_without_mutation()
    _assert_outer_diameter_does_not_override_frozen_mean()
    _assert_blocking_and_warning_changes()
    _assert_pending_field_becomes_confirmed_for_preview()
    _assert_tolerance_can_change_solid_height_risk()
    _assert_batch_is_simulated_as_one_change_set()
    _assert_non_protocol_field_does_not_change_package()
    _assert_technical_requirement_changes_update_generation_package()
    print("parameter impact preview tests passed")


def _assert_mean_diameter_changes_protocol_geometry_without_mutation() -> None:
    review = _ready_review()
    original = deepcopy(review)
    preview = assess_parameter_change_impact(review, [_patch("mean_diameter", 25, "mm")])
    assert review == original
    assert preview["status"] == "ready", preview
    assert preview["direct_changes"][0]["before"] == 18
    assert preview["direct_changes"][0]["after"] == 25
    derived = {item["field"]: item for item in preview["derived_changes"]}
    assert derived["outer_diameter"]["before"] == 20
    assert derived["outer_diameter"]["after"] == 27
    assert derived["inner_diameter"]["before"] == 16
    assert derived["inner_diameter"]["after"] == 23
    assert derived["spring_index"]["before"] == 9
    assert derived["spring_index"]["after"] == 12.5
    assert derived["spring_index"]["label"] == "旋绕比"
    assert derived["slenderness_ratio"]["label"] == "细长比"
    assert {item["field"] for item in preview["derived_changes"]} >= {
        "outer_diameter", "mean_diameter", "inner_diameter", "spring_index", "slenderness_ratio",
    }
    assert preview["generation_readiness"]["parameter_package_changed"] is True
    assert preview["generation_readiness"]["changed_frozen_fields"] == ["mean_diameter"]
    assert preview["workflow_effects"]["new_generation_required"] is True
    assert preview["baseline_state"]["spring_parameters"]["mean_diameter"]["value"] == 18


def _assert_outer_diameter_does_not_override_frozen_mean() -> None:
    preview = assess_parameter_change_impact(_ready_review(), [_patch("outer_diameter", 22, "mm")])
    assert preview["status"] == "ready", preview
    assert preview["generation_readiness"]["parameter_package_changed"] is False
    assert preview["generation_readiness"]["changed_frozen_fields"] == []
    assert preview["derived_changes"] == []
    assert "不会改变当前 SolidWorks 建模参数" in preview["summary"]


def _assert_blocking_and_warning_changes() -> None:
    blocked = assess_parameter_change_impact(_ready_review(), [_patch("active_coils", 13)])
    assert blocked["status"] == "blocked"
    assert any("有效圈数不能大于总圈数" in item["message"] for item in blocked["risk_delta"]["introduced"])

    invalid_mean = assess_parameter_change_impact(_ready_review(), [_patch("mean_diameter", 2, "mm")])
    assert invalid_mean["status"] == "blocked"
    assert any("中径必须大于线径" in item["message"] for item in invalid_mean["risk_delta"]["introduced"])

    warning = assess_parameter_change_impact(_ready_review(), [_patch("free_length", 100, "mm")])
    assert warning["status"] == "warning"
    assert any("细长比" in item["message"] for item in warning["risk_delta"]["introduced"])


def _assert_pending_field_becomes_confirmed_for_preview() -> None:
    review = _ready_review()
    review["spring_parameters"]["mean_diameter"]["need_human_review"] = True
    preview = assess_parameter_change_impact(review, [_patch("mean_diameter", 18, "mm")])
    readiness = preview["generation_readiness"]
    assert readiness["before_status"] == "needs_confirmation"
    assert readiness["after_status"] == "ready_with_warnings"
    assert readiness["parameter_package_changed"] is True


def _assert_tolerance_can_change_solid_height_risk() -> None:
    action = {
        "type": "propose_tolerance_patch",
        "target_field": "wire_diameter",
        "suggested_tolerance_upper": 1,
        "suggested_tolerance_lower": -1,
        "unit": "mm",
    }
    preview = assess_parameter_change_impact(_ready_review(), [action])
    assert preview["status"] == "blocked", preview
    derived = {item["field"]: item for item in preview["derived_changes"]}
    assert derived["solid_height"]["before"] == 24
    assert derived["solid_height"]["after"] == 36
    assert preview["direct_changes"][0]["change_type"] == "tolerance"
    assert preview["generation_readiness"]["parameter_package_changed"] is True


def _assert_batch_is_simulated_as_one_change_set() -> None:
    review = _ready_review()
    active_only = assess_parameter_change_impact(review, [_patch("active_coils", 11)])
    total_only = assess_parameter_change_impact(review, [_patch("total_coils", 10)])
    combined = assess_parameter_change_impact(
        review,
        [_patch("active_coils", 11), _patch("total_coils", 10)],
    )
    assert active_only["status"] == "ready"
    assert total_only["status"] == "ready"
    assert combined["status"] == "blocked"
    assert len(combined["direct_changes"]) == 2

    individually_blocked = assess_parameter_change_impact(review, [_patch("active_coils", 13)])
    valid_as_batch = assess_parameter_change_impact(
        review,
        [_patch("active_coils", 13), _patch("total_coils", 15)],
    )
    assert individually_blocked["status"] == "blocked"
    assert valid_as_batch["status"] == "ready"


def _assert_non_protocol_field_does_not_change_package() -> None:
    preview = assess_parameter_change_impact(_ready_review(), [_patch("spring_rate", 1.25, "N/mm")])
    assert preview["generation_readiness"]["parameter_package_changed"] is False
    assert preview["workflow_effects"]["new_generation_required"] is False


def _assert_technical_requirement_changes_update_generation_package() -> None:
    review = _ready_review()
    review["technical_requirements"][0]["requirement_id"] = "techreq_surface"
    original = deepcopy(review)

    updated = assess_parameter_change_impact(
        review,
        [
            {
                "type": "propose_technical_requirement_update",
                "requirement_id": "techreq_surface",
                "requirement_type": "surface",
                "content": "表面镀锌，盐雾试验 96 小时。",
            }
        ],
    )
    assert review == original
    assert updated["status"] == "ready", updated
    assert updated["generation_readiness"]["parameter_package_changed"] is True
    assert updated["generation_readiness"]["technical_requirements_changed"] is True
    assert updated["generation_readiness"]["changed_frozen_fields"] == []
    assert updated["workflow_effects"]["new_generation_required"] is True
    assert updated["workflow_effects"]["standardization_recalculation_required"] is False
    assert updated["direct_changes"][0]["change_type"] == "technical_requirement_update"
    assert updated["direct_changes"][0]["after"]["content"].endswith("96 小时。")

    added = assess_parameter_change_impact(
        review,
        [
            {
                "type": "propose_technical_requirement_add",
                "requirement_id": "techreq_hardness",
                "requirement_type": "hardness",
                "content": "硬度为 HRC 45～50。",
            }
        ],
    )
    assert added["generation_readiness"]["technical_requirements_changed"] is True
    assert added["workflow_effects"]["new_generation_required"] is True

    deleted = assess_parameter_change_impact(
        review,
        [
            {
                "type": "propose_technical_requirement_delete",
                "requirement_id": "techreq_surface",
            }
        ],
    )
    assert deleted["generation_readiness"]["technical_requirements_changed"] is True
    assert deleted["workflow_effects"]["new_generation_required"] is True
    assert deleted["direct_changes"][0]["after"] is None


def _patch(field: str, value: object, unit: str | None = None) -> dict:
    return {
        "type": "propose_parameter_patch",
        "target_field": field,
        "proposed_value": value,
        "unit": unit,
    }


def _ready_review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_parameters": {
            "wire_diameter": _param(2, "mm"),
            "mean_diameter": _param(18, "mm"),
            "outer_diameter": _param(20, "mm"),
            "free_length": _param(40, "mm"),
            "total_coils": _param(12, "turns"),
            "active_coils": _param(10, "turns"),
            "handedness": _param("right"),
            "end_grinding": _param("两端磨削"),
            "end_coils_closed": _param(1),
            "spring_rate": _param(1, "N/mm"),
            "load_points": [
                {
                    "label": "F1",
                    "height": 30,
                    "height_unit": "mm",
                    "force": 100,
                    "force_unit": "N",
                    "need_human_review": False,
                }
            ],
        },
        "technical_requirements": [
            {"type": "surface", "content": "表面镀锌。", "need_human_review": False},
        ],
        "standard_selection": {
            "selected_standard": "GB/T 1239.2-2009",
            "status": "applicable",
            "human_confirmed": True,
        },
        "standardization_results": [
            {
                "target_field": "free_length",
                "status": "human_confirmed",
                "need_human_review": False,
                "basis": "已按当前参数确认。",
            }
        ],
        "derived_parameters_stale": False,
    }


def _param(value: object, unit: str | None = None) -> dict:
    return {"value": value, "unit": unit, "need_human_review": False}


if __name__ == "__main__":
    main()
