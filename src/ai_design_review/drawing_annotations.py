"""Original-drawing locations, deliberately independent of engineering parameters."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .dimension_text import dimension_text, dimension_number, numeric_identity, safe_glyph_run

FIELDS = (
    "material", "standard_no", "accuracy_grade", "wire_diameter", "outer_diameter",
    "inner_diameter", "mean_diameter", "free_length", "solid_height", "total_coils",
    "active_coils", "surface_roughness_ra", "handedness", "end_type", "end_grinding",
)
LABELS = (
    "材料", "标准号", "通用精度等级", "线径", "外径", "内径", "中径", "自由长度",
    "压并高度", "总圈数", "有效圈数", "表面粗糙度 Ra", "旋向", "端部形式", "端面磨削",
)
PATTERNS = (
    r"材料|材质|material", r"标准|gb[/／]?t|standard", r"精度|等级|accuracy",
    r"线径|钢丝直径|wire|(?<![a-z])d[0₀]?(?![a-z])|[φΦϕøØ⌀]",
    r"外径|外圆|outer|[φΦϕøØ⌀]|do|d2", r"内径|inner|di|d1|[φΦϕøØ⌀]",
    r"中径|mean|dm", r"自由长度|自由高度|总长|轴向.*长|free|h0|h₀|l0|l₀",
    r"压并|并紧高度|solid|hb", r"总圈|total|n1", r"有效圈|active|(?<![a-z])n(?![a-z0-9])",
    r"粗糙|ra|[▽√]|surface", r"旋向|左旋|右旋|hand|left|right",
    r"端部|端圈|并紧|闭口|开口|end", r"磨平|磨削|研磨|环磨|不磨|grind|ground",
)
RECOGNIZED_SOURCES = ("qwen", "ocr", "werk24", "geometry", "dimension_role", "pdf_text")
ALGORITHM_VERSION = "original_annotation_locator/v3"
AUTOMATIC_SOURCES = {"ocr", "pdf_text", "candidate", "local_ocr"}


def page_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"(?:page[-_]?)(\d+)", path.stem, re.I)
    return (int(match[1]) if match else 1, path.name)


def preview_manifest(job_dir: Path, url_for: Callable[[Path], str]) -> list[dict[str, Any]]:
    from PIL import Image, ImageOps

    pages = []
    for path in sorted((job_dir / "pages").glob("*"), key=page_sort_key):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
            continue
        try:
            with Image.open(path) as image:
                width, height = ImageOps.exif_transpose(image).size
            pages.append({"page": page_sort_key(path)[0], "image_url": url_for(path.relative_to(job_dir)),
                          "width": width, "height": height})
        except (OSError, ValueError):
            continue
    return pages


def _normal(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower().replace("，", ",")


def _recognized(item: dict[str, Any]) -> bool:
    source = item.get("source") or []
    sources = source if isinstance(source, list) else [source]
    return any(any(marker in str(part).lower() for marker in RECOGNIZED_SOURCES) for part in sources)


def _rect(position: Any, width: float, height: float, *, center: bool = False) -> dict[str, float] | None:
    if not isinstance(position, dict):
        return None
    try:
        polygon = position.get("polygon")
        if polygon:
            xs, ys = zip(*[(float(p[0]), float(p[1])) for p in polygon])
            if not all(math.isfinite(v) for v in (*xs, *ys)):
                return None
            x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        else:
            x, y, w, h = (float(position[key]) for key in ("x", "y", "width", "height"))
            if position.get("origin") == "center" or center and position.get("origin") != "top_left":
                x, y = x - w / 2, y - h / 2
        if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
            return None
        if position.get("coordinate_type") not in {"normalized", "relative"}:
            x, w, y, h = x / width, w / width, y / height, h / height
        if x < 0 or y < 0 or x >= 1 or y >= 1 or x + w > 1.01 or y + h > 1.01:
            return None
        return {"x": x, "y": y, "width": min(w, 1 - x), "height": min(h, 1 - y)}
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return None


def pdf_blocks(source: Path, page_limit: int) -> list[dict[str, Any]]:
    """Use displayed MediaBox coordinates, including crop offset and page rotation.

    pdftoppm renders MediaBox (not CropBox). PyMuPDF words are unrotated and
    relative to CropBox, so convert before normalizing into the canonical PNG.
    """
    import fitz

    blocks = []
    with fitz.open(source) as document:
        for index in range(min(len(document), page_limit)):
            page = document[index]
            media = page.mediabox
            crop_offset = page.cropbox_position
            rotation = page.rotation
            width, height = (media.height, media.width) if rotation in (90, 270) else (media.width, media.height)
            groups: dict[tuple[int, int], list[Any]] = {}
            for word in page.get_text("words"):
                groups.setdefault((word[5], word[6]), []).append(word)
            for words in groups.values():
                words.sort(key=lambda word: word[7])
                rect = fitz.Rect(min(w[0] for w in words), min(w[1] for w in words),
                                 max(w[2] for w in words), max(w[3] for w in words))
                corners = []
                for x, y in ((rect.x0, rect.y0), (rect.x1, rect.y0), (rect.x0, rect.y1), (rect.x1, rect.y1)):
                    x, y = x + crop_offset.x, y + crop_offset.y
                    if rotation == 90:
                        x, y = media.height - y, x
                    elif rotation == 180:
                        x, y = media.width - x, media.height - y
                    elif rotation == 270:
                        x, y = y, media.width - x
                    corners.append((x, y))
                x0, y0 = min(p[0] for p in corners), min(p[1] for p in corners)
                position = _rect({"x": x0, "y": y0, "width": max(p[0] for p in corners) - x0,
                                  "height": max(p[1] for p in corners) - y0}, width, height)
                if position:
                    tokens = []
                    for word in words:
                        token = fitz.Rect(word[:4])
                        token = token + (crop_offset.x, crop_offset.y, crop_offset.x, crop_offset.y)
                        if rotation:
                            matrix = {90: fitz.Matrix(0, 1, -1, 0, media.height, 0),
                                      180: fitz.Matrix(-1, 0, 0, -1, media.width, media.height),
                                      270: fitz.Matrix(0, -1, 1, 0, 0, media.width)}[rotation]
                            token = token * matrix
                        box = _rect({"x": token.x0, "y": token.y0, "width": token.width, "height": token.height}, width, height)
                        if box:
                            tokens.append({"text": word[4], "position": box})
                    text = " ".join(w[4] for w in words)
                    blocks.append({"page": index + 1, "text": text, "position": position, "tokens": tokens, "source": "pdf_text",
                                   "numeric_join_unsafe": dimension_text(text) != text and not safe_glyph_run(tokens)})
    return blocks


def ocr_blocks(raw_payloads: dict[str, Any], pages: list[dict[str, Any]], *, unavailable_pages: set[int] | None = None) -> list[dict[str, Any]]:
    """Reuse only OCR with known image dimensions; never assume its DPI matches."""
    from PIL import Image

    allowed = {p["page"] for p in pages}
    blocks = []
    for payload in raw_payloads.values():
        if not isinstance(payload, dict):
            continue
        for raw_page in payload.get("raw_pages", payload.get("pages", [])) or []:
            if not isinstance(raw_page, dict) or raw_page.get("page") not in allowed:
                continue
            try:
                with Image.open(raw_page["image_path"]) as image:
                    width, height = image.size
                    # Legacy JPEG OCR may have auto-rotated its pixels. Without
                    # an explicit frame it cannot safely be reused.
                    if image.getexif().get(274, 1) != 1 and raw_page.get("coordinate_space") != "display":
                        if unavailable_pages is not None:
                            unavailable_pages.add(raw_page["page"])
                        continue
                if raw_page.get("coordinate_space") == "display":
                    from PIL import ImageOps
                    with Image.open(raw_page["image_path"]) as image:
                        width, height = ImageOps.exif_transpose(image).size
            except (KeyError, OSError, TypeError):
                if unavailable_pages is not None:
                    unavailable_pages.add(raw_page["page"])
                continue
            for item in raw_page.get("texts", []) or []:
                position = _rect(item.get("position"), width, height, center=True)
                if position:
                    blocks.append({"page": raw_page["page"], "text": item.get("text", ""),
                                   "position": position, "source": "ocr", "raw_position": item.get("position"),
                                   "input_size": [width, height], "image_path": raw_page["image_path"]})
    return blocks


def _value_matches(value: Any, text: str, field: str) -> bool:
    if value in (None, "") or isinstance(value, bool):
        return False
    if field == "handedness":
        value = {"right": "右旋", "left": "左旋"}.get(str(value), str(value))
        text = {"right": "右旋", "left": "左旋"}.get(str(text), str(text))
    if field == "end_grinding":
        negative = bool(re.search(r"不磨|未磨|不研磨|unground|not\s+ground", text, re.I))
        expected_negative = bool(re.search(r"不磨|未磨|unground", str(value), re.I))
        return negative if expected_negative else not negative and bool(re.search(r"磨平|(?:磨削|研磨|环磨)(?!粉尘|粉|液|膏|屑)|ground", text, re.I))
    if field == "end_type":
        negative = bool(re.search(r"不并紧|开口|open", text, re.I))
        return negative if re.search(r"不并紧|开口|open", str(value), re.I) else not negative and bool(re.search(r"并紧|闭口|closed", text, re.I))
    if field == "material":
        from .material_catalog import match_material_catalog, material_catalog_matches
        entry = match_material_catalog(value)
        return any(e["id"] == entry["id"] for e in material_catalog_matches(text)) if entry else _normal(value) in _normal(text)
    try:
        number = float(value)
        if not math.isfinite(number):
            return False
        # Digits in dimension identifiers (D2, H0, n1) are not their values.
        # Ra commonly touches the number in OCR; separate that known prefix.
        numeric_text = re.sub(r"\bRa(?=\d)", "Ra ", dimension_text(text).rstrip("。.;；"), flags=re.I)
        return any(abs(float(match) - number) < 1e-8 for match in re.findall(r"(?<![a-zA-Z\d_.])-?\d+(?:\.\d+)?(?![\d.])", numeric_text))
    except (TypeError, ValueError):
        return _normal(value) in _normal(text)


def _overlap(a: dict[str, float], b: dict[str, float]) -> float:
    intersection = max(0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])) * max(0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
    return intersection / max(1e-12, min(a["width"] * a["height"], b["width"] * b["height"]))


def _same_text_box(a: dict[str, float] | None, b: dict[str, float] | None) -> bool:
    if not a or not b:
        return False
    return _overlap(a, b) > .65 or (
        _overlap(a, b) > .4 and
        abs(a["x"] + a["width"] / 2 - b["x"] - b["width"] / 2) < max(a["width"], b["width"]) * .35 and
        abs(a["y"] + a["height"] / 2 - b["y"] - b["height"] / 2) < max(a["height"], b["height"]) * .35)


def _identity(field: str, text: str) -> bool:
    # Labels used for table pairing must establish the actual dimension role.
    if field == "end_grinding":
        return _value_matches("两端磨削", text, field) or _value_matches("两端不磨削", text, field)
    strict = {"wire_diameter": r"线径|钢丝直径|wire\s*(?:diameter|dia)",
              "outer_diameter": r"外径|外圆|outer|\bOD\b|\bDo\b",
              "inner_diameter": r"内径|inner|\bDi\b", "mean_diameter": r"中径|mean|\bDm\b"}
    return bool(re.search(strict.get(field, PATTERNS[FIELDS.index(field)]), text, re.I))


def _row_label(field: str, block: dict[str, Any], blocks: list[dict[str, Any]]) -> bool:
    box = block["position"]
    cy = box["y"] + box["height"] / 2
    labels = []
    for label in blocks:
        if label["page"] != block["page"] or label is block or not _identity(field, label["text"]):
            continue
        other = label["position"]
        gap = box["x"] - other["x"] - other["width"]
        if -.005 <= gap <= .18 and abs(cy - other["y"] - other["height"] / 2) <= max(.003, min(box["height"], other["height"]) * .6):
            labels.append((gap, label))
    if not labels:
        return False
    # Do not jump over another value/cell while joining a label and a number.
    label = min(labels, key=lambda p: p[0])[1]["position"]
    return not any(b is not block and b["page"] == block["page"] and
                   label["x"] + label["width"] + .003 < b["position"]["x"] < box["x"] - .003 and
                   abs(cy - b["position"]["y"] - b["position"]["height"] / 2) < .004 for b in blocks)


def _position_supported(candidate: dict[str, Any], block: dict[str, Any]) -> bool:
    if candidate.get("page", 1) != block["page"] or not block.get("input_size"):
        return False
    position = _rect(candidate.get("position"), *block["input_size"], center=True)
    return bool(position and _overlap(position, block["position"]) > .8)


def _bare_number(text: str) -> bool:
    return dimension_number(text) is not None


def _unique_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for block in sorted(blocks, key=lambda b: (b["page"], round(b["position"]["y"], 5), round(b["position"]["x"], 5), b["text"])):
        prior = next((b for b in result if not b.get("numeric_join_unsafe") and not block.get("numeric_join_unsafe") and b["page"] == block["page"] and numeric_identity(b["text"]) == numeric_identity(block["text"]) and _same_text_box(b["position"], block["position"])), None)
        if prior is None:
            result.append(copy.deepcopy(block))
        else:
            aliases = prior.setdefault("recognition_aliases", [])
            evidence = {k: block[k] for k in ("text", "source", "position", "tokens") if k in block}
            if evidence not in aliases:
                aliases.append(evidence)
            if not prior.get("tokens") and block.get("tokens"):
                prior["tokens"] = copy.deepcopy(block["tokens"])
    return result


def locate_fields(review: dict[str, Any], candidates: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = review.get("spring_parameters") or {}
    annotations = []
    from .multi_spec import restrict_blocks
    all_blocks = blocks
    for index, field in enumerate(FIELDS):
        blocks = restrict_blocks(review, all_blocks, field)
        param = params.get(field) or {}
        if field == "surface_roughness_ra":
            annotations.append(roughness_annotation(param, candidates, blocks))
            continue
        sources = param.get("source") or []
        sources = sources if isinstance(sources, list) else [sources]
        edited = any(s in {"human_edited", "manual"} for s in sources)
        roughness_conflict = field == "surface_roughness_ra" and bool(param.get("roughness_conflict"))
        originals = [c for c in candidates if c.get("field") == field and _recognized(c) and c.get("value") not in (None, "")]
        if not edited:
            matching = [c for c in originals if _value_matches(c.get("value"), str(param.get("value")), field)]
            originals = matching or originals
        original = max(originals, key=lambda c: float(c.get("confidence") or 0), default=None)
        if original is None and _recognized(param) and not edited and not any("formula" in str(s) for s in sources):
            original = param
        if roughness_conflict:
            original = None
        empty = not original and param.get("value") in (None, "") and not param.get("evidence")
        value = original.get("value") if original else None
        evidence = str((original or {}).get("evidence") or "")
        evidence_pages = {c["page"] for c in originals if c.get("page") is not None}
        recovery_blocks = [b for b in blocks if not evidence_pages or b["page"] in evidence_pages]
        recovered = _nominal_outer_evidence(recovery_blocks) if field == "outer_diameter" else None
        # A complete nominal dimension plus its separate tolerance can recover
        # a legacy concatenation. Do not move an unrelated, already valid value.
        suspect = not original or "vertical dimension candidate" in evidence or re.search(r"vertical dimension [\d.]*\.[\d.]*\.", evidence)
        if recovered and suspect:
            value, recovered_block = recovered
            original = {"value": value, "source": recovered_block["source"], "page": recovered_block["page"], "evidence": recovered_block["text"]}
            evidence = recovered_block["text"]
        matches = []
        pages = {c["page"] for c in originals if c.get("page") is not None}
        if not pages and (original or {}).get("page") is not None:
            pages.add(original["page"])
        for block in blocks:
            text = block["text"]
            if block.get("numeric_join_unsafe"):
                continue
            if not original or pages and block["page"] not in pages or not _value_matches(value, text, field):
                continue
            # Surface symbols cannot establish dimensional identity.
            if field in {"wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length"} and re.search(r"粗糙|\bra\b|▽|√", text, re.I):
                continue
            direct = _identity(field, text)
            row = _row_label(field, block, blocks)
            placed = any(_position_supported(c, block) for c in originals if c.get("value") == value)
            # A known candidate position is accepted only with compatible text.
            score = 8 if placed else 7 if direct else 6 if row else 0
            if field in {"material", "standard_no", "handedness"}:
                score = max(score, 7)
            if not score and _bare_number(text):
                score = 2
            if not score and field == "surface_roughness_ra" and re.fullmatch(r"[\\/√▽]\s*\d+(?:\.\d+)?", dimension_text(text)):
                # OCR can retain one stroke of the finish symbol. The complete
                # numeric value must still agree with the roughness candidate.
                score = 6
            # A leading zero is not globally interpreted as a diameter symbol.
            if field == "wire_diameter" and re.match(r"^0\d", text.strip()) and not (row or placed or re.search(r"线径|wire|[φΦϕøØ⌀]", evidence, re.I)):
                score = 0
            if score:
                matches.append((score, block))
        strong = [block for score, block in matches if score >= 6]
        winners = _unique_blocks(strong or [block for score, block in matches if score == 2])
        distinct = []
        for block in winners:
            # OCR on a crop may read the same glyph more accurately (02 -> 2).
            # Both already match this field's value; they are one location.
            if not any(b["page"] == block["page"] and _same_text_box(b["position"], block["position"]) for b in distinct):
                distinct.append(block)
        winners = distinct
        ambiguous = not strong and len(winners) > 1 and field != "surface_roughness_ra"
        if ambiguous:
            winners = []
        locations = []
        for block in winners:
            box = block["position"]
            tokens = [t for t in block.get("tokens", []) if _value_matches(value, t["text"], field)]
            if len(tokens) == 1 and dimension_number(block["text"]) == value and len(block.get("tokens", [])) > 1:
                tokens = []  # A single digit is not the complete split dimension.
            if len(tokens) == 1:
                box = tokens[0]["position"]
            key = json.dumps([block["page"], box, block["text"]], sort_keys=True)
            identifier = hashlib.sha256(key.encode()).hexdigest()[:12]
            locations.append({"location_id": f"{field}-{identifier}", "page": block["page"], "bbox": box,
                              "anchor": {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2},
                              "bubble": {"x": min(.98, box["x"] + box["width"] + .025), "y": max(.02, box["y"] - .025)},
                              "source": block["source"], "evidence": block["text"]})
        reason = "粗糙度存在不同候选，请先核对并人工定位" if roughness_conflict else "多个原图位置存在歧义，请核对后定位" if ambiguous else "OCR未读出对应标注或缺少可靠位置" if original else "此值没有原图直接标注，可人工定位"
        annotations.append({"annotation_id": field, "field": field, "number": index + 1, "label": LABELS[index],
                            "original_value": value, "evidence": evidence, "evidence_pages": sorted(pages or {(original or {}).get("page") or 1}), "locations": locations,
                            "status": "located" if locations else "empty" if empty else "unlocated",
                            "reason": "" if locations else reason})
    return annotations


def roughness_annotation(param, candidates, blocks):
    from .surface_roughness import (ROUGHNESS_VERIFICATION_VERSION, merge_roughness_candidates,
                                    verified_roughness_candidate, verify_roughness_candidates, roughness_selection, roughness_value_verified)
    claims = param.get("roughness_candidates") or [c for c in candidates if c.get("field") == "surface_roughness_ra"]
    from .standardizers.calculation_state import human_override
    if not claims and _recognized(param) and not human_override(param) and param.get("value") is not None:
        claims = [param]
    verified = [c for c in claims if roughness_value_verified(c)]
    pending = [c for c in claims if not roughness_value_verified(c)]
    # Raw OCR can resolve a retry before the review draft is saved. Final API
    # verification uses the same function and the actual document identity.
    grounded = verify_roughness_candidates(pending, blocks, "annotation-draft", dimension_candidates=candidates)
    verified = merge_roughness_candidates([*verified, *grounded])
    accepted, conflict, _ = roughness_selection(verified)
    locations = []
    for candidate in accepted:
        if not verified_roughness_candidate(candidate):
            continue
        for ref in candidate["independent_evidence"]:
            box = ref["position"]
            if any(l["page"] == ref["page"] and _same_text_box(l["bbox"], box) and l["evidence_value"] == candidate["value"] for l in locations):
                continue
            identifier = hashlib.sha256(json.dumps([ref["page"], box, candidate["value"]], sort_keys=True).encode()).hexdigest()[:12]
            locations.append({"location_id": f"surface_roughness_ra-{identifier}", "page": ref["page"], "bbox": copy.deepcopy(box),
                              "anchor": {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2},
                              "bubble": {"x": min(.98, box["x"] + box["width"] + .025), "y": max(.02, box["y"] - .025)},
                              "source": ref["source"], "evidence": ref["text"], "evidence_value": candidate["value"]})
    value = accepted[0]["value"] if accepted and not conflict else None
    return {"annotation_id": "surface_roughness_ra", "field": "surface_roughness_ra", "number": 12, "label": LABELS[11],
            "original_value": value, "evidence": " | ".join(dict.fromkeys(c.get("evidence", "") for c in accepted)),
            "evidence_pages": sorted({l["page"] for l in locations}) or [1], "locations": locations,
            "status": "located" if locations else "unlocated" if claims else "empty",
            "reason": "" if locations else "粗糙度位置或数值待核对，可重新补定位或人工定位。" if claims else "未识别到粗糙度标注。",
            "verification_version": ROUGHNESS_VERIFICATION_VERSION}


def _nominal_outer_evidence(blocks: list[dict[str, Any]]) -> tuple[float, dict[str, Any]] | None:
    """Recover a vertical nominal size with a distinct, nearby tolerance lane.

    This is evidence recovery, not a diameter inferred from spring equations.
    Multiple nominal values stay ambiguous. A bare diameter symbol is never
    sufficient to assign an outer/inner/wire role.
    """
    choices = []
    for block in blocks:
        if block.get("numeric_join_unsafe"):
            continue
        value = dimension_number(block["text"])
        box = block["position"]
        if value is None or value <= 0 or not (box["height"] > box["width"] * .8 or block.get("reading_angle") in {90, 270}):
            continue
        if re.search(r"Ra|粗糙|▽|√", block["text"], re.I):
            continue
        for tolerance in blocks:
            lower = dimension_number(tolerance["text"])
            other = tolerance["position"]
            if tolerance["page"] != block["page"] or lower is None or lower >= 0:
                continue
            if abs(other["x"] - box["x"]) < max(.015, box["width"] * .65) and abs(other["y"] - box["y"]) < max(.065, box["height"] * 2):
                choices.append((value, {**block, "nominal_tolerance_lower": lower}))
                break
    # A digit OCR box contained by a complete PDF dimension is a fragment of
    # that same measurement, not a second competing nominal value.
    choices = [(value, block) for value, block in choices if not any(
        other is not block and other["page"] == block["page"] and "." in dimension_text(other["text"]) and
        _overlap(block["position"], other["position"]) > .7 and
        other["position"]["width"] * other["position"]["height"] > block["position"]["width"] * block["position"]["height"] * 1.5
        for _, other in choices)]
    pdf_choices = [(value, block) for value, block in choices if block["source"] == "pdf_text" or any(a.get("source") == "pdf_text" and dimension_number(a.get("text")) == value for a in block.get("recognition_aliases", []))]
    choices = pdf_choices or choices
    values = {value for value, _ in choices}
    return choices[0] if len(values) == 1 else None


def recover_pdf_dimension_candidates(source: Path, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """New-upload recovery only; annotation GET never applies these values."""
    if source.suffix.lower() != ".pdf":
        return candidates
    from .engines.ocr_adapter import unsafe_vertical_dimension_candidate
    current = [c for c in candidates if not unsafe_vertical_dimension_candidate(c)]
    if any(c.get("field") == "outer_diameter" and c.get("value") not in (None, "") for c in current):
        return current
    recovered = _nominal_outer_evidence(pdf_blocks(source, max(1, int(os.getenv("QWEN_MAX_PAGES", "3")))))
    if recovered:
        value, block = recovered
        current.append({"field": "outer_diameter", "value": value, "unit": "mm", "page": block["page"],
                        "source": "pdf_text_dimension_recovery", "confidence": .94,
                        "tolerance_upper": 0, "tolerance_lower": block["nominal_tolerance_lower"],
                        "evidence": f"vertical dimension {dimension_text(block['text'])} / separate nominal and tolerance PDF text",
                        "position": {**block["position"], "coordinate_type": "normalized", "origin": "top_left"}})
    return current


def _annotation_diagnostics(review: dict[str, Any], annotations: list[dict[str, Any]], states: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = []
    params = review.get("spring_parameters") or {}
    for item in annotations:
        field = item["field"]
        current = (params.get(field) or {}).get("value")
        value = item["original_value"]
        if item["status"] == "empty" and current in (None, ""):
            continue
        mismatch = value is not None and current not in (None, "") and not _value_matches(value, str(current), field)
        role_conflict = False
        if field == "outer_diameter" and value is not None:
            try:
                inner = float((params.get("inner_diameter") or {})["value"])
                wire = float((params.get("wire_diameter") or {})["value"])
                # Only compare independent drawing values, not dimensions
                # previously completed from this same outer diameter.
                independent = all(not any("formula" in s for s in (params[f].get("source") or [])) for f in ("inner_diameter", "wire_diameter"))
                role_conflict = independent and abs(float(value) - inner - 2 * wire) > .0001
            except (KeyError, TypeError, ValueError):
                pass
        if mismatch or role_conflict or not item["locations"]:
            reason = f"原图证据值 {value} 与当前参数 {current} 不一致，请核对后修改并重新确认。" if mismatch else "图中直径标注与内径、线径关系不一致，请核对尺寸角色；参数未自动修改。" if role_conflict else item["reason"]
            diagnostics.append({"field": field, "evidence_value": value, "current_value": current,
                                "evidence": item["evidence"], "pages": item.get("evidence_pages", []),
                                "kind": "value_mismatch" if mismatch else "role_conflict" if role_conflict else "unlocated",
                                "reason": reason, "locations": [{"page": l["page"], "bbox": l["bbox"], "evidence": l["evidence"], "source": l["source"]} for l in item["locations"]],
                                "localization_status": "located" if item["locations"] else states.get(field, "not_run")})
    return diagnostics


def _local_ocr_blocks(job_dir: Path, pages: list[dict[str, Any]], document_id: str,
                      review: dict[str, Any], candidates: list[dict[str, Any]], existing: list[dict[str, Any]],
                      *, retry: bool = False, verification_requests: list[dict[str, Any]] | None = None):
    from .annotation_ocr import local_ocr_blocks
    from .multi_spec import shared_ocr_dir
    shared = shared_ocr_dir(job_dir)
    with annotation_file_lock(shared, "shared_local_ocr.lock"):
        return local_ocr_blocks(shared, pages, document_id, review, candidates, existing, retry=retry,
                                verification_requests=verification_requests)


def annotation_source(job_dir: Path, url_for: Callable[[Path], str]) -> tuple[dict[str, Any], Path | None]:
    pages = preview_manifest(job_dir, url_for)
    sources = sorted((job_dir / "inputs").glob("*"))
    source = next((p for p in sources if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}), None)
    digest = hashlib.sha256()
    if source:
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    from .multi_spec import shared_ocr_dir
    source_id = shared_ocr_dir(job_dir).name
    digest.update(json.dumps([(p["page"], p["width"], p["height"], p["image_url"].replace(f"/reviews/{job_dir.name}/", f"/reviews/{source_id}/")) for p in pages]).encode())
    document = {"schema_version": "original_annotations/v1", "algorithm_version": ALGORITHM_VERSION, "source_document_id": digest.hexdigest(),
                "annotation_revision": 1, "pages": pages, "annotations": [], "warnings": []}
    return document, source


def build_annotations(review: dict[str, Any], job_dir: Path, url_for: Callable[[Path], str],
                      *, candidates_payload: dict[str, Any] | None = None, allow_ocr: bool = True, retry_ocr: bool = False) -> dict[str, Any]:
    document, source = annotation_source(job_dir, url_for)
    pages = document["pages"]
    if review.get("drawing_summary", {}).get("spring_type") != "compression_spring":
        return document
    payload = candidates_payload
    if payload is None:
        path = job_dir / "candidates.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    candidates = payload.get("candidates") or []
    limit = max(1, int(os.getenv("QWEN_MAX_PAGES", "3")))
    eligible = [p for p in pages if p["page"] <= limit]
    blocks = []
    if source and source.suffix.lower() == ".pdf":
        try:
            blocks.extend(pdf_blocks(source, limit))
        except Exception:
            document["warnings"].append("PDF文本定位不可用，尝试OCR或人工定位。")
    unavailable_pages: set[int] = set()
    blocks.extend(ocr_blocks(payload.get("raw_payloads") or {}, eligible, unavailable_pages=unavailable_pages))
    document["annotations"] = locate_fields(review, candidates, blocks)
    missing = any(a["status"] == "unlocated" and a["original_value"] is not None for a in document["annotations"])
    from .surface_roughness import ROUGHNESS_VERIFICATION_VERSION, grounded_roughness_evidence, positive_surface_roughness, verified_roughness_candidate, roughness_request_key
    roughness = (review.get("spring_parameters") or {}).get("surface_roughness_ra") or {}
    verification_requests = [{"field": "surface_roughness_ra", "original_value": c["value"], "page": c.get("page") or 1,
                              "evidence_pages": [c.get("page") or 1], "position": c.get("position"), "status": "unlocated",
                              "request_key": roughness_request_key(c)}
                             for c in roughness.get("roughness_candidates") or []
                             if isinstance(c, dict) and positive_surface_roughness(c.get("value")) is not None and not verified_roughness_candidate(c)
                             and not grounded_roughness_evidence(c, blocks, dimension_candidates=candidates)[0]]
    for request in verification_requests:
        request["roughness_claim"] = next(c for c in roughness["roughness_candidates"] if c["value"] == request["original_value"])
    states = {}
    if allow_ocr and (missing or verification_requests) and eligible:
        try:
            local, warnings, states = _local_ocr_blocks(job_dir, eligible, document["source_document_id"], review, candidates, blocks,
                                                       retry=retry_ocr, verification_requests=verification_requests)
            blocks = _unique_blocks(blocks + local)
            document["warnings"].extend(warnings)
            document["annotations"] = locate_fields(review, candidates, blocks)
        except Exception:
            document["warnings"].append("本地OCR定位不可用，可使用调整标注人工定位。")
    # Screen-space layout belongs to the SVG viewer: a fixed normalized gap is
    # neither readable on small panels nor meaningful across aspect ratios.
    document["text_obstacles"] = [{"page": b["page"], "bbox": b["position"]} for b in _unique_blocks(blocks)]
    for annotation in document["annotations"]:
        relevant = {c.get("page", 1) for c in candidates if c.get("field") == annotation["field"]} or {1}
        if annotation["status"] == "unlocated" and annotation["original_value"] is not None and "歧义" not in annotation["reason"] and relevant & unavailable_pages:
            if not any(b["page"] in relevant and b["source"] in {"ocr", "local_ocr"} for b in blocks):
                annotation["reason"] = "来源坐标不可用，且本地OCR未完成，可人工定位"
    previous = review.get("drawing_annotations") or {}
    if retry_ocr and previous.get("source_document_id") == document["source_document_id"]:
        by_field = {a["field"]: a for a in previous.get("annotations", [])}
        for index, annotation in enumerate(document["annotations"]):
            prior = by_field.get(annotation["field"], {})
            automatic = [l for l in prior.get("locations", []) if l.get("source") in AUTOMATIC_SOURCES]
            # Preserve a reliable field's evidence metadata as well as its
            # coordinates. Legacy metadata contradicting its own saved glyphs
            # is rebuilt instead (parameters themselves are never changed).
            if annotation["field"] != "surface_roughness_ra" and automatic and all(_value_matches(prior.get("original_value"), l.get("evidence", ""), annotation["field"]) for l in automatic):
                document["annotations"][index] = copy.deepcopy(prior)
    document["diagnostics"] = _annotation_diagnostics(review, document["annotations"], states)
    document["roughness_evidence_signature"] = roughness_refresh_key(review)
    return document


def merge_annotation_upgrade(current: dict[str, Any], rebuilt: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Merge while holding the persistence lock, including edits made during OCR."""
    roughness_refresh = rebuilt.get("roughness_only_refresh") is True
    if not force and not roughness_refresh and current.get("algorithm_version") == ALGORITHM_VERSION:
        return current
    if current.get("source_document_id") != rebuilt.get("source_document_id"):
        failed = copy.deepcopy(current)
        failed["algorithm_version"] = ALGORITHM_VERSION
        failed.setdefault("warnings", []).append("原图或预览标识发生变化，已保留旧位置，请核对后人工定位。")
        failed["annotation_revision"] = current.get("annotation_revision", 1) + 1
        return failed
    result = copy.deepcopy(rebuilt)
    old = {a["annotation_id"]: a for a in current.get("annotations", [])}
    for annotation in result.get("annotations", []):
        previous = old.get(annotation["annotation_id"], {})
        if roughness_refresh and annotation["field"] != "surface_roughness_ra":
            annotation.update(copy.deepcopy(previous))
            continue
        if force and previous.get("locations") and annotation["field"] != "surface_roughness_ra":
            annotation.update({k: copy.deepcopy(previous[k]) for k in ("locations", "status", "reason")})
            continue
        available = list(annotation["locations"])
        for location in previous.get("locations", []):
            if location.get("source") not in AUTOMATIC_SOURCES:
                continue
            same_page = [l for l in available if l["page"] == location["page"]]
            if same_page:
                closest = min(same_page, key=lambda l: math.hypot(l["anchor"]["x"] - location["anchor"]["x"], l["anchor"]["y"] - location["anchor"]["y"]))
                closest["location_id"] = location["location_id"]
                available.remove(closest)
        protected = [l for l in previous.get("locations", []) if l.get("source") not in AUTOMATIC_SOURCES]
        if protected:
            remaining = annotation["locations"]
            if any(l.get("source") != "manual" for l in protected):
                remaining = []
            else:
                remaining = list(remaining)
                for location in protected:
                    same_page = [l for l in remaining if l["page"] == location["page"]]
                    if same_page:
                        nearest = min(same_page, key=lambda l: -_overlap(l["bbox"], location["bbox"]) if l.get("bbox") and location.get("bbox") else math.hypot(l["anchor"]["x"] - location["anchor"]["x"], l["anchor"]["y"] - location["anchor"]["y"]))
                        if annotation["field"] != "surface_roughness_ra" or _same_text_box(nearest.get("bbox"), location.get("bbox")) or math.hypot(nearest["anchor"]["x"] - location["anchor"]["x"], nearest["anchor"]["y"] - location["anchor"]["y"]) < .01:
                            remaining.remove(nearest)
            annotation["locations"] = copy.deepcopy(protected) + remaining
            annotation["status"] = "located"
            annotation["reason"] = ""
            if any(l.get("source") != "manual" for l in protected):
                annotation["reason"] = "旧位置来源不明，已保留，请核对。"
    result["annotation_revision"] = current.get("annotation_revision", 1) + 1
    for annotation in result.get("annotations", []):
        if roughness_refresh and annotation["field"] != "surface_roughness_ra":
            continue
        distinct = []
        for location in annotation["locations"]:
            if location.get("source") in AUTOMATIC_SOURCES and any(
                prior.get("source") in AUTOMATIC_SOURCES and prior["page"] == location["page"] and _same_text_box(prior.get("bbox"), location.get("bbox"))
                for prior in distinct
            ):
                continue
            distinct.append(location)
        annotation["locations"] = distinct
    if not roughness_refresh:
        _prune_resolved_diagnostics(result)
    return result


def roughness_refresh_key(review):
    from .surface_roughness import ROUGHNESS_VERIFICATION_VERSION
    item = (review.get("spring_parameters") or {}).get("surface_roughness_ra") or {}
    # Only evidence that affects locations belongs to this signature. Saving
    # adds audit/source metadata without changing an annotation revision.
    evidence = sorted({json.dumps([c.get("value"), c.get("value_verified"), c.get("recognition_state"), c.get("verification_method"), c.get("independent_evidence", []), c.get("numeric_evidence", []), c.get("expected_locations", 1)], sort_keys=True, ensure_ascii=False)
                       for c in item.get("roughness_candidates", [])})
    return hashlib.sha256(json.dumps([ROUGHNESS_VERIFICATION_VERSION, item.get("source_document_id"), evidence], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def refresh_roughness_annotations(current, review):
    """Build a narrow upgrade; persistence merges the latest manual positions."""
    result = copy.deepcopy(current)
    param = (review.get("spring_parameters") or {}).get("surface_roughness_ra") or {}
    if param.get("source_document_id") and param["source_document_id"] != current.get("source_document_id"):
        result["roughness_evidence_signature"] = roughness_refresh_key(review)
        result["roughness_only_refresh"] = True
        warning = "粗糙度核验的原图标识已变化，已保留现有位置，请核对原图。"
        if warning not in result.setdefault("warnings", []):
            result["warnings"].append(warning)
        return result
    annotation = roughness_annotation(param, [], [])
    result["annotations"] = [annotation if a.get("field") == "surface_roughness_ra" else a for a in result.get("annotations", [])]
    result["roughness_evidence_signature"] = roughness_refresh_key(review)
    result["roughness_only_refresh"] = True
    result["diagnostics"] = [d for d in result.get("diagnostics", []) if d.get("field") != "surface_roughness_ra"]
    return result


def failed_annotation_upgrade(current: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(current)
    result["algorithm_version"] = ALGORITHM_VERSION
    result["annotation_revision"] = current.get("annotation_revision", 1) + 1
    result.setdefault("warnings", []).append("自动定位升级未完成，已保留旧结果；本版本不自动重复尝试，可人工定位。")
    return result


class AnnotationConflictError(ValueError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("标注已在其他页面更新，请选择保留的位置。")
        self.current = current


def validate_annotation_revision(document: dict[str, Any], body: dict[str, Any]) -> None:
    if body.get("source_document_id") != document["source_document_id"]:
        raise AnnotationConflictError(document)
    revision = body.get("expected_annotation_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("expected_annotation_revision 必须为正整数。")
    if revision != document["annotation_revision"]:
        raise AnnotationConflictError(document)


def _prune_resolved_diagnostics(document: dict[str, Any]) -> None:
    located = {a["field"] for a in document["annotations"] if a["locations"]}
    if "diagnostics" in document:
        document["diagnostics"] = [d for d in document["diagnostics"] if d["kind"] != "unlocated" or d["field"] not in located]


def apply_annotation_patch(document: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    validate_annotation_revision(document, body)
    changes = body.get("changes")
    if not isinstance(changes, list) or not changes or len(changes) > 60:
        raise ValueError("changes 必须包含1至60个位置修改。")
    result = copy.deepcopy(document)
    by_id = {a["annotation_id"]: a for a in result["annotations"]}
    page_ids = {p["page"] for p in result["pages"]}
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) - {"annotation_id", "location_id", "page", "anchor", "bubble"}:
            raise ValueError("只允许修改标注位置。")
        annotation_id = change.get("annotation_id")
        if not isinstance(annotation_id, str):
            raise ValueError("无效参数标注标识。")
        annotation = by_id.get(annotation_id)
        if not annotation or annotation["field"] not in FIELDS:
            raise ValueError("未知参数标注。")
        location_id = change.get("location_id")
        if not isinstance(location_id, str) or not re.fullmatch(r"[a-z0-9_-]{1,96}", location_id):
            raise ValueError("无效标注位置标识。")
        key = (annotation["annotation_id"], location_id)
        if key in seen:
            raise ValueError("同一位置不能重复提交。")
        seen.add(key)
        page = change.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page not in page_ids:
            raise ValueError("标注页码不存在。")
        location = next((l for l in annotation["locations"] if l["location_id"] == location_id), None)
        if location is None:
            if annotation["locations"]:
                raise ValueError("已有定位仅允许调整现有位置。")
            location = {"location_id": location_id, "bbox": None, "evidence": "人工定位"}
            annotation["locations"].append(location)
        for name in ("anchor", "bubble"):
            point = change.get(name)
            if not isinstance(point, dict) or set(point) != {"x", "y"}:
                raise ValueError("位置必须包含 x、y。")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in point.values()):
                raise ValueError("位置必须是0至1之间的有限数值。")
            location[name] = dict(point)
        location.update({"page": page, "source": "manual"})
        annotation.update({"status": "located", "reason": ""})
    result["annotation_revision"] += 1
    _prune_resolved_diagnostics(result)
    return result


@contextmanager
def annotation_file_lock(job_dir: Path, filename: str = "annotations.lock"):
    """OS lock works across API processes; parameter JSON never writes this sidecar."""
    path = job_dir / filename
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic_annotation_write(path: Path, document: dict[str, Any]) -> None:
    handle, name = tempfile.mkstemp(prefix="annotations-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
