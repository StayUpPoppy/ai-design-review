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

REPLAY_OPTION = "multi_spec_layout_replay"
VERSION = "multi-spec-layout-replay/v1"
RESPONSE_PATH = "qwen_pages/response.json"


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


def prepare_retry_options(job, run_root):
    """Called under the failed-job row lock, before its error is cleared."""
    options = deepcopy(job.get("options") or {})
    old_replay = options.pop(REPLAY_OPTION, None)
    error = str(job.get("error_message") or "")
    if not any(text in error for text in ("无法确定规格表格/区块布局", "多规格布局字段不兼容")) and not old_replay:
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
        if not decoded.get("multi_spec"):
            return options
        options[REPLAY_OPTION] = {
            "version": VERSION, "layout_rules_version": LAYOUT_RULE_VERSION,
            "response_path": RESPONSE_PATH, "response_sha256": fingerprint(response),
            "drawing_path": options["drawing_path"], "drawing_sha256": fingerprint(drawing),
            "page_count": pages,
            "previous_error": error, "prepared_at": datetime.now(UTC).isoformat(),
        }
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
        return {"raw_response": json.loads(raw_bytes), "metadata": deepcopy(replay)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MultiSpecError("本地恢复失败：已保存响应或原文件缺失、变化或损坏；未重新调用Qwen。") from exc
