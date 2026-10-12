from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.generation_schemas import GenerationParameterPackageV2
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.standardizers.design_checks import calculate_design_checks
from ai_design_review.material_catalog import validate_material_change


MATERIAL_NAMES = (
    "SWPB", "SWPA 琴钢丝", "SWC 硬钢线", "SUS304 不锈钢", "SUS316 不锈钢",
    "SUS631 不锈钢", "65Mn 弹簧钢", "60Si2Mn 硅锰钢", "50CrVA 铬钒钢",
    "Inconel X750 镍基合金钢", "70碳素钢", "55CrSi合金钢", "17-4PH不锈钢",
    "17-7PH不锈钢", "Inconel 718 镍基合金钢",
)
GRADE_NAMES = ("SWPB", "SWPA", "SWC", "SUS304", "SUS316", "SUS631", "65Mn", "60Si2Mn", "50CrVA",
               "Inconel X750", "70#", "55CrSi", "17-4PH", "17-7PH", "Inconel 718")


def param(value: object, unit: str | None = None, **extra: object) -> dict:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["human_confirmed"], **extra}


def ready_review(material: str = "SUS304 不锈钢") -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring", "spring_type_label": "压缩弹簧", "drawing_name": "材料输出回归"},
        "spring_parameters": {
            "material": param(material, raw_value="ХН70МВТЮБ ГОСТ 5632-72", standard_value="SUS304", material_id="4", material_catalog_version="test-company-v1", material_selection_source="manual"),
            "wire_diameter": param(2, "mm"), "outer_diameter": param(20, "mm"),
            "inner_diameter": param(16, "mm"), "mean_diameter": param(18, "mm"),
            "free_length": param(40, "mm"), "total_coils": param(12, "turns"),
            "active_coils": param(10, "turns"), "handedness": param("右旋"),
            "pitch": param(3.7, "mm"), "support_coils": param(1, "turns"),
            "end_type": param("两端并紧"), "end_grinding": param("两端磨削"),
            "solid_height": param(24, "mm"), "load_points": [],
        },
        "technical_requirements": [{"requirement_id": "process-one", "type": "other", "content": "端圈并紧磨平。", "need_human_review": False}],
        "standardization_results": [], "derived_parameters": {},
    }


def main() -> None:
    baseline_model = None
    for index, (name, grade) in enumerate(zip(MATERIAL_NAMES, GRADE_NAMES, strict=True)):
        review = ready_review(name)
        before = deepcopy(review)
        package = build_generation_parameter_package(review)
        GenerationParameterPackageV2.model_validate(package)
        material = package["generation_parameters"]["spring_parameters"]["material"]
        assert material["value"] == grade
        assert material["unit"] is None
        assert material["tolerance_upper"] is None and material["tolerance_lower"] is None
        assert not {"material_id", "material_catalog_version", "raw_value", "standard_value", "material_selection_source"}.intersection(material), material
        command = build_solidworks_command(str(1_000_000_001 + index), package, review)
        model = command["models"][0]
        assert model["extraProperties"]["技术要求"].startswith(f"1.材料：{grade}。")
        assert model["materialCode"] is None, "Catalog ids are not SolidWorks materialCode"
        assert model["extraProperties"]["技术要求"].startswith("1.")
        assert not model["extraProperties"]["技术要求"].startswith("技术要求\n")
        assert model["modelParameters"] == package["solidworks_preview"]["modelParameters"]
        if baseline_model is None:
            baseline_model = deepcopy(model["modelParameters"])
        else:
            assert model["modelParameters"] == baseline_model, "Material display names do not change geometric inputs"
        assert review["spring_parameters"]["material"] == before["spring_parameters"]["material"], "Export must not mutate current material or original evidence"
        for field, item in before["spring_parameters"].items():
            assert review["spring_parameters"][field] == item, f"Export must not change existing {field} values"
        pure = deepcopy(review)
        pure["spring_parameters"]["material"]["value"] = grade
        old_checks = calculate_design_checks(review["spring_parameters"], {})
        new_checks = calculate_design_checks(pure["spring_parameters"], {})
        assert all(old_checks["metrics"][key]["value"] is not None for key in ("theoretical_spring_rate", "solid_stress", "unit_mass"))
        assert {k: (v["value"], v["status"]) for k, v in old_checks["metrics"].items()} == {
            k: (v["value"], v["status"]) for k, v in new_checks["metrics"].items()
        }, (name, grade)
        assert build_generation_parameter_package(pure)["solidworks_preview"] == package["solidworks_preview"]

    legacy = ready_review()
    legacy["manual_confirmations"] = {"material": {"value": "SUS304 不锈钢", "confirmation_state": "human_confirmed"}}
    original = deepcopy(legacy)
    validate_material_change(legacy, original)
    assert legacy["spring_parameters"]["material"]["value"] == "SUS304 不锈钢"
    assert legacy["spring_parameters"]["material"]["need_human_review"] is False
    assert legacy["manual_confirmations"] == original["manual_confirmations"]

    for value, pending in [("SUS304 不锈钢", True), (None, False), ("", False)]:
        review = ready_review()
        review["spring_parameters"]["material"].update(value=value, need_human_review=pending)
        package = build_generation_parameter_package(review)
        assert "material" not in package["generation_parameters"]["spring_parameters"]
        command = build_solidworks_command("1000000020", package, review)
        assert "材料：" not in command["models"][0]["extraProperties"]["技术要求"]

    historical = ready_review("ХН70МВТЮБ ГОСТ 5632-72")
    frozen = build_generation_parameter_package(historical)
    snapshot = json.dumps(frozen, ensure_ascii=False, sort_keys=True)
    historical["spring_parameters"]["material"].update(value="Inconel X750 镍基合金钢", standard_value="Inconel X750", material_id="10")
    current = build_generation_parameter_package(historical)
    assert build_solidworks_command("1000000021", frozen, historical)["models"][0]["extraProperties"]["技术要求"].startswith("1.材料：ХН70МВТЮБ ГОСТ 5632-72。")
    assert build_solidworks_command("1000000022", current, historical)["models"][0]["extraProperties"]["技术要求"].startswith("1.材料：Inconel X750。")
    assert json.dumps(frozen, ensure_ascii=False, sort_keys=True) == snapshot
    frozen["solidworks_preview"]["extraProperties"]["技术要求"] = "1.材料：SUS304 不锈钢。"
    assert build_solidworks_command("1000000023", frozen, historical)["models"][0]["extraProperties"]["技术要求"] == "1.材料：SUS304 不锈钢。"
    print("PASS: all 15 pure grades and legacy names, unchanged calculations/confirmation, pending omission and frozen history")


if __name__ == "__main__":
    main()
