from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ai_design_review.surface_terms import load_surface_terms, normalize_surface_requirement
from ai_design_review.workflow import DrawingReviewWorkflow
from ai_design_review.io_utils import read_json
from import_surface_terms import read_surface_terms_from_xlsx


DESKTOP_XLSX = Path(r"C:\Users\29580\Desktop\工作\图纸识别\不同弹簧特例\表面处理_术语对照标准表.xlsx")


def main() -> None:
    _assert_config_terms()
    _assert_normalization_cases()
    _assert_workflow_surface_payload()
    _assert_excel_import_if_available()
    print("surface terms test passed")


def _assert_config_terms() -> None:
    config = load_surface_terms()
    assert len(config["terms"]) == 91
    assert "电镀-镀彩锌" in config["terms"]
    assert config["aliases"]["镀锌五彩"] == "电镀-镀彩锌"


def _assert_normalization_cases() -> None:
    black = normalize_surface_requirement("发黑")
    assert black["content"] == "发黑"
    assert black["standard_content"] == "发黑"
    assert black["normalization_status"] in {"matched", "alias_matched"}

    phosphate = normalize_surface_requirement("磷化")
    assert phosphate["content"] == "磷化"
    assert phosphate["standard_content"] == "磷化"

    colorful_zinc = normalize_surface_requirement("表面处理：镀锌五彩")
    assert colorful_zinc["content"] == "电镀-镀彩锌"
    assert colorful_zinc["raw_content"] == "镀锌五彩"
    assert colorful_zinc["standard_content"] == "电镀-镀彩锌"
    assert colorful_zinc["normalization_status"] == "alias_matched"
    assert colorful_zinc["need_human_review"] is False

    unknown = normalize_surface_requirement("客户特殊蓝白处理")
    assert unknown["content"] == "客户特殊蓝白处理"
    assert unknown["standard_content"] == ""
    assert unknown["normalization_status"] == "unmatched"
    assert unknown["need_human_review"] is True


def _assert_excel_import_if_available() -> None:
    if not DESKTOP_XLSX.exists():
        return
    terms = read_surface_terms_from_xlsx(DESKTOP_XLSX, "术语对照标准")
    assert len(terms) == 91
    assert "电镀-镀彩锌" in terms


def _assert_workflow_surface_payload() -> None:
    rules = read_json("config/factory_rules.json")
    review = DrawingReviewWorkflow(rules).run(
        None,
        [
            {"field": "surface_requirement", "value": "客户特殊蓝白处理", "source": "test", "confidence": 0.9},
        ],
    )
    surface = next(item for item in review["technical_requirements"] if item["type"] == "surface")
    assert surface["content"] == "客户特殊蓝白处理"
    assert surface["standard_content"] == ""
    assert surface["normalization_status"] == "unmatched"
    assert surface["need_human_review"] is True


if __name__ == "__main__":
    main()
