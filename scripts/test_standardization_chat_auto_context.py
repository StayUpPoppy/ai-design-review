from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.api import _prepare_standardization_chat_context
from ai_design_review.standardization_chat_agent import chat_about_standardization


def main() -> None:
    review = _review_without_standardization()
    context = asyncio.run(
        _prepare_standardization_chat_context(review, "请根据标准化手册推荐完整标准化方案")
    )
    assert context["status"] == "refreshed"
    assert context["selected_standard"] == "GB/T 1239.2-2009"
    assert review["standardization_results"]
    assert review["derived_parameters"]
    assert review["spring_parameters"]["accuracy_grade"]["value"] == "2级"
    assert review["spring_parameters"]["accuracy_grade"]["default_source"] == "company_default"

    payload = chat_about_standardization(review, "请根据标准化手册推荐完整标准化方案")
    assert payload["intent"]["type"] == "missing_context"
    assert payload["intent"]["status"] == "need_input"
    assert payload["suggested_actions"][0]["target_field"] == "end_grinding"
    assert "还需要补充" in payload["reply"]

    review["standardization_results"][0]["status"] = "stale"
    context = asyncio.run(_prepare_standardization_chat_context(review, "外径改成22mm"))
    assert context["status"] == "refreshed"
    assert all(item.get("status") != "stale" for item in review["standardization_results"])
    print("standardization chat auto context test passed")


def _review_without_standardization() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_features": {
            "spring_family": {"value": "helical"},
            "spring_shape": {"value": "cylindrical"},
            "manufacturing_method": {"value": "unknown"},
            "wire_section": {"value": "round"},
            "pitch_type": {"value": "constant"},
        },
        "spring_parameters": {
            "wire_diameter": {"value": 1.5, "unit": "mm"},
            "outer_diameter": {"value": 25, "unit": "mm"},
            "free_length": {"value": 15, "unit": "mm"},
            "total_coils": {"value": 4, "unit": "turns"},
            "accuracy_grade": {"value": None},
            "load_points": [],
        },
        "standardization_results": [],
        "derived_parameters": {},
        "standard_selection": {},
    }


if __name__ == "__main__":
    main()
