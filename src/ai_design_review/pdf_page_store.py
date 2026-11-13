"""Independent page jobs for new PDF uploads; no cross-page engineering inheritance."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from math import isfinite
from pathlib import Path
import re
import shutil
import tempfile

from pypdf import PdfReader, PdfWriter
from pypdf._utils import read_non_whitespace, skip_over_comment
from pypdf.errors import PdfReadError
from pypdf.generic import IndirectObject, NameObject, read_object
from sqlalchemy import select

from .review_persistence import ReviewRecord, RecognitionJobRecord, _apply_summary
from .multi_spec_store import owned, lock, children, VariantStoreError

VERSION = "pdf-pages/v1"
MAX_PAGES = 50
_DUPLICATE_PAGE_MODE = re.compile(r"Multiple definitions in dictionary at byte (0x[0-9a-f]+) for key /PageMode")


def is_source(review):
    return (review or {}).get("source_kind") == "pdf_pages"


def origin(review):
    return (review or {}).get("page_origin") or {}


def _check_pages(reader):
    if reader.is_encrypted:
        raise ValueError("PDF已加密，请先解除加密后上传。")
    count = len(reader.pages)
    if not 1 <= count <= MAX_PAGES:
        raise ValueError(f"PDF共{count}页，每文件支持1至{MAX_PAGES}页；请分批上传。")
    for number, page in enumerate(reader.pages, 1):
        try:
            box = page.mediabox
            valid = all(isfinite(size) and size > 0 for size in (float(box.width), float(box.height)))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError(f"PDF第{number}页无法读取，请检查原文件。") from exc
        if not valid:
            raise ValueError(f"PDF第{number}页的页面尺寸无效，请检查原文件。")


def _repair_catalog_page_mode(reader, error):
    """Blank a duplicate direct catalog preference without shifting xref offsets."""
    match = _DUPLICATE_PAGE_MODE.fullmatch(str(error))
    if not match:
        raise error
    stop = int(match[1], 16)
    root = reader.trailer.raw_get("/Root")
    offset = reader.xref.get(root.generation, {}).get(root.idnum) if isinstance(root, IndirectObject) else None
    if offset is None or offset >= stop:
        raise error
    stream = reader.stream
    stream.seek(offset)
    if reader.read_object_header(stream) != (root.idnum, root.generation):
        raise error
    token = read_non_whitespace(stream)
    if token != b"<" or stream.read(1) != b"<":
        raise error
    seen = False
    while stream.tell() < stop:
        token = read_non_whitespace(stream)
        if token == b"%":
            skip_over_comment(stream)
            continue
        if token != b"/":
            break
        start = stream.tell() - 1
        stream.seek(start)
        key = read_object(stream, reader)
        token = read_non_whitespace(stream)
        while token == b"%":
            skip_over_comment(stream)
            token = read_non_whitespace(stream)
        if not token:
            break
        stream.seek(-1, 1)
        value = read_object(stream, reader)
        if key == "/PageMode" and isinstance(value, NameObject):
            if seen and stream.tell() == stop:
                stream.seek(0)
                data = stream.read()
                return data[:start] + b" " * (stop - start) + data[stop:]
            seen = True
    raise error


def _render_compatible_pdf(path, count):
    from PIL import Image
    from .preprocessing import _render_pdf_uncached

    with tempfile.TemporaryDirectory(prefix="pdf-upload-check-") as folder:
        for page in range(1, count + 1):
            try:
                rendered = _render_pdf_uncached(path, folder, prefix="page", dpi=72, max_side=600, page_number=page)
                with Image.open(rendered[0]) as image:
                    image.load()
            except (OSError, RuntimeError, ValueError, IndexError) as exc:
                raise ValueError(f"PDF第{page}页无法渲染，请检查原文件。") from exc


def inspect_pdf(path):
    try:
        reader = PdfReader(path, strict=True)
        repaired = False
        while True:
            try:
                _check_pages(reader)
                break
            except PdfReadError as error:
                reader = PdfReader(BytesIO(_repair_catalog_page_mode(reader, error)), strict=True)
                repaired = True
        if repaired:
            _render_compatible_pdf(path, len(reader.pages))
        return reader
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF损坏或无法读取，请检查原文件。") from exc


def dispatch(store, job, drawing, run_root, report):
    """Prepare files, then publish all placeholders and queue entries atomically."""
    if not (job.get("options") or {}).get("auto_split_pdf_pages") or drawing.suffix.lower() != ".pdf":
        return None
    reader = inspect_pdf(drawing)
    if len(reader.pages) == 1:
        return None
    source_id, user = job["job_id"], job["owner"]["user_id"]
    directory = Path(run_root) / source_id
    # Replay of a prepared source never rebuilds missing/deleted pages.
    with store._session() as session:
        existing = session.get(ReviewRecord, source_id)
        if existing and is_source(existing.review_snapshot):
            return {"pdf_pages_dispatched": True}
    with tempfile.TemporaryDirectory(prefix=".pdf-pages-", dir=directory) as staging:
        pages = []
        for number, page in enumerate(reader.pages, 1):
            report("splitting_pdf", 5 + int(number / len(reader.pages) * 60))
            page_id = f"page-{number}"
            child_id = hashlib.sha256(f"{source_id}:{VERSION}:{page_id}".encode()).hexdigest()[:24]
            target = Path(staging) / child_id
            path = target / "incoming" / "drawing.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = PdfWriter(); writer.add_page(page)
            with path.open("wb") as stream:
                writer.write(stream)
            pages.append({"page_id": page_id, "variant_id": page_id, "order": number, "page": number, "job_id": child_id})
        report("registering_pages", 80)
        manifest = {"version": VERSION, "pages": pages, "original_filename": job["input_filename"]}
        review = {"record_kind": "source", "source_kind": "pdf_pages", "pdf_pages": manifest,
                  "drawing_summary": {"drawing_name": job["drawing_name"], "spring_type": "compression_spring"}}
        try:
            with lock(source_id), store._session() as session, session.begin():
                task = session.execute(select(RecognitionJobRecord).where(RecognitionJobRecord.job_id == source_id).with_for_update()).scalar_one_or_none()
                if not task or task.status != "processing" or task.worker_id != job.get("worker_id") or task.cancellation_requested:
                    raise RuntimeError("分页任务已取消或租约已变化。")
                if task.lease_expires_at and task.lease_expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
                    raise RuntimeError("分页任务租约已失效。")
                if session.get(ReviewRecord, source_id):
                    return {"pdf_pages_dispatched": True}
                root = store._new_record(source_id, review, file_info=job.get("file_info"), artifact_dir=str(directory), owner=job["owner"])
                session.add(root); session.flush()
                for entry in pages:
                    child_id, number = entry["job_id"], entry["page"]
                    mapping = {"version": VERSION, "source_review_id": source_id, "page_id": entry["page_id"], "original_page": number, "local_page": 1}
                    name = f"{Path(job['input_filename']).stem} · 第{number}页"
                    snapshot = {"record_kind": "variant", "page_origin": mapping, "drawing_summary": {"drawing_name": name}}
                    child_dir = Path(run_root) / child_id
                    incoming = child_dir / "incoming"
                    incoming.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path(staging) / child_id / "incoming" / "drawing.pdf", incoming / "drawing.pdf")
                    record = store._new_record(child_id, snapshot, file_info={"original_page": number, "page_count": 1}, artifact_dir=str(child_dir), owner=job["owner"])
                    session.add(record)
                    options = deepcopy(job["options"])
                    for key in ("candidate_json_path", "ocr_json_path", "multi_spec_layout_replay", "pdf_page_replay"):
                        options.pop(key, None)
                    options.update(drawing_path="incoming/drawing.pdf", auto_split_pdf_pages=False, auto_create_variants=False, page_origin=mapping)
                    session.add(RecognitionJobRecord(job_id=child_id, drawing_name=name, artifact_dir=str(child_dir), input_filename="drawing.pdf", options=options,
                        owner_erp_user_id=record.owner_erp_user_id, owner_username=record.owner_username, owner_real_name=record.owner_real_name,
                        owner_org_id=record.owner_org_id, owner_org_name=record.owner_org_name, status="queued", stage="queued", progress=0))
                session.add(store._make_event(root, revision_before=1, revision_after=1, payload={"event_type": "pdf_pages_registered", "source": VERSION, "metadata": {"pages": deepcopy(pages)}}))
                (directory / "review.json").write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
                (directory / "owner.json").write_text(json.dumps(job["owner"], ensure_ascii=False), encoding="utf-8")
        except Exception:
            # Files are prepared before SQL commit; rollbacks must not leak page copies.
            with lock(source_id), store._session() as session, session.begin():
                current = session.execute(select(RecognitionJobRecord).where(RecognitionJobRecord.job_id == source_id).with_for_update()).scalar_one_or_none()
                for entry in pages:
                    if current and current.worker_id != job.get("worker_id"): continue
                    child_id = entry["job_id"]
                    if session.get(ReviewRecord, child_id) or session.get(RecognitionJobRecord, child_id): continue
                    target = (Path(run_root) / child_id).resolve()
                    target.relative_to(Path(run_root).resolve())
                    if target != Path(run_root).resolve(): shutil.rmtree(target, ignore_errors=True)
            raise
        return {"pdf_pages_dispatched": True}


def complete_page(store, job, result, worker_id):
    mapping = (job.get("options") or {}).get("page_origin")
    if not mapping:
        return None
    review = deepcopy(result.get("review") or {})
    if not review or review.get("record_kind") == "source":
        raise ValueError("本页包含多规格或没有有效识别结果，请将该页单独上传处理。")
    review.update(record_kind="variant", page_origin=deepcopy(mapping))
    # Material code is always manual, never inherited from a model or another page.
    review.setdefault("drawing_summary", {}).pop("material_code", None)
    source_id = mapping["source_review_id"]
    with lock(source_id), store._session() as session, session.begin():
        root = session.execute(select(ReviewRecord).where(ReviewRecord.job_id == source_id).with_for_update()).scalar_one_or_none()
        item = session.get(ReviewRecord, job["job_id"])
        task = session.execute(select(RecognitionJobRecord).where(RecognitionJobRecord.job_id == job["job_id"]).with_for_update()).scalar_one_or_none()
        if not root or not item or not task or task.worker_id != worker_id or task.status != "processing" or task.cancellation_requested:
            return False
        if task.lease_expires_at and task.lease_expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
            return False
        if not review["drawing_summary"].get("drawing_name"):
            review["drawing_summary"]["drawing_name"] = item.drawing_name
        item.review_snapshot = review; _apply_summary(item, review)
        directory = Path(item.artifact_dir)
        metadata = directory / "file_info.json"
        if metadata.is_file(): item.file_info = json.loads(metadata.read_text(encoding="utf-8"))
        if directory.is_dir(): (directory / "review.json").write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        item.revision += 1
        session.add(store._make_event(item, revision_before=item.revision-1, revision_after=item.revision,
            payload={"event_type": "pdf_page_recognized", "source": VERSION, "metadata": mapping}))
        task.status = task.stage = "completed"; task.progress = 100; task.error_message = None
        task.completed_at = task.updated_at = datetime.now(UTC); task.lease_expires_at = None
    return True


def describe(store, source_id, user):
    with store._session() as session:
        root = owned(session, source_id, user)
        if not is_source(root.review_snapshot):
            return None
        manifest = root.review_snapshot["pdf_pages"]
        records = {row.variant_id: row for row in children(session, source_id)}
        tasks = {row.job_id: row for row in session.execute(select(RecognitionJobRecord).where(RecognitionJobRecord.job_id.in_([e["job_id"] for e in manifest["pages"]]))).scalars()}
        values = []
        for entry in manifest["pages"]:
            item = records.get(entry["page_id"]); task = tasks.get(entry["job_id"])
            summary = (item.review_snapshot.get("drawing_summary") or {}) if item else {}
            value = {"variant_id": entry["page_id"], "order": entry["page"], "page": entry["page"], "code": f"第{entry['page']}页", "parameters": {}, "region": None,
                "creation_status": "created" if item else "deleted", "issues": [task.error_message] if task and task.error_message else [], "drawing_summary": deepcopy(summary)}
            value["review"] = store._serialize_review_list_item(item) if item else None
            if item and task:
                status = store._serialize_recognition_job(task)
                value["review"].update(recognition_status=status["status"], recognition_progress=status["progress"], recognition_stage=status["stage"],
                    recognition_error=status["error_message"], recognition_attempt_count=status["attempt_count"], updated_at=status["updated_at"])
            values.append(value)
        return {"source_id": source_id, "source_kind": "pdf_pages", "source_revision": root.revision, "drawing_summary": deepcopy(root.review_snapshot["drawing_summary"]),
            "creation_mode": "auto", "variants": values, "created_count": len(records)}


def aggregate(description):
    entries = [v["review"] for v in description["variants"] if v["review"]]
    statuses = [r.get("recognition_status", "queued") for r in entries]
    complete = statuses.count("completed"); failed = statuses.count("failed")
    running = any(s not in {"completed", "failed", "cancelled"} for s in statuses)
    status = "processing" if running else "failed" if failed else "completed"
    progress = int(sum(100 if r.get("recognition_status") in {"completed", "failed"} else min(99, r.get("recognition_progress") or 0) for r in entries) / max(1, len(entries)))
    signature = "|".join(f"{r['job_id']}:{r.get('recognition_status')}:{r.get('recognition_progress')}:{r.get('recognition_attempt_count')}:{r.get('revision')}" for r in entries)
    return {"source_kind": "pdf_pages", "record_kind": "source", "creation_mode": "auto", "variant_count": len(description["variants"]),
        "created_count": len(entries), "completed_count": complete, "failed_count": failed, "page_state_revision": signature,
        "recognition_status": status, "recognition_stage": "recognizing_pages" if running else status, "recognition_progress": min(99, progress) if running else 100,
        "recognition_error": f"{failed}页识别失败，可打开页面清单重试失败页。" if failed else None,
        "page_results": deepcopy(entries), "updated_at": max((r.get("updated_at") or "" for r in entries), default="")}


def delete_family(store, job_id, user, expected_revision):
    with store._session() as session:
        item = owned(session, job_id, user); source_id = origin(item.review_snapshot).get("source_review_id") or item.job_id
    with lock(source_id), store._session() as session, session.begin():
        root = owned(session, source_id, user, write=True)
        item = root if job_id == source_id else owned(session, job_id, user, write=True)
        group = item is root
        if group and expected_revision != root.revision:
            raise VariantStoreError(409, "来源组已变化，请刷新后重新确认删除。")
        targets = [*children(session, source_id), root] if group else [item]
        paths, ids, pending = [], [], False
        for target in targets:
            ids.append(target.job_id)
            task = session.execute(select(RecognitionJobRecord).where(RecognitionJobRecord.job_id == target.job_id).with_for_update()).scalar_one_or_none()
            if task and task.status in {"processing", "cancel_requested"}:
                task.status = task.stage = "cancel_requested"; task.cancellation_requested = True; pending = True
            else:
                if task: session.delete(task)
                paths.append(target.artifact_dir)
            session.delete(target)
        if group and pending:
            # Worker cleans the original only after all page cancellations finish.
            paths = [p for p in paths if p != root.artifact_dir]
            Path(root.artifact_dir, "pdf_delete_pending.json").write_text(json.dumps({"children": [p["job_id"] for p in root.review_snapshot["pdf_pages"]["pages"]]}), encoding="utf-8")
        if not group:
            root.revision += 1
        session.flush()
        return {"paths": paths, "deleted_ids": ids, "cancelling": pending}


def cleanup_cancelled_source(store, job, run_root):
    mapping = (job.get("options") or {}).get("page_origin") or {}
    source_id = mapping.get("source_review_id") or job.get("job_id")
    if not source_id:
        return
    directory = (Path(run_root) / source_id).resolve(); directory.relative_to(Path(run_root).resolve())
    marker = directory / "pdf_delete_pending.json"
    if not marker.is_file(): return
    with lock(source_id), store._session() as session:
        ids = json.loads(marker.read_text(encoding="utf-8"))["children"]
        active = session.execute(select(RecognitionJobRecord.job_id).where(RecognitionJobRecord.job_id.in_(ids))).first()
        if not active and not session.get(ReviewRecord, source_id): shutil.rmtree(directory)


def reap_cancelled(store, run_root):
    """Finish PDF deletion after a worker crash, once its lease has expired."""
    with store._session() as session:
        records = session.execute(select(RecognitionJobRecord).where(
            RecognitionJobRecord.status == "cancelled", RecognitionJobRecord.cancellation_requested.is_(True))).scalars().all()
        jobs = [{**store._serialize_recognition_job(r, include_execution_details=True)} for r in records
                if (r.options or {}).get("page_origin") or (Path(r.artifact_dir) / "pdf_delete_pending.json").is_file()]
    for job in jobs:
        directory = store.finalize_cancelled_recognition_job(job["job_id"], worker_id=job["worker_id"])
        if not directory: continue
        path = Path(directory).resolve(); path.relative_to(Path(run_root).resolve())
        if path == Path(run_root).resolve(): raise ValueError("Unsafe page cleanup path")
        if not (path / "pdf_delete_pending.json").is_file(): shutil.rmtree(path, ignore_errors=True)
        cleanup_cancelled_source(store, job, run_root)
