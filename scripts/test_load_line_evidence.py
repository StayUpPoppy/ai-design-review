"""Offline regression for the deployed OpenCV return shape and optional-evidence failures."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path.cwd() if __file__ == "<stdin>" else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

import cv2
import numpy as np
from PIL import Image
from ai_design_review import load_point_evidence as evidence
from ai_design_review.workflow import DrawingReviewWorkflow


class LoadLineEvidenceTests(unittest.TestCase):
    def test_opencv_shapes_and_real_detection(self):
        rows=np.array([[5,20,95,20],[50,5,50,95],[5,5,95,95]],dtype=np.int32)
        expected=rows[:2].astype(float).tolist()
        for found in (rows,rows.reshape(-1,1,4),rows[:1].reshape(4)):
            with self.subTest(shape=found.shape):
                self.assertEqual(evidence.axis_aligned_lines(found),expected if found.ndim!=1 else expected[:1])
        for empty in (None,[],np.empty((0,4)),np.empty((0,1,4))):
            self.assertEqual(evidence.axis_aligned_lines(empty),[])
        self.assertEqual(evidence.axis_aligned_lines([[0,0,float("nan"),0],[1,2,8,2]]),[[1.,2.,8.,2.]])
        for malformed in (np.int32(3),np.ones((2,3))):
            with self.assertRaises(ValueError):evidence.axis_aligned_lines(malformed)
        mask=np.zeros((100,100),np.uint8)
        mask[20,5:95]=255
        mask[5:95,50]=255
        detected=cv2.HoughLinesP(mask,1,np.pi/180,30,minLineLength=20,maxLineGap=5)
        self.assertTrue(evidence.axis_aligned_lines(detected),"Use the actual installed OpenCV, not only mocked rows")

    def test_raster_failure_retains_force_without_certifying_height(self):
        document={"source_document_id":"line-test","pages":[{"page":1,"width":200,"height":200}]}
        blocks=[{"page":1,"text":"P1=100N±5N","position":{"x":.1,"y":.1,"width":.5,"height":.06}}]
        candidates=[{"field":field,"value":value,"unit":unit,"source":"qwen_vision","confidence":.9}
                    for field,value,unit in (("spring_type","compression_spring",None),("wire_diameter",1,"mm"),("mean_diameter",10,"mm"),("free_length",100,"mm"))]
        candidates.append({"field":"load_point","source":"qwen_vision","confidence":.9,"page":1,"value":{
            "label":"P1","force":100,"force_unit":"N","height":7.58,"height_unit":"mm",
            "height_relation":{"kind":"unknown","mode":"automatic","verified":False,"value":7.58,"unit":"mm"}}})
        with tempfile.TemporaryDirectory(prefix="load-line-") as directory:
            job=Path(directory)
            (job/"inputs").mkdir();(job/"pages").mkdir()
            source=job/"inputs/source.png"
            Image.new("RGB",(200,200),"white").save(source)
            Image.new("RGB",(200,200),"white").save(job/"pages/page-1.png")
            rules=json.loads((ROOT/"config/factory_rules.json").read_text(encoding="utf-8"))
            with patch("ai_design_review.drawing_annotations.annotation_source",return_value=(document,source)),\
                 patch("ai_design_review.drawing_annotations.ocr_blocks",return_value=blocks),\
                 patch.object(cv2,"HoughLinesP") as hough:
                for shape in ((1,4),(1,1,4)):
                    hough.return_value=np.array([10,30,180,30]).reshape(shape)
                    pages=evidence.raster_pages(job,{})
                    self.assertEqual(len(pages[0]["lines"]),1)
                # Unexpected rows and detector exceptions both preserve OCR text/forces.
                for invalid in (np.ones((1,3)),IndexError("invalid index to scalar variable.")):
                    hough.side_effect=invalid if isinstance(invalid,Exception) else None
                    hough.return_value=invalid
                    warnings=[]
                    with self.assertLogs(evidence.LOGGER,level="WARNING"):
                        grounded=evidence.ground_job_candidates(job,candidates,{},warnings=warnings)
                    self.assertTrue(warnings)
                    review=DrawingReviewWorkflow(rules).run(str(source),grounded,run_standardization=False)
                    point=review["spring_parameters"]["load_points"][0]
                    self.assertEqual(point["force"],100)
                    self.assertEqual(point["load_tolerance_upper"],5)
                    self.assertIsNone(point["height"],"Failure must not certify model-computed/unknown height")
                    self.assertTrue(point["need_human_review"])
                    with self.assertLogs(evidence.LOGGER,level="WARNING"):
                        evidence.reconcile_load_points(review,job)
                    self.assertFalse((job/"load_point_evidence.json").exists(),"Transient verification failure must not poison the cache")
            with patch.object(evidence,"raster_pages",side_effect=IndexError("bad OCR input")),self.assertLogs(evidence.LOGGER,level="WARNING"):
                warnings=[]
                self.assertIs(evidence.ground_job_candidates(job,candidates,{},warnings=warnings),candidates)
                before=copy.deepcopy(review)
                evidence.reconcile_load_points(review,job)
                self.assertEqual(review,before,"Failed optional repair must not partially mutate saved data")
            self.assertTrue(warnings)
            pdf=job/"test.pdf";pdf.write_bytes(b"test")
            with patch.object(evidence,"original_points",side_effect=IndexError("bad PDF input")),self.assertLogs(evidence.LOGGER,level="WARNING"):
                self.assertIs(evidence.ground_candidates(candidates,pdf),candidates)


if __name__=="__main__":
    print(f"Testing actual OpenCV {cv2.__version__}",flush=True)
    unittest.main()
