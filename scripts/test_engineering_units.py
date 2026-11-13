import unittest
from copy import deepcopy

from ai_design_review.diameter_evidence import original_observation
from ai_design_review.engineering_units import apply_drawing_units, metric_review, metric_text, page_length_units
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.load_height_relations import model_load_relation
from ai_design_review.standardizers.design_checks import calculate_design_checks


class EngineeringUnitsTest(unittest.TestCase):
    def test_unit_scope_excludes_water_column_and_honors_explicit_dimensions(self):
        payload = {"ocr": {"texts": [
            {"text": "SIZE: 2 IN W.C. TO 4 IN W.C.", "page": 1},
            {"text": "FREE LENGTH 3.780 IN", "page": 2},
            {"text": "UNITS: MILLIMETERS", "page": 3},
            {"text": "HEIGHT 1 IN", "page": 4},
            {"text": "FREE LENGTH 20 MM", "page": 4},
        ]}}
        self.assertEqual(page_length_units(payload), {2: "in", 3: "mm", 4: "conflict"})
        points = [{"field": "wire_diameter", "value": .072, "page": 2},
                  {"field": "wire_diameter", "value": 1.8, "evidence": "1.8 mm", "page": 2},
                  {"field": "free_length", "value": 25, "page": 4}]
        converted = apply_drawing_units(points, payload)
        self.assertEqual([item.get("unit") for item in converted], ["in", "mm", None])
        self.assertTrue(converted[-1]["unit_pending"])

    def test_positioned_raw_value_restores_nominal_and_tolerance_before_conversion(self):
        original = {"field": "free_length", "value": 96.012, "unit": "mm", "evidence": "3.780+/- .090 FREE LENGTH"}
        page = {"page": 1, "width": 700, "height": 900, "texts": [
            {"text": "UNITS: INCHES"}, {"text": "3.780+1-.090", "bbox": [100, 90, 180, 100]},
            {"text": "FREE LENGTH", "bbox": [100, 102, 180, 112]},
        ]}
        [source] = apply_drawing_units([original], {}, [page])
        self.assertEqual((source["value"], source["tolerance_upper"], source["tolerance_lower"]), (3.78, .09, -.09))
        self.assertEqual(source["engineering_source"]["evidence"], "3.780+1-.090")

    def test_note_ranges_and_context(self):
        self.assertEqual(metric_text("Load: 1.35 KG MIN TO 1.68 MAX AT 34.9 MM"), ("Load: 13.2389775–16.475172 N AT 34.9 mm", False))
        self.assertEqual(metric_text("Rate: 0.03 KG PER MM ±10%"), ("Rate: 0.2941995 N/mm ±10%", False))
        self.assertEqual(metric_text("Mass 1 LB; 2 IN W.C.; ASTM A313"), ("Mass 0.45359237 kg; 2 IN W.C.; ASTM A313", False))
        self.assertEqual(metric_text("2 kg"), ("2 kg", True))
        self.assertEqual(metric_text("NOTE: 1.55 DIAMETER RING GAUGE", "in"), ("NOTE: 39.37 mm DIAMETER RING GAUGE", False))

    def test_model_arithmetic_does_not_replace_a_printed_load_dimension(self):
        quote = "MAX USABLE LOAD 1.98 KG WITH SPRING COMPRESSED 78.5 MM"
        point = {"height": 17.5, "height_unit": "mm", "force": 1.98, "force_unit": "kg",
                 "height_relation": {"kind": "absolute_height", "value": 17.5, "unit": "mm",
                                     "evidence": quote + " (Calculated: 96 - 78.5 = 17.5)"}}
        self.assertIsNone(model_load_relation({"source": "qwen_vision", "evidence": quote, "value": point}))

    def test_confirmation_and_model_precision_follow_physical_values(self):
        position = {"x": .2, "y": .3, "width": .1, "height": .04}
        wire = {"value": .072, "unit": "in", "need_human_review": False,
                "confirmation_snapshot": {"kind": "parameter", "value": .072, "tolerance_upper": None, "tolerance_lower": None}}
        free = {"value": 3.78, "unit": "in", "tolerance_upper": .09, "tolerance_lower": -.09, "need_human_review": False,
                "confirmation_snapshot": {"kind": "parameter", "value": 3.78, "tolerance_upper": .09, "tolerance_lower": -.09}}
        mark = {"candidate_id": "diameter-original", "value": 1.532, "unit": "in", "page": 1, "tolerance_upper": .015,
                "diameter_role_evidence": {"observation": {"page": 1, "value": 1.532, "source": "local_ocr", "text": "Ø1.532 ± .015", "position": position}}}
        review = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {"wire_diameter": wire,
                   "free_length": free}, "diameter_role_candidates": [mark]}
        metric = deepcopy(review)
        metric_review(metric)
        self.assertEqual(metric["spring_parameters"]["wire_diameter"]["confirmation_snapshot"]["value"], 1.8288)
        self.assertEqual(metric["spring_parameters"]["free_length"]["tolerance_upper"], 2.286)
        self.assertEqual(metric["diameter_role_candidates"][0]["candidate_id"], "diameter-original")
        self.assertEqual(original_observation(metric["diameter_role_candidates"][0])["value"], 1.532)
        canonical = deepcopy(metric)
        metric_review(metric)
        self.assertEqual(metric, canonical)
        package = build_generation_parameter_package(review)
        self.assertEqual(package["solidworks_preview"]["modelParameters"]["线径"], 1.8288)
        self.assertEqual(package["solidworks_preview"]["modelParameters"]["自由高度"], 96.012)
        self.assertEqual(review["spring_parameters"]["free_length"]["value"], 3.78)
        raw_design = {"wire_diameter": wire, "free_length": free, "mean_diameter": {"value": 1.46, "unit": "in"},
                      "material": {"value": "SUS304"}, "active_coils": {"value": 7.5, "unit": "turns"}}
        metric_design = {"spring_parameters": deepcopy(raw_design)}
        metric_review(metric_design)
        raw_results = calculate_design_checks(raw_design)["metrics"]
        metric_results = calculate_design_checks(metric_design["spring_parameters"])["metrics"]
        for field in ("spring_index", "slenderness_ratio", "theoretical_spring_rate"):
            self.assertAlmostEqual(raw_results[field]["value"], metric_results[field]["value"], places=8)


if __name__ == "__main__":
    unittest.main()
