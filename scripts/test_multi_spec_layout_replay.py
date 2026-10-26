"""Columns compatibility and explicit cached retry; no cloud/production writes."""
import asyncio
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_multi_spec import api, OWNER, fixture
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from ai_design_review import recognition_worker as worker
from ai_design_review.engines.qwen_vision_adapter import QwenVisionEngine, parse_qwen_json, _message_content
from ai_design_review.multi_spec import MULTI_SPEC_PROMPT, MultiSpecError, parse_multi_spec, source_review, child_review
from ai_design_review.multi_spec_replay import REPLAY_OPTION, prepare_retry_options, fingerprint, load_replay
from ai_design_review.review_persistence import ReviewPersistence

QA = Path("outputs/multi-spec-layout-qa")


def payload():
    value = fixture();value["layout"] = "columns"
    value["common"]["parameters"].update(value["variants"][0]["parameters"])
    value["common"]["parameters"]["solid_height"] = {"value":308,"unit":"mm"}
    for v in value["variants"]:v["parameters"] = {}
    return value


def response(value):
    return {"model":"offline-saved-qwen","choices":[{"finish_reason":"stop","message":{"content":json.dumps(value,ensure_ascii=False)}}]}


def assert_error(call, text=None):
    try: call()
    except MultiSpecError as exc:
        if text: assert text in str(exc),str(exc)
    else: raise AssertionError("Expected MultiSpecError")


def contracts():
    assert '"layout":"rows或blocks"' not in MULTI_SPEC_PROMPT
    row_example=next(line for line in MULTI_SPEC_PROMPT.splitlines() if line.startswith('{"document_mode"'))
    block_example=MULTI_SPEC_PROMPT.split("区块布局示例：",1)[1].split("。示例空字段",1)[0]
    for example in (row_example,block_example):
        p=json.loads(example);assert len(parse_multi_spec(p)["variants"])==p["spec_count"]
    original = payload()
    for layout, expected in (("columns","blocks"),(" COLUMNS ","blocks"),(" Blocks ","blocks"),(" ROWS ","rows")):
        p={**deepcopy(original),"layout":layout};before=deepcopy(p)
        multi=parse_multi_spec(p,1)
        assert multi["layout"]==expected and multi["layout_normalization"]["original"]==layout
        assert p==before and len(multi["variants"])==3
        for i,v in enumerate(multi["variants"]):
            review,_=child_review(source_review(p,multi),v,"source")
            params=review["spring_parameters"]
            assert [params[f]["value"] for f in ("wire_diameter","mean_diameter","free_length","total_coils","active_coils")]==[14,66,607,22,20]
            assert params["load_points"][0]["height"]==[460,470,493][i]
            assert params["wire_diameter"]["need_human_review"] and params["load_points"][0]["need_human_review"]
    for layout in (None,"matrix",{},True):assert_error(lambda:parse_multi_spec({**original,"layout":layout}),"布局字段不兼容")
    for change in ({"complete":False},{"spec_count":2},{"variants":[{},{}]}):
        assert_error(lambda:parse_multi_spec({**original,**change},1))
    missing=deepcopy(original)
    for v in missing["variants"]:v["region"]=None
    assert len(parse_multi_spec(missing)["variants"])==3
    badpage=deepcopy(original);badpage["variants"][0]["page"]=2
    assert_error(lambda:parse_multi_spec(badpage,1),"页码")
    assert parse_multi_spec({"document_mode":"single","layout":"columns","load_points":[{},{}]}) is None
    assert len(parse_multi_spec(fixture(13))["variants"])==13
    engine=QwenVisionEngine(api_key="")
    truncated=response(original);truncated["choices"][0]["finish_reason"]="length"
    assert_error(lambda:engine.parse_response(truncated,[],total_pages=1),"截断")
    assert_error(lambda:engine.parse_response(response(original),[],total_pages=engine.max_pages+1),"页数")


def saved_responses():
    path=QA/"saved-responses.json"
    if not path.exists():return [response(payload())]
    values=json.loads(path.read_text(encoding="utf-8-sig"));saved=[]
    evidence=Path("outputs/multi-spec-annotation-qa/saved.json")
    blocks=json.loads(evidence.read_text(encoding="utf-8-sig"))["ocr"]["blocks"] if evidence.exists() else None
    for job,raw in values.items():
        before=deepcopy(raw);decoded=QwenVisionEngine().parse_response(raw,[],total_pages=1)
        multi=decoded["multi_spec"];assert multi["layout"]=="blocks" and len(multi["variants"])==3
        for i,v in enumerate(multi["variants"]):
            review,candidates=child_review(source_review(decoded["parsed"],multi),v,"source")
            p=review["spring_parameters"]
            assert [p[k]["value"] for k in ("wire_diameter","mean_diameter","free_length","total_coils","active_coils")]==[14,66,607,22,20]
            assert v["load_points"][0]["deflection"]==[147,137,114][i]
            points=p["load_points"] or [item["original_candidate"]["value"] for item in review.get("load_point_diagnostics",[])]
            assert points[0]["height"]==[460,470,493][i]
            assert points[0]["force"]==[9698.504675,9038.742452,7521.28934][i]
            if blocks:
                from ai_design_review.drawing_annotations import locate_fields
                annotations={a["field"]:a for a in locate_fields(review,candidates,blocks)}
                for field in ("wire_diameter","mean_diameter","free_length","solid_height","total_coils","active_coils"):
                    assert len(annotations[field]["locations"])==1,(job,i,field)
                    x=annotations[field]["locations"][0]["anchor"]["x"]
                    assert v["region"]["x"]<=x<=v["region"]["x"]+v["region"]["width"]
        assert raw==before
        if decoded["parsed"]["layout"]=="columns": saved.append(raw)
    print("PASS actual two failed columns replies and prior blocks reply: three independent loads and own-region bubbles")
    return saved


def queue_tests(replies):
    old=api.REVIEW_PERSISTENCE,api.API_RUN_ROOT,api.verify_review_roughness
    try:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);url=f"sqlite+pysqlite:///{root/'layout.db'}"
            repo=ReviewPersistence(url);repo._engine.dispose();repo._engine=create_engine(url,poolclass=NullPool)
            repo._session_factory=sessionmaker(repo._engine,expire_on_commit=False);repo.create_schema_for_testing()
            api.REVIEW_PERSISTENCE,api.API_RUN_ROOT=repo,root/"runs";api.API_RUN_ROOT.mkdir()
            api.verify_review_roughness=lambda *a,**k:None
            png=io.BytesIO();Image.new("RGB",(50,50),"white").save(png,format="PNG")
            with patch.object(worker,"REVIEW_PERSISTENCE",repo),patch.object(worker,"API_RUN_ROOT",api.API_RUN_ROOT),patch.object(worker,"run_recognition_job_record",api.run_recognition_job_record),patch.object(worker.LOGGER,"exception"),patch("ai_design_review.engines.qwen_vision_adapter._configured",return_value=True),TestClient(api.app) as client:
                runner=worker.RecognitionWorker()
                def submit(name="blocks.png",content=None):
                    r=client.post("/api/reviews",files={"drawing":(name,png.getvalue() if content is None else content)},data={"use_qwen":"true","use_ocr":"false"})
                    assert r.status_code==202,r.text
                    return r.json()["job_id"]
                def old_failed(raw,name="blocks.png",content=None):
                    job=submit(name,content)
                    with patch("ai_design_review.multi_spec.normalize_layout",side_effect=MultiSpecError("无法确定规格表格/区块布局。")),patch.object(QwenVisionEngine,"_call_qwen",return_value=raw) as model:
                        runner._process_job(repo.claim_next_recognition_job(runner.worker_id))
                        assert model.call_count==1
                    assert repo.get_recognition_job(job,owner_user_id=OWNER["user_id"])["status"]=="failed"
                    assert repo.get_review(job,owner_user_id=OWNER["user_id"]) is None
                    return job
                def forbid_models():
                    return patch.object(QwenVisionEngine,"_call_qwen",side_effect=AssertionError("No Qwen during replay"))
                # New uploads use the same canonical path and one file-level request.
                job=submit()
                with patch.object(QwenVisionEngine,"_call_qwen",return_value=replies[0]) as model:
                    runner._process_job(repo.claim_next_recognition_job(runner.worker_id));assert model.call_count==1
                assert repo.get_review(job,owner_user_id=OWNER["user_id"])["review"]["multi_spec"]["layout"]=="blocks"
                for raw in replies:
                    job=old_failed(raw);d=api.API_RUN_ROOT/job;raw_hash=fingerprint(d/"qwen_pages/response.json")
                    prior_diagnostic=(d/"multi_spec_diagnostics.json").read_bytes()
                    with forbid_models() as model,patch.object(api.UnifiedOcrEngine,"extract_with_raw",side_effect=AssertionError("No OCR needed for replay")) as ocr:
                        receipt=client.post(f"/api/reviews/{job}/retry");assert receipt.status_code==202,receipt.text
                        assert "options" not in receipt.json()["recognition"]
                        assert client.post(f"/api/reviews/{job}/retry").status_code==409
                        claimed=repo.claim_next_recognition_job(runner.worker_id)
                        assert claimed["options"][REPLAY_OPTION]["response_sha256"]==raw_hash
                        runner._process_job(claimed);assert model.call_count==ocr.call_count==0
                        status=client.get(f"/api/reviews/{job}/recognition-status").json()["recognition"]
                        assert status["status"]=="completed" and status["attempt_count"]==2
                        stored=repo.get_review(job,owner_user_id=OWNER["user_id"])
                        assert stored["record_kind"]=="source" and len(stored["review"]["multi_spec"]["variants"])==3
                        assert fingerprint(d/"qwen_pages/response.json")==raw_hash
                        assert (d/"multi_spec_diagnostics.json").read_bytes()==prior_diagnostic
                        assert (d/"multi_spec_recovery.json").exists()
                        variants=client.get(f"/api/reviews/{job}/variants").json()
                        assert variants["created_count"]==0
                        ids=[v["variant_id"] for v in variants["variants"]]
                        made=client.post(f"/api/reviews/{job}/variants/create-reviews",json={"variant_ids":[ids[0]],"expected_source_revision":variants["source_revision"],"idempotency_key":"once"})
                        assert made.status_code==200,made.text
                        before=repo.get_review(job,owner_user_id=OWNER["user_id"])
                        # Lost completion acknowledgement/redelivery reuses stable IDs and children.
                        result=asyncio.run(api.run_recognition_job_record(claimed))
                        assert [v["variant_id"] for v in result["review"]["multi_spec"]["variants"]]==ids
                        assert repo.get_review(job,owner_user_id=OWNER["user_id"])==before
                        assert json.loads((d/"review.json").read_text(encoding="utf-8"))["multi_spec"]["variants"][0]["variant_id"]==ids[0]
                        assert model.call_count==0
                        changes=client.get(f"/api/reviews/{job}/changes").json()
                        assert "multi_spec_layout_recovered" in json.dumps(changes)
                # Fingerprint mismatches fail locally with zero fallback calls.
                for which in ("response","drawing"):
                    job=old_failed(replies[0]);assert client.post(f"/api/reviews/{job}/retry").status_code==202
                    claimed=repo.claim_next_recognition_job(runner.worker_id);d=api.API_RUN_ROOT/job
                    path=d/("qwen_pages/response.json" if which=="response" else claimed["options"]["drawing_path"])
                    path.write_bytes(path.read_bytes()+b" ")
                    with forbid_models() as model:
                        runner._process_job(claimed);assert model.call_count==0
                    failed=repo.get_recognition_job(job,owner_user_id=OWNER["user_id"])
                    assert failed["status"]=="failed" and "未重新调用Qwen" in failed["error_message"],json.dumps(failed,ensure_ascii=True)
                    assert repo.get_review(job,owner_user_id=OWNER["user_id"]) is None
                # A corrupt or missing cache keeps the normal explicit retry path.
                job=old_failed(replies[0]);d=api.API_RUN_ROOT/job;(d/"qwen_pages/response.json").write_text("bad json")
                assert client.post(f"/api/reviews/{job}/retry").status_code==202
                claimed=repo.claim_next_recognition_job(runner.worker_id);assert REPLAY_OPTION not in claimed["options"]
                with patch.object(QwenVisionEngine,"_call_qwen",return_value=replies[0]) as model:
                    runner._process_job(claimed);assert model.call_count==1
                # Cancellation and owner filtering happen before replay can publish a source.
                job=old_failed(replies[0])
                with patch.dict(os.environ,{"AI_REVIEW_MOCK_USER_ID":"other-owner"}):assert client.post(f"/api/reviews/{job}/retry").status_code==409
                assert client.post(f"/api/reviews/{job}/retry").status_code==202
                claimed=repo.claim_next_recognition_job(runner.worker_id)
                repo.request_recognition_job_deletion(job,owner_user_id=OWNER["user_id"])
                with forbid_models() as model:
                    runner._process_job(claimed);assert model.call_count==0
                assert repo.get_recognition_job(job,owner_user_id=OWNER["user_id"]) is None
                assert repo.get_review(job,owner_user_id=OWNER["user_id"]) is None
                # PDF replay validates actual page count, including specs on page2.
                from pypdf import PdfWriter
                pdf=io.BytesIO();writer=PdfWriter()
                for _ in range(2):writer.add_blank_page(width=100,height=100)
                writer.write(pdf)
                p=payload();p["variants"][1]["page"]=2;p["variants"][2]["page"]=2
                def render_pdf(drawing,pages,warnings):
                    result=[]
                    for number in (1,2):
                        path=pages/f"page-{number}.png";path.write_bytes(png.getvalue());result.append(str(path))
                    return result
                with patch.object(api,"_make_preview_images",side_effect=render_pdf):
                    job=old_failed(response(p),"multi.pdf",pdf.getvalue())
                    assert client.post(f"/api/reviews/{job}/retry").status_code==202
                    claimed=repo.claim_next_recognition_job(runner.worker_id)
                    assert claimed["options"][REPLAY_OPTION]["page_count"]==2
                    with forbid_models() as model:
                        runner._process_job(claimed);assert model.call_count==0
                    result=repo.get_review(job,owner_user_id=OWNER["user_id"])
                    assert result["file_info"]["page_count"]==2
                    assert result["review"]["multi_spec"]["variants"][1]["page"]==2
            repo.dispose()
    finally:api.REVIEW_PERSISTENCE,api.API_RUN_ROOT,api.verify_review_roughness=old


if __name__=="__main__":
    contracts();queue_tests(saved_responses())
    print("PASS layout normalization, queued cached retry, stable IDs/children, fingerprint protection, cancellation and permissions; no cloud calls")
