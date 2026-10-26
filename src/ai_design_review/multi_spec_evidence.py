"""Independent, cached table evidence. Raw model regions/parameters stay intact."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unicodedata

VERSION = "multi-spec-evidence/v2"
CACHE_REVISION = 3


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)).upper()).translate(str.maketrans({"—": "-", "－": "-", "–": "-", "／": "/", "₁": "1", "₀": "0"}))


def _read(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def _code_matches(code, text):
    expected, actual = normalized(code), normalized(text)
    # A printed row index is separate from the code; code digits never supply geometry.
    if actual == expected or re.fullmatch(r"\d+[.、]?" + re.escape(expected), actual): return "exact"
    if re.sub(r"(?<=\d)\.(?=/)", "", actual) == expected: return "separator"
    return None


def _blocks(source_dir, document, allow_ocr, retry):
    from .drawing_annotations import ALGORITHM_VERSION, ocr_blocks, pdf_blocks, annotation_file_lock, atomic_annotation_write, _unique_blocks
    payload = _read(source_dir/"candidates.json")
    blocks = ocr_blocks(payload.get("raw_payloads") or {}, document["pages"])
    inputs = list((source_dir/"inputs").glob("*.pdf"))
    if inputs:
        try: blocks.extend(pdf_blocks(inputs[0], len(document["pages"])))
        except Exception: pass
    path = source_dir/"annotation_ocr_v3.json"
    with annotation_file_lock(source_dir, "annotation_ocr.lock"):
        cache = _read(path)
        if cache.get("source_document_id") != document["source_document_id"] or cache.get("cache_format") != 4:
            cache = {"source_document_id": document["source_document_id"], "algorithm_version": ALGORITHM_VERSION, "cache_format": 4, "blocks": [], "full": {}, "regions": {}, "handled_fields": {}, "warnings": []}
        if allow_ocr:
            from PIL import Image, ImageOps
            from .engines.ocr_providers import RapidOcrProvider
            folder = source_dir/"annotation_ocr_pages"; folder.mkdir(exist_ok=True)
            changed = False
            for page in document["pages"]:
                key = str(page["page"])
                if any(b["page"] == page["page"] for b in blocks) or cache["full"].get(key) == "completed" or cache["full"].get(key) == "failed" and not retry: continue
                image_path = source_dir/"pages"/Path(page["image_url"]).name
                target = folder/f"page-{key}.png"
                try:
                    with Image.open(image_path) as image: ImageOps.exif_transpose(image).convert("RGB").save(target)
                    raw = RapidOcrProvider().recognize([target], {})
                    raw[0]["page"] = page["page"]
                    cache["blocks"].extend({**b, "source": "local_ocr"} for b in ocr_blocks({"local": {"raw_pages": raw}}, [page]))
                    cache["full"][key] = "completed"
                except Exception as exc:
                    cache["full"][key] = "failed"
                    cache.setdefault("errors", {})[f"full:{key}"] = type(exc).__name__
                changed = True
            if changed: atomic_annotation_write(path, cache)
        return _unique_blocks(blocks + cache.get("blocks", []))


def _grid(source_dir, page, anchors):
    """Only actual image lines may supply table edges."""
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
        with Image.open(source_dir/"pages"/Path(page["image_url"]).name) as im:
            im=ImageOps.exif_transpose(im).convert("L"); im.thumbnail((1800, 1800)); gray=np.array(im)
        height,width=gray.shape
        mask=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,12)
        horizontal=cv2.morphologyEx(mask,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(30,width//8),1)))
        contours,_=cv2.findContours(horizontal,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cx=sum(b["position"]["x"]+b["position"]["width"]/2 for b in anchors)/len(anchors)
        lines=[]
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            if w/width >= .35 and x/width <= cx <= (x+w)/width:
                lines.append((x/width,(y+h/2)/height,(x+w)/width))
        return sorted(lines,key=lambda l:l[1])
    except (ImportError,OSError,ValueError): return []


def _number(text):
    m=re.search(r"\d+(?:\.\d+)?",str(text))
    return float(m[0]) if m else None


def _composite(block, expected):
    text=normalized(block["text"]).replace("×","X")
    parts=re.split(r"[X*]",text)
    if len(parts)!=3: return False
    values=[_number(p) for p in parts]
    return all(v is not None and abs(v-e)<1e-8 for v,e in zip(values,expected))


def resolve(source, source_dir, *, allow_ocr=True, retry=False):
    multi=source.get("multi_spec") or {}
    if multi.get("layout") != "rows": return {}
    from .drawing_annotations import annotation_source, annotation_file_lock, atomic_annotation_write
    source_dir=Path(source_dir)
    if not (source_dir/"pages").exists(): return {}
    document,_=annotation_source(source_dir,lambda p:f"/api/reviews/{source_dir.name}/artifacts/{p.as_posix()}")
    cache_path=source_dir/"multi_spec_evidence.json"
    ocr_path=source_dir/"annotation_ocr_v3.json"
    input_hash=hashlib.sha256(json.dumps([VERSION,CACHE_REVISION,document["source_document_id"],multi],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with annotation_file_lock(source_dir,"multi_spec_evidence.lock"):
        cache=_read(cache_path)
        stamp=ocr_path.stat().st_mtime_ns if ocr_path.exists() else None
        if not retry and cache.get("input_hash")==input_hash and cache.get("ocr_stamp")==stamp: return cache
        blocks=_blocks(source_dir,document,allow_ocr,retry)
        entries={}; variants=multi.get("variants") or []
        for page in document["pages"]:
            number=page["page"]; body=[b for b in blocks if b["page"]==number]
            anchors=[]
            for variant in variants:
                if variant.get("page",1)!=number or not variant.get("code"): continue
                if sum(v.get("page",1)==number and normalized(v.get("code", ""))==normalized(variant["code"]) for v in variants)!=1: continue
                matches=[(b,_code_matches(variant["code"],b["text"])) for b in body if _code_matches(variant["code"],b["text"])]
                # OCR duplicates refer to the same physical glyph.
                from .drawing_annotations import _same_text_box, _overlap
                matches.sort(key=lambda item: (normalized(item[0]["text"])!=normalized(variant["code"]),item[0]["position"]["width"]*item[0]["position"]["height"]))
                distinct=[]
                for b,method in matches:
                    def same_reading(old):
                        a,c=b["position"],old[0]["position"]
                        indexed_pair=normalized(old[0]["text"])==normalized(variant["code"]) and bool(re.fullmatch(str(variant["order"])+r"[.、]?"+re.escape(normalized(variant["code"])),normalized(b["text"])))
                        return _same_text_box(a,c) or indexed_pair and _overlap(a,c)>.4 and abs(a["y"]+a["height"]/2-c["y"]-c["height"]/2)<=min(a["height"],c["height"])*.5
                    if not any(same_reading(old) for old in distinct): distinct.append((b,method))
                if len(distinct)==1: anchors.append((variant,*distinct[0]))
            if not anchors: continue
            # Independent tables/columns are not combined into a single row sequence.
            clusters=[]
            for item in anchors:
                x=item[1]["position"]["x"]
                cluster=next((c for c in clusters if abs(c[0][1]["position"]["x"]-x)<.04),None)
                if cluster is None: clusters.append([item])
                else: cluster.append(item)
            for cluster in clusters:
                cluster.sort(key=lambda a:a[1]["position"]["y"])
                lines=_grid(source_dir,page,[b for _,b,_ in cluster])
                centers=[b["position"]["y"]+b["position"]["height"]/2 for _,b,_ in cluster]
                for i,(variant,anchor,method) in enumerate(cluster):
                    cy=centers[i]
                    above=[l for l in lines if l[1]<cy]; below=[l for l in lines if l[1]>cy]
                    # A grid row must contain only this independently identified code.
                    top,bottom=(above[-1][1],below[0][1]) if above and below else (None,None)
                    use_grid=top is not None and sum(top<y<bottom for y in centers)==1
                    if use_grid:
                        left=max(above[-1][0],below[0][0]);right=min(above[-1][2],below[0][2])
                    elif len(cluster)>=2:
                        if any(c is not cluster and any(min(centers)<=b["position"]["y"]+b["position"]["height"]/2<=max(centers) for _,b,_ in c) for c in clusters):
                            continue  # Separate side-by-side tables need actual table edges.
                        top=(centers[i-1]+cy)/2 if i else cy-(centers[1]-cy)/2
                        bottom=(cy+centers[i+1])/2 if i+1<len(cluster) else cy+(cy-centers[i-1])/2
                        # Column extent comes from actual row cells/header, not model x coordinates.
                        near=[b["position"] for b in body if top<=b["position"]["y"]+b["position"]["height"]/2<=bottom]
                        left=min(p["x"] for p in near);right=max(p["x"]+p["width"] for p in near)
                    else: continue
                    region={"page":number,"x":max(0,left),"y":max(0,top),"width":min(1,right)-max(0,left),"height":min(1,bottom)-max(0,top)}
                    row=[b for b in body if region["x"]<=b["position"]["x"]+b["position"]["width"]/2<=region["x"]+region["width"] and top<=b["position"]["y"]+b["position"]["height"]/2<=bottom]
                    parameters={**multi.get("common",{}).get("parameters",{}),**variant.get("parameters",{})}
                    def val(field):
                        p=parameters.get(field) or {};return _number(p.get("value")) if isinstance(p,dict) else _number(p)
                    if method=="separator":
                        index_ok=any(normalized(b["text"])==str(variant["order"]) and b["position"]["x"]<anchor["position"]["x"] for b in row)
                        matched=sum(any(re.fullmatch(r"\d+(?:\.\d+)?",normalized(b["text"])) and _number(b["text"])==val(f) for b in row) for f in ("active_coils","total_coils","pitch"))
                        if not index_ok or matched<2: continue
                    entry={"status":"verified","region":region,"method":"grid" if use_grid else "code_neighbors","code_evidence":deepcopy(anchor),"cells":{}}
                    headers=[b for b in body if b["position"]["y"]<min(centers) and re.search(r"D1",normalized(b["text"])) and re.search(r"H[0O]",normalized(b["text"]))]
                    references={**multi.get("common",{}).get("reference_values",{}),**variant.get("reference_values",{})}
                    d1_reference=next((v for k,v in references.items() if normalized(k) in {"DIAMETER_D1","D1"} and isinstance(v,dict)),{})
                    expected=[val("wire_diameter"),val("inner_diameter") or val("outer_diameter") or _number(d1_reference.get("value")),val("free_length")]
                    from .standardizers.hot_coiled import is_hot
                    explicit_standard=(parameters.get("standard_no") or {}).get("value")
                    hot_symbols=is_hot(explicit_standard) if explicit_standard else val("wire_diameter") is not None and val("wire_diameter")>=8
                    if hot_symbols and all(v is not None for v in expected):
                        cells=[b for b in row if _composite(b,expected) and any(b["position"]["x"] <= h["position"]["x"]+h["position"]["width"]/2 <= b["position"]["x"]+b["position"]["width"] for h in headers)]
                        if len(cells)==1:
                            cell=cells[0]
                            entry["diameter_role"]={"field":"inner_diameter","value":expected[1],"header":headers[0]["text"],"cell":deepcopy(cell)}
                            if d1_reference:
                                entry["diameter_role"]["parameter"]=deepcopy(d1_reference)
                            entry["cells"]={f:{**deepcopy(cell),"evidence_value":value,"anchor_kind":"cell"} for f,value in zip(("wire_diameter","inner_diameter","free_length"),expected)}
                    entries[variant["variant_id"]]=entry
        # Public textual requirements have independent named evidence outside rows.
        common_regions=[]
        from .drawing_annotations import _value_matches,_identity
        for field,p in multi.get("common",{}).get("parameters",{}).items():
            if field not in {"material","standard_no"} or not isinstance(p,dict): continue
            for b in blocks:
                if _identity(field,b["text"]) and _value_matches(p.get("value"),b["text"],field):
                    common_regions.append({"page":b["page"],**b["position"]})
        result={"version":VERSION,"cache_revision":CACHE_REVISION,"input_hash":input_hash,"source_document_id":document["source_document_id"],
                "ocr_stamp":ocr_path.stat().st_mtime_ns if ocr_path.exists() else None,"variants":entries,"common_regions":common_regions}
        atomic_annotation_write(cache_path,result)
        return result


def apply_parameters(parameters, entry):
    """New child: reassign only a cell whose D1 role and all nominals agree."""
    result=deepcopy(parameters);role=(entry or {}).get("diameter_role") or {}
    if role.get("field")!="inner_diameter": return result
    old=result.get("outer_diameter") or {}
    if (old.get("value")==role["value"] or role.get("parameter")) and not (result.get("inner_diameter") or {}).get("value"):
        original=old if old.get("value")==role["value"] else role["parameter"]
        result["inner_diameter"]={**original,"evidence":f"{role['header']}；{role['cell']['text']}；D1为内径"}
        if old.get("value")==role["value"]:
            result.pop("outer_diameter",None)
        result["controlled_diameter_field"]={"value":"inner_diameter","evidence":role["header"]}
    return result


def reconcile_review(review, job_dir):
    """Prepare a revisioned draft repair; the API read itself does not save it."""
    from .multi_spec import annotation_context
    meta=review.get("multi_spec_reconciliation") or {}
    if meta.get("version")==VERSION and not meta.get("pending_save"): return False
    context=annotation_context(review,job_dir).get("multi_spec_origin") or {}
    entry=context.get("location_evidence") or {};role=entry.get("diameter_role") or {}
    if role.get("field")!="inner_diameter": return False
    params=review.get("spring_parameters") or {};outer=params.get("outer_diameter") or {}
    reference_only=outer.get("value") is None and (params.get("inner_diameter") or {}).get("value") is None and bool(role.get("parameter"))
    if outer.get("value")!=role["value"] and not reference_only: return False
    from .standardizers.calculation_state import human_override, sources
    def protected(field):
        p=params.get(field) or {}
        confirmed=any(v.get("confirmed") and (k==field or k.endswith("_"+field) or v.get("target_field")==field)
                      for k,v in (review.get("manual_confirmations") or {}).items() if isinstance(v,dict))
        automatic_formula=any(s in {"formula_calculation","derived"} for s in sources(p))
        return p.get("value") is not None and (human_override(p) or p.get("need_human_review") is False and not automatic_formula or p.get("human_confirmed") or "human_confirmed" in sources(p) or confirmed or not p.get("source"))
    if any(protected(f) for f in ("outer_diameter","inner_diameter","mean_diameter")):
        outer["recognition_role_notice"]="原图D1表示内径，当前直径已由人工修改或确认，请核对。"
        return False
    before={f:deepcopy(params.get(f)) for f in ("outer_diameter","inner_diameter","mean_diameter","controlled_diameter_field","accuracy_grade")}
    original=role["parameter"] if reference_only else outer
    params["inner_diameter"]={**deepcopy(original),"field":"inner_diameter","need_human_review":True,
                              "source":list(dict.fromkeys([*sources(original),"qwen_vision","table_role_verification"])),
                              "evidence":f"{role['header']}；{role['cell']['text']}；D1为内径"}
    params.pop("outer_diameter",None)
    params["controlled_diameter_field"]={"value":"inner_diameter","source":["table_role_verification"],"need_human_review":True,"evidence":role["header"]}
    from .standardizers.diameters import apply_formula_compression_diameter_completion
    from .standardizers.stiffness import apply_formula_compression_spring_rate
    apply_formula_compression_diameter_completion(params)
    apply_formula_compression_spring_rate(params,review.get("spring_features") or {})
    from .accuracy_inference import capture, refresh_accuracy_inference
    current=capture(review);inference=review.get("accuracy_inference") or {}
    for key in ("input_snapshot","observed_inputs"):
        if key in inference:
            for field in ("inner_diameter","outer_diameter","mean_diameter","controlled_diameter_field"):
                inference[key][field]=deepcopy(current[field])
    accuracy=params.get("accuracy_grade") or {}
    default_auto=accuracy.get("default_source")=="company_default" and accuracy.get("need_human_review") is not False and not human_override(accuracy)
    if default_auto and inference.get("selection_mode")=="legacy":
        inference["selection_mode"]="auto"
    refresh_accuracy_inference(review,initialize=default_auto)
    for result in review.get("standardization_results") or []: result.update(status="stale",need_human_review=True)
    review["multi_spec_reconciliation"]={"version":VERSION,"pending_save":True,"before":before,
                                         "after":{f:deepcopy(params.get(f)) for f in before},"evidence":deepcopy(role)}
    return True
