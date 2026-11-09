"""Resolve diameter roles from original text or both dimension witnesses."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from copy import deepcopy

from .diameter_linkage import DIAMETERS

SOURCE = "original_diameter_role"
CANDIDATE = "diameter_role_candidate"
PENDING = "diameter_role_candidates"
INFERENCE = "diameter_model_inference"
VERSION = "diameter-role/v3"
ROLE_STATE_VERSION = "diameter-candidates/v1"
REASON = "直径类型待核对。请选择内径、中径或外径。"
LABELS = {
    "inner_diameter": r"内径|內徑|内直径|inner\s+diameter|inside\s+diameter|\bI\.?D\.?",
    "mean_diameter": r"中径|中徑|平均径|mean\s+diameter|average\s+diameter|center\s+diameter",
    "outer_diameter": r"外径|外徑|外直径|outer\s+diameter|outside\s+diameter|\bO\.?D\.?",
}
MARK = r"[φΦϕøØ⌀]"
NUMBER = r"\d+(?:\.\d+)?"
DERIVATION = re.compile(r"推算|推导|计算|换算|\b(?:derived|calculated|inferred|computed)\b"
                        r"|(?:外径|内径|中径|线径).{0,24}(?:减去|减|加上|乘以|除以)"
                        r"|(?:外径|内径|中径|线径|\bD[oim]?\b|\bd\b)\s*[-+−×*÷/]\s*(?:外径|内径|中径|线径|\bD[oim]?\b|\bd\b)", re.I)
EXCLUDED = re.compile(r"粗糙|\b(?:ra|rz)(?:\b|(?=\d))|[▽√⊥∥⌖]|形位公差|几何公差|线径|簧丝直径|wire\s+diameter", re.I)
NON_SPRING_DIAMETER = re.compile(r"[⊥∥⌖]|形位公差|几何公差|线径|簧丝直径|wire\s+diameter", re.I)
# Closed-loop OCR substitutions for Φ. These only seed a search; both
# dimension witnesses must independently verify the drawing annotation.
OCR_DIAMETER_PREFIX = re.compile(rf"^[09opq]\s*(?={NUMBER})", re.I)
BARE_DIMENSION = re.compile(rf"^[≤≥<>]?\s*{MARK}?\s*((?:[1-9]\d*|0)(?:\.\d+)?)(?![\d.])"
                            rf"(?:\s*(?:mm|[+±−/\-\d.])*)?\s*$", re.I)


def _value(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n > 0 else None


def supported_candidates(candidates):
    from .diameter_linkage import supported
    features = {item["field"]: item for item in candidates if item.get("field") in {"spring_shape", "wire_section"}}
    return supported({"drawing_summary": {"spring_type": "compression_spring"}, "spring_features": features})


def _text(text):
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def _label_roles(text, value):
    roles = set()
    for field, label in LABELS.items():
        pattern = rf"(?:{label})\s*(?:D(?:_?[iom]|[12])?\s*)?(?:\(mm\))?\s*[:=]?\s*{MARK}?\s*({NUMBER})(?![\d.])"
        if any(_value(m.group(1)) == value for m in re.finditer(pattern, text, re.I)):
            roles.add(field)
    return roles


def _diameter_number(text, value):
    return any(_value(m.group(1)) == value for m in re.finditer(rf"{MARK}\s*({NUMBER})(?![\d.])", text))


def _normalized_mark(content, value, allow_substitution):
    if allow_substitution:
        corrected = OCR_DIAMETER_PREFIX.sub("Φ", content, count=1)
        if _diameter_number(corrected, value):
            return corrected
    return content


def _observed_tolerance(text, value):
    nominal = next((match for match in re.finditer(rf"(?<![\d.])({NUMBER})(?![\d.])", text)
                    if _value(match.group(1)) == value), None)
    if nominal is None:
        return {}
    tail = text[nominal.end():].replace("−", "-")
    match = re.match(rf"\s*(?:mm\s*)?±\s*({NUMBER})(?![\d.])", tail, re.I)
    if match:
        upper = float(match.group(1))
        return {"tolerance_upper": upper, "tolerance_lower": -upper}
    match = re.match(rf"\s*(?:mm\s*)?([+-]\s*{NUMBER}|0)\s*/\s*([+-]\s*{NUMBER}|0)(?![\d.])", tail, re.I)
    if match:
        upper, lower = (float(re.sub(r"\s+", "", v)) for v in match.groups())
        return {"tolerance_upper": upper, "tolerance_lower": lower} if upper >= lower else {}
    match = re.match(rf"\s*(?:mm\s*)?([+-])\s*({NUMBER})(?![\d.])", tail, re.I)
    if match:
        side = "tolerance_upper" if match[1] == "+" else "tolerance_lower"
        return {side: float(match[1] + match[2])}
    return {}


def _stacked_tolerance(text, page, axis, dimension, value, content):
    """Recover signed offsets from the small adjacent text of this dimension."""
    inline = _observed_tolerance(content, value)
    start, end = text["bbox"][axis], text["bbox"][axis + 2]
    lo, hi = text["bbox"][1 - axis], text["bbox"][3 - axis]
    font = max(hi - lo, 3)
    distance = 1.6 * font
    offsets = []
    split = {}
    position = _original_box(text, page)
    for other in page["texts"]:
        if other is text:
            continue
        a, b = other["bbox"][axis], other["bbox"][axis + 2]
        c, d = other["bbox"][1 - axis], other["bbox"][3 - axis]
        center = (a + b) / 2
        if not dimension["a"] < center < dimension["b"]:
            continue
        token = _text(other["text"]).replace("−", "-").replace(" ", "")
        origin = other.get("diameter_offset_origin")
        if origin:
            if _same_box(position, origin) and re.fullmatch(rf"(?:[+\-]{NUMBER}|0)", token):
                split.setdefault(other["diameter_offset_slot"], set()).add(float(token))
            continue
        if max(a - end, start - b) > distance or min(hi, d) < max(lo, c) - font * .5:
            continue
        if min(end, b) - max(start, a) > .4 * min(end - start, b - a) and min(hi, d) - max(lo, c) > .65 * min(hi - lo, d - c):
            continue
        if re.fullmatch(rf"(?:[+\-±]{NUMBER}|0)", token):
            offsets.append((token, center))
    if split:
        for slot, key in enumerate(("tolerance_upper", "tolerance_lower")):
            if key in inline and (slot not in split or len(inline) == 2):
                split.setdefault(slot, set()).add(inline[key])
        return {key: split.get(slot, set()) for slot, key in enumerate(("tolerance_upper", "tolerance_lower"))}, 2 if len(split) == 2 else 1
    positive = {float(v[1:]) for v, _ in offsets if v.startswith("+")}
    negative = {float(v) for v, _ in offsets if v.startswith("-")}
    symmetric = {float(v[1:]) for v, _ in offsets if v.startswith("±")}
    has_zero = any(v == "0" for v, _ in offsets)
    if "tolerance_upper" in inline:
        positive.add(inline["tolerance_upper"])
    if "tolerance_lower" in inline:
        negative.add(inline["tolerance_lower"])
    if has_zero and positive and not negative:
        negative.add(0.)
    elif has_zero and negative and not positive:
        positive.add(0.)
    positive.update(symmetric)
    negative.update(-v for v in symmetric)
    return {"tolerance_upper": positive, "tolerance_lower": negative}, 2 if len(inline) == 2 else 0


def stacked_offset_crops(image, blocks, requests, page):
    """Propose tiny OCR crops for the two separately printed offset rows."""
    import numpy as np

    claims = {(_value(r["original_value"]), r.get("diameter_mark", False))
              for r in requests if r.get("kind") == "diameter_dimension"}
    if not claims:
        return []
    gray = np.asarray(image.convert("L"))
    regions, used = [], []
    for block in blocks:
        if block["page"] != page or block.get("diameter_offset_origin"):
            continue
        text = _text(block["text"])
        value = next((v for v, mark in claims if v is not None and
                      (match := BARE_DIMENSION.fullmatch(_normalized_mark(text, v, mark))) and _value(match[1]) == v), None)
        if value is None or len(_observed_tolerance(_normalized_mark(text, value, True), value)) == 2:
            continue
        origin = block["position"]
        if any(_same_box(origin, old) for old in used):
            continue
        height, width = gray.shape
        vertical = origin["height"] * height > origin["width"] * width
        raster = gray.T if vertical else gray
        rows, cols = raster.shape
        u, v = ("y", "x") if vertical else ("x", "y")
        w, h = ("height", "width") if vertical else ("width", "height")
        a, c = origin[u] * cols, origin[v] * rows
        b, d = a + origin[w] * cols, c + origin[h] * rows
        font = d - c
        if b - a < font or font < 8:
            continue
        pair = _offset_rows(raster, a, b, c, d)
        if not pair:
            continue
        direction, boxes = pair
        angle = (90 if direction > 0 else 270) if vertical else (0 if direction > 0 else 180)
        if vertical:
            boxes.reverse()
        for slot, (x0, y0, x1, y1) in enumerate(boxes):
            rect = (y0/rows, x0/cols, y1/rows, x1/cols) if vertical else (x0/cols, y0/rows, x1/cols, y1/rows)
            regions.append(((*rect, angle), {"diameter_offset_origin": origin, "diameter_offset_slot": slot}))
        used.append(origin)
    return regions


def _offset_rows(raster, a, b, c, d):
    import cv2
    import numpy as np

    height, width = raster.shape
    font = d - c
    left, top = max(0, round(a - font * .55)), max(0, round(c - font * .45))
    right, bottom = min(width, round(b + font * .55)), min(height, round(d + font * .45))
    roi = raster[top:bottom, left:right]
    if not roi.size:
        return None
    _, _, stats, _ = cv2.connectedComponentsWithStats((roi < 160).astype(np.uint8))
    components = [(int(x)+left, int(y)+top, int(w), int(h)) for x,y,w,h,area in stats[1:] if area >= 6]
    glyphs = [(x,y,w,h) for x,y,w,h in components if font * .22 <= h <= font * .8 and .22 * h <= w <= h * 1.1]
    pairs = []
    for x,y,w,h in glyphs:
        center = x + w/2
        direction = 1 if center >= (a+b)/2 else -1
        if abs(center-(b if direction > 0 else a)) > font * .63:
            continue
        for xx,yy,ww,hh in glyphs:
            if yy <= y or abs(center-(xx+ww/2)) > max(w,ww) * .55 or not .7 <= h/hh <= 1.4:
                continue
            row_gap = yy + hh/2 - y - h/2
            if not .80 <= row_gap/max(h,hh) <= 1.5:
                continue
            mid = round((y+h+yy)/2)
            # Include the sign before the terminal digit, while separating rows.
            x0 = max(0, round(min(x,xx) - (max(w,ww)*1.6 if direction > 0 else 2)))
            x1 = min(width, round(max(x+w,xx+ww) + (2 if direction > 0 else max(w,ww)*1.6)))
            boxes = [(x0,max(0,y-2),x1,mid), (x0,mid,x1,min(height,yy+hh+2))]
            # Exclude a clipped, narrow nominal stroke while retaining compact
            # signs printed directly before the offset.
            for slot, (gx,gy,gw,gh) in enumerate(((x,y,w,h), (xx,yy,ww,hh))):
                gx0, gy0, gx1, gy1 = boxes[slot]
                for cx,cy,cw,ch in components:
                    if ch < gh * 1.15 or cw > ch * .6 or cy >= gy1 or cy + ch <= gy0:
                        continue
                    if direction > 0 and cx <= gx0 + 2 < cx + cw < gx - 2:
                        gx0 = cx + cw + 1
                    elif direction < 0 and gx + gw + 2 < cx < gx1 - 2 <= cx + cw:
                        gx1 = cx - 1
                boxes[slot] = (gx0,gy0,gx1,gy1)
            if direction > 0:
                pairs.append((abs(center-(xx+ww/2)), direction, boxes))
            else:
                pairs.append((abs(center-(xx+ww/2)), direction, boxes[::-1]))
    if pairs:
        _, direction, boxes = min(pairs)
        return direction, boxes


def _same_box(a, b):
    if not a or not b or min(a["width"], a["height"], b["width"], b["height"]) <= 0:
        return False
    x, y = max(a["x"], b["x"]), max(a["y"], b["y"])
    right = min(a["x"] + a["width"], b["x"] + b["width"])
    bottom = min(a["y"] + a["height"], b["y"] + b["height"])
    return max(0, right - x) * max(0, bottom - y) >= .35 * min(a["width"] * a["height"], b["width"] * b["height"])


def _box(candidate, page):
    from .drawing_annotations import _rect
    return _rect(candidate.get("position"), page["width"], page["height"])


def _original_box(text, page):
    x0, y0, x1, y1 = text["bbox"]
    return {"x": x0 / page["width"], "y": y0 / page["height"],
            "width": (x1 - x0) / page["width"], "height": (y1 - y0) / page["height"],
            "coordinate_type": "normalized", "origin": "top_left"}


def _in_region(box, region):
    if not region:
        return True
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    return region["x"] <= x <= region["x"] + region["width"] and region["y"] <= y <= region["y"] + region["height"]


def _dimension_roles(text, page, region):
    # A verified pair of wire sections supplies all three boundaries without
    # measuring a diameter from drawing scale. Each witness must reach its own
    # section, and the sections must lie on opposite sides of the spring axis.
    sections = [s for s in page.get("wire_sections", [])
                if _in_region({"x": s[0] / page["width"], "y": s[1] / page["height"], "width": 0, "height": 0}, region)]
    results, simplified = [], []
    for axis, dimension in _witness_dimensions(text, page):
        w, h = text["bbox"][2] - text["bbox"][0], text["bbox"][3] - text["bbox"][1]
        if (axis == 1 and w > 1.45 * h) or (axis == 0 and h > 1.45 * w):
            continue
        original = _roles_for_witness(axis, dimension, page, sections, region)
        from .simplified_diameter_geometry import repeated_coil_boundaries
        key = (axis, *(round(dimension[k], 3) for k in ("a", "b", "cross")), json.dumps(region, sort_keys=True))
        cache = page.setdefault("_simplified_diameter_cache", {})
        if key not in cache:
            cache[key] = repeated_coil_boundaries(axis, dimension, page, region)
        match = cache[key]
        if match:
            field, geometry = match
            # Intersecting coil strokes can resemble a large hatched disk to
            # HoughCircles. Repeated caps independently check the wire radius.
            credible_sections = [(role, evidence) for role, evidence in original if evidence.get("wire_sections") and
                                 all(.5*geometry["radius"] <= section[2] <= 1.8*geometry["radius"]
                                     for section in evidence["wire_sections"])]
            base = {"axis": axis, "endpoints": [dimension["a"], dimension["b"]],
                    "baseline": dimension["cross"], "page_size": [page["width"], page["height"]]}
            if credible_sections and any(role != field for role, _ in credible_sections):
                results.extend([*credible_sections, (field, {**base, **geometry})])
                continue
            distance = abs(dimension["cross"]-(text["bbox"][1-axis]+text["bbox"][3-axis])/2)
            simplified.append((distance, field, {**base, **geometry}))
        else:
            results.extend(original)
    # Keep the legacy successful paths. Adjacent nested dimensions may both be
    # near one OCR box; use its nearest baseline for the new arc-only path.
    if results or not simplified:
        return results
    closest = min(item[0] for item in simplified)
    return [(field, geometry) for distance, field, geometry in simplified if distance <= closest + page.get("epsilon", 1)*.5]


def _roles_for_witness(axis, dimension, page, sections, region):
    a, b, cross = (dimension[k] for k in ("a", "b", "cross"))
    base = {"axis": axis, "endpoints": [a, b], "baseline": cross,
            "page_size": [page["width"], page["height"]]}
    ends = []
    for endpoint, side in ((a, -1), (b, 1)):
        matches = []
        for section in sections:
            along, across, radius = section[axis], section[1 - axis], section[2]
            if radius >= (b - a) / 3 or abs(across - cross) > (b - a) * 1.2:
                continue
            for field, offset in (("inner_diameter", -side), ("mean_diameter", 0), ("outer_diameter", side)):
                limit = max(page.get("epsilon", 1), radius * .65)
                if abs(along + offset * radius - endpoint) > limit:
                    continue
                guides = [g for g in dimension["guides"] if abs(g[0] - endpoint) <= limit]
                # Witnesses can stop just outside the ink at the section.
                reach = radius + page.get("epsilon", 1)
                if any(min(g[1], g[3]) - reach <= across <= max(g[1], g[3]) + reach for g in guides):
                    matches.append((field, section))
        ends.append(matches)
    results = []
    for field, first in ends[0]:
        for other, second in ends[1]:
            if field != other or first == second or max(first[2], second[2]) > 1.45 * min(first[2], second[2]):
                continue
            if not _same_spring_view(first, second, axis, page, b - a):
                continue
            results.append((field, {**base, "wire_sections": [first, second]}))
    # The outline path only verifies the outer envelope and requires a
    # sequence of turns in one connected view. It cannot infer inner/mean.
    if not results:
        outline = _outer_envelope(axis, dimension, page, region)
        if outline:
            results.append(("outer_diameter", {**base, "coil_envelope": outline}))
    return results


def _same_spring_view(first, second, axis, page, span):
    lo, hi = sorted((first[1-axis], second[1-axis]))
    if hi - lo <= span:
        return True
    # On a broken-out view the two sections can be far apart. Require the
    # axial centerline between them before treating them as one spring.
    if hi - lo > span * 2:
        return False
    center = (first[axis] + second[axis]) / 2
    band = max(page.get("epsilon", 1) * 2, span * .03)
    pieces = []
    for line in [*page["lines"], *page.get("line_segments", [])]:
        if max(abs(line[axis]-center), abs(line[axis+2]-center)) > band:
            continue
        a, b = sorted((line[1-axis], line[3-axis]))
        if b - a >= band and a < hi and b > lo:
            pieces.append((max(a, lo), min(b, hi)))
    covered, end = 0, lo
    for a, b in sorted(pieces):
        covered += max(0, b - max(a, end))
        end = max(end, b)
    return covered >= (hi - lo) * .38


def _ink_runs(ink):
    import numpy as np
    edges = np.flatnonzero(np.diff(np.r_[False, ink, False]))
    return list(zip(edges[::2], edges[1::2]))


def _outer_envelope(axis, dimension, page, region):
    """Find opposing repeated turns tangent to the two extension lines."""
    raster = page.get("diameter_raster")
    if raster is None:
        return None
    import cv2
    import numpy as np
    mask, scale = raster
    # Rows run across the spring, columns run along its axis.
    ink = mask if axis == 1 else mask.T
    a, b, cross = (round(dimension[k] * scale) for k in ("a", "b", "cross"))
    span = b - a
    band = max(3, round(page.get("epsilon", 1) * scale * 1.35))
    if span < band * 12 or a < band * 4 or b + band * 4 >= ink.shape[0]:
        return None
    ends = []
    for endpoint in (a, b):
        guides = [g for g in dimension["guides"] if abs(g[0] * scale - endpoint) <= band]
        ends.append([round(c * scale) for g in guides for c in (g[1], g[3])])
    for direction in (-1, 1):
        reaches = [max((direction * (c - cross) for c in values), default=0) for values in ends]
        if min(reaches) < band * 2:
            continue
        # Inspect the contact and the turns just beyond it, keeping both sides
        # in the same axial window even when one extension reaches farther.
        origin = cross + direction * min(reaches)
        lo, hi = sorted((origin - direction * band * 2, origin + direction * round(span * 1.35)))
        lo, hi = max(0, lo), min(ink.shape[1], hi)
        if hi - lo < span // 3:
            continue
        caps = []
        for endpoint, inward in ((a, 1), (b, -1)):
            boundary = np.any(ink[endpoint-band:endpoint+band+1, lo:hi], axis=0)
            outside_start, outside_end = sorted((endpoint-inward*band*4, endpoint-inward*band*2))
            outside = ink[outside_start:outside_end, lo:hi]
            # A long parallel dimension or extension stroke is not coil ink.
            straight = cv2.morphologyEx(outside, cv2.MORPH_OPEN,
                                        np.ones((1, max(3, round(span * .24))), np.uint8))
            exterior = np.any(outside & ~straight, axis=0)
            inside_start, inside_end = sorted((endpoint+inward*band*2, endpoint+inward*band*4))
            interior = np.any(ink[inside_start:inside_end, lo:hi], axis=0)
            tips = []
            for start, end in _ink_runs(boundary):
                if not band <= end - start <= span * .28:
                    continue
                neighborhood = slice(max(0, start-band), min(hi-lo, end+band))
                if exterior[neighborhood].mean() > .25 or not interior[neighborhood].any():
                    continue
                tip = (lo + (start+end)/2) / scale
                position = [0., 0.]
                position[axis], position[1-axis] = endpoint / scale, tip
                if _in_region({"x": position[0]/page["width"], "y": position[1]/page["height"],
                               "width": 0, "height": 0}, region):
                    tips.append(tip)
            caps.append(tips)
        if min(map(len, caps)) < 2:
            continue
        spacings = [b - a for tips in caps for a, b in zip(tips, tips[1:])]
        if len(spacings) == 2:
            # Two visible turns on each side can still agree on the pitch,
            # including views where other turns are interrupted by linework.
            aligned = min(spacings) >= max(band * 2 / scale, max(spacings) * .78)
        else:
            aligned = any(sum(.6 * gap <= other <= 1.6 * gap for other in spacings) >= 3
                          for gap in spacings if gap >= band * 2 / scale)
        if not aligned:
            continue
        reach = [min(abs(tip * scale - (cross + direction * length)) for tip in tips)
                 for tips, length in zip(caps, reaches)]
        if max(reach) > span * .45 or max(min(c) for c in caps) > min(max(c) for c in caps):
            continue
        return [[float(tip) for tip in tips] for tips in caps]
    return None


def _witness_dimensions(text, page):
    """Join broken dimension strokes and retain only supported end witnesses."""
    epsilon = page.get("epsilon", .8)
    for axis in (0, 1):
        box = text["bbox"]
        start, end, lo, hi = box[axis], box[axis + 2], box[1 - axis], box[3 - axis]
        center, depth = (start + end) / 2, max(hi - lo, 3)
        baselines, witnesses = [], []
        for line in [*page["lines"], *page.get("line_segments", [])]:
            a, b, c, d = (line[i] for i in (axis, 1 - axis, axis + 2, 3 - axis))
            cross = (b + d) / 2
            if abs(b-d) <= max(2 * epsilon, abs(a-c) * .038) and abs(a-c) > depth * .7:
                if lo - depth <= cross <= hi + depth and not lo + depth * .40 < cross < hi - depth * .40:
                    baselines.append((cross, min(a, c), max(a, c)))
            if abs(a-c) <= max(1.6 * epsilon, abs(b-d) * .025) and abs(b-d) >= depth * .45:
                if max(b, d) >= lo - depth * 1.5 and min(b, d) <= hi + depth * 1.5:
                    witnesses.append(((a + c) / 2, b, d))
        seen = []
        for cross, _, _ in baselines:
            strokes = sorted((a, b) for y, a, b in baselines if abs(y - cross) <= epsilon * 1.6)
            intervals = []
            for a, b in strokes:
                if intervals and a <= intervals[-1][1] + max(depth * 1.1, epsilon * 4):
                    intervals[-1][1] = max(intervals[-1][1], b)
                else:
                    intervals.append([a, b])
            for a, b in intervals:
                if not a < center < b or b - a < depth * 2:
                    continue
                tip_margin = min(depth * .8, (b - a) * .13) + epsilon
                starts = [g for g in witnesses if abs(g[0] - a) <= tip_margin and min(g[1:]) - epsilon * 3 <= cross <= max(g[1:]) + epsilon * 3]
                ends = [g for g in witnesses if abs(g[0] - b) <= tip_margin and min(g[1:]) - epsilon * 3 <= cross <= max(g[1:]) + epsilon * 3]
                if not starts or not ends:
                    continue
                p = min(starts, key=lambda g: abs(g[0]-a))[0]
                q = min(ends, key=lambda g: abs(g[0]-b))[0]
                if any(max(abs(p-u), abs(q-v), abs(cross-w)) <= epsilon * 2 for u, v, w in seen):
                    continue
                seen.append((p, q, cross))
                yield axis, {"a": p, "b": q, "cross": cross, "guides": [[t, y, t, z] for t, y, z in starts + ends]}


def _observations(candidate, pages, region):
    value = _value(candidate.get("value"))
    if value is None:
        return []
    has_diameter_mark = _diameter_number(_text(candidate.get("evidence")), value)
    found = []
    contradictory_position = False
    for page in pages:
        if page["page"] != candidate.get("page", 1) or region and page["page"] != region.get("page", page["page"]):
            continue
        prior = _box(candidate, page)
        for text in page["texts"]:
            content = _text(text["text"])
            box = _original_box(text, page)
            if not _in_region(box, region):
                continue
            positioned = _matching_position(prior, box)
            labels = _label_roles(content, value)
            is_diameter = _diameter_number(content, value)
            if EXCLUDED.search(content) and not labels:
                contradictory_position |= bool(positioned)
                continue
            corrected = _normalized_mark(content, value, has_diameter_mark)
            corrected_mark = corrected != content and _diameter_number(corrected, value)
            bare = BARE_DIMENSION.fullmatch(content)
            is_bare = bool(bare and _value(bare[1]) == value)
            if not (labels or is_diameter or corrected_mark or is_bare):
                contradictory_position |= bool(positioned and re.match(rf"^\s*{MARK}\s*{NUMBER}", content))
                continue
            geometry = _dimension_roles(text, page, region) if not labels else []
            dimensions = [{"axis": axis, "endpoints": [d["a"], d["b"]], "baseline": d["cross"],
                           "page_size": [page["width"], page["height"]]}
                          for axis, d in _witness_dimensions(text, page)]
            if not (labels or is_diameter or geometry or (is_bare and (positioned or dimensions))):
                continue
            roles = labels or {field for field, _ in geometry}
            nominal = corrected if corrected_mark else content
            tolerance = {}
            offset_quality = 0
            for _, mark in geometry:
                a, b = mark["endpoints"]
                dimension = {"a": a, "b": b}
                values_by_side, quality = _stacked_tolerance(text, page, mark["axis"], dimension, value, nominal)
                if quality > offset_quality:
                    tolerance, offset_quality = {}, quality
                if quality < offset_quality:
                    continue
                for key, values in values_by_side.items():
                    tolerance.setdefault(key, set()).update(values)
            if not offset_quality:
                for key, offset in _observed_tolerance(nominal, value).items():
                    tolerance.setdefault(key, set()).add(offset)
            observation = {"position": box, "text": content, "page": page["page"],
                           "value": value, "unit": candidate.get("unit") or "mm",
                           "source": "pdf_text" if page.get("source") == "pdf_text_layer" else "local_ocr",
                           "method": "original_label" if labels else "dimension_witnesses",
                           "roles": sorted(roles), "geometry": [evidence for _, evidence in geometry],
                           "dimensions": dimensions,
                           "offsets": {key: sorted(values) for key, values in tolerance.items()},
                           "offset_quality": max(offset_quality, 2 if len(_observed_tolerance(nominal, value)) == 2 else 0)}
            if corrected_mark:
                observation["normalized_text"] = corrected
            overlap = next((o for o in found if _same_observation(o, observation)), None)
            if overlap:
                _merge_observation(overlap, observation)
            else:
                found.append(observation)
    positioned = [o for o in found if any(_matching_position(_box(candidate, p), o["position"])
                                         for p in pages if p["page"] == o["page"])]
    return positioned or ([] if contradictory_position else found)


def _matching_position(prior, original):
    return (prior and original and prior["width"] <= 3 * original["width"]
            and prior["height"] <= 3 * original["height"] and _same_box(prior, original))


def _same_observation(a, b):
    if not a or not b or a["page"] != b["page"] or a["value"] != b["value"]:
        return False
    if _same_box(a["position"], b["position"]):
        return True
    for first in a["geometry"]:
        for second in b["geometry"]:
            axis = first["axis"]
            if axis != second["axis"]:
                continue
            fsize, ssize = first["page_size"], second["page_size"]
            p = [first["baseline"]/fsize[1-axis], *(x/fsize[axis] for x in first["endpoints"])]
            q = [second["baseline"]/ssize[1-axis], *(x/ssize[axis] for x in second["endpoints"])]
            if max(abs(x-y) for x,y in zip(p,q)) < .005:
                return True
    return False


def _merge_observation(prior, observation):
    if observation["offset_quality"] > prior["offset_quality"]:
        prior["offsets"] = {}
        prior["offset_quality"] = observation["offset_quality"]
    if observation["offset_quality"] == prior["offset_quality"]:
        for key, values in observation["offsets"].items():
            prior["offsets"][key] = sorted(set(prior["offsets"].get(key, [])) | set(values))
    if observation["method"] == "original_label":
        if prior["method"] != "original_label":
            prior.update({k: observation[k] for k in ("method", "position", "text", "source", "roles")})
            return
    elif prior["method"] == "original_label":
        return
    prior["roles"] = sorted(set(prior["roles"]) | set(observation["roles"]))
    if observation["geometry"] and not prior["geometry"]:
        prior["geometry"] = observation["geometry"]


def is_diameter_candidate(candidate):
    field = candidate.get("field")
    if field in DIAMETERS:
        return True
    return field in {"free_length", "body_length", "dimension"} and _diameter_number(
        _text(candidate.get("evidence")), _value(candidate.get("value"))
    )


def diameter_ocr_requests(candidates):
    requests = []
    for candidate in candidates:
        value = _value(candidate.get("value"))
        if value is None or not is_diameter_candidate(candidate):
            continue
        page = candidate.get("page", 1)
        requests.append({"kind": "diameter_dimension", "field": candidate["field"], "page": page,
                         "evidence_pages": [page], "status": "unlocated", "original_value": value,
                         "position": candidate.get("position"),
                         "diameter_mark": _diameter_number(_text(candidate.get("evidence")), value),
                         "request_key": f"{VERSION}:{page}:{value}"})
    return requests


def _trusted_text_roles(candidate):
    source = str(candidate.get("source") or "").lower()
    if "qwen" in source or not any(s in source for s in ("ocr", "pdf_text", "werk24")):
        return set()
    return _label_roles(_text(candidate.get("evidence")), _value(candidate.get("value")))


def _roughness_marks(candidate, roughness, pages, region):
    from .surface_roughness import verified_roughness_candidate

    value = _value(candidate.get("value"))
    number = candidate.get("page", 1)
    for item in roughness:
        if _value(item.get("value")) != value or not verified_roughness_candidate(item):
            continue
        for ref in item["independent_evidence"]:
            if ref.get("page") != number or not _in_region(ref["position"], region):
                continue
            for page in pages:
                if page["page"] == number and page.get("source_document_id") == item["source_document_id"]:
                    yield ref["position"], page


def resolve_diameter_roles(candidates, pages=(), *, region=None):
    """Keep the original candidate in trace data and fuse only the verified field."""
    output, measurements, inferences = [], [], []
    roughness = [c for c in candidates if c.get("field") == "surface_roughness_ra"]
    for candidate in candidates:
        if candidate.get("field") == CANDIDATE and not candidate.get("selected_field") and not candidate.get("ignored") and model_derived_diameter(candidate):
            inferences.append(deepcopy(candidate))
            continue
        if candidate.get("field") in {CANDIDATE, INFERENCE} or candidate.get("source") == SOURCE or not is_diameter_candidate(candidate):
            output.append(candidate)
            continue
        if candidate.get("structured_specification"):
            output.append(candidate)
            continue
        value = _value(candidate.get("value"))
        text = _text(candidate.get("evidence"))
        if value is None:
            continue
        mixed_evidence = bool(_label_roles(text, value))
        printed_claim = _direct_claim(text, value)
        wire_claim = re.search(rf"(?:线径|簧丝直径|wire\s+diameter)\s*[:=]?\s*{MARK}?\s*({NUMBER})(?![\d.])", text, re.I)
        if not mixed_evidence and (re.search(r"[⊥∥⌖]|形位公差|几何公差", text) or wire_claim and _value(wire_claim[1]) == value):
            continue
        observations = _observations(candidate, pages, region) if mixed_evidence or printed_claim or not EXCLUDED.search(text) else []
        rough_marks = list(_roughness_marks(candidate, roughness, pages, region))
        if any(_matching_position(_box(candidate, page), box) for box, page in rough_marks):
            if not any(o["roles"] and any(p["page"] == o["page"] and
                       _matching_position(_box(candidate, p), o["position"]) for p in pages) for o in observations):
                continue
        ambiguous_mark = (rough_marks and not _diameter_number(text, value) and not _trusted_text_roles(candidate)
                          and not any(_matching_position(_box(candidate, page), o["position"])
                                      for o in observations for _, page in rough_marks))
        if not observations and model_derived_diameter(candidate):
            inferences.append(deepcopy(candidate))
            continue
        observation = observations[0] if len(observations) == 1 else None
        roles = set(observation["roles"]) if observation else set()
        if not observations and not EXCLUDED.search(text):
            roles = _trusted_text_roles(candidate)
        evidence = {"version": VERSION, "original_field": candidate["field"],
                    "observation": observation, "original_evidence": candidate.get("evidence"),
                    "original_position": deepcopy(candidate.get("position")), "original_source": candidate.get("source")}
        record = {**candidate, "diameter_role_evidence": evidence}
        if observation:
            record["position"] = observation["position"]
        role = next(iter(roles)) if len(roles) == 1 and not ambiguous_mark else None
        reason = ("原图文字尚未与直径候选对应。" if not observations else
                  "同页有多处相同数值，无法确定标注位置。" if len(observations) > 1 else
                  "原图证据指向多个直径类型。" if len(roles) > 1 else
                  "尺寸线两端尚未唯一对应弹簧边界。")
        if ambiguous_mark:
            reason = "原图还有同值粗糙度标注，候选位置待核对。"
            record["position"] = deepcopy(candidate.get("position"))
            record["diameter_role_evidence"]["observation"] = observation = None
        group = next((g for g in measurements if _same_observation(
            g[0][0]["diameter_role_evidence"]["observation"], observation)), None)
        if group is None:
            measurements.append([(record, role, reason)])
        else:
            group.append((record, role, reason))

    verified = [(entry[0]["diameter_role_evidence"]["observation"], entry[1])
                for group in measurements for entry in group if entry[1]]
    wires = {(_value(c.get("value")), str(c.get("unit") or "mm").lower())
             for c in candidates if c.get("field") == "wire_diameter" and _value(c.get("value")) is not None}
    for group in measurements:
        record, role, reason = next((m for m in group if m[1]), group[0])
        observation = record["diameter_role_evidence"]["observation"]
        if not role and observation and _axial_dimension(observation, verified):
            output.append({**record, "field": "axial_dimension_evidence", "feature_type": "dimension_evidence",
                           "value": {"kind": "axial_dimension", "value": record["value"], "unit": record.get("unit"),
                                     "evidence": record.get("evidence"), "position": record.get("position"), "page": record.get("page", 1),
                                     "reason": "尺寸线沿弹簧轴向跨越端面，不属于直径。"}})
            continue
        if inferences:
            record["diameter_role_evidence"]["model_derived_candidates"] = [deepcopy(c) for c in inferences if c.get("page", 1) == record.get("page", 1)]
        choices, offsets = set(), {}
        for entry, entry_role, _ in group:
            observation = entry["diameter_role_evidence"]["observation"]
            choices.update(observation["roles"] if observation else ([entry_role] if entry_role else []))
            for key, values in (observation or {}).get("offsets", {}).items():
                offsets.setdefault(key, set()).update(values)
        if len(choices) > 1:
            role, reason = None, "同一原图标注的直径类型存在冲突。"
        if role and len(wires) == 1 and _inconsistent_simple_dimensions(observation, role, next(iter(wires)), verified, record.get("unit")):
            role, reason = None, "同一视图的直径标注与线径关系不一致，请核对原图。"
        upper, lower = offsets.get("tolerance_upper"), offsets.get("tolerance_lower")
        if any(len(values) > 1 for values in offsets.values()) or upper and lower and min(upper) < max(lower):
            record["diameter_role_evidence"]["tolerance_options"] = {k: sorted(v) for k, v in offsets.items()}
            role, reason = None, "同一原图标注的公差证据存在冲突。"
            record.update(tolerance_upper=None, tolerance_lower=None)
        elif offsets or role and record["diameter_role_evidence"]["observation"]:
            record.update({key: next(iter(offsets.get(key, ())), None)
                           for key in ("tolerance_upper", "tolerance_lower")})
        if role:
            output.append({**record, "field": role, "source": SOURCE, "confidence": .99, "need_human_review": True})
            continue
        identity = [record.get(k) for k in ("page", "position", "value", "unit", "tolerance_upper", "tolerance_lower")]
        if not record.get("position"):
            identity.append(record.get("evidence"))
        identifier = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        if not any(c.get("candidate_id") == identifier for c in output):
            output.append({**record, "field": CANDIDATE, "candidate_id": identifier, "reason": reason})
    for candidate in inferences:
        output.append({**candidate, "field": INFERENCE, "feature_type": "dimension_evidence",
                       "value": {"kind": INFERENCE, "value": candidate["value"], "evidence": candidate.get("evidence"),
                                 "page": candidate.get("page", 1), "reason": "模型推导值，仅供追溯，不作为原图尺寸。"}})
    return output


def _direct_claim(text, value):
    for clause in re.split(r"[，,;；。\n]", text):
        if re.search(r"未(?:直接)?标|没有标|无.*标注|not\s+(?:shown|marked)", clause, re.I):
            continue
        # A formula mentioning drawing operands does not make its result a
        # printed dimension. Keep a separate original claim for this value.
        if _formula_result(clause, value):
            continue
        derived = DERIVATION.search(clause)
        if derived:
            clause = clause[:derived.start()]
            if not re.search(r"图中|图纸|原图|标注|marked|drawing", clause, re.I):
                continue
        if _diameter_number(clause, value):
            return True
        if re.search(r"图中|图纸|原图|标注|marked|drawing", clause, re.I) and any(
                _value(m[0]) == value for m in re.finditer(NUMBER, clause)):
            return True
    return False


def _formula_result(text, value):
    for match in re.finditer(rf"[=＝≈]\s*(?:约\s*)?{MARK}?\s*({NUMBER})(?![\d.])", text):
        if _value(match[1]) == value and re.search(r"[+\-−×*÷/]", text[:match.start()]):
            return True
    return False


def model_derived_diameter(candidate):
    """Classify a value, not the whole model explanation; never run OCR here."""
    evidence = candidate.get("diameter_role_evidence") or {}
    observation = evidence.get("observation") or {}
    if observation.get("source") in {"local_ocr", "pdf_text"} and _value(observation.get("value")) == _value(candidate.get("value")):
        return False
    value = _value(candidate.get("value"))
    if value is None:
        return False
    text = _text(candidate.get("evidence") or evidence.get("original_evidence"))
    source = candidate.get("source") or []
    source = [source] if isinstance(source, str) else source
    if "formula_calculation" in source or candidate.get("formula_calculation_kind") == "diameter_completion":
        return True
    return bool((DERIVATION.search(text) or _formula_result(text, value)) and not _direct_claim(text, value))


def _inconsistent_simple_dimensions(observation, role, wire, verified, unit):
    if not observation or str(unit or "mm").lower() not in {"mm", "毫米"} or wire[1] not in {"mm", "毫米"}:
        return False
    offsets = {"inner_diameter": -1, "mean_diameter": 0, "outer_diameter": 1}
    for other, field in verified:
        if not other or other["page"] != observation["page"] or other is observation or field == role:
            continue
        if str(other.get("unit") or "mm").lower() not in {"mm", "毫米"}:
            continue
        for first in observation.get("geometry", []):
            for second in other.get("geometry", []):
                if first.get("method") != "repeated_coil_arcs" or second.get("method") != "repeated_coil_arcs" or first["axis"] != second["axis"]:
                    continue
                axis = first["axis"]
                fsize, ssize = first["page_size"], second["page_size"]
                radius = max(first["radius"]/fsize[axis], second["radius"]/ssize[axis])
                if max(abs(a/fsize[axis]-b/ssize[axis]) for a,b in zip(first["centers"], second["centers"])) > radius:
                    continue
                a = [v/fsize[1-axis] for v in first["axial_extent"]]
                b = [v/ssize[1-axis] for v in second["axial_extent"]]
                if min(a[1],b[1])-max(a[0],b[0]) < min(a[1]-a[0],b[1]-b[0])*.3:
                    continue
                expected = (offsets[role]-offsets[field])*wire[0]
                if not math.isclose(observation["value"]-other["value"], expected, abs_tol=1e-6):
                    return True
    return False


def _axial_dimension(observation, verified):
    for original, _ in verified:
        if not original or original["page"] != observation["page"]:
            continue
        for geometry in original.get("geometry", []):
            if geometry.get("method") != "repeated_coil_arcs":
                continue
            for dimension in observation.get("dimensions", []):
                if dimension["axis"] == geometry["axis"]:
                    continue
                axis = dimension["axis"]
                dsize, gsize = dimension["page_size"], geometry["page_size"]
                a, b = [v/dsize[axis] for v in dimension["endpoints"]]
                start, end = [v/gsize[axis] for v in geometry["axial_extent"]]
                radius = geometry["radius"]/gsize[axis]
                # Both end witnesses encompass this particular coil view.
                if max(abs(a-start), abs(b-end)) > radius*3:
                    continue
                lo, hi = [v/gsize[1-axis] for v in geometry["centers"]]
                if lo-(hi-lo)*.6 <= dimension["baseline"]/dsize[1-axis] <= hi+(hi-lo)*.6:
                    return True
    return False


def has_pending_roles(review):
    return bool(pending_roles(review))


def pending_roles(review):
    return [item for item in review.get(PENDING) or [] if isinstance(item, dict)
            and not item.get("selected_field") and not item.get("ignored") and not model_derived_diameter(item)]


def ignore_role(review, candidate_id):
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("缺少直径候选标识，请刷新后核对。")
    candidate = next((item for item in review.get(PENDING, []) if item.get("candidate_id") == candidate_id), None)
    if candidate is None or candidate.get("selected_field"):
        raise ValueError("这条直径标注已处理或不存在，请刷新后核对。")
    candidate["ignored"] = True
    return candidate


def resolve_specification_diameters(candidates, origin, local, blocks):
    from .drawing_annotations import _scoped_matches, _specification_region_conflict, _unique_blocks

    result, unresolved = [], []
    blocked = not origin["region"] or _specification_region_conflict({"multi_spec_origin": origin}, blocks)
    for candidate in candidates:
        original_field = candidate.get("field")
        if original_field not in DIAMETERS:
            result.append(candidate)
            continue
        value = _value(candidate.get("value"))
        context = {"multi_spec_origin": {**origin, "field_origins": {
            field: "local" if original_field in local else "common" for field in DIAMETERS
        }}}
        found = []
        if value is not None and not blocked:
            for field in DIAMETERS:
                for block in _unique_blocks([b for _, b in _scoped_matches(context, field, value, blocks)]):
                    if block["page"] == origin["region"]["page"]:
                        found.append((field, block))
        if len(found) != 1:
            unresolved.append({k: v for k, v in candidate.items() if k != "structured_specification"})
            continue
        field, block = found[0]
        observation = {"position": {**block["position"], "coordinate_type": "normalized", "origin": "top_left"},
                       "page": block["page"], "value": value, "text": block["text"],
                       "method": "verified_specification_cell", "source": block.get("source", "local_ocr"), "roles": [field]}
        result.append({**candidate, "tolerance_upper": None, "tolerance_lower": None,
                       **_observed_tolerance(_text(block["text"]), value),
                       "field": field, "source": SOURCE, "confidence": .99,
                       "position": observation["position"], "page": observation["page"],
                       "diameter_role_evidence": {"version": VERSION, "original_field": original_field,
                                                  "original_evidence": candidate.get("evidence"), "observation": observation}})
    return [*result, *resolve_diameter_roles(unresolved)]


def select_role(review, candidate_id, field):
    """Apply one operator decision to the saved source measurement."""
    if field not in DIAMETERS:
        raise ValueError("请选择内径、中径或外径。")
    candidate = next((item for item in review.get(PENDING, []) if item["candidate_id"] == candidate_id), None)
    if candidate is not None and candidate.get("selected_field") == field:
        return candidate
    if candidate is None or candidate.get("selected_field") or candidate.get("ignored") or model_derived_diameter(candidate):
        raise ValueError("这条直径标注已处理，请刷新后核对。")
    from .standardizers.diameters import apply_formula_compression_diameter_completion
    from .diameter_linkage import supported
    from .standardizers.calculation_state import human_override, sources
    if not supported(review):
        raise ValueError("当前结构不适用圆柱圆截面弹簧三径联动。")

    parameters = review["spring_parameters"]
    current = parameters.get(field) or {}
    upper, lower = candidate.get("tolerance_upper"), candidate.get("tolerance_lower")
    existing = current.get("value")
    if existing not in (None, "") and not any(s in (current.get("source") or []) for s in
                                               ("formula_calculation", "solidworks_protocol_default")):
        if (_value(existing), current.get("unit") or "mm", current.get("tolerance_upper"), current.get("tolerance_lower")) != (
            _value(candidate["value"]), candidate.get("unit") or "mm", upper, lower
        ):
            raise ValueError("该字段已有不同的原图或人工尺寸，请先核对该尺寸。")
    item = {**current, **{k: deepcopy(candidate.get(k)) for k in ("value", "evidence", "page", "position")},
            "unit": candidate.get("unit") or "mm", "tolerance_upper": upper, "tolerance_lower": lower,
            "diameter_role_evidence": deepcopy(candidate["diameter_role_evidence"]),
            "source": [SOURCE, "human_diameter_role"], "need_human_review": True,
            "status": "need_review", "confidence": .99}
    for key in ("default_source", "formula_calculation_kind", "formula_dependencies", "diameter_linkage_managed",
                "formula_recommendation_stale", "derived_value_stale", "diameter_linkage_error"):
        item.pop(key, None)
    parameters[field] = item
    candidate["selected_field"] = field
    review.pop("diameter_linkage", None)
    affected = {field}
    for other in DIAMETERS:
        if other == field or not isinstance(parameters.get(other), dict):
            continue
        old = parameters[other]
        if "formula_calculation" in sources(old) and not human_override(old):
            parameters[other] = {"value": None, "unit": old.get("unit") or "mm", "need_human_review": True}
            affected.add(other)
        else:
            old.pop("diameter_linkage_managed", None)
    apply_formula_compression_diameter_completion(parameters)
    affected.update(f for f in DIAMETERS if "formula_calculation" in sources(parameters.get(f) or {}))
    for changed in affected:
        param = parameters.get(changed) or {}
        param["need_human_review"] = True
        param["status"] = "need_review"
        for key, entry in (review.get("manual_confirmations") or {}).items():
            if isinstance(entry, dict) and (key == changed or key.endswith("_" + changed) or entry.get("target_field") == changed):
                entry.update(confirmed=False, revoked_reason="diameter_role_selected")
    return candidate
