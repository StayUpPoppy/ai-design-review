from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.generation_contract import COMPRESSION_GENERATION_INPUT_FIELDS
from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.standardization_chat_agent import chat_about_standardization


def main() -> None:
    _assert_ready_review_builds_frozen_package()
    _assert_protocol_conversions()
    _assert_mean_diameter_source_precedence()
    _assert_missing_values_receive_pending_defaults()
    _assert_handedness_has_no_default()
    _assert_pending_field_is_omitted_but_package_exports()
    _assert_contract_validation()
    _assert_optional_standardization_is_warning()
    _assert_warning_blocked_and_not_applicable_states()
    _assert_agent_answers_generation_readiness()
    print("generation readiness test passed")


def _assert_ready_review_builds_frozen_package() -> None:
    review = _ready_review()
    review["derived_parameters"].update({
        "spring_index": {"value": 8, "unit": None},
        "slenderness_ratio": {"value": 3, "unit": None},
    })
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "ready", readiness
    assert readiness["confirmed_core_count"] == 8
    assert readiness["core_field_count"] == 8
    package = build_generation_parameter_package(review)
    assert package["schema_version"] == "spring_generation_parameters/v1"
    assert package["package_type"] == "confirmed_compression_spring_generation_input"
    spring_parameters = package["generation_parameters"]["spring_parameters"]
    assert tuple(spring_parameters) == COMPRESSION_GENERATION_INPUT_FIELDS
    assert spring_parameters["wire_diameter"]["value"] == 2
    assert spring_parameters["mean_diameter"]["value"] == 18
    assert spring_parameters["total_coils"]["value"] == 12
    assert spring_parameters["total_coils"]["unit"] is None
    assert spring_parameters["handedness"]["value"] == "right"
    assert spring_parameters["end_grinding"]["value"] == 1
    assert spring_parameters["end_coils_closed"]["value"] == 1
    for excluded in ("material", "outer_diameter", "inner_diameter", "solid_height", "spring_rate", "end_type"):
        assert excluded not in spring_parameters
    assert "load_points" not in package["generation_parameters"]
    assert "torque_points" not in package["generation_parameters"]
    assert package["generation_parameters"]["technical_requirements"][0]["content"] == "镀锌"
    assert package["derived_parameters"]["mean_diameter"]["value"] == 18
    assert package["derived_parameters"]["spring_index"]["value"] == 9
    assert package["derived_parameters"]["slenderness_ratio"]["value"] == round(40 / 18, 4)


def _assert_protocol_conversions() -> None:
    review = _ready_review()
    review["spring_parameters"]["handedness"]["value"] = "左旋"
    review["spring_parameters"]["end_grinding"]["value"] = "两端不磨削"
    review["spring_parameters"]["end_type"]["value"] = "两端不并紧"
    parameters = build_generation_parameter_package(review)["generation_parameters"]["spring_parameters"]
    assert parameters["handedness"]["value"] == "left"
    assert parameters["end_grinding"]["value"] == 0
    assert parameters["end_coils_closed"]["value"] == 0

    review["spring_parameters"]["handedness"]["value"] = "right"
    review["spring_parameters"]["end_grinding"]["value"] = 1
    review["spring_parameters"]["end_coils_closed"] = _param(1)
    del review["spring_parameters"]["end_type"]
    parameters = build_generation_parameter_package(review)["generation_parameters"]["spring_parameters"]
    assert parameters["handedness"]["value"] == "right"
    assert parameters["end_grinding"]["value"] == 1
    assert parameters["end_coils_closed"]["value"] == 1


def _assert_mean_diameter_source_precedence() -> None:
    direct = _ready_review()
    direct["spring_parameters"]["mean_diameter"]["value"] = 17
    parameters = build_generation_parameter_package(direct)["generation_parameters"]["spring_parameters"]
    assert parameters["mean_diameter"]["value"] == 17

    from_outer = _ready_review()
    del from_outer["spring_parameters"]["mean_diameter"]
    parameters = build_generation_parameter_package(from_outer)["generation_parameters"]["spring_parameters"]
    assert parameters["mean_diameter"]["value"] == 18

    from_inner = _ready_review()
    del from_inner["spring_parameters"]["mean_diameter"]
    del from_inner["spring_parameters"]["outer_diameter"]
    parameters = build_generation_parameter_package(from_inner)["generation_parameters"]["spring_parameters"]
    assert parameters["mean_diameter"]["value"] == 18

    pending_source = _ready_review()
    del pending_source["spring_parameters"]["mean_diameter"]
    pending_source["spring_parameters"]["outer_diameter"]["need_human_review"] = True
    readiness = assess_generation_readiness(pending_source)
    assert readiness["status"] == "needs_confirmation"
    assert any(item["field"] == "mean_diameter" for item in readiness["pending_fields"])

    pending_direct = _ready_review()
    pending_direct["spring_parameters"]["mean_diameter"]["need_human_review"] = True
    readiness = assess_generation_readiness(pending_direct)
    assert readiness["status"] == "needs_confirmation"
    assert any(item["field"] == "mean_diameter" for item in readiness["pending_fields"])
    parameters = build_generation_parameter_package(pending_direct)["generation_parameters"]["spring_parameters"]
    assert "mean_diameter" not in parameters


def _assert_missing_values_receive_pending_defaults() -> None:
    review = _ready_review()
    for field in ("wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "total_coils", "active_coils", "end_grinding"):
        del review["spring_parameters"][field]
    del review["spring_parameters"]["end_type"]
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_confirmation", readiness
    assert set(readiness["defaulted_fields"]) == {
        "wire_diameter", "mean_diameter", "free_length", "total_coils",
        "active_coils", "end_grinding", "end_coils_closed",
    }
    assert review["spring_parameters"]["wire_diameter"]["value"] == 3
    assert review["spring_parameters"]["mean_diameter"]["value"] == 23
    assert review["spring_parameters"]["free_length"]["value"] == 45
    assert review["spring_parameters"]["total_coils"]["value"] == 10
    assert review["spring_parameters"]["active_coils"]["value"] == 8
    assert review["spring_parameters"]["end_grinding"]["value"] == "两端磨削"
    assert review["spring_parameters"]["end_type"]["value"] == "两端并紧"
    assert all(review["spring_parameters"][field]["need_human_review"] for field in (
        "wire_diameter", "mean_diameter", "free_length", "total_coils", "active_coils", "end_grinding", "end_type"
    ))
    package = build_generation_parameter_package(review)
    assert set(package["generation_parameters"]["spring_parameters"]) == {"handedness"}


def _assert_handedness_has_no_default() -> None:
    review = _ready_review()
    del review["spring_parameters"]["handedness"]
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_input"
    assert any(item["field"] == "handedness" for item in readiness["missing_fields"])
    assert "handedness" not in readiness["defaulted_fields"]


def _assert_pending_field_is_omitted_but_package_exports() -> None:
    review = _ready_review()
    review["spring_parameters"]["mean_diameter"]["need_human_review"] = True
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_confirmation"
    assert any(item["field"] == "mean_diameter" for item in readiness["pending_fields"])
    package = build_generation_parameter_package(review)
    assert "mean_diameter" not in package["generation_parameters"]["spring_parameters"]
    assert package["generation_parameters"]["spring_parameters"]["wire_diameter"]["value"] == 2
    assert package["derived_parameters"]["mean_diameter"]["value"] == 18


def _assert_contract_validation() -> None:
    cases = [
        ("wire_diameter", -1),
        ("mean_diameter", 2),
        ("total_coils", 10.5),
        ("active_coils", 13),
        ("handedness", "clockwise"),
        ("end_grinding", 2),
    ]
    for field, value in cases:
        review = _ready_review()
        review["spring_parameters"][field]["value"] = value
        readiness = assess_generation_readiness(review)
        assert readiness["status"] == "blocked", (field, readiness)

    review = _ready_review()
    review["spring_parameters"]["end_type"]["value"] = "unknown"
    assert assess_generation_readiness(review)["status"] == "blocked"


def _assert_optional_standardization_is_warning() -> None:
    direct = _ready_review()
    direct["standard_selection"] = {
        "selected_standard": None,
        "status": "not_started",
        "need_human_review": False,
        "human_confirmed": False,
    }
    readiness = assess_generation_readiness(direct)
    assert readiness["status"] == "ready_with_warnings", readiness
    assert not any(item["field"] == "standard_no" for item in readiness["missing_fields"])
    assert not any(item["field"] == "standard_no" for item in readiness["pending_fields"])
    assert any(item["field"] == "standard_no" for item in readiness["warnings"])
    package = build_generation_parameter_package(direct)
    assert package["standard_context"] == {
        "selected_standard": None,
        "selection_status": "not_started",
        "human_confirmed": False,
    }
    assert tuple(package["generation_parameters"]["spring_parameters"]) == COMPRESSION_GENERATION_INPUT_FIELDS

    pending_standard = _ready_review()
    pending_standard["standard_selection"]["need_human_review"] = True
    pending_standard["standard_selection"]["human_confirmed"] = False
    readiness = assess_generation_readiness(pending_standard)
    assert readiness["status"] == "ready_with_warnings"
    assert any(item["field"] == "standard_no" for item in readiness["warnings"])

    stale = _ready_review()
    stale["derived_parameters_stale"] = True
    stale["standardization_results"] = [
        {"target_field": "free_length", "status": "stale", "basis": "参数变化后建议已过期。", "need_human_review": True},
        {"target_field": "total_coils", "status": "need_context", "basis": "缺少标准化上下文。", "need_human_review": True},
        {"target_field": "surface", "status": "suggested", "basis": "标准化建议待处理。", "need_human_review": False},
    ]
    readiness = assess_generation_readiness(stale)
    assert readiness["status"] == "ready_with_warnings", readiness
    assert not readiness["pending_fields"]
    assert {item["field"] for item in readiness["warnings"]} >= {
        "standardization", "free_length", "total_coils", "surface",
    }

    technical_pending = _ready_review()
    technical_pending["technical_requirements"][0]["need_human_review"] = True
    readiness = assess_generation_readiness(technical_pending)
    assert readiness["status"] == "needs_confirmation"
    assert any(item["field"].startswith("technical_requirements.") for item in readiness["pending_fields"])


def _assert_warning_blocked_and_not_applicable_states() -> None:
    warned = _ready_review()
    warned["standardization_results"] = [
        {"target_field": "surface", "status": "not_applicable", "basis": "特殊表面处理需工程复核。"}
    ]
    assert assess_generation_readiness(warned)["status"] == "ready_with_warnings"

    blocked = _ready_review()
    blocked["spring_parameters"]["wire_diameter"]["value"] = 12
    assessment = assess_generation_readiness(blocked)
    assert assessment["status"] == "blocked"
    assert assessment["blocking_reasonableness"]

    extension = _ready_review()
    extension["drawing_summary"]["spring_type"] = "extension_spring"
    assert assess_generation_readiness(extension)["status"] == "not_applicable"


def _assert_agent_answers_generation_readiness() -> None:
    review = _ready_review()
    payload = chat_about_standardization(review, "现在可以重新生图吗", use_llm=True)
    assert payload["intent"]["type"] == "generation_readiness"
    assert payload["intent"]["status"] == "ready"
    assert payload["generation_readiness"]["status"] == "ready"
    assert "llm_chat" not in payload


def _param(value: object, unit: str | None = None, **extra: object) -> dict[str, object]:
    return {"value": value, "unit": unit, "need_human_review": False, **extra}


def _ready_review() -> dict:
    return {
        "drawing_summary": {
            "spring_type": "compression_spring",
            "spring_type_label": "压缩弹簧",
            "drawing_no": "YD-001",
            "drawing_name": "圆柱压缩弹簧",
        },
        "standard_selection": {
            "selected_standard": "GB/T 1239.2-2009",
            "status": "applicable",
            "need_human_review": False,
            "human_confirmed": True,
        },
        "spring_parameters": {
            "material": _param("SUS304 raw", standard_value="SUS304"),
            "wire_diameter": _param(2, "mm"),
            "outer_diameter": _param(20, "mm"),
            "inner_diameter": _param(16, "mm"),
            "mean_diameter": _param(18, "mm"),
            "free_length": _param(40, "mm"),
            "total_coils": _param(12, "turns"),
            "active_coils": _param(10, "turns"),
            "handedness": _param("右旋"),
            "end_type": _param("两端并紧"),
            "end_grinding": _param("两端磨平"),
            "solid_height": _param(24, "mm"),
            "spring_rate": _param(1.5, "N/mm"),
            "load_points": [{"label": "F1", "height": 25, "force": 100, "need_human_review": False}],
        },
        "technical_requirements": [{"type": "surface", "content": "镀锌", "standard_content": "公司内部镀锌", "need_human_review": False}],
        "derived_parameters": {"mean_diameter": {"value": 18, "unit": "mm"}},
        "standardization_results": [],
    }


if __name__ == "__main__":
    main()
