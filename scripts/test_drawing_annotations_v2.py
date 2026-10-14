"""Coordinate, evidence and legacy-upgrade regression cases; no cloud calls."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.drawing_annotations import (  # noqa: E402
    ALGORITHM_VERSION, _rect, build_annotations, failed_annotation_upgrade,
    locate_fields, merge_annotation_upgrade, ocr_blocks,
)


def block(text, x=.2, y=.3, page=1, width=.05, height=.015):
    return {"text": text, "page": page, "source": "ocr", "position": {"x": x, "y": y, "width": width, "height": height}}


def review(**values):
    return {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {
        field: {"value": value, "source": ["qwen_vision"], "evidence": str(value), "page": 1}
        for field, value in values.items()}}


def fields(document):
    return {a["field"]: a for a in document}


def main():
    center = {"x": 100, "y": 200, "width": 20, "height": 40, "coordinate_type": "pixel"}
    assert _rect(center, 1000, 1000, center=True) == {"x": .09, "y": .18, "width": .02, "height": .04}
    polygon = {**center, "polygon": [[50, 60], [80, 60], [80, 90], [50, 90]]}
    assert _rect(polygon, 1000, 1000, center=True)["x"] == .05
    assert _rect({**center, "origin": "top_left"}, 1000, 1000, center=True)["x"] == .1
    assert _rect({**center, "polygon": [[float("nan"), 10], [20, 10], [20, 20]]}, 1000, 1000) is None
    assert _rect({"x": 1.005, "y": .5, "width": .001, "height": .01, "coordinate_type": "normalized"}, 1000, 1000) is None

    r = review(free_length=19, outer_diameter=27)
    found = fields(locate_fields(r, [], [block("19"), block("27", x=.6), block("19", page=2)]))
    assert found["free_length"]["locations"][0]["anchor"]["x"] == .225
    assert found["outer_diameter"]["locations"]
    assert not fields(locate_fields(r, [], [block("19"), block("19", x=.8)]))["free_length"]["locations"]

    r = review(total_coils=9, active_coils=7, wire_diameter=2, material="65Mn弹簧钢丝", end_grinding="两端磨削")
    blocks = [block("总圈数", x=.4, y=.7), block("9", x=.53, y=.7), block("9", x=.8, y=.2),
              block("有效圈数", x=.4, y=.73), block("7", x=.53, y=.73),
              block("线径", x=.4, y=.76), block("02", x=.53, y=.76), block("02", x=.25, y=.4),
              block("材质65Mn", x=.8, y=.85), block("闭口端形，端面研磨", x=.4, y=.65)]
    found = fields(locate_fields(r, [], blocks))
    assert len(found["total_coils"]["locations"]) == 1
    assert found["total_coils"]["locations"][0]["anchor"]["x"] == .555
    assert found["active_coils"]["locations"]
    assert len(found["wire_diameter"]["locations"]) == 1
    assert found["material"]["locations"]
    assert found["end_grinding"]["locations"]
    assert not fields(locate_fields(r, [], [block("两端不磨削")]))["end_grinding"]["locations"]
    assert not fields(locate_fields(r, [], [block("产品不可有油污、研磨粉尘。表面毛刺小于线径的10%")]))["end_grinding"]["locations"], "grinding dust is not an end treatment"
    assert not fields(locate_fields(review(end_type="两端并紧"), [], [block("两端不并紧")]))["end_type"]["locations"]
    assert not fields(locate_fields(review(wire_diameter=2), [], [block("D2 28"), block("H0 80")]))["wire_diameter"]["locations"]

    r = review(wire_diameter=2)
    r["spring_parameters"]["wire_diameter"]["evidence"] = "图形φ2；线径φ2"
    found = fields(locate_fields(r, [], [block("线径φ2"), block("线径φ2", x=.6)]))
    assert len(found["wire_diameter"]["locations"]) == 2
    r["spring_parameters"]["mean_diameter"] = {"value": 26, "source": ["formula_calculation"]}
    assert not fields(locate_fields(r, [], [block("26")]))["mean_diameter"]["locations"]

    # Candidate coordinates are useful only after their source frame and text
    # have been established, never by comparing arbitrary pixel values.
    b = block("19")
    b.update(input_size=[1000, 1000], raw_position={"x": 225, "y": 307.5, "width": 50, "height": 15})
    c = {"field": "free_length", "value": 19, "source": "ocr", "evidence": "19", "page": 1, "position": b["raw_position"]}
    found = fields(locate_fields(review(free_length=19), [c], [b, block("19", x=.8)]))
    assert len(found["free_length"]["locations"]) == 1

    from PIL import Image, ImageOps
    for orientation in range(1, 9):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inputs").mkdir()
            (root / "pages").mkdir()
            exif = Image.Exif()
            exif[274] = orientation
            Image.new("RGB", (200, 100), "white").save(root / "pages" / "source.jpg", exif=exif)
            original_bytes = (root / "pages" / "source.jpg").read_bytes()
            def recognize(paths, _diagnostics):
                with Image.open(paths[0]) as image:
                    assert image.getexif().get(274, 1) == 1
                    assert image.size == ((100, 200) if orientation >= 5 else (200, 100))
                    width, height = image.size
                return [{"page": 1, "image_path": str(paths[0]), "texts": [{"text": "wire diameter 2", "position": {
                    "x": width * .25, "y": height * .35, "width": width * .1, "height": height * .1}}]}]
            with patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=recognize) as mock:
                first = build_annotations(r, root, lambda p: str(p))
                second = build_annotations(r, root, lambda p: str(p))
                assert mock.call_count == 1, "normalized local OCR must be cached"
            assert first == second
            assert len(first["annotations"]) == 15
            anchor = fields(first["annotations"])["wire_diameter"]["locations"][0]["anchor"]
            assert abs(anchor["x"] - .25) < 1e-9 and abs(anchor["y"] - .35) < 1e-9
            assert original_bytes == (root / "pages" / "source.jpg").read_bytes()
            if orientation != 1:
                legacy = {"raw_pages": [{"page": 1, "image_path": str(root / "pages" / "source.jpg"), "texts": [{"text": "2", "position": center}]}]}
                assert ocr_blocks({"legacy": legacy}, first["pages"]) == [], "unknown EXIF coordinate frames must not be guessed"
            with Image.open(root / "pages" / "source.jpg") as image:
                assert ImageOps.exif_transpose(image).size == (first["pages"][0]["width"], first["pages"][0]["height"])

    rebuilt = {"algorithm_version": ALGORITHM_VERSION, "source_document_id": "same", "annotation_revision": 1,
               "annotations": locate_fields(review(surface_roughness_ra=12.5), [], [block("Ra 12.5"), block("Ra 12.5", x=.7)]), "warnings": []}
    current = copy.deepcopy(rebuilt)
    current.pop("algorithm_version")
    current["annotation_revision"] = 8
    manual = fields(current["annotations"])["surface_roughness_ra"]["locations"][0]
    manual.update(source="manual", location_id="legacy-manual", bubble={"x": .1, "y": .2})
    expected = copy.deepcopy(manual)
    merged = merge_annotation_upgrade(current, rebuilt)
    assert merged["annotation_revision"] == 9
    locations = fields(merged["annotations"])["surface_roughness_ra"]["locations"]
    assert locations[0] == expected and len(locations) == 2, "keep manual left and rebuilt automatic right"
    assert merge_annotation_upgrade(merged, rebuilt) == merged
    assert locations[1]["location_id"] == fields(current["annotations"])["surface_roughness_ra"]["locations"][1]["location_id"], "automatic location IDs remain usable after upgrade"
    unknown = copy.deepcopy(current)
    fields(unknown["annotations"])["surface_roughness_ra"]["locations"][0]["source"] = "unknown"
    assert "来源不明" in fields(merge_annotation_upgrade(unknown, rebuilt)["annotations"])["surface_roughness_ra"]["reason"]
    failed = failed_annotation_upgrade(current)
    assert failed["annotations"] == current["annotations"] and failed["algorithm_version"] == ALGORITHM_VERSION
    print("annotation v2 regressions passed: centers, polygons, EXIF 1–8, cached OCR, evidence rows, duplicate values, negation and protected upgrades")


if __name__ == "__main__":
    main()
