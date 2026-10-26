"""Regression: timed-out multi-spec recognition must not succeed via single OCR."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, MagicMock

import httpx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_multi_spec import api, OWNER
from test_multi_spec_pipeline import table_response
from ai_design_review import recognition_worker as worker
from ai_design_review.engines.qwen_vision_adapter import QwenVisionEngine
from ai_design_review.multi_spec import MultiSpecError, local_multi_spec_hint, parse_multi_spec
from ai_design_review.review_persistence import ReviewPersistence


def block(text, x=100, y=20, page=1):
    return {"text":text,"page":page,"position":{"x":x,"y":y,"width":200,"height":20,"coordinate_type":"pixel"}}


def table_ocr():
    return {"texts":[block("规格"),block("总圈数"),*[block(f"Φ{10+i}xΦ75x{260+i}±4.5",y=100+i*40) for i in range(13)]],
            "candidates":[{"field":"spring_type","value":"压缩弹簧","feature_type":"note","source":"rapidocr"},
                {"field":"wire_diameter","value":3,"unit":"mm","feature_type":"dimension","source":"rapidocr"},
                {"field":"free_length","value":100,"unit":"mm","feature_type":"dimension","source":"rapidocr"}]}


def main():
    with patch.dict(os.environ,{},clear=True): assert QwenVisionEngine(api_key="offline").timeout_seconds==360
    with patch.dict(os.environ,{"QWEN_TIMEOUT_SECONDS":"900"},clear=True): assert QwenVisionEngine(api_key="offline").timeout_seconds==900
    with patch.dict(os.environ,{"QWEN_VISION_TIMEOUT_SECONDS":"75","QWEN_TIMEOUT_SECONDS":"180"},clear=True):
        assert QwenVisionEngine(api_key="offline").timeout_seconds==75
        assert QwenVisionEngine(api_key="offline",timeout_seconds=12).timeout_seconds==12
    assert local_multi_spec_hint({"ocr":table_ocr()},[])["observed_count"]==13
    one={"texts":[block("规格"),block("总圈数"),block("Φ10x75x260",y=100),block("10×75×260",y=100.1)]}
    assert local_multi_spec_hint({"ocr":one},[]) is None, "Duplicate OCR is not a second spec"
    single={"texts":[block("规格"),block("总圈数"),block("10x75x260",y=100),block("载荷 高度 F1 F2 Fb",y=140)]}
    assert local_multi_spec_hint({"ocr":single},[]) is None
    pages={"texts":[block("规格",page=page) for page in (1,2)]+[block("总圈数",page=page) for page in (1,2)]+[block(f"{10+page}x75x260",y=100,page=page) for page in (1,2)]}
    assert local_multi_spec_hint({"ocr":pages},[]) is None
    repeated={"texts":[block(label,x=x,y=y) for x in (100,500,900) for y,label in enumerate(["线径d","中径D","自由高度H0","总圈数n1"])]}
    assert local_multi_spec_hint({"ocr":repeated},[])["kind"]=="blocks"
    assert parse_multi_spec({"notes":"仅包含1种规格"}) is None
    try: parse_multi_spec({"notes":"该表包含13种规格，需按行提取。"})
    except MultiSpecError: pass
    else: raise AssertionError("Declared multi cannot become legacy single")
    snapshot=Path("outputs/multi-spec-timeout-qa/ocr_snapshot.json")
    actual=json.loads(snapshot.read_text(encoding="utf-8-sig")) if snapshot.exists() else table_ocr()
    actual_hint=local_multi_spec_hint({"rapidocr_fallback":actual},[])
    assert actual_hint and actual_hint["observed_count"]==13,actual_hint

    old_repo,old_root=api.REVIEW_PERSISTENCE,api.API_RUN_ROOT
    try:
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); url=f"sqlite+pysqlite:///{root/'timeout.db'}"
            repo=ReviewPersistence(url); repo._engine.dispose();repo._engine=create_engine(url,poolclass=NullPool);repo._session_factory=sessionmaker(repo._engine,expire_on_commit=False);repo.create_schema_for_testing()
            api.REVIEW_PERSISTENCE=repo;api.API_RUN_ROOT=root/'runs';api.API_RUN_ROOT.mkdir()
            png=io.BytesIO();Image.new("RGB",(50,50),"white").save(png,format="PNG")
            with patch.object(worker,"REVIEW_PERSISTENCE",repo),patch.object(worker,"API_RUN_ROOT",api.API_RUN_ROOT),patch.object(worker,"run_recognition_job_record",api.run_recognition_job_record),patch.object(worker.LOGGER,"exception"), TestClient(api.app) as client:
                runner=worker.RecognitionWorker()
                with patch("ai_design_review.engines.qwen_vision_adapter._configured",return_value=True),patch.object(QwenVisionEngine,"_call_qwen",side_effect=httpx.ReadTimeout("offline read timeout")) as call,patch.object(api.UnifiedOcrEngine,"extract_with_raw",return_value=deepcopy(actual)) as ocr:
                    receipt=client.post("/api/reviews",files={"drawing":("multi.png",png.getvalue(),"image/png")},data={"use_qwen":"true","use_ocr":"false"});assert receipt.status_code==202,receipt.text
                    job_id=receipt.json()["job_id"]; job=repo.claim_next_recognition_job(runner.worker_id);runner._process_job(job)
                    status=client.get(f"/api/reviews/{job_id}/recognition-status").json()["recognition"]
                    assert status["status"]=="failed",status
                    assert "Qwen请求超时" in status["error_message"]
                    assert repo.get_review(job_id,owner_user_id=OWNER["user_id"]) is None
                    assert call.call_count==1 and ocr.call_count==1
                    assert (api.API_RUN_ROOT/job_id/"multi_spec_diagnostics.json").exists()
                    assert client.get(f"/api/reviews/{job_id}").status_code==409
                # User explicitly retries: same order, one new mocked file call,
                # complete 13-spec source rather than an automatic extra request.
                assert client.post(f"/api/reviews/{job_id}/retry").status_code==202
                response={"choices":[{"finish_reason":"stop","message":{"content":json.dumps(table_response(),ensure_ascii=False)}}]}
                with patch("ai_design_review.engines.qwen_vision_adapter._configured",return_value=True),patch.object(QwenVisionEngine,"_call_qwen",return_value=response) as call:
                    runner._process_job(repo.claim_next_recognition_job(runner.worker_id))
                    assert call.call_count==1
                source=client.get(f"/api/reviews/{job_id}").json();assert source["record_kind"]=="source" and len(source["multi_spec"]["variants"])==13
                assert client.get(f"/api/reviews/{job_id}/recognition-status").json()["recognition"]["status"]=="completed"
                # Ordinary single-spring OCR fallback is unchanged.
                with patch("ai_design_review.engines.qwen_vision_adapter._configured",return_value=True),patch.object(QwenVisionEngine,"_call_qwen",side_effect=httpx.ReadTimeout("offline")),patch.object(api.UnifiedOcrEngine,"extract_with_raw",return_value={**single,"candidates":table_ocr()["candidates"]}),patch.object(api,"verify_job_candidates",side_effect=lambda directory,candidates,*a,**k:candidates):
                    receipt=client.post("/api/reviews",files={"drawing":("single.png",png.getvalue(),"image/png")},data={"use_qwen":"true","use_ocr":"false"})
                    single_id=receipt.json()["job_id"];runner._process_job(repo.claim_next_recognition_job(runner.worker_id))
                    assert client.get(f"/api/reviews/{single_id}/recognition-status").json()["recognition"]["status"]=="completed"
                    assert repo.get_review(single_id,owner_user_id=OWNER["user_id"])["record_kind"]=="single"
                # Truncated response is never fused, and raw response survives.
                response["choices"][0]["finish_reason"]="length"
                with patch.object(QwenVisionEngine,"_call_qwen",return_value=response):
                    try: QwenVisionEngine(api_key="offline",work_dir=root/"raw").extract_with_raw(root/"drawing.png",[api.API_RUN_ROOT/job_id/"pages"/"source.png"])
                    except MultiSpecError: pass
                    else: raise AssertionError("Truncation must fail")
                assert (root/"raw"/"response.json").exists()
                fake=MagicMock();fake.__enter__.return_value=fake;fake.post.return_value.status_code=200;fake.post.return_value.json.return_value={"choices":[{"message":{"content":"{}"}}]}
                with patch.dict(os.environ,{"QWEN_VISION_TIMEOUT_SECONDS":"360"}),patch("httpx.Client",return_value=fake) as ctor:
                    QwenVisionEngine(api_key="offline")._call_qwen([api.API_RUN_ROOT/job_id/"pages"/"source.png"])
                    timeout=ctor.call_args.kwargs["timeout"];assert timeout.read==360 and timeout.connect==20
    finally: api.REVIEW_PERSISTENCE,api.API_RUN_ROOT=old_repo,old_root
    print("PASS actual cached 13-row OCR replay: timeout -> failed (no merged order), explicit retry -> 13-spec source, preserved single fallback, duplicates/pages, truncation and vision timeout; no cloud calls")


if __name__=="__main__":main()
