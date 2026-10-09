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
    r"端部|端圈|并紧|闭口|开口|end", r"磨平|磨削|不磨|grind|ground",
)
RECOGNIZED_SOURCES = ("qwen", "ocr", "werk24", "geometry", "dimension_role", "pdf_text")


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


def _rect(position: Any, width: float, height: float) -> dict[str, float] | None:
    if not isinstance(position, dict):
        return None
    try:
        x, y, w, h = (float(position[key]) for key in ("x", "y", "width", "height"))
        if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
            return None
        if position.get("coordinate_type") not in {"normalized", "relative"}:
            x, w, y, h = x / width, w / width, y / height, h / height
        if x < 0 or y < 0 or x + w > 1.01 or y + h > 1.01:
            return None
        return {"x": x, "y": y, "width": min(w, 1 - x), "height": min(h, 1 - y)}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
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
                    blocks.append({"page": index + 1, "text": " ".join(w[4] for w in words),
                                   "position": position, "source": "pdf_text"})
    return blocks


def ocr_blocks(raw_payloads: dict[str, Any], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
            except (KeyError, OSError, TypeError):
                continue
            for item in raw_page.get("texts", []) or []:
                position = _rect(item.get("position"), width, height)
                if position:
                    blocks.append({"page": raw_page["page"], "text": item.get("text", ""),
                                   "position": position, "source": "ocr"})
    return blocks


def _value_matches(value: Any, text: str, field: str) -> bool:
    if value in (None, "") or isinstance(value, bool):
        return False
    if field == "handedness":
        value = {"right": "右旋", "left": "左旋"}.get(str(value), str(value))
    if field == "end_grinding":
        return bool(re.search(r"不磨|未磨" if "不磨" in str(value) else r"磨平|磨削|ground", text, re.I))
    if field == "end_type":
        return bool(re.search(r"不并紧|开口" if "不并紧" in str(value) else r"(?<!不)并紧|闭口", text))
    try:
        number = float(value)
        if not math.isfinite(number):
            return False
        # Digits in dimension identifiers (D2, H0, n1) are not their values.
        # Ra commonly touches the number in OCR; separate that known prefix.
        numeric_text = re.sub(r"\bRa(?=\d)", "Ra ", text, flags=re.I)
        return any(abs(float(match) - number) < 1e-8 for match in re.findall(r"(?<![a-zA-Z\d_.])-?\d+(?:\.\d+)?(?![\d.])", numeric_text))
    except (TypeError, ValueError):
        return _normal(value) in _normal(text)


def locate_fields(review: dict[str, Any], candidates: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = review.get("spring_parameters") or {}
    annotations = []
    for index, field in enumerate(FIELDS):
        param = params.get(field) or {}
        sources = param.get("source") or []
        sources = sources if isinstance(sources, list) else [sources]
        edited = any(s in {"human_edited", "manual"} for s in sources)
        roughness_conflict = field == "surface_roughness_ra" and bool(param.get("roughness_conflict"))
        originals = [c for c in candidates if c.get("field") == field and _recognized(c) and c.get("value") not in (None, "")]
        if not edited:
            matching = [c for c in originals if c.get("value") == param.get("value")]
            originals = matching or originals
        original = max(originals, key=lambda c: float(c.get("confidence") or 0), default=None)
        if original is None and _recognized(param) and not edited and not any("formula" in str(s) for s in sources):
            original = param
        if roughness_conflict:
            original = None
        empty = not original and param.get("value") in (None, "") and not param.get("evidence")
        value = original.get("value") if original else None
        evidence = str((original or {}).get("evidence") or "")
        matches = []
        for block in blocks:
            text = block["text"]
            if not original or not _value_matches(value, text, field):
                continue
            # Surface symbols cannot establish dimensional identity.
            if field in {"wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length"} and re.search(r"粗糙|\bra\b|▽|√", text, re.I):
                continue
            direct = bool(re.search(PATTERNS[index], text, re.I))
            supported = bool(re.search(PATTERNS[index], evidence, re.I))
            if direct or supported or field in {"material", "standard_no", "handedness"}:
                matches.append((4 if direct else 2, block))
        # Explicit textual identity wins. Bare numbers need a unique field-specific
        # evidence match; repeated ambiguous dimensions remain unplaced.
        best = max((score for score, _ in matches), default=0)
        winners = [block for score, block in matches if score == best]
        unique = {}
        for block in winners:
            pos = block["position"]
            key = (block["page"], round(pos["x"], 3), round(pos["y"], 3))
            unique.setdefault(key, block)
        winners = list(unique.values())
        if len(winners) > 1 and field != "surface_roughness_ra":
            winners = []
        locations = []
        for n, block in enumerate(winners):
            box = block["position"]
            locations.append({"location_id": f"{field}-{n + 1}", "page": block["page"], "bbox": box,
                              "anchor": {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2},
                              "bubble": {"x": min(.98, box["x"] + box["width"] + .025), "y": max(.02, box["y"] - .025)},
                              "source": block["source"], "evidence": block["text"]})
        annotations.append({"annotation_id": field, "field": field, "number": index + 1, "label": LABELS[index],
                            "original_value": value, "evidence": evidence, "locations": locations,
                            "status": "located" if locations else "empty" if empty else "unlocated",
                            "reason": "" if locations else ("粗糙度存在不同候选，请先核对并人工定位" if roughness_conflict else "未找到可靠原图位置" if original else "此值没有原图直接标注，可人工定位")})
    return annotations


def build_annotations(review: dict[str, Any], job_dir: Path, url_for: Callable[[Path], str],
                      *, candidates_payload: dict[str, Any] | None = None, allow_ocr: bool = True) -> dict[str, Any]:
    pages = preview_manifest(job_dir, url_for)
    sources = sorted((job_dir / "inputs").glob("*"))
    source = next((p for p in sources if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}), None)
    digest = hashlib.sha256()
    if source:
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    digest.update(json.dumps([(p["page"], p["width"], p["height"], p["image_url"]) for p in pages]).encode())
    document = {"schema_version": "original_annotations/v1", "source_document_id": digest.hexdigest(),
                "annotation_revision": 1, "pages": pages, "annotations": [], "warnings": []}
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
    blocks.extend(ocr_blocks(payload.get("raw_payloads") or {}, eligible))
    document["annotations"] = locate_fields(review, candidates, blocks)
    missing = any(a["status"] == "unlocated" and a["original_value"] is not None for a in document["annotations"])
    if allow_ocr and missing and eligible and not any(b["source"] == "ocr" for b in blocks):
        try:
            from .engines.ocr_providers import RapidOcrProvider
            # Reuse canonical PNGs; their coordinates belong to the displayed pages.
            paths = sorted([p for p in (job_dir / "pages").glob("*") if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}], key=page_sort_key)[:len(eligible)]
            raw_pages = RapidOcrProvider().recognize(paths, {})
            blocks.extend(ocr_blocks({"local": {"raw_pages": raw_pages}}, eligible))
            document["annotations"] = locate_fields(review, candidates, blocks)
        except Exception:
            document["warnings"].append("本地OCR定位不可用，可使用调整标注人工定位。")
    # Spread labels sharing one requirement text box without moving their anchors.
    occupied: dict[int, list[dict[str, float]]] = {}
    for annotation in document["annotations"]:
        for location in annotation["locations"]:
            points = occupied.setdefault(location["page"], [])
            bubble = location["bubble"]
            for _ in range(20):
                if all(math.hypot(bubble["x"] - p["x"], bubble["y"] - p["y"]) >= .045 for p in points):
                    break
                bubble["y"] = bubble["y"] + .045 if bubble["y"] < .93 else .03
            points.append(dict(bubble))
    return document


class AnnotationConflictError(ValueError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("标注已在其他页面更新，请选择保留的位置。")
        self.current = current


def apply_annotation_patch(document: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    if body.get("source_document_id") != document["source_document_id"]:
        raise AnnotationConflictError(document)
    revision = body.get("expected_annotation_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("expected_annotation_revision 必须为正整数。")
    if revision != document["annotation_revision"]:
        raise AnnotationConflictError(document)
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
    return result


@contextmanager
def annotation_file_lock(job_dir: Path):
    """OS lock works across API processes; parameter JSON never writes this sidecar."""
    path = job_dir / "annotations.lock"
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
