"""Recover labelled pitch or dimensions tied to neighbouring repeated wire sections."""
from __future__ import annotations
import re
from copy import deepcopy


def pitch_from_pages(pages, *, region=None, wire_diameter=None, free_height=None):
    from .load_point_evidence import _inside, _deduplicate_texts, _position
    found=[]
    for page in pages:
        if region and region.get("page",page["page"])!=page["page"]:continue
        for text in _deduplicate_texts([t for t in page["texts"] if _inside(t,page,region)]):
            labelled=re.search(r"(?:节距|\bpitch\b|\bt\s*[=＝])\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?",text["text"],re.I)
            number=re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*",text["text"])
            if not labelled and not number:continue
            value=float((labelled or number)[1])
            if value<=0 or wire_diameter is not None and value<=wire_diameter:continue
            if not labelled and (free_height is None or value>=free_height):continue
            method="labelled_pitch" if labelled else "adjacent_turn_dimension"
            if not labelled and (_table_cell(text,page) or not _adjacent_dimension(text,page)):continue
            found.append({"field":"pitch","value":value,"unit":"mm","source":["local_pitch_evidence"],"need_human_review":True,
                          "page":page["page"],"position":_position(text,page),"evidence":text["text"],"verification_method":method,"pitch_evidence_version":"pitch-evidence/v1"})
    if len({p["value"] for p in found})!=1:return None
    return found[0]


def _table_cell(text,page):
    x0,y0,x1,y1=text["bbox"];cx=(x0+x1)/2;cy=(y0+y1)/2;h=max(3,y1-y0)
    vertical=[l for l in page["lines"] if abs(l[0]-l[2])<2 and abs(l[1]-l[3])>6*h and min(l[1],l[3])<=cy<=max(l[1],l[3])]
    left=[l for l in vertical if l[0]<=x0+2];right=[l for l in vertical if l[0]>=x1-2]
    if not left or not right:return False
    lo=max(l[0] for l in left);hi=min(l[0] for l in right)
    crossings={round(l[1]/3) for l in page["lines"] if abs(l[1]-l[3])<2 and min(l[0],l[2])<=lo+3 and max(l[0],l[2])>=hi-3 and abs(l[1]-cy)<8*h}
    return len(crossings)>=3


def _adjacent_dimension(text,page):
    circles=page.get("coil_circles") or []
    if len(circles)<4:return False
    for axis in (0,1):
        x0,y0,x1,y1=text["bbox"] if axis==0 else [text["bbox"][1],text["bbox"][0],text["bbox"][3],text["bbox"][2]]
        h=max(3,y1-y0);center=(x0+x1)/2
        lines=page["lines"] if axis==0 else [[l[1],l[0],l[3],l[2]] for l in page["lines"]]
        cs=circles if axis==0 else [[c[1],c[0],c[2]] for c in circles]
        for line in lines:
            lo,hi=min(line[0],line[2]),max(line[0],line[2]);base=(line[1]+line[3])/2
            if abs(line[1]-line[3])>2 or not lo<=center<=hi or min(abs(base-y0),abs(base-y1))>h*.45:continue
            for cx,cy,r in cs:
                if not r<abs(base-cy)<9*r or not lo-r<=cx<=hi+r:continue
                row=sorted([c for c in cs if abs(c[1]-cy)<r*.65 and .7*r<c[2]<1.4*r],key=lambda c:c[0])
                distances=[b[0]-a[0] for a,b in zip(row,row[1:]) if b[0]-a[0]>2*r]
                if len(distances)<3:continue
                spacing=sorted(distances)[len(distances)//2]
                if sum(abs(d-spacing)<spacing*.18 for d in distances)<3:continue
                for a,b in zip(row,row[1:]):
                    if abs((b[0]-a[0])-spacing)>spacing*.18 or not lo-r<=a[0]<b[0]<=hi+r:continue
                    if min(abs(center-a[0]),abs(center-b[0]))>4*r:continue
                    guides=[l for l in lines if abs(l[0]-l[2])<2 and min(l[1],l[3])-2<=base<=max(l[1],l[3])+2
                            and min(l[1],l[3])-r<=cy<=max(l[1],l[3])+r and min(abs(l[0]-a[0]),abs(l[0]-b[0]))<r*.5]
                    if guides:return True
    return False


def recover_pitch(review,pages,*,region=None):
    from .standardizers.calculation_state import human_override
    from .load_height_relations import millimeters
    params=review.setdefault("spring_parameters",{});old=params.get("pitch") or {}
    if human_override(old) or old.get("value") not in (None,"") and old.get("formula_calculation_kind")!="pitch":return False
    wire=params.get("wire_diameter") or {}
    free=params.get("free_length") or {}
    candidate=pitch_from_pages(pages,region=region,wire_diameter=millimeters(wire.get("value"),wire.get("unit")),free_height=millimeters(free.get("value"),free.get("unit")))
    if not candidate:return False
    if old.get("need_human_review") is False:
        if millimeters(old.get("value"),old.get("unit"))!=candidate["value"]:
            old["pitch_evidence_candidate"]=candidate
            old["pitch_evidence_warning"]=f"原图可核对节距{candidate['value']:g} mm，保留当前已确认值，请核对"
        return False
    if old.get("need_human_review") is False:
        if millimeters(old.get("value"),old.get("unit"))!=candidate["value"]:
            old["pitch_evidence_candidate"]=candidate
            old["pitch_evidence_warning"]=f"原图可核对节距{candidate['value']:g} mm，保留当前已确认值，请核对"
        return False
    params["pitch"]={**deepcopy(old),**candidate}
    for key in ("derived_value_stale","formula_recommendation_stale","formula_calculation_kind","formula_calculation_inputs","formula_recalculation_candidate","confirmation_snapshot"):
        params["pitch"].pop(key,None)
    for key in list(review.get("manual_confirmations") or {}):
        if key=="pitch" or key.endswith("_pitch"):review["manual_confirmations"].pop(key)
    review["pitch_recovery"]={"version":"pitch-evidence/v1","pending_save":True,"before":deepcopy(old)}
    return True
