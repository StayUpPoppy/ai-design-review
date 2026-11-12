"""Fingerprint-bound replay for explicit retries of layout-only failures."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .engines.qwen_vision_adapter import QwenVisionEngine, QwenVisionError
from .multi_spec import MultiSpecError, LAYOUT_RULE_VERSION
from .multi_spec_layout import layout_blocks, layout_evidence

REPLAY_OPTION = "multi_spec_layout_replay"
VERSION = "multi-spec-layout-replay/v1"
RESPONSE_PATH = "qwen_pages/response.json"
OCR_SNAPSHOT_PATH = "candidates.json"
OCR_GUARD_ERROR = "已停止单规格OCR兜底"


def _inside(directory, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Invalid replay path")
    path = (directory / relative).resolve()
    path.relative_to(directory.resolve())
    if not path.is_file():
        raise ValueError("Replay file missing")
    return path


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _layout_snapshot(content, response):
    snapshot = json.loads(content)
    payloads = snapshot.get("raw_payloads")
    candidates = snapshot.get("candidates")
    if not isinstance(candidates, list) or not isinstance(payloads, dict) or not all(
        isinstance(item, dict) for item in [*candidates, *payloads.values()]
    ) or payloads.get("qwen_vision", {}).get("raw") != response:
        raise ValueError("OCR snapshot does not match the saved Qwen response")
    return snapshot


def _snapshot_frames(directory, payloads):
    for payload in payloads.values():
        for page in payload.get("raw_pages", payload.get("pages", [])) or []:
            if not isinstance(page, dict) or not page.get("texts") or not page.get("image_path"):
                continue
            yield Path(page["image_path"]).resolve().relative_to(directory.resolve()).as_posix()


def prepare_retry_options(job, run_root):
    """Called under the failed-job row lock, before its error is cleared."""
    options = deepcopy(job.get("options") or {})
    old_replay = options.pop(REPLAY_OPTION, None)
    error = str(job.get("error_message") or "")
    if "识别结果未列全" in error:
        return options
    page_retry = bool(options.get("page_origin"))
    legacy_guard = OCR_GUARD_ERROR in error or isinstance(old_replay, dict) and old_replay.get("ocr_snapshot")
    if not (page_retry or legacy_guard or old_replay or any(text in error for text in ("无法确定规格表格/区块布局", "多规格布局字段不兼容"))):
        return options
    try:
        directory = (Path(run_root) / job["job_id"]).resolve()
        directory.relative_to(Path(run_root).resolve())
        if directory != Path(job["artifact_dir"]).resolve():
            return options
        response = _inside(directory, RESPONSE_PATH)
        drawing = _inside(directory, options.get("drawing_path"))
        raw = json.loads(response.read_bytes())
        pages = len(PdfReader(str(drawing)).pages) if drawing.suffix.lower() == ".pdf" else 1
        decoded = QwenVisionEngine().parse_response(raw, [], total_pages=pages)
        snapshot_meta = None
        if legacy_guard and not decoded.get("multi_spec") and decoded.get("candidates"):
            diagnostic = json.loads(_inside(directory, "multi_spec_diagnostics.json").read_bytes())
            if diagnostic.get("kind") not in {"rows", "blocks"} or diagnostic.get("layout_rules_version") == LAYOUT_RULE_VERSION:
                return options
            content = _inside(directory, OCR_SNAPSHOT_PATH).read_bytes()
            snapshot = _layout_snapshot(content, raw)
            payloads = snapshot["raw_payloads"]
            frames = {path: fingerprint(_inside(directory, path)) for path in set(_snapshot_frames(directory, payloads))}
            blocks = layout_blocks(payloads, page_count=pages)
            if not blocks or any(item["strong"] for item in layout_evidence(blocks + layout_blocks({}, drawing, pages))):
                return options
            snapshot_meta = {"sha256": hashlib.sha256(content).hexdigest(), "frames": frames}
        if not (decoded.get("multi_spec") or snapshot_meta or page_retry and decoded.get("candidates")):
            return options
        options[REPLAY_OPTION] = {
            "version": VERSION, "layout_rules_version": LAYOUT_RULE_VERSION,
            "response_path": RESPONSE_PATH, "response_sha256": fingerprint(response),
            "drawing_path": options["drawing_path"], "drawing_sha256": fingerprint(drawing),
            "page_count": pages, "page_retry": page_retry,
            "previous_error": error, "prepared_at": datetime.now(UTC).isoformat(),
        }
        if snapshot_meta:
            options[REPLAY_OPTION]["ocr_snapshot"] = snapshot_meta
    except (OSError, ValueError, PyPdfError, QwenVisionError, KeyError, TypeError, IndexError, AttributeError):
        # No valid saved result: the user's explicit retry keeps its old path.
        return options
    return options


def load_replay(job, directory):
    """A queued replay never falls back to another paid request on failure."""
    options = job.get("options") or {}
    replay = options.get(REPLAY_OPTION)
    if not replay:
        return None
    try:
        if not isinstance(replay, dict) or replay.get("version") != VERSION:
            raise ValueError("Invalid replay version")
        if replay.get("drawing_path") != options.get("drawing_path") or replay.get("response_path") != RESPONSE_PATH:
            raise ValueError("Replay input changed")
        response = _inside(directory, replay["response_path"])
        drawing = _inside(directory, replay["drawing_path"])
        raw_bytes = response.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != replay["response_sha256"] or fingerprint(drawing) != replay["drawing_sha256"]:
            raise ValueError("Replay fingerprint changed")
        raw = json.loads(raw_bytes)
        result = {"raw_response": raw, "metadata": deepcopy(replay)}
        if snapshot_meta := replay.get("ocr_snapshot"):
            content = _inside(directory, OCR_SNAPSHOT_PATH).read_bytes()
            if hashlib.sha256(content).hexdigest() != snapshot_meta["sha256"]:
                raise ValueError("OCR snapshot changed")
            snapshot = _layout_snapshot(content, raw)
            frames = snapshot_meta["frames"]
            if set(frames) != set(_snapshot_frames(directory, snapshot["raw_payloads"])) or any(
                fingerprint(_inside(directory, path)) != digest for path, digest in frames.items()
            ):
                raise ValueError("OCR frame changed")
            result["ocr_snapshot"] = snapshot
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MultiSpecError("本地恢复失败：已保存响应或原文件缺失、变化或损坏；未重新调用Qwen。") from exc
