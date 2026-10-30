from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
os.environ["AI_REVIEW_IDENTITY_MODE"]="mock"
os.environ["AI_REVIEW_MOCK_USER_ID"]="load-height-test"
from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_readiness import build_generation_parameter_package


def main():
    source=Path(os.getenv("LOAD_HEIGHT_TEST_PDF",r"C:/Users/29580/Desktop/aaa4b87f42474811b3b8000ce8fb0ea7.pdf"))
    fixture=json.loads((ROOT/"data/test/compression_design_checks.json").read_text(encoding="utf-8"))["base"]
    fixture["spring_parameters"]["free_length"].update(value=133.35,unit="mm")
    fixture["spring_parameters"]["load_points"]=[{"load_point_id":"point2","label":"P2","height":103.02,"height_unit":"mm","force":5550.05,"force_unit":"N","source":["qwen_vision"],"need_human_review":True,"page":1}]
    fixture["manual_confirmations"]={}
    with tempfile.TemporaryDirectory(prefix="load-height-api-") as directory:
        root=Path(directory);job=root/"job";(job/"inputs").mkdir(parents=True)
        if source.is_file():shutil.copyfile(source,job/"inputs/source.pdf")
        else:
            from test_load_height_relations import create_sample_pdf
            create_sample_pdf(job/"inputs/source.pdf")
        from ai_design_review.load_point_evidence import reconcile_load_points
        unknown=copy.deepcopy(fixture)
        unknown["spring_parameters"]["load_points"][0]["source"]=[]
        reconcile_load_points(unknown,job)
        protected=next(p for p in unknown["spring_parameters"]["load_points"] if p["label"]=="P2")
        assert protected["height"]==103.02 and protected.get("load_relation_candidate"),"unknown-origin legacy values require manual review"
        repo=ReviewPersistence(f"sqlite+pysqlite:///{root/'reviews.db'}");repo.create_schema_for_testing()
        repo.create_review("job",fixture,file_info={"kind":"pdf"},artifact_dir=str(job),owner={"user_id":"load-height-test"})
        before=copy.deepcopy(repo.get_review("job")["review"])
        with patch.object(api,"API_RUN_ROOT",root),patch.object(api,"REVIEW_PERSISTENCE",repo),patch.object(api,"verify_review_roughness",lambda *a,**k:None),TestClient(api.app) as client:
            response=client.get("/api/reviews/job");assert response.status_code==200,response.text
            loaded=response.json();points=loaded["spring_parameters"]["load_points"]
            assert {p["label"]:p["height"] for p in points}=={"P1":125.77,"P2":95.44},[(p["label"],p["height"],p.get("height_relation")) for p in points]
            assert repo.get_review("job")["review"]==before,"GET does not write review/confirmation state"
            assert loaded["load_height_adjustment"]["pending_save"]
            assert build_generation_parameter_package(loaded)["generation_parameters"]["load_points"]==[]
            response=client.patch("/api/reviews/job",json={"review":loaded,"expected_revision":1})
            assert response.status_code==200,response.text
            revision=response.json()["review_revision"]
            reopened=client.get("/api/reviews/job").json()
            assert not reopened.get("load_height_adjustment",{}).get("pending_save")
            assert any(e["event_type"]=="load_height_evidence_reconciled" for e in repo.list_change_events("job"))
            points=reopened["spring_parameters"]["load_points"]
            for p in points:p["need_human_review"]=False
            result=client.patch("/api/reviews/job",json={"review":reopened,"expected_revision":revision});assert result.status_code==200,result.text
            revision=result.json()["review_revision"]
            current=client.get("/api/reviews/job").json()
            assert all(p["need_human_review"] is False for p in current["spring_parameters"]["load_points"])
            package=build_generation_parameter_package(current)
            assert {p["label"]:p["height"]["value"] for p in package["generation_parameters"]["load_points"]}=={"P1":125.77,"P2":95.44}
            p2=next(p for p in package["generation_parameters"]["load_points"] if p["label"]=="P2")
            assert p2["force"]["tolerance_upper"]==221.96
            assert "height_relation" not in json.dumps(package["solidworks_preview"])
            # Changing free height recalculates automatic points and revokes confirmation.
            current["spring_parameters"]["free_length"]["value"]=140
            response=client.patch("/api/reviews/job",json={"review":current,"expected_revision":revision});assert response.status_code==200,response.text
            revision=response.json()["review_revision"]
            current=client.get("/api/reviews/job").json()
            assert {p["label"]:p["height"] for p in current["spring_parameters"]["load_points"]}=={"P1":132.42,"P2":102.09}
            assert all(p["need_human_review"] for p in current["spring_parameters"]["load_points"])
            # A manual point survives reopen; deleting the other point does not resurrect it.
            current["spring_parameters"]["load_points"]=[p for p in current["spring_parameters"]["load_points"] if p["label"]=="P1"]
            current["spring_parameters"]["load_points"][0]["height"]=120
            response=client.patch("/api/reviews/job",json={"review":current,"expected_revision":revision});assert response.status_code==200,response.text
            current=client.get("/api/reviews/job").json()
            assert len(current["spring_parameters"]["load_points"])==1
            assert current["spring_parameters"]["load_points"][0]["height"]==120
            assert current["spring_parameters"]["load_points"][0]["height_relation"]["mode"]=="manual"
            # Stale saves and a different owner cannot overwrite or read these results.
            assert client.patch("/api/reviews/job",json={"review":loaded,"expected_revision":1}).status_code==409
            with patch.dict(os.environ,{"AI_REVIEW_MOCK_USER_ID":"another-user"}):assert client.get("/api/reviews/job").status_code==404
        repo.dispose()
    print("PASS: original PDF local recovery, read-only GET, CAS repair/audit, confirm/export, dependencies, manual/delete protection and owner isolation")


if __name__=="__main__":main()
