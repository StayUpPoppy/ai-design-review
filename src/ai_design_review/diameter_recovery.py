"""Recover unrepresented diameter marks from positioned table and drawing text."""

import json
import re
from hashlib import sha256
from math import isfinite

from .diameter_evidence import (
    CANDIDATE, DIAMETERS, INFERENCE, LABELS, MARK, NUMBER, SOURCE, VERSION,
    _box, _in_region, _observed_tolerance, _original_box,
    _same_box, _text, _value, original_observation,
)

RECOVERY_VERSION = "diameter-recovery/v1"
_NOMINAL = re.compile(rf"^\s*{MARK}?\s*({NUMBER})(?![\d.])")
_UNIT = re.compile(r"^(?:mm|in\.?|inch(?:es)?|毫米|英寸|[\"″])$", re.I)
_SUFFIX = re.compile(r"(?<![A-Z])[O0○]\s*\.?\s*D\.?$", re.I)
_GAUGE = re.compile(r"\bgag(?:e|es)\b|\bgauges?\b|\bfit\b|\bgo\s+into\b|\bcylinder\b|环规|量规", re.I)
_SYMBOL = re.compile(r"D\s*[12oim]?", re.I)
_TWO_OFFSETS = re.compile(rf"^\s*([+-]\s*{NUMBER}|0)\s*/?\s*([+-]\s*{NUMBER})\s*$")


def _row(a, b, fraction=.42):
    return abs((a[1] + a[3] - b[1] - b[3]) / 2) <= fraction * min(a[3] - a[1], b[3] - b[1])


def _labels(text):
    return {field for field, pattern in LABELS.items() if re.fullmatch(pattern, _text(text), re.I)}


def _table_marks(page, region):
    for label in page["texts"]:
        roles = _labels(label["text"])
        if len(roles) != 1:
            continue
        box = label["bbox"]
        font = box[3] - box[1]
        if font <= 0:
            continue
        right = sorted((t for t in page["texts"] if not t.get("diameter_crop_slot") and 0 <= t["bbox"][0] - box[2] <= 20 * font and _row(box, t["bbox"])
                        and _in_region(_original_box(t, page), region)), key=lambda t: t["bbox"][0])
        if not _in_region(_original_box(label, page), region):
            continue
        for index in range(len(right) - 2):
            symbol, nominal, unit = right[index:index + 3]
            symbol_text = _text(symbol["text"])
            value_text = _text(nominal["text"])
            unit_text = _text(unit["text"])
            field = next(iter(roles))
            if not (_SYMBOL.fullmatch(symbol_text) and re.fullmatch(NUMBER, value_text) and _UNIT.fullmatch(unit_text)):
                continue
            if symbol_text[-1].lower() in {"1", "2", "i", "o", "m"} and symbol_text[-1].lower() not in {
                "inner_diameter": {"1", "i"}, "outer_diameter": {"2", "o"}, "mean_diameter": {"m"},
            }[field]:
                continue
            if max(nominal["bbox"][0] - symbol["bbox"][2], unit["bbox"][0] - nominal["bbox"][2]) > font * 5:
                continue
            yield {"field": field, "value": float(value_text), "unit": unit_text, "text": " ".join(
                (_text(label["text"]), symbol_text, value_text, unit_text)), "box": nominal["bbox"], "method": "diameter_table_cells"}


def _outer_callout(text):
    normalized = text.replace("。", ".").rstrip(" .")
    suffix = _SUFFIX.search(normalized)
    if suffix and (suffix.start() == 0 or (nominal := _NOMINAL.match(normalized)) and
                   re.fullmatch(r"[\s\d.±+/\-−]*", normalized[nominal.end():suffix.start()])):
        return suffix
    return None


def is_explicit_callout(candidate):
    text = _text(candidate.get("evidence"))
    return candidate.get("field") == "outer_diameter" and not _GAUGE.search(text) and bool(_outer_callout(text))


def _explicit_diameters(candidates, page):
    return {c["field"] for c in candidates if c.get("field") in DIAMETERS and c.get("page", 1) == page
            and (is_explicit_callout(c) or re.search(r"[I1]\s*\.?\s*D\.?\s*$", _text(c.get("evidence")), re.I))}


def _horizontal_callout(page, box):
    """Locate the annotation beside a horizontal dimension with two witnesses."""
    left, top, right, bottom = box
    height = bottom - top
    if not 3 <= height <= page["height"] * .05:
        return None
    lines = [*page["lines"], *page.get("line_segments", ())]
    for x, y, z, v in lines:
        a, b, cross = min(x, z), max(x, z), (y + v) / 2
        if (abs(y - v) > max(1, (b - a) * .03) or b - a < 3 * height
                or not top - .25 * height <= cross <= bottom + .25 * height
                or not -.6 * height <= left - b <= 1.9 * height):
            continue
        witnesses = sorted((u + w) / 2 for u, c, w, d in lines
                           if abs(u - w) <= 2 and abs(c - d) >= .55 * height
                           and min(c, d) - 2 <= cross <= max(c, d) + 2 and a - 3 <= (u + w) / 2 <= b + 3)
        if witnesses and witnesses[-1] - witnesses[0] >= 2 * height:
            return cross
    return None


def _mark_blocks(page, value, region):
    for token in page["texts"]:
        if token.get("diameter_crop_slot") or not _in_region(_original_box(token, page), region):
            continue
        text = _text(token["text"])
        match = _NOMINAL.match(text)
        if not match or _GAUGE.search(text):
            continue
        suffix = _outer_callout(text)
        if not re.fullmatch(r"[\s\d.±+/\-−]*", text[match.end():suffix.start() if suffix else None]):
            continue
        read = match[1]
        partial = _value(read) != value
        if partial and not (len(read) >= 4 and str(value).startswith(read) and len(str(value)) - len(read) == 1 and match.end() == len(text)):
            continue
        baseline = _horizontal_callout(page, token["bbox"])
        if baseline is not None:
            yield token, baseline, partial


def _segment_callout(image, page, box, baseline):
    import cv2
    import numpy as np

    width, height = image.size
    scale = width / page["width"]
    left, top, right, bottom = box
    font = bottom - top
    x0, y0, x1, y1 = (round(v * scale) for v in (
        max(0, left - font * .6), baseline - font * .85,
        min(page["width"], right + 6 * font), baseline + font * .85,
    ))
    if y0 < 0 or y1 > height or x0 >= x1:
        return {}
    ink = np.asarray(image.crop((x0, y0, x1, y1)).convert("L")) < 175
    _, _, components, _ = cv2.connectedComponentsWithStats(ink.astype("uint8"))
    glyphs = [(x + x0, y + y0, w, h) for x, y, w, h, area in components[1:] if area >= 5]
    baseline *= scale
    font *= scale
    digits = sorted(g for g in glyphs if .28 * font <= g[3] <= .9 * font and g[2] <= g[3] * 1.1
                    and abs(g[1] + g[3] / 2 - baseline) < .25 * g[3])
    # Find the decimal group, separating its full-height characters from the
    # smaller symbols beside it. The crop is then read independently by OCR.
    for lead, second, third, last in zip(digits, digits[1:], digits[2:], digits[3:]):
        step = (last[0] - second[0]) / 2
        if not (.5 * min(lead[3], second[3]) <= step <= 1.65 * second[3]
                and all(.8 * step <= b[0] - a[0] <= 1.2 * step for a, b in ((second, third), (third, last)))
                and 1.25 * step <= second[0] - lead[0] <= 2.2 * step
                and max(g[3] for g in (lead, second, third, last)) <= 1.2 * min(g[3] for g in (lead, second, third, last))):
            continue
        dot = any(lead[0] + lead[2] < x < second[0] and y > baseline and h < .45 * lead[3] for x, y, w, h in glyphs)
        if not dot:
            continue
        after = last[0] + last[2]
        suffix = next((g for g in digits if 2.7 * step < g[0] - after < 7 * step and g[3] >= .86 * lead[3]), None)
        if not suffix:
            continue
        pad = .18 * step
        top, bottom = min(g[1] for g in (lead, second, third, last)), max(g[1] + g[3] for g in (lead, second, third, last))
        split = baseline + .06 * step
        left_offset, right_offset = after + .2 * step, suffix[0] - .2 * step
        slots = {"nominal": (lead[0] - pad, top - pad, after + pad, bottom + pad),
                 "suffix": (suffix[0] - pad, top - pad, min(x1, suffix[0] + 4 * step), bottom + pad),
                 "upper": (left_offset, top - .65 * step, right_offset, split),
                 "lower": (left_offset, split, right_offset, bottom + .6 * step)}
        return {key: (a / width, b / height, c / width, d / height) for key, (a, b, c, d) in slots.items()}
    return {}


def callout_crop_regions(image, page, candidates, baseline, region):
    if len(_explicit_diameters(candidates, page["page"])) > 1:
        return []
    crops, locations = [], []
    for candidate in candidates:
        if (not is_explicit_callout(candidate) or candidate.get("page", 1) != page["page"] or _covered(candidate, baseline, page)):
            continue
        complete = [_original_box({"bbox": mark["box"]}, page) for mark in _drawing_marks(candidate, page, region)
                    if mark["field"] and not mark["pending"]]
        prior = _box(candidate, page)
        for token, line, _ in _mark_blocks(page, _value(candidate["value"]), region):
            origin = _original_box(token, page)
            if prior and not _same_box(prior, origin) or any(_same_box(origin, old) for old in locations + complete):
                continue
            slots = _segment_callout(image, page, token["bbox"], line)
            if not slots or region and any(not (region["x"] <= a < c <= region["x"] + region["width"] and
                                               region["y"] <= b < d <= region["y"] + region["height"])
                                           for a, b, c, d in slots.values()):
                continue
            locations.append(origin)
            crops.extend(((*bounds, 0), {"diameter_crop_origin": origin, "diameter_crop_slot": slot,
                                         "diameter_recovery_version": RECOVERY_VERSION}) for slot, bounds in slots.items())
            if len(crops) == 12:
                return crops
    return crops


def locatable_callout_keys(candidates, pages):
    """Let positioned callouts use their specific crop instead of the general OCR regions."""
    return {(page["page"], value) for page in pages if len(_explicit_diameters(candidates, page["page"])) <= 1
            for candidate in candidates if candidate.get("page", 1) == page["page"] and is_explicit_callout(candidate)
            and (value := _value(candidate.get("value"))) is not None and next(_mark_blocks(page, value, None), None)}


def _observed_offsets(text):
    match = _TWO_OFFSETS.fullmatch(text.replace("−", "-"))
    if not match:
        return None
    upper, lower = (float(part.replace(" ", "")) for part in match.groups())
    return (upper, lower) if upper >= 0 >= lower else None


def _callout_offsets(text):
    nominal = _NOMINAL.match(text)
    suffix = _outer_callout(text)
    if not nominal:
        return None
    return _observed_offsets(text[nominal.end():suffix.start() if suffix else None])


def _crop_readings(page, box):
    readings = {}
    position = _original_box({"bbox": box}, page)
    for token in page["texts"]:
        origin = token.get("diameter_crop_origin")
        if origin and _same_box(position, origin):
            readings.setdefault(token["diameter_crop_slot"], set()).add(_text(token["text"]).replace("。", "."))
    return readings


def attach_callout_blocks(pages, blocks):
    for block in blocks:
        box = block["position"]
        for page in pages:
            if page["page"] != block["page"] or page.get("source") == "pdf_text_layer":
                continue
            page["texts"].append({**block, "bbox": [box["x"] * page["width"], box["y"] * page["height"],
                                                     (box["x"] + box["width"]) * page["width"],
                                                     (box["y"] + box["height"]) * page["height"]]})


def _drawing_marks(candidate, page, region):
    if not is_explicit_callout(candidate):
        return
    value = _value(candidate["value"])
    for token, _, partial in _mark_blocks(page, value, region):
        box, raw = token["bbox"], _text(token["text"])
        reads = _crop_readings(page, box)
        nominals = {_value(text) for text in reads.get("nominal", ()) if re.fullmatch(NUMBER, text)} - {None}
        if (partial and not nominals) or nominals and nominals != {value}:
            continue
        suffix = _outer_callout(raw) or any(_outer_callout(text) for text in reads.get("suffix", ()))
        font = box[3] - box[1]
        if not suffix:
            suffix = any(_SUFFIX.fullmatch(_text(t["text"]).replace("。", "."))
                         and _row(box, t["bbox"], .75) and -.4 * font <= t["bbox"][0] - box[2] <= 5 * font
                         and _in_region(_original_box(t, page), region) for t in page["texts"] if not t.get("diameter_crop_slot"))
        upper = {_value(t[1:]) if t != "+0" else 0. for t in reads.get("upper", ()) if re.fullmatch(rf"\+{NUMBER}", t)} - {None}
        lower = {float(t) for t in reads.get("lower", ()) if re.fullmatch(rf"-{NUMBER}", t)}
        model_offsets = (candidate.get("tolerance_upper"), candidate.get("tolerance_lower"))
        model_pair = _callout_offsets(_text(candidate.get("evidence")))
        # The raw model wording can identify a suspicious merged OCR '±', but
        # only independently printed offset tokens can supply the final pair.
        if model_pair is not None:
            model_offsets = model_pair
        offsets = _observed_tolerance(raw, value)
        pair = _callout_offsets(raw)
        if len(upper) == len(lower) == 1:
            pair = (next(iter(upper)), next(iter(lower)))
        if pair is None and len(offsets) == 2 and (offsets["tolerance_upper"], offsets["tolerance_lower"]) == model_offsets:
            pair = model_offsets
        pending = pair is None and (bool(offsets or upper or lower) or any(x is not None for x in model_offsets))
        excerpt = raw
        if partial or upper and lower or pending:
            excerpt = str(value)
            if pair:
                excerpt += f" {pair[0]:+g}/{pair[1]:+g}"
            if suffix:
                excerpt += " O.D."
        yield {"field": "outer_diameter" if suffix else None, "value": value, "unit": candidate.get("unit"),
               "text": excerpt, "box": box, "method": "diameter_callout", "pair": pair, "pending": pending,
               "readings": {"line": [raw], **{key: sorted(items) for key, items in reads.items()}}}


def _covered(candidate, baseline, page):
    for item in baseline:
        if item.get("source") != SOURCE and not (original_observation(item) or item.get("selected_field") or item.get("ignored")):
            continue
        original = original_observation(item)
        if item.get("page", 1) != candidate.get("page", 1):
            continue
        prior = _box(candidate, page)
        if prior and original:
            if _same_box(prior, original["position"]):
                return True
            continue
        if _value((item.get("engineering_source") or {}).get("value", item.get("value"))) != _value(candidate.get("value")):
            continue
        field = (item.get("diameter_role_evidence") or {}).get("original_field", item["field"])
        if field == candidate["field"] or item.get("field") == candidate["field"]:
            return True
    return False


def recover_diameters(candidates, baseline, pages, *, region=None, protected=(), allow_callouts=True):
    """Return the legacy resolution with only uncovered, verified marks added."""
    from .engineering_units import factor

    pending = list(baseline)
    eligible = [c for c in candidates if c.get("field") in DIAMETERS and c["field"] not in protected
                and not c.get("structured_specification") and _value(c.get("value")) is not None]
    for page in pages:
        needed = [c for c in eligible if c.get("page", 1) == page["page"] and not _covered(c, pending, page)]
        if not needed:
            continue
        table = list(_table_marks(page, region))
        probe_callouts = allow_callouts and len(_explicit_diameters(candidates, page["page"])) <= 1
        for candidate in needed:
            value = _value(candidate.get("value"))
            field = candidate.get("field")
            if _covered(candidate, pending, page):
                continue
            marks = [mark for mark in table if mark["field"] == field and mark["value"] == value]
            matches = marks or (list(_drawing_marks(candidate, page, region)) if probe_callouts else [])
            unique = []
            for mark in matches:
                position = _original_box({"bbox": mark["box"]}, page)
                match = next((old for old in unique if _same_box(old["position"], position)), None)
                if not match:
                    unique.append({**mark, "position": position})
                elif (bool(mark["field"]), bool(mark.get("pair"))) > (bool(match["field"]), bool(match.get("pair"))):
                    match.update({**mark, "position": position})
            if (prior := _box(candidate, page)) is not None:
                unique = [mark for mark in unique if _same_box(prior, mark["position"])]
            if len(unique) != 1:
                continue
            mark = unique[0]
            unit = mark["unit"]
            if factor("length", unit) is None or candidate.get("unit_pending") and mark["method"] != "diameter_table_cells":
                continue
            pair = mark.get("pair") or (None, None)
            role = mark["field"]
            observation = {"page": page["page"], "position": mark["position"], "text": mark["text"],
                           "value": value, "unit": unit, "roles": [role] if role else [], "method": mark["method"],
                           "source": "pdf_text" if page.get("source") == "pdf_text_layer" else "local_ocr", "geometry": [],
                           "callout_verified": mark["method"] == "diameter_callout"}
            if mark.get("readings"):
                observation["readings"] = mark["readings"]
            record = {**candidate, "field": role or CANDIDATE, "position": mark["position"], "evidence": mark["text"],
                      "unit": unit, "tolerance_upper": pair[0], "tolerance_lower": pair[1], "need_human_review": True,
                      "diameter_role_evidence": {"version": VERSION, "recovery_version": RECOVERY_VERSION,
                                                 "original_field": field, "observation": observation}}
            record.pop("unit_pending", None)
            record.pop("engineering_source", None)
            if mark.get("pending"):
                record["diameter_tolerance_pending"] = True
            if role:
                record.update(source=SOURCE, confidence=.99)
            else:
                identity = json.dumps([page["page"], mark["position"], value, unit], sort_keys=True)
                record.update(candidate_id=sha256(identity.encode()).hexdigest()[:20], reason="原图直径尺寸已定位，请核对直径类型。")
            pending.append(record)
    return pending


def validate_tolerance_resolution(review, previous, events):
    edited = {event.get("target_field") for event in events if event.get("event_type") == "parameter_tolerance_updated"}
    for field in DIAMETERS:
        old = (previous.get("spring_parameters") or {}).get(field) or {}
        if not old.get("diameter_tolerance_pending"):
            continue
        item = review.setdefault("spring_parameters", {}).setdefault(field, {})
        if item.get("diameter_tolerance_pending"):
            item["need_human_review"] = True
            continue
        upper, lower = item.get("tolerance_upper"), item.get("tolerance_lower")
        valid = upper is None and lower is None or (
            all(type(n) in (int, float) and isfinite(n) for n in (upper, lower)) and upper >= lower
        )
        if field not in edited or not valid or item.get("tolerance_input_draft"):
            raise ValueError("直径公差待核对，请填写有效偏差或在公差编辑器中清除。")
