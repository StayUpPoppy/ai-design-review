"""File-level multi-spec recognition and model-free child review construction."""
from copy import deepcopy
import hashlib
import json
import math
import re
from pathlib import Path
import uuid


class MultiSpecError(ValueError):
    pass


MULTI_SPEC_PROMPT = '''
多规格判断：普通多视图、同一弹簧的尺寸/载荷表仍是single。独立规格表的每行、各自重复完整参数表头的独立计算区块均分别为规格；即使几个区块线径/中径/自由高度/圈数相同，仅工况不同，也逐块保留。单规格沿用以上JSON。
发现多规格时只返回此结构，禁止把多套数据填入顶层parameters：
{"document_mode":"multi","layout":"rows或blocks","complete":true,"spec_count":13,"drawing_summary":{"drawing_name":"","drawing_no":""},"common":{"applies_to_all":true,"parameters":{},"technical_requirements":[],"regions":[]},"variants":[{"code":"原图规格代号，可空","page":1,"region":{"x":0.1,"y":0.2,"width":0.8,"height":0.04},"source_context":{"table_title":"","headers":[],"row_text":"可见整行原文","unit_evidence":""},"parameters":{},"load_points":[],"technical_requirements":[],"reference_values":{}}]}
region仅在明确定位时填写，使用显示方向原页左上角归一化坐标，不能猜坐标。每个规格的parameters/load_points/technical_requirements采用上面的单规格字段结构，保留页码、原文、单位、公差；表格按行、区块按从左到右再从上到下的原顺序。最多50种，所有实际规格必须列全；无法列全complete=false，不静默省略。common只放有明确全体适用依据的材料、标准和技术要求，其regions保留公共依据位置。单元格不清晰可为空，不借用相邻行。规格代号不得代替整图图号。F/P字母依表头单位判断角色；变形量填写load_points.deflection及deflection_unit，力填force，不能将变形量直接作为height；极限工况使用普通标签，只有明确压并才用Fb。压力分级和表内计算结果放reference_values，不填accuracy_grade或用它覆盖系统公式。表面处理仍按公司目录完整中文转换。
混合弹簧类型或不能判断规格划分时返回document_mode=uncertain并保留原因，不猜成一套参数。
先判断单/多规格，再选择JSON结构。多规格parameters只列实际识别的字段，缺失字段直接省略，不逐行复制整套空字段；公共信息只放common。原文及表头简洁保存，不重复长篇分析，不省略规格或工程条件。单规格可显式返回document_mode=single。
'''


def box(value):
    if not isinstance(value, dict): return None
    values = [value.get(k) for k in ("x", "y", "width", "height")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values): return None
    x, y, w, h = values
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 1.000001 or y+h > 1.000001: return None
    return dict(zip(("x", "y", "width", "height"), values))


def number(value):
    if isinstance(value, dict): value = value.get("value")
    return float(value) if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) else None


def local_multi_spec_hint(raw_payloads, candidates):
    """Detect strong layout evidence only; never create parameters from it.

    Reuse completed OCR/PDF text, without another OCR/model call. Composite
    dimension cells in a specification table and repeated complete block labels
    are distinct from an ordinary single-spring force/height table.
    """
    import unicodedata
    pages = {}
    seen = set()

    def append(item):
        if not isinstance(item, dict): return
        content = item.get("text")
        if content is None and str(item.get("field", "")).startswith("document_text"): content = item.get("value")
        if not isinstance(content, str): return
        page = item.get("page") or 1
        for text in content.splitlines():
            text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
            if not text: continue
            pos = item.get("position") if isinstance(item.get("position"), dict) else {}
            identity = (str(page), text, pos.get("x"), pos.get("y"))
            if identity in seen: continue
            seen.add(identity); pages.setdefault(str(page), []).append((text, pos))

    def walk(value):
        if isinstance(value, dict):
            for item in value.get("texts") or []: append(item)
            for child in value.get("raw_pages") or []: walk(child)
            for item in value.get("candidates") or []: append(item)
        elif isinstance(value, list):
            for item in value: append(item)

    for value in raw_payloads.values(): walk(value)
    for value in candidates: append(value)
    composite = re.compile(r"^[ΦφØø⌀$]?\d+(?:\.\d+)?[xX×*].*[xX×*][ΦφØø⌀$]?\d")
    labels = (r"(?:簧丝直径|钢丝直径|线径)[dD]?", r"中径[Dd]?", r"自由(?:高度|长度)[HLhl]?[0oO]?", r"(?:总|有效)圈数[nN]?1?")
    for page, entries in pages.items():
        text = "\n".join(t for t, _ in entries)
        cells = [(t, p) for t, p in entries if composite.match(t)]
        has_header = "规格" in text and ("圈数" in text or re.search(r"d[x×*]D1?[x×*]H[0o]", text, re.I))
        located = [p for _, p in cells if all(isinstance(p.get(k), (int, float)) for k in ("x", "y", "width", "height"))]
        rows = 0
        for anchor in located:
            column = sorted((p for p in located if abs(p["x"]-anchor["x"]) <= max(p["width"], anchor["width"])*.5), key=lambda p: p["y"])
            independent = []
            for p in column:
                if not independent or p["y"]-independent[-1]["y"] > max(p["height"],independent[-1]["height"])*.5: independent.append(p)
            rows = max(rows, len(independent))
        if not located: rows = len({t.replace("×", "x").lower() for t, _ in cells})
        if has_header and rows >= 2:
            return {"page": page, "kind": "rows", "observed_count": rows, "reason": "规格表含多行独立的复合几何尺寸"}
        repeated = 0
        for pattern in labels:
            matches = [(t, p) for t, p in entries if re.fullmatch(pattern, t)]
            # Prefer position-bearing OCR; whole-page text duplicates are not
            # additional blocks, and a label inside a sentence is not a header.
            locations = {(p.get("x"), p.get("y")) for _, p in matches if p.get("x") is not None and p.get("y") is not None}
            if len(locations) >= 2: repeated += 1
        if repeated >= 3:
            return {"page": page, "kind": "blocks", "reason": "多个参数区块重复包含线径、中径、自由高度或圈数表头"}
    return None


def parse_multi_spec(payload, page_count=None):
    if not isinstance(payload, dict): return None
    mode = payload.get("document_mode")
    if mode == "uncertain": raise MultiSpecError("无法确定规格划分，请提供更清晰图纸后重试。")
    if mode != "multi":
        if payload.get("variants"): raise MultiSpecError("多规格结果缺少明确文档类型。")
        if re.search(r"(?<![不未])(?:包含|共有|包括|共)\s*(?:[2-9]\d*|1\d+|[两二三四五六七八九十]+)\s*(?:种规格|个规格|组(?:独立)?(?:参数|工况))", str(payload.get("notes") or "")):
            raise MultiSpecError("模型说明包含多种规格，但未返回完整规格集合，不能作为单规格使用。请重试或拆分文件。")
        return None
    family = payload.get("spring_type", "compression_spring")
    if isinstance(family, dict): family = family.get("value")
    if family != "compression_spring": raise MultiSpecError("首期仅支持压缩弹簧多规格。")
    variants = payload.get("variants")
    if payload.get("complete") is not True or not isinstance(variants, list) or not 2 <= len(variants) <= 50 or payload.get("spec_count") != len(variants):
        raise MultiSpecError("多规格结果不完整或超过50种，请拆分文件后重试。")
    if payload.get("layout") not in {"rows", "blocks"}: raise MultiSpecError("无法确定规格表格/区块布局。")
    common = payload.get("common") or {}
    if not isinstance(common, dict): raise MultiSpecError("公共参数格式无效。")
    if common.get("applies_to_all") is not True: common = {}
    if not isinstance(common.get("parameters", {}), dict) or not isinstance(common.get("technical_requirements", []), list):
        raise MultiSpecError("公共参数/技术要求格式无效。")
    common = deepcopy(common)
    common_refs = common.get("reference_values") or {}
    if not isinstance(common_refs, dict): raise MultiSpecError("公共计算参考格式无效。")
    for key in ("spring_rate", "shear_stress", "spring_index", "stress"):
        if key in common.get("parameters", {}): common_refs[key] = common["parameters"].pop(key)
    common["reference_values"] = common_refs
    result = {"version": 1, "layout": payload["layout"], "common": deepcopy(common), "variants": []}
    for index, value in enumerate(variants):
        if not isinstance(value, dict) or not isinstance(value.get("parameters", {}), dict): raise MultiSpecError("规格参数格式无效。")
        if any(not isinstance(value.get(key, []), list) for key in ("load_points", "technical_requirements", "issues")):
            raise MultiSpecError("规格载荷/技术要求格式无效。")
        if not isinstance(value.get("source_context", {}), dict): raise MultiSpecError("规格来源格式无效。")
        family = value.get("spring_type", "compression_spring")
        if isinstance(family, dict): family = family.get("value")
        if family != "compression_spring": raise MultiSpecError("首期仅支持压缩弹簧多规格，不支持混合类型。")
        page = value.get("page", 1)
        if isinstance(page, bool) or not isinstance(page, int) or page < 1 or page_count and page > page_count: raise MultiSpecError("规格页码无效。")
        region = box(value.get("region"))
        item = deepcopy(value)
        item.update(variant_id="variant_"+uuid.uuid4().hex[:20], order=index+1, code=str(value.get("code") or "").strip(), page=page, region=region)
        item["issues"] = [str(v) for v in value.get("issues", []) if isinstance(v, str)]
        refs = deepcopy(item.get("reference_values") or {})
        if not isinstance(refs, dict): raise MultiSpecError("计算参考格式无效。")
        for key in ("spring_rate", "shear_stress", "spring_index", "stress"):
            if key in item.get("parameters", {}): refs[key] = item["parameters"].pop(key)
        item["reference_values"] = refs
        combined = {**common.get("parameters", {}), **item.get("parameters", {})}
        for key, label in (("wire_diameter", "线径"), ("free_length", "自由高度"), ("total_coils", "总圈数"), ("active_coils", "有效圈数")):
            if number(combined.get(key)) is None: item["issues"].append(label+"缺失或无法判读。")
        if not any(number(combined.get(key)) for key in ("inner_diameter", "outer_diameter", "mean_diameter")):
            item["issues"].append("三径角色或数值待核对，未猜测直径类型。")
        if not region: item["issues"].append("原图区域待定位；此规格不自动跨区域定位气泡。")
        result["variants"].append(item)
    return result


def source_review(payload, multi):
    summary = deepcopy(payload.get("drawing_summary") or {})
    summary.update(spring_type="compression_spring", spring_type_label="压缩弹簧", overall_status="need_review")
    return {"record_kind": "source", "drawing_summary": summary, "multi_spec": multi,
            "spring_parameters": {}, "technical_requirements": [], "manual_confirmations": {}, "change_history": []}


def child_review(source, candidate, source_id):
    from .engines.qwen_vision_adapter import qwen_payload_to_candidates
    from .workflow import DrawingReviewWorkflow
    from .io_utils import read_json, project_path
    common = source["multi_spec"]["common"]
    parameters = deepcopy(common.get("parameters") or {})
    local = candidate.get("parameters") or {}
    conflicts = [f"{key}：公共值与本规格值不同，采用本规格原文，需核对。" for key, value in local.items() if key in parameters and (parameters[key].get("value") if isinstance(parameters[key], dict) else parameters[key]) != (value.get("value") if isinstance(value, dict) else value)]
    parameters.update(deepcopy(local))
    summary = deepcopy(source["drawing_summary"])
    summary["drawing_name"] = (str(summary.get("drawing_name") or "压缩弹簧") + " · " + (candidate["code"] or f"规格{candidate['order']}"))[:512]
    points = deepcopy(candidate.get("load_points") or [])
    for point in points:
        if not isinstance(point, dict): raise MultiSpecError("载荷条目格式无效。")
        if point.get("height") is None and point.get("deflection") is not None:
            h, delta = number(parameters.get("free_length")), number(point.get("deflection"))
            h_unit = (parameters.get("free_length") or {}).get("unit") if isinstance(parameters.get("free_length"), dict) else None
            if h is not None and delta is not None and delta >= 0 and h > delta and h_unit in {"mm", "毫米"} and point.get("deflection_unit") in {"mm", "毫米"}:
                point.update(height=h-delta, height_unit="mm", height_calculation={"formula": "H0-deflection", "free_length": h, "deflection": delta})
            else: conflicts.append("变形量缺少明确单位或有效自由高度，工作高度保持空值。")
        point.setdefault("source_context", deepcopy(candidate.get("source_context") or {}))
    local_notes = deepcopy(candidate.get("technical_requirements") or [])
    for note in local_notes:
        if not isinstance(note, dict): raise MultiSpecError("技术要求格式无效。")
        note.setdefault("page", candidate["page"])
    payload = {"spring_type": {"value": "compression_spring"}, "drawing_summary": summary, "parameters": parameters,
               "load_points": points, "technical_requirements": [*deepcopy(common.get("technical_requirements") or []), *local_notes]}
    candidates = qwen_payload_to_candidates(payload)
    region = {"page": candidate["page"], **candidate["region"]} if candidate.get("region") else None
    common_regions = [{"page": r.get("page", 1), **b} for r in common.get("regions") or [] if isinstance(r, dict) and (b := box(r))]
    field_regions = {key: ([region] if region else []) if key in local else common_regions for key in parameters}
    for value in candidates:
        value["structured_specification"] = True
        if value.get("field") in local or value.get("field") == "load_point": value["page"] = candidate["page"]
    review = DrawingReviewWorkflow(read_json(project_path("config", "factory_rules.json"))).run(None, candidates, run_standardization=False)
    # Every recognised input remains pending, independent from the source or siblings.
    for item in review.get("spring_parameters", {}).values():
        if isinstance(item, dict) and item.get("value") is not None and "formula_calculation" not in (item.get("source") or []): item["need_human_review"] = True
    for item in review.get("technical_requirements", []): item["need_human_review"] = True
    for item in review.get("spring_parameters", {}).get("load_points", []):
        item["need_human_review"] = True
        original = next((p for p in points if p.get("height") == item.get("height") and p.get("force") == item.get("force")), {})
        if original.get("height_calculation"): item["height_calculation"] = original["height_calculation"]
    review.update(record_kind="variant", multi_spec_origin={"source_review_id": source_id, "variant_id": candidate["variant_id"],
        "order": candidate["order"], "code": candidate["code"], "region": region, "common_regions": common_regions,
        "field_regions": field_regions, "issues": [*candidate.get("issues", []), *conflicts], "reference_values": {**deepcopy(common.get("reference_values") or {}), **deepcopy(candidate.get("reference_values") or {})}})
    return review, candidates


def restrict_blocks(review, blocks, field):
    origin = review.get("multi_spec_origin")
    if not origin: return blocks
    regions = origin.get("field_regions", {}).get(field, [origin.get("region")])
    return [b for b in blocks if isinstance(b.get("position"), dict) and any(r and b.get("page", 1) == r.get("page", 1) and
        r["x"] <= b["position"]["x"]+b["position"]["width"]/2 <= r["x"]+r["width"] and
        r["y"] <= b["position"]["y"]+b["position"]["height"]/2 <= r["y"]+r["height"] for r in regions)]


def fingerprint(ids):
    return hashlib.sha256(json.dumps(sorted(ids), separators=(",", ":")).encode()).hexdigest()


def link_assets(source_dir: Path, child_dir: Path, candidates):
    """Hard-link immutable originals/previews: deleting a child only unlinks it."""
    import os
    from .io_utils import write_json
    for folder in ("inputs", "pages"):
        (child_dir / folder).mkdir(parents=True, exist_ok=True)
        for file in (source_dir / folder).glob("*"):
            if file.is_file():
                target = child_dir / folder / file.name
                if not target.exists(): os.link(file, target)
    if (source_dir / "file_info.json").is_file() and not (child_dir / "file_info.json").exists(): os.link(source_dir / "file_info.json", child_dir / "file_info.json")
    write_json(child_dir / "candidates.json", {"candidates": candidates, "raw_payloads": {}})
    write_json(child_dir / "shared_source.json", {"source_id": source_dir.name})


def shared_ocr_dir(job_dir):
    marker = job_dir / "shared_source.json"
    if not marker.is_file(): return job_dir
    source_id = json.loads(marker.read_text(encoding="utf-8")).get("source_id", "")
    if not isinstance(source_id, str) or not source_id.isalnum(): return job_dir
    source = job_dir.parent / source_id
    return source if source.is_dir() else job_dir
