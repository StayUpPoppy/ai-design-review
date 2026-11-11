"""Fast read metadata and lease/CAS protected local verification jobs."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import threading
import time
import logging

from sqlalchemy import select
from .review_persistence import ReviewRecord, RecognitionJobRecord, _apply_summary
from .page_images import read_json, write_json, fingerprint

VERSION='review-local/v3-load-diameter'
KIND='local_verification'


def task_id(job_id, revision):
    return 'local_'+hashlib.sha256(f'{job_id}:{revision}:{VERSION}'.encode()).hexdigest()[:32]


def enqueue(store, stored, owner):
    review=stored['review']
    if review.get('record_kind')=='source' or review.get('local_verification',{}).get('version')==VERSION: return None
    id=task_id(stored['job_id'],stored['revision'])
    with store._session() as session, session.begin():
        # Lock the order first; deletion and verification use the same order.
        row=session.execute(select(ReviewRecord).where(ReviewRecord.job_id==stored['job_id']).with_for_update()).scalar_one_or_none()
        if not row or row.owner_erp_user_id!=owner.user_id or row.revision!=stored['revision']: return None
        existing=session.get(RecognitionJobRecord,id)
        if existing: return existing.status
        main=session.get(RecognitionJobRecord,row.job_id)
        if main and main.status!='completed':return None
        session.add(RecognitionJobRecord(job_id=id,drawing_name=row.drawing_name,artifact_dir=row.artifact_dir,
            options={'task_kind':KIND,'review_id':row.job_id,'expected_review_revision':row.revision,'verification_version':VERSION},
            owner_erp_user_id=row.owner_erp_user_id,owner_username=row.owner_username,owner_real_name=row.owner_real_name,
            owner_org_id=row.owner_org_id,owner_org_name=row.owner_org_name,status='queued',stage='queued',progress=0))
    return 'queued'


def metadata(store, stored):
    review=stored['review'];ann=review.get('drawing_annotations') or {}
    root=Path(stored['artifact_dir']) if stored.get('artifact_dir') else None
    images=read_json(root/'pages/.page_metadata.json') if root else {}
    version=hashlib.sha256(json.dumps(images,sort_keys=True).encode()).hexdigest() if images else 'legacy'
    state='completed'
    if review.get('record_kind')!='source' and review.get('local_verification',{}).get('version')!=VERSION:
        with store._session() as session:
            task=session.get(RecognitionJobRecord,task_id(stored['job_id'],stored['revision']))
            state=task.status if task else 'not_scheduled'
    return {'job_id':stored['job_id'],'review_revision':stored['revision'],'annotation_revision':ann.get('annotation_revision',0),
        'source_document_id':ann.get('source_document_id'),'preview_version':version,'verification_state':state}


def prepare_preview(directory, review):
    from .api import _make_preview_images, _artifact_url
    from .drawing_annotations import annotation_source, preview_manifest
    source=next((p for p in (directory/'inputs').glob('*') if p.suffix.lower() in {'.pdf','.png','.jpg','.jpeg','.webp','.bmp','.tiff','.tif'}),None)
    if not source:return
    # Record the old coordinate frame before changing derived image sizes/URLs.
    ann=review.get('drawing_annotations') or {}
    old_id=ann.get('source_document_id') or annotation_source(directory,lambda p:_artifact_url(directory.name,p))[0]['source_document_id']
    write_json(directory/'preview_transform.json',{'source_sha256':fingerprint(source),'source_document_id':old_id})
    _make_preview_images(source,directory/'pages',[])
    if ann:
        # Only page-image metadata changes; normalized anchors remain untouched.
        ann['pages']=preview_manifest(directory,lambda p:_artifact_url(directory.name,p))


def execute(store, job, worker_id, run_root, report):
    from . import api
    from .identity import IdentityContext
    from .drawing_annotations import build_annotations, merge_annotation_upgrade
    options=job['options'];id=options['review_id'];owner=job['owner']
    phase_started = time.perf_counter()
    original_report = report
    def report(stage, progress):
        nonlocal phase_started
        now = time.perf_counter()
        logging.getLogger(__name__).info('Local verification review=%s phase=%s previous_phase_ms=%.1f', id, stage, (now-phase_started)*1000)
        phase_started = now
        original_report(stage, progress)
    identity=IdentityContext(user_id=owner['user_id'],username=owner['username'],real_name=owner.get('real_name') or owner['username'],
        org_id=owner.get('org_id') or '',org_name=owner.get('org_name') or '',source='local_verification')
    stored=store.get_review(id,owner_user_id=identity.user_id)
    if not stored or stored['revision']!=options['expected_review_revision']:return False
    directory=Path(run_root)/id;before=stored['review'];report('preparing_preview',10)
    prepare_preview(directory,before)
    report('local_verification',35)
    review,_=api._load_persisted_review(id,directory/'review.json',identity,recover=True)
    current=before.get('drawing_annotations')
    if current:review['drawing_annotations']=current
    report('local_annotations',75)
    rebuilt=build_annotations(review,directory,lambda p:api._artifact_url(id,p)) if (review.get('drawing_summary') or {}).get('spring_type')=='compression_spring' else None
    if rebuilt: review['drawing_annotations']=merge_annotation_upgrade(current,rebuilt) if current else rebuilt
    for adjustment in (review.get('automatic_calculation_adjustments') or {}).values():
        if isinstance(adjustment,dict):adjustment.update(pending_save=False,audit_recorded=True)
    for key in ('pitch_recovery','multi_spec_reconciliation','load_point_recovery','load_height_adjustment'):
        if isinstance(review.get(key),dict):review[key].update(pending_save=False,audit_recorded=True)
    for field in ('surface_roughness_ra', 'support_coils'):
        parameter = (review.get('spring_parameters') or {}).get(field) or {}
        for key in ('roughness_verification_adjustment', 'support_coils_adjustment'):
            if isinstance(parameter.get(key), dict):
                parameter[key].update(pending_save=False, audit_recorded=True)
    review['local_verification']={'version':VERSION,'completed_at':datetime.now(UTC).isoformat()}
    report('saving_local_verification',95)
    with store._session() as session,session.begin():
        row=session.execute(select(ReviewRecord).where(ReviewRecord.job_id==id).with_for_update()).scalar_one_or_none()
        task=session.execute(select(RecognitionJobRecord).where(RecognitionJobRecord.job_id==job['job_id']).with_for_update()).scalar_one_or_none()
        if not row or row.revision!=options['expected_review_revision'] or not task or task.worker_id!=worker_id or task.status!='processing' or task.cancellation_requested:return False
        if task.lease_expires_at and task.lease_expires_at.replace(tzinfo=UTC)<=datetime.now(UTC):return False
        latest=row.review_snapshot.get('drawing_annotations')
        if latest and review.get('drawing_annotations'):review['drawing_annotations']=merge_annotation_upgrade(latest,review['drawing_annotations'])
        row.review_snapshot=deepcopy(review);row.revision+=1;_apply_summary(row,review)
        session.add(store._make_event(row,revision_before=row.revision-1,revision_after=row.revision,
            payload={'event_type':'local_verification_completed','source':VERSION,'metadata':{'task_id':job['job_id']},'before_state':{'spring_parameters':before.get('spring_parameters')},'after_state':{'spring_parameters':review.get('spring_parameters')}}))
    return True


_readiness_cache = {}
_readiness_lock = threading.RLock()

def cached_readiness(job_id, revision, identity, review):
    from .generation_readiness import assess_generation_readiness
    from .diameter_evidence import ROLE_STATE_VERSION
    from .io_utils import project_path
    from .material_catalog import load_material_catalog
    versions = (project_path('config/factory_rules.json').stat().st_mtime_ns, load_material_catalog()['version'], ROLE_STATE_VERSION)
    signature=hashlib.sha256(json.dumps([review.get(k) for k in ('spring_parameters','technical_requirements','technical_output_deletions','spring_features','generation_settings','diameter_role_candidates')],sort_keys=True,default=str).encode()).hexdigest()
    key=(job_id,revision,identity.user_id,versions,signature)
    if revision is not None:
        with _readiness_lock:
            if key in _readiness_cache:return deepcopy(_readiness_cache[key])
    value=assess_generation_readiness(review)
    if revision is not None:
        with _readiness_lock:
            if len(_readiness_cache)>=128:_readiness_cache.pop(next(iter(_readiness_cache)))
            _readiness_cache[key]=deepcopy(value)
    return value
