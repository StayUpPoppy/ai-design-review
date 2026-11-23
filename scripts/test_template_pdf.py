"""Offline coverage of fixed-template PDF data, layout, API and ownership."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
from xml.etree import ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review
from fastapi.testclient import TestClient
from ai_design_review.review_persistence import ReviewPersistence, PersistenceError
from ai_design_review.template_pdf import build_snapshot, readiness, resource_status, resources
from ai_design_review.template_pdf_store import TemplatePdfStore
from ai_design_review.generation_readiness import assess_generation_readiness
from sqlalchemy import inspect
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
NS={'s':'http://www.w3.org/2000/svg'}


def fixture():
    review=ready_review()
    review['generation_settings']={'username':''}
    review['drawing_summary'].update(drawing_name='中文弹簧 & 试样',material_code='0012 003',company_name='不作为客户显示')
    return review


def main():
    if not resource_status()['available']:
        raise SystemExit('Install the private template resource bundle before running this integration test.')
    review=fixture()
    result,snapshot=readiness(review)
    assert result['readiness']['status'] in ('ready','ready_with_warnings'),result
    data=snapshot['template_data']
    assert data['product_name']=='中文弹簧 & 试样' and data['part_number']=='0012 003'
    assert data['customer_name']==data['drawing_date']==data['designer_name']==''
    assert data['technical_requirements']==result['technical_requirements_projection']['text']
    assert 'YKZZ' not in json.dumps(data)
    deleted=deepcopy(review)
    entry=next(e for e in snapshot['technical_requirements_projection']['entries'] if e['source_key']=='auto:coils')
    deleted['technical_output_deletions']=[deepcopy({key:entry[key] for key in ['source_key','fields','load_point_ids','basis']})]
    deleted_snapshot=build_snapshot(deleted)
    assert entry['body'] not in deleted_snapshot['template_data']['technical_requirements']
    assert deleted_snapshot['template_data']['technical_requirements']==deleted_snapshot['technical_requirements_projection']['text']
    converted=deepcopy(review)
    for field in ['wire_diameter','outer_diameter','free_length','pitch','solid_height']:
        converted['spring_parameters'][field]['value']/=10
        converted['spring_parameters'][field]['unit']='cm'
    for point in converted['spring_parameters']['load_points']:
        point.update(height=point['height']/10,height_unit='cm',force=point['force']/1000,force_unit='kN')
    metric=build_snapshot(converted)['template_data']
    assert all(metric[key]==data[key] for key in ['wire_diameter','outer_diameter','free_length','pitch','solid_height','height1','height2','load1','load2','solid_load'])
    open_ends=deepcopy(review)
    open_ends['spring_parameters'].pop('active_coils')
    open_ends['spring_parameters'].pop('end_type')
    open_ends['spring_parameters']['end_coils_closed']={'value':0,'need_human_review':False}
    assert readiness(open_ends)[0]['readiness']['status'] in ('ready','ready_with_warnings')
    svg,pdf=resources().render(data)
    assert len(pymupdf.open(stream=pdf,filetype='pdf'))==1
    nodes=ET.fromstring(svg).findall('.//s:text[@data-field]',NS)
    assert all('0012 003' in (e.text or '') for e in nodes if e.get('data-field')=='part_number')
    changed=deepcopy(review)
    changed['spring_parameters']['load_points'][1].update(label='P7',height_label='H9')
    renamed=build_snapshot(changed)['template_data']
    assert renamed['load1_label']=='P7' and renamed['height1_label']=='H9'
    text=resources().fill(renamed).decode()
    assert 'P7=' in text and '高度 H9' in text
    changed['spring_parameters']['load_points'][1].pop('height_label')
    assert build_snapshot(changed)['template_data']['height1_label']=='H7'
    for point in changed['spring_parameters']['load_points']:
        point['load_role']='unknown'
    assert any('角色' in i['reason'] for i in readiness(changed)[0]['readiness']['blocking_reasonableness'])
    signed=deepcopy(review)
    signed['spring_parameters']['load_points'][1].update(height_tolerance_upper=1,height_tolerance_lower=.5)
    assert assess_generation_readiness(deepcopy(signed))['status'] not in ('ready','ready_with_warnings')
    assert readiness(signed)[0]['readiness']['status'] in ('ready','ready_with_warnings')
    assert build_snapshot(signed)['template_data']['height1_tolerance']=='+1/+0.5'
    no_points=deepcopy(review);no_points['spring_parameters']['load_points']=[]
    unused=readiness(no_points)
    assert unused[0]['readiness']['status'] in ('ready','ready_with_warnings')
    assert all(unused[1]['template_data'][key]=='' for key in ['load1','load2','solid_load','load1_label','load2_label','solid_load_label'])
    unconfirmed=deepcopy(review);unconfirmed['spring_parameters']['material']['need_human_review']=True
    assert build_snapshot(unconfirmed)['template_data']['spring_rate']==''
    empty_name=deepcopy(review);empty_name['generation_settings']={}
    assert readiness(empty_name)[0]['readiness']['status'] in ('ready','ready_with_warnings')
    composite=resources().render({**data,'product_name':'Café & Ø ± 中文','designer_name':'张三'})[1]
    assert pymupdf.open(stream=composite,filetype='pdf')[0].get_images()==[]
    try: resources().fill({**data,'product_name':'测试🧬'})
    except ValueError as exc: assert exc.field=='product_name'
    else: raise AssertionError('Unsupported glyph must identify its field')
    for missing in ['wire_diameter','handedness']:
        invalid=deepcopy(review);invalid['spring_parameters'].pop(missing)
        assert readiness(invalid)[0]['readiness']['status'] not in ('ready','ready_with_warnings')
    closed=deepcopy(review);closed['spring_parameters'].pop('active_coils')
    assert readiness(closed)[0]['readiness']['status'] not in ('ready','ready_with_warnings')
    overflow=deepcopy(review)
    point=deepcopy(overflow['spring_parameters']['load_points'][0]);point.update(label='F3',height_label='H3')
    overflow['spring_parameters']['load_points'].append(point)
    assert any('最多' in i['reason'] for i in readiness(overflow)[0]['readiness']['blocking_reasonableness'])
    for field,value in [('product_name','产品'*100),('technical_requirements','要求\n'*100),('designer_name','很长的名字'*20)]:
        invalid={**data,field:value}
        try: resources().fill(invalid)
        except ValueError: pass
        else: raise AssertionError('Expected overflow: '+field)
    assert resources().fill({**data,'part_number':'','technical_requirements':''}).count(b'YKZZ')==0
    print('PASS mapping, explicit blanks, core validation, actual labels, overflow and vector rendering',flush=True)

    with tempfile.TemporaryDirectory(prefix='template-pdf-test-') as directory:
        tmp=Path(directory)
        repository=ReviewPersistence(f'sqlite+pysqlite:///{tmp / "test.db"}')
        repository.create_schema_for_testing()
        previous_repository,previous_runs=api.REVIEW_PERSISTENCE,api.API_RUN_ROOT
        api.REVIEW_PERSISTENCE,api.API_RUN_ROOT=repository,tmp/'runs'
        api.API_RUN_ROOT.mkdir()
        repository.create_review('pdf-order',review,owner=OWNER)
        try:
            with TestClient(api.app) as client:
                base='/api/reviews/pdf-order'
                assert client.get(base+'/template-pdf-readiness').status_code==200
                body={'expected_review_revision':1,'idempotency_key':'first-request'}
                created=client.post(base+'/template-pdfs',json=body)
                assert created.status_code==201,created.text
                row=created.json()['template_pdf'];pdf_id=row['pdf_id']
                duplicate=client.post(base+'/template-pdfs',json=body)
                assert duplicate.status_code==200 and duplicate.json()['template_pdf']['pdf_id']==pdf_id
                mismatch=client.post(base+'/template-pdfs',json={**body,'expected_review_revision':2})
                assert mismatch.status_code==409
                stale=client.post(base+'/template-pdfs',json={'expected_review_revision':99,'idempotency_key':'stale'})
                assert stale.status_code==409
                file=client.get(row['inline_url'])
                assert file.status_code==200 and file.content.startswith(b'%PDF') and 'inline' in file.headers['content-disposition']
                original_hash=hashlib.sha256(file.content).hexdigest()
                assert client.get(base+'/template-pdfs').json()['template_pdfs'][0]['pdf_id']==pdf_id
                captured=TemplatePdfStore(repository).get(pdf_id,OWNER['user_id'])
                assert captured['template_data']==data and captured['technical_requirements_text']==data['technical_requirements']
                old_user=os.environ['AI_REVIEW_MOCK_USER_ID']
                os.environ['AI_REVIEW_MOCK_USER_ID']='other-pdf-user'
                try:
                    assert client.get(row['url']).status_code==404
                    assert client.get(base+'/template-pdfs').status_code in (403,404)
                    assert client.post(base+'/template-pdfs',json=body).status_code in (403,404)
                finally:os.environ['AI_REVIEW_MOCK_USER_ID']=old_user
                old_root=os.environ.get('PDF_TEMPLATE_ROOT')
                os.environ['PDF_TEMPLATE_ROOT']=str(tmp/'missing-assets')
                try:
                    unavailable=client.get(base+'/template-pdf-readiness').json()
                    assert unavailable['resources']['available'] is False
                    assert unavailable['technical_requirements_projection']['text']==data['technical_requirements']
                    assert client.post(base+'/template-pdfs',json={**body,'idempotency_key':'missing'}).status_code==503
                    assert client.get(row['url']).status_code==200
                finally:
                    if old_root is None:os.environ.pop('PDF_TEMPLATE_ROOT',None)
                    else:os.environ['PDF_TEMPLATE_ROOT']=old_root
                original_create=TemplatePdfStore.create
                TemplatePdfStore.create=lambda *args,**kwargs:(_ for _ in ()).throw(PersistenceError('simulated'))
                try:
                    failed=client.post(base+'/template-pdfs',json={**body,'idempotency_key':'failed-store'})
                    assert failed.status_code==503
                    assert len(list((api.API_RUN_ROOT/'pdf-order/template_pdf').iterdir()))==1
                finally:TemplatePdfStore.create=original_create
                revised=deepcopy(review);revised['drawing_summary']['drawing_name']='第二版弹簧'
                saved=client.patch(base,json={'review':revised,'expected_revision':1})
                assert saved.status_code==200,saved.text
                revision=saved.json()['review_revision']
                second=client.post(base+'/template-pdfs',json={'expected_review_revision':revision,'idempotency_key':'second'})
                assert second.status_code==201,second.text
                assert len(client.get(base+'/template-pdfs').json()['template_pdfs'])==2
                assert hashlib.sha256(client.get(row['url']).content).hexdigest()==original_hash
                # Keep one real output for visual QA; it contains only synthetic fixture data.
                qa=ROOT/'outputs/template-pdf-qa';qa.mkdir(parents=True,exist_ok=True)
                (qa/'integration-example.pdf').write_bytes(client.get(second.json()['template_pdf']['url']).content)
                deleted=client.delete(base)
                assert deleted.status_code==200,deleted.text
                assert not (api.API_RUN_ROOT/'pdf-order').exists()
                assert TemplatePdfStore(repository).get(pdf_id,OWNER['user_id']) is None
                assert client.get(row['url']).status_code==404
                # A missing migration disables new generation without breaking the text projection.
                from ai_design_review.template_pdf_store import TemplatePdfRecord
                repository.create_review('migration-order',review,owner=OWNER)
                TemplatePdfRecord.__table__.drop(repository._engine)
                migration_base='/api/reviews/migration-order'
                blocked=client.get(migration_base+'/template-pdf-readiness').json()
                assert blocked['readiness']['status']=='blocked'
                assert blocked['technical_requirements_projection']['text']==data['technical_requirements']
                assert client.get(migration_base+'/template-pdfs').status_code==503
                # Exercise the actual migration against the disposable database.
                import importlib.util
                from alembic.migration import MigrationContext
                from alembic.operations import Operations
                spec=importlib.util.spec_from_file_location('pdf_migration',ROOT/'migrations/versions/20261122_01_template_pdf_drawings.py')
                migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
                with repository._engine.begin() as connection:
                    with Operations.context(MigrationContext.configure(connection)):
                        migration.upgrade()
                assert 'template_pdf_drawings' in inspect(repository._engine).get_table_names()
                assert client.get(migration_base+'/template-pdf-readiness').json()['readiness']['status'] in ('ready','ready_with_warnings')
                print('PASS API persistence, idempotency, conflicts, isolation, missing resources, failure cleanup, frozen history and deletion',flush=True)
        finally:
            api.REVIEW_PERSISTENCE,api.API_RUN_ROOT=previous_repository,previous_runs
            repository.dispose()


if __name__=='__main__':main()
