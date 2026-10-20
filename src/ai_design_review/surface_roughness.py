from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .standardizers.calculation_state import human_override, parameter_current
from .technical_requirements import technical_requirement_body, technical_requirement_output_content


SURFACE_ROUGHNESS_FIELD = "surface_roughness_ra"
SURFACE_ROUGHNESS_UNIT = "μm"
SURFACE_ROUGHNESS_LABEL = "表面粗糙度 Ra（μm）"
ROUGHNESS_VERIFICATION_VERSION = "roughness_original_evidence/v3"
INDEPENDENT_ROUGHNESS_SOURCES = {"pdf_text", "ocr", "local_ocr"}
END_SURFACES = {"两端面", "端面", "左端面", "右端面"}

_SURFACE_LOCATION = r"两端面?|[左右]端面|端面|外圆(?:表面)?|内圆(?:表面)?|弹簧表面|全表面|整体"
_STANDALONE_ROUGHNESS = re.compile(
    rf"(?:(?P<location>{_SURFACE_LOCATION})\s*)?"
    r"(?:(?:表面)?粗糙度(?:要求)?\s*[:=]?\s*(?:Ra\s*[:=]?\s*)?|Ra\s*[:=]?\s*)"
    r"(?P<value>\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*(?P<unit>μm|um)?", re.IGNORECASE
)


def _roughness_unit(value: Any) -> str:
    return str(value or "μm").strip().lower().replace("µ", "μ").replace("um", "μm")


def _roughness_location(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    return {"两端": "两端面", "外圆表面": "外圆", "内圆表面": "内圆"}.get(text, text)


def standalone_surface_roughness(item: dict[str, Any]) -> dict[str, Any] | None:
    """Parse only an entire Ra sentence; inequalities and process clauses survive."""
    body, _ = technical_requirement_body(technical_requirement_output_content(item))
    suffix = re.search(r"\(作用范围:\s*([^()]+)\)$", body)
    locations = [item.get("application_scope"), suffix[1] if suffix else None]
    if suffix:
        body = body[:suffix.start()].strip()
    match = _STANDALONE_ROUGHNESS.fullmatch(body)
    if match:
        value = positive_surface_roughness(match["value"])
        unit = _roughness_unit(match["unit"])
        locations.append(match["location"])
    elif str(item.get("type") or "").lower() in {"surface_roughness", "roughness", "surface_finish", "表面粗糙度"}:
        value, unit = positive_surface_roughness(body), "μm"
    else:
        return None
    if value is None or unit != "μm":
        return None
    scopes = {_roughness_location(location) for location in locations if str(location or "").strip()}
    if len(scopes) > 1:
        return None
    return {"value": value, "unit": unit, "location": next(iter(scopes), "")}


def confirmed_surface_roughness(review: dict[str, Any]) -> dict[str, Any] | None:
    parameters = review.get("spring_parameters") or {}
    item = parameters.get(SURFACE_ROUGHNESS_FIELD)
    if not isinstance(item, dict) or item.get("need_human_review") is not False:
        return None
    if item.get("roughness_conflict") or item.get("formula_recommendation_stale") or not parameter_current(parameters, SURFACE_ROUGHNESS_FIELD):
        return None
    value = positive_surface_roughness(item.get("value"))
    if value is None or _roughness_unit(item.get("unit")) != "μm":
        return None
    return {"value": value, "unit": "μm", "location": _roughness_location(item.get("surface_location"))}


def surface_roughness_matches(item: dict[str, Any], roughness: dict[str, Any] | None) -> bool:
    parsed = standalone_surface_roughness(item)
    return roughness is not None and parsed == roughness

_ROUGHNESS_PATTERNS = (
    re.compile(r"(?<![A-Za-z])Ra\s*[:：=]?\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(r"(?:表面)?粗糙度\s*(?:Ra\s*)?[:：=]?\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(r"[▽√]\s*(\d+(?:[.,]\d+)?)"),
)
_LOCATION_PATTERNS = (
    (re.compile(r"两端(?:面)?"), "两端面"),
    (re.compile(r"(?:左|右)端面"), None),
    (re.compile(r"端面"), "端面"),
    (re.compile(r"外圆(?:表面)?"), "外圆"),
    (re.compile(r"内圆(?:表面)?"), "内圆"),
    (re.compile(r"全表面|整体|弹簧表面"), None),
)

# These qualifiers apply to the Ra clause, not unrelated statements such as
# "Ra12.5不作为尺寸提取". Keep the display fallback in JS in sync via fixtures.
_ROUGHNESS_SPECULATION = re.compile(r"可能|也许|大概|猜测|推测|怀疑|似乎|不确定|无法确认|看不清|假设|例如|比如|举例|推荐|建议|默认|常规|参考|possibly|perhaps|example|recommend|default", re.I)
_ROUGHNESS_NEGATION = re.compile(r"(?:未|没有|无|并无|不含|不存在|未见|不要求|无需|不需要|不涉及).{0,12}(?:粗糙度|Ra|标注)|(?:不是|并非|不属于|不作为|不应作为).{0,8}(?:粗糙度|Ra)|(?:粗糙度|Ra).{0,8}(?:未标注|没有标注|不要求|未出现|没有出现|不适用)|not\s+(?:roughness|Ra)|no\s+(?:roughness|Ra)", re.I)
_ROUGHNESS_DISCUSSION = re.compile(r"need_human_review|surface_roughness_ra|我们|我再|再看|再确认|无法辨认|无法确定", re.I)
_CLAUSE_BOUNDARY = re.compile(r"[。；;\n|，]|(?<!\d),|,(?!\d)|而是|实际为")


def roughness_evidence_assessment(value: Any, evidence: Any, *, structured: bool = False) -> tuple[str, str]:
    """Text prefilter only. A lexical 'direct' result is not original evidence.

    Only verify_roughness_candidates may mark a recognition candidate direct.
    """
    number, text = positive_surface_roughness(value), str(evidence or "").strip()
    statuses = []
    for pattern in _ROUGHNESS_PATTERNS:
        for match in pattern.finditer(text):
            if positive_surface_roughness(match[1]) != number:
                continue
            boundaries = list(_CLAUSE_BOUNDARY.finditer(text))
            start = max((edge.end() for edge in boundaries if edge.end() <= match.start()), default=0)
            end = min((edge.start() for edge in boundaries if edge.start() >= match.end()), default=len(text))
            clause = text[start:end]
            if re.match(r"\s*(?:mm|nm|毫米|纳米)\b", text[match.end():], re.I):
                continue
            if _ROUGHNESS_NEGATION.search(clause):
                statuses.append(("excluded", "该数值所在语句否定了粗糙度标注，不作为原图候选。"))
            elif _ROUGHNESS_SPECULATION.search(clause):
                statuses.append(("excluded", "该数值来自推测、举例或参考说明，不作为原图候选。"))
            elif len(clause) > 160 or _ROUGHNESS_DISCUSSION.search(text) or len(text) > 240:
                statuses.append(("unverified", "依据包含长篇解释，尚不能证明是原图明确标注。"))
            else:
                statuses.append(("direct", "包含与候选一致的明确粗糙度文字或符号。"))
    if any(status == "direct" for status, _ in statuses):
        return next(entry for entry in statuses if entry[0] == "direct")
    if any(status == "unverified" for status, _ in statuses):
        return next(entry for entry in statuses if entry[0] == "unverified")
    if statuses:
        return statuses[0]
    if structured and number is not None and positive_surface_roughness(text) == number:
        return "direct", "粗糙度结构化字段保留了对应原图数值。"
    return "unverified", "缺少与候选一致的原图粗糙度文字或符号，请核对。"


def surface_roughness_mentions(text: Any) -> list[dict[str, Any]]:
    """Extract explicit Ra values without treating an ordinary dimension as roughness."""

    content = str(text or "").strip()
    if not content:
        return []
    mentions: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for pattern in _ROUGHNESS_PATTERNS:
        for match in pattern.finditer(content):
            value = positive_surface_roughness(match.group(1))
            if value is None:
                continue
            context = content[max(0, match.start() - 36) : min(len(content), match.end() + 36)]
            location = _surface_roughness_location_near(content, match.start(), match.end())
            key = (value, location or "")
            if key in seen:
                continue
            seen.add(key)
            mentions.append(
                {
                    "value": value,
                    "location": location,
                    "evidence": context.strip() or match.group(0),
                }
            )
    return mentions


def surface_roughness_location(text: Any) -> str | None:
    content = str(text or "")
    for pattern, normalized in _LOCATION_PATTERNS:
        match = pattern.search(content)
        if not match:
            continue
        if normalized is not None:
            return normalized
        return match.group(0)
    return None


def _surface_roughness_location_near(text: str, start: int, end: int) -> str | None:
    boundaries = list(_CLAUSE_BOUNDARY.finditer(text))
    clause_start = max((edge.end() for edge in boundaries if edge.end() <= start), default=0)
    clause_end = min((edge.start() for edge in boundaries if edge.start() >= end), default=len(text))
    before = text[max(clause_start, start - 36) : start]
    matches: list[tuple[int, str]] = []
    for pattern, normalized in _LOCATION_PATTERNS:
        for match in pattern.finditer(before):
            matches.append((match.end(), normalized or match.group(0)))
    if matches:
        return max(matches, key=lambda item: item[0])[1]
    return surface_roughness_location(text[end : min(clause_end, end + 36)])


def positive_surface_roughness(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    text = str(value).strip().replace(",", ".")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return float(number)


def _valid_evidence_box(box: Any) -> bool:
    if not isinstance(box, dict):
        return False
    try:
        x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
        return all(math.isfinite(v) for v in (x, y, w, h)) and min(x, y) >= 0 and min(w, h) > 0 and max(x + w, y + h) <= 1.01
    except (KeyError, ValueError, TypeError):
        return False


def independent_roughness_evidence(value: Any, blocks: list[dict[str, Any]], page: Any = None) -> list[dict[str, Any]]:
    """Match within a located PDF/OCR line, never against a model's explanation.

    Filled triangles and single slash strokes are deliberately not roughness
    symbols here. Ambiguous symbol-only readings remain unverified.
    """
    number = positive_surface_roughness(value)
    refs = []
    for block in blocks:
        text = str(block.get("text") or "")
        box = block.get("position")
        if (number is None or not isinstance(block.get("source"), str) or block["source"] not in INDEPENDENT_ROUGHNESS_SOURCES
                or not _valid_evidence_box(box) or block.get("numeric_join_unsafe")
                or not isinstance(block.get("page"), int) or block["page"] < 1
                or page is not None and block["page"] != page):
            continue
        # A complete label and number must occur in this same text run. Keep
        # signs/decimals intact; do not join spaced digits or nearby cells.
        matches = [m for pattern in _ROUGHNESS_PATTERNS for m in pattern.finditer(text)
                   if positive_surface_roughness(m[1]) == number
                   and not re.match(r"[\d.,]|\s+\d", text[m.end():])]
        for match in matches:
            box = block["position"]
            edges = list(_CLAUSE_BOUNDARY.finditer(text))
            start = max((e.end() for e in edges if e.end() <= match.start()), default=0)
            end = min((e.start() for e in edges if e.start() >= match.end()), default=len(text))
            clause = text[start:end]
            if re.match(r"\s*(?:mm|nm|毫米|纳米)(?![A-Za-z])", text[match.end():], re.I):
                continue
            if (_ROUGHNESS_NEGATION.search(clause) or _ROUGHNESS_SPECULATION.search(clause)
                    or not re.search(r"Ra|粗糙度", match[0], re.I) and re.search(r"加工基准|基准面|datum", clause, re.I)):
                continue
            # PDF lines may span several table cells. Validate the actual word
            # spacing rather than treating the entire line as a single label.
            tokens = block.get("tokens") or []
            if tokens:
                offset, selected = 0, []
                for token in tokens:
                    token_text = str(token.get("text") or "")
                    if offset < match.end() and offset + len(token_text) > match.start():
                        selected.append(token)
                    offset += len(token_text) + 1
                if selected:
                    boxes = [t.get("position") for t in selected]
                    if not all(_valid_evidence_box(b) for b in boxes):
                        continue
                    # Horizontal or vertical text, without jumping a column.
                    angle = int(block.get("reading_angle") or 0) % 180
                    vertical = angle == 90 or box["height"] > box["width"] * 1.5
                    axis, extent = ("y", "height") if vertical else ("x", "width")
                    ordered = sorted(boxes, key=lambda b: b[axis])
                    cross = "width" if vertical else "height"
                    if any(b[axis] - a[axis] - a[extent] > max(a[cross], b[cross]) * 1.5 for a, b in zip(ordered, ordered[1:])):
                        continue
                    box = {"x": min(b["x"] for b in boxes), "y": min(b["y"] for b in boxes),
                           "width": max(b["x"] + b["width"] for b in boxes) - min(b["x"] for b in boxes),
                           "height": max(b["y"] + b["height"] for b in boxes) - min(b["y"] for b in boxes)}
            ref = {"source": block["source"], "page": block["page"], "position": deepcopy(box),
                   "text": clause.strip(), "location": _surface_roughness_location_near(text, match.start(), match.end())}
            if ref not in refs:
                refs.append(ref)
    return refs


def verified_roughness_candidate(item: dict[str, Any]) -> bool:
    refs = item.get("independent_evidence") or []
    return (item.get("evidence_status") == "direct"
            and item.get("verification_version") == ROUGHNESS_VERIFICATION_VERSION
            and bool(item.get("source_document_id")) and isinstance(refs, list) and bool(refs)
            and all(isinstance(r, dict) and (independent_roughness_evidence(item.get("value"), [r], r.get("page"))
                    or item.get("verification_method") in {"model_position", "historical_anchor", "unique_number", "end_pair"}
                    and _numeric_roughness_refs(item.get("value"), [r], r.get("page"))) for r in refs))


def roughness_value_verified(item: dict[str, Any]) -> bool:
    """A verified scalar need not have an assigned drawing location."""
    if verified_roughness_candidate(item):
        return True
    refs = item.get("numeric_evidence") or []
    return (item.get("value_verified") is True and item.get("verification_version") == ROUGHNESS_VERIFICATION_VERSION
            and bool(item.get("source_document_id")) and bool(refs) and isinstance(refs, list)
            and all(isinstance(r, dict) and (independent_roughness_evidence(item.get("value"), [r], r.get("page"))
                    or _numeric_roughness_refs(item.get("value"), [r], r.get("page"))) for r in refs))


def _declared_scopes(item):
    return {_roughness_location(s) for s in [item.get("surface_location"), item.get("location"), *item.get("location_candidates", []),
            *[r.get("surface_location") or r.get("location") for r in item.get("evidence_records", [])]] if s}


def _model_roughness_claim(item):
    evidence = str(item.get("evidence") or "")
    claim = item.get("roughness_model_claim")
    if claim is None:
        claim = "qwen" in str(item.get("source") or "").lower() and roughness_evidence_assessment(item.get("value"), evidence)[0] == "direct"
    return bool(claim) and not (_ROUGHNESS_SPECULATION.search(evidence) or _ROUGHNESS_NEGATION.search(evidence))


def _both_ends_claim(item, claims):
    scopes = set()
    for claim in [item, *claims]:
        if (positive_surface_roughness(claim.get("value")) == positive_surface_roughness(item.get("value"))
                and claim.get("page", 1) == item.get("page", 1) and _model_roughness_claim(claim)):
            scopes.update(_declared_scopes(claim))
    return bool(scopes <= END_SURFACES and ("两端面" in scopes or {"左端面", "右端面"} <= scopes))


def _end_pair_refs(refs, page, view_context):
    """Match two end numbers within one uniquely identified drawing region."""
    choices = []
    for view in view_context:
        if view.get("page") != page:
            continue
        width, height = view["width"], view["height"]
        for x0, y0, x1, y1 in view.get("regions", []):
            w, h = (x1 - x0) * width, (y1 - y0) * height
            if min(w, h) <= 0 or max(w, h) / min(w, h) < 1.3:
                continue
            inside = [r for r in refs if x0 <= r["position"]["x"] + r["position"]["width"] / 2 <= x1
                      and y0 <= r["position"]["y"] + r["position"]["height"] / 2 <= y1]
            if len(inside) != 2:
                continue
            axis, extent, start, end = ("x", "width", x0, x1) if w >= h else ("y", "height", y0, y1)
            pair = sorted(inside, key=lambda r: r["position"][axis] + r["position"][extent] / 2)
            t = [(r["position"][axis] + r["position"][extent] / 2 - start) / (end - start) for r in pair]
            if t[0] <= .35 and t[1] >= .65:
                choices.append(pair)
    return choices[0] if len(choices) == 1 else []


def _numeric_roughness_refs(value, blocks, page):
    """Complete numeric runs only. No digit joining or diameter/tolerance stripping."""
    from .drawing_annotations import _same_text_box
    refs = []
    for block in blocks:
        if (block.get("source") not in INDEPENDENT_ROUGHNESS_SOURCES or block.get("page") != page
                or not _valid_evidence_box(block.get("position")) or block.get("numeric_join_unsafe")):
            continue
        # A PDF word can provide the numeric box without borrowing another cell.
        runs = [block, *[{**block, **token, "tokens": []} for token in block.get("tokens", [])]]
        for run in runs:
            match = re.fullmatch(r"\s*[\\/]?\s*(\d+(?:[.,]\d+)?)\s*(?:μm|µm|um)?\s*", str(run.get("text") or ""), re.I)
            if not match or positive_surface_roughness(match[1]) != positive_surface_roughness(value):
                continue
            ref = {k: deepcopy(run[k]) for k in ("source", "page", "position", "text")}
            if _valid_evidence_box(ref["position"]) and not any(_same_text_box(ref["position"], r["position"]) for r in refs):
                refs.append(ref)
    return refs


def _near_digit(hint, ref):
    if not _valid_evidence_box(hint):
        return False
    box = ref["position"]
    pad = min(box["width"], box["height"])
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    return hint["x"] - pad <= x <= hint["x"] + hint["width"] + pad and hint["y"] - pad <= y <= hint["y"] + hint["height"] + pad


def roughness_request_key(item):
    import hashlib
    import json
    key = [item.get("value"), item.get("page", 1), item.get("recognition_position", item.get("position"))]
    return ROUGHNESS_VERIFICATION_VERSION + ":" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def grounded_roughness_evidence(item, blocks, *, dimension_candidates=(), historical_locations=(), claims=(), view_context=()):
    """Shared original-number decision for fusion, restoration and annotations."""
    from .drawing_annotations import FIELDS, _identity, _row_label, _same_text_box
    value, page = item.get("value"), item.get("page", 1)
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        return [], "unverified", "粗糙度候选页码不明确，请核对原图页。"
    if _roughness_unit(item.get("unit")) != "μm":
        return [], "unverified", "粗糙度单位待核对。"
    explicit = independent_roughness_evidence(value, blocks, page)
    distinct = []
    for ref in explicit:
        if not any(_same_text_box(ref["position"], r["position"]) and ref.get("location") == r.get("location") for r in distinct):
            distinct.append(ref)
    explicit = distinct
    hint = item.get("recognition_position", item.get("position"))
    if hint and hint.get("coordinate_type") not in (None, "normalized"):
        hint = None
    if explicit:
        if hint:
            matched = [ref for ref in explicit if _near_digit(hint, ref)]
            if len(matched) != 1:
                return explicit, "needs_location", "对应位置内存在多个同值标注，位置待核对。"
            explicit = matched
        if explicit:
            return explicit, "explicit_label", "原图文字已核实粗糙度数值和位置。"
    if not _model_roughness_claim(item):
        return [], "unverified", "尚无明确粗糙度识别候选，不能借用普通数字。"
    refs = _numeric_roughness_refs(value, blocks, page)
    def dimension_role(ref):
        fields = [f for f in FIELDS if f not in {SURFACE_ROUGHNESS_FIELD, "material", "standard_no", "handedness", "end_type", "end_grinding"}]
        # A same-row label, diameter, explicit tolerance, or another grounded
        # parameter at this glyph is incompatible with a numeric-only Ra claim.
        nearby = [b for b in blocks if b.get("page") == page and _valid_evidence_box(b.get("position")) and _same_text_box(ref["position"], b["position"])]
        if any(re.search(r"[φΦϕøØ⌀±]|公差|tolerance", str(b.get("text") or ""), re.I) for b in nearby):
            return True
        if any(_identity(f, b.get("text", "")) or _row_label(f, b, blocks) for f in fields for b in nearby):
            return True
        return any(c.get("field") != SURFACE_ROUGHNESS_FIELD and c.get("page", 1) == page
                   and positive_surface_roughness(c.get("value")) == positive_surface_roughness(value)
                   and _valid_evidence_box(c.get("position")) and _same_text_box(c["position"], ref["position"])
                   for c in dimension_candidates)
    refs = [ref for ref in refs if not dimension_role(ref)]
    if hint:
        matched = [ref for ref in refs if _near_digit(hint, ref)]
        if refs and not matched:
            return refs, "needs_location", "数值已核实，模型数字框与原图位置不一致，位置待核对。"
        refs = matched
        method = "model_position"
    else:
        anchors = [h for h in historical_locations if h.get("page") == page and positive_surface_roughness(h.get("evidence_value", h.get("original_value"))) == positive_surface_roughness(value)]
        anchored = []
        for h in anchors:
            # Only bbox/anchor from original evidence, never bubble coordinates.
            bbox = h.get("bbox")
            if not _valid_evidence_box(bbox) and isinstance(h.get("anchor"), dict):
                a = h["anchor"]
                bbox = {"x": a.get("x", -1), "y": a.get("y", -1), "width": .000001, "height": .000001}
            local = [r for r in refs if _near_digit(bbox, r)]
            if len(local) == 1 and local[0] not in anchored:
                anchored.append(local[0])
        if anchored:
            return anchored, "historical_anchor", "已复核历史原图锚点、页码及同值数字。"
        if _both_ends_claim(item, claims):
            pair = _end_pair_refs(refs, page, view_context)
            if pair:
                return pair, "end_pair", "已核实同一弹簧视图区两端的同值数字。"
        method = "unique_number"
    if len(refs) == 1:
        return refs, method, "模型明确识别为粗糙度，原图同页同位数字已核实。"
    if refs:
        return refs, "needs_location", "数值已核实，原图存在多个同值数字，位置待核对。"
    return [], "unverified", "对应原图位置未读到同值数字；模型说明不能代替原图证据。"


def verify_roughness_candidates(items: list[dict[str, Any]], blocks: list[dict[str, Any]], document_id: str,
                                *, failure_reason: str = "", dimension_candidates=(), historical_locations=(), view_context=()) -> list[dict[str, Any]]:
    results = []
    for original in items:
        item = deepcopy(original)
        refs, method, reason = grounded_roughness_evidence(item, blocks, dimension_candidates=dimension_candidates, historical_locations=historical_locations, claims=items, view_context=view_context)
        item.setdefault("recognition_position", deepcopy(item.get("position")))
        item.setdefault("evidence_records", [{k: deepcopy(original.get(k)) for k in ("evidence", "source", "page", "position", "surface_location", "location")}])
        item.update(verification_version=ROUGHNESS_VERIFICATION_VERSION, source_document_id=document_id,
                    evidence_status="unverified", independent_evidence=[], numeric_evidence=deepcopy(refs), value_verified=bool(refs),
                    expected_locations=2 if _both_ends_claim(item, items) else 1,
                    verification_method=method, recognition_state="failed" if failure_reason and not refs else "needs_location" if refs else "unverified",
                    evidence_reason=failure_reason if failure_reason and not refs else reason)
        if method == "needs_location":
            results.append(item)
            continue
        matched = False
        for ref in refs:
            result = deepcopy(item)
            result.update(evidence_status="direct", independent_evidence=[ref],
                          recognition_state="located", evidence_reason=reason,
                          page=ref["page"], position={**ref["position"], "coordinate_type": "normalized", "origin": "top_left"},
                          surface_location="两端面" if method == "end_pair" else ref.get("location") or item.get("surface_location") or item.get("location"),
                          location="两端面" if method == "end_pair" else ref.get("location") or item.get("surface_location") or item.get("location"))
            result.pop("location_conflict", None)
            result.pop("location_candidates", None)
            results.append(result)
            matched = True
        if not matched:
            results.append(item)
    return results


def merge_roughness_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One physical annotation per candidate, keeping all contributing records."""
    result = []
    for item in items:
        value = positive_surface_roughness(item.get("value"))
        if value is None:
            continue
        candidate = deepcopy(item)
        candidate.update(value=value, unit=_roughness_unit(item.get("unit")), location=None if item.get("location_conflict") else item.get("location") or item.get("surface_location"))
        direct = verified_roughness_candidate(candidate)
        candidate["evidence_status"] = "direct" if direct else "unverified"
        candidate["value_verified"] = roughness_value_verified(candidate)
        if not direct:
            candidate["independent_evidence"] = []
            candidate["evidence_reason"] = (item.get("evidence_reason") if item.get("evidence_status") == "unverified" else None) or "尚未通过原图独立证据核验。"
        records = deepcopy(item.get("evidence_records") or [{k: item.get(k) for k in ("evidence", "source", "page", "position", "surface_location", "location")}])
        candidate["evidence_records"] = records
        def same(prior):
            if prior["value"] != value or prior["unit"] != candidate["unit"] or prior["evidence_status"] != candidate["evidence_status"]:
                return False
            if prior.get("value_verified") != candidate.get("value_verified"):
                return False
            if direct:
                if prior.get("location") and candidate.get("location") and prior["location"] != candidate["location"]:
                    return False
                from .drawing_annotations import _same_text_box
                return any(a["page"] == b["page"] and _same_text_box(a["position"], b["position"])
                           for a in prior["independent_evidence"] for b in candidate["independent_evidence"])
            return (prior.get("page", 1) == item.get("page", 1)
                    and str(prior.get("evidence") or "").strip() == str(item.get("evidence") or "").strip()
                    and prior.get("position") == item.get("position"))
        prior = next((p for p in result if same(p)), None)
        if prior is None:
            result.append(candidate)
            continue
        for record in records:
            if record not in prior["evidence_records"]:
                prior["evidence_records"].append(record)
        scopes = set(filter(None, [prior.get("location"), candidate.get("location"), *prior.get("location_candidates", [])]))
        if scopes <= END_SURFACES and ("两端面" in scopes or {"左端面", "右端面"} <= scopes):
            prior.update(location="两端面", surface_location="两端面")
            prior.pop("location_conflict", None)
            prior.pop("location_candidates", None)
        elif len(scopes) > 1:
            prior.update(location=None, surface_location=None, location_conflict=True, location_candidates=sorted(scopes))
        elif scopes:
            prior["location"] = next(iter(scopes))
        for ref in candidate.get("independent_evidence", []):
            if ref not in prior["independent_evidence"]:
                prior["independent_evidence"].append(ref)
        for ref in candidate.get("numeric_evidence", []):
            if ref not in prior.setdefault("numeric_evidence", []):
                prior["numeric_evidence"].append(ref)
        prior["expected_locations"] = max(prior.get("expected_locations", 1), candidate.get("expected_locations", 1))
    return result


def roughness_selection(candidates):
    """Select verified values; assigned locations are a separate requirement."""
    from .drawing_annotations import _same_text_box
    accepted = [c for c in candidates if roughness_value_verified(c)]
    direct = [c for c in accepted if verified_roughness_candidate(c)]
    scopes = {_roughness_location(c.get("location")) for c in accepted} - {""}
    # End annotations share one scalar; explicit other surfaces remain separate.
    conflict = len({c["value"] for c in accepted}) > 1 or len(scopes) > 1 and not scopes <= END_SURFACES
    located_refs = [(c["value"], r) for c in direct for r in c["independent_evidence"]]
    def covered(value, ref):
        return any(v == value and ref["page"] == r["page"] and _same_text_box(ref["position"], r["position"]) for v, r in located_refs)
    pending = any(not covered(c["value"], r) for c in accepted if not verified_roughness_candidate(c) for r in c.get("numeric_evidence", []))
    for c in accepted:
        refs = []
        for value, r in located_refs:
            if value == c["value"] and r["page"] == c.get("page", 1) and not any(_same_text_box(r["position"], old["position"]) for old in refs):
                refs.append(r)
        pending |= len(refs) < c.get("expected_locations", 1)
    state = "needs_location" if accepted and pending else "located" if direct else "failed" if any(c.get("recognition_state") == "failed" for c in candidates) else "unverified" if candidates else "missing"
    return accepted, bool(conflict), state


def selected_roughness_location(candidates):
    scopes = {_roughness_location(c.get("location")) for c in candidates} - {""}
    if scopes <= END_SURFACES and ("两端面" in scopes or {"左端面", "右端面"} <= scopes):
        return "两端面"
    return next(iter(scopes), None) if len(scopes) <= 1 else None


def apply_roughness_verification(review: dict[str, Any], candidates: list[dict[str, Any]], document_id: str) -> bool:
    """Upgrade a read draft, protecting manual values and ambiguous legacy history."""
    item = (review.get("spring_parameters") or {}).get(SURFACE_ROUGHNESS_FIELD)
    if not isinstance(item, dict):
        return False
    before = deepcopy(item)
    before.pop("roughness_verification_adjustment", None)
    grouped = merge_roughness_candidates(candidates)
    accepted, conflict, recognition_state = roughness_selection(grouped)
    item.update(roughness_candidates=grouped, verification_version=ROUGHNESS_VERIFICATION_VERSION,
                source_document_id=document_id, recognition_state=recognition_state, value_verified=bool(accepted) and not conflict)
    confirmation = (review.get("manual_confirmations") or {}).get(SURFACE_ROUGHNESS_FIELD) or {}
    protected = (human_override(item) or "human_confirmed" in _source_values(item.get("source"))
                 or confirmation.get("confirmed") is True or item.get("need_human_review") is not True)
    if protected:
        if positive_surface_roughness(item.get("value")) is not None and not any(c["value"] == positive_surface_roughness(item["value"]) for c in accepted):
            item["roughness_verification_warning"] = "未找到该值的明确原图依据；已保留人工值或历史确认值，请核对。"
        else:
            item.pop("roughness_verification_warning", None)
    else:
        item.pop("roughness_conflict", None)
        item.pop("roughness_verification_warning", None)
        item["value"] = accepted[0]["value"] if accepted and not conflict else None
        item["surface_location"] = selected_roughness_location(accepted) if accepted and not conflict else None
        item["need_human_review"] = True
        if conflict:
            item["roughness_conflict"] = True
        if accepted and not conflict:
            first = next((c for c in accepted if verified_roughness_candidate(c)), accepted[0])
            item["page"], item["position"] = first.get("page", 1), first.get("position") if verified_roughness_candidate(first) else None
        else:
            item["position"] = None
        if before.get("value") != item["value"]:
            item.setdefault("roughness_original_recognition", before)
            item.pop("confirmation_snapshot", None)
    item["value_verified"] = not conflict and any(c["value"] == positive_surface_roughness(item.get("value")) for c in accepted)
    after = deepcopy(item)
    after.pop("roughness_verification_adjustment", None)
    if before == after:
        return False
    # The client puts this upgrade through its ordinary revisioned save queue.
    item["roughness_verification_adjustment"] = {"before": before, "audit_recorded": False,
                                                "verification_version": ROUGHNESS_VERIFICATION_VERSION}
    return True


def surface_roughness_text(value: Any, location: Any = None) -> str | None:
    number = positive_surface_roughness(value)
    if number is None:
        return None
    prefix = str(location or "").strip()
    label = _compact_number(number)
    return f"{prefix}粗糙度 Ra {label}μm" if prefix else f"表面粗糙度 Ra {label}μm"


def ensure_surface_roughness_parameter(review: dict[str, Any]) -> bool:
    """Add the optional compression-spring parameter and promote legacy notes.

    This intentionally does not scan historical free-form Qwen notes. Those jobs
    need re-recognition because a note alone was never persisted as review data.
    """

    if not isinstance(review, dict) or _spring_type(review) != "compression_spring":
        return False
    changed = _ensure_template_field(review)
    parameters = review.setdefault("spring_parameters", {})
    if not isinstance(parameters, dict):
        return changed
    existing = parameters.get(SURFACE_ROUGHNESS_FIELD)
    if not isinstance(existing, dict):
        existing = _blank_surface_roughness_parameter()
        parameters[SURFACE_ROUGHNESS_FIELD] = existing
        changed = True
    elif not existing.get("unit"):
        existing["unit"] = SURFACE_ROUGHNESS_UNIT
        changed = True

    requirements = review.get("technical_requirements")
    if not isinstance(requirements, list):
        return changed
    promoted: list[dict[str, Any]] = []
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in requirements:
        if not isinstance(item, dict) or str(item.get("type") or "").strip().casefold() not in {
            "surface_roughness",
            "roughness",
            "surface_finish",
            "表面粗糙度",
        }:
            continue
        mention = standalone_surface_roughness(item)
        if mention is None:
            continue
        candidates.append((item, mention))
        promoted.append({
            **mention, "evidence": str(item.get("evidence") or item.get("content") or ""),
            "source": _source_values(item.get("source")) or ["legacy_technical_requirement"],
            "confidence": float(item.get("confidence", 0) or 0),
            "need_human_review": item.get("need_human_review", True),
            "human_confirmed": item.get("need_human_review") is False and (
                human_override(item) or "human_confirmed" in _source_values(item.get("source"))
                or item.get("confirmation_source") == "human_confirmed"
                or ((review.get("manual_confirmations") or {}).get(f"technical_requirement_{item.get('requirement_id')}") or {}).get("confirmed") is True),
            "page": item.get("page", 1), "position": item.get("position"),
            **{k: item[k] for k in ("verification_version", "source_document_id", "independent_evidence", "evidence_status") if k in item},
        })
    if promoted:
        if existing.get("value") in (None, "") and not human_override(existing):
            changed = _merge_promoted_mentions(existing, promoted) or changed
        selected = {"value": positive_surface_roughness(existing.get("value")),
                    "unit": _roughness_unit(existing.get("unit")),
                    "location": _roughness_location(existing.get("surface_location"))}
        usable = not existing.get("roughness_conflict") and not existing.get("formula_recommendation_stale") and parameter_current(parameters, SURFACE_ROUGHNESS_FIELD)
        absorbed = {id(item) for item, mention in candidates if usable and mention == selected
                    and (existing.get("need_human_review") is False or item.get("need_human_review") is not False)}
        if absorbed:
            review["technical_requirements"] = [item for item in requirements if id(item) not in absorbed]
            changed = True
    return changed


def confirmed_surface_roughness_requirement(review: dict[str, Any]) -> dict[str, Any] | None:
    if _spring_type(review) != "compression_spring":
        return None
    roughness = confirmed_surface_roughness(review)
    content = surface_roughness_text(roughness["value"], roughness["location"]) if roughness else None
    if not content:
        return None
    return {
        "type": "surface_roughness",
        "content": content,
        "confirmation_source": "human_confirmed",
    }


def _merge_promoted_mentions(target: dict[str, Any], mentions: list[dict[str, Any]]) -> bool:
    # Legacy prose is another recognition source, not an independent verifier.
    # Explicitly human-confirmed notes keep the historical promotion behavior.
    if not all(item.get("human_confirmed") is True for item in mentions):
        candidates = merge_roughness_candidates([*(target.get("roughness_candidates") or []), *mentions])
        if target.get("roughness_candidates") == candidates:
            return False
        target["roughness_candidates"] = candidates
        target["source"] = _unique([*_source_values(target.get("source")), "legacy_technical_requirement"])
        return True
    values: dict[tuple[float, str], dict[str, Any]] = {}
    for mention in mentions:
        value = positive_surface_roughness(mention.get("value"))
        if value is None:
            continue
        values.setdefault((value, _roughness_location(mention.get("location"))), mention)
    if not values:
        return False
    had_value = positive_surface_roughness(target.get("value")) is not None
    candidates = [
        {
            "value": float(value[0]),
            "location": item.get("location"),
            "evidence": item.get("evidence", ""),
            "source": item.get("source", []),
        }
        for value, item in values.items()
    ]
    target["roughness_candidates"] = candidates
    target["source"] = _unique([*_source_values(target.get("source")), "legacy_technical_requirement"])
    target["evidence"] = " | ".join(
        value for value in [str(item.get("evidence") or "").strip() for item in mentions] if value
    )
    target["confidence"] = max(float(item.get("confidence", 0) or 0) for item in mentions)
    if not had_value:
        target["need_human_review"] = not (
            len(values) == 1 and all(item.get("need_human_review") is False for item in mentions)
        )
    if len(values) == 1 and target.get("value") in (None, ""):
        value, mention = next(iter(values.items()))
        target["value"] = float(value[0])
        target["surface_location"] = mention.get("location") or None
        target.pop("roughness_conflict", None)
        if target.get("need_human_review") is False:
            target["source"] = _unique(["human_confirmed", *_source_values(target.get("source"))])
    elif len(values) > 1 and target.get("value") in (None, ""):
        target["value"] = None
        target["roughness_conflict"] = True
    return True


def _ensure_template_field(review: dict[str, Any]) -> bool:
    template = review.get("spring_template")
    if not isinstance(template, dict):
        return False
    fields = template.get("fields")
    if not isinstance(fields, list):
        return False
    if any(isinstance(item, dict) and item.get("key") == SURFACE_ROUGHNESS_FIELD for item in fields):
        return False
    field = {
        "key": SURFACE_ROUGHNESS_FIELD,
        "label": SURFACE_ROUGHNESS_LABEL,
        "unit": SURFACE_ROUGHNESS_UNIT,
    }
    active_index = next(
        (index for index, item in enumerate(fields) if isinstance(item, dict) and item.get("key") == "active_coils"),
        len(fields) - 1,
    )
    fields.insert(active_index + 1, deepcopy(field))
    return True


def _blank_surface_roughness_parameter() -> dict[str, Any]:
    return {
        "value": None,
        "unit": SURFACE_ROUGHNESS_UNIT,
        "tolerance_upper": None,
        "tolerance_lower": None,
        "source": [],
        "evidence": "",
        "confidence": 0,
        "need_human_review": True,
        "page": 1,
        "position": None,
        "suggested_region": "",
    }


def _spring_type(review: dict[str, Any]) -> str:
    return str(
        (review.get("drawing_summary") or {}).get("spring_type")
        or (review.get("spring_template") or {}).get("spring_type")
        or ""
    )


def _source_values(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    return [str(item) for item in raw if item not in (None, "")]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _compact_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)
