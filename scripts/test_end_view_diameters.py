"""Local end-view geometry, provenance, cache and historical-card regressions."""
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.diameter_evidence import (
    CANDIDATE, PENDING, SOURCE, pending_roles, reconcile_diameter_review, resolve_diameter_roles,
)
from ai_design_review.end_view_diameter_geometry import end_view_boundaries


def end_view(*, inner=False, vertical=False, broken=False, center=(340, 360)):
    mask = np.zeros((600, 640), np.uint8)
    for radius in (62, 90):
        if broken:
            cv2.ellipse(mask, center, (radius, radius), 0, 0, 55, 255, 2)
            cv2.ellipse(mask, center, (radius, radius), 0, 105, 360, 255, 2)
        else:
            cv2.circle(mask, center, radius, 255, 2)
    x, y = center
    cv2.line(mask, (x - 100, y), (x + 100, y), 255, 1)
    cv2.line(mask, (x, y - 100), (x, y + 100), 255, 1)
    radius = 62 if inner else 90
    a, b, cross = x - radius, x + radius, y - 140
    lines = [[a, cross, b, cross],
             [a, cross - 6, a, y + 4], [b, cross - 6, b, y + 4]]
    for line in lines:
        cv2.line(mask, tuple(line[:2]), tuple(line[2:]), 255, 1)
    box = [x - 25, cross - 19, x + 25, cross - 5]
    if vertical:
        mask = mask.T.copy()
        lines = [[y, x, yy, xx] for x, y, xx, yy in lines]
        box = [box[1], box[0], box[3], box[2]]
    height, width = mask.shape
    return {"page": 1, "width": width, "height": height, "source": "local_ocr",
            "source_document_id": "end-view-fixture", "epsilon": .8, "lines": lines,
            "wire_sections": [], "texts": [{"text": "Φ68±1.94", "bbox": box}],
            "diameter_raster": (mask, 1)}


def claim(**changes):
    return {"field": "outer_diameter", "value": 68, "unit": "mm", "page": 1,
            "source": "qwen_vision", "evidence": "Φ68±1.94", **changes}


def historical_review(page):
    old_page = {key: value for key, value in page.items() if key != "diameter_raster"}
    card, = resolve_diameter_roles([claim()], [old_page])
    card["diameter_role_evidence"]["version"] = "diameter-role/v3"
    return {"drawing_summary": {"spring_type": "compression_spring"},
            "spring_parameters": {"wire_diameter": {"value": 3.5, "unit": "mm"}}, PENDING: [card]}


class EndViewTests(unittest.TestCase):
    def test_inner_outer_vertical_and_partial_arcs(self):
        for inner in (False, True):
            for vertical in (False, True):
                for broken in (False, True):
                    with self.subTest(inner=inner, vertical=vertical, broken=broken):
                        item, = resolve_diameter_roles([claim()], [end_view(inner=inner, vertical=vertical, broken=broken)])
                        self.assertEqual(item["field"], "inner_diameter" if inner else "outer_diameter")
                        self.assertEqual((item["value"], item["tolerance_upper"], item["tolerance_lower"]), (68, 1.94, -1.94))
                        self.assertTrue(item["need_human_review"])
                        geometry, = item["diameter_role_evidence"]["observation"]["geometry"]
                        self.assertEqual(geometry["method"], "end_view_circles")
                        self.assertEqual(len(geometry["contacts"]), 2)

    def test_view_position_does_not_determine_role(self):
        for center in ((130, 350), (490, 420), (350, 220)):
            with self.subTest(center=center):
                item, = resolve_diameter_roles([claim()], [end_view(center=center)])
                self.assertEqual(item["field"], "outer_diameter")

    def test_unit_conversion_uses_text_not_circle_scale(self):
        from ai_design_review.engineering_units import metric_item
        page = end_view()
        page["texts"][0]["text"] = "Φ1.547 +0/-0.03"
        item, = resolve_diameter_roles([claim(value=1.547, unit="in", evidence="Φ1.547 +0/-0.03")], [page])
        converted = metric_item(item, "outer_diameter")
        self.assertEqual(converted["value"], 39.2938)
        self.assertEqual((converted["tolerance_upper"], converted["tolerance_lower"]), (0, -.762))

    def test_tolerance_failure_preserves_verified_role(self):
        page = end_view()
        page["texts"][0]["text"] = "Φ68 +0"
        item, = resolve_diameter_roles([claim()], [page])
        self.assertEqual(item["field"], "outer_diameter")
        self.assertTrue(item["diameter_tolerance_pending"])
        self.assertEqual((item["tolerance_upper"], item["tolerance_lower"]), (None, None))
        page["texts"].append({"text": "-0.76", "bbox": [366, 209, 390, 217]})
        item, = resolve_diameter_roles([claim()], [page])
        self.assertEqual((item["tolerance_upper"], item["tolerance_lower"]), (0, -.76))
        self.assertNotIn("diameter_tolerance_pending", item)
        page["texts"].append({"text": "-0.8", "bbox": [367, 209, 389, 217]})
        item, = resolve_diameter_roles([claim()], [page])
        self.assertEqual(item["field"], "outer_diameter")
        self.assertTrue(item["diameter_tolerance_pending"])

    def test_multiple_circles_wrong_contacts_and_regions_require_review(self):
        third = end_view()
        cv2.circle(third["diameter_raster"][0], (340, 360), 42, 255, 2)
        shifted = end_view()
        cv2.circle(shifted["diameter_raster"][0], (340, 360), 62, 0, 5)
        cv2.circle(shifted["diameter_raster"][0], (360, 360), 62, 255, 2)
        wrong = end_view()
        wrong["lines"][-1][0] += 15
        wrong["lines"][-1][2] += 15
        for page in (third, shifted, wrong):
            with self.subTest(page=page["lines"]):
                item, = resolve_diameter_roles([claim()], [page])
                self.assertEqual(item["field"], CANDIDATE)
        excluded = {"page": 1, "x": 0, "y": 0, "width": .3, "height": 1}
        self.assertNotEqual(resolve_diameter_roles([claim()], [end_view()], region=excluded)[0]["field"], "outer_diameter")

    def test_two_views_on_one_dimension_remain_ambiguous(self):
        page = end_view()
        for radius in (62, 90):
            cv2.circle(page["diameter_raster"][0], (340, 80), radius, 255, 2)
        for line in page["lines"][-2:]:
            line[1] = 76
        item, = resolve_diameter_roles([claim()], [page])
        self.assertEqual(item["field"], CANDIDATE)
        self.assertIn("多个", item["reason"])

    def test_gauge_notes_and_table_circles_do_not_supply_spring_diameters(self):
        for text in ("Φ68 RING GAGE", "环规 Φ68", "检验套筒 Φ68"):
            page = end_view()
            page["texts"][0]["text"] = text
            self.assertEqual(resolve_diameter_roles([claim()], [page])[0]["field"], CANDIDATE)
        page = end_view()
        page["lines"] = []
        self.assertEqual(resolve_diameter_roles([claim()], [page])[0]["field"], CANDIDATE)

    def test_text_label_and_legacy_geometry_win_without_end_view_search(self):
        from scripts.test_diameter_role_evidence import drawing, candidate
        with patch("ai_design_review.end_view_diameter_geometry.end_view_boundaries", side_effect=AssertionError("unneeded geometry")):
            item, = resolve_diameter_roles([candidate()], [drawing()])
            self.assertEqual(item["field"], "inner_diameter")
            page = end_view()
            page["texts"][0]["text"] = "外径 Φ68±1.94"
            self.assertEqual(resolve_diameter_roles([claim()], [page])[0]["field"], "outer_diameter")

    def test_persistent_cache_is_scoped_to_original_and_region(self):
        from ai_design_review.diameter_evidence import _witness_dimensions
        with TemporaryDirectory() as folder:
            page = end_view()
            page["end_view_cache_dir"] = folder
            axis, dimension = next(_witness_dimensions(page["texts"][0], page))
            expected = end_view_boundaries(axis, dimension, page)
            self.assertTrue(expected[0])
            page.pop("_end_view_cache")
            with patch("ai_design_review.end_view_diameter_geometry._detect", side_effect=AssertionError("cache miss")):
                self.assertEqual(end_view_boundaries(axis, dimension, page), expected)
            with patch("ai_design_review.end_view_diameter_geometry._detect", return_value=([], "new scope")) as detector:
                page["source_document_id"] = "different-original"
                self.assertEqual(end_view_boundaries(axis, dimension, page), ([], "new scope"))
                self.assertEqual(detector.call_count, 1)

    def test_historical_card_is_retired_with_original_id_archived(self):
        page = end_view()
        review = historical_review(page)
        card = deepcopy(review[PENDING][0])
        with TemporaryDirectory() as folder, patch("ai_design_review.load_point_evidence.raster_pages", return_value=[page]):
            reconcile_diameter_review(review, Path(folder))
            self.assertFalse(pending_roles(review))
            outer = review["spring_parameters"]["outer_diameter"]
            self.assertEqual(outer["diameter_role_evidence"]["resolved_candidate"], card)
            self.assertEqual(outer["source"], [SOURCE])
            self.assertTrue(outer["need_human_review"])
            self.assertEqual([review["spring_parameters"][field]["value"] for field in
                              ("inner_diameter", "mean_diameter", "outer_diameter")], [61, 64.5, 68])
            snapshot = deepcopy(review)
            reconcile_diameter_review(review, Path(folder))
            self.assertEqual(review, snapshot)

    def test_manual_clear_confirmed_and_processed_records_are_protected(self):
        page = end_view()
        for param in ({"value": 70, "source": ["manual_input"], "need_human_review": True},
                      {"value": None, "source": ["manual_input"], "need_human_review": True},
                      {"value": 70, "need_human_review": False}):
            review = historical_review(page)
            review["spring_parameters"]["outer_diameter"] = deepcopy(param)
            with TemporaryDirectory() as folder, patch("ai_design_review.load_point_evidence.raster_pages", return_value=[page]):
                reconcile_diameter_review(review, Path(folder))
            self.assertEqual(review["spring_parameters"]["outer_diameter"], param)
            self.assertTrue(pending_roles(review))
        for processed in ({"ignored": True}, {"selected_field": "outer_diameter"}):
            review = historical_review(page)
            review[PENDING][0].update(processed)
            before = deepcopy(review)
            with TemporaryDirectory() as folder, patch("ai_design_review.load_point_evidence.raster_pages", return_value=[page]):
                reconcile_diameter_review(review, Path(folder))
            self.assertEqual(review, before)


if __name__ == "__main__":
    unittest.main()
