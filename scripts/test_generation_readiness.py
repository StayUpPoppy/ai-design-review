from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.generation_readiness import assess_generation_readiness, build_generation_parameter_package
from ai_design_review.standardization_chat_agent import chat_about_standardization


def main() -> None:
    _assert_ready_review_builds_confirmed_package()
    _assert_missing_core_field_blocks_package()
    _assert_pending_field_blocks_package()
    _assert_agent_answers_generation_readiness()
    print("generation readiness test passed")


def _assert_ready_review_builds_confirmed_package() -> None:
    review = _ready_review()
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "ready"
    package = build_generation_parameter_package(review)
    assert package["package_type"] == "confirmed_compression_spring_generation_input"
    assert package["generation_parameters"]["spring_parameters"]["material"]["value"] == "SUS304"
    assert package["generation_parameters"]["spring_parameters"]["outer_diameter"]["value"] == 20
    assert package["generation_parameters"]["load_points"][0]["label"] == "F1"


def _assert_missing_core_field_blocks_package() -> None:
    review = _ready_review()
    review["spring_parameters"]["active_coils"]["value"] = None
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_input"
    assert any(item["field"] == "active_coils" for item in readiness["missing_fields"])
    try:
        build_generation_parameter_package(review)
    except ValueError:
        pass
    else:
        raise AssertionError("missing core fields must block generation parameter package export")


def _assert_pending_field_blocks_package() -> None:
    review = _ready_review()
    review["spring_parameters"]["outer_diameter"]["need_human_review"] = True
    readiness = assess_generation_readiness(review)
    assert readiness["status"] == "needs_confirmation"
    assert any(item["field"] == "outer_diameter" for item in readiness["pending_fields"])


def _assert_agent_answers_generation_readiness() -> None:
    review = _ready_review()
    payload = chat_about_standardization(review, "现在可以重新生图吗", use_llm=True)
    assert payload["intent"]["type"] == "generation_readiness"
    assert payload["intent"]["status"] == "ready"
    assert payload["generation_readiness"]["status"] == "ready"
    assert "llm_chat" not in payload


def _ready_review() -> dict:
    def param(value, unit: str | None = None, **extra) -> dict:
        return {"value": value, "unit": unit, "need_human_review": False, **extra}

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
            "material": param("SUS304 raw", standard_value="SUS304"),
            "wire_diameter": param(2, "mm"),
            "outer_diameter": param(20, "mm"),
            "free_length": param(40, "mm"),
            "total_coils": param(12, "turns"),
            "active_coils": param(10, "turns"),
            "handedness": param("右旋"),
            "end_grinding": param("两端磨平"),
            "load_points": [{"label": "F1", "height": 25, "force": 100, "need_human_review": False}],
        },
        "technical_requirements": [{"type": "surface", "content": "镀锌", "standard_content": "公司内部镀锌", "need_human_review": False}],
        "derived_parameters": {"mean_diameter": {"value": 18, "unit": "mm"}},
        "standardization_results": [],
    }


if __name__ == "__main__":
    main()
