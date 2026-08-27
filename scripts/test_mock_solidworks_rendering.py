from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.mock_solidworks_worker import (  # noqa: E402
    _load_font,
    _load_point_lines,
    _technical_requirement_lines,
    render_mock_artifacts,
)


def main() -> None:
    requirements = [
        {
            "type": "other",
            "content": f"第 {index} 条技术要求：" + ("这是完整的中文标注内容，" * 12) + f"唯一结尾-{index}",
            "confirmation_source": "human_confirmed",
        }
        for index in range(1, 8)
    ]
    requirements[3]["content"] += "\n第二行内容也必须保留。"
    lines = _technical_requirement_lines(requirements, _load_font(20), max_width=1440)
    rendered_text = "\n".join(lines)
    assert "唯一结尾-1" in rendered_text
    assert "唯一结尾-7" in rendered_text
    assert "第二行内容也必须保留。" in rendered_text
    assert len(lines) > len(requirements)
    supplied_text = "1.表面处理：以汇总文本为准。\n2.工艺要求：不得截断。"
    supplied_lines = _technical_requirement_lines(
        requirements,
        _load_font(20),
        max_width=1440,
        technical_requirements_text=supplied_text,
    )
    assert "\n".join(supplied_lines) == supplied_text
    assert "唯一结尾" not in "\n".join(supplied_lines)
    load_points = [
        {
            "label": "F1",
            "height": {"value": 25, "unit": "mm"},
            "force": {"value": 100, "unit": "N", "tolerance_upper": 6, "tolerance_lower": -6},
            "confirmation_source": "human_confirmed",
        },
        {
            "label": "F2",
            "height": {"value": 30, "unit": "mm"},
            "force": {"value": 150, "unit": "N", "tolerance_upper": None, "tolerance_lower": None},
            "confirmation_source": "human_confirmed",
        },
    ]
    assert _load_point_lines(load_points) == [
        "F1: H=25 mm, F=100 N (+6/-6 N)",
        "F2: H=30 mm, F=150 N",
    ]

    job = _mock_job(requirements, load_points, supplied_text)
    artifacts = render_mock_artifacts(job)
    png = next(content for kind, _, _, content in artifacts if kind == "png")
    pdf = next(content for kind, _, _, content in artifacts if kind == "pdf")
    manifest_bytes = next(content for kind, _, _, content in artifacts if kind == "model_manifest")
    with Image.open(io.BytesIO(png)) as image:
        assert image.width == 1600
        assert image.height > 1000
    assert pdf.startswith(b"%PDF")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    assert manifest["technical_requirements"] == requirements
    assert manifest["technical_requirements_text"] == supplied_text
    assert manifest["load_points"] == load_points
    legacy_manifest_bytes = next(
        content for kind, _, _, content in render_mock_artifacts(_mock_job(requirements, load_points))
        if kind == "model_manifest"
    )
    legacy_manifest = json.loads(legacy_manifest_bytes.decode("utf-8"))
    assert legacy_manifest["technical_requirements_text"].startswith("1.其他要求：")
    assert "第二行内容也必须保留。" in legacy_manifest["technical_requirements_text"]
    legacy_defaulted_manifest_bytes = next(
        content for kind, _, _, content in render_mock_artifacts(_mock_job(requirements, load_points, ""))
        if kind == "model_manifest"
    )
    legacy_defaulted_manifest = json.loads(legacy_defaulted_manifest_bytes.decode("utf-8"))
    assert legacy_defaulted_manifest["technical_requirements_text"].startswith("1.其他要求：")
    print("mock SolidWorks technical requirement and load point rendering tests passed")


def _mock_job(
    requirements: list[dict[str, str]],
    load_points: list[dict[str, object]],
    technical_requirements_text: str | None = None,
) -> dict:
    generation_parameters = {
        "spring_parameters": {
            "wire_diameter": {"value": 3},
            "mean_diameter": {"value": 23},
            "free_length": {"value": 45},
            "total_coils": {"value": 10},
            "active_coils": {"value": 8},
            "handedness": {"value": "right"},
            "end_grinding": {"value": 1},
            "end_coils_closed": {"value": 1},
        },
        "load_points": load_points,
        "technical_requirements": requirements,
    }
    if technical_requirements_text is not None:
        generation_parameters["technical_requirements_text"] = technical_requirements_text
    return {
        "generation_id": "generation-techreq-render",
        "template_code": "mock/compression-spring",
        "template_version": "v3",
        "parameter_hash": "a" * 64,
        "parameter_package": {
            "source": {"drawing_no": "TECHREQ-001"},
            "generation_parameters": generation_parameters,
        },
    }


if __name__ == "__main__":
    main()
