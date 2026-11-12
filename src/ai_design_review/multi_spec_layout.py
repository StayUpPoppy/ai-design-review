"""Spatial evidence for the multi-spec guard, independent of extracted parameters."""
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
import re
import unicodedata

from .drawing_annotations import _rect, ocr_blocks, pdf_blocks


LAYOUT_RULE_VERSION = "multi-spec-layout/v2"

_NUMBER = r"[φø⌀$]?\d+(?:\.\d+)?"
_COMPOSITE = re.compile(rf"^{_NUMBER}x{_NUMBER}[^x]*x{_NUMBER}[^x]*$")
_PARTIAL_COMPOSITE = re.compile(rf"^{_NUMBER}x{_NUMBER}[^x]*x?$")
_SPEC_HEADER = re.compile(r"规格(?:尺寸)?|dxd[12]?xh[0o]|specifications?")
_BLOCK_TITLE = re.compile(r"(?:螺旋)?压缩弹簧(?:计算|参数)(?:表)?|compressionspring(?:calculation|parameters)")
_CORE = {
    "wire": r"(?:簧丝直径|钢丝直径|线径|wirediameter)d?",
    "mean": r"(?:中径|meandiameter)d?",
    "free": r"(?:自由(?:高度|长度)|free(?:height|length))[hl]?[0o]?",
    "coils": r"(?:(?:总|有效)圈数|(?:total|active)(?:numberof)?(?:coils|turns))n?1?",
}
_VALUE = rf"{_NUMBER}(?:(?:±|\+|-|/){_NUMBER})*(?:mm|圈)?"
_LABELS = {key: re.compile(pattern + rf"(?:(?:[:=]|\s+)\s*({_VALUE}))?$") for key, pattern in _CORE.items()}


@dataclass(frozen=True)
class TextBox:
    text: str
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    @property
    def cx(self):
        return self.x + self.width / 2

    @property
    def cy(self):
        return self.y + self.height / 2


def _compact(text):
    return re.sub(r"\s+", "", text)


def _same_row(left, right):
    return abs(left.cy - right.cy) <= min(left.height, right.height) * 0.6


def _same_column(left, right):
    return min(left.right, right.right) - max(left.x, right.x) >= min(left.width, right.width) * 0.45


def _region(boxes, padding=0):
    x = max(0, min(box.x for box in boxes) - padding)
    y = max(0, min(box.y for box in boxes) - padding)
    right = min(1, max(box.right for box in boxes) + padding)
    bottom = min(1, max(box.bottom for box in boxes) + padding)
    return {"x": x, "y": y, "width": right - x, "height": bottom - y}


def _text_box(text, rect):
    if not isinstance(text, str) or not rect or len(text.splitlines()) != 1:
        return None
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).strip().lower())
    return TextBox(text.replace("×", "x").replace("*", "x"), **rect) if text else None


def _frame_blocks(payload):
    """Imported OCR can supply its own image dimensions or normalized boxes."""
    frames = payload.get("raw_pages") or payload.get("pages") or [payload]
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        width, height = frame.get("width"), frame.get("height")
        framed = isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0
        for item in frame.get("texts") or []:
            if not isinstance(item, dict) or str(item.get("field", "")).startswith("document_text"):
                continue
            position = item.get("position")
            if not isinstance(position, dict):
                continue
            normalized = position.get("coordinate_type") in {"normalized", "relative"}
            if normalized or framed:
                rect = _rect(position, width if framed else 1, height if framed else 1, center=not normalized)
                yield {"page": frame.get("page", item.get("page", 1)), "text": item.get("text"), "position": rect}


def layout_blocks(raw_payloads, source=None, page_count=1, *, artifact_dir=None):
    pages = [{"page": number} for number in range(1, page_count + 1)]
    payloads = {key: {"texts": value} if isinstance(value, list) else value for key, value in raw_payloads.items()}
    # Raw OCR page images carry their own DPI and orientation. The flattened
    # candidates and page summaries do not supply an independent spatial read.
    framed_payloads = {}
    for key, payload in payloads.items():
        if not isinstance(payload, dict) or key in {"candidate_json", "ocr_json", "sample_ocr_json"}:
            continue
        frames = []
        for frame in payload.get("raw_pages", payload.get("pages", [])) or []:
            if not isinstance(frame, dict) or not isinstance(frame.get("image_path"), str):
                continue
            if artifact_dir and not Path(frame["image_path"]).resolve().is_relative_to(artifact_dir.resolve()):
                continue
            frames.append({**frame, "texts": [item for item in frame.get("texts") or [] if isinstance(item, dict)
                           and not str(item.get("field", "")).startswith("document_text")]})
        if frames:
            framed_payloads[key] = {"raw_pages": frames}
    result = ocr_blocks(framed_payloads, pages)
    for payload in payloads.values():
        if isinstance(payload, dict):
            result.extend(_frame_blocks(payload))
    if source and Path(source).suffix.lower() == ".pdf":
        try:
            for line in pdf_blocks(Path(source), page_count):
                result.append(line)
                if len(line["tokens"]) > 1:
                    result.extend({**token, "page": line["page"]} for token in line["tokens"])
        except (OSError, ValueError, RuntimeError):
            pass
    return [item for item in result if isinstance(item.get("page"), int) and 1 <= item["page"] <= page_count]


def _row_evidence(boxes):
    headers = [box for box in boxes if _SPEC_HEADER.fullmatch(_compact(box.text))]
    dimensions = [box for box in boxes if _COMPOSITE.fullmatch(_compact(box.text))]
    partial = [box for box in boxes if _PARTIAL_COMPOSITE.fullmatch(_compact(box.text))]
    best = None
    for header in headers:
        if not re.fullmatch(r"dxd[12]?xh[0o]", _compact(header.text)) and not any(
            abs(box.cy - header.cy) <= max(box.height, header.height) * 2
            and (re.search(r"圈数|(?:coils|turns)$", box.text) or re.fullmatch(r"dxd[12]?xh[0o]", _compact(box.text)))
            for box in boxes
        ):
            continue
        rows = []
        for cell in dimensions:
            if cell.cy <= header.cy or not _same_column(cell, header):
                continue
            previous = rows[-1] if rows else header
            if cell.cy - previous.cy > max(cell.height, previous.height) * 4:
                break
            if not _same_row(cell, previous):
                rows.append(cell)
        if len(rows) >= 2 and (best is None or len(rows) > best[0]):
            best = (len(rows), _region([header, *rows], .02), True)
        if len(rows) == 1 and best is None:
            neighbors = [cell for cell in partial if _same_column(cell, header)
                         and 0 < cell.cy - rows[0].cy <= rows[0].height * 4 and not _same_row(cell, rows[0])]
            if neighbors:
                best = (1, _region([header, *rows, *neighbors], .02), False)
    return best


def _label(box):
    # Preserve the gap before an inline value while allowing bilingual labels
    # whose letters or characters are split by the PDF text layer.
    text = box.text
    for key, pattern in _LABELS.items():
        for spelling in (_compact(text), re.sub(r"\s+(?![φø⌀$]?\d)", "", text)):
            match = pattern.fullmatch(spelling)
            if match:
                return key, bool(match.group(1))
    return None


def _block_evidence(boxes):
    labels = [(box, *label) for box in boxes if (label := _label(box))]
    values = [box for box in boxes if re.fullmatch(_VALUE, _compact(box.text))]
    titles = [box for box in boxes if _BLOCK_TITLE.fullmatch(_compact(box.text))]
    lanes = []
    for label, family, inline in labels:
        nearest_label = min((other.cx for other, _, _ in labels if other.cx > label.right and _same_row(other, label)), default=1)
        value = label if inline else min((value for value in values if _same_row(label, value)
            and label.right - label.width * .1 <= value.x < nearest_label
            and value.x - label.right <= label.width * 2), key=lambda value: value.x, default=None)
        lane = next((lane for lane in lanes if _same_column(lane[0][0], label)
                     and abs(lane[0][0].cx - label.cx) <= max(lane[0][0].width, label.width) * .5), None)
        if lane is None:
            lane = []
            lanes.append(lane)
        if any(item[1] == family and _same_row(item[0], label) for item in lane):
            continue
        lane.append((label, family, value))

    groups = []
    for lane in lanes:
        segments = [[]]
        for entry in lane:
            previous = segments[-1][-1][0] if segments[-1] else None
            if previous and (entry[0].cy - previous.cy > max(previous.height, entry[0].height) * 4 or any(
                previous.cy < title.cy < entry[0].cy and _same_column(title, entry[0]) for title in titles
            )):
                segments.append([])
            segments[-1].append(entry)
        for segment in segments:
            if len({family for _, family, _ in segment}) >= 3:
                groups.append(segment)

    # Two label columns can describe the same value column. Only groups with
    # independent value locations can count as separate specifications.
    matches = defaultdict(set)
    suspected = set()
    for left, right in combinations(range(len(groups)), 2):
        left_values = [(family, value) for _, family, value in groups[left] if value is not None]
        right_values = [(family, value) for _, family, value in groups[right] if value is not None]
        if not left_values or not right_values or any(_same_column(a, b) and _same_row(a, b)
                for _, a in left_values for _, b in right_values):
            continue
        shared = {family for family, _ in left_values} & {family for family, _ in right_values}
        if len(shared) >= 3:
            for common in combinations(sorted(shared), 3):
                matches[common].add((left, right))
        elif len({family for _, family, _ in groups[left]} & {family for _, family, _ in groups[right]}) >= 3:
            suspected.update((left, right))
    best = []
    for pairs in matches.values():
        # Count only mutually independent groups that share the same core labels.
        independent = []
        for index in sorted({index for pair in pairs for index in pair}):
            if all((other, index) in pairs for other in independent):
                independent.append(index)
        if len(independent) > len(best):
            best = independent
    if len(best) >= 2:
        return (len(best), _group_region(groups, best, .02), True)
    if suspected:
        return (0, _group_region(groups, suspected, .09), False)
    return None


def _group_region(groups, indexes, padding):
    return _region([box for index in indexes for label, _, value in groups[index]
                    for box in (label, value) if box is not None], padding)


def layout_evidence(blocks):
    """Return page-local evidence, with at most one suspected region per layout."""
    pages = defaultdict(set)
    for item in blocks:
        if box := _text_box(item.get("text"), item.get("position")):
            pages[item["page"]].add(box)
    result = []
    for page, entries in sorted(pages.items()):
        boxes = sorted(entries, key=lambda box: (box.cy, box.x, -box.height, box.text))
        for kind, find, reason in (
            ("rows", _row_evidence, "规格表含多行独立的复合几何尺寸"),
            ("blocks", _block_evidence, "多个独立参数区块包含相同的核心表头及各自数值"),
        ):
            if evidence := find(boxes):
                count, region, strong = evidence
                result.append({"page": page, "kind": kind, "observed_count": count,
                               "region": region, "strong": strong, "reason": reason})
    return result


def reread_region(image, target, directory):
    """One local OCR pass, with crop boxes projected back onto the original page."""
    from PIL import Image, ImageOps
    from .engines.ocr_providers import RapidOcrProvider

    region = target["region"]
    with Image.open(image) as source:
        source = ImageOps.exif_transpose(source)
        width, height = source.size
        x, y = int(region["x"] * width), int(region["y"] * height)
        right = min(width, round((region["x"] + region["width"]) * width))
        bottom = min(height, round((region["y"] + region["height"]) * height))
        if right <= x or bottom <= y:
            return []
        crop_path = directory / "multi_spec_region.png"
        source.crop((x, y, right, bottom)).save(crop_path)
    result = []
    for item in RapidOcrProvider().recognize([crop_path], {})[0]["texts"]:
        rect = _rect(item.get("position"), right - x, bottom - y, center=True)
        if rect:
            position = {"x": (rect["x"] * (right - x) + x) / width,
                        "y": (rect["y"] * (bottom - y) + y) / height,
                        "width": rect["width"] * (right - x) / width,
                        "height": rect["height"] * (bottom - y) / height}
            result.append({"page": target["page"], "text": item.get("text"), "position": position})
    return result
