from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ai_design_review.io_utils import read_json
from ai_design_review.material_terms import load_material_terms, normalize_material
from ai_design_review.workflow import DrawingReviewWorkflow
from import_material_terms import read_material_terms_from_xlsx


DESKTOP_XLSX = Path(r"C:\Users\29580\Desktop\工作\图纸识别\不同弹簧特例\材质标准表.xlsx")


def main() -> None:
    _assert_config_terms()
    _assert_normalization_cases()
    _assert_workflow_material_payload()
    _assert_excel_import_if_available()
    print("material terms test passed")


def _assert_config_terms() -> None:
    config = load_material_terms()
    assert len(config["terms"]) == 134
    for term in ("65Mn", "SUS304", "SUS316L", "17-7PH", "Inconel X750", "ASTM A228", "70#"):
        assert term in config["terms"]


def _assert_normalization_cases() -> None:
    cases = {
        "sus304": "SUS304",
        "SUS 304": "SUS304",
        "sus-316l": "SUS316L",
        "17 7 ph": "17-7PH",
        "inconelx750": "Inconel X750",
        "70": "70#",
    }
    for raw, expected in cases.items():
        result = normalize_material(raw)
        assert result["value"] == expected
        assert result["standard_value"] == expected
        assert result["normalization_status"] == "matched"
        assert result["normalization_source"] == "material_terms"

    unknown = normalize_material("客户特殊材料A")
    assert unknown["value"] == "客户特殊材料A"
    assert unknown["standard_value"] == ""
    assert unknown["normalization_status"] == "unmatched"

    ambiguous = normalize_material("A B", {"terms": ["AB", "A-B"]})
    assert ambiguous["value"] == "A B"
    assert ambiguous["standard_value"] == ""
    assert ambiguous["normalization_status"] == "unmatched"


def _assert_workflow_material_payload() -> None:
    rules = read_json("config/factory_rules.json")
    review = DrawingReviewWorkflow(rules).run(
        None,
        [
            {"field": "material", "value": "sus-316l", "source": "test", "confidence": 0.9},
        ],
    )
    material = review["spring_parameters"]["material"]
    assert material["value"] == "SUS316L"
    assert material["raw_value"] == "sus-316l"
    assert material["standard_value"] == "SUS316L"
    assert material["normalization_status"] == "matched"
    assert review["drawing_summary"]["material"] == "SUS316L"


def _assert_excel_import_if_available() -> None:
    if not DESKTOP_XLSX.exists():
        return
    terms = read_material_terms_from_xlsx(DESKTOP_XLSX, "Sheet1")
    assert len(terms) == 134
    assert "SUS304" in terms
    assert "70#" in terms


if __name__ == "__main__":
    main()
