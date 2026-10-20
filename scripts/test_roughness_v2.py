"""Numeric roughness grounding; saved local drawings only, never Qwen."""
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.surface_roughness import verify_roughness_candidates, apply_roughness_verification, roughness_selection
from ai_design_review.roughness_verification import verify_review_roughness, verify_job_candidates
from ai_design_review import roughness_verification as verification_module
from ai_design_review.drawing_annotations import locate_fields, refresh_roughness_annotations, merge_annotation_upgrade, annotation_source
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.fusion import fuse_candidates
from test_roughness_verification import block, claim, FIELD, BASE_BOX


def run():
    for value in (12.5, 6.3, 3.2, 8.7):
        for text in (str(value), f"/{value}", f"Ra{value}"):
            items = verify_roughness_candidates([claim(value)], [block(text)], "doc")
            assert items[0]["recognition_state"] == "located", items
            assert fuse_candidates(items)["fields"][FIELD]["value"] == value
        for text in (f"φ{value}", f"{value}±0.1", f"{value}1", "加工基准面", "3 2", f"{value} mm"):
            assert verify_roughness_candidates([claim(value)], [block(text)], "doc")[0]["evidence_status"] == "unverified", text
    # Missing, wrong, and ambiguous positions never borrow a nearby dimension.
    numeric = block("6.3")
    other = block("6.3", position={**BASE_BOX, "x": .2})
    hint = {**BASE_BOX, "coordinate_type": "normalized", "origin": "top_left"}
    assert verify_roughness_candidates([claim(6.3, position=hint)], [numeric, other], "doc")[0]["recognition_state"] == "located"
    assert verify_roughness_candidates([claim(6.3)], [numeric, other], "doc")[0]["recognition_state"] == "needs_location"
    assert verify_roughness_candidates([claim(6.3, position={**hint, "x": .8})], [numeric], "doc")[0]["evidence_status"] == "unverified"
    assert verify_roughness_candidates([claim(6.3)], [block("6.3", page=2)], "doc")[0]["evidence_status"] == "unverified"
    assert verify_roughness_candidates([claim(6.3)], [numeric, deepcopy(numeric)], "doc")[0]["recognition_state"] == "located"
    dims = [{"field": "wire_diameter", "value": 6.3, "page": 1, "position": BASE_BOX}]
    assert verify_roughness_candidates([claim(6.3)], [numeric], "doc", dimension_candidates=dims)[0]["evidence_status"] == "unverified"
    refs = verify_roughness_candidates([claim(6.3)], [numeric, other], "doc", historical_locations=[{"page": 1, "bbox": BASE_BOX, "evidence_value": 6.3}])
    assert refs[0]["verification_method"] == "historical_anchor"
    # Same scalar at two ends, and conflicts: evidence bubbles are independent
    # of whether the official scalar is null or pending confirmation.
    claims = [claim(6.3, position=hint), claim(6.3, position={**hint, "x": .2})]
    verified = verify_roughness_candidates(claims, [numeric, other], "doc")
    assert len(verified) == 2 and not roughness_selection(verified)[1]
    review = {"spring_parameters": {FIELD: {"value": None, "need_human_review": True}}}
    apply_roughness_verification(review, verified, "doc")
    assert review["spring_parameters"][FIELD]["value"] == 6.3
    a = next(a for a in locate_fields(review, [], []) if a["field"] == FIELD)
    assert len(a["locations"]) == 2 and all(l["evidence_value"] == 6.3 for l in a["locations"])
    verified = verify_roughness_candidates([claim(6.3), claim(3.2)], [numeric, block("3.2", position={**BASE_BOX, "x": .2})], "doc")
    apply_roughness_verification(review, verified, "doc")
    assert review["spring_parameters"][FIELD]["value"] is None
    assert len(next(a for a in locate_fields(review, [], []) if a["field"] == FIELD)["locations"]) == 2
    # A narrow upgrade leaves every other field and manual roughness position.
    current = {"algorithm_version": "original_annotation_locator/v3", "source_document_id": "doc", "annotation_revision": 9,
               "annotations": [{"field": "wire_diameter", "annotation_id": "wire_diameter", "locations": [{"source": "manual", "page": 1, "anchor": {"x": .2, "y": .3}}]},
                               {**a, "locations": [{**a["locations"][0], "source": "manual"}]}]}
    updated = merge_annotation_upgrade(current, refresh_roughness_annotations(current, review))
    assert updated["annotations"][0] == current["annotations"][0]
    assert updated["annotations"][1]["locations"][0] == current["annotations"][1]["locations"][0]
    print("PASS: v2 numeric positions, dimensions, ambiguity, page/dedup, two ends, conflicts, narrow/manual upgrade")

    # Legacy cached regions >12 cannot consume a new attempt's budget. Completed
    # regions are not sent again, even on an explicit retry.
    from ai_design_review.annotation_ocr import local_ocr_blocks
    from ai_design_review.surface_roughness import roughness_request_key
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        (folder / "inputs").mkdir(); (folder / "pages").mkdir()
        Image.new("RGB", (400, 600), "white").save(folder / "inputs/source.png")
        Image.new("RGB", (400, 600), "white").save(folder / "pages/page-1.png")
        doc, _ = annotation_source(folder, str)
        cache = {"source_document_id": doc["source_document_id"], "algorithm_version": doc["algorithm_version"], "cache_format": 4,
                 "blocks": [], "full": {"1": "completed"}, "regions": {f"old-{n}": {"page": 1, "status": "completed"} for n in range(15)}, "handled_fields": {"1": ["roughness_original_evidence/v1"]}}
        cache_path = folder / "annotation_ocr_v3.json"
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        c = claim(6.3)
        request = {"field": FIELD, "original_value": 6.3, "page": 1, "evidence_pages": [1], "status": "unlocated", "roughness_claim": c, "request_key": roughness_request_key(c)}
        review = {"spring_parameters": {FIELD: {"value": None}}}
        with patch("ai_design_review.annotation_ocr.crop_regions", return_value=[(.2, .3, .4, .5, a) for a in (0, 90, 270)]), patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", return_value=[]) as ocr:
            local_ocr_blocks(folder, doc["pages"], doc["source_document_id"], review, [c], [], verification_requests=[request], retry=True)
            assert len(ocr.call_args.args[0]) == 3
            # Failed empty responses stay retryable, but an actual completed
            # receipt must be skipped on the next retry.
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            for record in cached["regions"].values():
                record["status"] = "completed"
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            ocr.reset_mock()
            local_ocr_blocks(folder, doc["pages"], doc["source_document_id"], review, [c], [], verification_requests=[request], retry=True)
            assert not ocr.called
    print("PASS: legacy >12 cached crops allow new regions, rotations count, completed regions never rerun")


def real():
    with patch("ai_design_review.engines.qwen_vision_adapter.QwenVisionEngine._call_qwen", side_effect=AssertionError("No Qwen")):
        for job in ("a5730d90908d", "c90288992d76"):
            folder = Path("outputs/annotation-v3-qa") / job
            data = (folder / "annotation_qa_snapshot.json").read_bytes()
            review = json.loads(data)
            history = review["drawing_annotations"]
            urls = {Path(p["image_url"]).name: p["image_url"] for p in history["pages"]}
            url_for = lambda path: urls[path.name]
            saved_read = verification_module._read
            def local_read(path):
                # Saved Docker receipts carry Linux paths; the QA copy has
                # equivalent local image paths in remapped_candidates.json.
                return saved_read(folder / "remapped_candidates.json") if path == folder / "candidates.json" else saved_read(path)
            # Require cache-only positive recovery, not a new OCR/cloud run.
            with patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=AssertionError("Saved OCR must suffice")), patch.object(verification_module, "_read", side_effect=local_read):
                verify_review_roughness(review, folder, url_for)
            item = review["spring_parameters"][FIELD]
            assert item["value"] == 12.5 and item["recognition_state"] == "located", (job, item)
            result = refresh_roughness_annotations(history, review)
            a = next(a for a in result["annotations"] if a["field"] == FIELD)
            assert len(a["locations"]) == (2 if job == "a5730d90908d" else 1), (job, a)
            assert all(l["evidence_value"] == 12.5 and .3 < l["anchor"]["y"] < .5 for l in a["locations"])
            if job == "c90288992d76":
                assert item["need_human_review"] and item["roughness_candidates"][0]["verification_method"] == "unique_number"
            (folder / "roughness_v2_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            (folder / "roughness_v2_annotations.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            assert (folder / "annotation_qa_snapshot.json").read_bytes() == data
            print("PASS: saved positive", job, "Ra12.5 anchors", len(a["locations"]))
        folder = Path("outputs/roughness-verification-qa/3b6ab8b8b7f9")
        review = json.loads((folder / "review.json").read_text(encoding="utf-8"))
        verify_review_roughness(review, folder, lambda p: f"/api/reviews/{folder.name}/artifacts/{p.as_posix()}")
        item = review["spring_parameters"][FIELD]
        assert item["value"] is None and item["recognition_state"] != "located"
        assert not next(a for a in locate_fields(review, [], []) if a["field"] == FIELD)["locations"]
        (folder / "verified_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        print("PASS: 1624CA-38 absent 3.2 remains blocked")


if __name__ == "__main__":
    run()
    if "--real" in sys.argv:
        real()
