"""Value/position separation and fresh-upload end pairing, with no cloud calls."""
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.surface_roughness import (apply_roughness_verification, verify_roughness_candidates,
    roughness_selection, verified_roughness_candidate, roughness_value_verified)
from ai_design_review.roughness_verification import verify_job_candidates, verify_review_roughness
from ai_design_review.drawing_annotations import build_annotations, locate_fields
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.fusion import fuse_candidates
from ai_design_review.workflow import DrawingReviewWorkflow
from ai_design_review.generation_readiness import build_generation_parameter_package
from test_roughness_verification import block, claim, FIELD
from test_solidworks_export import base_review


def rotated(box, angle):
    x, y, w, h = (box[k] for k in ("x", "y", "width", "height"))
    if angle == 90:
        x, y, w, h = 1-y-h, x, h, w
    elif angle == 180:
        x, y = 1-x-w, 1-y-h
    elif angle == 270:
        x, y, w, h = y, 1-x-w, h, w
    return dict(x=x, y=y, width=w, height=h)


def run():
    for value in (12.5, 6.3, 3.2, 8.7):
        for angle in (0, 90, 180, 270):
            boxes = [rotated(dict(x=x, y=.27, width=.025, height=.03), angle) for x in (.23, .74)]
            region = rotated(dict(x=.2, y=.2, width=.6, height=.2), angle)
            context = [{"page": 1, "width": 800 if angle % 180 else 1200, "height": 1200 if angle % 180 else 800,
                        "regions": [(region["x"], region["y"], region["x"]+region["width"], region["y"]+region["height"])]}]
            claims = [claim(value, location=scope, roughness_model_claim=True) for scope in ("左端面", "右端面")]
            blocks = [block(str(value), position=b) for b in boxes]
            verified = verify_roughness_candidates(claims, blocks, "doc", view_context=context)
            assert all(c["verification_method"] == "end_pair" and c["value_verified"] for c in verified), verified
            projected = fuse_candidates(verified)["fields"][FIELD]
            assert projected["value"] == value and projected["surface_location"] == "两端面" and not projected.get("roughness_conflict")
            assert projected["recognition_state"] == "located" and projected["need_human_review"]
            review = base_review(); review["spring_parameters"][FIELD] = projected
            annotation = next(a for a in locate_fields(review, [], []) if a["field"] == FIELD)
            assert len(annotation["locations"]) == 2
            assert {l["evidence_value"] for l in annotation["locations"]} == {value}
            # Ambiguous regions, a square view, or a third same-value glyph
            # prevent pairing while preserving the verified scalar.
            for views, texts in (([], blocks), (context*2, blocks),
                                 ([{"page": 1, "width": 800, "height": 800, "regions": [(0, 0, 1, 1)]}], blocks),
                                 (context, blocks + [block(str(value), position=rotated(dict(x=.48, y=.27, width=.025, height=.03), angle))])):
                unlocated = verify_roughness_candidates(claims, texts, "doc", view_context=views)
                assert all(roughness_value_verified(c) and not verified_roughness_candidate(c) for c in unlocated)
                pending = fuse_candidates(unlocated)["fields"][FIELD]
                assert pending["value"] == value and pending["value_verified"] and pending["recognition_state"] == "needs_location"
                review["spring_parameters"][FIELD] = pending
                a = next(a for a in locate_fields(review, [], []) if a["field"] == FIELD)
                assert not a["locations"] and a["original_value"] == value
                assert "表面粗糙度" not in build_generation_parameter_package(review)["solidworks_preview"]["titleBlockProperties"]
                pending.update(need_human_review=False, source=["human_confirmed"])
                assert build_generation_parameter_package(review)["solidworks_preview"]["titleBlockProperties"]["表面粗糙度"] == value
            # One real end can be located while the second stays pending.
            one = verify_roughness_candidates(claims, blocks[:1], "doc", view_context=context)
            projected = fuse_candidates(one)["fields"][FIELD]
            assert projected["value"] == value and projected["recognition_state"] == "needs_location"
            review["spring_parameters"][FIELD] = projected
            assert len(next(a for a in locate_fields(review, [], []) if a["field"] == FIELD)["locations"]) == 1
    # A numeric-only dimension or a different page does not verify a Ra claim.
    c = claim(3.2, roughness_model_claim=True)
    number = block("3.2")
    for blocks, dims in (([number], [{"field": "wire_diameter", "value": 3.2, "page": 1, "position": number["position"]}]),
                         ([block("3.2", page=2)], []), ([block("▲：加工基准面")], [])):
        assert not roughness_value_verified(verify_roughness_candidates([c], blocks, "doc", dimension_candidates=dims)[0])
    print("PASS: v3 separate values/positions, two ends, 4 rotations, 4 values, duplicate/multiple views, partial location and SW confirmation")


def real():
    folder = Path("outputs/roughness-v3-qa/891b8f3b749f")
    original = (folder / "review.json").read_bytes()
    raw_bytes = (folder / "qwen_vision_raw.json").read_bytes()
    raw = json.loads(raw_bytes)
    candidates = qwen_payload_to_candidates(raw["parsed"])
    roughness = [c for c in candidates if c.get("field") == FIELD]
    assert len(roughness) == 2 and all(c.get("position") is None and c.get("roughness_model_claim") for c in roughness)
    payload = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    local_raw = deepcopy(payload["raw_payloads"])
    for receipt in local_raw.values():
        if not isinstance(receipt, dict):
            continue
        for page in receipt.get("raw_pages", []):
            prefix = f"/app/outputs/api_runs/{folder.name}/"
            if str(page.get("image_path", "")).startswith(prefix):
                page["image_path"] = str(folder / page["image_path"][len(prefix):])
    url_for = lambda p: f"/api/reviews/{folder.name}/artifacts/{p.as_posix()}"
    with patch("ai_design_review.engines.qwen_vision_adapter.QwenVisionEngine._call_qwen", side_effect=AssertionError("No cloud")), \
         patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=AssertionError("Saved OCR must suffice")):
        # No review/history is passed: this exercises the new-upload path.
        verified = verify_job_candidates(folder, candidates, local_raw, url_for)
        rules = json.loads(Path("config/factory_rules.json").read_text(encoding="utf-8"))
        review = DrawingReviewWorkflow(rules).run(None, verified, run_standardization=False)
        param = review["spring_parameters"][FIELD]
        assert param["value"] == 12.5 and param["surface_location"] == "两端面" and param["need_human_review"]
        assert param["recognition_state"] == "located" and param["value_verified"]
        assert all(c["verification_method"] == "end_pair" for c in param["roughness_candidates"])
        annotations = build_annotations(review, folder, url_for, candidates_payload={"candidates": verified, "raw_payloads": local_raw}, allow_ocr=False)
        a = next(a for a in annotations["annotations"] if a["field"] == FIELD)
        assert len(a["locations"]) == 2
        left, right = sorted(a["locations"], key=lambda l: l["anchor"]["x"])
        assert .32 < left["anchor"]["x"] < .4 and .4 < left["anchor"]["y"] < .5
        assert .62 < right["anchor"]["x"] < .68 and .34 < right["anchor"]["y"] < .43
        # v2 persisted classifications also recover, without old anchors.
        old = json.loads(original); old.pop("drawing_annotations", None)
        verify_review_roughness(old, folder, url_for)
        legacy = old["spring_parameters"][FIELD]
        assert legacy["value"] == 12.5 and legacy["recognition_state"] == "located"
        assert all(c["value_verified"] for c in legacy["roughness_candidates"])
        assert not verify_review_roughness(old, folder, url_for), "Reopening the current version is stable"
        (folder / "v3_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "v3_annotations.json").write_text(json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8")
    assert original == (folder / "review.json").read_bytes() and raw_bytes == (folder / "qwen_vision_raw.json").read_bytes()
    negative = Path("outputs/roughness-verification-qa/3b6ab8b8b7f9")
    review = json.loads((negative / "review.json").read_text(encoding="utf-8"))
    verify_review_roughness(review, negative, lambda p: f"/api/reviews/{negative.name}/artifacts/{p.as_posix()}")
    assert review["spring_parameters"][FIELD]["value"] is None
    assert not next(a for a in locate_fields(review, [], []) if a["field"] == FIELD)["locations"]
    print("PASS: fresh YD4765020175, no historical anchors/model boxes: Ra12.5 with TWO evidence anchors; absent 3.2 blocked")


if __name__ == "__main__":
    run()
    if "--real" in sys.argv:
        real()
