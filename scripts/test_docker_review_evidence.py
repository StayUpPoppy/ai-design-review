"""Replay copied Docker artifacts with local evidence only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path.cwd()
sys.path.insert(0,str(ROOT/"src"))
from ai_design_review.diameter_evidence import pending_roles, public_roles, reconcile_diameter_review
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.load_point_evidence import ground_job_candidates, reconcile_load_points
from ai_design_review.workflow import DrawingReviewWorkflow

CASES=[
    ("10fb2c6332635f855929e668",83300,225,None),
    ("da9f62cc253f623aceb80cf2",9384,199,None),
    ("02db62416195006ea923889c",3881,104,2),
    ("71dc3e0a1975e859a6e78172",29500,225,None),
    ("f9c345c3316d82ebf003c02a",79100,225,None),
]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_point(review, force, height, tolerance):
    points=review["spring_parameters"]["load_points"]
    assert len(points)==1,points
    point=points[0]
    assert (point["force"],point["height"],point.get("height_tolerance_upper"),point.get("height_tolerance_lower"))==(
        force,height,tolerance,-tolerance if tolerance is not None else None),point
    assert point["need_human_review"] is True
    if tolerance is not None:
        assert point["height_relation"]["verified"],point
    return point


def check_diameters(review):
    assert all(p["value"]!=175 for p in pending_roles(review))
    visible=deepcopy(review)
    public_roles(visible)
    assert all(len(str(p.get("evidence") or ""))<=96 for p in visible.get("diameter_role_candidates",[]))
    matches=[p for p in visible.get("diameter_role_candidates",[]) if p["value"]==111]
    matches.extend(p for field,p in visible["spring_parameters"].items()
                   if field in {"inner_diameter","mean_diameter","outer_diameter"} and p.get("value")==111)
    assert any((p.get("tolerance_upper"),p.get("tolerance_lower"))==(2,0) for p in matches),matches


def replay(root):
    import cv2
    cv2.setNumThreads(1)
    workflow=DrawingReviewWorkflow(read(ROOT/"config/factory_rules.json"))
    # The cached OCR was produced by the actual Docker recognition jobs.
    with patch("ai_design_review.annotation_ocr.local_ocr_blocks",return_value=([],[],{})):
        for job_id,force,height,tolerance in CASES:
            job=root/job_id
            model=read(job/"qwen_vision_raw.json")["parsed"]
            candidates=qwen_payload_to_candidates(model,require_height_relation=True)
            raw=read(job/"candidates.json").get("raw_payloads",{})
            fresh=workflow.run(None,ground_job_candidates(job,candidates,raw),run_standardization=False)
            point=check_point(fresh,force,height,tolerance)
            old=read(job/"review.json")
            old_id=old["spring_parameters"]["load_points"][0]["load_point_id"]
            reconcile_load_points(old,job)
            assert check_point(old,force,height,tolerance)["load_point_id"]==old_id
            if force==79100:
                reconcile_diameter_review(old,job)
                check_diameters(fresh)
                check_diameters(old)
            print(f"{force} N -> {height} mm, tolerance {tolerance}, {point['height_relation']['status']}",flush=True)


if __name__=="__main__":
    replay(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/"outputs/docker-evidence-replay")
