from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.drawing_annotations import (  # noqa: E402
    AnnotationConflictError, FIELDS, apply_annotation_patch, build_annotations,
    locate_fields, ocr_blocks, page_sort_key, pdf_blocks,
)


def block(text, page=1, x=.2, y=.3, source="ocr"):
    return {"text": text, "page": page, "position": {"x": x, "y": y, "width": .1, "height": .02}, "source": source}


def review():
    return {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {
        "wire_diameter": {"value": 2, "source": ["qwen_vision"], "evidence": "wire diameter 2"},
        "free_length": {"value": 50, "source": ["qwen_vision"], "evidence": "free length 50"},
        "mean_diameter": {"value": 24, "source": ["formula_calculation"]},
        "accuracy_grade": {"value": "2级", "source": ["company_default"]},
        "surface_roughness_ra": {"value": 12.5, "source": ["qwen_vision"], "evidence": "Ra 12.5"},
    }}


def main():
    result = locate_fields(review(), [], [block("wire diameter 2"), block("free length 50", 2), block("Ra 12.5", x=.4), block("Ra 12.5", x=.7)])
    by_field = {a["field"]: a for a in result}
    assert len(result) == 15
    assert by_field["wire_diameter"]["number"] == 4
    assert by_field["free_length"]["locations"][0]["page"] == 2
    assert len(by_field["surface_roughness_ra"]["locations"]) == 2
    assert not by_field["mean_diameter"]["locations"]
    assert not by_field["accuracy_grade"]["locations"]
    assert by_field["material"]["status"] == "empty"
    identifiers = locate_fields(review(), [], [block("D2 28"), block("H0 80"), block("Ra12.5", x=.6)])
    assert not next(a for a in identifiers if a["field"] == "wire_diameter")["locations"], "dimension-label digits must not become wire values"
    assert next(a for a in identifiers if a["field"] == "surface_roughness_ra")["locations"], "OCR can join Ra and its value"

    repeated = locate_fields(review(), [], [block("50", x=.1), block("50", x=.8)])
    assert not next(a for a in repeated if a["field"] == "free_length")["locations"]
    bad = review()
    bad["spring_parameters"]["outer_diameter"] = {"value": 12.5, "source": ["qwen_vision"], "evidence": "outer diameter 12.5"}
    assert not next(a for a in locate_fields(bad, [], [block("Ra 12.5")]) if a["field"] == "outer_diameter")["locations"]
    conflicted = review()
    conflicted["spring_parameters"]["surface_roughness_ra"].update(value=None, roughness_conflict=True)
    candidates = [{"field": "surface_roughness_ra", "value": value, "source": ["qwen_vision"], "evidence": f"Ra {value}"} for value in (12.5, 6.3)]
    roughness = next(a for a in locate_fields(conflicted, candidates, [block("Ra 12.5"), block("Ra 6.3", x=.5)]) if a["field"] == "surface_roughness_ra")
    assert not roughness["locations"]
    assert "不同候选" in roughness["reason"]
    edited = review()
    edited["spring_parameters"]["free_length"].update(value=70, source=["qwen_vision", "human_edited"])
    original = {"field": "free_length", "value": 50, "evidence": "free length 50", "source": "qwen_vision"}
    assert next(a for a in locate_fields(edited, [original], [block("free length 50")]) if a["field"] == "free_length")["original_value"] == 50

    from PIL import Image
    import fitz
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "inputs").mkdir()
        (root / "pages").mkdir()
        for page in (1, 2, 10):
            Image.new("RGB", (1000, 800)).save(root / "pages" / f"page-{page}.png")
        doc = fitz.open()
        p = doc.new_page(width=500, height=400)
        p.insert_text((50, 60), "wire diameter 2")
        p.set_cropbox(fitz.Rect(20, 20, 400, 350))
        p.set_rotation(90)
        doc.save(root / "inputs" / "drawing.pdf")
        doc.close()
        texts = pdf_blocks(root / "inputs" / "drawing.pdf", 3)
        assert texts[0]["text"] == "wire diameter 2"
        assert .83 < texts[0]["position"]["x"] < .9
        assert .09 < texts[0]["position"]["y"] < .11
        assert sorted([Path("page-10.png"), Path("page-2.png")], key=page_sort_key)[0].name == "page-2.png"
        reuse = ocr_blocks({"ocr": {"raw_pages": [{"page": 1, "image_path": str(root / "pages" / "page-1.png"), "texts": [{"text": "wire diameter 2", "position": {"x": 200, "y": 160, "width": 100, "height": 20, "coordinate_type": "pixel"}}]}]}}, [{"page": 1}])
        assert reuse[0]["position"]["x"] == .2
        document = build_annotations(review(), root, lambda p: f"/api/demo/{p.as_posix()}", candidates_payload={"candidates": [], "raw_payloads": {}}, allow_ocr=False)
        assert [p["page"] for p in document["pages"]] == [1, 2, 10]
        patch_body = {"source_document_id": document["source_document_id"], "expected_annotation_revision": 1, "changes": [{"annotation_id": "mean_diameter", "location_id": "mean_diameter-manual", "page": 10, "anchor": {"x": .4, "y": .5}, "bubble": {"x": .45, "y": .45}}]}
        updated = apply_annotation_patch(document, patch_body)
        assert updated["annotation_revision"] == 2
        assert document["annotation_revision"] == 1
        assert next(a for a in updated["annotations"] if a["field"] == "mean_diameter")["locations"][0]["page"] == 10
        try:
            apply_annotation_patch(updated, patch_body)
        except AnnotationConflictError:
            pass
        else:
            raise AssertionError("stale annotation revision accepted")
        for change in [{"page": 99}, {"bubble": {"x": float("nan"), "y": .2}}, {"bubble": {"x": 1.5, "y": .2}}, {"value": 99}, {"page": True}, {"annotation_id": {}}, {"annotation_id": []}]:
            invalid = copy.deepcopy(patch_body)
            invalid["changes"][0].update(change)
            try:
                apply_annotation_patch(document, invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid change accepted: {change}")
        with patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=RuntimeError("offline")):
            fallback = build_annotations(review(), root, lambda p: str(p), candidates_payload={"candidates": [], "raw_payloads": {}})
            assert fallback["warnings"]
            assert fallback["annotations"]
    assert FIELDS.index("surface_roughness_ra") == 11
    print("drawing annotation localization and validation tests passed")


if __name__ == "__main__":
    main()
