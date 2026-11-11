"""Read nominal working height and its own printed deviations."""
from __future__ import annotations

import re
import unicodedata

from .load_height_relations import millimeters

DECIMAL = r"\d+(?:\.\d+)?"
UNIT = r"(?:mm|毫米|cm|厘米|inch|in|m|米)(?![A-Za-z])"
NOMINAL = re.compile(rf"(?P<open>\()?\s*(?P<value>{DECIMAL})(?![\d.])\s*(?P<unit>{UNIT})?", re.I)
HEIGHT_NAME = re.compile(r"^([HL]\s*\d*)\s*[=:]\s*", re.I)
DEVIATIONS = re.compile(
    rf"(?:±\s*(?P<symmetric>{DECIMAL})|\+\s*(?P<upper>{DECIMAL})(?:\s*/?\s*(?P<lower>-\s*{DECIMAL})|\s*(?:/|\n)\s*(?P<zero>0)))(?![\d.])"
)
OFFSET = re.compile(rf"(?:[+\-]\s*{DECIMAL}|0)")
HEIGHT_FIELDS = ("height_label", "height_tolerance_upper", "height_tolerance_lower", "height_tolerance_status")


def _normalized(text):
    return re.sub(r"\+\s*/\s*-","±",unicodedata.normalize("NFKC", text).replace("−", "-").replace("士", "±"))


def read_height_dimension(text, *, prefix=False):
    """For prose, parse the dimension at the start of an already matched height clause."""
    text = _normalized(text).strip()
    name=HEIGHT_NAME.match(text)
    if name:
        text=text[name.end():]
    nominal = NOMINAL.match(text)
    if not nominal or float(nominal["value"]) <= 0:
        return None
    rest = text[nominal.end():].lstrip()
    offsets = DEVIATIONS.match(rest)
    unit = nominal["unit"]
    fields = {}
    if offsets:
        rest = rest[offsets.end():].lstrip()
        suffix_unit = re.match(UNIT, rest, re.I)
        if suffix_unit and not unit:
            unit = suffix_unit.group()
            rest = rest[suffix_unit.end():].lstrip()
        if offsets["symmetric"] is not None:
            upper = float(offsets["symmetric"])
            lower = -upper
        else:
            upper = float(offsets["upper"])
            lower = float(re.sub(r"\s+", "", offsets["lower"] or offsets["zero"]))
        fields = {
            "height_tolerance_upper": millimeters(upper, unit or "mm"),
            "height_tolerance_lower": millimeters(lower, unit or "mm"),
        }
    elif rest.startswith(("+", "-", "±")):
        partial = re.match(rf"[+\-±]\s*(?:{DECIMAL})?\s*(?:/\s*[+\-]?)?", rest)
        rest = rest[partial.end():].lstrip()
        fields["height_tolerance_status"] = "uncertain"
    if rest.startswith(")") and nominal["open"]:
        rest = rest[1:].lstrip()
    if fields and rest.startswith(("%", "+", "-", "±")):
        fields = {"height_tolerance_status": "uncertain"}
    elif rest and not prefix:
        return None
    return {"value": float(nominal["value"]), "unit": unit or "mm",
            "reference_only": bool(nominal["open"]), **({"height_label":re.sub(r"\s+","",name[1])} if name else {}), **fields}


def dimension_with_offsets(text, neighbors, baseline):
    """Attach stacked deviations only within the dimension's own text band."""
    parsed = read_height_dimension(text["text"])
    if not parsed or any(key in parsed for key in HEIGHT_FIELDS[1:]):
        return parsed, text
    _, y, right, bottom = text["bbox"]
    height = max(3, bottom - y)
    offsets = []
    for other in neighbors:
        if other is text:
            continue
        value = _normalized(other["text"]).strip()
        if not OFFSET.fullmatch(value):
            continue
        left, top, _, low = other["bbox"]
        if right - height * .25 <= left <= right + height * .85 and y - height * .7 <= top < bottom and low <= baseline + height * .2:
            offsets.append((other, re.sub(r"\s+", "", value)))
    if not offsets or not any(value != "0" for _, value in offsets):
        return parsed, text
    ordered = sorted(offsets, key=lambda entry: entry[0]["bbox"][1])
    if len(ordered) == 2 and ordered[0][1].startswith("+") and ordered[1][1].startswith(("-", "0")):
        parsed.update(height_tolerance_upper=millimeters(ordered[0][1], parsed["unit"]),
                      height_tolerance_lower=millimeters(ordered[1][1], parsed["unit"]))
    else:
        parsed["height_tolerance_status"] = "uncertain"
    boxes = [text["bbox"], *(entry[0]["bbox"] for entry in ordered)]
    evidence = {"text": "\n".join([text["text"], *(entry[0]["text"] for entry in ordered)]),
                "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                         max(b[2] for b in boxes), max(b[3] for b in boxes)]}
    return parsed, evidence
