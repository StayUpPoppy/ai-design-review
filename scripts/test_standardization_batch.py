from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardization_batch import build_standardization_batch  # noqa: E402


def main() -> None:
    review = {
        "spring_parameters": {
            "free_length": _param(45, "mm", upper=1, lower=-1),
            "outer_diameter": _param(26, "mm"),
            "spring_rate": _param(5, "N/mm"),
            "load_points": [
                {
                    "label": "F1",
                    "force": 100,
                    "force_unit": "N",
                    "load_tolerance_upper": 10,
                    "load_tolerance_lower": -10,
                    "need_human_review": False,
                }
            ],
        },
        "standardization_results": [
            _result("free_length", "FREE", 45, 0.6, -0.6, "mm"),
            _result("load_points.F1.force", "LOAD", 100, 6, -6, "N"),
            {
                "target_field": "spring_rate",
                "rule_id": "STIFF",
                "status": "need_context",
                "basis": "缺少有效圈数。",
                "metadata": {"missing_fields": ["active_coils"]},
            },
            _result("outer_diameter", "DIA-A", 26, 0.4, -0.4, "mm"),
            _result("outer_diameter", "DIA-B", 26, 0.3, -0.3, "mm"),
            {
                "target_field": "straightness",
                "rule_id": "STRAIGHT",
                "status": "not_applicable",
                "basis": "当前细长比不适用。",
                "metadata": {},
            },
        ],
    }

    batch = build_standardization_batch(review, review_revision=12)
    assert batch["status"] == "ready"
    assert batch["review_revision"] == 12
    assert batch["applicable_count"] == 2
    assert {item["label"] for item in batch["items"]} == {"自由长度", "载荷测试点 F1 力值"}
    assert batch["items"][0]["change_types"] == ["tolerance"]
    assert batch["items"][1]["after"]["tolerance_upper"] == 6
    skipped_reasons = " ".join(item["reason"] for item in batch["skipped_items"])
    assert "有效圈数" in skipped_reasons
    assert "多个标准化方案" in skipped_reasons
    assert "适用范围" in skipped_reasons
    assert batch["skipped_count"] == 4
    assert len(batch["baseline_fingerprint"]) == 64
    assert len(batch["result_fingerprint"]) == 64

    unchanged = {
        "spring_parameters": {"free_length": _param(45, "mm", upper=0.6, lower=-0.6)},
        "standardization_results": [_result("free_length", "FREE", 45, 0.6, -0.6, "mm")],
    }
    no_changes = build_standardization_batch(unchanged)
    assert no_changes["status"] == "no_changes"
    assert no_changes["items"] == []

    print("standardization batch tests passed")


def _param(value: object, unit: str, *, upper: object = None, lower: object = None) -> dict:
    return {
        "value": value,
        "unit": unit,
        "tolerance_upper": upper,
        "tolerance_lower": lower,
        "need_human_review": False,
    }


def _result(target: str, rule_id: str, value: object, upper: object, lower: object, unit: str) -> dict:
    return {
        "target_field": target,
        "rule_id": rule_id,
        "standard_no": "GB/T 1239.2-2009",
        "suggested_value": value,
        "suggested_tolerance_upper": upper,
        "suggested_tolerance_lower": lower,
        "unit": unit,
        "status": "suggested",
        "basis": "标准依据",
        "metadata": {},
    }


if __name__ == "__main__":
    main()
