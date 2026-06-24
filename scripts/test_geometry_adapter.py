from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.geometry_adapter import GeometryEngine
from ai_design_review.io_utils import project_path, read_json
from ai_design_review.workflow import DrawingReviewWorkflow


def main() -> None:
    image_path = _make_synthetic_drawing()
    payload = GeometryEngine().extract_with_raw(image_path)
    evidence = payload["dimension_evidence"]
    kinds = {item["kind"] for item in evidence}

    assert evidence, "geometry evidence should not be empty"
    assert "drawing_content_bbox" in kinds, kinds
    assert "title_block_candidate" in kinds, kinds
    assert _has_any_line(kinds), kinds
    assert all(candidate["feature_type"] == "dimension_evidence" for candidate in payload["candidates"])

    rules = read_json(project_path("config", "factory_rules.json"))
    review = DrawingReviewWorkflow(rules).run(str(image_path), payload["candidates"])
    assert review["dimension_evidence"], "workflow should preserve geometry evidence"
    assert review["dimension_evidence"][0]["source"] == "geometry"
    print("geometry adapter test passed")


def _make_synthetic_drawing() -> Path:
    out_dir = project_path("outputs", "tests", "geometry")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "synthetic_geometry.png"

    image = Image.new("RGB", (900, 620), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((45, 35, 855, 585), outline="black", width=3)
    draw.rectangle((440, 490, 845, 575), outline="black", width=2)
    draw.line((160, 210, 500, 210), fill="black", width=3)
    draw.line((160, 198, 160, 222), fill="black", width=3)
    draw.line((500, 198, 500, 222), fill="black", width=3)
    draw.line((330, 160, 330, 325), fill="black", width=3)
    draw.ellipse((600, 165, 735, 300), outline="black", width=4)
    draw.polygon([(510, 210), (530, 199), (530, 221)], outline="black", fill="black")
    draw.text((300, 180), "48", fill="black")
    draw.text((610, 315), "R5.25", fill="black")
    draw.text((462, 510), "表面处理: 镀锌五彩", fill="black")
    image.save(path)
    return path


def _has_any_line(kinds: set[str]) -> bool:
    return bool({"raster_line", "horizontal_line_candidate", "vertical_line_candidate"} & kinds)


if __name__ == "__main__":
    main()
