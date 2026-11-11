"""Offline geometry/provenance regressions; no recognition or SW requests."""
import unittest
from copy import deepcopy

import cv2
import numpy as np

from ai_design_review.diameter_evidence import CANDIDATE, INFERENCE, resolve_diameter_roles
from ai_design_review.generation_contract import apply_generation_defaults
from ai_design_review.standardizers.calculation_state import parameter_current
from ai_design_review.standardizers.diameters import calculate_compression_diameter_completion
from ai_design_review.standardizers.design_checks import calculate_design_checks


def simplified(endpoints=(100, 300), *, nominal=47, centers=True, turns=4, rotate=False):
    mask = np.zeros((400, 600), np.uint8)
    for index in range(turns):
        x = 100+index*65
        cv2.ellipse(mask, (x, 100), (14, 14), 0, 180, 360, 255, 2)
        cv2.ellipse(mask, (x+25, 300), (14, 14), 0, 0, 180, 255, 2)
        cv2.line(mask, (x-14, 100), (x+11, 300), 255, 2)
        cv2.line(mask, (x+14, 100), (x+39, 300), 255, 2)
    a,b=endpoints
    guide_start=70 if centers else 350
    lines = [[400,a,400,(a+b)/2-5], [400,(a+b)/2+5,400,b], [guide_start,a,402,a], [guide_start,b,402,b]]
    if centers:
        for y in (100,300):
            for x in range(80, 340, 30):
                cv2.line(mask,(x,y),(x+18,y),255,1)
                lines.append([x,y,x+18,y])
    box=[380,180,395,220]
    if rotate:
        mask=mask.T.copy()
        lines=[[y,x,yy,xx] for x,y,xx,yy in lines]
        box=[box[1],box[0],box[3],box[2]]
    h,w=mask.shape
    return {"page":1,"width":w,"height":h,"source":"local_ocr","source_document_id":"synthetic",
            "texts":[{"text":f"Φ{nominal}","bbox":box}],"lines":lines,"wire_sections":[],
            "diameter_raster":(mask,1),"epsilon":.8}


def claim(value=47, **changes):
    return {"field":"outer_diameter","value":value,"unit":"mm","page":1,"source":"qwen_vision",
            "evidence":f"图中标注Φ{value}",**changes}


class SimplifiedDiameterTests(unittest.TestCase):
    def test_three_roles_and_transposed_view(self):
        for field, endpoints in [("mean_diameter",(100,300)),("inner_diameter",(114,286)),("outer_diameter",(86,314))]:
            for rotate in (False,True):
                with self.subTest(field=field,rotate=rotate):
                    record,=resolve_diameter_roles([claim()], [simplified(endpoints,rotate=rotate)])
                    self.assertEqual(record["field"],field)
                    self.assertEqual(record["diameter_role_evidence"]["observation"]["geometry"][0]["method"],"repeated_coil_arcs")
                    self.assertTrue(record["need_human_review"])

    def test_centerline_alone_and_one_turn_do_not_verify_mean(self):
        no_coils=simplified();no_coils["diameter_raster"][0][:]=0
        disconnected=simplified();mask=disconnected['diameter_raster'][0];mask[:]=0
        for x in (100,165,230,295):
            cv2.ellipse(mask,(x,100),(14,14),0,180,360,255,2)
            cv2.ellipse(mask,(x,300),(14,14),0,0,180,255,2)
        for page in [simplified(turns=1),simplified(centers=False),no_coils,disconnected]:
            result,=resolve_diameter_roles([claim()], [page])
            self.assertNotEqual(result["field"],"mean_diameter")

    def test_mixed_model_explanation_keeps_original_but_not_derived_values(self):
        direct=claim(28,evidence="图中标注φ28，结合线径2推算外径约28")
        inferred=claim(26,field="mean_diameter",evidence="由外径28减线径2推算，原图未标注中径")
        page={"page":1,"width":400,"height":400,"lines":[],"texts":[{"text":"Φ28","bbox":[32,170,46,220]}]}
        records=resolve_diameter_roles([direct,inferred],[page])
        self.assertEqual([r["field"] for r in records],[CANDIDATE,INFERENCE])
        self.assertEqual(records[0]["value"],28)
        self.assertEqual(records[1]["value"]["value"],26)
        self.assertEqual(records[0]["evidence"],"Φ28")
        inferred['evidence']='由外径28减线径2推算中径26，图中未标注Φ26'
        self.assertEqual(resolve_diameter_roles([inferred])[0]['field'],INFERENCE)

    def test_defaults_do_not_supply_missing_geometry_or_formula_inputs(self):
        review={"drawing_summary":{"spring_type":"compression_spring"},"spring_parameters":{}}
        apply_generation_defaults(review)
        self.assertNotIn("mean_diameter",review["spring_parameters"])
        params={"mean_diameter":{"value":23,"unit":"mm","source":["solidworks_protocol_default"],"need_human_review":True},
                "wire_diameter":{"value":2,"unit":"mm"}}
        self.assertFalse(parameter_current(params,"mean_diameter"))
        self.assertEqual(calculate_compression_diameter_completion(params),{})
        params["outer_diameter"]={"value":25,"unit":"mm","source":["formula_calculation"],"source_fields":["mean_diameter","wire_diameter"]}
        self.assertFalse(parameter_current(params,"outer_diameter"))
        params["mean_diameter"]["need_human_review"]=False
        self.assertTrue(parameter_current(params,"mean_diameter"))

    def test_wrong_end_pair_and_region_do_not_borrow_arcs(self):
        record,=resolve_diameter_roles([claim()],[simplified((100,286))])
        self.assertEqual(record["field"],CANDIDATE)
        region={"x":.65,"y":0,"width":.35,"height":1,"page":1}
        record,=resolve_diameter_roles([claim()],[simplified()],region=region)
        self.assertEqual(record["field"],INFERENCE)

    def test_same_view_dimensions_are_cross_checked_but_not_solved_by_numbers(self):
        p=simplified()
        p["lines"].extend([[435,114,435,195],[435,205,435,286],[70,114,437,114],[70,286,437,286]])
        p["texts"].append({"text":"Φ41","bbox":[415,180,430,220]})
        records=resolve_diameter_roles([claim(),claim(41),{"field":"wire_diameter","value":7,"unit":"mm"}], [p])
        self.assertEqual([r["field"] for r in records if r.get("candidate_id")],[CANDIDATE,CANDIDATE])
        self.assertTrue(all('关系不一致' in r['reason'] for r in records if r.get('candidate_id')))

    def test_original_role_is_not_replaced_by_later_geometry(self):
        original,=resolve_diameter_roles([claim()],[simplified()])
        snapshot=deepcopy(original)
        self.assertEqual(resolve_diameter_roles([original],[simplified((114,286))]),[snapshot])

    def test_four_quarter_turns(self):
        for turns in range(4):
            page=simplified()
            for _ in range(turns):
                width=page['width']
                page['lines']=[[y,width-1-x,yy,width-1-xx] for x,y,xx,yy in page['lines']]
                x,y,xx,yy=page['texts'][0]['bbox']
                page['texts'][0]['bbox']=[y,width-1-xx,yy,width-1-x]
                page['width'],page['height']=page['height'],page['width']
                page['diameter_raster']=(np.rot90(page['diameter_raster'][0]).copy(),1)
            self.assertEqual(resolve_diameter_roles([claim()],[page])[0]['field'],'mean_diameter',turns)


if __name__ == "__main__":
    unittest.main()
