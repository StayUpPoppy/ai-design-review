"""Transactional multi-spec persistence; shared source files are never child-owned."""
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import threading
import uuid

from sqlalchemy import select

from .review_persistence import ReviewRecord, ReviewChangeEvent, RecognitionJobRecord, _record_matches_owner
from .multi_spec import child_review, fingerprint, MultiSpecError

_locks = {}
_guard = threading.Lock()


class VariantStoreError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def lock(source_id):
    with _guard: return _locks.setdefault(source_id, threading.RLock())


def owned(session, source_id, user, *, write=False):
    query = select(ReviewRecord).where(ReviewRecord.job_id == source_id)
    record = session.execute(query.with_for_update() if write else query).scalar_one_or_none()
    if record is None or not _record_matches_owner(record, user): raise VariantStoreError(404, "审图记录不存在。")
    return record


def children(session, source_id):
    return session.execute(select(ReviewRecord).where(ReviewRecord.parent_review_id == source_id)).scalars().all()


def creation_receipts(session, source_id):
    return session.execute(select(ReviewChangeEvent).where(
        ReviewChangeEvent.review_job_id == source_id, ReviewChangeEvent.event_type == "variants_created")).scalars().all()


def previously_created(receipts):
    return {value["variant_id"] for event in receipts
            for value in ((event.event_metadata or {}).get("result") or {}).get("reviews", []) if value.get("variant_id")}


def describe(store, source_id, user):
    with store._session() as session:
        root = owned(session, source_id, user)
        if root.record_kind != "source": raise VariantStoreError(409, "此记录不是多规格来源。")
        existing = {v.variant_id: v for v in children(session, source_id)}
        multi = root.review_snapshot["multi_spec"]
        ever_created = previously_created(creation_receipts(session, source_id))
        from .multi_spec_evidence import resolve
        evidence=resolve(root.review_snapshot,Path(root.artifact_dir)) if root.artifact_dir else {}
        result = []
        for candidate in multi["variants"]:
            value = {k: deepcopy(candidate.get(k)) for k in ("variant_id", "order", "code", "page", "region", "issues", "source_context", "reference_values")}
            value["parameters"] = {**deepcopy(multi["common"].get("parameters") or {}), **deepcopy(candidate.get("parameters") or {})}
            entry=evidence.get("variants",{}).get(candidate["variant_id"],{})
            if evidence:
                value.update(model_region=value.get("region"),region=entry.get("region"),region_verification=entry.get("status","unverified"))
                from .multi_spec_evidence import apply_parameters
                value["parameters"]=apply_parameters(value["parameters"],entry)
            child = existing.get(candidate["variant_id"])
            value["review"] = store._serialize_review_list_item(child) if child else None
            value["creation_status"] = "created" if child else "deleted" if candidate["variant_id"] in ever_created else "not_created"
            result.append(value)
        return {"source_id": source_id, "source_revision": root.revision, "drawing_summary": deepcopy(root.review_snapshot["drawing_summary"]),
                "variants": result, "created_count": len(existing), "creation_mode": multi.get("creation_mode", "manual")}


def materialize(store, job_id, user, run_root):
    from .multi_spec import link_assets
    with store._session() as read_session:
        item = owned(read_session, job_id, user)
        if item.record_kind != "variant": return
        source_id = item.parent_review_id
    with lock(source_id), store._session() as session:
        source = owned(session, source_id, user, write=True)
        item = owned(session, job_id, user)
        target = run_root / job_id
        if not (target / "candidates.json").exists():
            candidate = next(v for v in source.review_snapshot["multi_spec"]["variants"] if v["variant_id"] == item.variant_id)
            from .multi_spec_evidence import resolve
            evidence=resolve(source.review_snapshot,Path(source.artifact_dir))
            _, candidates = child_review(source.review_snapshot, candidate, source_id,evidence=evidence)
            link_assets(Path(source.artifact_dir), target, candidates)


def create_children(store, source_id, user, body, actor, run_root):
    expected = body.get("expected_source_revision")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1: raise VariantStoreError(422, "来源修订无效。")
    ids = body.get("variant_ids")
    key = body.get("idempotency_key")
    if not isinstance(ids, list) or not ids or len(ids) > 50 or any(not isinstance(v, str) for v in ids) or len(set(ids)) != len(ids):
        raise VariantStoreError(422, "请选择1至50个不同规格。")
    if not isinstance(key, str) or not key.strip() or len(key) > 128: raise VariantStoreError(422, "建单幂等键无效。")
    from .multi_spec_evidence import resolve
    with store._session() as session:
        source=owned(session,source_id,user)
        evidence=resolve(source.review_snapshot,Path(source.artifact_dir)) if source.artifact_dir else {}
    with lock(source_id), store._session() as session, session.begin():
        root = owned(session, source_id, user, write=True)
        if root.record_kind != "source": raise VariantStoreError(409, "此记录不是多规格来源。")
        job = session.get(RecognitionJobRecord, source_id)
        if job and job.status != "completed": raise VariantStoreError(409, "来源识别尚未完成或正在删除。")
        receipts = creation_receipts(session, source_id)
        for event in receipts:
            metadata = event.event_metadata or {}
            if metadata.get("idempotency_key") == key:
                if metadata.get("fingerprint") != fingerprint(ids): raise VariantStoreError(409, "同一幂等键不能用于不同选择。")
                result = deepcopy(metadata["result"])
                for value in result["reviews"]: value["deleted"] = not value.get("job_id") or session.get(ReviewRecord, value["job_id"]) is None
                return result
        if body.get("expected_source_revision") != root.revision: raise VariantStoreError(409, "来源版本已变化，请刷新规格清单。")
        available = {v["variant_id"]: v for v in root.review_snapshot["multi_spec"]["variants"]}
        if any(v not in available for v in ids): raise VariantStoreError(422, "选择包含无效规格。")
        return _write_children(store, session, root, ids, key, actor, run_root, evidence=evidence)


def _write_children(store, session, root, ids, key, actor, run_root, *, evidence=None, prepared=None, automatic=False):
    """One writer for manual legacy creation and the worker's atomic completion."""
    source_id = root.job_id
    existing = {v.variant_id: v for v in children(session, source_id)}
    available = {v["variant_id"]: v for v in root.review_snapshot["multi_spec"]["variants"]}
    deleted = previously_created(creation_receipts(session, source_id)) - existing.keys() if automatic else set()
    result, created = {"source_id": source_id, "reviews": []}, []
    owner = {"user_id": root.owner_erp_user_id, "username": root.owner_username, "real_name": root.owner_real_name,
             "org_id": root.owner_org_id, "org_name": root.owner_org_name}
    for variant_id in ids:
        if variant_id in deleted:
            result["reviews"].append({"variant_id": variant_id, "deleted": True})
            continue
        record = existing.get(variant_id)
        if record is None:
            review = prepared[variant_id] if prepared is not None else child_review(root.review_snapshot, available[variant_id], source_id, evidence=evidence)[0]
            child_id = uuid.uuid4().hex[:12]
            record = store._new_record(child_id, review, file_info=root.file_info, artifact_dir=str(run_root / child_id), owner=owner)
            session.add(record)
            created.append(record)
            session.add(store._make_event(record, revision_before=0, revision_after=1, payload={"event_type": "variant_review_created", "actor": actor,
                "source": "multi_spec_auto" if automatic else "multi_spec", "metadata": {"source_id": source_id, "variant_id": variant_id}}))
        result["reviews"].append({"job_id": record.job_id, "variant_id": variant_id, "drawing_name": record.drawing_name, "existing": variant_id in existing})
    before = root.revision
    root.revision += 1
    snapshot = deepcopy(root.review_snapshot)
    snapshot["multi_spec"]["created_count"] = len(existing) + len(created)
    if automatic:
        snapshot["multi_spec"]["creation_mode"] = "auto"
    root.review_snapshot, root.updated_at = snapshot, datetime.now(UTC)
    result["source_revision"] = root.revision
    session.add(store._make_event(root, revision_before=before, revision_after=root.revision,
        payload={"event_type": "variants_created", "actor": actor, "source": "multi_spec_auto" if automatic else "multi_spec",
                 "metadata": {"idempotency_key": key, "fingerprint": fingerprint(ids), "result": deepcopy(result)}}))
    session.flush()
    return result


def _current_worker(job, worker_id):
    expiry = job.lease_expires_at if job else None
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return bool(job and job.worker_id == worker_id and job.status == "processing" and not job.cancellation_requested
                and expiry is not None and expiry > datetime.now(UTC))


def complete_automatic(store, source_id, user, worker_id, actor, run_root, progress):
    """Return None for ordinary/legacy jobs; otherwise atomically finish all specs.

    Expensive local fusion runs before locks. The final transaction locks the
    source before its task, matching deletion; no public endpoint bypasses the
    completed-job check. The deterministic receipt survives worker redelivery.
    """
    with store._session() as session:
        job = session.get(RecognitionJobRecord, source_id)
        if not job or not (job.options or {}).get("auto_create_variants"):
            return None
        if not _current_worker(job, worker_id):
            return False
        root = owned(session, source_id, user)
        if root.record_kind != "source":
            return None
        snapshot, revision, directory = deepcopy(root.review_snapshot), root.revision, root.artifact_dir
        existing = {v.variant_id for v in children(session, source_id)}
        ever_created = previously_created(creation_receipts(session, source_id))
    variants = snapshot["multi_spec"]["variants"]
    if not 1 <= len(variants) <= 50:
        raise MultiSpecError("创建规格审图失败：规格数量必须为1至50。")
    from .multi_spec_evidence import resolve
    progress("creating_variant_reviews", 96)
    evidence = resolve(snapshot, Path(directory)) if directory else {}
    prepared = {}
    for index, candidate in enumerate(variants):
        variant_id = candidate["variant_id"]
        if variant_id not in existing and variant_id not in ever_created:
            prepared[variant_id] = child_review(snapshot, candidate, source_id, evidence=evidence)[0]
        progress("creating_variant_reviews", 96 + (index + 1) * 3 // len(variants))
    ids = [v["variant_id"] for v in variants]
    key = f"auto-specs-v1:{source_id}"
    with lock(source_id), store._session() as session, session.begin():
        root = owned(session, source_id, user, write=True)
        job = session.execute(select(RecognitionJobRecord).where(RecognitionJobRecord.job_id == source_id).with_for_update()).scalar_one_or_none()
        if not _current_worker(job, worker_id):
            return False
        receipt = next((e for e in creation_receipts(session, source_id) if (e.event_metadata or {}).get("idempotency_key") == key), None)
        if receipt is not None:
            if receipt.event_metadata.get("fingerprint") != fingerprint(ids):
                raise VariantStoreError(409, "创建规格审图失败：来源规格已变化。")
        else:
            if root.revision != revision:
                raise VariantStoreError(409, "创建规格审图失败：来源版本已变化，请重试。")
            _write_children(store, session, root, ids, key, actor, run_root, prepared=prepared, automatic=True)
        job.status = job.stage = "completed"
        job.progress, job.error_message = 100, None
        job.completed_at = job.updated_at = datetime.now(UTC)
        job.lease_expires_at = None
    return True


def delete_family(store, job_id, user, expected_revision=None):
    with store._session() as read_session:
        item = owned(read_session, job_id, user)
        source_id = item.parent_review_id or item.job_id
    with lock(source_id), store._session() as session, session.begin():
        root = owned(session, source_id, user, write=True)
        item = root if job_id == source_id else owned(session, job_id, user, write=True)
        group = item.record_kind == "source"
        all_children = children(session, source_id)
        if group and expected_revision != root.revision: raise VariantStoreError(409, "来源组已变化，请刷新后重新确认删除。")
        targets = [*all_children, root] if group else [item]
        if len(targets) - int(group) > 100: raise VariantStoreError(422, "一次最多删除100条实际审图记录。")
        paths, ids, cancelling = [], [], False
        for target in targets:
            ids.append(target.job_id)
            job = session.get(RecognitionJobRecord, target.job_id)
            if job and job.status in {"processing", "cancel_requested"}:
                job.cancellation_requested = True; job.status = job.stage = "cancel_requested"; cancelling = True
            else:
                if job: session.delete(job)
                paths.append(target.artifact_dir)
            session.delete(target)
        if not group:
            before = root.revision; root.revision += 1
            snapshot = deepcopy(root.review_snapshot); snapshot["multi_spec"]["created_count"] = max(0, len(all_children)-1); root.review_snapshot = snapshot
            session.add(store._make_event(root, revision_before=before, revision_after=root.revision, payload={"event_type": "variant_review_deleted", "source": "multi_spec", "metadata": {"job_id": job_id, "variant_id": item.variant_id}}))
        session.flush()
        return {"deleted_ids": ids, "paths": paths, "cancelling": cancelling}
