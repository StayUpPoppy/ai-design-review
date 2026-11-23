"""Offline coverage of fixed-template PDF data, layout, API and ownership."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import shutil
import re
from xml.etree import ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review
from fastapi.testclient import TestClient
from ai_design_review.review_persistence import ReviewPersistence, PersistenceError
from ai_design_review.template_pdf import build_snapshot, readiness, resource_status, resources, resource_root, weight_number
from ai_design_review.template_pdf_store import TemplatePdfStore
from ai_design_review.generation_readiness import assess_generation_readiness
from sqlalchemy import inspect
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
NS={'s':'http://www.w3.org/2000/svg'}


def fixture():
    review=ready_review()
    review['generation_settings']={'username':''}
    review['drawing_summary'].update(drawing_name='中文弹簧 & 试样',drawing_no='KH-0009 A',material_code='0012 003',company_name='不作为客户显示')
    review['spring_parameters']['perpendicularity']={'value':.25,'unit':'mm','need_human_review':False,'source':['manual']}
    return review


def complex_fixture():
    review=fixture();parameters=review['spring_parameters']
    parameters['wire_diameter'].update(tolerance_upper=.03,tolerance_lower=-.02)
    parameters['outer_diameter'].update(tolerance_upper=.2,tolerance_lower=-.1)
    parameters['free_length'].update(tolerance_upper=.5,tolerance_lower=-.25)
    parameters['pitch'].update(tolerance_upper=.1,tolerance_lower=-.1)
    parameters['load_points'][1].update(label='P7',height_label='H9',height_tolerance_upper=.2,height_tolerance_lower=-.1,load_tolerance_percent=10)
    parameters['load_points'][2].update(label='P4',height_label='H8',height_tolerance_upper=.4,height_tolerance_lower=.2,load_tolerance_percent_upper=8,load_tolerance_percent_lower=-5)
    parameters['load_points'][0].update(height_tolerance_upper=.3,height_tolerance_lower=-.1,load_tolerance_upper=5,load_tolerance_lower=2)
    return review


def verify_layout(pdf):
    layout=resources().manifest['layout_checks']['revision_table']
    scale=72/25.4
    with pymupdf.open(stream=pdf,filetype='pdf') as document:
        horizontal=[]
        for drawing in document[0].get_drawings():
            for item in drawing['items']:
                if item[0]!='l':continue
                a,b=item[1:]
                if abs(a.y-b.y)<.01 and abs(min(a.x,b.x)/scale-layout['left_mm'])<.02 and abs(max(a.x,b.x)/scale-layout['right_mm'])<.02:
                    horizontal.append(a.y/scale)
        assert len(horizontal)==2,horizontal
        assert any(abs(y-layout['header_bottom_y_mm'])<.02 for y in horizontal)
        assert any(abs(y-layout['new_bottom_y_mm'])<.02 for y in horizontal)
        assert not any(abs(y-layout['old_bottom_y_mm'])<.02 for y in horizontal)
        left,top,right,bottom=resources().manifest['layout_checks']['calculation_table_mm']
        rows=set()
        for drawing in document[0].get_drawings():
            for item in drawing['items']:
                if item[0]=='l':
                    a,b=item[1:]
                    if abs(a.y-b.y)<.01 and abs(min(a.x,b.x)/scale-left)<.02 and abs(max(a.x,b.x)/scale-right)<.02 and top-.02<=a.y/scale<=bottom+.02:
                        rows.add(round(a.y/scale,2))
        assert rows=={round(top+7*i,2) for i in range(5)},rows
        assert abs(bottom-top-28)<.001


def main():
    if not resource_status()['available']:
        raise SystemExit('Install the private template resource bundle before running this integration test.')
    review=fixture()
    result,snapshot=readiness(review)
    assert result['readiness']['status'] in ('ready','ready_with_warnings'),result
    data=snapshot['template_data']
    assert data['product_name']=='中文弹簧 & 试样' and data['material_code']=='0012 003' and data['customer_code']=='KH-0009 A'
    assert snapshot['schema_version']=='template_pdf_parameters/v3' and 'part_number' not in data
    assert resources().keys==set(data) and resources().manifest['mapping_version']==3
    assert data['weight_kg']=='0.046' and snapshot['calculation_snapshot']['metrics']['unit_mass']['value']!=.046
    for value,expected in [(.0456137,'0.046'),(1.2,'1.2'),(1.2345,'1.235'),(.0005,'0.001'),(.0004999,'<0.001'),(.00000012345678,'<0.001')]:
        assert weight_number(value)==expected
    for invalid_weight in [None,True,float('nan'),float('inf'),-1,0]:assert weight_number(invalid_weight)==''
    for source_key,blank_key,retained_key in [('drawing_no','customer_code','material_code'),('material_code','material_code','customer_code')]:
        independently_blank=deepcopy(review);independently_blank['drawing_summary'][source_key]=''
        blank_data=build_snapshot(independently_blank)['template_data']
        assert blank_data[blank_key]=='' and blank_data[retained_key]==data[retained_key]
    special=deepcopy(review);special['drawing_summary'].update(drawing_no='0001 A & 客户',material_code='0002 B <内部>')
    special_data=build_snapshot(special)['template_data']
    assert special_data['customer_code']=='0001 A & 客户' and special_data['material_code']=='0002 B <内部>'
    assert ET.fromstring(resources().fill(special_data)) is not None
    unconfirmed_perp=deepcopy(review);unconfirmed_perp['spring_parameters']['perpendicularity']['need_human_review']=True
    assert build_snapshot(unconfirmed_perp)['template_data']['perpendicularity']==''
    assert data['designer_name']=='' and 'customer_name' not in data and 'drawing_date' not in data
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
    assert all(metric[key]==data[key] for key in ['wire_diameter','outer_diameter','free_length','pitch','solid_height','height1','height2','load1','load2','solid_load','weight_kg'])
    open_ends=deepcopy(review)
    open_ends['spring_parameters'].pop('active_coils')
    open_ends['spring_parameters'].pop('end_type')
    open_ends['spring_parameters']['end_coils_closed']={'value':0,'need_human_review':False}
    assert readiness(open_ends)[0]['readiness']['status'] in ('ready','ready_with_warnings')
    svg,pdf=resources().render(data)
    verify_layout(pdf)
    assert len(pymupdf.open(stream=pdf,filetype='pdf'))==1
    svg_root=ET.fromstring(svg)
    nodes=svg_root.findall('.//s:text[@data-field]',NS)
    assert svg_root.find(".//s:g[@id='material-label']",NS).get('data-text')=='材料牌号'
    assert svg_root.find(".//s:g[@id='part-number-label']",NS).get('data-text')=='客户编码'
    assert next(e for e in nodes if e.get('data-field')=='material_code').text=='0012 003'
    assert next(e for e in nodes if e.get('data-field')=='customer_code').text=='KH-0009 A'
    assert [e.text for e in nodes if e.get('data-field')=='perpendicularity']==['0.25']
    assert [e.text for e in nodes if e.get('data-field')=='surface_roughness_ra']==['12.5','12.5']
    assert svg_root.find(".//s:g[@id='added-labels']",NS) is None
    assert 'roughness_limit' not in data and not any(f.get('location')=='parameter_table' for f in resources().fields)
    assert svg_root.find(".//s:g[@id='description-A']",NS) is not None
    stress_label=svg_root.find(".//s:g[@id='calculation-label-stress']",NS)
    unit_label=svg_root.find(".//s:g[@id='calculation-unit-stress']",NS)
    assert unit_label.get('data-text')=='MPa'
    def baseline(node,role):
        path=node.find(f"s:path[@data-role='{role}']",NS)
        return float(re.search(r'translate\([^ ]+ ([^)]+)\)',path.get('transform'))[1])
    assert baseline(stress_label,'subscript')>baseline(stress_label,'label')
    assert unit_label.find("s:path[@data-role='unit']",NS) is not None
    assert unit_label.find("s:path[@data-role='superscript']",NS) is None
    assert next(e for e in nodes if e.get('data-field')=='solid_stress').text==data['solid_stress']
    top=next(e for e in nodes if e.get('data-field')=='material_code')
    assert not top.get('transform')
    field=next(f for f in resources().fields if f['key']=='material_code')
    bounds=list(map(float,top.get('data-ink-bounds').split()))
    assert abs((bounds[0]+bounds[2])/2-(field['box_mm'][0]+field['box_mm'][2])/2)<.001
    assert next(e for e in nodes if e.get('data-field')=='weight_kg').text==data['weight_kg']
    small=deepcopy(review)
    for key in ['wire_diameter','outer_diameter','free_length','pitch','solid_height']:small['spring_parameters'][key]['value']/=10
    small['spring_parameters']['load_points']=[]
    small_data=build_snapshot(small)['template_data']
    assert small_data['weight_kg']=='<0.001'
    resources().render(small_data)
    changed=deepcopy(review)
    changed['spring_parameters']['load_points'][1].update(label='P7',height_label='H9')
    renamed=build_snapshot(changed)['template_data']
    assert renamed['load1_label']=='P7' and renamed['height1_label']=='H9'
    text=resources().fill(renamed).decode()
    assert 'P7=' in text and 'H9=' in text
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
    assert build_snapshot(unconfirmed)['template_data']['weight_kg']==''
    assert readiness(unconfirmed)[0]['readiness']['status'] in ('ready','ready_with_warnings')
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
    for field,value in [('product_name','产品'*100),('technical_requirements','要求\n'*100),('designer_name','很长的名字'*20),('customer_code','客户编号'*100),('material_code','内部编码'*100)]:
        invalid={**data,field:value}
        try: resources().fill(invalid)
        except ValueError: pass
        else: raise AssertionError('Expected overflow: '+field)
    assert resources().fill({**data,'customer_code':'','material_code':'','technical_requirements':''}).count(b'YKZZ')==0
    mixed=complex_fixture()
    mixed_readiness,mixed_snapshot=readiness(mixed)
    assert mixed_readiness['readiness']['status'] in ('ready','ready_with_warnings'),mixed_readiness
    mixed_svg,mixed_pdf=resources().render(mixed_snapshot['template_data'])
    mixed_nodes=ET.fromstring(mixed_svg).findall('.//s:text[@data-field]',NS)
    outlined=ET.fromstring(resources().fill(mixed_snapshot['template_data'],outline=True))
    for node in mixed_nodes:
        spans=list(node) if list(node) else [node] if node.text else []
        group=outlined.find(f".//s:g[@id='{node.get('id')}']",NS)
        paths=group.findall('s:path',NS)
        assert len(spans)==len(paths)
        assert node.get('transform')==group.get('transform')
        for span,path in zip(spans,paths):
            coordinates=re.search(r'translate\(([^ ]+) ([^)]+)\) scale\(([^ ]+)',path.get('transform'))
            assert tuple(float(coordinates[i]) for i in (1,2,3))==tuple(float(span.get(key)) for key in ('x','y','font-size'))
    assert next(e for e in mixed_nodes if e.get('data-field')=='load1').text=='P7=2000 N ±10%'
    load2=next(e for e in mixed_nodes if e.get('data-field')=='load2')
    assert load2.find("s:tspan[@data-role='tolerance-upper']",NS).text=='+8%'
    assert load2.find("s:tspan[@data-role='tolerance-lower']",NS).text=='-5%'
    h2=next(e for e in mixed_nodes if e.get('data-field')=='height2')
    upper=h2.find("s:tspan[@data-role='tolerance-upper']",NS)
    lower=h2.find("s:tspan[@data-role='tolerance-lower']",NS)
    assert upper.text=='+0.4' and lower.text=='+0.2' and float(upper.get('y'))<float(lower.get('y'))
    assert mixed_snapshot['technical_requirements_projection']['text']==data['technical_requirements']
    # Source unit conversion applies to nominal values and their deviations.
    converted_mixed=deepcopy(mixed)
    for key in ('wire_diameter','outer_diameter','free_length','pitch','solid_height'):
        item=converted_mixed['spring_parameters'][key]
        for property in ('value','tolerance_upper','tolerance_lower'):
            if property in item:item[property]/=10
        item['unit']='cm'
    for point in converted_mixed['spring_parameters']['load_points']:
        for property in ('height','height_tolerance_upper','height_tolerance_lower'):
            if property in point:point[property]/=10
        point['height_unit']='cm'
        for property in ('force','load_tolerance_upper','load_tolerance_lower'):
            if property in point:point[property]/=1000
        point['force_unit']='kN'
    assert build_snapshot(converted_mixed)['template_data']==mixed_snapshot['template_data']
    print('PASS v3 layout, independent codes, three calculation rows, math typography, roughness, rounded kg, signed/percentage tolerances, unit conversion and vector rendering',flush=True)

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
                # An obsolete resource package disables new rendering, never existing file access.
                old_assets=tmp/'v1-assets';shutil.copytree(resource_root(),old_assets)
                manifest=json.loads((old_assets/'fields.json').read_text(encoding='utf8'))
                manifest['mapping_version']=2
                (old_assets/'fields.json').write_text(json.dumps(manifest),encoding='utf8')
                os.environ['PDF_TEMPLATE_ROOT']=str(old_assets)
                try:
                    blocked=client.get(base+'/template-pdf-readiness').json()
                    assert blocked['resources']['code']=='template_pdf_resource_version_mismatch'
                    assert client.post(base+'/template-pdfs',json={**body,'idempotency_key':'old-assets'}).status_code==503
                    assert hashlib.sha256(client.get(row['url']).content).hexdigest()==original_hash
                    assert client.post(base+'/template-pdfs',json=body).json()['template_pdf']['pdf_id']==pdf_id
                    # Legacy snapshots retain their old field names and are served as saved bytes.
                    repository.create_review('legacy-order',review,owner=OWNER)
                    legacy_directory=api.API_RUN_ROOT/'legacy-order/template_pdf/legacy-v1'
                    legacy_directory.mkdir(parents=True)
                    with pymupdf.open() as document:
                        document.new_page().insert_text((50,50),'Legacy v1 material code: 0012 003')
                        legacy_pdf=document.tobytes()
                    (legacy_directory/'drawing.pdf').write_bytes(legacy_pdf)
                    legacy_snapshot={'schema_version':'template_pdf_parameters/v1','template_data':{'part_number':'0012 003'}}
                    TemplatePdfStore(repository).create({
                        'pdf_id':'legacy-v1','review_job_id':'legacy-order','owner_erp_user_id':OWNER['user_id'],
                        'review_revision':1,'idempotency_key':'legacy-request','request_fingerprint':'0'*64,
                        'template_version':'1'*64,'parameter_snapshot':legacy_snapshot,'technical_requirements_text':'',
                        'template_data':legacy_snapshot['template_data'],'relative_path':'template_pdf/legacy-v1/drawing.pdf','filename':'legacy-v1.pdf',
                    })
                    legacy_url='/api/template-pdfs/legacy-v1/file'
                    assert client.get(legacy_url).content==legacy_pdf
                    assert client.get('/api/reviews/legacy-order/template-pdfs').json()['template_pdfs'][0]['pdf_id']=='legacy-v1'
                    assert TemplatePdfStore(repository).get('legacy-v1',OWNER['user_id'])['parameter_snapshot']==legacy_snapshot
                    assert client.delete('/api/reviews/legacy-order').status_code==200
                    assert not legacy_directory.exists() and client.get(legacy_url).status_code==404
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
