"""Direct working heights, deflections and their old-record recovery, without cloud calls."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path.cwd() if __file__=="<stdin>" else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from PIL import Image
from ai_design_review import load_point_evidence as evidence
from ai_design_review.fusion import fuse_candidates
from ai_design_review.load_height_relations import refresh_load_heights
from ai_design_review.engines.ocr_adapter import _extract_load_points
from ai_design_review.workflow import DrawingReviewWorkflow


def direct_page():
    return {"page":1,"width":300,"height":220,"lines":[],"texts":[
        {"text":"F1=11.9N±10%","bbox":[160,10,260,20]},
        {"text":"F2=15.3N±10%","bbox":[100,40,200,50]},
        {"text":"4.力值要求：H1压缩到11.414mm/F1=11.9N±10%","bbox":[10,150,290,160]},
        {"text":"H2压缩到9.474mm/F2=15.3N±10%（参考）","bbox":[10,170,290,180]}]}


def review_for(points,h0=15):
    review={"drawing_summary":{"spring_type":"compression_spring"},"spring_parameters":{
        "free_length":{"value":h0,"unit":"mm"},"load_points":points}}
    for index,point in enumerate(points):point.setdefault("load_point_id",f"p{index}")
    refresh_load_heights(review)
    return review


class DirectHeightTests(unittest.TestCase):
    def test_explicit_wording_and_boundaries(self):
        for text in ("H1=25mm F1=100N","H1压缩到25mm/F1=100N","H1壓縮至25mm/F1=100N","H1 25mm F1=100N","工作高度为25mm，F1=100N"):
            with self.subTest(text=text):
                self.assertEqual(evidence.explicit_load_heights(text,"F1")[0]["value"],25)
                point=_extract_load_points(text,{"source":"rapidocr","page":1})[0]["value"]
                self.assertEqual(point["height"],25)
                self.assertTrue(point["height_relation"]["verified"])
        for text in ("压缩量H1=10mm/F1=100N","追加行程H1=10mm/F1=100N","H1压缩了10mm/F1=100N","H11=10mm/F1=100N","H1=25mm/P1=100N"):
            with self.subTest(text=text):self.assertEqual(evidence.explicit_load_heights(text,"F1"),[])
        self.assertTrue(evidence.explicit_load_heights("H2压缩到9.474mm/F2=15.3N±10%（参考）","F2")[0]["reference_only"])

    def test_duplicate_ocr_and_conflicting_values(self):
        page=direct_page()
        for item in list(page["texts"]):
            page["texts"].append({**item,"bbox":[x+.5 for x in item["bbox"]]})
        points=evidence.extract_page_points(page)
        review_for(points)
        self.assertEqual({p["label"]:p["height"] for p in points},{"F1":11.414,"F2":9.474})
        self.assertEqual(len(points),2)
        page["texts"].append({"text":"H1压缩到12mm/F1=11.9N","bbox":[10,190,290,200]})
        points=evidence.extract_page_points(page)
        review_for(points)
        self.assertIsNone(next(p for p in points if p["label"]=="F1")["height"])
        self.assertTrue(next(p for p in points if p["label"]=="F1")["load_height_conflict"])
        points=evidence.extract_page_points(direct_page(),region={"page":1,"x":.5,"y":0,"width":.5,"height":.5})
        self.assertTrue(points)
        self.assertTrue(all(not p["height_relation"].get("verified") for p in points),"Do not borrow the text outside this specification region")

    def test_verified_ocr_beats_model_relation(self):
        model={"field":"load_point","source":"qwen_vision","confidence":1.,"page":1,"value":{
            "label":"F1","height":11.414,"height_unit":"mm","force":11.9,"force_unit":"N",
            "height_relation":{"kind":"absolute_height","value":11.414,"unit":"mm","verified":False}}}
        ocr=_extract_load_points("H1压缩到11.414mm/F1=11.9N±10%",{"source":"rapidocr","page":1})[0]
        for high in (model,{**model,"value":{**model["value"],"height_relation":{"kind":"absolute_height","value":99,"unit":"mm","verified":True}}}):
            fused=fuse_candidates([high,ocr])["load_points"][0]["value"]
            self.assertTrue(fused["height_relation"]["verified"])
            review_for([fused])
            self.assertEqual(fused["height"],11.414)
        unknown=copy.deepcopy(model);unknown["value"]["height_relation"]["verified"]=True
        fused=fuse_candidates([unknown])["load_points"][0]["value"]
        review_for([fused])
        self.assertIsNone(fused["height"],"A model cannot certify its own direct height")

    def test_direct_height_and_incremental_stroke_in_one_chain(self):
        page={"page":1,"width":350,"height":220,"texts":[
            {"text":"H0=133.35","bbox":[60,135,130,145]},
            {"text":"P1=1109.83N","bbox":[148,40,240,50]},
            {"text":"P2=5550.05±221.96N","bbox":[98,20,240,30]},
            {"text":"(7.58)","bbox":[160,112,195,122]},
            {"text":"30.33","bbox":[108,112,142,122]},
            {"text":"H1=125.77mm/P1=1109.83N","bbox":[5,180,230,190]}],
            "lines":[[5,150,195,150],[0,70,0,160],[200,70,200,160],
                     [150,53,150,136],[100,33,100,136],[50,70,200,70],
                     [155,130,195,130],[105,130,145,130]]}
        points=evidence.extract_page_points(page)
        review_for(points,133.35)
        self.assertEqual({p["label"]:p["height"] for p in points},{"P1":125.77,"P2":95.44})
        self.assertEqual(points[0]["height_relation"]["kind"],"absolute_height")
        self.assertEqual(points[1]["height_relation"]["kind"],"incremental_deflection")

    def test_old_cache_recovery_and_manual_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            job=Path(directory);(job/"inputs").mkdir()
            Image.new("RGB",(100,100),"white").save(job/"inputs/source.png")
            initial={"drawing_summary":{"spring_type":"compression_spring"},"spring_parameters":{"free_length":{"value":15,"unit":"mm"},"load_points":[
                {"load_point_id":label,"label":label,"height":None,"height_unit":"mm","force":force,"force_unit":"N","source":["qwen_vision"],"need_human_review":True,
                 "height_relation":{"kind":"absolute_height","mode":"automatic","value":value,"unit":"mm","verified":False}}
                for label,value,force in (("F1",11.414,11.9),("F2",9.474,15.3))]}}
            with patch.object(evidence,"raster_pages",return_value=[direct_page()]) as raster:
                for mode in ("automatic","manual","confirmed","unknown"):
                    (job/"load_point_evidence.json").write_text(json.dumps({"version":"load-height/v1","fingerprint":"old","points":[]}),encoding="utf-8")
                    review=copy.deepcopy(initial)
                    first=review["spring_parameters"]["load_points"][0]
                    if mode=="manual":first["height_relation"]["mode"]="manual"
                    if mode=="confirmed":first.update(height=12,need_human_review=False)
                    if mode=="unknown":first.update(height=12,source=[])
                    evidence.reconcile_load_points(review,job)
                    points=review["spring_parameters"]["load_points"]
                    self.assertEqual(points[1]["height"],9.474)
                    self.assertEqual(points[0]["height"],11.414 if mode=="automatic" else 12 if mode in ("confirmed","unknown") else None)
                    self.assertEqual(points[0]["load_point_id"],"F1")
                self.assertEqual(raster.call_count,4)
                # A PDF with only force text must not suppress the better cached OCR height.
                base=evidence.extract_page_points({**direct_page(),"texts":direct_page()["texts"][:2]})
                merged=evidence._merge_original_points(base,evidence.extract_page_points(direct_page()))
                review_for(merged)
                self.assertEqual({p["label"]:p["height"] for p in merged},{"F1":11.414,"F2":9.474})

    def test_saved_diagram_fixtures(self):
        path=Path(os.getenv("LOAD_HEIGHT_DIRECT_FIXTURES",str(ROOT/"outputs/load-height-direct-fixtures.jsonl")))
        if not path.is_file():self.skipTest("Optional locally saved diagrams are unavailable")
        expected={"46b6db7bc555":{"F1":11.414,"F2":9.474},"7b4daa4ef73b":{"F1":14.284,"F2":12.284},
                  "b7a16286339f":{"F1":21.15,"F2":9.668},"83214107923f":{"P1":125.77,"P2":95.44}}
        rules=json.loads((ROOT/"config/factory_rules.json").read_text(encoding="utf-8"))
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            data=json.loads(line)
            with self.subTest(job=data["job_id"]):
                points=[p for page in data["pages"] for p in evidence.extract_page_points(page)]
                review_for(points,data["review"]["spring_parameters"]["free_length"]["value"])
                self.assertEqual({p["label"]:p["height"] for p in points},expected[data["job_id"]])
                # New-upload fusion, with higher-confidence but unverified model values.
                points=[p for page in data["pages"] for p in evidence.extract_page_points(page)]
                fields=[{"field":field,"value":value,"unit":unit,"source":"qwen_vision","confidence":1.} for field,value,unit in
                        (("spring_type","compression_spring",None),("free_length",data["review"]["spring_parameters"]["free_length"]["value"],"mm"),("wire_diameter",1,"mm"),("mean_diameter",10,"mm"))]
                model=[{"field":"load_point","value":p,"source":"qwen_vision","confidence":1.,"page":p.get("page",1)} for p in data["review"]["spring_parameters"]["load_points"]]
                review=DrawingReviewWorkflow(rules).run(None,[*fields,*model,*evidence._point_candidates(points)],run_standardization=False)
                self.assertEqual({p["label"]:p["height"] for p in review["spring_parameters"]["load_points"]},expected[data["job_id"]])

    def test_direct_api_save_confirm_and_export(self):
        from fastapi.testclient import TestClient
        from ai_design_review import api
        from ai_design_review.review_persistence import ReviewPersistence
        from ai_design_review.generation_readiness import build_generation_parameter_package
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job=root/"direct";(job/"inputs").mkdir(parents=True)
            Image.new("RGB",(100,100),"white").save(job/"inputs/source.png")
            fixture=json.loads((ROOT/"data/test/compression_design_checks.json").read_text(encoding="utf-8"))["base"]
            fixture["spring_parameters"]["free_length"].update(value=15,unit="mm")
            fixture["spring_parameters"]["load_points"]=[{
                "load_point_id":label,"label":label,"height":None,"height_unit":"mm","force":force,"force_unit":"N",
                "source":["qwen_vision"],"need_human_review":True,"height_relation":{"kind":"absolute_height","value":value,"unit":"mm","mode":"automatic","verified":False}}
                for label,value,force in (("F1",11.414,11.9),("F2",9.474,15.3))]
            fixture["manual_confirmations"]={}
            repo=ReviewPersistence(f"sqlite+pysqlite:///{root/'reviews.db'}");repo.create_schema_for_testing()
            repo.create_review("direct",fixture,file_info={"kind":"image"},artifact_dir=str(job),owner={"user_id":"direct-height-test"})
            try:
                with patch.dict(os.environ,{"AI_REVIEW_IDENTITY_MODE":"mock","AI_REVIEW_MOCK_USER_ID":"direct-height-test"}),\
                     patch.object(api,"API_RUN_ROOT",root),patch.object(api,"REVIEW_PERSISTENCE",repo),\
                     patch.object(api,"verify_review_roughness",lambda *a,**k:None),\
                     patch.object(evidence,"raster_pages",return_value=[direct_page()]),TestClient(api.app) as client:
                    current=client.get("/api/reviews/direct").json()
                    self.assertEqual([p["height"] for p in current["spring_parameters"]["load_points"]],[11.414,9.474])
                    self.assertIsNone(repo.get_review("direct")["review"]["spring_parameters"]["load_points"][0]["height"])
                    result=client.patch("/api/reviews/direct",json={"review":current,"expected_revision":1})
                    self.assertEqual(result.status_code,200,result.text)
                    revision=result.json()["review_revision"]
                    current=client.get("/api/reviews/direct").json()
                    self.assertFalse(current.get("load_height_adjustment",{}).get("pending_save"))
                    for point in current["spring_parameters"]["load_points"]:point["need_human_review"]=False
                    result=client.patch("/api/reviews/direct",json={"review":current,"expected_revision":revision})
                    self.assertEqual(result.status_code,200,result.text)
                    revision=result.json()["review_revision"]
                    current=client.get("/api/reviews/direct").json()
                    package=build_generation_parameter_package(current)
                    self.assertEqual({p["label"]:p["height"]["value"] for p in package["generation_parameters"]["load_points"]},{"F1":11.414,"F2":9.474})
                    current["spring_parameters"]["free_length"]["value"]=18
                    result=client.patch("/api/reviews/direct",json={"review":current,"expected_revision":revision})
                    self.assertEqual(result.status_code,200,result.text)
                    current=client.get("/api/reviews/direct").json()
                    self.assertEqual([p["height"] for p in current["spring_parameters"]["load_points"]],[11.414,9.474])
                    self.assertTrue(all(p["need_human_review"] is False for p in current["spring_parameters"]["load_points"]),"Independent direct heights stay confirmed when H0 changes")
            finally:repo.dispose()


if __name__=="__main__":unittest.main()
