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

from .load_height_relations import VERSION, number, millimeters, refresh_load_heights

_PDF_LOCK = RLock()
LOGGER = logging.getLogger(__name__)
EVIDENCE_VERSION = "load-evidence/v2"


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
FORCE = re.compile(rf"(?<![A-Za-z0-9_])(?P<label>[FP]\s*(?:\d+|b))\s*(?:[=＝:：]\s*|\s+)(?P<force>{NUM})(?![\d.])\s*(?P<unit>{UNIT})?\s*(?:(?P<pm>±|\+\s*/\s*-|士)\s*(?P<sym>{NUM})|(?P<up>\+\s*\d+(?:\.\d+)?)\s*(?P<up_unit>{UNIT})?\s*/\s*(?P<down>-\s*\d+(?:\.\d+)?)|(?P<single>[+-]\s*\d+(?:\.\d+)?))?\s*(?P<tail>%|{UNIT})?", re.I)
FREE = re.compile(rf"(?:[LH]\s*[0o₀]|自由(?:高度|长度))\s*[=＝:：]?\s*({NUM})(?![\d.])", re.I)
DIMENSION = re.compile(rf"^\s*([（(]?)\s*({NUM})\s*[）)]?\s*(mm|毫米|cm|m|in)?\s*$", re.I)


def explicit_load_heights(text: str, label: str) -> list[dict[str, Any]]:
    """Read a height identity or 'compressed to', never a compression amount."""
    text = unicodedata.normalize("NFKC", text)
    suffix = re.escape(re.sub(r"^[FPfp]", "", label.strip()))
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<symbol>[HL]\s*{suffix}(?![A-Za-z0-9_])|(?:工作|测试|试验)高度)"
        rf"(?:\s*(?:[=＝:：]|压缩到|壓縮到|压缩至|壓縮至|为|為)\s*|\s+)"
        rf"(?P<value>{NUM})(?![\d.])\s*(?P<unit>mm|毫米|cm|in)?", re.I)
    result=[]
    for clause in re.split(r"[;；。\n]", text):
        labels={p["label"].casefold() for p in extract_force_annotations(clause)}
        if labels and label.casefold() not in labels:
            continue
        for match in pattern.finditer(clause):
            if re.search(r"压缩量|壓縮量|变形量|變形量|行程", clause[:match.start()]):
                continue
            if not re.match(r"[HL]",match["symbol"],re.I) and not re.search(rf"(?<![A-Za-z0-9_]){re.escape(label)}(?![A-Za-z0-9_])",clause,re.I):
                continue
            value=number(match["value"])
            if value is None or value<=0:
                continue
            result.append({"value":value,"unit":match["unit"] or "mm","reference_only":bool(re.search(r"参考|參考",clause)),"evidence":clause.strip()})
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
        if re.match(r"\s*(?:/|·)\s*(?:mm|cm|m)(?![A-Za-z])",text[match.end():],re.I):continue
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
        malformed_suffix = (symmetric is not None or upper is not None) and re.match(r"(?:mm|cm|MPa|kg)(?![A-Za-z])",text[match.end():],re.I)
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
                result.append({"page":index+1,"width":width,"height":height,"texts":texts,"lines":lines,"source":"pdf_text_layer"})
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


def extract_page_points(page: dict[str, Any], *, region=None, document_id="", scope="") -> list[dict[str, Any]]:
    epsilon=page.get("epsilon",.8)
    if region:
        x0,y0=region["x"]*page["width"],region["y"]*page["height"]
        x1,y1=x0+region["width"]*page["width"],y0+region["height"]*page["height"]
        page={**page,"lines":[l for l in page["lines"] if all(x0<=x<=x1 and y0<=y<=y1 for x,y in ((l[0],l[1]),(l[2],l[3])))]}
    texts = _deduplicate_texts([t for t in page["texts"] if _inside(t,page,region)])
    records = []
    for text in texts:
        for point in extract_force_annotations(text["text"]):
            # Only the actual force annotation, not a prose repetition in test instructions.
            if not re.match(r"^\s*[FP]\s*(?:\d+|b)\s*[=＝:：]",text["text"],re.I):
                continue
            point.update(height=None,height_unit="mm",page=page["page"],position=_position(text,page),
                         force_evidence_verified=True,source_document_id=document_id,source=["local_load_evidence"],need_human_review=True)
            point["height_relation"]={"kind":"unknown","mode":"automatic","verified":False,"page":page["page"],"scope":scope,"reason":"原图工作高度的起止关系待核对"}
            records.append((point,text))
    for point,text in records:
        direct=[]
        for t in texts:
            direct.extend((t,value) for value in explicit_load_heights(t["text"],point["label"]))
        signatures={millimeters(value["value"],value["unit"]) for _,value in direct}
        if len(signatures)==1:
            source_text,value=direct[0]
            point["height_relation"]=_relation("absolute_height",value["value"],value["unit"],source_text,page,document_id,scope,any(v["reference_only"] for _,v in direct))
            point["height_relation"]["evidence_refs"]=[ref for t,_ in direct for ref in _relation("absolute_height",value["value"],value["unit"],t,page,document_id,scope)["evidence_refs"]]
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
                match=DIMENSION.fullmatch(unicodedata.normalize("NFKC",t["text"]))
                if not match:
                    continue
                dimension=_dimension(t,page,axis)
                if dimension and full["a"]-1<=dimension["a"]<dimension["b"]<=full["b"]+1 and abs(dimension["cross"]-full["cross"])<length*.6:
                    edges.append((dimension,t,float(match[2]),match[3] or "mm",bool(match[1])))
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
    return [p for p,_ in records]


def _position(text,page):
    x0,y0,x1,y1=text["bbox"]
    return {"coordinate_type":"normalized","origin":"top_left","x":x0/page["width"],"y":y0/page["height"],"width":(x1-x0)/page["width"],"height":(y1-y0)/page["height"]}


def _relation(kind,value,unit,text,page,document_id,scope,reference=False):
    return {"version":VERSION,"kind":kind,"mode":"automatic","value":value,"unit":unit,"reference_only":reference,
            "verified":True,"page":page["page"],"scope":scope,"evidence":text["text"],"source_document_id":document_id,
            "verification_method":"dimension_endpoints" if kind!="absolute_height" else "explicit_height",
            "evidence_refs":[{"page":page["page"],"text":text["text"],"position":_position({"bbox":box},page)} for box in text.get("_source_boxes",[text["bbox"]])]}


def original_points(source: Path, *, region=None, scope="", pages=None) -> list[dict[str, Any]]:
    if pages is None:
        if source.suffix.lower()!=".pdf":
            return []
        stat=source.stat()
        pages=_pdf_pages(str(source.resolve()),stat.st_size,stat.st_mtime_ns,max(1,int(os.getenv("QWEN_MAX_PAGES","3"))))
    document_id=hashlib.sha256(source.read_bytes()).hexdigest()
    return [p for page in pages for p in extract_page_points(page,region=region,document_id=document_id,scope=scope)]


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
        origin=next(p for p in originals if p.get("page",1)==page and p["label"].casefold()==value["label"].casefold() and p["height_relation"].get("scope","")==scope)
        point={**deepcopy(origin),**deepcopy(value)}
        point["height_relation"]=value.get("height_relation") or deepcopy(origin["height_relation"])
        point["need_human_review"]=True
        result.append(point)
    return result


def raster_pages(job_dir, review, *, raw_payloads=None, allow_ocr=False, warnings=None):
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
    blocks=ocr_blocks(payload,pages)
    pool=shared_ocr_dir(job_dir)
    cached=_read_json(pool/"annotation_ocr_v3.json")
    if cached.get("source_document_id")==document["source_document_id"]:
        blocks.extend(cached.get("blocks",[]))
    if allow_ocr and not blocks:
        from .annotation_ocr import local_ocr_blocks
        requests=[{"kind":"load_dimensions","field":f"load_dimensions_{p['page']}","page":p["page"],"evidence_pages":[p["page"]],"status":"unlocated","original_value":0} for p in pages]
        extra,_,_=local_ocr_blocks(pool,pages,document["source_document_id"],review,[],blocks,verification_requests=requests)
        blocks.extend(extra)
    if not blocks:
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
            texts=[]
            for block in blocks:
                if block.get("page")!=page["page"]:continue
                b=block.get("position") or {}
                if not all(k in b for k in ("x","y","width","height")):continue
                texts.append({"text":block["text"],"bbox":[b["x"]*width,b["y"]*height,(b["x"]+b["width"])*width,(b["y"]+b["height"])*height]})
            scale=min(width,height)/595
            lines=[[v/scale for v in line] for line in lines]
            texts=[{**t,"bbox":[v/scale for v in t["bbox"]]} for t in texts]
            result.append({"page":page["page"],"width":width/scale,"height":height/scale,"lines":lines,"texts":texts,"epsilon":1.5,"source":"local_ocr"})
    return result


def ground_job_candidates(job_dir,candidates,raw_payloads, *, warnings=None):
    sources=sorted((Path(job_dir)/"inputs").glob("*"))
    source=next((p for p in sources if p.suffix.lower() in {".pdf",".png",".jpg",".jpeg",".webp",".bmp",".tif",".tiff"}),None)
    if not source:return candidates
    try:
        pdf_points=original_points(source) if source.suffix.lower()==".pdf" else []
        if pdf_points and all(p["height_relation"].get("verified") for p in pdf_points):return candidates
        pages=raster_pages(Path(job_dir),{"drawing_summary":{"spring_type":"compression_spring"},"spring_parameters":{}},raw_payloads=raw_payloads,allow_ocr=True,warnings=warnings)
        recovered=_merge_original_points(pdf_points,original_points(source,pages=pages))
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
                       "source_context":{"kind":"annotation","unit_evidence":point["force_unit"]}})
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
    signatures=[]
    for path in (job_dir/"candidates.json",shared_ocr_dir(job_dir)/"annotation_ocr_v3.json"):
        info=path.stat() if path.is_file() else None
        signatures.append((info.st_size,info.st_mtime_ns) if info else None)
    fingerprint=hashlib.sha256(f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{EVIDENCE_VERSION}:{json.dumps(region,sort_keys=True)}:{signatures}".encode()).hexdigest()
    cache_path=job_dir/"load_point_evidence.json"
    cache=_read_json(cache_path)
    if cache.get("fingerprint")==fingerprint:
        recovered=cache.get("points",[])
    else:
        verification_warnings=[]
        try:
            recovered=original_points(source,region=region,scope=scope)
            if not recovered or any(not p["height_relation"].get("verified") for p in recovered):
                recovered=_merge_original_points(recovered,original_points(source,region=region,scope=scope,pages=raster_pages(job_dir,review,warnings=verification_warnings)))
        except Exception as error:
            _verification_warning("saved review", error)
            return
        from .drawing_annotations import atomic_annotation_write
        if not verification_warnings:
            atomic_annotation_write(cache_path,{"version":EVIDENCE_VERSION,"fingerprint":fingerprint,"points":recovered})
    if not recovered:
        return
    parameters=review.setdefault("spring_parameters",{})
    points=parameters.setdefault("load_points",[])
    before=deepcopy(points)
    expected=deepcopy(review)
    expected["spring_parameters"]["load_points"]=deepcopy(recovered)
    for index,p in enumerate(expected["spring_parameters"]["load_points"]):p["load_point_id"]=f"source_{index}"
    refresh_load_heights(expected)
    expected_heights={(p["page"],p["label"]):p.get("height") for p in expected["spring_parameters"]["load_points"]}
    meta=review.setdefault("load_point_recovery",{"version":VERSION,"applied_keys":[]})
    seen=set(meta.get("applied_keys") or [])
    for original in recovered:
        key=hashlib.sha256(json.dumps([original.get("source_document_id") or (original.get("height_relation") or {}).get("source_document_id"),original["page"],scope,original["label"].casefold()],sort_keys=True).encode()).hexdigest()[:24]
        matches=[p for p in points if str(p.get("label") or "").casefold()==original["label"].casefold() and p.get("page",1)==original["page"]]
        if not matches:
            matches=[p for p in points if p.get("page",1)==original["page"] and any(v["label"].casefold()==original["label"].casefold() for v in extract_force_annotations(str(p.get("evidence") or "")))]
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
            sources=point.get("source") or []
            sources=[sources] if isinstance(sources,str) else sources
            relation=point.get("height_relation") or {}
            recognized_source=any(re.search(r"qwen|rapidocr|baidu|pdf_text|local_load_evidence|^ocr|^cad|^formula|^multi_spec",str(s),re.I) for s in sources)
            automatic=recognized_source or relation.get("verified") is True and relation.get("mode")=="automatic"
            protected=not automatic or point.get("need_human_review") is False or any(re.search(r"human|manual",str(s),re.I) for s in sources) or relation.get("mode")=="manual"
            if protected:
                existing=millimeters(point.get("height"),point.get("height_unit"))
                if not relation.get("verified") and existing is not None and existing>0:
                    relation["preserve_existing_value"]=True
                expected_height=expected_heights.get((original["page"],original["label"]))
                different=any(point.get(k)!=original.get(k) for k in ("force","force_unit","load_tolerance_upper","load_tolerance_lower","load_tolerance_percent"))
                different=different or expected_height is not None and (point.get("height")!=expected_height or point.get("height_unit")!="mm")
                if different:
                    point["load_relation_candidate"]={"version":VERSION,"original":{**deepcopy(original),"height":expected_height},"reason":"原图有可核对的载荷/尺寸链；保留已确认或人工修改的数据"}
                else:point.pop("load_relation_candidate",None)
                seen.add(key)
                continue
            for field in ("force","force_unit","load_tolerance_upper","load_tolerance_lower","load_tolerance_percent","force_tolerance_percent","force_tolerance_status"):
                point[field]=deepcopy(original.get(field))
            for field in ("load_height_conflict","load_relation_conflict"):
                if original.get(field):point[field]=True
                else:point.pop(field,None)
            if original["height_relation"].get("verified"):
                old=point.get("height_relation") or {}
                point["height_relation"]=deepcopy(original["height_relation"])
                # Stable dependency identity survives point renames/reordering and reopen.
                for field in ("last_inputs","base_point_id"):
                    if field in old:point["height_relation"][field]=deepcopy(old[field])
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
    if previous.get("load_point_recovery"):
        review["load_point_recovery"]=deepcopy(previous["load_point_recovery"])
    adjustment=previous.get("load_height_adjustment") or {}
    if adjustment.get("pending_save"):
        review["load_height_adjustment"]=deepcopy(adjustment)
        review["load_height_adjustment"].update(pending_save=False,audit_recorded=True)
    else:
        review.pop("load_height_adjustment",None)
