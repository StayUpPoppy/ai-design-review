"""Offline hot-coiled limits, real table evidence and revisioned legacy repair."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
os.environ["AI_REVIEW_IDENTITY_MODE"]="mock"
os.environ["AI_REVIEW_MOCK_USER_ID"]="hot-table-test"
os.environ["AI_REVIEW_MOCK_USERNAME"]="hot-table-test"
from fastapi.testclient import TestClient
from PIL import Image, ImageOps
from ai_design_review import api, standard_selector
from ai_design_review.accuracy_inference import refresh_accuracy_inference, mark_accuracy_input, select_manual_accuracy
from ai_design_review.drawing_annotations import annotation_source, build_annotations, locate_fields
from ai_design_review.engines.ocr_providers import RapidOcrProvider
from ai_design_review.io_utils import write_json
from ai_design_review.multi_spec import child_review, annotation_context, link_assets, source_review, parse_multi_spec
from ai_design_review.multi_spec_evidence import resolve, reconcile_review
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.standardizers.hot_coiled import standardize
from ai_design_review.standardization_chat_agent import parse_accuracy_standardization_request, select_general_accuracy_grade
from test_accuracy_inference import hot_base

QA=Path(__file__).resolve().parents[1]/"outputs/multi-spec-annotation-qa"
FIELDS=("wire_diameter","inner_diameter","free_length","total_coils","active_coils")
OWNER={"user_id":"hot-table-test","username":"hot-table-test"}


def rules_lifecycle():
    review=hot_base(); refresh_accuracy_inference(review,initialize=True)
    results={r["field"]:r for r in review["accuracy_inference"]["results"]}
    assert results["inner_diameter"]["grade"]=="T级"
    assert results["free_length"]["grade"]=="2级"
    assert results["spring_rate"]["status"]=="not_graded"
    assert parse_accuracy_standardization_request("按T级精度标准化")["requested_grade"]=="T级"
    select_general_accuracy_grade(review,"2级")
    original=deepcopy(review["accuracy_inference"]["input_snapshot"])
    for item in standardize(review["spring_parameters"])["standardization_results"]:
        p=review["spring_parameters"][item["target_field"]]
        p.update(tolerance_upper=item["suggested_tolerance_upper"],tolerance_lower=item["suggested_tolerance_lower"])
        mark_accuracy_input(review,item["target_field"],generated=True,tolerance=True)
    assert review["spring_parameters"]["inner_diameter"]["tolerance_upper"]==2
    assert review["spring_parameters"]["free_length"]["tolerance_upper"]==5.48
    for _ in range(3):
        review=json.loads(json.dumps(review));refresh_accuracy_inference(review)
        assert review["accuracy_inference"]["input_snapshot"]==original
        assert review["spring_parameters"]["accuracy_grade"]["value"]=="2级"
    # Changing an effective generated stiffness changes the load minimum only,
    # never turns a generated tolerance into independent drawing evidence.
    review=hot_base();p=review["spring_parameters"]
    for field in ("inner_diameter","free_length"): p[field].update(tolerance_upper=None,tolerance_lower=None)
    p["spring_rate"].update(value=10,source=["formula_calculation"])
    p["load_points"]=[{"label":"F1","force":100,"height":200,"load_tolerance_upper":20,"load_tolerance_lower":-20}]
    refresh_accuracy_inference(review,initialize=True); assert review["accuracy_inference"]["inferred_grade"]=="1级"
    p["spring_rate"]["value"]=20;refresh_accuracy_inference(review)
    assert review["accuracy_inference"]["inferred_grade"]=="T级"
    p["load_points"][0]["height"]=None;refresh_accuracy_inference(review)
    assert review["accuracy_inference"]["inferred_grade"] is None


def setup_source(root, source, ocr, image):
    d=root/"source";(d/"pages").mkdir(parents=True);(d/"inputs").mkdir()
    for folder in ("pages","inputs"): (d/folder/"source.jpg").write_bytes(image.read_bytes())
    write_json(d/"review.json",source)
    document,_=annotation_source(d,lambda p:f"/api/reviews/source/artifacts/{p.as_posix()}")
    write_json(d/"annotation_ocr_v3.json",{**ocr,"source_document_id":document["source_document_id"]})
    return d


def synthetic_evidence():
    from PIL import ImageDraw
    def block(text,x,y,width=.04,height=.025):
        return {"text":text,"position":{"x":x,"y":y,"width":width,"height":height},"page":1,"source":"ocr"}
    raw={"document_mode":"multi","layout":"rows","complete":True,"spec_count":3,
        "common":{"applies_to_all":True,"parameters":{}},"variants":[]}
    blocks=[block("d × D₁ × H₀",.4,.12,.16)]
    for i in range(3):
        code=f"FTA-{10+i}/60-100";y=.22+i*.1
        raw["variants"].append({"code":code,"page":1,"region":{"x":.05,"y":.4-i*.1,"width":.9,"height":.09},
            "parameters":{f:{"value":v,"unit":"mm" if f not in ("active_coils","total_coils") else "turns","evidence":str(v)} for f,v in
                {"wire_diameter":10,"outer_diameter":50,"free_length":100,"active_coils":8,"total_coils":10,"pitch":10}.items()}})
        blocks.extend([block(str(i+1),.05,y),block(code if i else code.replace("/","./"),.12,y,.2),
            block("φ10×φ50×100",.4,y,.16),block("8",.65,y),block("10",.75,y),block("10",.85,y)])
    source=source_review({},parse_multi_spec(raw))
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);d=root/"source";(d/"pages").mkdir(parents=True)
        image=Image.new("RGB",(1000,1000),"white");draw=ImageDraw.Draw(image)
        for y in (.2,.3,.4,.5):draw.line((50,int(y*1000),950,int(y*1000)),fill="black",width=2)
        image.save(d/"pages/p.png");write_json(d/"review.json",source)
        document,_=annotation_source(d,lambda p:f"/api/reviews/source/artifacts/{p.as_posix()}")
        def put(values):write_json(d/"annotation_ocr_v3.json",{"source_document_id":document["source_document_id"],"cache_format":4,"blocks":values,"full":{"1":"completed"},"regions":{},"handled_fields":{},"warnings":[]})
        put(blocks);proof=resolve(source,d,allow_ocr=False)
        assert len(proof["variants"])==3 and all(v["method"]=="grid" for v in proof["variants"].values())
        put(blocks+[block("2FTA-11/60-100",.09,.31,.23,.04)])
        assert len(resolve(source,d,allow_ocr=False)["variants"])==3,"overlapping indexed OCR is the same printed code"
        put(blocks)
        reference=deepcopy(source)
        for v in reference["multi_spec"]["variants"]:
            v["reference_values"]["diameter_D1"]={**v["parameters"].pop("outer_diameter"),"tolerance_upper":1,"tolerance_lower":0}
        ref_proof=resolve(reference,d,allow_ocr=False)
        ref_child,_=child_review(reference,reference["multi_spec"]["variants"][0],"source",evidence=ref_proof)
        assert ref_child["spring_parameters"]["inner_diameter"]["value"]==50
        assert ref_child["spring_parameters"]["inner_diameter"]["tolerance_lower"]==0
        proof=resolve(source,d,allow_ocr=False)
        first=source["multi_spec"]["variants"][0];entry=proof["variants"][first["variant_id"]]
        review,candidates=child_review(source,first,"source",evidence=proof)
        target=root/"child";link_assets(d,target,candidates)
        context=annotation_context(review,target)
        # Prefer actual individual digit boxes over the verified composite cell.
        cell=deepcopy(entry["cells"]["wire_diameter"])
        cell["tokens"]=[{"text":"10","position":{"x":.42,"y":.22,"width":.02,"height":.025}}]
        values=[b for b in blocks if b["text"]!="φ10×φ50×100"]+[cell]
        wire=next(a for a in locate_fields(context,candidates,values) if a["field"]=="wire_diameter")
        assert wire["locations"][0]["bbox"]["width"]==.02 and not wire["locations"][0].get("anchor_kind")
        # A noisy code needs its row number plus two independent engineering values.
        put([b for b in blocks if not (b["text"]=="1" and b["position"]["y"]==.22)])
        proof=resolve(source,d,allow_ocr=False)
        assert first["variant_id"] not in proof["variants"]
        put([{**b,"page":2} if b["text"]=="FTA-12/60-100" else b for b in blocks])
        proof=resolve(source,d,allow_ocr=False)
        assert source["multi_spec"]["variants"][2]["variant_id"] not in proof["variants"]
        put([{**b,"text":"φ11×φ50×100"} if b["text"]=="φ10×φ50×100" else b for b in blocks])
        proof=resolve(source,d,allow_ocr=False)
        assert all(not e["cells"] for e in proof["variants"].values()),"different digits cannot establish role"
    print("PASS grid evidence, OCR separators, independent digits, page isolation and engineering cross-checks")


def replay_rows():
    saved_path=QA/"rows-saved.json";image=Path("C:/Users/29580/Desktop/多规格2.jpg")
    if not saved_path.exists() or not image.exists():
        print("SKIP private saved table replay (use local saved source/OCR for acceptance)");return
    saved=json.loads(saved_path.read_text(encoding="utf-8-sig"));source=saved["source"]
    runtime=QA/"rows-runtime-ocr.json"
    if runtime.exists(): saved["ocr"]=json.loads(runtime.read_text(encoding="utf-8-sig"))
    with tempfile.TemporaryDirectory() as directory, patch.object(RapidOcrProvider,"recognize",side_effect=AssertionError("cached evidence only")):
        root=Path(directory);d=setup_source(root,source,saved["ocr"],image)
        proof=resolve(source,d);assert len(proof["variants"])==13
        before=deepcopy(source);browser=[]
        for v in source["multi_spec"]["variants"]:
            entry=proof["variants"][v["variant_id"]]
            assert entry["status"]=="verified" and entry["diameter_role"]["field"]=="inner_diameter"
            review,candidates=child_review(source,v,"source",evidence=proof)
            job_id=f"row{v['order']}";target=root/job_id;link_assets(d,target,candidates)
            context=annotation_context(review,target);region=context["multi_spec_origin"]["region"]
            document=build_annotations(review,target,lambda p:f"/api/reviews/{job_id}/artifacts/{p.as_posix()}")
            for field in FIELDS:
                a=next(a for a in document["annotations"] if a["field"]==field)
                assert len(a["locations"])==1,(v["order"],field,a)
                l=a["locations"][0];assert region["y"]<=l["anchor"]["y"]<=region["y"]+region["height"]
                assert l["page"]==region["page"]
            assert not next(a for a in document["annotations"] if a["field"]=="outer_diameter")["locations"]
            if v["order"]==13:
                p=review["spring_parameters"]
                assert [p[f]["value"] for f in ("wire_diameter","inner_diameter","mean_diameter","outer_diameter","free_length","total_coils","active_coils")]==[28,75,103,131,274,7.5,6]
                assert p["inner_diameter"]["tolerance_upper"]==1 and p["outer_diameter"].get("tolerance_upper") is None
                assert p["accuracy_grade"]["value"]=="T级",review["accuracy_inference"]
            if v["order"] in (1,13):
                api.ensure_compression_material(review);api.ensure_surface_roughness_parameter(review);api.apply_generation_defaults(review);api._prepare_review_reasonableness(review,1)
                adjustment=(review["spring_parameters"].get("support_coils") or {}).get("support_coils_adjustment")
                if adjustment: adjustment["audit_recorded"]=True
                browser.append({"id":job_id,"review":review,"annotations":document})
        assert source==before,"source response and stable IDs remain intact"
        # Raw model boxes are reversed. Evidence, not their order, supplies rows.
        assert proof["variants"][source["multi_spec"]["variants"][-1]["variant_id"]]["region"]["y"]>.65
        assert resolve(source,d)==proof,"ordinary reads reuse evidence cache"
        duplicate=deepcopy(source);duplicate["multi_spec"]["variants"][1]["code"]=duplicate["multi_spec"]["variants"][0]["code"]
        rejected=resolve(duplicate,d,allow_ocr=False)
        assert not any(v["variant_id"] in rejected["variants"] for v in duplicate["multi_spec"]["variants"][:2])
        proof=resolve(source,d,allow_ocr=False)
        legacy,candidates=child_review(source,source["multi_spec"]["variants"][-1],"source")
        target=root/"legacy";link_assets(d,target,candidates);old=deepcopy(legacy)
        assert reconcile_review(legacy,target)
        assert legacy["spring_parameters"]["mean_diameter"]["value"]==103
        assert legacy["spring_parameters"]["accuracy_grade"]["value"]=="T级"
        for protection in ("confirmed","human","unknown"):
            protected=deepcopy(old);p=protected["spring_parameters"]["outer_diameter"]
            if protection=="confirmed":p["need_human_review"]=False
            elif protection=="human":p["source"]=["human_edited"]
            else:p.pop("source",None)
            assert not reconcile_review(protected,target)
            assert protected["spring_parameters"]["outer_diameter"]["value"]==75
        check_api(root,source,old)
        write_json(QA/"rows-browser.json",browser)
        with Image.open(image) as im: ImageOps.exif_transpose(im).save(QA/"rows.png")
        write_json(QA/"rows-evidence.json",proof)
    print("PASS actual 13 rows: fresh anchors, corrected D1, T inference, cached proof and old manual-value protection")


def check_api(root,source,legacy):
    original=(api.REVIEW_PERSISTENCE,api.API_RUN_ROOT)
    store=ReviewPersistence(f"sqlite+pysqlite:///{root/'hot.db'}");store.create_schema_for_testing()
    api.REVIEW_PERSISTENCE,api.API_RUN_ROOT=store,root
    try:
        store.create_review("source",source,artifact_dir=str(root/"source"),owner=OWNER)
        store.create_review("legacy",legacy,artifact_dir=str(root/"legacy"),owner=OWNER)
        with TestClient(api.app) as client,patch.object(api,"verify_review_roughness",return_value=None):
            read=client.get("/api/reviews/legacy");assert read.status_code==200,read.text
            review=read.json();assert review["spring_parameters"]["inner_diameter"]["value"]==75
            assert store.get_review("legacy",owner_user_id=OWNER["user_id"])["review"]["spring_parameters"]["outer_diameter"]["value"]==75,"GET prepares a draft only"
            saved=client.patch("/api/reviews/legacy",json={"review":review,"expected_revision":1})
            assert saved.status_code==200,saved.text
            reopened=client.get("/api/reviews/legacy").json()
            assert reopened["spring_parameters"]["mean_diameter"]["value"]==103
            assert not reopened["multi_spec_reconciliation"].get("pending_save")
            changes=client.get("/api/reviews/legacy/changes").json()
            assert "multi_spec_diameter_reconciled" in json.dumps(changes)
            assert client.patch("/api/reviews/legacy",json={"review":legacy,"expected_revision":1}).status_code==409
            manual=client.post("/api/reviews/legacy/standardization-chat",json={"message":"按二级精度标准化","use_llm":False,"expected_revision":reopened["review_revision"]})
            assert manual.status_code==200,manual.text
            assert manual.json()["review"]["spring_parameters"]["accuracy_grade"]["value"]=="2级"
            assert client.get("/api/reviews/legacy").json()["accuracy_inference"]["selection_mode"]=="manual"
            # Dedicated annotation revisions do not persist parameter repairs or overwrite drafts.
            annotations=client.get("/api/reviews/legacy/annotations")
            assert annotations.status_code==200,annotations.text
            assert all(next(a for a in annotations.json()["annotations"] if a["field"]==f)["locations"] for f in FIELDS)
            assert next(a for a in annotations.json()["annotations"] if a["field"]=="outer_diameter")["original_value"] is None,"verified D1 cannot remain an outer evidence value"
    finally:
        api.REVIEW_PERSISTENCE,api.API_RUN_ROOT=original;store._engine.dispose()


if __name__=="__main__":
    with patch.object(standard_selector,"standard_references",return_value=[]):
        rules_lifecycle();synthetic_evidence();replay_rows()
    print("PASS hot-coiled suggestion application, manual mode, effective stiffness, revisioned correction and API replay")
