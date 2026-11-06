"""Offline page fan-out/worker/API acceptance using the real six-page PDF."""
from copy import deepcopy
from pathlib import Path
import asyncio
import io
import sys
import tempfile
from unittest.mock import patch
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review, create_request
from fastapi.testclient import TestClient
from ai_design_review import recognition_worker as workers, pdf_page_store as pages
from ai_design_review.review_persistence import ReviewPersistence, ReviewRecord, RecognitionJobRecord
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command

PDF = Path('C:/Users/29580/Desktop/扫描全能王 2024-09-09 10.38.pdf')

def pdf_bytes(count, encrypted=False):
    writer=PdfWriter()
    for _ in range(count): writer.add_blank_page(width=600, height=800)
    if encrypted: writer.encrypt('secret')
    stream=io.BytesIO();writer.write(stream);return stream.getvalue()

def main():
    import logging
    logging.getLogger("ai_design_review.recognition_worker").setLevel(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);repo=ReviewPersistence(f'sqlite+pysqlite:///{root/"pages.db"}');repo.create_schema_for_testing()
        worker=workers.RecognitionWorker();worker.worker_id='pdf-qa'
        with patch.object(api,'REVIEW_PERSISTENCE',repo), patch.object(api,'API_RUN_ROOT',root), \
             patch.object(workers,'REVIEW_PERSISTENCE',repo), patch.object(workers,'API_RUN_ROOT',root), \
             patch('ai_design_review.engines.qwen_vision_adapter.QwenVisionEngine._call_qwen',side_effect=AssertionError('No cloud calls')), TestClient(api.app) as client:
            def upload(data, name='drawings.pdf'):
                r=client.post('/api/reviews',files={'drawing':(name,data,'application/pdf')},data={'use_qwen':'false'})
                assert r.status_code==202,r.text
                return r.json()['job_id']
            source=upload(PDF.read_bytes() if PDF.is_file() else pdf_bytes(6))
            task=repo.claim_next_recognition_job(worker.worker_id)
            worker._process_job(task)
            data=client.get(f'/api/reviews/{source}/variants').json()
            assert data['source_kind']=='pdf_pages' and len(data['variants'])==6,data
            ids=[v['review']['job_id'] for v in data['variants']]
            assert len(set(ids))==6
            assert repo.get_recognition_job(source)['status']=='completed','Preparation releases its worker'
            assert client.get(f'/api/reviews/{source}/recognition-status').json()['recognition']['status']=='processing'
            assert len(client.get('/api/reviews?root_only=true&limit=100').json()['reviews'])==1
            assert client.get(f'/api/reviews/{ids[3]}').status_code==409
            assert repo.get_review(ids[3],owner_user_id='other-user') is None
            actual=PdfReader(PDF) if PDF.is_file() else PdfReader(io.BytesIO(pdf_bytes(6)))
            for i,child in enumerate(ids):
                saved=PdfReader(root/child/'incoming/drawing.pdf')
                assert len(saved.pages)==1 and saved.pages[0].rotation==actual.pages[i].rotation
                assert saved.pages[0].mediabox==actual.pages[i].mediabox
            import os
            if PDF.is_file() and not os.environ.get("PDF_TEST_SKIP_RENDER"):
                from ai_design_review.preprocessing import render_pdf_with_pdftoppm
                import hashlib
                hashes=[]
                for child in ids:
                    image=render_pdf_with_pdftoppm(root/child/'incoming/drawing.pdf',root/child/'preview-qa',dpi=60,first_page_only=True)[0]
                    hashes.append(hashlib.sha256(Path(image).read_bytes()).hexdigest())
                assert len(set(hashes))==6, 'All original pages including 4–6 render independently'
            # Replay the preparation job: never duplicate or resurrect pages.
            assert asyncio.run(api.run_recognition_job_record(task))['pdf_pages_dispatched']
            assert pages.describe(repo,source,OWNER['user_id'])['created_count']==6
            executed=[]
            async def execute(**kwargs):
                child=kwargs['job_id'];executed.append(child)
                assert len(PdfReader(kwargs['drawing'].file).pages)==1
                if child==ids[1] and executed.count(child)==1: raise RuntimeError('offline page failure')
                review=ready_review();review['drawing_summary'].update(drawing_name=f'已识别第{ids.index(child)+1}张',drawing_no=f'00{ids.index(child)+1}')
                review['technical_requirements']=[]
                for value in review['spring_parameters'].values():
                    if isinstance(value,dict): value['need_human_review']=True
                return {'review':review}
            with patch.object(api,'run_recognition_execution',execute):
                for i in range(6):
                    claimed=repo.claim_next_recognition_job(worker.worker_id);assert claimed['job_id']==ids[i]
                    worker._process_job(claimed)
                    if i==0:
                        assert repo.get_review(ids[0],owner_user_id=OWNER['user_id'])['review']['drawing_summary']['drawing_no']=='001'
                        assert client.get(f'/api/reviews/{source}/recognition-status').json()['recognition']['status']=='processing'
                status=client.get(f'/api/reviews/{source}/recognition-status').json()['recognition']
                assert status['status']=='failed' and status['completed_count']==5 and status['failed_count']==1,status
                assert client.post(f'/api/reviews/{ids[1]}/retry').status_code==202
                claimed=repo.claim_next_recognition_job(worker.worker_id);assert claimed['job_id']==ids[1];worker._process_job(claimed)
                assert executed.count(ids[0])==1 and executed.count(ids[1])==2
            status=client.get(f'/api/reviews/{source}/recognition-status').json()['recognition'];assert status['status']=='completed'
            for i,child in enumerate(ids):
                review=repo.get_review(child,owner_user_id=OWNER['user_id'])['review']
                assert review['page_origin']['original_page']==i+1 and review['page_origin']['local_page']==1
                assert review['drawing_summary']['drawing_no']==f'00{i+1}'
            # Child deletion keeps the source and all other pages, even after redelivery.
            assert client.delete(f'/api/reviews/{ids[0]}').status_code==200
            assert (root/source/'incoming/drawings.pdf').exists()
            assert asyncio.run(api.run_recognition_job_record(task))['pdf_pages_dispatched']
            assert pages.describe(repo,source,OWNER['user_id'])['variants'][0]['creation_status']=='deleted'
            # Pending group deletion cancels only live tasks; completed pages clean immediately.
            group=upload(pdf_bytes(2));worker._process_job(repo.claim_next_recognition_job(worker.worker_id))
            desc=pages.describe(repo,group,OWNER['user_id']); active=repo.claim_next_recognition_job(worker.worker_id)
            result=client.delete(f'/api/reviews/{group}?expected_source_revision=1');assert result.status_code==200,result.text
            assert result.json()['status']=='cancelling' and (root/group/'incoming/drawings.pdf').exists()
            worker._process_job(active)
            assert not (root/group).exists() and not repo.get_review(active['job_id'],owner_user_id=OWNER['user_id'])
            # Publishing failure rolls back every placeholder/task and cleans prepared copies.
            broken=upload(pdf_bytes(2));claimed=repo.claim_next_recognition_job(worker.worker_id)
            original=repo._new_record;counter=[]
            def fail_publish(*args,**kwargs):
                counter.append(1)
                if len(counter)==3: raise RuntimeError('injected SQL publication failure')
                return original(*args,**kwargs)
            with patch.object(repo,'_new_record',side_effect=fail_publish): worker._process_job(claimed)
            assert repo.get_recognition_job(broken)['status']=='failed'
            assert repo.get_review(broken,owner_user_id=OWNER['user_id']) is None
            assert client.post(f'/api/reviews/{broken}/retry').status_code==202
            worker._process_job(repo.claim_next_recognition_job(worker.worker_id))
            assert pages.describe(repo,broken,OWNER['user_id'])['created_count']==2
            client.delete(f'/api/reviews/{broken}?expected_source_revision=1')
            # Saved single-page model responses are parsed locally and fingerprint-bound on retry.
            from ai_design_review.multi_spec_replay import prepare_retry_options, load_replay, REPLAY_OPTION
            import json
            cached=root/ids[1]/'qwen_pages/response.json';cached.parent.mkdir(exist_ok=True)
            raw={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'document_mode':'single','parameters':{'wire_diameter':{'value':1.6,'unit':'mm'}}})}}]}
            cached.write_text(json.dumps(raw),encoding='utf-8')
            with repo._session() as session:
                record=session.get(RecognitionJobRecord,ids[1]);job=repo._serialize_recognition_job(record,include_execution_details=True)
            options=prepare_retry_options({**job,'error_message':'local postprocess failure'},root)
            assert options[REPLAY_OPTION]['page_retry'] is True
            assert load_replay({**job,'options':options},root/ids[1])['metadata']['page_count']==1
            cached.write_text('{}',encoding='utf-8')
            try: load_replay({**job,'options':options},root/ids[1])
            except ValueError: pass
            else: raise AssertionError('Changed cache must not trigger a cloud fallback')
            # Limits/encryption/corruption fail atomically; no partial children.
            for payload in [pdf_bytes(51),pdf_bytes(2,True),b'%PDF-broken']:
                bad=upload(payload);worker._process_job(repo.claim_next_recognition_job(worker.worker_id))
                assert repo.get_recognition_job(bad)['status']=='failed'
                assert repo.get_review(bad,owner_user_id=OWNER['user_id']) is None
            large=upload(pdf_bytes(50));worker._process_job(repo.claim_next_recognition_job(worker.worker_id))
            assert pages.describe(repo,large,OWNER['user_id'])['created_count']==50
            client.delete(f'/api/reviews/{large}?expected_source_revision=1')
            # Single-page uploads retain the normal recognition path.
            one=upload(pdf_bytes(1));claimed=repo.claim_next_recognition_job(worker.worker_id)
            with patch.object(api,'run_recognition_execution',return_value={'review':ready_review()}) as execution:
                result=asyncio.run(api.run_recognition_job_record(claimed));assert execution.call_count==1 and not result.get('pdf_pages_dispatched')
            repo.complete_recognition_job(one,worker_id=worker.worker_id)
            # Material code: strings, explicit clear, validation, package snapshot and old retry isolation.
            review=ready_review();repo.create_review('material',review,owner=OWNER)
            for value in [' 00123 ', 'YB156b7509', 'AB-01  02', '']:
                stored=repo.get_review('material',owner_user_id=OWNER['user_id']);review=stored['review'];review['drawing_summary']['material_code']=value
                response=client.patch('/api/reviews/material',json={'review':review,'expected_revision':stored['revision']})
                assert response.status_code==200,response.text
                saved=repo.get_review('material',owner_user_id=OWNER['user_id'])['review']
                package=build_generation_parameter_package(saved);assert package['source']['material_code']==(value.strip() or None)
                command=build_solidworks_command('1234567890',package,saved);assert command['models'][0]['materialCode']==(value.strip() or None)
            # Freeze material codes in actual mock-SW tasks; later edits cannot change them.
            from ai_design_review.generation_persistence import GenerationStore
            submissions=[]
            with patch.object(api, '_post_solidworks_command', side_effect=lambda url,payload,**kw: submissions.append(deepcopy(payload))):
                stored=repo.get_review('material',owner_user_id=OWNER['user_id'])
                request={**create_request('material-empty'), 'expected_review_revision':stored['revision']}
                first=client.post('/api/reviews/material/generation-jobs',json=request)
                assert first.status_code==202,first.text
                assert submissions[-1]['models'][0]['materialCode'] is None
                review=stored['review'];review['drawing_summary']['material_code']='00123'
                response=client.patch('/api/reviews/material',json={'review':review,'expected_revision':stored['revision']});assert response.status_code==200,response.text
                second=client.post('/api/reviews/material/generation-jobs',json={**create_request('material-code'), 'expected_review_revision':response.json()['review_revision']})
                assert second.status_code==202,second.text
                assert submissions[-1]['models'][0]['materialCode']=='00123'
                assert first.json()['generation_job']['parameter_hash']!=second.json()['generation_job']['parameter_hash']
                frozen=GenerationStore(repo).get_job(first.json()['generation_job']['generation_id'],owner_user_id=OWNER['user_id'])
                assert frozen['execution_options']['solidworks_payload']['models'][0]['materialCode'] is None
                assert client.post('/api/reviews/material/generation-jobs',json={**request,'expected_review_revision':response.json()['review_revision']}).status_code==409
            for invalid in ['X'*257,123]:
                stored=repo.get_review('material',owner_user_id=OWNER['user_id']);stored['review']['drawing_summary']['material_code']=invalid
                assert client.patch('/api/reviews/material',json={'review':stored['review'],'expected_revision':stored['revision']}).status_code==422
        repo.dispose()
    print('PASS real six pages, independent jobs 4–6/local page1, partial success, per-page retry, no duplicate/resurrection, 50-page limit, cancellation/deletion, ownership, single-page compatibility and material-code save/SW')

if __name__=='__main__': main()
