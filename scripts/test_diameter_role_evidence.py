import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai_design_review.diameter_evidence import CANDIDATE, INFERENCE, PENDING, pending_roles, resolve_diameter_roles, select_role
from ai_design_review.generation_readiness import assess_generation_readiness
from ai_design_review.workflow import DrawingReviewWorkflow


def candidate(**changes):
    return {
        "field": "outer_diameter", "value": 111, "unit": "mm", "evidence": "Φ111 +2/0",
        "tolerance_upper": 2, "tolerance_lower": 0, "page": 1, "source": "qwen_vision",
        "confidence": .95, **changes,
    }


def drawing(start=120, end=280, *, rotated=False):
    lines = [[50, start, 50, 201], [50, 204, 50, end], [49, start, 132, start], [49, end, 132, end]]
    rect = [32, 170, 46, 220]
    sections = [[132, 100, 20], [132, 300, 20]]
    if rotated:
        lines = [[y, x, yy, xx] for x, y, xx, yy in lines]
        rect = [rect[1], rect[0], rect[3], rect[2]]
        sections = [[y, x, r] for x, y, r in sections]
    return {"page": 1, "width": 400, "height": 400, "lines": lines,
            "wire_sections": sections, "texts": [{"text": "Φ111 +2/0", "bbox": rect}]}


class DiameterRoleTests(unittest.TestCase):
    def test_inner_mean_outer_and_rotation(self):
        for field, endpoints in (("inner_diameter", (120, 280)), ("mean_diameter", (100, 300)), ("outer_diameter", (80, 320))):
            for rotated in (False, True):
                with self.subTest(field=field, rotated=rotated):
                    page = drawing(*endpoints, rotated=rotated)
                    result, = resolve_diameter_roles([candidate()], [page])
                    self.assertEqual(result["field"], field)
                    self.assertEqual((result["value"], result["tolerance_upper"], result["tolerance_lower"]), (111, 2, 0))
                    self.assertEqual(result["diameter_role_evidence"]["observation"]["page"], 1)

    def test_incompatible_ends_other_view_and_second_mark_require_review(self):
        cases = [drawing(end=300), drawing()]
        cases[1]["lines"][-1][-2] = 90
        repeated = drawing()
        repeated["texts"].append({"text": "Φ111", "bbox": [160, 200, 200, 210]})
        cases.append(repeated)
        for page in cases:
            with self.subTest(page=page):
                results = resolve_diameter_roles([candidate()], [page])
                self.assertEqual(len(results), 2 if page is repeated else 1)
                self.assertTrue(all(result["field"]==CANDIDATE for result in results))
                self.assertEqual(len(pending_roles({PENDING:results})),len(results))

    def test_ocr_zero_for_diameter_mark_requires_original_geometry(self):
        for text in ("0111", "0111+2", "0111 +2/0"):
            with self.subTest(text=text):
                page = drawing()
                page["texts"][0]["text"] = text
                result, = resolve_diameter_roles([candidate()], [page])
                self.assertEqual(result["field"], "inner_diameter")
                self.assertEqual(result["diameter_role_evidence"]["observation"]["text"], text)
                self.assertEqual(result["tolerance_lower"], 0 if "/" in text else None)
                result, = resolve_diameter_roles([candidate(evidence="111")], [page])
                self.assertEqual(result["field"], INFERENCE)
                page["wire_sections"] = []
                result, = resolve_diameter_roles([candidate()], [page])
                self.assertEqual(result["field"], CANDIDATE)

        page = drawing()
        page["texts"][0]["text"] = "01110"
        result, = resolve_diameter_roles([candidate()], [page])
        self.assertEqual(result["field"], INFERENCE)

    def test_label_requires_original_evidence_and_matches_value(self):
        proposed = candidate(evidence="图中明确标注外径 Φ111")
        self.assertEqual(resolve_diameter_roles([proposed])[0]["field"], INFERENCE)
        page = drawing()
        page["texts"][0]["text"] = "内径 Φ111 +2/0"
        self.assertEqual(resolve_diameter_roles([proposed], [page])[0]["field"], "inner_diameter")
        page["page"] = 2
        self.assertEqual(resolve_diameter_roles([proposed], [page])[0]["field"], INFERENCE)

    def test_explicit_partial_tolerance_and_mixed_model_description(self):
        page = drawing()
        page["texts"][0]["text"] = "外径 Φ111 +0.1"
        proposed = candidate(evidence="外径 Φ111，线径 Φ2")
        result, = resolve_diameter_roles([proposed], [page])
        self.assertEqual((result["field"], result["tolerance_upper"], result["tolerance_lower"]),
                         ("outer_diameter", .1, None))

    def test_region_and_non_diameter_evidence(self):
        page = drawing()
        page["texts"].append({"text": "外径 111", "bbox": [275, 30, 320, 40]})
        region = {"x": 0, "y": 0, "width": .55, "height": 1, "page": 1}
        self.assertEqual(resolve_diameter_roles([candidate()], [page], region=region)[0]["field"], "inner_diameter")
        for evidence in ("线径 Φ111", "⊥ Φ111 A"):
            self.assertEqual(resolve_diameter_roles([candidate(evidence=evidence)], [page]), [])
        self.assertEqual(resolve_diameter_roles([candidate(evidence="Ra 111")], [page])[0]["field"], INFERENCE)

    def test_stacked_offsets_and_duplicate_descriptions(self):
        page = drawing()
        page["texts"][0]["text"] = "111"
        page["texts"].extend([
            {"text": "+2", "bbox": [31, 222, 36, 228]},
            {"text": "0", "bbox": [40, 222, 45, 228]},
        ])
        first = candidate(evidence="111")
        duplicate = candidate(evidence="vertical dimension 111")
        result, = resolve_diameter_roles([first, duplicate], [page])
        self.assertEqual((result["field"], result["tolerance_upper"], result["tolerance_lower"]),
                         ("inner_diameter", 2, 0))
        page["texts"].append({"text": "+3", "bbox": [31, 222, 36, 228]})
        result, = resolve_diameter_roles([first, duplicate], [page])
        self.assertEqual(result["field"], CANDIDATE)
        self.assertEqual(result["diameter_role_evidence"]["tolerance_options"]["tolerance_upper"], [2, 3])

    def test_same_value_roughness_is_excluded_only_at_its_verified_mark(self):
        from ai_design_review.surface_roughness import ROUGHNESS_VERIFICATION_VERSION

        def box(x, y, w, h):
            return {"x": x, "y": y, "width": w, "height": h, "coordinate_type": "normalized"}

        rough_box = box(.65, .35, .035, .10)
        rough = {"field": "surface_roughness_ra", "value": 12.5, "evidence_status": "direct",
                 "source_document_id": "original", "verification_version": ROUGHNESS_VERIFICATION_VERSION,
                 "independent_evidence": [{"page": 1, "position": rough_box, "text": "Ra 12.5", "source": "local_ocr"}]}
        page = drawing()
        page["source_document_id"] = "original"
        page["texts"][0]["text"] = "Φ12.5"
        false_candidate = candidate(value=12.5, position=rough_box, evidence="12.5")
        real = candidate(value=12.5, evidence="Φ12.5", position=box(.08, .425, .035, .125))
        self.assertEqual([r["field"] for r in resolve_diameter_roles([false_candidate, real, rough], [page])],
                         ["surface_roughness_ra", "inner_diameter"])
        page["texts"] = []
        self.assertEqual(resolve_diameter_roles([{**false_candidate, "position": None}, rough], [page])[-1]["field"],
                         INFERENCE)

    def test_verified_value_and_tolerance_fuse_together(self):
        fields = [{"field": "drawing_name", "value": "圆柱压缩弹簧", "source": "qwen_vision", "confidence": .99},
                  {"field": "wire_diameter", "value": 32, "unit": "mm"}]
        resolved = resolve_diameter_roles([candidate(tolerance_upper=None, tolerance_lower=None), candidate(field="inner_diameter")], [drawing()])
        review = DrawingReviewWorkflow({}).run(None, fields + resolved, run_standardization=False, verify_diameter_roles=True)
        params = review["spring_parameters"]
        self.assertEqual([params[f]["value"] for f in ("inner_diameter", "mean_diameter", "outer_diameter")], [111, 143, 175])
        self.assertEqual(params["inner_diameter"]["tolerance_upper"], 2)
        self.assertIsNone(params["outer_diameter"]["tolerance_upper"])
        self.assertIsNone(params["mean_diameter"]["tolerance_lower"])
        self.assertNotIn(PENDING, review)

    def test_specification_cannot_take_a_role_from_neighbor(self):
        from ai_design_review.diameter_evidence import resolve_specification_diameters

        def block(text, x):
            return {"text": text, "source": "local_ocr", "page": 1,
                    "position": {"x": x, "y": .2, "width": .05, "height": .02}}

        current = {"page": 1, "x": 0, "y": 0, "width": .48, "height": 1}
        other = {"page": 1, "x": .5, "y": 0, "width": .48, "height": 1}
        origin = {"region": current, "code": "", "layout": "blocks", "location_evidence": {},
                  "specification_regions": [current, other], "common_regions": []}
        model = candidate(structured_specification=True)
        blocks = [block("中径", .1), block("111", .2), block("外径", .6), block("111", .7)]
        result, = resolve_specification_diameters([model], origin, {"outer_diameter": model}, blocks)
        self.assertEqual(result["field"], "mean_diameter")
        result, = resolve_specification_diameters([model], origin, {"outer_diameter": model}, blocks[2:])
        self.assertEqual(result["field"], INFERENCE)

    def test_pending_blocks_generation_and_choice_preserves_confirmation_boundary(self):
        pending, = resolve_diameter_roles([candidate()],[drawing(end=300)])
        review = {"drawing_summary": {"spring_type": "compression_spring"},
                  "spring_parameters": {"wire_diameter": {"value": 32, "unit": "mm"}}, PENDING: [pending]}
        self.assertEqual(assess_generation_readiness(review)["status"], "blocked")
        self.assertNotIn("mean_diameter", review["spring_parameters"])
        select_role(review, pending["candidate_id"], "inner_diameter")
        select_role(review, pending["candidate_id"], "inner_diameter")
        self.assertTrue(review["spring_parameters"]["inner_diameter"]["need_human_review"])
        self.assertEqual(review["spring_parameters"]["mean_diameter"]["value"], 143)
        self.assertEqual(review["spring_parameters"]["outer_diameter"]["value"], 175)

    def test_saved_choice_reopens_and_uses_inner_anchor(self):
        from fastapi.testclient import TestClient
        from scripts.test_solidworks_push_api import api, OWNER, ready_review
        from ai_design_review.drawing_annotations import locate_fields
        from ai_design_review.review_persistence import ReviewPersistence
        from ai_design_review.generation_readiness import build_generation_parameter_package

        with TemporaryDirectory() as directory:
            root = Path(directory)
            repo = ReviewPersistence(f"sqlite+pysqlite:///{root / 'review.db'}")
            repo.create_schema_for_testing()
            page = drawing(end=300)
            pending, = resolve_diameter_roles([candidate()], [page])
            review = ready_review()
            review["spring_parameters"].pop("outer_diameter")
            review["spring_parameters"]["wire_diameter"]["value"] = 32
            review["spring_parameters"]["free_length"]["value"] = 350
            review[PENDING] = [pending]
            review["drawing_annotations"] = {
                "annotation_revision": 1, "source_document_id": "fixture",
                "annotations": locate_fields(review, [], []),
            }
            repo.create_review("role", review, owner=OWNER)
            job_dir = root / "role"
            job_dir.mkdir()
            with patch.multiple(api, REVIEW_PERSISTENCE=repo, API_RUN_ROOT=root, verify_review_roughness=lambda *a, **kw: None):
                with TestClient(api.app) as client:
                    url = "/api/reviews/role"
                    current = client.get(url).json()
                    edit = {
                        "review": current, "expected_revision": current["review_revision"],
                        "events": [{"client_event_id": "inner-1", "event_type": "diameter_role_selected",
                                    "metadata": {"candidate_id": pending["candidate_id"], "field": "inner_diameter"}}],
                    }
                    response = client.patch(url, json=edit)
                    self.assertEqual(response.status_code, 200, response.text)
                    update = response.json()["diameter_role_update"]
                    self.assertEqual(update["candidates"][0]["selected_field"], "inner_diameter")
                    self.assertEqual(update["parameters"]["mean_diameter"]["value"], 143)
                    self.assertEqual(client.patch(url, json=edit).status_code, 409)
                    reopened = client.get(url).json()
                    inner = next(a for a in reopened["drawing_annotations"]["annotations"] if a["field"] == "inner_diameter")
                    self.assertEqual(inner["original_value"], 111)
                    self.assertEqual(inner["locations"][0]["page"], 1)
                    self.assertEqual(reopened["spring_parameters"]["inner_diameter"]["tolerance_lower"], 0)
                    confirmed = deepcopy(reopened)
                    for field in ("inner_diameter", "mean_diameter", "outer_diameter"):
                        confirmed["spring_parameters"][field]["need_human_review"] = False
                    preview = build_generation_parameter_package(confirmed)["solidworks_preview"]
                    self.assertEqual(preview["modelParameters"]["中径"], 143)


if __name__ == "__main__":
    unittest.main()
