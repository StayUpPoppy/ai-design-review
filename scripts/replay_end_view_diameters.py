"""Replay copied original end-view orders without Qwen or production writes.

Usage: python scripts/replay_end_view_diameters.py <copied-orders-directory>
Only derived local geometry/OCR caches in that copy may be updated.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.diameter_evidence import PENDING, pending_roles, reconcile_diameter_review
from ai_design_review.engines.ocr_providers import RapidOcrProvider
from ai_design_review.engines.qwen_vision_adapter import QwenVisionEngine, qwen_payload_to_candidates
from ai_design_review.load_point_evidence import ground_job_candidates
from ai_design_review.standardizers.calculation_state import human_override
from ai_design_review.workflow import DrawingReviewWorkflow

EXPECTED = {
    "F01P10203": (3.5, 61, 64.5, 68, 1.94, -1.94),
    "F01P10171": (4.8, 29.69, 34.49, 39.29, 0, -.76),
}
FIELDS = ("wire_diameter", "inner_diameter", "mean_diameter", "outer_diameter")


def check(review, expected):
    params = review["spring_parameters"]
    assert tuple(params.get(field, {}).get("value") for field in FIELDS) == expected[:4]
    outer = params["outer_diameter"]
    assert (outer.get("tolerance_upper"), outer.get("tolerance_lower")) == expected[4:]
    assert not outer.get("diameter_tolerance_pending")
    assert outer["need_human_review"]
    assert not pending_roles(review)
    observation = outer["diameter_role_evidence"]["observation"]
    assert observation["position"] and observation["source"] in {"pdf_text", "local_ocr"}
    assert any(item["method"] == "end_view_circles" for item in observation["geometry"])


def main(root):
    covered = set()
    total_ocr = 0
    for path in sorted(Path(root).glob("*/review.json")):
        original = json.loads(path.read_text(encoding="utf-8"))
        drawing_no = original.get("drawing_summary", {}).get("drawing_no")
        if drawing_no not in EXPECTED:
            continue
        folder = path.parent
        before = deepcopy(original)
        with patch.object(QwenVisionEngine, "_call_qwen", side_effect=AssertionError("Unexpected Qwen call")), \
             patch.object(RapidOcrProvider, "recognize", wraps=RapidOcrProvider().recognize) as ocr:
            started = perf_counter()
            reconcile_diameter_review(original, folder, allow_callout_ocr=True)
            historical_ms = (perf_counter() - started) * 1000
            if human_override(before["spring_parameters"].get("outer_diameter", {})):
                assert original["spring_parameters"] == before["spring_parameters"]
                assert original[PENDING] == before[PENDING]
                print("PASS protected historical selection", path.parent.name, drawing_no)
                continue
            check(original, EXPECTED[drawing_no])
            prior_id = before[PENDING][0]["candidate_id"]
            assert original["spring_parameters"]["outer_diameter"]["diameter_role_evidence"]["resolved_candidate"]["candidate_id"] == prior_id
            reopened = json.loads(json.dumps(original))
            reconcile_diameter_review(reopened, folder, allow_callout_ocr=True)
            assert reopened == original
            replay = deepcopy(before)
            with patch("ai_design_review.end_view_diameter_geometry._detect", side_effect=AssertionError("Geometry cache miss")):
                started = perf_counter()
                reconcile_diameter_review(replay, folder, allow_callout_ocr=True)
                cached_ms = (perf_counter() - started) * 1000
            check(replay, EXPECTED[drawing_no])
            raw = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))["raw_payloads"]
            parsed = json.loads((folder / "qwen_vision_raw.json").read_text(encoding="utf-8"))["parsed"]
            source = next((folder / "inputs").glob("*.pdf"))
            candidates = ground_job_candidates(folder, qwen_payload_to_candidates(parsed), raw)
            fresh = DrawingReviewWorkflow({}).run(str(source), candidates, run_standardization=False, verify_diameter_roles=True)
            check(fresh, EXPECTED[drawing_no])
            total_ocr += ocr.call_count
            assert ocr.call_count == 0, "Complete original caches should not need another OCR pass"
        assert json.loads(path.read_text(encoding="utf-8")) == before
        covered.add(drawing_no)
        print(f"PASS {drawing_no}: original + historical + reopen; verification_ms={historical_ms:.1f}, "
              f"cached_ms={cached_ms:.1f}, OCR={ocr.call_count}, Qwen=0")
    assert covered == set(EXPECTED), ("Missing unhandled original orders", sorted(set(EXPECTED) - covered))
    print(f"PASS both original end-view drawings, OCR={total_ocr}, Qwen=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    main(parser.parse_args().root)
