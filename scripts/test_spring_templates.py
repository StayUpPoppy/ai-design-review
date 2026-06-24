from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.io_utils import read_json
from ai_design_review.spring_templates import classify_spring_type, required_field_keys
from ai_design_review.workflow import DrawingReviewWorkflow


def main() -> None:
    _assert_classifier_cases()
    _assert_workflow_templates()
    print("spring template test passed")


def _assert_classifier_cases() -> None:
    cases = [
        (
            "compression_spring",
            {"path": r"C:\drawings\YD4765020143 UQD04阳接头弹簧(1).pdf", "kind": "pdf"},
            [
                {"field": "document_text_1", "feature_type": "note", "value": "H1压缩到21.15mm/F1=16N H2压缩到9.668mm/F2=35N"},
            ],
        ),
        (
            "retaining_ring",
            {"path": r"C:\drawings\YD4799140278 UQD04内卡簧(1).pdf", "kind": "pdf"},
            [
                {"field": "document_text_1", "feature_type": "note", "value": "缺口 内卡簧 A-A 剖面"},
            ],
        ),
        (
            "torsion_spring",
            {"path": r"C:\drawings\wechat.jpg", "kind": "image"},
            [
                {"field": "document_text_1", "feature_type": "note", "value": "扭簧 臂长20 工作角35° R3.5 旋向左旋"},
            ],
        ),
        (
            "extension_spring",
            {"path": r"C:\drawings\拉伸弹簧.jpg", "kind": "image"},
            [
                {"field": "document_text_1", "feature_type": "note", "value": "圆柱螺旋拉伸弹簧 线径4 中径19 圈数9.5 钩环"},
            ],
        ),
    ]
    for expected, file_info, candidates in cases:
        result = classify_spring_type(candidates, file_info)
        assert result["spring_type"] == expected, result


def _assert_workflow_templates() -> None:
    rules = read_json("config/factory_rules.json")
    result = DrawingReviewWorkflow(rules).run(
        None,
        [
            {"field": "material", "value": "SUS304", "source": "test", "confidence": 0.95},
            {"field": "document_text_1", "feature_type": "note", "value": "UQD04内卡簧 缺口 A-A 剖面", "source": "test", "confidence": 0.9},
            {"field": "inner_diameter", "value": 10.47, "unit": "mm", "source": "test", "confidence": 0.9},
            {"field": "surface_requirement", "value": "镀锌五彩", "source": "test", "confidence": 0.9},
        ],
    )
    assert result["drawing_summary"]["spring_type"] == "retaining_ring"
    assert result["spring_template"]["label"] == "卡簧/挡圈"
    assert "inner_diameter" in required_field_keys("retaining_ring")
    assert "outer_diameter" in result["spring_parameters"]
    assert any(item["type"] == "surface" and item["content"] == "镀锌五彩" for item in result["technical_requirements"])


if __name__ == "__main__":
    main()
