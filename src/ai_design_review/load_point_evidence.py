"""Local, bounded original-document evidence for load annotations and dimension chains."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import unicodedata
from typing import Any
from threading import RLock

from .load_height_dimension import HEIGHT_FIELDS, dimension_with_offsets, read_height_dimension
from .load_height_relations import VERSION, model_load_relation, number, millimeters, refresh_load_heights

_PDF_LOCK = RLock()
LOGGER = logging.getLogger(__name__)
EVIDENCE_VERSION = "load-evidence/v6"


def _verification_warning(stage, error, warnings=None):
    message = f"载荷高度本地证据核验异常，相关高度待核对（{stage}: {type(error).__name__}）"
    LOGGER.warning(message, exc_info=True)
    if warnings is not None and message not in warnings:
        warnings.append(message)


def axis_aligned_lines(found):
    """Normalize OpenCV 4.x (N,1,4) and 5.x (N,4) before reading coordinates."""
    import numpy as np

    if found is None:
        return []
    coordinates = np.asarray(found)
    if not coordinates.size:
        return []
    if not 1 <= coordinates.ndim <= 3 or coordinates.shape[-1] != 4:
        raise ValueError(f"Unexpected Hough line shape: {coordinates.shape}")
    lines = []
    for row in coordinates.reshape(-1, 4):
        values = [float(value) for value in row]
        if all(np.isfinite(values)) and (abs(values[0]-values[2]) < 3 or abs(values[1]-values[3]) < 3):
            lines.append(values)
    return lines

NUM = r"[+-]?\d+(?:\.\d+)?"
UNIT = r"(?:kN|kgf|N|牛顿|牛)"
FORCE = re.compile(rf"(?<![A-Za-z0-9_])(?P<label>[A-Za-z0-9_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{{0,23}}(?:\s*\d+)?)\s*(?:[=＝:：]\s*|\s+)(?P<force>{NUM})(?![\d.])\s*(?P<unit>{UNIT})?\s*(?:(?P<pm>±|\+\s*/\s*-|士)\s*(?P<sym>{NUM})|(?P<up>\+\s*\d+(?:\.\d+)?)\s*(?P<up_unit>{UNIT})?\s*/\s*(?P<down>-\s*\d+(?:\.\d+)?)|(?P<single>[+-]\s*\d+(?:\.\d+)?))?\s*(?P<tail>%|{UNIT})?", re.I)
FREE = re.compile(rf"(?:[LH]\s*[0o₀]|自由(?:高度|长度))\s*[=＝:：]?\s*({NUM})(?![\d.])", re.I)


def explicit_load_heights(text: str, label: str) -> list[dict[str, Any]]:
    """Read a height identity or 'compressed to', never a compression amount."""
    text = unicodedata.normalize("NFKC", text)
    suffix = re.escape(re.search(r"\d*$", label)[0])
    def pattern(suffix):
        return re.compile(
            rf"(?<![A-Za-z0-9_])(?:(?P<symbol>[HL]\s*{suffix}(?![A-Za-z0-9_]))"
            rf"(?:\s*(?:[=:]|压缩到|壓縮到|压缩至|壓縮至|为|為)\s*|\s+)|"
            rf"(?:工作|测试|试验)高度\s*(?:[=:]|为|為)?\s*)", re.I)
    adjacent=pattern(r"\d*")
    independent=pattern(suffix)
    compressed_to=re.compile(r"(?:压缩到|壓縮到|压缩至|壓縮至|压至)\s*")
    result=[]
    for clause in re.split(r"[;；。\n](?!\s*[+−-])", text):
        labels={p["label"].casefold() for p in extract_force_annotations(clause)
                if not re.fullmatch(r"载荷|负荷|荷重|力值|load|force",p["label"],re.I)}
        if labels and label.casefold() not in labels:
            continue
        same_clause=labels=={label.casefold()} or not label and re.search(r"(?:载荷|负荷|力值)\s*(?:[=:]|为|為)?\s*\d",clause)
        matches=list((adjacent if same_clause and not suffix else independent).finditer(clause))
        if not matches and same_clause and not label:
            matches=list(compressed_to.finditer(clause))
        for match in matches:
            if re.search(r"压缩量|壓縮量|变形量|變形量|行程", clause[:match.start()]):
                continue
            symbol = match.groupdict().get("symbol") or ""
            if re.fullmatch(r"[HL]\s*0",symbol,re.I):
                continue
            if not re.match(r"[HL]",symbol,re.I) and not same_clause and (not label or not re.search(rf"(?<![A-Za-z0-9_]){re.escape(label)}(?![A-Za-z0-9_])",clause,re.I)):
                continue
            dimension=read_height_dimension(clause[match.end():],prefix=True)
            if not dimension:
                continue
            if re.match(r"[HL]",symbol,re.I):
                dimension["height_label"] = re.sub(r"\s+", "", symbol)
            dimension["reference_only"] |= bool(re.search(r"参考|參考",clause))
            result.append({**dimension,"evidence":clause.strip()})
    return result


def _deduplicate_texts(texts):
    """Different OCR rotations of the same printed text are one physical position."""
    result=[]
    for text in texts:
        key=re.sub(r"\s+", "", unicodedata.normalize("NFKC",text["text"])).casefold()
        x0,y0,x1,y1=text["bbox"]
        for existing in result:
            if existing["_text_key"]!=key:
                continue
            a,b,c,d=existing["bbox"]
            overlap=max(0,min(x1,c)-max(x0,a))*max(0,min(y1,d)-max(y0,b))
            area=min((x1-x0)*(y1-y0),(c-a)*(d-b))
            if area>0 and overlap/area>=.7:
                existing["bbox"]=[min(x0,a),min(y0,b),max(x1,c),max(y1,d)]
                if text["bbox"] not in existing["_source_boxes"]:
                    existing["_source_boxes"].append(text["bbox"])
                break
        else:
            result.append({**text,"_text_key":key,"_source_boxes":[text["bbox"]]})
    return result


def extract_force_annotations(text: str, declared_unit: str | None = None) -> list[dict[str, Any]]:
    """A tolerance belongs to this force lexeme; an absent tolerance remains absent."""
    result = []
    text = unicodedata.normalize("NFKC", text).replace("＋", "+").replace("−", "-")
    for match in FORCE.finditer(text):
        remainder=text[match.end():]
        if re.match(r"\s*(?:/|·)\s*(?:mm|cm|m)(?![A-Za-z])",remainder,re.I):continue
        attached_unit = bool(re.match(r"[A-Za-z]",remainder) and not text[match.end()-1].isspace())
        if attached_unit and not any(match[k] is not None for k in ("sym","up","single")):
            continue
        unit = match["unit"] or (match["tail"] if match["tail"] != "%" else None) or declared_unit
        if not unit:
            continue
        force = number(match["force"])
        if force is None or force < 0:
            continue
        unit = {"n": "N", "kn": "kN", "kgf": "kgf", "牛顿": "N", "牛": "N"}.get(unit.lower(), unit)
        item = {"label": re.sub(r"\s+", "", match["label"]), "force": force, "force_unit": unit,
                "load_tolerance_upper": None, "load_tolerance_lower": None, "load_tolerance_percent": None,
                "force_tolerance_percent": None, "force_tolerance_status": "not_specified", "evidence": match.group().strip()}
        upper = number(re.sub(r"\s+", "", match["up"] or match["single"] or ""))
        lower = number(re.sub(r"\s+", "", match["down"] or ""))
        symmetric = number(match["sym"])
        factors={"n":1.,"kn":1000.,"kgf":9.80665,"牛顿":1.,"牛":1.}
        factor=factors.get((match["tail"] or unit).lower(),1.)/factors.get(unit.lower(),1.) if match["tail"]!="%" else 1.
        upper_factor=factors.get((match["up_unit"] or match["tail"] or unit).lower(),1.)/factors.get(unit.lower(),1.)
        malformed_suffix = (symmetric is not None or upper is not None) and (
            attached_unit or re.match(r"(?:mm|cm|MPa|kg)(?![A-Za-z])",remainder,re.I))
        if malformed_suffix:
            item["force_tolerance_status"]="uncertain"
            result.append(item)
            continue
        if symmetric is not None:
            if symmetric < 0:
                item["force_tolerance_status"] = "uncertain"
                result.append(item)
                continue
            if match["tail"] == "%":
                item.update(load_tolerance_percent=symmetric, force_tolerance_percent=symmetric)
            else:
                item.update(load_tolerance_upper=round(symmetric*factor,12), load_tolerance_lower=round(-symmetric*factor,12))
            item["force_tolerance_status"] = "specified"
        elif upper is not None:
            item["force_tolerance_status"] = "specified"
            if match["tail"] == "%":
                # Asymmetric percentages need separate engineering interpretation.
                item["force_tolerance_status"] = "uncertain"
            else:
                item.update(load_tolerance_upper=round(upper*upper_factor,12) if upper >= 0 else None,
                            load_tolerance_lower=round(lower*factor,12) if lower is not None else round(upper*factor,12) if upper < 0 else None)
        result.append(item)
    return result


def force_marks(text):
    """Read force marks on the diagram, retaining a missing name until pairing."""
    normalized=unicodedata.normalize("NFKC",text).replace("−","-").strip()
    compact=re.sub(r"\s+","",normalized)
    marks=[]
    for point in extract_force_annotations(normalized):
        if not re.match(rf"^{re.escape(point['label'])}[=:]",compact,re.I):
            continue
        if re.fullmatch(r"载荷|负荷|荷重|力值|load|force",point["label"],re.I):
            point["label"]=""
        marks.append(point)
    if not marks and re.match(rf"^{NUM}\s*{UNIT}(?![A-Za-z])",normalized,re.I):
        parsed=extract_force_annotations("F="+normalized)
        if parsed and len(parsed)==1 and parsed[0]["evidence"][2:].strip()==normalized:
            marks.append({**parsed[0],"label":"","evidence":text.strip()})
    if not marks and re.fullmatch(rf"[A-Za-z][A-Za-z0-9_]*\s*-\s*{NUM}\s*{UNIT}",normalized,re.I):
        # A faint equals sign can lose a stroke. Require independent graph evidence.
        parsed=extract_force_annotations(normalized.replace("-","=",1))
        if parsed:
            marks.append({**parsed[0],"evidence":text.strip(),"_graph_required":True})
    return marks


def _text_overlap(first, second):
    x,y,xx,yy=first["bbox"]
    a,b,c,d=second["bbox"]
    area=min((xx-x)*(yy-y),(c-a)*(d-b))
    return max(0,min(xx,c)-max(x,a))*max(0,min(yy,d)-max(y,b))/area if area>0 else 0


def _load_texts(texts):
    texts=_deduplicate_texts(texts)
    clusters=[]
    for text in texts:
        marks=force_marks(text["text"])
        if len(marks)!=1:
            continue
        mark=marks[0]
        group=next((group for group in clusters if any(
            _text_overlap(text,t)>=.7 and mark["force_unit"]==p["force_unit"]
            and (not mark["label"] or not p["label"] or mark["label"].casefold()==p["label"].casefold())
            for t,p in group)),None)
        if group is None:
            clusters.append([(text,mark)])
        else:
            group.append((text,mark))
    omitted=set()
    for group in clusters:
        if len(group)<2:
            continue
        def fragment(mark):
            digits=f'{mark["force"]:g}'
            return digits.isdigit() and any(
                (other:=f'{p["force"]:g}').isdigit() and len(other)==len(digits)+1 and digits in other
                for _,p in group)
        full=[(t,p) for t,p in group if not fragment(p)]
        chosen,mark=max(full,key=lambda pair:(bool(pair[1]["label"]),not pair[1].get("_graph_required"),
                                              len(pair[0]["_source_boxes"])))
        others=[p for _,p in full if p["force"]!=mark["force"]]
        if others:
            chosen["_force_alternatives"]=sorted({mark["force"],*(p["force"] for p in others)})
        omitted.update(id(t) for t,_ in group if t is not chosen)
    return [t for t in texts if id(t) not in omitted]


def _requirement_force(text):
    normalized=unicodedata.normalize("NFKC",text)
    pattern=rf"(?:载荷|负荷|力值)\s*(?:[=:]|为|為)?\s*({NUM}\s*{UNIT})(?![A-Za-z/·])"
    matches=list(re.finditer(pattern,normalized,re.I))
    if len(matches)!=1:
        return None
    match=matches[0]
    mark=next(iter(force_marks(normalized[match.start():])),None) or next(iter(force_marks(match[1])),None)
    stated_test_force=bool(re.fullmatch(r"\s*(?:试验|测试|工作)\s*",normalized[:match.start()]))
    if mark and (stated_test_force or explicit_load_heights(normalized,"")):
        return {**mark,"evidence":text,"source_context":{"kind":"load_requirement","unit_evidence":mark["force_unit"]}}
    return None


def _set_height_fields(point, evidence):
    for field in HEIGHT_FIELDS:
        if field in evidence:
            point[field]=evidence[field]


def _assign_load_labels(records):
    def order(record):
        point,text=record
        return point.pop("_graph_order", (text["bbox"][0],text["bbox"][1]))
    ordered=sorted(records,key=order)
    occupied={p[key].casefold() for p,_ in ordered for key in ("label","height_label") if p.get(key)}
    fields=(("label","F","height_label"),("height_label","H","label"))

    def assign(point,missing,start,explicit_zero=False):
        while True:
            suffix=str(start) if start or explicit_zero else ""
            names={field:prefix+suffix for field,prefix in missing}
            if not any(name.casefold() in occupied for name in names.values()):
                point.update(names)
                occupied.update(name.casefold() for name in names.values())
                return start
            start+=1

    for point,_ in ordered:
        if not point.get("label"):
            point.setdefault("source_context",{})["force_label_inferred"]=True
        for field,prefix,partner in fields:
            if not point.get(field) and (suffix:=re.search(r"\d+$",point.get(partner) or "")):
                assign(point,[(field,prefix)],int(suffix[0]),explicit_zero=True)

    next_pair=1 if len(ordered)>1 else 0
    for point,_ in ordered:
        if not point.get("label") and not point.get("height_label"):
            next_pair=1+assign(point,[(field,prefix) for field,prefix,_ in fields],next_pair)
    for index,(point,_) in enumerate(ordered,1):
        for field,prefix,_ in fields:
            if not point.get(field):
                assign(point,[(field,prefix)],index if len(ordered)>1 else 0)
    return [p for p,_ in records]


def _point(x, y, page):
    offset, media, rotation = page.cropbox_position, page.mediabox, page.rotation
    x, y = x + offset.x, y + offset.y
    if rotation == 90:
        return media.height-y, x
    if rotation == 180:
        return media.width-x, media.height-y
    if rotation == 270:
        return y, media.width-x
    return x, y


@lru_cache(maxsize=12)
def _pdf_pages(path: str, size: int, modified: int, limit: int) -> list[dict[str, Any]]:
    import fitz
    result = []
    with _PDF_LOCK:
        with fitz.open(path) as document:
            for index in range(min(limit, len(document))):
                page = document[index]
                media = page.mediabox
                width, height = (media.height, media.width) if page.rotation in (90, 270) else (media.width, media.height)
                texts, lines = [], []
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        text = "".join(span["text"] for span in line.get("spans", []))
                        x0,y0,x1,y1 = line["bbox"]
                        corners = [_point(x,y,page) for x,y in ((x0,y0),(x0,y1),(x1,y0),(x1,y1))]
                        texts.append({"text": text, "bbox": [min(p[0] for p in corners),min(p[1] for p in corners),max(p[0] for p in corners),max(p[1] for p in corners)]})
                for drawing in page.get_drawings():
                    for item in drawing.get("items", []):
                        if item[0] == "l":
                            a,b = _point(item[1].x,item[1].y,page), _point(item[2].x,item[2].y,page)
                            lines.append([*a,*b])
                result.append({"page":index+1,"width":width,"height":height,"texts":texts,"lines":lines,"line_segments":deepcopy(lines),"source":"pdf_text_layer"})
    return result


def _inside(text, page, region):
    if not region:
        return True
    if page["page"] != region.get("page", page["page"]):
        return False
    x0,y0,x1,y1 = text["bbox"]
    return region["x"] <= (x0+x1)/2/page["width"] <= region["x"]+region["width"] and region["y"] <= (y0+y1)/2/page["height"] <= region["y"]+region["height"]


def _clusters(values,epsilon):
    groups=[]
    for value in sorted(set(values)):
        if not groups or value-groups[-1][-1]>epsilon:groups.append([value])
        else:groups[-1].append(value)
    return [round(sum(group)/len(group),3) for group in groups]


def _dimension(text, page, axis):
    """Find a dimension baseline and both extension-line/arrow-tip coordinates."""
    x0,y0,x1,y1 = text["bbox"]
    epsilon=page.get("epsilon",.8)
    if axis == 1:
        text = {**text,"bbox":[y0,x0,y1,x1]}
        return _dimension(text,{**page,"lines":[[l[1],l[0],l[3],l[2]] for l in page["lines"]]},0)
    h, center = max(3,y1-y0), (x0+x1)/2
    horizontal = [l for l in page["lines"] if abs(l[1]-l[3]) <= epsilon and min(abs(l[1]-y0),abs(l[1]-y1)) <= h*1.5 and not y0+h*.25<l[1]<y1-h*.25 and min(l[0],l[2]) <= center <= max(l[0],l[2]) and abs(l[2]-l[0]) > h]
    horizontal.sort(key=lambda l: (min(abs(l[1]-y0),abs(l[1]-y1)), -abs(l[2]-l[0])))
    for line in horizontal[:3]:
        lo,hi,y = min(line[0],line[2]),max(line[0],line[2]),line[1]
        guides = [l for l in page["lines"] if abs(l[0]-l[2]) <= epsilon and min(l[1],l[3])-epsilon <= y <= max(l[1],l[3])+epsilon and abs(l[3]-l[1]) >= h]
        split=_clusters([l[0] for l in guides if lo-h<=l[0]<=hi+h],epsilon)
        before=[x for x in split if x<center]
        after=[x for x in split if x>center]
        if before and after and min(after)-max(before)>h:
            return {"a":max(before),"b":min(after),"cross":y,"axis":axis,"guides":guides}
        left = sorted(_clusters([l[0] for l in guides if lo-h <= l[0] <= lo+epsilon],epsilon),key=lambda x:abs(lo-x))
        right = sorted(_clusters([l[0] for l in guides if hi-epsilon <= l[0] <= hi+h],epsilon),key=lambda x:abs(hi-x))
        if left and right and left[0] < right[0]:
            return {"a":left[0],"b":right[0],"cross":y,"axis":axis,"guides":guides}
    return None


def extract_page_points(page: dict[str, Any], *, region=None, document_id="", scope="", hints=None) -> list[dict[str, Any]]:
    epsilon=page.get("epsilon",.8)
    if region:
        x0,y0=region["x"]*page["width"],region["y"]*page["height"]
        x1,y1=x0+region["width"]*page["width"],y0+region["height"]*page["height"]
        page={**page,"lines":[l for l in page["lines"] if all(x0<=x<=x1 and y0<=y<=y1 for x,y in ((l[0],l[1]),(l[2],l[3])))]}
    texts = _load_texts([t for t in page["texts"] if _inside(t,page,region)])
    from .load_table_evidence import FORCE_HEADER, table_height
    records = []
    table_units={m.group(0) for t in texts if FORCE_HEADER.fullmatch(t["text"].strip())
                 if (m:=re.search(r"(?<![A-Za-z])(?:kN|kgf|N)(?![A-Za-z])",t["text"],re.I))}
    table_units={u.lower():u for u in table_units}
    for text in texts:
        marks=force_marks(text["text"])
        requirement=_requirement_force(text["text"]) if not any(p["label"] for p in marks) else None
        if requirement:
            marks=[requirement]
        if not marks and table_units and re.fullmatch(NUM,text["text"].strip()):
            force=number(text["text"])
            for unit in table_units.values():
                candidate={"label":"","force":force,"force_unit":unit,"evidence":text["text"],"_force_bbox":text["bbox"]}
                if force>=0 and (match:=table_height(candidate,texts)) and not match.get("conflict"):
                    marks.append(candidate)
            if len(marks)>1:
                marks=[]
        for point in marks:
            point.update(height=None,height_unit="mm",page=page["page"],position=_position(text,page),
                         force_evidence_verified=True,source_document_id=document_id,source=["local_load_evidence"],need_human_review=True)
            if text.get("_force_alternatives"):
                point.update(load_force_conflict=True,force_evidence_verified=False,force_alternatives=text["_force_alternatives"])
            point["height_relation"]={"kind":"unknown","mode":"automatic","verified":False,"page":page["page"],"scope":scope,"reason":"原图工作高度的起止关系待核对"}
            records.append((point,text))
    for hint in hints or []:
        if hint.get("page",1)!=page["page"] or not hint.get("label") or number(hint.get("force")) is None:continue
        if any(p["label"].casefold()==str(hint["label"]).casefold() for p,_ in records):continue
        if sum(h.get("page",1)==page["page"] and h.get("force")==hint.get("force") for h in hints)>1:continue
        match=table_height(hint,texts)
        if match and not match.get("conflict"):
            point=deepcopy(hint)
            point.update(page=page["page"],source_document_id=document_id,source=["local_load_evidence"],need_human_review=True)
            point["position"]=_position(match["cell"],page)
            records.append((point,match["cell"]))
    for point,text in records:
        if not point["label"]:
            point["_force_bbox"]=text["bbox"]
        table=table_height(point,texts)
        point.pop("_force_bbox",None)
        if table and not table.get("conflict"):
            relation=_relation("absolute_height",table["value"],"mm",table["cell"],page,document_id,scope)
            relation["reference_only"]=table["dimension"]["reference_only"]
            relation.update(verification_method="table_cells",evidence=table["evidence"])
            relation["evidence_refs"]+=_relation("absolute_height",table["value"],"mm",table["force_cell"],page,document_id,scope)["evidence_refs"]
            point["height_relation"]=relation
            point["source_context"]={"kind":"table","row_text":table["evidence"],"unit_evidence":"mm; "+(point.get("force_unit") or "N")}
            _set_height_fields(point,table.get("dimension",{}))
            continue
        if table and table.get("conflict"):point["load_height_conflict"]=True
        direct=[]
        if point.get("source_context",{}).get("kind")=="load_requirement":
            direct.extend((text,value) for value in explicit_load_heights(text["text"],""))
        elif point["label"]:
            for t in texts:
                direct.extend((t,value) for value in explicit_load_heights(t["text"],point["label"]))
        signatures={millimeters(value["value"],value["unit"]) for _,value in direct}
        if len(signatures)==1:
            source_text,value=direct[0]
            point["height_relation"]=_relation("absolute_height",value["value"],value["unit"],source_text,page,document_id,scope,any(v["reference_only"] for _,v in direct))
            point["height_relation"]["evidence_refs"]=[ref for t,_ in direct for ref in _relation("absolute_height",value["value"],value["unit"],t,page,document_id,scope)["evidence_refs"]]
            _set_height_fields(point,value)
            deviations={tuple(v.get(key) for key in HEIGHT_FIELDS[1:]) for _,v in direct
                        if any(key in v for key in HEIGHT_FIELDS[1:])}
            if len(deviations)>1:
                for key in HEIGHT_FIELDS[1:]:
                    point.pop(key,None)
                point["height_tolerance_status"]="uncertain"
            elif deviations:
                _set_height_fields(point,next(v for _,v in direct if any(key in v for key in HEIGHT_FIELDS[1:])))
        elif len(signatures)>1:
            point["load_height_conflict"]=True
    # Independent chains are constructed from a full free-height dimension and adjoining dimensions.
    for free in [t for t in texts if FREE.search(t["text"])]:
        for axis in (0,1):
            full=_dimension(free,page,axis)
            if not full:
                continue
            length=full["b"]-full["a"]
            edges=[]
            for t in texts:
                parsed=read_height_dimension(t["text"])
                if not parsed:
                    continue
                dimension=_dimension(t,page,axis)
                if dimension and full["a"]-1<=dimension["a"]<dimension["b"]<=full["b"]+1 and abs(dimension["cross"]-full["cross"])<length*.6:
                    edges.append((dimension,t,parsed["value"],parsed["unit"],parsed["reference_only"]))
            mapped=[]
            for point,t in records:
                bounds=t["bbox"] if axis==0 else [t["bbox"][1],t["bbox"][0],t["bbox"][3],t["bbox"][2]]
                h=max(3,min(bounds[3]-bounds[1],bounds[2]-bounds[0]))
                available=[]
                for edge,_,_,_,_ in edges:
                    for x in (edge["a"],edge["b"]):
                        if min(abs(bounds[0]-x),abs(bounds[2]-x))<=h and any(abs(g[0]-x)<epsilon*2 and min(abs(min(g[1],g[3])-bounds[3]),abs(max(g[1],g[3])-bounds[1]))<h*1.5 for g in edge["guides"]):
                            available.append(x)
                available=_clusters(available,epsilon)
                if len(available)==1:
                    mapped.append((point,available[0]))
            # Identify the free-state end independently from the load diagram's zero baseline.
            # A dimension from the opposite, fixed end is an absolute working height.
            zero_ends=set()
            transformed=page["lines"] if axis==0 else [[l[1],l[0],l[3],l[2]] for l in page["lines"]]
            xs=[x for _,x in mapped]
            for line in transformed:
                if not xs or abs(line[1]-line[3])>epsilon or not 5<abs(line[1]-full["cross"])<length*.65:
                    continue
                lo,hi=sorted((line[0],line[2]))
                if not lo-1<=min(xs)<=max(xs)<=hi+1:
                    continue
                ends=[x for x in (full["a"],full["b"]) if min(abs(lo-x),abs(hi-x))<epsilon*3]
                if len(ends)==1:zero_ends.add(ends[0])
            if len(zero_ends)!=1:
                continue
            zero=next(iter(zero_ends));fixed=full["a"] if zero==full["b"] else full["b"]
            for edge,t,value,unit,reference in edges:
                ends=(edge["a"],edge["b"])
                for anchor,kind in ((zero,"free_deflection"),(fixed,"absolute_height")):
                    if any(abs(x-anchor)<epsilon*2 for x in ends):
                        targets=[p for p,x in mapped if any(abs(x-e)<epsilon*2 for e in ends) and abs(x-anchor)>epsilon*2]
                        if len(targets)==1:
                            target=targets[0]
                            old=target["height_relation"]
                            if old.get("verified"):
                                previous=millimeters(old.get("value"),old.get("unit"))
                                proposed=millimeters(value,unit)
                                if old.get("kind")=="absolute_height" and kind=="free_deflection":
                                    free_match=FREE.search(free["text"])
                                    free_unit=re.search(r"mm|毫米|cm|in",free["text"][free_match.end():],re.I)
                                    proposed=millimeters(free_match[1],free_unit.group() if free_unit else "mm")-proposed
                                elif old.get("kind")!=kind:
                                    continue
                                if abs(previous-proposed)>1e-8:
                                    target["load_height_conflict"]=True
                            else:
                                target["height_relation"]=_relation(kind,value,unit,t,page,document_id,scope,reference)
                                if kind=="absolute_height":
                                    parsed,evidence=dimension_with_offsets(t,texts,edge["cross"]) if axis==0 else (read_height_dimension(t["text"]),t)
                                    _set_height_fields(target,parsed)
                                    target["height_relation"]=_relation(kind,value,unit,evidence,page,document_id,scope,reference)
            for _ in range(len(edges)):
                for edge,t,value,unit,reference in edges:
                    left=[p for p,x in mapped if abs(x-edge["a"])<epsilon*2]
                    right=[p for p,x in mapped if abs(x-edge["b"])<epsilon*2]
                    if len(left)!=1 or len(right)!=1:continue
                    a,b=left[0],right[0]
                    known=[p for p in (a,b) if p["height_relation"].get("kind")!="unknown"]
                    if len(known)!=1:continue
                    base=known[0];target=b if base is a else a
                    # Compression proceeds away from the verified free-state endpoint.
                    base_x=edge["a"] if base is a else edge["b"]
                    target_x=edge["b"] if base is a else edge["a"]
                    if abs(target_x-zero)<=abs(base_x-zero):continue
                    target["height_relation"]=_relation("incremental_deflection",value,unit,t,page,document_id,scope,reference)
                    target["height_relation"]["base_label"]=base["label"]
    # Supplement only unresolved relations. The established text/table/chain
    # paths and their original coordinates remain authoritative.
    if records and page.get('line_segments'):
        from .load_graph_geometry import geometry_relations
        diagnostics=[]
        for graph in geometry_relations(page,region=region,diagnostics=diagnostics):
            matching=[p for p,t in records if t['bbox']==graph['force_bbox'] and p['label'].casefold()==graph['label'].casefold()
                      and p['force_unit']==graph['force_unit'] and abs(p['force']-graph['force'])<1e-8]
            if len(matching)!=1:continue
            point=matching[0]
            point["_graph_order"]=graph["graph_order"]
            if not point["label"] or point.get("_graph_required"):
                point["source_context"]={"kind":"load_graph","unit_evidence":point["force_unit"]}
            existing=point['height_relation']
            if existing.get('verified'):
                if existing.get('kind')=='absolute_height' and millimeters(existing.get('value'),existing.get('unit'))!=graph['value']:
                    existing['geometry_candidate']={'value':graph['value'],'unit':'mm','evidence':graph['dimension_text'],
                        'geometry_evidence':deepcopy(graph['geometry_evidence'])}
                elif existing.get('kind')=='absolute_height' and millimeters(existing.get('value'),existing.get('unit'))==graph['value']:
                    if not any(k in point for k in HEIGHT_FIELDS[1:]):
                        _set_height_fields(point,graph["height_fields"])
                continue
            text={'text':graph['dimension_text'],'bbox':graph['dimension_bbox']}
            kind='free_deflection' if graph["free_dimension"] else 'absolute_height'
            relation=_relation(kind,graph['distance'],'mm',text,page,document_id,scope,graph['reference_only'])
            relation.update(verification_method=graph['verification_method'],geometry_evidence=graph['geometry_evidence'])
            if graph["free_dimension"]:
                relation["observed_free_height_mm"]=graph["free_dimension"]["value"]
                relation["evidence_refs"]+=_relation("absolute_height",graph["free_dimension"]["value"],"mm",graph["free_dimension"]["text"],page,document_id,scope)["evidence_refs"]
            point['height_relation']=relation
            _set_height_fields(point,graph["height_fields"])
        for diagnosis in diagnostics:
            for point,t in records:
                if (not point['height_relation'].get('verified')
                    and point['label'].casefold()==diagnosis['label'].casefold()
                    and t['bbox']==diagnosis['force_bbox']
                    and point['force_unit']==diagnosis['force_unit'] and abs(point['force']-diagnosis['force'])<1e-8):
                    point['height_relation']['verification_failure']=diagnosis['reason']
                    if diagnosis.get('force_verified'):
                        point["source_context"]={"kind":"load_graph","unit_evidence":point["force_unit"]}
                        point["_graph_order"]=diagnosis["graph_order"]
    return _assign_load_labels([(p,t) for p,t in records if (not p.pop("_graph_required",False) and p["label"]) or p.get("source_context")])


def _position(text,page):
    x0,y0,x1,y1=text["bbox"]
    return {"coordinate_type":"normalized","origin":"top_left","x":x0/page["width"],"y":y0/page["height"],"width":(x1-x0)/page["width"],"height":(y1-y0)/page["height"]}


def _relation(kind,value,unit,text,page,document_id,scope,reference=False):
    return {"version":VERSION,"kind":kind,"mode":"automatic","value":value,"unit":unit,"reference_only":reference,
            "verified":True,"page":page["page"],"scope":scope,"evidence":text["text"],"source_document_id":document_id,
            "verification_method":"dimension_endpoints" if kind!="absolute_height" else "explicit_height",
            "evidence_refs":[{"page":page["page"],"text":text["text"],"position":_position({"bbox":box},page)} for box in text.get("_source_boxes",[text["bbox"]])]}


def original_points(source: Path, *, region=None, scope="", pages=None, hints=None) -> list[dict[str, Any]]:
    if pages is None:
        if source.suffix.lower()!=".pdf":
            return []
        stat=source.stat()
        pages=_pdf_pages(str(source.resolve()),stat.st_size,stat.st_mtime_ns,max(1,int(os.getenv("QWEN_MAX_PAGES","3"))))
    document_id=hashlib.sha256(source.read_bytes()).hexdigest()
    return [p for page in pages for p in extract_page_points(page,region=region,document_id=document_id,scope=scope,hints=hints)]


def _merge_original_points(primary, supplementary):
    """Use the same whole-point fusion for PDF text and independent raster evidence."""
    if not supplementary:
        return primary
    if not primary:
        return supplementary
    from .fusion import fuse_candidates
    originals=[*primary,*supplementary]
    fused=fuse_candidates(_point_candidates(originals))
    result=[]
    for entry in fused["load_points"]:
        value=entry["value"]
        page=entry.get("page",1)
        scope=(value.get("height_relation") or {}).get("scope","")
        matching=[p for p in originals if p.get("page",1)==page and p["label"].casefold()==value["label"].casefold() and p["height_relation"].get("scope","")==scope]
        anchor=_load_anchor(value)
        origin=next((p for p in matching if anchor and _load_anchor(p)==anchor),matching[0])
        point={**deepcopy({k:v for k,v in origin.items() if k not in HEIGHT_FIELDS}),**deepcopy(value)}
        point["height_relation"]=value.get("height_relation") or deepcopy(origin["height_relation"])
        point["need_human_review"]=True
        result.append(point)
    return result


def raster_pages(job_dir, review, *, raw_payloads=None, allow_ocr=False, warnings=None, diameter_geometry=False,
                 diameter_requests=(), load_ocr_pages=None):
    """Reuse the annotation coordinate frame, full-page cache and local OCR budget."""
    from .drawing_annotations import annotation_source, ocr_blocks
    from .multi_spec import shared_ocr_dir
    from PIL import Image, ImageOps
    from urllib.parse import quote
    document,source=annotation_source(job_dir,lambda p:"/api/reviews/"+quote(job_dir.name,safe="")+"/artifacts/"+quote(p.as_posix(),safe="/"))
    if not source or not document["pages"]:
        return []
    pages=document["pages"][:max(1,int(os.getenv("QWEN_MAX_PAGES","3")))]
    payload=raw_payloads if raw_payloads is not None else _read_json(job_dir/"candidates.json").get("raw_payloads",{})
    evidence_payload = payload
    if diameter_geometry:
        evidence_payload = {name: item for name, item in payload.items()
                            if name not in {"candidate_json", "ocr_json", "sample_ocr_json", "qwen_vision", "vlm", "geometry", "werk24", "cached_werk24"}
                            and isinstance(item, dict) and (item.get("provider") or item.get("engine")) == "rapidocr"}
    blocks=ocr_blocks(evidence_payload,pages)
    pool=shared_ocr_dir(job_dir)
    cached=_read_json(pool/"annotation_ocr_v3.json")
    if cached.get("source_document_id")==document["source_document_id"]:
        blocks.extend(cached.get("blocks",[]))
    pitch=(review.get("spring_parameters") or {}).get("pitch") or {}
    if diameter_requests or allow_ocr:
        from .annotation_ocr import local_ocr_blocks
        requests = list(diameter_requests)
        if allow_ocr:
            requests += [{"kind":"load_dimensions","field":f"load_dimensions_{p['page']}","page":p["page"],"evidence_pages":[p["page"]],"status":"unlocated","original_value":0,
                          "request_key":f"{EVIDENCE_VERSION}:load_dimensions_{p['page']}"} for p in pages
                         if load_ocr_pages is None or p["page"] in load_ocr_pages]
            requests += [{"kind":"pitch_dimension","field":f"pitch_evidence_{p['page']}","page":p["page"],"evidence_pages":[p["page"]],"status":"unlocated","original_value":0} for p in pages if not pitch.get("value") or pitch.get("formula_calculation_kind")=="pitch"]
        extra,_,_=local_ocr_blocks(pool,pages,document["source_document_id"],review,[],blocks,verification_requests=requests)
        blocks.extend(extra)
    if not blocks and not diameter_geometry:
        return []
    import cv2
    import numpy as np
    from .drawing_annotations import page_sort_key
    files={page_sort_key(p)[0]:p for p in (job_dir/"pages").glob("*") if p.suffix.lower() in {".png",".jpg",".jpeg",".webp",".tif",".tiff",".bmp"}}
    result=[]
    for page in pages:
        file=files.get(page["page"])
        if file is None:continue
        with Image.open(file) as raw:
            image=ImageOps.exif_transpose(raw).convert("L");image.thumbnail((2400,2400))
            width,height=image.size
            mask=cv2.threshold(np.asarray(image),180,255,cv2.THRESH_BINARY_INV)[1]
            try:
                found=cv2.HoughLinesP(mask,1,np.pi/180,threshold=40,minLineLength=max(12,min(width,height)*.012),maxLineGap=5)
                lines=axis_aligned_lines(found)
            except Exception as error:
                # Text/force evidence remains usable; no lines means no inferred dimension chain.
                _verification_warning(f"page {page['page']} lines", error, warnings)
                lines=[]
            # LSD recovers faint/tilted photographed rules without changing the
            # legacy threshold/Hough input. This is local geometry, not an OCR/model call.
            try:
                detected=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(np.asarray(image))[0]
                segments=np.asarray(detected).reshape(-1,4).tolist() if detected is not None else []
            except Exception as error:
                _verification_warning(f"page {page['page']} load graph",error,warnings)
                segments=[]
            texts=[]
            for block in blocks:
                if block.get("page")!=page["page"]:continue
                b=block.get("position") or {}
                if not all(k in b for k in ("x","y","width","height")):continue
                texts.append({"text":block["text"],"bbox":[b["x"]*width,b["y"]*height,(b["x"]+b["width"])*width,(b["y"]+b["height"])*height],
                              **{key: block[key] for key in ("diameter_offset_origin", "diameter_offset_slot") if key in block}})
            scale=min(width,height)/595
            wire_sections = []
            try:
                circles=cv2.HoughCircles(cv2.GaussianBlur(np.asarray(image),(3,3),0),cv2.HOUGH_GRADIENT,1.2,max(8,min(width,height)*.025),param1=100,param2=18,minRadius=max(3,int(min(width,height)*.009)),maxRadius=max(8,int(min(width,height)*.03)))
                coil_circles=[[float(x)/scale,float(y)/scale,float(r)/scale] for x,y,r in np.asarray(circles).reshape(-1,3)] if circles is not None else []
                if diameter_geometry:
                    wire_sections = _section_circles(mask, coil_circles, scale)
            except Exception as error:
                _verification_warning(f"page {page['page']} pitch dimension",error,warnings)
                coil_circles=[]
            lines=[[v/scale for v in line] for line in lines]
            texts=[{**t,"bbox":[v/scale for v in t["bbox"]]} for t in texts]
            result.append({"page":page["page"],"width":width/scale,"height":height/scale,"lines":lines,"line_segments":[[v/scale for v in l] for l in segments],"texts":texts,"epsilon":1.5,"source":"local_ocr","coil_circles":coil_circles,"wire_sections":wire_sections})
            if diameter_geometry:
                result[-1]["diameter_raster"] = (mask, scale)
                result[-1]["source_document_id"] = document["source_document_id"]
    return result


def _section_circles(mask, circles, scale):
    """Require a closed outline with section hatching, excluding open turns."""
    import numpy as np

    height, width = mask.shape
    angles = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    ring = np.linspace(.78, 1.18, 9)[:, None]
    sections = []
    for section in circles:
        x, y, radius = (v * scale for v in section)
        if not (1.2 * radius < x < width - 1.2 * radius and 1.2 * radius < y < height - 1.2 * radius):
            continue
        xs = np.rint(x + ring * radius * np.cos(angles)).astype(int)
        ys = np.rint(y + ring * radius * np.sin(angles)).astype(int)
        if np.any(mask[ys, xs], axis=0).mean() < .85:
            continue
        rows, cols = np.mgrid[int(y-radius):int(y+radius)+1, int(x-radius):int(x+radius)+1]
        disk = (rows-y)**2 + (cols-x)**2 <= (.63*radius)**2
        if disk.any() and .14 <= np.mean(mask[rows[disk], cols[disk]] != 0) <= .65:
            sections.append(section)
    return sections


def _load_ocr_targets(loads,recovered):
    def identity(point):
        return point.get("page",1),str(point.get("label") or "").casefold()
    local={identity(p):p for p in recovered}
    complete={identity(p) for p in recovered if p["height_relation"].get("verified") and not p.get("load_force_conflict")
              and p.get("height_tolerance_status")!="uncertain"}
    drafts={}
    for c in loads:
        key=identity({**c["value"],"page":c.get("page",1)})
        if model_load_relation(c):
            drafts[key]=c["value"]
    supported=complete|set(drafts)
    missing={p["page"] for p in recovered if identity(p) not in supported}
    missing.update(c.get("page",1) for c in loads if identity({**c["value"],"page":c.get("page",1)}) not in supported)
    for key,draft in drafts.items():
        original=local.get(key)
        if original and key not in complete and str(original.get("force_unit") or "").lower()==str(draft.get("force_unit") or "").lower():
            if number(original.get("force"))!=number(draft.get("force")):
                missing.add(key[0])
    missing.update(p["page"] for p in recovered if p.get("load_force_conflict") or p.get("height_tolerance_status")=="uncertain"
                   or p.get("force_tolerance_status")=="uncertain")
    return missing


def ground_job_candidates(job_dir,candidates,raw_payloads, *, warnings=None):
    sources=sorted((Path(job_dir)/"inputs").glob("*"))
    source=next((p for p in sources if p.suffix.lower() in {".pdf",".png",".jpg",".jpeg",".webp",".bmp",".tif",".tiff"}),None)
    if not source:return candidates
    try:
        from .diameter_evidence import diameter_ocr_requests, resolve_diameter_roles, supported_candidates
        verify_diameters = supported_candidates(candidates)
        pdf_points=original_points(source) if source.suffix.lower()==".pdf" else []
        loads=[c for c in candidates if c.get("field")=="load_point" and isinstance(c.get("value"),dict)]
        hints=[{**c["value"],"page":c.get("page",1)} for c in loads]
        pitch_known=next((c for c in candidates if c.get("field")=="pitch" and c.get("value") is not None),{})
        review={"drawing_summary":{"spring_type":"compression_spring"},"spring_parameters":{"pitch":pitch_known}}
        diameter_requests = diameter_ocr_requests(candidates) if verify_diameters else []
        def recover(pages):
            return _merge_original_points(pdf_points,original_points(source,pages=pages,hints=hints))
        pages=raster_pages(Path(job_dir),review,raw_payloads=raw_payloads,warnings=warnings,diameter_geometry=verify_diameters)
        recovered=recover(pages)
        load_ocr_pages=_load_ocr_targets(loads,recovered)
        if diameter_requests or load_ocr_pages or not pitch_known or not (loads or recovered):
            pages=raster_pages(Path(job_dir),review,raw_payloads=raw_payloads,
                               allow_ocr=bool(load_ocr_pages or not pitch_known or not (loads or recovered)),warnings=warnings,
                               diameter_geometry=verify_diameters,diameter_requests=diameter_requests,
                               load_ocr_pages=load_ocr_pages if loads or recovered else None)
            recovered=recover(pages)
        evidence_pages = list(pages)
        if verify_diameters and source.suffix.lower() == ".pdf":
            stat = source.stat()
            limit = max(1, int(os.getenv("QWEN_MAX_PAGES", "3")))
            for vector in _pdf_pages(str(source), stat.st_size, stat.st_mtime_ns, limit):
                raster = next((p for p in pages if p["page"] == vector["page"]), None)
                if raster and abs(vector["width"] / vector["height"] - raster["width"] / raster["height"]) < .02:
                    ratio = vector["height"] / raster["height"]
                    vector = {**vector, "wire_sections": [[v * ratio for v in section] for section in raster["wire_sections"]]}
                    mask, scale = raster["diameter_raster"]
                    vector["diameter_raster"] = (mask, scale / ratio)
                    vector["source_document_id"] = raster["source_document_id"]
                evidence_pages.append(vector)
        if verify_diameters:
            candidates = resolve_diameter_roles(candidates, evidence_pages)
        from .pitch_evidence import pitch_from_pages
        geometry={c.get("field"):c.get("value") for c in candidates if c.get("field") in {"wire_diameter","free_length"} and isinstance(c.get("value"),(int,float))}
        pitch=pitch_from_pages(pages,wire_diameter=geometry.get("wire_diameter"),free_height=geometry.get("free_length"))
        if pitch and not any(c.get("field")=="pitch" for c in candidates):candidates=[*candidates,{**pitch,"source":"local_pitch_evidence","confidence":.97}]
    except Exception as error:
        _verification_warning("upload", error, warnings)
        return candidates
    return [*candidates,*_point_candidates(recovered)]


def _point_candidates(points):
    result=[]
    for point in points:
        value=deepcopy(point)
        result.append({"field":"load_point","value":value,"source":"local_load_evidence","confidence":.99,
                       "evidence":point["evidence"],"page":point["page"],"position":point.get("position"),
                       "source_context":point.get("source_context") or {"kind":"annotation","unit_evidence":point["force_unit"]}})
    return result


def ground_candidates(candidates, source):
    """Attach independently recovered PDF evidence before fusion; model flags are not trusted."""
    if any(c.get("source")=="local_load_evidence" for c in candidates):
        return candidates
    if not source or Path(source).suffix.lower() != ".pdf" or not Path(source).is_file():
        return candidates
    try:
        points=original_points(Path(source))
    except Exception as error:
        _verification_warning("PDF", error)
        return candidates
    return [*candidates,*_point_candidates(points)]


def _read_json(path):
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


def _load_anchor(point):
    geometry=(point.get("height_relation") or {}).get("geometry_evidence") or {}
    return geometry.get("load_anchor")


def _automatic_load_point(point):
    relation=point.get("height_relation") or {}
    sources=point.get("source") or []
    sources=[sources] if isinstance(sources,str) else sources
    if point.get("need_human_review") is False or relation.get("mode")=="manual" or any(re.search(r"human|manual",str(s),re.I) for s in sources):
        return False
    return relation.get("verified") is True or any(re.search(
        r"qwen|rapidocr|baidu|pdf_text|local_load_evidence|^ocr|^cad|^formula|^multi_spec",str(s),re.I) for s in sources)


def reconcile_load_points(review, job_dir):
    """GET-only repair in memory. Normal CAS saving persists the repair and its audit."""
    if review.get("drawing_summary",{}).get("spring_type")!="compression_spring" or review.get("record_kind")=="source":
        return
    job_dir=Path(job_dir)
    sources=sorted((job_dir/"inputs").glob("*"))
    source=next((p for p in sources if p.suffix.lower() in {".pdf",".png",".jpg",".jpeg",".webp",".bmp",".tif",".tiff"}),None)
    if source is None:
        return
    origin=review.get("multi_spec_origin") or {}
    region=origin.get("effective_region") or origin.get("region")
    if origin and not region:
        return
    scope=str(origin.get("variant_id") or "")
    stat=source.stat()
    from .multi_spec import shared_ocr_dir
    def cache_fingerprint(version):
        signatures=[]
        for path in (job_dir/"candidates.json",shared_ocr_dir(job_dir)/"annotation_ocr_v3.json"):
            info=path.stat() if path.is_file() else None
            signatures.append((info.st_size,info.st_mtime_ns) if info else None)
        return hashlib.sha256(f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{version}:{json.dumps(region,sort_keys=True)}:{signatures}".encode()).hexdigest()

    fingerprint=cache_fingerprint(EVIDENCE_VERSION)
    legacy_fingerprints={cache_fingerprint(f"load-evidence/{version}") for version in ("v3","v4","v5")}
    cache_path=job_dir/"load_point_evidence.json"
    cache=_read_json(cache_path)
    from .pitch_evidence import recover_pitch
    pitch_item=(review.get("spring_parameters") or {}).get("pitch") or {}
    repair_pitch=(pitch_item.get("value") in (None,"") or pitch_item.get("formula_calculation_kind")=="pitch") and not any(str(s).startswith(("human_edited","manual")) for s in pitch_item.get("source",[]))
    evidence_pages=None
    verification_warnings=[]
    if repair_pitch:
        try:
            evidence_pages=raster_pages(job_dir,review,allow_ocr=True,warnings=verification_warnings,load_ocr_pages=())
            recover_pitch(review,evidence_pages,region=region)
        except Exception as error:
            _verification_warning("pitch evidence",error,verification_warnings)
    if cache.get("fingerprint")==fingerprint:
        recovered=cache.get("points",[])
    else:
        try:
            hints=(review.get("spring_parameters") or {}).get("load_points") or []
            pdf_points=original_points(source,region=region,scope=scope,hints=hints)
            recovered=pdf_points
            if not recovered or any(not p["height_relation"].get("verified") for p in recovered):
                pages=evidence_pages if evidence_pages is not None else raster_pages(job_dir,review,warnings=verification_warnings)
                recovered=_merge_original_points(pdf_points,original_points(source,region=region,scope=scope,pages=pages,hints=hints))
                automatic=[{"source":p.get("source"),"value":p,"page":p.get("page",1)}
                           for p in hints if _automatic_load_point(p)]
                missing=_load_ocr_targets(automatic,recovered) if automatic or not hints else set()
                if missing or not (hints or recovered):
                    pages=raster_pages(job_dir,review,allow_ocr=True,warnings=verification_warnings,load_ocr_pages=missing or None)
                    recovered=_merge_original_points(pdf_points,original_points(source,region=region,scope=scope,pages=pages,hints=hints))
            if cache.get('fingerprint') in legacy_fingerprints:
                key=lambda p:(p.get('page',1),p.get('label','').casefold(),p.get('force'),p.get('force_unit'))
                successful={key(p):p for p in cache.get('points',[]) if p.get('height_relation',{}).get('verified')}
                for index,p in enumerate(recovered):
                    old=successful.get(key(p))
                    if old and not p['height_relation'].get('verified'):
                        recovered[index]=deepcopy(old)
                    elif old and old['height_relation'].get('kind')==p['height_relation'].get('kind') and old['height_relation'].get('value')==p['height_relation'].get('value'):
                        # Keep established coordinates and source identity when the new evidence agrees.
                        if not any(k in p for k in HEIGHT_FIELDS[1:]):
                            p['height_relation']=deepcopy(old['height_relation'])
                recovered.extend(deepcopy(p) for identity,p in successful.items() if all(key(found)!=identity for found in recovered))
        except Exception as error:
            _verification_warning("saved review", error)
            return
        from .drawing_annotations import atomic_annotation_write
        if not verification_warnings:
            atomic_annotation_write(cache_path,{"version":EVIDENCE_VERSION,"fingerprint":cache_fingerprint(EVIDENCE_VERSION),"points":recovered})
    parameters=review.setdefault("spring_parameters",{})
    points=parameters.setdefault("load_points",[])
    before=deepcopy(points)
    for point in points:
        relation=point.get("height_relation") or {}
        if _automatic_load_point(point) and not relation.get("verified"):
            provisional=model_load_relation({"source":point.get("source"),"value":point,"page":point.get("page",1)})
            if provisional:
                point["height_relation"]={**relation,**provisional}
    expected=deepcopy(review)
    expected["spring_parameters"]["load_points"]=deepcopy(recovered)
    for index,p in enumerate(expected["spring_parameters"]["load_points"]):p["load_point_id"]=f"source_{index}"
    refresh_load_heights(expected)
    expected_heights=[p.get("height") for p in expected["spring_parameters"]["load_points"]]
    meta=review.setdefault("load_point_recovery",{"version":VERSION,"applied_keys":[]})
    seen=set(meta.get("applied_keys") or [])
    for original,expected_height in zip(recovered,expected_heights):
        identity=[original.get("source_document_id") or (original.get("height_relation") or {}).get("source_document_id"),original["page"],scope,original["label"].casefold()]
        anchor=_load_anchor(original)
        repeated=sum(p["page"]==original["page"] and p["label"].casefold()==original["label"].casefold() for p in recovered)>1
        if repeated and anchor:
            identity.append([round(anchor["x"],3),round(anchor["y"],3)])
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:24]
        matches=[p for p in points if str(p.get("label") or "").casefold()==original["label"].casefold() and p.get("page",1)==original["page"]]
        if repeated and anchor and matches:
            nearby=[p for p in matches if (known:=_load_anchor(p)) and abs(known["x"]-anchor["x"])<=.008 and abs(known["y"]-anchor["y"])<=.008]
            if nearby or all(_load_anchor(p) for p in matches):
                matches=nearby
            else:
                continue
        if not matches and not repeated:
            matches=[p for p in points if p.get("page",1)==original["page"] and any(v["label"].casefold()==original["label"].casefold() for v in extract_force_annotations(str(p.get("evidence") or "")))]
        if not matches and original.get("source_context",{}).get("force_label_inferred"):
            same_force=lambda p: p.get("page",1)==original["page"] and number(p.get("force"))==original["force"] and str(p.get("force_unit") or "").casefold()==original["force_unit"].casefold()
            if sum(same_force(p) for p in recovered)==1:
                matches=[p for p in points if same_force(p)]
        if len(matches)>1:
            continue
        if not matches:
            if key in seen or any(e.get("event_type")=="load_point_deleted" and str((e.get("before_state") or {}).get("label","")).casefold()==original["label"].casefold() for e in review.get("change_history",[]) if isinstance(e,dict)):
                continue
            point=deepcopy(original)
            point["load_point_id"]=f"loadpt_evidence_{key}"
            if point["height_relation"].get("kind")=="unknown":point.pop("height_relation")
            points.append(point)
        else:
            point=matches[0]
            relation=point.get("height_relation") or {}
            verified_original=relation.get('verified') and (not relation.get('source_document_id') or relation.get('source_document_id')==original.get('source_document_id'))
            protected=not _automatic_load_point(point)
            existing=millimeters(point.get("height"),point.get("height_unit"))
            if verified_original and not protected and expected_height is not None and expected_height==existing and original.get("force")==point.get("force"):
                if not point.get("height_label") and original.get("height_label"):
                    point["height_label"]=original["height_label"]
                if not any(field in point for field in HEIGHT_FIELDS[1:]):
                    _set_height_fields(point,{field:original[field] for field in HEIGHT_FIELDS[1:] if field in original})
            protected |= bool(verified_original)
            if protected:
                if not relation.get("verified") and existing is not None and existing>0:
                    relation["preserve_existing_value"]=True
                different=any(point.get(k)!=original.get(k) for k in ("force","force_unit","load_tolerance_upper","load_tolerance_lower","load_tolerance_percent"))
                different=different or expected_height is not None and existing!=expected_height
                different=different or any(k in original and point.get(k)!=original[k] for k in HEIGHT_FIELDS[1:])
                if different:
                    point["load_relation_candidate"]={"version":VERSION,"original":{**deepcopy(original),"height":expected_height},"reason":"原图有可核对的载荷/尺寸链；保留已确认或人工修改的数据"}
                else:point.pop("load_relation_candidate",None)
                seen.add(key)
                continue
            prior_force=(point.get("force"),point.get("force_unit"))
            for field in ("force","force_unit","load_tolerance_upper","load_tolerance_lower","load_tolerance_percent","force_tolerance_percent","force_tolerance_status"):
                if not original.get("load_force_conflict"):
                    point[field]=deepcopy(original.get(field))
            for field in ("load_height_conflict","load_relation_conflict","load_force_conflict"):
                if original.get(field):point[field]=True
                else:point.pop(field,None)
            for field in ("force_evidence_verified","force_alternatives"):
                if field in original:point[field]=deepcopy(original[field])
                else:point.pop(field,None)
            if (not original["height_relation"].get("verified") and not original.get("load_force_conflict")
                and prior_force!=(point.get("force"),point.get("force_unit"))
                and relation.get("verification_method")=="qwen_provisional"):
                point["height_relation"]=deepcopy(original["height_relation"])
            if original["height_relation"].get("verified"):
                old=point.get("height_relation") or {}
                point["height_relation"]=deepcopy(original["height_relation"])
                # Stable dependency identity survives point renames/reordering and reopen.
                for field in ("last_inputs","base_point_id"):
                    if field in old:point["height_relation"][field]=deepcopy(old[field])
                _set_height_fields(point,original)
            point["evidence"]=original["evidence"]
            point["need_human_review"]=True
        seen.add(key)
    meta.update(version=VERSION,applied_keys=sorted(seen))
    from .load_points import ensure_load_point_ids
    ensure_load_point_ids(review)
    refresh_load_heights(review)
    if before!=points:
        meaningful=lambda ps:[{k:v for k,v in p.items() if k not in {"load_relation_candidate"}} for p in ps]
        if meaningful(before)!=meaningful(points):
            review["load_height_adjustment"]={"version":VERSION,"before":before,"pending_save":True}


def prepare_recovery_save(review, previous):
    """Keep deletion tombstones and protect new user input against a pending local repair."""
    for adjustment in (review.get("automatic_calculation_adjustments") or {}).values():
        adjustment["pending_save"]=False
    if review.get("pitch_recovery"):
        review["pitch_recovery"]["pending_save"]=False
    if previous.get("load_point_recovery"):
        review["load_point_recovery"]=deepcopy(previous["load_point_recovery"])
    adjustment=previous.get("load_height_adjustment") or {}
    if adjustment.get("pending_save"):
        review["load_height_adjustment"]=deepcopy(adjustment)
        review["load_height_adjustment"].update(pending_save=False,audit_recorded=True)
    else:
        review.pop("load_height_adjustment",None)
