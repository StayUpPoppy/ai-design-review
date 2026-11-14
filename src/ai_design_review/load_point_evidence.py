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
EVIDENCE_VERSION = "load-evidence/v7"


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

NUM = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
UNIT = r"(?:kN|kgf?|lbf|lbs?|N|牛顿|牛)"
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
        if re.match(r"\s*(?:/|·|per\b)\s*(?:mm|cm|m|in\b|inches\b)(?![A-Za-z])",remainder,re.I):continue
        attached_unit = bool(re.match(r"[A-Za-z]",remainder) and not text[match.end()-1].isspace())
        if attached_unit and not any(match[k] is not None for k in ("sym","up","single")):
            continue
        unit = match["unit"] or (match["tail"] if match["tail"] != "%" else None) or declared_unit
        if not unit:
            continue
        if unit.lower() in {"kg", "lb", "lbs"} and not declared_unit and not re.search(
                r"载荷|负荷|力值|荷重|\b(?:load|force)\b|^[FPW]\d*$", match["label"], re.I):
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
        from .load_units import FORCE_UNITS as factors
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
    pattern=rf"(?:载荷|负荷|力值|\bload\b|\bforce\b)\s*(?:[=:]|为|為)?\s*({NUM}\s*{UNIT})(?![A-Za-z/·]|\s+per\b)"
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
    from .load_point_identity import assign_load_names

    def order(record):
        point,text=record
        return point.pop("_graph_order", (text["bbox"][0],text["bbox"][1]))
    ordered=sorted(records,key=order)
    for point,_ in ordered:
        if not point.get("label"):
            point.setdefault("source_context",{})["force_label_inferred"]=True
        if not point.get("height_label"):
            point.setdefault("source_context", {})["height_label_inferred"] = True
    assign_load_names([point for point, _ in ordered])
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
    texts = _load_texts([t for t in page["texts"] if not t.get("diameter_crop_slot") and _inside(t,page,region)])
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
        if hint.get("page",1)!=page["page"] or number(hint.get("force")) is None:continue
        if hint.get("label") and any(p["label"].casefold()==str(hint["label"]).casefold() for p,_ in records):continue
        if sum(h.get("page",1)==page["page"] and h.get("force")==hint.get("force") for h in hints)>1:continue
        match=table_height(hint,texts)
        if match and not match.get("conflict"):
            point=deepcopy(hint)
            point.update(page=page["page"],source_document_id=document_id,source=["local_load_evidence"],need_human_review=True)
            # A table match proves the value pair. A draft name still requires original text.
            from .load_point_identity import explicit_label
            point["source_context"] = {**(hint.get("source_context") or {}),
                                       "force_label_inferred": not bool(explicit_label({**hint, "source": hint.get("source") or "qwen_vision"}))}
            point["position"]=_position(match["force_cell"],page)
            records.append((point,match["force_cell"]))
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
            point["evidence"] = table["evidence"]
            point["force_evidence_verified"] = True
            point["source_context"]={**(point.get("source_context") or {}), "kind":"table",
                                     "row_text":table["evidence"],"unit_evidence":"mm; "+(point.get("force_unit") or "N")}
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
    from .fusion import _merge_load_point, _station_names
    from .load_point_identity import group_load_points

    result = []
    for group in group_load_points(_point_candidates([*primary, *supplementary])):
        origin = group[0]["value"]
        names = _station_names(group)
        label = names["label"] or origin["label"]
        entry = _merge_load_point(label, group, [])
        point = {**deepcopy(origin), **deepcopy(entry["value"]), "evidence": entry["evidence"],
                 "source_context": entry["source_context"], "need_human_review": True}
        if names["height_label"]:
            point["height_label"] = names["height_label"]
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
                if block.get("diameter_crop_slot") and not diameter_geometry:continue
                b=block.get("position") or {}
                if not all(k in b for k in ("x","y","width","height")):continue
                texts.append({"text":block["text"],"bbox":[b["x"]*width,b["y"]*height,(b["x"]+b["width"])*width,(b["y"]+b["height"])*height],
                              **{key: block[key] for key in ("diameter_offset_origin", "diameter_offset_slot", "diameter_crop_origin", "diameter_crop_slot") if key in block}})
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
    from . import load_point_identity as identity

    missing = set()
    for group in identity.group_load_points([*loads, *recovered]):
        if any(identity.value(p).get("load_force_conflict") or identity.value(p).get("load_height_conflict")
               or identity.value(p).get("height_tolerance_status") == "uncertain"
               or identity.value(p).get("force_tolerance_status") == "uncertain" for p in group):
            missing.add(identity.scope(group[0])[0])
        elif not any(identity.relation(point).get("verified") or model_load_relation(point if "value" in point else {**point, "value": point}) for point in group):
            missing.add(identity.scope(group[0])[0])
    return missing


def ground_job_candidates(job_dir,candidates,raw_payloads, *, warnings=None, drawing_units=None):
    sources=sorted((Path(job_dir)/"inputs").glob("*"))
    source=next((p for p in sources if p.suffix.lower() in {".pdf",".png",".jpg",".jpeg",".webp",".bmp",".tif",".tiff"}),None)
    if not source:return candidates
    try:
        from .diameter_evidence import INFERENCE, diameter_ocr_requests, resolve_diameter_roles, supported_candidates
        from .diameter_recovery import attach_callout_blocks, locatable_callout_keys, recover_diameters
        verify_diameters = supported_candidates(candidates)
        pdf_points=original_points(source) if source.suffix.lower()==".pdf" else []
        loads=[c for c in candidates if c.get("field")=="load_point" and isinstance(c.get("value"),dict)]
        # The OCR adapter extracts these candidates from concatenated page text.
        # Their shared anchor cannot compete with a specific table row.
        aggregate_loads = [candidate for payload in raw_payloads.values()
                           if isinstance(payload, dict) and payload.get("provider") and payload.get("texts")
                           for candidate in payload.get("candidates") or []
                           if candidate.get("field") == "load_point" and isinstance(candidate.get("value"), dict)]
        def force_key(candidate):
            value = candidate["value"]
            return (candidate.get("page", 1), number(value.get("force")), str(value.get("force_unit") or "").casefold())

        specific_forces = {force_key(candidate) for candidate in loads if candidate not in aggregate_loads}
        hints = [{**candidate["value"], "page": candidate.get("page", 1), "source": candidate.get("source"),
                  "evidence": candidate.get("evidence"), "source_context": candidate.get("source_context") or {}} for candidate in loads
                 if candidate not in aggregate_loads or force_key(candidate) not in specific_forces]
        pitch_known=next((c for c in candidates if c.get("field")=="pitch" and c.get("value") is not None),{})
        review={"drawing_summary":{"spring_type":"compression_spring"},"spring_parameters":{"pitch":pitch_known}}
        def recover(pages):
            return _merge_original_points(pdf_points,original_points(source,pages=pages,hints=hints))
        pages=raster_pages(Path(job_dir),review,raw_payloads=raw_payloads,warnings=warnings,diameter_geometry=verify_diameters)
        vectors = []
        if verify_diameters and source.suffix.lower() == ".pdf":
            stat = source.stat()
            limit = max(1, int(os.getenv("QWEN_MAX_PAGES", "3")))
            vectors = _pdf_pages(str(source), stat.st_size, stat.st_mtime_ns, limit)
        from .engineering_units import apply_drawing_units
        evidence_pages = _diameter_pages(pages, vectors)
        scoped = apply_drawing_units(candidates, raw_payloads, evidence_pages, drawing_units=drawing_units)
        diameter_requests = diameter_ocr_requests(scoped) if verify_diameters else []
        baseline = None
        if diameter_requests and pages:
            baseline = resolve_diameter_roles(scoped, evidence_pages)
            needed = {(c.get("page", 1), c["value"]["value"]) for c in baseline if c.get("field") == INFERENCE}
            if needed:
                table_matches = recover_diameters(scoped, baseline, evidence_pages, allow_callouts=False)[len(baseline):]
                needed.difference_update((c.get("page", 1), c["value"]) for c in table_matches)
                targeted_pages = {page for page, value in locatable_callout_keys(scoped, pages) & needed}
                needed = {(page, value) for page, value in needed if page not in targeted_pages}
            diameter_requests = [r for r in diameter_requests if (r["page"], r["original_value"]) in needed]
        recovered=recover(pages)
        load_ocr_pages=_load_ocr_targets(loads,recovered)
        if diameter_requests or load_ocr_pages or not pitch_known or not (loads or recovered):
            pages=raster_pages(Path(job_dir),review,raw_payloads=raw_payloads,
                               allow_ocr=bool(load_ocr_pages or not pitch_known or not (loads or recovered)),warnings=warnings,
                               diameter_geometry=verify_diameters,diameter_requests=diameter_requests,
                               load_ocr_pages=load_ocr_pages if loads or recovered else None)
            recovered=recover(pages)
            evidence_pages = _diameter_pages(pages, vectors)
            scoped = apply_drawing_units(candidates, raw_payloads, evidence_pages, drawing_units=drawing_units)
            baseline = None
        candidates = scoped
        if verify_diameters:
            from .annotation_ocr import diameter_callout_blocks
            if baseline is None:
                baseline = resolve_diameter_roles(candidates, evidence_pages)
            resolved = recover_diameters(candidates, baseline, evidence_pages)
            try:
                requested_pages = {request["page"] for request in diameter_requests}
                local_pages = [page for page in pages if page["page"] not in requested_pages]
                if blocks := diameter_callout_blocks(Path(job_dir), local_pages, candidates, baseline):
                    attach_callout_blocks(pages, blocks)
                    resolved = recover_diameters(candidates, baseline, evidence_pages)
            except Exception:
                LOGGER.warning("Diameter callout OCR failed for %s", job_dir, exc_info=True)
            candidates = resolved
        from .pitch_evidence import pitch_from_pages
        geometry={c.get("field"):c.get("value") for c in candidates if c.get("field") in {"wire_diameter","free_length"} and isinstance(c.get("value"),(int,float))}
        pitch=pitch_from_pages(pages,wire_diameter=geometry.get("wire_diameter"),free_height=geometry.get("free_length"))
        if pitch and not any(c.get("field")=="pitch" for c in candidates):candidates=[*candidates,{**pitch,"source":"local_pitch_evidence","confidence":.97}]
    except Exception as error:
        _verification_warning("upload", error, warnings)
        return candidates
    table_keys = {(p["page"], number(p.get("force")), str(p.get("force_unit") or "").casefold(),
                   re.sub(r"\d+$", "", p.get("label") or "").casefold()) for p in recovered
                  if p.get("height_relation", {}).get("verification_method") == "table_cells" and p.get("force_evidence_verified")}
    redundant = [candidate for candidate in aggregate_loads if
                 (*force_key(candidate), str(candidate["value"].get("label") or "").casefold()) in table_keys]
    candidates = [candidate for candidate in candidates if candidate not in redundant]
    return [*candidates,*_point_candidates(recovered)]


def _diameter_pages(pages, vectors):
    merged = list(pages)
    raster_by_page = {page["page"]: page for page in pages}
    for vector in vectors:
        raster = raster_by_page.get(vector["page"])
        if raster and abs(vector["width"] / vector["height"] - raster["width"] / raster["height"]) < .02:
            ratio = vector["height"] / raster["height"]
            mask, scale = raster["diameter_raster"]
            vector = {**vector, "wire_sections": [[v * ratio for v in section] for section in raster["wire_sections"]],
                      "diameter_raster": (mask, scale / ratio), "source_document_id": raster["source_document_id"]}
        merged.append(vector)
    return merged


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


_PROTECTED_LOAD_EVENTS = {"load_point_value_updated", "load_point_tolerance_updated", "load_point_added",
                          "load_point_restored", "load_point_confirmed"}


def _protected_load_ids(review, points):
    confirmations = review.get("manual_confirmations") or {}
    protected = {point.get("load_point_id") for index, point in enumerate(points)
                 if not _automatic_load_point(point) or confirmations.get(f"load_point_{point.get('load_point_id')}")
                 or confirmations.get(f"load_points_{index}")}
    for event in review.get("change_history") or []:
        if not isinstance(event, dict) or event.get("event_type") not in _PROTECTED_LOAD_EVENTS:
            continue
        metadata = event.get("metadata") or {}
        point_id = metadata.get("load_point_id") or (event.get("after_state") or {}).get("load_point_id")
        if point_id:
            protected.add(point_id)
        elif (target := str(event.get("target_field") or "")).startswith("load_point_"):
            protected.add(target.removeprefix("load_point_"))
        elif match := re.fullmatch(r"load_points_(\d+)", target):
            index = int(match[1])
            if index < len(points):
                protected.add(points[index].get("load_point_id"))
    return protected


def _saved_original_loads(snapshot, source, scope):
    from .page_images import fingerprint

    candidates = [candidate for candidate in snapshot.get("candidates", [])
                  if candidate.get("field") == "load_point" and candidate.get("source") == "local_load_evidence"]
    if not candidates:
        return []
    document = fingerprint(source)
    originals = []
    for candidate in candidates:
        point = candidate.get("value") or {}
        relation = point.get("height_relation") or {}
        if (relation.get("verified") and relation.get("scope", "") == scope
                and (point.get("source_document_id") or relation.get("source_document_id")) == document):
            originals.append({**point, "source": ["local_load_evidence"], "evidence": candidate.get("evidence") or point.get("evidence", ""),
                              "source_context": candidate.get("source_context") or point.get("source_context") or {}})
    return originals


def _collapse_saved_load_duplicates(review, points):
    from . import load_point_identity as identity
    from .fusion import _merge_load_point, _station_names

    protected = _protected_load_ids(review, points)
    remapped = {}
    retired_ids = {}
    replaced = {}
    for group in identity.group_load_points(points):
        ids = {point.get("load_point_id") for point in group}
        if len(group) < 2 or None in ids or ids & protected:
            continue
        if any(identity.relation(point).get("base_point_id") in ids for point in group):
            continue
        survivor = max(group, key=lambda point: (bool(identity.station_position(point)), bool(identity.relation(point).get("verified"))))
        survivor_id = survivor["load_point_id"]
        removed = ids - {survivor_id}
        aliases = {str(point["label"]).casefold() for point in group if point.get("label")}
        if any(point.get("load_point_id") in protected and (
            identity.relation(point).get("base_point_id") in ids or not identity.relation(point).get("base_point_id")
            and identity.scope(point) == identity.scope(survivor)
            and str(identity.relation(point).get("base_label") or "").casefold() in aliases
        ) for point in points):
            continue
        names = _station_names([{"value": p, "source": p.get("source", []), "confidence": p.get("confidence", 0),
                                "evidence": p.get("evidence", "")} for p in group])
        label = names["label"] or survivor["label"]
        renamed = aliases - {label.casefold()}
        references = [point for point in points if identity.relation(point).get("base_point_id") in removed
                      or not identity.relation(point).get("base_point_id") and identity.scope(point) == identity.scope(survivor)
                      and str(identity.relation(point).get("base_label") or "").casefold() in renamed]
        if any(point.get("load_point_id") in protected for point in references):
            continue
        if any(not identity.relation(point).get("base_point_id") and sum(
            identity.scope(other) == identity.scope(point) and str(other.get("label") or "").casefold()
            == str(identity.relation(point).get("base_label") or "").casefold() for other in points
        ) != 1 for point in references):
            continue

        candidates = [{**point, "value": point, "source_context": point.get("source_context") or {}} for point in group]
        merged = _merge_load_point(label, candidates, [])
        fused = {**survivor, **merged["value"], "source": merged["source"], "evidence": merged["evidence"],
                 "source_context": {**(survivor.get("source_context") or {}), "merged_labels": sorted(aliases),
                                    "force_label_inferred": not names["label"], "height_label_inferred": not names["height_label"]},
                 "need_human_review": True}
        fused["height_label"] = names["height_label"] or survivor.get("height_label")
        for point in references:
            remapped[point["load_point_id"]] = (survivor_id, label)
        replaced[survivor_id] = fused
        replaced.update(dict.fromkeys(removed))
        retired_ids.update(dict.fromkeys(removed, (survivor_id, label)))

    if not replaced:
        return
    # Legacy confirmation keys are positional. Preserve their already promoted
    # stable keys before shifting any rows.
    confirmations = review.get("manual_confirmations") or {}
    for index, point in enumerate(points):
        if isinstance(old := confirmations.pop(f"load_points_{index}", None), dict):
            confirmations.setdefault(f"load_point_{point['load_point_id']}", {**old, "load_point_id": point["load_point_id"]})
    points[:] = [replacement for point in points if (replacement := replaced.get(point["load_point_id"], point)) is not None]
    for point in points:
        if target := (retired_ids.get(identity.relation(point).get("base_point_id")) or remapped.get(point["load_point_id"])):
            point["height_relation"].update(base_point_id=target[0], base_label=target[1])


def _deleted_load_station(review, original, recovered, snapshot):
    from . import load_point_identity as identity

    for event in review.get("change_history") or []:
        if not isinstance(event, dict) or event.get("event_type") != "load_point_deleted":
            continue
        before = event.get("before_state") or {}
        label = str(before.get("label") or "").casefold()
        if not label:
            continue
        named = [point for point in recovered if point["label"].casefold() == label]
        if len(named) == 1 and named[0] is original:
            return True
        matched = set()
        for candidate in snapshot.get("candidates", []):
            if (candidate.get("field") != "load_point" or str(identity.value(candidate).get("label") or "").casefold() != label
                    or identity.readings(candidate) != identity.readings(before)):
                continue
            matches = identity.unique_match(candidate, recovered, [*recovered, candidate])
            if len(matches) == 1:
                matched.add(id(matches[0]))
        if matched == {id(original)}:
            return True
    return False


def reconcile_saved_load_duplicates(review):
    """Project an already evidenced merge in memory, without OCR or file writes."""
    if review.get("drawing_summary", {}).get("spring_type") != "compression_spring" or review.get("record_kind") == "source":
        return
    points = review.get("spring_parameters", {}).get("load_points") or []
    if len(points) < 2:
        return
    from .load_points import ensure_load_point_ids
    ensure_load_point_ids(review)
    before = deepcopy(points)
    _collapse_saved_load_duplicates(review, points)
    if len(points) < len(before):
        refresh_load_heights(review)
        review["load_height_adjustment"] = {"version": EVIDENCE_VERSION, "before": before, "pending_save": True}


def reconcile_load_points(review, job_dir, *, merge_saved_duplicates=True):
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
    legacy_fingerprints={cache_fingerprint(f"load-evidence/{version}") for version in ("v3","v4","v5","v6")}
    cache_path=job_dir/"load_point_evidence.json"
    cache=_read_json(cache_path)
    snapshot = _read_json(job_dir / "candidates.json")
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
            automatic=[{**p,"value":p} for p in hints if _automatic_load_point(p)]
            saved = _saved_original_loads(snapshot, source, scope)
            pdf_points = saved if saved and not _load_ocr_targets(automatic, saved) else original_points(source,region=region,scope=scope,hints=hints)
            recovered=pdf_points
            if not recovered or any(not p["height_relation"].get("verified") for p in recovered):
                pages=evidence_pages if evidence_pages is not None else raster_pages(job_dir,review,warnings=verification_warnings)
                recovered=_merge_original_points(pdf_points,original_points(source,region=region,scope=scope,pages=pages,hints=hints))
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
    if merge_saved_duplicates:
        _collapse_saved_load_duplicates(review, points)
    from . import load_point_identity as identity
    protected_ids = _protected_load_ids(review, points)
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
        identity_parts=[original.get("source_document_id") or (original.get("height_relation") or {}).get("source_document_id"),original["page"],scope,original["label"].casefold()]
        anchor=_load_anchor(original)
        repeated=sum(p["page"]==original["page"] and p["label"].casefold()==original["label"].casefold() for p in recovered)>1
        if repeated and anchor:
            identity_parts.append([round(anchor["x"],3),round(anchor["y"],3)])
        key=hashlib.sha256(json.dumps(identity_parts,sort_keys=True).encode()).hexdigest()[:24]
        comparable = {**original, "height": expected_height} if expected_height is not None else original
        known = [*recovered, *points]
        matches = identity.unique_match(comparable, points, known)
        if len(matches) == 1 and identity.match_rank(comparable, matches[0], known) == 1 and len(identity.unique_match(matches[0], recovered, known)) != 1:
            continue
        if not matches and not repeated and identity.explicit_label(original):
            # Legacy records may contain the same original symbol before label provenance existed.
            matches = [point for point in points if point.get("page", 1) == original["page"]
                       and not identity.station_position(point)
                       and (str(point.get("label") or "").casefold() == original["label"].casefold()
                            or any(mark["label"].casefold() == original["label"].casefold()
                                   for mark in extract_force_annotations(str(point.get("evidence") or ""))))]
        if len(matches)>1:
            continue
        if not matches:
            if key in seen or _deleted_load_station(review, original, recovered, snapshot):
                continue
            point=deepcopy(original)
            point["load_point_id"]=f"loadpt_evidence_{key}"
            if point["height_relation"].get("kind")=="unknown":point.pop("height_relation")
            points.append(point)
        else:
            point=matches[0]
            relation=point.get("height_relation") or {}
            verified_original=relation.get('verified') and (not relation.get('source_document_id') or relation.get('source_document_id')==original.get('source_document_id'))
            protected=point.get("load_point_id") in protected_ids or not _automatic_load_point(point)
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


def align_pending_load_recovery(review, previous, events):
    """Reject edits from a stale view of a row already merged on the server."""
    from .load_points import load_point_snapshot

    adjustment = previous.get("load_height_adjustment") or {}
    if not adjustment.get("pending_save"):
        return
    retained = {p.get("load_point_id") for p in previous.get("spring_parameters", {}).get("load_points", [])}
    retired = {p["load_point_id"]: p for p in adjustment.get("before", []) if p.get("load_point_id") and p["load_point_id"] not in retained}
    if not retired:
        return
    points = review.get("spring_parameters", {}).get("load_points") or []
    touched = {(e.get("metadata") or {}).get("load_point_id") for e in events if e.get("event_type") in _PROTECTED_LOAD_EVENTS}
    for point in points:
        point_id = point.get("load_point_id")
        if point_id not in retired:
            continue
        baseline = load_point_snapshot(retired[point_id])
        current = load_point_snapshot(point)
        baseline.pop("height_relation", None)
        current.pop("height_relation", None)
        if point_id in touched or current != baseline:
            raise ValueError("载荷测点已合并，请刷新后核对并保存原测点的修改。")
    points[:] = [point for point in points if point.get("load_point_id") not in retired]
