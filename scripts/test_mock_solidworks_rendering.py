from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.mock_solidworks_worker import (  # noqa: E402
    _load_font,
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

    job = _mock_job(requirements)
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
    print("mock SolidWorks technical requirement rendering tests passed")


def _mock_job(requirements: list[dict[str, str]]) -> dict:
    return {
        "generation_id": "generation-techreq-render",
        "template_code": "mock/compression-spring",
        "template_version": "v3",
        "parameter_hash": "a" * 64,
        "parameter_package": {
            "source": {"drawing_no": "TECHREQ-001"},
            "generation_parameters": {
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
                "technical_requirements": requirements,
            },
        },
    }


if __name__ == "__main__":
    main()
