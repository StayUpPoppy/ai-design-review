"""Original drawing units and the metric quantities used for review and output."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from collections import defaultdict
import re
import unicodedata
from math import isfinite


VERSION = "engineering-units/v1"
INCH = Decimal("25.4")
KGF = Decimal("9.80665")
POUND = Decimal("0.45359237")
LBF = POUND * KGF
KSI = LBF / (INCH * INCH) * 1000
METRIC = {"length": "mm", "force": "N", "rate": "N/mm", "stress": "MPa", "mass": "kg",
          "roughness": "μm", "density": "g/cm³", "moment": "N·mm"}
FACTORS = {
    "length": {"mm": 1, "毫米": 1, "cm": 10, "厘米": 10, "m": 1000, "米": 1000, "in": INCH,
               "inch": INCH, "inches": INCH, "英寸": INCH, '"': INCH, "″": INCH, "ft": INCH * 12},
    "force": {"n": 1, "牛": 1, "牛顿": 1, "kn": 1000, "kgf": KGF, "kg": KGF, "lbf": LBF, "lb": LBF, "lbs": LBF},
    "rate": {"n/mm": 1, "kn/mm": 1000, "kgf/mm": KGF, "kg/mm": KGF, "n/m": Decimal(".001"),
             "lbf/in": LBF / INCH, "lb/in": LBF / INCH, "lbs/in": LBF / INCH},
    "stress": {"mpa": 1, "n/mm2": 1, "gpa": 1000, "kpa": Decimal(".001"), "pa": Decimal(".000001"),
               "ksi": KSI, "psi": KSI / 1000},
    "mass": {"kg": 1, "g": Decimal(".001"), "lb": POUND, "lbs": POUND},
    "roughness": {"μm": 1, "um": 1, "μin": Decimal(".0254"), "uin": Decimal(".0254"),
                  "microinch": Decimal(".0254"), "microinches": Decimal(".0254")},
    "density": {"g/cm3": 1, "kg/m3": Decimal(".001"), "lb/in3": POUND * 1000000 / INCH**3},
    "moment": {"n·mm": 1, "n·m": 1000, "lbf·in": LBF * INCH},
}
FIELDS = {
    **dict.fromkeys(("wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "free_height",
                    "pitch", "solid_height", "wire_length", "installed_height", "working_height", "height", "deflection",
                    "min_working_length", "max_solid_length", "body_length", "length", "distance"), "length"),
    **dict.fromkeys(("spring_rate", "theoretical_spring_rate", "stiffness"), "rate"),
    **dict.fromkeys(("shear_stress", "stress", "solid_stress", "work_stress", "shear_modulus", "elastic_modulus"), "stress"),
    **dict.fromkeys(("force", "load", "solid_load", "working_load"), "force"),
    **dict.fromkeys(("weight", "unit_mass", "mass"), "mass"),
    "surface_roughness_ra": "roughness", "density": "density", "torque": "moment",
}
DECIMAL = r"[+\-−]?(?:\d+(?:\.\d+)?|\.\d+)"


def unit_key(unit):
    text = unicodedata.normalize("NFKC", str(unit or "")).casefold().strip().rstrip(".")
    text = re.sub(r"\bper\s+", "/", text)
    text = re.sub(r"\binch(?:es)?\b", "in", text)
    text = re.sub(r"\bmillimet(?:er|re)s?\b", "mm", text)
    aliases = {"英寸": "in", "毫米": "mm", "磅力": "lbf", "英磅": "lb", "磅": "lb", "公斤力": "kgf", "公斤": "kg", "牛顿": "n"}
    text = re.sub(r"[\s^]", "", text).replace("in.", "in").replace("每", "/")
    return "/".join(aliases.get(part, part) for part in text.split("/"))


def factor(kind, unit):
    value = FACTORS.get(kind, {}).get(unit_key(unit))
    return Decimal(value) if value is not None else None


def converted(value, multiplier):
    if value in (None, "") or isinstance(value, bool) or multiplier is None:
        return None
    try:
        result = float(Decimal(str(value).replace("−", "-")) * multiplier)
        return result if isfinite(result) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def quantity(field, unit=None):
    if field in FIELDS:
        return FIELDS[field]
    matches = [kind for kind in FACTORS if factor(kind, unit) is not None]
    return matches[0] if len(matches) == 1 else None


def metric_item(item, field=None):
    kind = quantity(field, item.get("unit"))
    source_unit = item.get("unit")
    if not kind or not source_unit or item.get("unit_pending"):
        return item
    scale = factor(kind, source_unit)
    if scale is None:
        return {**item, "unit_pending": True, "need_human_review": True} if item.get("value") not in (None, "") else item
    unit = METRIC[kind]
    if source_unit == unit:
        return item
    keys = ("value", "tolerance_upper", "tolerance_lower", "lower_limit", "upper_limit", "minimum", "maximum", "min", "max")
    changed = {key: v for key in keys if key in item and (v := converted(item[key], scale)) is not None}
    result = {**item, **changed, "unit": unit, "engineering_source": item.get("engineering_source") or {
        **{key: item[key] for key in (*keys, "unit", "evidence", "position", "page") if key in item}, "version": VERSION,
    }}
    snapshot = item.get("confirmation_snapshot")
    if isinstance(snapshot, dict) and snapshot.get("kind", "parameter") == "parameter":
        result["confirmation_snapshot"] = {**snapshot, **{key: value for key, value in changed.items() if key in snapshot and snapshot[key] == item[key]}}
    return result


def metric_load(point):
    result = point.copy()
    raw = {}
    pending = set(point.get("unit_pending_fields") or [])
    for name, kind, other in (("height", "length", ()), ("force", "force", ("load_tolerance_upper", "load_tolerance_lower")),
                              ("deflection", "length", ())):
        key = name + "_unit"
        unit = point.get(key)
        scale = factor(kind, unit)
        if unit and scale is None and point.get(name) not in (None, ""):
            pending.add(name)
        if scale is None or unit == METRIC[kind]:
            continue
        raw[key] = unit
        result[key] = METRIC[kind]
        for field in (name, *other):
            if (n := converted(point.get(field), scale)) is not None:
                result[field] = n
                raw[field] = point[field]
        if name == "force" and isinstance(point.get("force_alternatives"), list):
            result["force_alternatives"] = [n for v in point["force_alternatives"] if (n := converted(v, scale)) is not None]
    relation = point.get("height_relation")
    if isinstance(relation, dict) and relation.get("unit") and relation["unit"] != "mm":
        scale = factor("length", relation["unit"])
        if (n := converted(relation.get("value"), scale)) is not None:
            raw["height_relation"] = {k: relation[k] for k in ("value", "unit", "evidence", "evidence_refs") if k in relation}
            result["height_relation"] = {**relation, "value": n, "unit": "mm"}
    if raw:
        result["engineering_source"] = {**raw, **(point.get("engineering_source") or {}), "version": VERSION}
        snapshot = point.get("confirmation_snapshot")
        if isinstance(snapshot, dict) and snapshot.get("kind") == "load_point":
            patch = {key: result[key] for key in raw if key in snapshot and snapshot[key] == point.get(key)}
            result["confirmation_snapshot"] = {**snapshot, **patch}
    if pending:
        result.update(unit_pending=True, unit_pending_fields=sorted(pending), need_human_review=True)
    return result


_LENGTH_UNIT = r"(?:millimeters?|millimetres?|mm|inches|inch|in|毫米|英寸|[\"″])"
_PRESSURE = r"(?:\s*\.?\s*w\.?\s*c\.?(?![A-Za-z])|\s*H2O\b)"
_DECLARE = re.compile(rf"(?:\bunits?\s*[:=]?\s*|\bdimensions?\s+(?:are\s+)?in\s+|单位\s*[:：=]?\s*)({_LENGTH_UNIT})(?![A-Za-z])", re.I)
_EXPLICIT = re.compile(rf"(?<![A-Za-z\d.]){DECIMAL}\s*({_LENGTH_UNIT})(?![A-Za-z])(?!(?:\s*/)|{_PRESSURE})", re.I)
_GEOMETRIC = re.compile(r"length|height|diameter|pitch|dimension|width|thick|\bat\b|@|高度|长度|直径|节距|宽度|[ØΦφ]", re.I)


def _length_key(unit):
    scale = factor("length", unit)
    return "in" if scale == INCH else "mm" if scale == 1 else None


_ANNOTATION_LENGTH = re.compile(
    rf"(?<![A-Za-z0-9_.])(?P<value>{DECIMAL})(?:\s*(?:±|\+\s*/\s*-|\+)\s*{DECIMAL}(?:\s*/\s*{DECIMAL})?)?"
    rf"\s*(?P<unit>{_LENGTH_UNIT}|cm|m|ft)(?![A-Za-z0-9])(?!(?:\s*/)|{_PRESSURE})", re.I,
)
_ANNOTATION_ROUGHNESS = re.compile(rf"(?<![\d.])(?P<value>{DECIMAL})\s*(?P<unit>μm|um|μin|uin|microinches?)\b", re.I)


def annotation_text_units(text, value, kind):
    """Read units attached to this nominal dimension, including its tolerance."""
    pattern = _ANNOTATION_LENGTH if kind == "length" else _ANNOTATION_ROUGHNESS
    text = unicodedata.normalize("NFKC", str(text or ""))
    return {unit_key(m["unit"]) for m in pattern.finditer(text)
            if converted(m["value"], Decimal(1)) == value and factor(kind, m["unit"]) is not None}


def page_length_units(raw_payloads):
    by_page = defaultdict(list)
    model_notes = defaultdict(list)
    for payload in raw_payloads.values():
        if not isinstance(payload, dict):
            continue
        for group in (payload, *(payload.get("raw_pages") or [])):
            if not isinstance(group, dict):
                continue
            for item in group.get("texts") or []:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    by_page[item.get("page", group.get("page", 1))].append(unicodedata.normalize("NFKC", item["text"]))
        parsed = payload.get("parsed") or {}
        if isinstance(parsed, dict):
            for field in ("technical_requirements", "load_points"):
                for item in parsed.get(field) or []:
                    if isinstance(item, dict) and isinstance(quote := item.get("original_content") or item.get("evidence"), str):
                        model_notes[item.get("page", 1)].append(quote)
    result = {}
    for page in by_page.keys() | model_notes.keys():
        lines = by_page[page]
        declared = {_length_key(m[1]) for m in _DECLARE.finditer(" ".join(lines))} - {None}
        explicit = {_length_key(m[1]) for line in lines if _GEOMETRIC.search(line) for m in _EXPLICIT.finditer(line)} - {None}
        quoted = {_length_key(m[1]) for line in model_notes[page] if _GEOMETRIC.search(line) for m in _EXPLICIT.finditer(line)} - {None}
        options = declared or explicit or quoted
        if options:
            result[page] = next(iter(options)) if len(options) == 1 else "conflict"
    return result


_LABELS = {
    "wire_diameter": r"wire\s+diameter|线径|簧丝直径",
    "free_length": r"free\s+(?:length|height)|自由(?:长度|高度)",
    "solid_height": r"(?:max(?:imum)?\s+)?solid\s+(?:length|height)|压并高度",
    "pitch": r"\bpitch\b|节距",
}
_DIAMETERS = {"outer_diameter", "inner_diameter", "mean_diameter", "diameter_role_candidate"}


def _raw_dimension(source, blocks, scope):
    from .diameter_evidence import _observed_tolerance
    field = source.get("field")
    evidence = unicodedata.normalize("NFKC", str(source.get("evidence") or ""))
    nominal = converted(source.get("value"), Decimal(1))
    if nominal is None:
        return None
    label = _LABELS.get(field)
    seeds = []
    if field in _DIAMETERS:
        claim = re.search(rf"[ØøΦφ⌀]\s*({DECIMAL})", evidence)
        if not claim:
            return None
        expected = float(claim[1])
        seeds = [(block, m) for block in blocks if (m := re.match(rf"\s*[ØøΦφ⌀]?\s*({DECIMAL})(?![\d.])", block['text']))
                 and float(m[1]) == expected and re.search(r"[ØøΦφ⌀±]|\+/\-", block['text'])]
    elif label:
        for block in blocks:
            line = block["text"]
            if m := re.search(rf"(?:{label})\s*[:：=]?\s*({DECIMAL})(?![\d.])", line, re.I):
                seeds.append((block, m))
            elif re.fullmatch(label, line.strip(), re.I) and (box := block.get("bbox")):
                height = box[3] - box[1]
                for near in blocks:
                    other = near.get("bbox")
                    if other and abs(box[0] - other[0]) <= height and 0 <= box[1] - other[3] <= height:
                        if m := re.match(rf"\s*({DECIMAL})(?![\d.])", near["text"]):
                            seeds.append((near, m))
    options = {}
    for block, match in seeds:
        text = block["text"]
        number = float(match[1])
        explicit = {_length_key(m[1]) for m in _EXPLICIT.finditer(text)} - {None}
        unit = next(iter(explicit)) if len(explicit) == 1 else scope if not explicit else None
        if unit not in {"in", "mm"}:
            continue
        canonical = converted(number, factor("length", unit))
        if field not in _DIAMETERS and number != nominal and abs(nominal - canonical) > .051 * max(1, abs(nominal)):
            continue
        repaired = re.sub(r"\+\s*[1Il]\s*-\s*(?=\.)", "±", text)
        offsets = _observed_tolerance(text, number)
        if repaired != text:
            corrected = _observed_tolerance(repaired, number)
            offsets = corrected if corrected and corrected == _observed_tolerance(evidence, number) else {}
        options[(number, unit, tuple(sorted(offsets.items())))] = (text, block.get("position"), offsets)
    if len(options) != 1:
        return None
    (number, unit, _), (text, position, offsets) = next(iter(options.items()))
    provenance = {"value": number, "unit": unit, "evidence": text, "page": source.get("page", 1), **offsets}
    if position:
        provenance["position"] = position
    return {**source, "value": number, "unit": unit, "tolerance_upper": None, "tolerance_lower": None,
            **offsets, "engineering_source": provenance}


def _restore_load_force(source):
    point = source["value"]
    nominal = converted(point.get("force"), factor("force", point.get("force_unit")))
    quote = str(source.get("evidence") or "")
    if nominal is None or not _LOAD_CONTEXT.search(quote):
        return source
    readings = set()
    for match in _SPAN.finditer(quote):
        unit = match["unit"]
        if _text_kind(unit, quote[:match.start()]) != "force":
            continue
        # A quoted single force can verify a rounded conversion without
        # guessing which endpoint of a range the model intended.
        if not re.fullmatch(DECIMAL, match["numbers"]):
            continue
        value = converted(match["numbers"], factor("force", unit))
        if value is not None and abs(nominal - value) <= max(1e-8, abs(value) * .00005):
            readings.add((float(match["numbers"]), unit))
    if len(readings) != 1:
        return source
    value, unit = next(iter(readings))
    if factor("force", unit) == factor("force", point.get("force_unit")):
        return source
    changed = {**point, "force": value, "force_unit": unit}
    scale = factor("force", point.get("force_unit")) / factor("force", unit)
    for key in ("load_tolerance_upper", "load_tolerance_lower"):
        if (offset := converted(point.get(key), scale)) is not None:
            changed[key] = offset
    return {**source, "value": changed, "reported_units": {"height_unit": point.get("height_unit"),
            **(source.get("reported_units") or {}), "force_unit": unit}}


def apply_drawing_units(candidates, raw_payloads, pages=(), *, drawing_units=None):
    """Assign source units before geometry matching. The metric pass follows it."""
    blocks = defaultdict(list)
    for page in pages:
        for item in page["texts"]:
            position = None
            if box := item.get("bbox"):
                position = {"x": box[0] / page["width"], "y": box[1] / page["height"],
                            "width": (box[2] - box[0]) / page["width"], "height": (box[3] - box[1]) / page["height"],
                            "coordinate_type": "normalized", "origin": "top_left"}
            blocks[page["page"]].append({**item, "page": page["page"], "position": position})
    units = page_length_units({**raw_payloads, "positioned_units": {"texts": [b for group in blocks.values() for b in group]}})
    if drawing_units is not None:
        drawing_units.update(units)
    output = []
    for source in candidates:
        item = source
        field = source.get("field")
        scope = units.get(source.get("page", 1))
        if field == "load_point" and isinstance(source.get("value"), dict):
            source = item = _restore_load_force(source)
        if FIELDS.get(field) == "rate" and source.get("value") not in (None, ""):
            text = str(source.get("evidence") or "")
            readings = [(m["numbers"], m["unit"]) for m in _SPAN.finditer(text) if _text_kind(m["unit"], text[:m.start()]) == "rate"]
            if len(readings) == 1:
                raw, unit = readings[0]
                raw = converted(raw, Decimal(1))
                expected = converted(raw, factor("rate", unit))
                nominal = converted(source.get("value"), factor("rate", source.get("unit")))
                if raw is not None and (expected is not None and nominal is not None and abs(nominal - expected) <= abs(expected) * .01
                                        or not source.get("unit") and raw == converted(source["value"], Decimal(1))):
                    item = {**source, "value": raw, "unit": unit}
        if (FIELDS.get(field) == "length" or field in _DIAMETERS) and source.get("value") not in (None, ""):
            evidence = str(source.get("evidence") or "")
            explicit = {_length_key(m[1]) for m in _EXPLICIT.finditer(evidence)} - {None}
            unit = next(iter(explicit)) if len(explicit) == 1 else scope if not explicit else "conflict"
            raw = _raw_dimension(source, blocks[source.get("page", 1)], unit)
            if raw:
                item = raw
            elif unit == "conflict":
                item = {**source, "unit_pending": True, "need_human_review": True}
            elif unit and not source.get("unit"):
                item = {**source, "unit": unit}
            elif unit and unit != _length_key(source.get("unit")) and (unit == "in" or explicit):
                nominal = converted(source.get("value"), Decimal(1))
                literals = [float(m[0]) for m in re.finditer(rf"(?<![\w.]){DECIMAL}(?![\w.])", evidence)]
                if literals and literals[0] == nominal and not re.search(r"换算|converted|\bto\s+mm", evidence, re.I):
                    item = {**source, "unit": unit}
                elif not (literals and converted(literals[0], factor("length", unit)) ==
                          converted(nominal, factor("length", source.get("unit")))):
                    item = {**source, "unit_pending": True, "need_human_review": True}
        if field == "load_point" and isinstance(source.get("value"), dict) and scope:
            value = source["value"]
            height_relation = value.get("height_relation") or {}
            reported = source.get("reported_units") or value
            if not reported.get("height_unit") and scope in {"in", "mm"}:
                item = {**source, "reported_units": {**reported, "height_unit": scope}, "value": {**value, "height_unit": scope}}
            if height_relation.get("value") is not None and not height_relation.get("unit") and scope in {"in", "mm"}:
                item = {**item, "value": {**item["value"], "height_relation": {**height_relation, "unit": scope}}}
            if scope == "conflict" and not reported.get("height_unit") and value.get("height") is not None:
                item = {**item, "value": {**item["value"], "unit_pending": True, "unit_pending_fields": ["height"]}}
        output.append(item)
    return output


_UNIT_PATTERN = (r"(?:lbf|lbs?|kgf|kg|磅力|英磅|磅|公斤力|公斤)\s*(?:/|\bper\b|每)\s*(?:inches|inch|in\.?|mm|英寸|毫米)|"
                 r"(?:N|kN)\s*/\s*mm(?:\^?2|²)?|lbf\s*[·⋅]\s*in|N\s*[·⋅]\s*m{1,2}|"
                 r"(?:g|kg)\s*/\s*(?:cm|m)(?:\^?3|³)|lb\s*/\s*in(?:\^?3|³)|"
                 r"microinches?|[μµu](?:in|m)|ksi|psi|GPa|MPa|kPa|kN|kgf|lbf|lbs?|kg|N|英磅|磅力|磅|公斤力|公斤|牛顿|"
                 + _LENGTH_UNIT)
_SPAN = re.compile(rf"(?<![A-Za-z0-9_.])(?P<numbers>{DECIMAL}(?:(?:\s*(?:±|\+\s*/\s*-|/|\bto\b|至|～|–|-)\s*|\s*\+(?=\s*\d|\s*\.)){DECIMAL}){{0,2}})"
                   rf"(?P<gap>\s*)(?P<unit>{_UNIT_PATTERN})(?![A-Za-z0-9])(?!(?:\s*/\s*[A-Za-z])|{_PRESSURE})", re.I)
_LOAD_CONTEXT = re.compile(r"\b(?:load|force|compression\s+rate|spring\s+rate|stiffness)\b|负荷|荷重|载荷|负载|力值|刚度|弹力", re.I)
_MASS_CONTEXT = re.compile(r"\b(?:mass|weight)\b|质量|重量", re.I)
_IMPLICIT = re.compile(rf"(?P<prefix>(?:minimum\s+(?:color\s+)?stripe\s+width|max(?:imum)?\s+solid\s+length|(?:free|working|installed)\s+(?:height|length)|自由(?:长度|高度)|工作(?:长度|高度)|压并(?:长度|高度)|色带宽度)\s*[:：=]?\s*)(?P<n>{DECIMAL})(?![\d.]|\s*[A-Za-zμµ])", re.I)
_RING = re.compile(rf"(?P<n>{DECIMAL})(?P<tail>\s+diameter\s+ring\s+gauge\b|\s*(?:直径)?的环规)", re.I)
_MIN_MAX = re.compile(rf"(?P<a>{DECIMAL})\s*(?P<u>{_UNIT_PATTERN})\s*(?:min\.?\s*(?:to|[-–])\s*)"
                      rf"(?P<b>{DECIMAL})(?:\s*(?P<v>{_UNIT_PATTERN}))?\s*max\b", re.I)


def _text_kind(unit, context):
    key = unit_key(unit)
    if key in {"lb", "lbs", "kg"}:
        if _LOAD_CONTEXT.search(context) and not _MASS_CONTEXT.search(context):
            return "force"
        if _MASS_CONTEXT.search(context) and not _LOAD_CONTEXT.search(context):
            return "mass"
        return None
    return quantity(None, unit)


def metric_text(content, implicit_unit=None):
    if not isinstance(content, str) or not content:
        return content, False
    pending = False

    def range_endpoints(match):
        unit = match["u"]
        kind = _text_kind(unit, content[:match.start()])
        if kind is None:
            return match[0]
        end_factor = factor(kind, match["v"] or unit)
        if end_factor is None:
            return match[0]
        low = _print_number(converted(match["a"], factor(kind, unit)))
        high = _print_number(converted(match["b"], end_factor))
        return f"{low}–{high} {METRIC[kind]}"

    content = _MIN_MAX.sub(range_endpoints, content)

    def replace(match):
        nonlocal pending
        unit = match["unit"]
        if unit.casefold() == "in" and re.match(r"\s+(?:the|a|an|this|each)\b", content[match.end():], re.I):
            return match[0]
        start = max(content.rfind("\n", 0, match.start()), content.rfind("；", 0, match.start()), content.rfind(";", 0, match.start())) + 1
        kind = _text_kind(unit, content[start:match.start()])
        if kind is None:
            pending |= unit_key(unit) in {"lb", "lbs", "kg"}
            return match[0]
        scale = factor(kind, unit)
        if scale == 1 and unit == METRIC[kind]:
            return match[0]
        # Signs in a tolerance separator belong to the separator itself.
        numbers = re.sub(r"(?<!\d)[+\-−]?(?:\d+(?:\.\d+)?|\.\d+)",
                         lambda n: ("+" if n[0].startswith("+") else "") + _print_number(converted(n[0], scale)), match["numbers"])
        return numbers + " " + METRIC[kind]

    result = _SPAN.sub(replace, content)
    if result != content:
        result = re.sub(rf"({DECIMAL}\s+(?:mm|N/mm|N|MPa|kg|μm))\s*[（(]\s*\1\s*[)）]", r"\1", result)
    if implicit_unit in {"in", "mm"}:
        scale = factor("length", implicit_unit)
        result = _IMPLICIT.sub(lambda m: m["prefix"] + _print_number(converted(m["n"], scale)) + " mm", result)
        result = _RING.sub(lambda m: _print_number(converted(m["n"], scale)) + " mm" + m["tail"], result)
    return result, pending


def _print_number(value):
    return f"{value:.13g}" if value is not None else ""


def metric_requirements(review, page_units=None):
    page_units = page_units or review.get("drawing_length_units") or {}
    for item in review.get("technical_requirements") or []:
        content = item.get("content")
        unit = page_units.get(str(item.get("page", 1)), page_units.get(item.get("page", 1)))
        # An edited text must carry its own unit. Drawing-wide inheritance is
        # for original engineering statements, not new reviewer prose.
        sources = item.get("source") or []
        if "human" in str(sources).casefold() or item.get("human_modified"):
            unit = None
        text, pending = metric_text(content, unit)
        if text != content:
            item.setdefault("engineering_source_text", content)
            item["content"] = text
            snapshot = item.get("translation_output_snapshot")
            if isinstance(snapshot, dict) and snapshot.get("content") == content:
                item["translation_output_snapshot"] = {**snapshot, "content": text}
            confirmation = item.get("confirmation_snapshot")
            if isinstance(confirmation, dict) and confirmation.get("content") == content:
                item["confirmation_snapshot"] = {**confirmation, "content": text}
        if pending:
            item.update(unit_pending=True, need_human_review=True)
        else:
            item.pop("unit_pending", None)


def metric_review(review, *, requirements=True):
    parameters = review.get("spring_parameters") or {}
    changed = []
    for field, item in list(parameters.items()):
        if isinstance(item, dict):
            value = metric_item(item, field)
        elif field == "load_points" and isinstance(item, list):
            value = [metric_load(point) for point in item]
        else:
            continue
        if value != item:
            parameters[field] = value
            changed.append(field)
            confirmation = (review.get("manual_confirmations") or {}).get(field)
            if isinstance(confirmation, dict) and isinstance(item, dict) and confirmation.get("value") == item.get("value"):
                confirmation["value"] = value.get("value")
    for section in ("derived_parameters",):
        for field, item in list((review.get(section) or {}).items()):
            if isinstance(item, dict):
                review[section][field] = metric_item(item, field)
    if isinstance(review.get("diameter_role_candidates"), list):
        review["diameter_role_candidates"] = [item if item.get("selected_field") or item.get("ignored") else metric_item(item, "outer_diameter")
                                             for item in review["diameter_role_candidates"]]
    if requirements:
        metric_requirements(review)
    return changed
