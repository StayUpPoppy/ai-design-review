"""Numeric evidence, bounded local OCR/retry and real offline drawing regression."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.dimension_text import dimension_number, dimension_text
from ai_design_review.dimension_text import safe_glyph_run
from ai_design_review.drawing_annotations import (
    _annotation_diagnostics, _unique_blocks, build_annotations, locate_fields,
    merge_annotation_upgrade, recover_pdf_dimension_candidates,
)
from ai_design_review.annotation_ocr import local_ocr_blocks
from ai_design_review.engines.ocr_adapter import _outer_diameter_vertical_cluster, _vertical_number_clusters
from test_drawing_annotations_v2 import block, fields, review


def numeric_tests():
    assert dimension_text("3 0 . 2 5") == "30.25"
    assert dimension_number("8 . 2 5") == 8.25
    assert dimension_number("- 0 . 0 2") == -.02
    assert dimension_number("φ 1 . 6") == 1.6
    for text in ("30 25", "4 5", ".020.0528", "D2", "8.25 0 -0.02"):
        assert dimension_number(text) is None, text
    # Deduplication cannot discard the only parseable copy of a PDF dimension.
    original = [block("3 0 . 2 5", y=.2), block("30.25", y=.2001)]
    before = copy.deepcopy(original)
    unique = _unique_blocks(original)
    assert len(unique) == 1 and unique[0]["recognition_aliases"]
    assert original == before
    duplicate_roughness = [block("12.5", x=.6453, y=.3543, width=.0189, height=.0501), block("12.5", x=.6455, y=.3594, width=.0298, height=.0311), block("12.5", x=.33, y=.43)]
    assert len(fields(locate_fields(review(surface_roughness_ra=12.5), [], duplicate_roughness))["surface_roughness_ra"]["locations"]) == 2, "different OCR aspect ratios over one glyph are one location"
    assert safe_glyph_run([{"position": {"x": .1, "y": .2, "width": .01, "height": .01}}, {"position": {"x": .115, "y": .2, "width": .01, "height": .01}}])
    assert not safe_glyph_run([{"position": {"x": .1, "y": .2, "width": .01, "height": .01}}, {"position": {"x": .4, "y": .2, "width": .01, "height": .01}}])
    assert fields(locate_fields(review(free_length=30.25), [], unique))["free_length"]["locations"]
    assert not fields(locate_fields(review(free_length=30), [], [block("3 0 . 2 5")]))["free_length"]["locations"]

    # Tolerance fragments must never become a fabricated nominal diameter.
    fragments = [{"text": text, "position": {"x": 100, "y": y, "width": 12, "height": 15}} for y, text in enumerate([".02", "0", "0.", "5", "2", "8"], start=1)]
    assert not any(v == 20.0528 for v, _, _ in _vertical_number_clusters(fragments))
    assert _outer_diameter_vertical_cluster(fragments) is None
    unread = [{"text": glyph, "position": {"x": 100, "y": i * 16, "width": 12, "height": 15}} for i, glyph in enumerate("8.25")]
    unread.append({"text": "-0.02", "position": {"x": 120, "y": 70, "width": 8, "height": 10}})
    assert _outer_diameter_vertical_cluster(unread) is None, "a digit next to a tolerance is still not a complete nominal value"
    for direction, glyphs in (("top_to_bottom", "8.25"), ("bottom_to_top", "52.8")):
        ordered = [{"text": glyph, "reading_direction": direction, "position": {"x": 100, "y": i * 16, "width": 12, "height": 15}} for i, glyph in enumerate(glyphs)]
        assert any(v == 8.25 for v, _, _ in _vertical_number_clusters(ordered))
    # A rightmost diameter by itself establishes no outer/inner/wire role.
    assert _outer_diameter_vertical_cluster([{"text": "44", "position": {"x": 200, "y": 100}}]) is None

    r = review(outer_diameter=20.0528, free_length=30.25, surface_roughness_ra=12.5)
    r["spring_parameters"]["outer_diameter"]["evidence"] = "vertical dimension candidate .020.0528"
    r["spring_parameters"]["outer_diameter"].update(human_confirmed=True, need_human_review=False)
    saved = copy.deepcopy(r)
    blocks = [block("8 . 2 5", x=.7, y=.4, width=.025, height=.04), block("- 0 . 0 2", x=.71, y=.365, width=.02, height=.025),
              block("5", x=.713, y=.4, width=.01, height=.01), block("3 0 . 2 5"), block("/12.5", x=.66, width=.02, height=.04)]
    found = locate_fields(r, [], blocks)
    assert fields(found)["outer_diameter"]["original_value"] == 8.25
    assert fields(found)["surface_roughness_ra"]["locations"]
    d = _annotation_diagnostics(r, found, {})
    assert next(x for x in d if x["field"] == "outer_diameter")["kind"] == "value_mismatch"
    assert r == saved, "localization must not rewrite confirmed parameters"
    assert not _annotation_diagnostics(review(handedness="right"), locate_fields(review(handedness="right"), [], [block("右旋")]), {})


def cache_tests():
    from PIL import Image
    r = review(outer_diameter=12, surface_roughness_ra=12.5)
    existing = [block("unrelated OCR text")]
    with tempfile.TemporaryDirectory() as directory:
        p = Path(directory)
        (p / "pages").mkdir()
        Image.new("RGB", (400, 300), "white").save(p / "pages" / "page-1.png")
        with patch("ai_design_review.annotation_ocr.crop_regions", return_value=[]), patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize") as mock:
            local_ocr_blocks(p, [{"page": 1}], "doc", r, [], existing)
            assert not mock.called
        cache = json.loads((p / "annotation_ocr_v3.json").read_text())
        assert cache["regions"] == {} and cache["handled_fields"] == {}, "empty proposals are not completed work"
        regions = [(.1, .1, .8, .7, angle) for angle in (0, 90, 270)]
        def recognize(paths, diagnostics):
            results = []
            for i, path in enumerate(paths, 1):
                with Image.open(path) as image:
                    w, h = image.size
                results.append({"page": i, "image_path": str(path), "texts": [{"text": "/12.5", "position": {"x": w / 2, "y": h / 2, "width": 40, "height": 12}}]})
            return results
        with patch("ai_design_review.annotation_ocr.crop_regions", return_value=regions), patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=RuntimeError("offline")) as mock:
            local_ocr_blocks(p, [{"page": 1}], "doc", r, [], existing)
            assert mock.call_count == 1
            local_ocr_blocks(p, [{"page": 1}], "doc", r, [], existing)
            assert mock.call_count == 1, "GET-style reads do not retry failures"
        with patch("ai_design_review.annotation_ocr.crop_regions", return_value=regions), patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=recognize) as mock:
            recovered, warnings, states = local_ocr_blocks(p, [{"page": 1}], "doc", r, [], existing, retry=True)
            assert mock.call_count == 1 and len(recovered) == 3
            assert states["surface_roughness_ra"] == "located" and not warnings
            assert all(0 <= b["position"][k] <= 1 for b in recovered for k in ("x", "y", "width", "height"))
            local_ocr_blocks(p, [{"page": 1}], "doc", r, [], existing)
            assert mock.call_count == 1
        current = {"algorithm_version": "original_annotation_locator/v3", "source_document_id": "doc", "annotation_revision": 3,
                   "annotations": locate_fields(r, [], [block("外径12")])}
        rebuilt = {**copy.deepcopy(current), "annotations": locate_fields(r, [], recovered)}
        old = copy.deepcopy(fields(current["annotations"])["outer_diameter"]["locations"])
        merged = merge_annotation_upgrade(current, rebuilt, force=True)
        assert merged["annotation_revision"] == 4
        assert fields(merged["annotations"])["outer_diameter"]["locations"] == old
        assert fields(merged["annotations"])["surface_roughness_ra"]["locations"]
        legacy = review(outer_diameter=20.0528)
        legacy["spring_parameters"]["outer_diameter"]["evidence"] = "vertical dimension candidate .020.0528"
        base = build_annotations(legacy, p, str, candidates_payload={"candidates": []}, allow_ocr=False)
        located = fields(locate_fields(review(outer_diameter=8.25), [], [block("8.25")]))["outer_diameter"]
        base["annotations"] = [located if a["field"] == "outer_diameter" else a for a in base["annotations"]]
        legacy["drawing_annotations"] = base
        refreshed = build_annotations(legacy, p, str, candidates_payload={"candidates": []}, allow_ocr=False, retry_ocr=True)
        assert fields(refreshed["annotations"])["outer_diameter"]["original_value"] == 8.25, "retry must not revert reliable evidence to an old wrong parameter value"
        assert any(d["kind"] == "value_mismatch" for d in refreshed["diagnostics"])


def real_tests():
    """User files stay ignored/local; fixture values appear only in tests."""
    root = Path(__file__).resolve().parents[1] / "outputs" / "annotation-v3-qa"
    cases = {
        "94372f98ae61": {"outer_diameter": (8.25, (.66, .39, .72, .47)), "free_length": (30.25, (.47, .27, .55, .34)), "surface_roughness_ra": (12.5, (.62, .33, .68, .41))},
        "c90288992d76": {"outer_diameter": (12, (.67, .40, .71, .48)), "free_length": (55.6, (.48, .31, .58, .38)), "surface_roughness_ra": (12.5, (.65, .33, .69, .40))},
        "0a96d83d903c": {"outer_diameter": (44, (.72, .26, .77, .34)), "free_length": (80, (.46, .41, .54, .46))},
        "a5730d90908d": {"outer_diameter": (27, (.64, .40, .69, .47)), "free_length": (19, (.46, .31, .52, .37)), "surface_roughness_ra": (12.5, (.61, .36, .67, .44))},
        "137090949f86": {"outer_diameter": (28, (.62, .40, .68, .46)), "free_length": (80, (.48, .30, .54, .37))},
    }
    for job, expected in cases.items():
        p = root / job
        review_data = json.loads((p / "annotation_qa_snapshot.json").read_text(encoding="utf-8"))
        payload = json.loads((p / "remapped_candidates.json").read_text(encoding="utf-8"))
        before = copy.deepcopy(review_data)
        doc = build_annotations(review_data, p, str, candidates_payload=payload)
        (p / "v3.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        by_field = fields(doc["annotations"])
        for field, (value, region) in expected.items():
            a = by_field[field]
            assert a["original_value"] == value, (job, field, a)
            assert any(region[0] <= l["anchor"]["x"] <= region[2] and region[1] <= l["anchor"]["y"] <= region[3] for l in a["locations"]), (job, field, a["locations"])
        if job == "94372f98ae61":
            assert any(d["kind"] == "value_mismatch" and d["evidence_value"] == 8.25 for d in doc["diagnostics"])
            recovered = recover_pdf_dimension_candidates(next((p / "inputs").glob("*.pdf")), payload["candidates"])
            assert any(c["field"] == "outer_diameter" and c["value"] == 8.25 for c in recovered)
            assert not any(c["field"] == "outer_diameter" and c["value"] == 20.0528 for c in recovered)
            from ai_design_review.workflow import DrawingReviewWorkflow
            rules = json.loads((root.parents[1] / "config" / "factory_rules.json").read_text(encoding="utf-8"))
            replay = DrawingReviewWorkflow(rules).run(None, recovered, run_standardization=False)
            assert replay["spring_parameters"]["outer_diameter"]["value"] == 8.25
            assert replay["spring_parameters"]["outer_diameter"]["tolerance_lower"] == -.02
        if job == "0a96d83d903c":
            assert any(d["kind"] == "role_conflict" for d in doc["diagnostics"])
        if job == "a5730d90908d":
            assert len(by_field["surface_roughness_ra"]["locations"]) == 2
        # Replay the upload's deterministic parsing/fusion, reusing raw local
        # OCR and saved visual candidates; never call an external model.
        from ai_design_review.engines.ocr_adapter import ocr_payload_to_candidates
        from ai_design_review.workflow import DrawingReviewWorkflow
        rules = json.loads((root.parents[1] / "config" / "factory_rules.json").read_text(encoding="utf-8"))
        replay_candidates = [c for c in payload["candidates"] if c.get("source") not in {"rapidocr", "paddleocr"}]
        for raw in payload.get("raw_payloads", {}).values():
            if isinstance(raw, dict):
                for page in raw.get("raw_pages", []):
                    replay_candidates.extend(ocr_payload_to_candidates({"texts": page.get("texts", [])}))
        source = next((p / "inputs").iterdir())
        replay_candidates = recover_pdf_dimension_candidates(source, replay_candidates)
        replay = DrawingReviewWorkflow(rules).run(None, replay_candidates, run_standardization=False)
        for field in ("outer_diameter", "free_length"):
            assert replay["spring_parameters"][field]["value"] == expected[field][0], (job, field, replay["spring_parameters"][field])
        (p / "replayed_review.json").write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
        assert review_data == before
        print("real anchors passed", job, flush=True)


if __name__ == "__main__":
    numeric_tests()
    cache_tests()
    if "--real" in sys.argv:
        real_tests()
    print("annotation v3 regressions passed")
