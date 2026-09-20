from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copy import deepcopy

from ai_design_review.generation_contract import COMPRESSION_GENERATION_EXPORT_FIELDS, COMPRESSION_GENERATION_INPUT_FIELDS
from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.generation_schemas import GenerationParameterPackageV1, GenerationParameterPackageV2
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.standardization_chat_agent import chat_about_standardization
from ai_design_review.surface_roughness import ensure_surface_roughness_parameter
from ai_design_review.technical_requirements import build_technical_requirements_text, ensure_technical_requirements_title


def main() -> None:
    _assert_ready_review_builds_frozen_package()
    _assert_protocol_conversions()
    _assert_new_confirmed_values_do_not_change_old_snapshot()
    _assert_mean_diameter_source_precedence()
    _assert_missing_values_receive_pending_defaults()
    _assert_handedness_has_no_default()
    _assert_optional_material_export_and_warning()
    _assert_pending_field_is_omitted_but_package_exports()
    _assert_technical_requirements_require_explicit_confirmation()
    _assert_technical_requirements_text_formatting()
    _assert_surface_roughness_is_optional_and_exported_as_note()
    _assert_legacy_surface_roughness_is_promoted()
    _assert_duplicate_technical_requirements_block_release()
    _assert_load_points_require_explicit_confirmation_and_export_cleanly()
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
    GenerationParameterPackageV2.model_validate(package)
    older_v2_package = deepcopy(package)
    older_v2_package.pop("solidworks_preview")
    GenerationParameterPackageV2.model_validate(older_v2_package)
    assert package["schema_version"] == "spring_generation_parameters/v2"
    assert package["package_type"] == "confirmed_compression_spring_generation_input"
    spring_parameters = package["generation_parameters"]["spring_parameters"]
    assert tuple(spring_parameters) == COMPRESSION_GENERATION_EXPORT_FIELDS
    assert spring_parameters["material"]["value"] == "SUS304 raw"
    assert spring_parameters["material"]["unit"] is None
    assert spring_parameters["material"]["tolerance_upper"] is None
    assert spring_parameters["material"]["tolerance_lower"] is None
    assert spring_parameters["wire_diameter"]["value"] == 2
    assert spring_parameters["mean_diameter"]["value"] == 18
    assert spring_parameters["total_coils"]["value"] == 12
    assert spring_parameters["total_coils"]["unit"] is None
    assert spring_parameters["handedness"]["value"] == "right"
    assert spring_parameters["end_grinding"]["value"] == 1
    assert spring_parameters["end_coils_closed"]["value"] == 1
    preview = package["solidworks_preview"]["modelParameters"]
    assert preview["有效圈数n"] == 10
    assert preview["是否磨平"] == 1
    assert preview == build_solidworks_command("1000000001", package, review)["models"][0]["modelParameters"]
    for excluded in ("outer_diameter", "inner_diameter", "solid_height", "spring_rate", "end_type"):
        assert excluded not in spring_parameters
    assert package["generation_parameters"]["load_points"] == [
        {
            "label": "F1",
            "height": {"value": 25.0, "unit": "mm"},
            "force": {"value": 100.0, "unit": "N", "tolerance_upper": None, "tolerance_lower": None},
            "confirmation_source": "human_confirmed",
        }
    ]
    assert "torque_points" not in package["generation_parameters"]
    assert package["generation_parameters"]["technical_requirements"][0]["content"] == "镀锌"
    assert package["generation_parameters"]["technical_requirements_text"] == "技术要求\n1.表面处理：镀锌"
    assert package["derived_parameters"]["mean_diameter"]["value"] == 18
    assert package["derived_parameters"]["spring_index"]["value"] == 9
    assert package["derived_parameters"]["slenderness_ratio"]["value"] == round(40 / 18, 4)


def _assert_protocol_conversions() -> None:
    review = _ready_review()
    review["spring_parameters"]["handedness"]["value"] = "左旋"
    review["spring_parameters"]["end_grinding"]["value"] = "两端不磨削"
    review["spring_parameters"]["end_type"]["value"] = "两端不并紧"
    package = build_generation_parameter_package(review)
    parameters = package["generation_parameters"]["spring_parameters"]
    assert parameters["handedness"]["value"] == "left"
    assert parameters["end_grinding"]["value"] == 0
    assert parameters["end_coils_closed"]["value"] == 0
    assert package["solidworks_preview"]["modelParameters"]["是否磨平"] == 0
    assert build_solidworks_command("1000000002", package, review)["models"][0]["modelParameters"]["是否磨平"] == 0

    review["spring_parameters"]["handedness"]["value"] = "right"
    review["spring_parameters"]["end_grinding"]["value"] = 1
    review["spring_parameters"]["end_coils_closed"] = _param(1)
    del review["spring_parameters"]["end_type"]
    parameters = build_generation_parameter_package(review)["generation_parameters"]["spring_parameters"]
    assert parameters["handedness"]["value"] == "right"
    assert parameters["end_grinding"]["value"] == 1
    assert parameters["end_coils_closed"]["value"] == 1


def _assert_new_confirmed_values_do_not_change_old_snapshot() -> None:
    review = _ready_review()
    old_package = build_generation_parameter_package(review)
    old_model = old_package["solidworks_preview"]["modelParameters"]

    review["spring_parameters"]["active_coils"]["value"] = 9
    review["spring_parameters"]["end_grinding"]["value"] = "两端不磨削"
    new_package = build_generation_parameter_package(review)
    new_model = new_package["solidworks_preview"]["modelParameters"]

    assert (old_model["有效圈数n"], old_model["是否磨平"]) == (10, 1)
    assert (new_model["有效圈数n"], new_model["是否磨平"]) == (9, 0)
    assert build_solidworks_command("1000000003", old_package, _ready_review())["models"][0]["modelParameters"] == old_model
    assert build_solidworks_command("1000000004", new_package, review)["models"][0]["modelParameters"] == new_model


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
    assert set(package["generation_parameters"]["spring_parameters"]) == {"material", "handedness"}


def _assert_handedness_has_no_default() -> None:
    review = _ready_review()
    del review["spring_parameters"]["handedness"]
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_input"
    assert any(item["field"] == "handedness" for item in readiness["missing_fields"])
    assert "handedness" not in readiness["defaulted_fields"]


def _assert_optional_material_export_and_warning() -> None:
    missing = _ready_review()
    del missing["spring_parameters"]["material"]
    readiness = assess_generation_readiness(missing)
    assert readiness["status"] == "ready_with_warnings", readiness
    assert any(item["field"] == "material" for item in readiness["warnings"])
    assert "material" not in build_generation_parameter_package(missing)["generation_parameters"]["spring_parameters"]

    pending = _ready_review()
    pending["spring_parameters"]["material"]["need_human_review"] = True
    readiness = assess_generation_readiness(pending)
    assert readiness["status"] == "ready_with_warnings", readiness
    assert any(item["field"] == "material" for item in readiness["warnings"])
    assert "material" not in build_generation_parameter_package(pending)["generation_parameters"]["spring_parameters"]

    invalid = _ready_review()
    invalid["spring_parameters"]["material"]["value"] = 65
    readiness = assess_generation_readiness(invalid)
    assert readiness["status"] == "ready_with_warnings", readiness
    assert any(item["field"] == "material" for item in readiness["warnings"])

    package = build_generation_parameter_package(_ready_review())
    legacy = deepcopy(package)
    legacy["schema_version"] = "spring_generation_parameters/v1"
    legacy["export_policy"]["parameter_filter"] = "frozen_compression_inputs_v1_human_confirmed_only"
    legacy["generation_parameters"]["spring_parameters"].pop("material")
    legacy.pop("solidworks_preview")
    GenerationParameterPackageV1.model_validate(legacy)


def _assert_pending_field_is_omitted_but_package_exports() -> None:
    review = _ready_review()
    review["spring_parameters"]["mean_diameter"]["need_human_review"] = True
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_confirmation"
    assert any(item["field"] == "mean_diameter" for item in readiness["pending_fields"])
    package = build_generation_parameter_package(review)
    assert "mean_diameter" not in package["generation_parameters"]["spring_parameters"]
    assert package["generation_parameters"]["spring_parameters"]["wire_diameter"]["value"] == 2
    assert package["solidworks_preview"]["modelParameters"]["中径"] is None
    assert package["derived_parameters"]["mean_diameter"]["value"] == 18

    pending_grinding = _ready_review()
    pending_grinding["spring_parameters"]["end_grinding"]["need_human_review"] = True
    pending_package = build_generation_parameter_package(pending_grinding)
    assert "end_grinding" not in pending_package["generation_parameters"]["spring_parameters"]
    assert pending_package["solidworks_preview"]["modelParameters"]["是否磨平"] is None


def _assert_technical_requirements_require_explicit_confirmation() -> None:
    review = _ready_review()
    review["technical_requirements"] = [
        {
            "requirement_id": "techreq_confirmed",
            "type": "surface",
            "content": "表面镀锌。",
            "need_human_review": False,
            "source": ["human"],
        },
        {
            "requirement_id": "techreq_pending",
            "type": "hardness",
            "content": "硬度为 HRC 45～50。",
            "need_human_review": True,
        },
        {
            "requirement_id": "techreq_legacy_without_state",
            "type": "other",
            "content": "未显式确认的历史要求。",
        },
        {
            "requirement_id": "techreq_empty",
            "type": "other",
            "content": "  ",
            "need_human_review": False,
        },
    ]

    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_confirmation", readiness
    pending = [
        item for item in readiness["pending_fields"]
        if item["field"].startswith("technical_requirements.")
    ]
    assert {item.get("requirement_id") for item in pending} == {
        "techreq_pending", "techreq_legacy_without_state", "techreq_empty",
    }
    assert any("内容为空" in item["reason"] for item in pending)

    requirements = build_generation_parameter_package(review)["generation_parameters"]["technical_requirements"]
    assert requirements == [
        {
            "type": "surface",
            "content": "表面镀锌。",
            "confirmation_source": "human_confirmed",
        }
    ]
    assert "requirement_id" not in requirements[0]
    assert "source" not in requirements[0]
    assert build_generation_parameter_package(review)["generation_parameters"]["technical_requirements_text"] == (
        "技术要求\n1.表面处理：表面镀锌。"
    )


def _assert_technical_requirements_text_formatting() -> None:
    requirements = [
        {"type": "surface", "content": "表面处理：表面镀锌。"},
        {"type": "hardness", "content": "硬度 HRC 45～50。"},
        {"type": "heat_treatment", "content": "淬火并回火。"},
        {"type": "salt_spray", "content": "盐雾试验: 96小时。"},
        {"type": "environmental", "content": "符合 RoHS。"},
        {"type": "lifetime", "content": "寿命不少于10万次。"},
        {"type": "process", "content": "去除毛刺。\n不得有锐边。"},
        {"type": "unexpected_type", "content": "包装时防潮。"},
        {"type": "other", "content": "  "},
    ]
    assert build_technical_requirements_text(requirements) == "\n".join((
        "技术要求",
        "1.表面处理：表面镀锌。",
        "2.硬度要求：硬度 HRC 45～50。",
        "3.热处理：淬火并回火。",
        "4.盐雾试验：96小时。",
        "5.环保要求：符合 RoHS。",
        "6.寿命要求：寿命不少于10万次。",
        "7.工艺要求：去除毛刺。；不得有锐边。",
        "8.其他要求：包装时防潮。",
    ))
    assert build_technical_requirements_text([]) == ""
    assert ensure_technical_requirements_title("") == ""
    assert ensure_technical_requirements_title("技术要求\n") == ""
    assert ensure_technical_requirements_title("1.其他要求：端圈并紧磨平。") == "技术要求\n1.其他要求：端圈并紧磨平。"
    assert ensure_technical_requirements_title("技术要求\n1.其他要求：端圈并紧磨平。") == "技术要求\n1.其他要求：端圈并紧磨平。"


def _assert_surface_roughness_is_optional_and_exported_as_note() -> None:
    pending = _ready_review()
    pending["spring_parameters"]["surface_roughness_ra"] = {
        "value": 12.5,
        "unit": "μm",
        "surface_location": "两端面",
        "need_human_review": True,
    }
    assert assess_generation_readiness(pending)["status"] == "ready"
    pending_package = build_generation_parameter_package(pending)
    assert "surface_roughness_ra" not in pending_package["generation_parameters"]["spring_parameters"]
    assert all(item["type"] != "surface_roughness" for item in pending_package["generation_parameters"]["technical_requirements"])

    confirmed = deepcopy(pending)
    confirmed["spring_parameters"]["surface_roughness_ra"]["need_human_review"] = False
    confirmed_package = build_generation_parameter_package(confirmed)
    GenerationParameterPackageV2.model_validate(confirmed_package)
    requirements = confirmed_package["generation_parameters"]["technical_requirements"]
    assert requirements[0] == {
        "type": "surface_roughness",
        "content": "两端面粗糙度 Ra 12.5μm",
        "confirmation_source": "human_confirmed",
    }
    assert confirmed_package["generation_parameters"]["technical_requirements_text"].startswith(
        "技术要求\n1.两端面粗糙度 Ra 12.5μm\n2.表面处理：镀锌"
    )
    assert "surface_roughness_ra" not in confirmed_package["generation_parameters"]["spring_parameters"]


def _assert_legacy_surface_roughness_is_promoted() -> None:
    review = _ready_review()
    review["spring_template"] = {
        "spring_type": "compression_spring",
        "label": "压缩弹簧",
        "fields": [{"key": "active_coils", "label": "有效圈数", "unit": "turns"}, {"key": "end_coils", "label": "端圈数", "unit": "turns"}],
    }
    review["technical_requirements"].insert(0, {
        "type": "surface_roughness",
        "content": "两端面粗糙度 Ra 12.5μm",
        "need_human_review": False,
        "source": ["qwen_vision"],
    })
    assert ensure_surface_roughness_parameter(review) is True
    roughness = review["spring_parameters"]["surface_roughness_ra"]
    assert roughness["value"] == 12.5
    assert roughness["surface_location"] == "两端面"
    assert roughness["need_human_review"] is False
    assert not any(item["type"] == "surface_roughness" for item in review["technical_requirements"])
    keys = [item["key"] for item in review["spring_template"]["fields"]]
    assert keys == ["active_coils", "surface_roughness_ra", "end_coils"]
    package = build_generation_parameter_package(review)
    assert package["generation_parameters"]["technical_requirements"][0]["content"] == "两端面粗糙度 Ra 12.5μm"


def _assert_duplicate_technical_requirements_block_release() -> None:
    review = _ready_review()
    review["technical_requirements"].append(
        {
            "requirement_id": "techreq_duplicate",
            "type": "surface",
            "content": "  镀锌  ",
            "need_human_review": False,
        }
    )
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_confirmation", readiness
    duplicate = next(
        item for item in readiness["pending_fields"]
        if item.get("requirement_id") == "techreq_duplicate"
    )
    assert "重复" in duplicate["reason"]


def _assert_load_points_require_explicit_confirmation_and_export_cleanly() -> None:
    review = _ready_review()
    review["spring_parameters"]["load_points"] = [
        {"label": "F1", "height": 25, "force": 100, "need_human_review": False},
        {"label": " F2 ", "height": 30, "force": 150, "load_tolerance_upper": 6, "load_tolerance_lower": -6, "need_human_review": True},
        {"label": "f1", "height": 35, "force": 200, "need_human_review": False},
        {"label": "F4", "height": None, "force": 250, "need_human_review": False},
    ]
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_confirmation", readiness
    pending = [item for item in readiness["pending_fields"] if item["field"].startswith("load_points.")]
    assert len(pending) == 3
    assert any("重复" in item["reason"] for item in pending)
    assert any("完整且有效" in item["reason"] for item in pending)
    assert any("尚未人工确认" in item["reason"] for item in pending)

    exported = build_generation_parameter_package(review)["generation_parameters"]["load_points"]
    assert exported == [
        {
            "label": "F1",
            "height": {"value": 25.0, "unit": "mm"},
            "force": {"value": 100.0, "unit": "N", "tolerance_upper": None, "tolerance_lower": None},
            "confirmation_source": "human_confirmed",
        },
    ]


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
    assert tuple(package["generation_parameters"]["spring_parameters"]) == COMPRESSION_GENERATION_EXPORT_FIELDS

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

    stale_formula = _ready_review()
    stale_formula["spring_parameters"]["solid_height"] = {
        "value": 24,
        "unit": "mm",
        "source": ["formula_calculation", "human_edited", "human_confirmed"],
        "need_human_review": False,
        "formula_recommendation_stale": True,
    }
    readiness = assess_generation_readiness(stale_formula)
    assert readiness["status"] == "ready_with_warnings"
    assert not readiness["pending_fields"]
    assert any(item["field"] == "solid_height" for item in readiness["warnings"])

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
            "material": _param(
                "SUS304 raw",
                standard_value="SUS304",
                tolerance_upper=1,
                tolerance_lower=-1,
            ),
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
