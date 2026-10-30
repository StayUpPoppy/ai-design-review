from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ai_design_review.load_height_relations import refresh_load_heights, mark_manual_height, prepare_load_height_save
from ai_design_review.load_point_evidence import original_points, extract_force_annotations, extract_page_points
from ai_design_review.fusion import fuse_candidates
from ai_design_review.engines.ocr_adapter import _extract_load_points


def base():
    return {"drawing_summary":{"spring_type":"compression_spring"},"spring_parameters":{"free_length":{"value":133.35,"unit":"mm"},"load_points":[
        {"load_point_id":"point1","label":"P1","page":1,"height":None,"height_unit":"mm","force":1109.83,"force_unit":"N","need_human_review":True,
         "height_relation":{"version":"load-height/v1","kind":"free_deflection","value":7.58,"unit":"mm","mode":"automatic","verified":True,"page":1,"reference_only":True}},
        {"load_point_id":"point2","label":"P2","page":1,"height":None,"height_unit":"mm","force":5550.05,"force_unit":"N","load_tolerance_upper":221.96,"load_tolerance_lower":-221.96,"need_human_review":True,
         "height_relation":{"version":"load-height/v1","kind":"incremental_deflection","value":30.33,"unit":"mm","base_label":"P1","mode":"automatic","verified":True,"page":1}}
    ]},"manual_confirmations":{}}


def cases():
    result=[]
    def add(name,review,heights):
        initial=copy.deepcopy(review)
        refresh_load_heights(review)
        assert [p.get("height") for p in review["spring_parameters"]["load_points"]]==heights,name
        again=copy.deepcopy(review);assert refresh_load_heights(review)==[],name+" no repeated subtraction"
        assert review==again,name+" idempotent"
        result.append({"name":name,"review":initial,"expected":copy.deepcopy(review)})
    add("two-point chain",base(),[125.77,95.44])
    r=base();r["spring_parameters"]["load_points"].reverse();add("out-of-order points",r,[95.44,125.77])
    r=base();p=r["spring_parameters"]["load_points"][0];p["height_relation"].update(kind="absolute_height",value=125.77);add("direct height is not subtracted",r,[125.77,95.44])
    r=base();p=r["spring_parameters"]["load_points"][0];p["height_relation"].update(kind="absolute_height",value=140);add("direct height retained for engineering review",r,[140,109.67])
    r=base();p=r["spring_parameters"]["load_points"][0];p.pop("height_relation");p.update(height=125.77,deflection=7.58,deflection_unit="mm",height_calculation={"formula":"H0-deflection","free_length":133.35,"deflection":7.58},source=["qwen_vision"]);add("legacy explicit table deflection",r,[125.77,95.44])
    r=base();r["spring_parameters"]["free_length"]["value"]=140;add("free height changed",r,[132.42,102.09])
    r=base();r["spring_parameters"]["free_length"]["value"]=None;add("missing free height",r,[None,None])
    r=base();r["spring_parameters"]["free_length"]["derived_value_stale"]=True;add("stale free height",r,[None,None])
    r=base();r["spring_parameters"]["load_points"][0]["height_relation"]["verified"]=False;add("unverified endpoints",r,[None,None])
    r=base();p=r["spring_parameters"]["load_points"][0];p.update(height=120,need_human_review=False);p["height_relation"].update(verified=False,preserve_existing_value=True);add("server-protected legacy confirmed height",r,[120,89.67])
    r=base();p=r["spring_parameters"]["load_points"][0];p.update(height=120,need_human_review=True);p["height_relation"].update(verified=False,preserve_existing_value=True);add("server-protected unknown-origin height remains pending",r,[120,89.67])
    r=base();p=r["spring_parameters"]["load_points"][0];p.update(height=120,need_human_review=False);p["height_relation"]["verified"]=False;add("model flag does not certify unverified height",r,[None,None])
    r=base();r["spring_parameters"]["load_points"][0]["height_relation"]["kind"]="unknown";add("unknown relation",r,[None,None])
    r=base();r["spring_parameters"]["load_points"][1]["height_relation"]["base_label"]="missing";add("missing reference point",r,[125.77,None])
    r=base();r["spring_parameters"]["load_points"][1]["height_relation"]["page"]=2;add("cross-page chain denied",r,[125.77,None])
    r=base();r["spring_parameters"]["load_points"][1]["height_relation"]["scope"]="another-spec";add("cross-spec chain denied",r,[125.77,None])
    r=base();r["spring_parameters"]["load_points"][0]["height_relation"].update(kind="incremental_deflection",base_label="P2");add("cycle denied",r,[None,None])
    r=base();r["spring_parameters"]["load_points"][0]["height_relation"].update(value=200);add("nonpositive result",r,[None,None])
    r=base();r["spring_parameters"]["load_points"][0]["height_relation"].update(unit="cm",value=.758);add("explicit unit conversion",r,[125.77,95.44])
    r=base();r["spring_parameters"]["load_points"][0]["height_relation"]["unit"]="unknown";add("unknown unit",r,[None,None])
    r=base();p=r["spring_parameters"]["load_points"][0];p.update(height=120);mark_manual_height(p);add("manual height protected",r,[120,89.67])
    r=base();p=r["spring_parameters"]["load_points"][0];p.update(height=None);mark_manual_height(p);add("manual blank protected",r,[None,None])
    r=base();refresh_load_heights(r);r["spring_parameters"]["load_points"][0]["label"]="custom";add("rename uses stable reference ID",r,[125.77,95.44])
    r=base();refresh_load_heights(r)
    for p in r["spring_parameters"]["load_points"]:p["need_human_review"]=False
    add("confirmation survives unchanged inputs",r,[125.77,95.44])
    r["spring_parameters"]["free_length"]["value"]=140;add("changed dependency revokes confirmation",r,[132.42,102.09])
    assert all(p["need_human_review"] for p in result[-1]["expected"]["spring_parameters"]["load_points"])
    return result


def parser_tests():
    for text,unit,upper,lower,percent in [
        ("P1=1109.83N","N",None,None,None),("P2=5550.05±221.96N","N",221.96,-221.96,None),
        ("F1=100N±5%","N",None,None,5),("F1=100N±0%","N",None,None,0),
        ("P1=1.2kN±0.1kN","kN",.1,-.1,None),("P1=1.2kN±100N","kN",.1,-.1,None),
        ("P1=100N +5/-2N","N",5,-2,None),("P1=100N +5/-0N","N",5,0,None),
        ("P1=100N +5N","N",5,None,None),("P1=100N -2N","N",None,-2,None),
        ("P1=100N 20mm","N",None,None,None)]:
        p=extract_force_annotations(text)[0]
        assert (p["force_unit"],p["load_tolerance_upper"],p["load_tolerance_lower"],p["load_tolerance_percent"])==(unit,upper,lower,percent),text
    assert not extract_force_annotations("P1=20")
    assert not extract_force_annotations("P1=100 N / mm")
    invalid=extract_force_annotations("P1=100 N ±-5 N")[0]
    assert invalid["force"]==100 and invalid["force_tolerance_status"]=="uncertain"
    p=extract_force_annotations("P1=100N±5mm")[0];assert p["force_tolerance_status"]=="uncertain" and p["load_tolerance_upper"] is None
    p=_extract_load_points("H1=25mm P1=1109.83N; H2=20mm P2=5550.05±221.96N",{"page":1,"source":"rapidocr"})
    assert len(p)==2 and p[1]["value"]["load_tolerance_upper"]==221.96 and p[0]["value"]["load_tolerance_upper"] is None
    assert p[0]["value"]["height_relation"]["kind"]=="absolute_height"


def fusion_tests():
    a={"field":"load_point","source":"qwen_vision","confidence":.98,"page":1,"value":{"label":"P1","force":100,"height":25,"force_unit":"N"}}
    b={"field":"load_point","source":"rapidocr","confidence":.7,"page":1,"value":{"label":"P1","force":200,"force_unit":"N","load_tolerance_upper":5,"load_tolerance_lower":-5}}
    p=fuse_candidates([a,b])["load_points"][0]["value"]
    assert p["force"]==100 and p["load_tolerance_upper"] is None,"Do not borrow the other force's tolerance"
    b["value"]["force"]=100
    p=fuse_candidates([a,b])["load_points"][0]["value"]
    assert p["force"]==100 and p["load_tolerance_upper"]==5,"Choose a whole explicit bundle for the same point and exact force"
    a["value"].update(load_tolerance_upper=10,load_tolerance_lower=-10)
    assert any(c["field"].endswith(".tolerance") for c in fuse_candidates([a,b])["conflicts"])
    b["page"]=2;assert len(fuse_candidates([a,b])["load_points"])==2


def geometry_tests():
    # A full free-length dimension, a load diagram zero endpoint, and one working point.
    common={"page":1,"width":300,"height":200,"texts":[{"text":"H0=133.35","bbox":[70,80,120,90]},{"text":"P1=1109.83N","bbox":[148,14,240,24]}],
            "lines":[[5,100,195,100],[0,30,0,110],[200,35,200,110],[150,28,150,75],[50,35,200,35]]}
    direct=copy.deepcopy(common);direct["texts"].append({"text":"125.77","bbox":[50,52,90,62]});direct["lines"].append([5,70,145,70])
    point=extract_page_points(direct)[0]
    assert point["height_relation"]["kind"]=="absolute_height" and point["height_relation"]["value"]==125.77
    compression=copy.deepcopy(common);compression["texts"].append({"text":"(7.58)","bbox":[160,52,190,62]});compression["lines"].append([155,70,195,70])
    point=extract_page_points(compression)[0]
    assert point["height_relation"]["kind"]=="free_deflection" and point["height_relation"]["reference_only"]
    unknown=copy.deepcopy(compression);unknown["lines"].remove([50,35,200,35])
    assert extract_page_points(unknown)[0]["height_relation"]["kind"]=="unknown","No guessed free-state endpoint"
    outside={"page":1,"x":.85,"y":0,"width":.15,"height":1}
    assert extract_page_points(compression,region=outside)==[]
    clipped={"page":1,"x":.2,"y":0,"width":.8,"height":1}
    assert extract_page_points(compression,region=clipped)[0]["height_relation"]["kind"]=="unknown","Do not borrow extension lines outside this specification"


def save_tests():
    r=base();refresh_load_heights(r)
    n=copy.deepcopy(r);n["spring_parameters"]["free_length"]["value"]=140;refresh_load_heights(n);prepare_load_height_save(n,r)
    assert n["spring_parameters"]["load_points"][0]["height_relation"]["mode"]=="automatic"
    n=copy.deepcopy(r);n["spring_parameters"]["load_points"][0]["force"]=1200;prepare_load_height_save(n,r)
    assert n["spring_parameters"]["load_points"][0]["height_relation"]["mode"]=="automatic"
    n=copy.deepcopy(r);n["spring_parameters"]["load_points"][0]["height"]=120;prepare_load_height_save(n,r)
    assert n["spring_parameters"]["load_points"][0]["height_relation"]["mode"]=="manual"
    assert n["spring_parameters"]["load_points"][1]["height"]==89.67


def raster_test(path):
    import pymupdf,cv2,numpy as np
    from ai_design_review import load_point_evidence as module
    page=pymupdf.open(path)[0];pix=page.get_pixmap(dpi=180,colorspace=pymupdf.csGRAY)
    width,height=pix.width,pix.height;scale=min(width,height)/595
    mask=cv2.threshold(np.frombuffer(pix.samples,dtype=np.uint8).reshape(height,width),180,255,cv2.THRESH_BINARY_INV)[1]
    detected=cv2.HoughLinesP(mask,1,np.pi/180,threshold=40,minLineLength=max(12,min(width,height)*.012),maxLineGap=5)
    lines=[[value/scale for value in line] for line in module.axis_aligned_lines(detected)]
    texts=[]
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines",[]):
            x0,y0,x1,y1=line["bbox"]
            texts.append({"text":"".join(span["text"] for span in line["spans"]),"bbox":[x0*width/page.rect.width/scale,y0*height/page.rect.height/scale,x1*width/page.rect.width/scale,y1*height/page.rect.height/scale]})
    raster={"page":1,"width":width/scale,"height":height/scale,"lines":lines,"texts":texts,"epsilon":1.5}
    points=module.extract_page_points(raster)
    for i,point in enumerate(points):point["load_point_id"]=f"image{i}"
    review={"spring_parameters":{"free_length":{"value":133.35,"unit":"mm"},"load_points":points}}
    refresh_load_heights(review)
    assert [p["height"] for p in points]==[125.77,95.44],[(p["label"],p["height_relation"]) for p in points]


def create_sample_pdf(path):
    import pymupdf
    doc=pymupdf.open();page=doc.new_page(width=595,height=842)
    for line in [(104.88,247.16,310.68,247.16),(97.44,188,97.44,254),(318.12,182.5,318.12,254),
                 (277.44,215.12,310.68,215.12),(225,215.24,262.8,215.24),(270.48,167,270.48,222),(217.68,151,217.68,222),
                 (174,182.5,318.12,182.5),(174,139,318.12,182.5)]:page.draw_line(line[:2],line[2:],width=.6)
    for x,y,size,text in [(174,241,12,"L0=133.35+/-1.59"),(274,210,10,"(7.58)"),(231,210,10,"30.33"),(268.5,160,12,"P1=1109.83N"),(221.5,146,12,"P2=5550.05+/-221.96N")]:page.insert_text((x,y),text,fontsize=size)
    doc.save(path);doc.close()
    return path


def pdf_tests():
    path=Path(os.getenv("LOAD_HEIGHT_TEST_PDF",r"C:/Users/29580/Desktop/aaa4b87f42474811b3b8000ce8fb0ea7.pdf"))
    if not path.is_file():
        return
    raster_test(path)
    points=original_points(path)
    assert len(points)==2
    r=base();r["spring_parameters"]["load_points"]=points
    for i,p in enumerate(points):p["load_point_id"]=f"actual{i}"
    refresh_load_heights(r)
    assert [p["height"] for p in points]==[125.77,95.44]
    assert points[0]["load_tolerance_upper"] is None and points[1]["load_tolerance_upper"]==221.96
    assert points[1]["height_relation"]["last_inputs"]["base_inputs"]["reference_only"]
    import pymupdf,tempfile
    with tempfile.TemporaryDirectory() as directory:
        for angle in (90,180,270):
            target=Path(directory)/f"rotated-{angle}.pdf"
            with pymupdf.open(path) as document:
                document[0].set_rotation(angle);document.save(target)
            rotated=original_points(target)
            for index,p in enumerate(rotated):p["load_point_id"]=f"rot{index}"
            r=base();r["spring_parameters"]["load_points"]=rotated;refresh_load_heights(r)
            assert [p["height"] for p in rotated]==[125.77,95.44],f"PDF rotation {angle}"
    # The drawing contains enough independent PDF geometry, without historic anchors/model coordinates.
    from ai_design_review.workflow import DrawingReviewWorkflow
    rules=json.loads((ROOT/"config/factory_rules.json").read_text(encoding="utf-8"))
    candidates=[{"field":f,"value":v,"unit":u,"source":"qwen_vision","confidence":.9} for f,v,u in [("spring_type","compression_spring",None),("free_length",133.35,"mm"),("wire_diameter",12.7,"mm"),("total_coils",6.64,"turns"),("active_coils",4.64,"turns")]]
    review=DrawingReviewWorkflow(rules).run(str(path),candidates,run_standardization=False)
    assert {p["label"]:p["height"] for p in review["spring_parameters"]["load_points"]}=={"P1":125.77,"P2":95.44}
    assert all(p["need_human_review"] for p in review["spring_parameters"]["load_points"])


if __name__=="__main__":
    shared=cases()
    if "--json" in sys.argv:print(json.dumps(shared,ensure_ascii=False))
    else:
        parser_tests();fusion_tests();geometry_tests();save_tests();pdf_tests()
        print(f"PASS: {len(shared)} load-height chains, force/tolerance bundles, confirmation dependencies and original PDF new-upload evidence")
