"""Ground new surface-treatment notes in their original drawing lines."""

from copy import deepcopy
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unicodedata

from PIL import Image, ImageOps

from .drawing_annotations import _rect, annotation_file_lock, ocr_blocks, pdf_blocks
from .engines.ocr_providers import RapidOcrProvider
from .multi_spec import box
from .page_images import fingerprint, read_json, write_json
from .surface_catalog import SURFACE_EVIDENCE_VERSION, surface_hint, surface_terms, verified_surface
from .technical_requirements import surface_requirement_body

_NUMBER = re.compile(r"^\s*[·•]?\s*(\d+)\s*[.．、)]\s*(?=[^\d\s])")
_NUMBERS = re.compile(r"\d+(?:\.\d+)?")
_CHINESE = re.compile(r"[\u3400-\u9fff]")
_CONDITIONS = re.compile(r"除氢|厚度|等级|端面|内侧|外侧|局部|不得|禁止|无需|不允许|thickness|without|shall not", re.I)
_INCOMPLETE = re.compile(r"^(?:[混批]?丸|[?？□]+)(?:[。.;；])?$")
_WEAK_ANCHOR = re.compile(r"(?<=\d)-(\d)(?=HRC|HRE)", re.I)
_SURFACE_FIELDS = {"surface", "surface_treatment", "surface_requirement"}
_NOTE_FIELDS = _SURFACE_FIELDS | {"process_requirement", "other_requirement", "heat_treatment", "hardness",
                                  "salt_spray", "environmental", "lifetime_test"}


def _raw(note):
    return str(note.get("original_content") or note.get("raw_content") or note.get("content") or note.get("value") or "").strip()


def _body(text):
    return _NUMBER.sub("", text.strip(), count=1).strip()


def _number(text):
    match = _NUMBER.match(text)
    return int(match[1]) if match else None


def _note_number(note):
    number = _number(_raw(note))
    declared = str(note.get("original_number") or "")
    return int(declared) if number is None and declared.isdecimal() else number


def _literal(text):
    body = surface_requirement_body(unicodedata.normalize("NFKC", _body(text)))
    return re.sub(r"[。.;；]+$", "", re.sub(r"\s+", "", body)).casefold()


def _incomplete(text):
    body = surface_requirement_body(_body(text))
    return not body or bool(_INCOMPLETE.fullmatch(body))


def _broad_paint(text):
    return _literal(text) == "涂漆"


def _same_region(left, right):
    if not left or not right:
        return False
    w = min(left["x"] + left["width"], right["x"] + right["width"]) - max(left["x"], right["x"])
    h = min(left["y"] + left["height"], right["y"] + right["height"]) - max(left["y"], right["y"])
    return w > 0 and h > 0 and w * h >= min(left["width"] * left["height"], right["width"] * right["height"]) * .5


def _contained(position, scope):
    return any(scope_box["x"] <= position["x"] + position["width"] / 2 <= scope_box["x"] + scope_box["width"]
               and scope_box["y"] <= position["y"] + position["height"] / 2 <= scope_box["y"] + scope_box["height"]
               for scope_box in scope)


def _surface_note(note):
    return (note.get("type", note.get("field")) in _SURFACE_FIELDS
            or surface_hint(_raw(note)) or surface_hint(note.get("content", note.get("value"))))


def _is_auxiliary(note):
    return note.get("field") == "surface_requirement" and note.get("recognition_channel") != "technical_requirements" and not note.get("original_content")


def _anchor_text(left, right):
    a, b = _literal(left), _literal(right)
    if a == b and len(a) >= 4:
        return True
    # Hardness text is used only to find the numbered note list.
    if "硬度" in a and "硬度" in b:
        def shape(literal):
            literal = _WEAK_ANCHOR.sub(r"\1", literal).replace("hre", "hrc")
            return re.sub(r"[^\w]", "", literal.replace("hrc", ""))
        return len(_NUMBERS.findall(a)) >= 2 and shape(a) == shape(b)
    return False


def _numbering_anchor(notes, lines):
    offsets = set()
    anchors = []
    for note in notes:
        source = _raw(note)
        number = _note_number(note)
        if number is not None and not _surface_note(note):
            matches = _unique_site([line for line in lines if _number(line["text"]) is not None and _anchor_text(source, line["text"])])
            if matches:
                offsets.add(_number(matches[0]["text"]) - number)
                anchors.append(matches[0]["position"])
    return (next(iter(offsets)), anchors) if len(offsets) == 1 else (None, [])


def _unique_site(lines):
    if not lines or any(not _same_region(lines[0]["position"], line["position"]) for line in lines[1:]):
        return []
    return lines


def _match_lines(note, lines, offset, position, anchors):
    raw = _raw(note)
    at_position = [line for line in lines if _same_region(position, line["position"])]
    if at_position:
        site = _unique_site(at_position)
        if site:
            return site
    # A bilingual Qwen note can quote two printed locations. Prefer the
    # independently observed Chinese line for an already Chinese finish.
    parts = raw.splitlines()
    if len(parts) > 1 and _CHINESE.search(parts[0]):
        chinese = _unique_site([line for line in lines if _literal(line["text"]) == _literal(parts[0])])
        if chinese and surface_hint(parts[0]):
            return chinese
        translated = _unique_site([line for line in lines if _literal(line["text"]) in {_literal(part) for part in parts[1:]}])
        if translated:
            return translated
    number = _note_number(note)
    if number is not None:
        expected = number + (offset or 0)
        numbered = [line for line in lines if _number(line["text"]) == expected]
        if anchors:
            numbered = [line for line in numbered if any(_same_list(line["position"], anchor) for anchor in anchors)]
        # Number-only matches require a matching note from the same list or
        # an identical surface reading. Repeated numbers never select a site.
        if offset is not None or any(_literal(line["text"]) in {_literal(part) for part in raw.splitlines()} for line in numbered):
            if site := _unique_site(numbered):
                return site
        if offset is not None and numbered:
            return []
    if _literal(raw):
        exact = {_literal(part) for part in parts}
        return _unique_site([line for line in lines if _literal(line["text"]) in exact
                             or (_is_auxiliary(note) and _literal(line["text"]).split(":", 1)[-1] in exact)])
    return []


def _same_list(a, b):
    return abs(a["x"] - b["x"]) < .18 and abs(a["y"] - b["y"]) < .18


def _near_numbered_peer(note, lines, offset, peers):
    target = _note_number(note)
    if offset is not None or target is None:
        return False
    # A numbered candidate with no box can only use the list when an adjacent
    # note also matches and the two boxes belong to the same column or row.
    current = _unique_site([line for line in lines if _number(line["text"]) == target])
    if not current:
        return False
    for peer in peers:
        raw = _raw(peer)
        number = _note_number(peer)
        if number not in {target - 1, target + 1}:
            continue
        matches = [line for line in lines if _number(line["text"]) == number
                   and (_same_or_more_specific(line["text"], raw) or _anchor_text(raw, line["text"]))]
        if len(matches) == 1:
            a, b = current[0]["position"], matches[0]["position"]
            if abs(a["x"] - b["x"]) < .065 and abs(a["y"] - b["y"]) < .065:
                return True
    return False


def _readings(paths, meta=None):
    """Return OCR boxes in original normalized page coordinates."""
    if not paths:
        return []
    output = []
    for page in RapidOcrProvider().recognize(list(paths.values()), {}):
        key = list(paths)[page["page"] - 1]
        bounds, angle, original_page = meta[key] if meta is not None else ((0, 0, 1, 1), 0, key)
        with Image.open(paths[key]) as image:
            width, height = image.size
        for row in page.get("texts", []):
            rect = _rect(row.get("position"), width, height, center=True)
            if not rect or not str(row.get("text") or "").strip():
                continue
            x, y, w, h = (rect[k] for k in ("x", "y", "width", "height"))
            if angle == 90:
                x, y, w, h = 1 - y - h, x, h, w
            elif angle == 270:
                x, y, w, h = y, 1 - x - w, h, w
            bx, by, ex, ey = bounds
            position = {"x": bx + x * (ex - bx), "y": by + y * (ey - by), "width": w * (ex - bx), "height": h * (ey - by)}
            output.append({"key": key, "page": original_page, "text": row["text"], "position": position,
                           "source": "local_ocr", "confidence": row.get("confidence")})
    return output


def _cached_lines(raw_payloads, images):
    pages = [{"page": number} for number in images]
    return ocr_blocks(raw_payloads, pages)


def _page_ocr(images, pages, directory):
    paths = {}
    for page in sorted(pages)[:3]:
        if page not in images:
            continue
        path = directory / f"page-{page}.png"
        with Image.open(images[page]) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((3000, 3000))
            image.save(path)
        paths[page] = path
    return _readings(paths)


def _crop(source, image_path, page, position):
    x, y, w, h = (position[key] for key in ("x", "y", "width", "height"))
    with Image.open(image_path) as original:
        image = ImageOps.exif_transpose(original)
        width, height = image.size
        if h * height > w * width * 1.3:
            dx, dy = w * .16, max(h * .08, .002)
            angle = 90 if x > .5 else 270
        else:
            dx, dy, angle = max(w * .08, .002), h * .16, 0
        bounds = max(0, x - dx), max(0, y - dy), min(1, x + w + dx), min(1, y + h + dy)
        if source.suffix.lower() == ".pdf":
            from .page_images import render_region
            try:
                crop = render_region(source, page, bounds, dpi=420)
            except (RuntimeError, ValueError):
                crop = image.crop(tuple(round(value * side) for value, side in zip(bounds, (width, height, width, height))))
        else:
            crop = image.crop(tuple(round(value * side) for value, side in zip(bounds, (width, height, width, height))))
        if angle:
            crop = crop.rotate(angle, expand=True)
        if crop.height < 150:
            scale = min(150 / max(crop.height, 1), 1800 / max(crop.width, 1))
            if scale > 1:
                crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)
        return crop, bounds, angle


def _evidence(line):
    return {key: line.get(key) for key in ("source", "text", "page", "position") if line.get(key) is not None}


def _credible(line, original):
    text = line["text"]
    if not surface_hint(text) or _incomplete(text):
        return False
    # A crop which truncates known engineering values is not a complete note.
    observed = set(_NUMBERS.findall(_body(text)))
    expected = {number for part in original.splitlines() for number in _NUMBERS.findall(_body(part))}
    found = set(_CONDITIONS.findall(text.casefold().replace("thickness", "厚度")))
    required = set(_CONDITIONS.findall(original.casefold().replace("thickness", "厚度")))
    return expected <= observed and required <= found


def _classification_terms(text):
    return [term[2].upper().replace(" ", "") for term in surface_terms(text, aliases=True, generic=True, include_negative=True)
            if term[2].upper() not in {"表面处理", "表面處理", "FINISH"}]


def _matches_scope(other, note):
    return str(other.get("application_scope") or "").strip() == str(note.get("application_scope") or "").strip()


def _same_or_more_specific(text, other):
    a, b = _literal(text), _literal(other)
    if a == b:
        return True
    # Retain the full clause and its conditions. Only this maintained paint
    # distinction may resolve an OCR omission by a longer reading.
    return "涂清漆" in a and a.replace("涂清漆", "涂漆", 1) == b


def _pick_line(lines, original):
    complete = [line for line in lines if _credible(line, original)]
    verified_pdf = [line for line in complete if line["source"] == "pdf_text"]
    if verified_pdf:
        complete = verified_pdf
    if not complete:
        return None
    for line in complete:
        if all(_same_or_more_specific(line["text"], other["text"]) for other in complete):
            return line
    return None


def _agrees_with_local(local, followup):
    if not local:
        return True
    return all(_incomplete(line["text"]) or not _credible(line, "")
               or _same_or_more_specific(followup["text"], line["text"]) for line in local)


def _followup(job_dir, source, crops, engine):
    if not crops:
        return {}
    with annotation_file_lock(job_dir, "surface-read.lock"):
        path = job_dir / "surface-line-read.json"
        cached = read_json(path)
        digest = fingerprint(source)
        regions = {key: fingerprint(crop) for key, crop in crops.items()}
        if cached.get("source") == digest and cached.get("version") == SURFACE_EVIDENCE_VERSION:
            return {key: text for key, text in (cached.get("lines") or {}).items() if cached.get("regions", {}).get(key) == regions.get(key)}
        if engine is None:
            return {}
        record = {"source": digest, "version": SURFACE_EVIDENCE_VERSION, "regions": regions, "lines": {}}
        write_json(path, record)
        try:
            record["lines"] = engine.read_surface_lines(crops)
        except Exception as exc:
            record["error_type"] = type(exc).__name__
        write_json(path, record)
        return record["lines"]


def _scoped_notes(candidates, multi):
    if multi is None:
        return [(candidates, None, 1)]
    common = multi["common"]
    scopes = [(common.get("technical_requirements", []), common.get("regions") or [], 1)]
    scopes.extend((variant.get("technical_requirements", []),
                   [{"page": variant["page"], **variant["region"]}] if variant.get("region") else [],
                   variant["page"]) for variant in multi["variants"])
    return scopes


def _prepared_note(note, chosen, evidence, page, position):
    raw = chosen["text"] if chosen else _raw(note)
    verification = {"version": SURFACE_EVIDENCE_VERSION, "status": "verified" if chosen else "uncertain", "readings": evidence[:8]}
    if chosen and chosen["source"] == "qwen_crop" and len(evidence) > 8:
        verification["readings"][-1] = _evidence(chosen)
    position = {**position, "coordinate_type": "normalized", "origin": "top_left"} if position else None
    result = verified_surface({**note, "page": page, "position": position}, raw, verification)
    if note.get("source") != "qwen_vision":
        result["recognition_channel"] = note.get("recognition_channel") or "technical_requirements"
    if chosen and (number := _number(raw)) is not None:
        result["original_number"] = str(number)
    if "field" in note:
        result.update(field="surface_requirement", value=result["content"], recognized_content=result["content"])
    return result


def _inspection_position(note):
    position = note.get("position")
    if not isinstance(position, dict) or position.get("coordinate_type") == "pixel" or position.get("origin") == "center":
        return None
    return box(position)


def reconcile_surface_notes(candidates, multi, *, source: Path, job_dir: Path, images, raw_payloads, engine=None):
    """Run once during recognition, before storing single or multi-spec notes."""
    multi = deepcopy(multi)
    candidates = list(candidates)
    if multi is None:
        parsed = (raw_payloads.get("qwen_vision") or {}).get("parsed") or {}
        originals = {str(note.get("recognition_key")): note.get("original_content")
                     for note in _model_note_metadata(parsed) if note.get("original_content")}
        candidates = [{**note, "original_content": originals[note["recognition_key"]]}
                      if note.get("source") == "qwen_vision" and note.get("recognition_key") in originals else note
                      for note in candidates]
    scopes = _scoped_notes(candidates, multi)
    if not any(_surface_note(note) for notes, regions, _ in scopes for note in notes
               if isinstance(note, dict) and (regions is not None or note.get("field") in _NOTE_FIELDS)):
        return candidates, multi
    image_pages = {page: Path(path) for page, path in enumerate(images, 1)}
    initial = _cached_lines(raw_payloads, image_pages)
    if source.suffix.lower() == ".pdf":
        try:
            initial.extend(pdf_blocks(source, max(image_pages, default=1)))
        except (RuntimeError, OSError, ValueError):
            pass
    with TemporaryDirectory(prefix="surface-evidence-", dir=job_dir) as temp:
        directory = Path(temp)
        entries = _surface_entries(scopes, initial)
        missing = {entry["page"] for entry in entries if not entry["lines"]}
        if missing:
            try:
                initial.extend(_page_ocr(image_pages, missing, directory))
            except (RuntimeError, OSError, ValueError):
                pass
            entries = _surface_entries(scopes, initial)
        _resolve_entries(entries, source, job_dir, image_pages, directory, engine)
        if multi is None:
            candidates = _merge_auxiliary(candidates)
    return candidates, multi


def _model_note_metadata(parsed):
    from .technical_requirement_recognition import recognition_metadata
    for index, note in enumerate(parsed.get("technical_requirements") or [], 1):
        if isinstance(note, dict):
            yield {**note, **recognition_metadata(note, index)}


def _surface_entries(scopes, lines):
    entries = []
    for notes, regions, default in scopes:
        relevant = [note for note in notes if isinstance(note, dict) and (regions is not None or note.get("field") in _NOTE_FIELDS)]
        page_cache = {}
        for index, note in enumerate(notes):
            if not isinstance(note, dict) or (regions is None and note.get("field") not in _NOTE_FIELDS) or not _surface_note(note):
                continue
            page = note.get("page") or default
            scope_key = page, str(note.get("application_scope") or "").strip()
            if scope_key not in page_cache:
                page_regions = [r for r in regions or [] if isinstance(r, dict) and (r.get("page") or default) == page and box(r)]
                page_lines = [line for line in lines if line["page"] == page
                              and (regions is None or _contained(line["position"], page_regions))]
                peers = [other for other in relevant if (other.get("page") or default) == page and _matches_scope(other, note)]
                offset, anchors = _numbering_anchor(peers, page_lines)
                page_cache[scope_key] = page_regions, page_lines, peers, offset, anchors
            page_regions, page_lines, peers, offset, anchors = page_cache[scope_key]
            position = _inspection_position(note)
            if position and regions is not None and not _contained(position, page_regions):
                position = None
            if _near_numbered_peer(note, page_lines, offset, peers):
                offset = 0
            at_note = _match_lines(note, page_lines, offset, position, anchors)
            if at_note:
                position = at_note[0]["position"]
            entries.append({"notes": notes, "index": index, "note": note, "page": page, "lines": at_note, "position": position})
    return entries


def _resolve_entries(entries, source, job_dir, images, directory, engine):
    crops, metadata, pending = {}, {}, {}
    crop_directory = job_dir / "surface-evidence"
    for index, entry in enumerate(entries):
        note, lines, page, position = (entry[key] for key in ("note", "lines", "page", "position"))
        raw = _raw(note)
        entry["evidence"] = [_evidence(line) for line in lines]
        if raw:
            entry["evidence"].append({"source": "initial", "text": raw, "page": page, "position": note.get("position")})
        proposed = str(note.get("content") or note.get("value") or "").strip()
        if proposed and _literal(proposed) != _literal(raw):
            entry["evidence"].append({"source": "initial_body", "text": proposed, "page": page})
        chosen = _pick_line(lines, raw)
        if chosen and chosen["source"] != "pdf_text":
            source_parts = raw.splitlines() or [raw]
            matching_kind = any(_classification_terms(chosen["text"]) == _classification_terms(part) for part in source_parts)
            more_specific = any(_same_or_more_specific(chosen["text"], part) for part in source_parts)
            if not matching_kind and not more_specific and not _is_auxiliary(note):
                chosen = None
        if chosen and chosen["source"] != "pdf_text" and _broad_paint(chosen["text"]):
            entry["broad"] = chosen
            chosen = None
        entry["chosen"] = chosen
        if chosen or not position or page not in images or len(crops) >= 12:
            continue
        try:
            crop, bounds, angle = _crop(source, images[page], page, position)
            key = str(index + 1)
            path = directory / f"line-{key}.png"
            crop.save(path)
            crops[key], metadata[key], pending[key] = path, (bounds, angle, page), entry
            entry["crop"] = path
        except (OSError, RuntimeError, ValueError):
            continue
    try:
        local = _readings(crops, metadata)
    except (RuntimeError, OSError, ValueError):
        local = []
    for key, entry in pending.items():
        reads = [line for line in local if line["key"] == key and _same_region(line["position"], entry["position"])]
        entry["local"] = reads
        entry["evidence"].extend(_evidence(line) for line in reads)
        chosen = _pick_line(reads, _raw(entry["note"]))
        if chosen and _agrees_with_local(entry["lines"], chosen):
            entry["broad" if _broad_paint(chosen["text"]) else "chosen"] = chosen
    needed = {key: crops[key] for key, entry in pending.items() if not entry["chosen"]}
    for key, text in _followup(job_dir, source, needed, engine).items():
        entry = pending[key]
        line = {"source": "qwen_crop", "text": text, "page": entry["page"], "position": entry["position"]}
        entry["evidence"].append(_evidence(line))
        entry["crop_answer"] = text
        printed = {_number(other["text"]) for other in entry["lines"] + entry["local"]} - {None}
        if (_number(text) is None or not printed or _number(text) in printed) and _credible(line, _raw(entry["note"])):
            if _agrees_with_local(entry["local"] + entry["lines"], line):
                entry["chosen"] = line
    for entry in entries:
        notes, index, note, chosen, evidence, page, position = (entry[k] for k in ("notes", "index", "note", "chosen", "evidence", "page", "position"))
        if (not chosen and entry.get("broad") and not entry.get("crop_answer")
                and all(_broad_paint(reading["text"]) for reading in entry.get("local") or entry["lines"])):
            chosen = entry["broad"]
        notes[index] = _prepared_note(note, chosen, evidence, page, position)
        if not chosen and entry.get("crop"):
            crop = entry["crop"]
            name = f"{fingerprint(crop)[:20]}.png"
            crop_directory.mkdir(exist_ok=True)
            crop.replace(crop_directory / name)
            notes[index]["surface_mapping"]["verification"]["crop_path"] = f"surface-evidence/{name}"


def _merge_auxiliary(candidates):
    notes = [note for note in candidates if isinstance(note, dict) and note.get("surface_mapping", {}).get("verification")]
    primary = [note for note in notes if note.get("source") == "qwen_vision" and note.get("recognition_channel") == "technical_requirements"]
    dropped = set()
    for note in notes:
        verification = note["surface_mapping"]["verification"]
        if note in primary or verification["status"] != "verified":
            continue
        matches = [item for item in primary if item.get("page") == note.get("page")
                   and _matches_scope(item, note)
                   and _same_region(item.get("position"), note.get("position"))
                   and _literal(item["original_content"]) == _literal(note["original_content"])]
        if len(matches) == 1:
            readings = matches[0]["surface_mapping"]["verification"]["readings"]
            for reading in verification["readings"]:
                if reading not in readings and len(readings) < 8:
                    readings.append(reading)
            dropped.add(id(note))
    return [note for note in candidates if id(note) not in dropped]
