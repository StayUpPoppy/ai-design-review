"""Grounding regression: no network, no real order writes, bounded mock OCR."""
from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.surface_roughness import (
    ROUGHNESS_VERIFICATION_VERSION, apply_roughness_verification, ensure_surface_roughness_parameter,
    independent_roughness_evidence, merge_roughness_candidates, verified_roughness_candidate, verify_roughness_candidates,
)
from ai_design_review.roughness_verification import verify_job_candidates, verify_review_roughness
from ai_design_review.fusion import fuse_candidates
from ai_design_review.drawing_annotations import annotation_source, build_annotations, locate_fields
from ai_design_review.annotation_ocr import local_ocr_blocks
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package
from test_solidworks_export import base_review


FIELD = "surface_roughness_ra"
BASE_BOX = {"x": .6, "y": .3, "width": .1, "height": .02}


def block(text, page=1, **kwargs):
    return {"text": text, "page": page, "source": "local_ocr", "position": deepcopy(BASE_BOX), **kwargs}


def claim(value=3.2, location="两端面", **kwargs):
    return {"field": FIELD, "value": value, "unit": "μm", "source": "qwen_vision", "evidence": f"Ra{value}",
            "surface_location": location, "page": 1, "position": None, "need_human_review": True, **kwargs}


def run():
    for value in (3.2, 12.5, 6.3, 1.6):
        for text in (f"Ra{value}", f"两端面粗糙度：{value}", f"▽ {value}", f"√ {value}"):
            refs = independent_roughness_evidence(value, [block(text)])
            assert refs and refs[0]["position"] == BASE_BOX, text
            verified = verify_roughness_candidates([claim(value)], [block(text)], "doc")
            assert verified_roughness_candidate(verified[0])
            result = fuse_candidates(verified)["fields"][FIELD]
            assert result["value"] == value and result["need_human_review"]
        for text in (str(value), f"φ{value}", f"▲：加工基准面 {value}", f"▼{value}", f"△{value}", f"/{value}",
                     f"Ra{value}1", f"不是粗糙度Ra{value}", f"参考Ra{value}", f"▽{value} 加工基准面"):
            assert not independent_roughness_evidence(value, [block(text)]), text
    assert not independent_roughness_evidence(3.2, [block("Ra3.2", source="qwen_vision")])
    assert not independent_roughness_evidence(3.2, [block("Ra3.2", position=None)])
    assert not independent_roughness_evidence(3.2, [block("Ra3.2", page=2)], 1)
    assert not independent_roughness_evidence(3.2, [block("Ra3.2", numeric_join_unsafe=True)])
    assert not independent_roughness_evidence(3.2, [block("Ra"), block("3.2")])
    assert not independent_roughness_evidence(3.2, [block("Ra 3 . 2")])
    assert independent_roughness_evidence(3.2, [block("▲：加工基准面"), block("外圆Ra3.2", page=2)], 2)
    assert independent_roughness_evidence(3.2, [block("▲：加工基准面；两端面Ra3.2")])
    assert independent_roughness_evidence(3.2, [block("加工基准面粗糙度Ra3.2")]), "An actual Ra label on a datum face is valid"
    assert not independent_roughness_evidence(3.2, [block("Ra3.2 mm")])
    tokens = [{"text": "Ra", "position": {"x": .1, "y": .1, "width": .03, "height": .01}},
              {"text": "3.2", "position": {"x": .8, "y": .1, "width": .03, "height": .01}}]
    assert not independent_roughness_evidence(3.2, [block("Ra 3.2", source="pdf_text", tokens=tokens)])
    tokens[1]["position"]["x"] = .135
    assert independent_roughness_evidence(3.2, [block("Ra 3.2", source="pdf_text", tokens=tokens)])
    for angle in (90, 270):
        assert independent_roughness_evidence(6.3, [block("Ra6.3", reading_angle=angle, position={"x": .1, "y": .2, "width": .02, "height": .1})])
    # Repeated numbers cannot borrow a different annotation's coordinates.
    misplaced = claim(position={**BASE_BOX, "x": .1, "coordinate_type": "normalized"})
    assert not verified_roughness_candidate(verify_roughness_candidates([misplaced], [block("Ra3.2")], "doc")[0])
    bogus = "标题栏下方符号 ▲: 加工基准面 (对应粗糙度符号 ▽3.2/Ra3.2 指向端面)"
    payload = {"spring_type": "compression_spring", "parameters": {FIELD: {"value": 3.2, "surface_location": "两端面", "confidence": 1.0, "evidence": bogus}}}
    raw = qwen_payload_to_candidates(payload)
    raw = [c for c in raw if c.get("field") == FIELD]
    assert len(raw) == 1, "The structured roughness field is not re-extracted as an unrelated note"
    assert all(c["evidence_status"] == "unverified" for c in raw)
    raw[0]["evidence_status"] = "direct"  # Old/model labels never prove anything.
    assert fuse_candidates(raw)["fields"][FIELD]["value"] is None
    verified = verify_roughness_candidates(raw, [block("▲：加工基准面")], "doc")
    merged = merge_roughness_candidates(verified)
    assert len(merged) == 1 and not merged[0].get("location_conflict")
    result = fuse_candidates(verified)["fields"][FIELD]
    assert result["value"] is None and not result.get("roughness_conflict")
    # Same value in physically independent locations is not deduplicated away.
    direct = verify_roughness_candidates([claim()], [block("外圆Ra3.2"), block("两端面Ra3.2", position={**BASE_BOX, "x": .2})], "doc")
    result = fuse_candidates(direct)["fields"][FIELD]
    assert len(result["roughness_candidates"]) == 2 and result["roughness_conflict"]
    same_line = verify_roughness_candidates([claim()], [block("外圆Ra3.2 两端面Ra3.2")], "doc")
    assert len(merge_roughness_candidates(same_line)) == 2, "Different explicit scopes in one OCR run remain distinct"
    review = base_review()
    review["spring_parameters"][FIELD] = {**result, "value": 3.2, "roughness_candidates": merge_roughness_candidates(raw), "source": ["qwen_vision"], "need_human_review": True}
    assert apply_roughness_verification(review, verified, "doc")
    item = review["spring_parameters"][FIELD]
    assert item["value"] is None and len(item["roughness_candidates"]) == 1
    assert item["roughness_original_recognition"]["value"] == 3.2
    assert not apply_roughness_verification(review, verified, "doc"), "Ordinary reads don't repeat an upgrade"
    assert "表面粗糙度" not in build_generation_parameter_package(review)["solidworks_preview"]["titleBlockProperties"]
    for protection in ({"source": ["human_edited"]}, {"source": ["human_roughness_reference"]}, {"source": ["human_confirmed"]},
                       {"need_human_review": False}, {"need_human_review": None}):
        human = deepcopy(review)
        human["spring_parameters"][FIELD].update(value=6.3, **protection)
        apply_roughness_verification(human, verified, "doc")
        assert human["spring_parameters"][FIELD]["value"] == 6.3
        assert human["spring_parameters"][FIELD]["roughness_verification_warning"]
    legacy = base_review()
    legacy["spring_parameters"][FIELD] = {"value": None, "need_human_review": True}
    legacy["technical_requirements"] = [{"type": "surface_roughness", "content": "Ra3.2", "source": "qwen_vision", "need_human_review": True}]
    ensure_surface_roughness_parameter(legacy)
    assert legacy["spring_parameters"][FIELD]["value"] is None
    assert legacy["spring_parameters"][FIELD]["roughness_candidates"][0]["evidence_status"] == "unverified"
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / "inputs").mkdir(); (folder / "pages").mkdir()
        Image.new("RGB", (400, 600), "white").save(folder / "inputs/drawing.jpg")
        Image.new("RGB", (400, 600), "white").save(folder / "pages/page-1.png")
        document, _ = annotation_source(folder, lambda p: str(p))
        calls = []
        def recognize(paths, diagnostics):
            calls.extend(paths)
            return [{"page": n, "image_path": str(path), "texts": [{"text": "▲：加工基准面", "position": {"x": 100, "y": 200, "width": 60, "height": 20}}]}
                    for n, path in enumerate(paths, 1)]
        stub = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {FIELD: {"value": None}}}
        fake_receipt = {"engine": "rapidocr", "provider": "rapidocr", "raw_pages": [{"page": 1,
                        "image_path": str(folder / "pages/page-1.png"), "texts": [{"text": "Ra3.2",
                        "position": {"x": 100, "y": 200, "width": 60, "height": 20}}]}]}
        with patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=recognize):
            output = verify_job_candidates(folder, raw, {"qwen_vision": fake_receipt, "candidate_json": fake_receipt}, lambda p: str(p), review=stub)
            assert len(calls) == 13, "One full page plus 12 crop/rotation inputs"
            assert all(c["evidence_status"] == "unverified" for c in output)
            verify_job_candidates(folder, raw, {}, lambda p: str(p), review=stub)
            build_annotations(stub, folder, lambda p: str(p), candidates_payload={"candidates": raw})
            assert len(calls) == 13, "Ordinary reads and bubbles share the cache/budget"
            cached_receipt = verify_job_candidates(folder, raw, {"rapidocr_dimension_grounding": fake_receipt}, lambda p: str(p), review=stub)
            assert all(verified_roughness_candidate(c) for c in cached_receipt)
            assert len(calls) == 13, "An actual saved local-OCR receipt is reused without a second run"
            ocr = json.loads((folder / "annotation_ocr_v3.json").read_text(encoding="utf-8"))
            assert len(ocr["regions"]) == 12 and set(ocr["full"].values()) == {"completed"}
        # A null formal value still independently triggers candidate verification.
        item = {"value": None, "need_human_review": True, "roughness_candidates": merge_roughness_candidates(raw), "source": ["qwen_vision"]}
        stub["spring_parameters"][FIELD] = item
        with patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=AssertionError("cache must be reused")):
            verify_review_roughness(stub, folder, lambda p: str(p))
        assert item["value"] is None and len(item["roughness_candidates"]) == 1
        # Failure is cached; ordinary opens do not loop on a broken OCR runtime.
        (folder / "annotation_ocr_v3.json").unlink()
        (folder / "roughness_verification.json").unlink()
        with patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=RuntimeError("offline failure")) as mocked:
            output = verify_job_candidates(folder, raw, {}, lambda p: str(p))
            count = mocked.call_count
            assert count > 0
            verify_job_candidates(folder, raw, {}, lambda p: str(p))
            assert mocked.call_count == count
        assert "失败" in output[0]["evidence_reason"]
        def recovered_ocr(paths, diagnostics):
            return [{"page": n, "image_path": str(path), "texts": [{"text": "Ra3.2", "position": {"x": 100, "y": 200, "width": 60, "height": 20}}]}
                    for n, path in enumerate(paths, 1)]
        stub["spring_parameters"][FIELD] = {"value": None, "unit": "μm", "source": ["qwen_vision"], "need_human_review": True,
                                            "roughness_candidates": merge_roughness_candidates(raw)}
        with patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", side_effect=recovered_ocr):
            build_annotations(stub, folder, lambda p: str(p), candidates_payload={"candidates": raw}, retry_ocr=True)
            verify_review_roughness(stub, folder, lambda p: str(p))
        assert stub["spring_parameters"][FIELD]["value"] == 3.2, "Retry also works when the formal value and bubble are absent"
        assert stub["spring_parameters"][FIELD]["need_human_review"]
    print("PASS: independent roughness evidence, hallucinated datum, coordinates, scope dedup, protected history, null-value OCR, shared budgets and failure caches")


if __name__ == "__main__":
    run()
    if "--real" in sys.argv:
        from ai_design_review.workflow import DrawingReviewWorkflow
        folder = Path("outputs/roughness-verification-qa/3b6ab8b8b7f9")
        original = (folder / "review.json").read_bytes()
        raw_file = (folder / "qwen_vision_raw.json").read_bytes()
        review = json.loads(original)
        url_for = lambda p: f"/api/reviews/{folder.name}/artifacts/{p.as_posix()}"
        with patch("ai_design_review.engines.qwen_vision_adapter.QwenVisionEngine._call_qwen", side_effect=AssertionError("No cloud calls")):
            assert verify_review_roughness(review, folder, url_for)
            item = review["spring_parameters"][FIELD]
            assert item["value"] is None and not item.get("roughness_conflict")
            assert len(item["roughness_candidates"]) == 1 and item["roughness_candidates"][0]["value"] == 3.2
            assert item["roughness_candidates"][0]["evidence_status"] == "unverified"
            assert not verify_review_roughness(review, folder, url_for), "Repeated reads are stable"
            (folder / "verified_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            raw = json.loads(raw_file)
            candidates = qwen_payload_to_candidates(raw["parsed"])
            verified = verify_job_candidates(folder, candidates, {}, url_for)
            rules = json.loads(Path("config/factory_rules.json").read_text(encoding="utf-8"))
            replay = DrawingReviewWorkflow(rules).run(None, verified, run_standardization=False)
            assert replay["spring_parameters"][FIELD]["value"] is None
            assert len(replay["spring_parameters"][FIELD]["roughness_candidates"]) == 1
            (folder / "replayed_review.json").write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
        assert (folder / "review.json").read_bytes() == original
        assert (folder / "qwen_vision_raw.json").read_bytes() == raw_file
        print("PASS: real saved 1624CA-38 drawing/raw Qwen replay: 3.2 stays unverified, original files unchanged", flush=True)
