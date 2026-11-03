"""Temporary SQLite: graph recovery/save/confirm/export, stale writes and manual protection."""
import json
import os
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
os.environ['AI_REVIEW_IDENTITY_MODE']='mock';os.environ['AI_REVIEW_MOCK_USER_ID']='load-graph-test'
from fastapi.testclient import TestClient
from PIL import Image
from ai_design_review import api
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.load_point_evidence import extract_page_points,raster_pages,reconcile_load_points
from ai_design_review.load_height_relations import refresh_load_heights
from ai_design_review.generation_readiness import build_generation_parameter_package
from test_load_graph_geometry import drawing

def exercise(kind,pages,expected,saved=None):
    fixture=deepcopy(saved) if saved else json.loads((ROOT/'data/test/compression_design_checks.json').read_text(encoding='utf-8'))['base']
    points=extract_page_points(pages[0]);fixture['manual_confirmations']={}
    fixture['spring_parameters']['load_points']=deepcopy(points)
    for i,p in enumerate(fixture['spring_parameters']['load_points']):
        p.update(load_point_id=f'point-{i}',height=None,need_human_review=True,source=['qwen_vision'])
        p['height_relation']={'kind':'unknown','verified':False,'mode':'automatic'}
    with tempfile.TemporaryDirectory(prefix='graph-recovery-') as directory:
        root=Path(directory);job=root/kind;(job/'inputs').mkdir(parents=True)
        Image.new('RGB',(500,300),'white').save(job/'inputs/source.png')
        repo=ReviewPersistence(f"sqlite+pysqlite:///{root/'reviews.db'}");repo.create_schema_for_testing()
        repo.create_review(kind,fixture,file_info={'kind':'image'},artifact_dir=str(job),owner={'user_id':'load-graph-test'})
        before=deepcopy(repo.get_review(kind)['review'])
        with patch.object(api,'API_RUN_ROOT',root),patch.object(api,'REVIEW_PERSISTENCE',repo),patch.object(api,'verify_review_roughness',lambda *a,**k:None),patch('ai_design_review.load_point_evidence.raster_pages',return_value=pages),TestClient(api.app) as client:
            def load():
                r=client.get('/api/reviews/'+kind);assert r.status_code==200,r.text;return r.json()
            def save(r,revision=None):
                response=client.patch('/api/reviews/'+kind,json={'review':r,'expected_revision':revision or r['review_revision']});assert response.status_code==200,response.text;return response.json()
            current=load();ps=current['spring_parameters']['load_points']
            assert {p['label']:p['height'] for p in ps}==expected
            assert all(p['need_human_review'] and p['height_relation']['geometry_evidence'] for p in ps)
            assert repo.get_review(kind)['review']==before,'GET cannot mutate stored review'
            assert build_generation_parameter_package(current)['generation_parameters']['load_points']==[]
            save(current);current=load()
            assert any(e['event_type']=='load_height_evidence_reconciled' for e in repo.list_change_events(kind))
            assert not current.get('load_height_adjustment',{}).get('pending_save')
            for p in current['spring_parameters']['load_points']:p['need_human_review']=False
            save(current);current=load()
            assert all(p['need_human_review'] is False for p in current['spring_parameters']['load_points'])
            package=build_generation_parameter_package(current);frozen=deepcopy(package)
            assert {p['label']:p['height']['value'] for p in package['generation_parameters']['load_points']}==expected
            assert 'geometry_evidence' not in json.dumps(package['solidworks_preview'])
            # Rename/reorder without changing identity or a direct height.
            ps=current['spring_parameters']['load_points'];ids={p['load_point_id'] for p in ps}
            first=ps[0];first['label']='安装工况';ps.reverse()
            current['spring_parameters']['free_length']['value']=200
            save(current);current=load()
            assert {p['load_point_id'] for p in current['spring_parameters']['load_points']}==ids
            assert next(p for p in current['spring_parameters']['load_points'] if p['label']=='安装工况')['height']==first['height']
            # Explicit manual clearing cannot be silently filled by old evidence.
            p=current['spring_parameters']['load_points'][0];blank_id=p['load_point_id']
            p.update(height=None,need_human_review=True);p['height_relation']['mode']='manual'
            save(current);current=load();p=next(p for p in current['spring_parameters']['load_points'] if p['load_point_id']==blank_id)
            assert p['height'] is None and p['height_relation']['mode']=='manual'
            assert package==frozen
            assert client.patch('/api/reviews/'+kind,json={'review':before,'expected_revision':1}).status_code==409
            with patch.dict(os.environ,{'AI_REVIEW_MOCK_USER_ID':'other-user'}):assert client.get('/api/reviews/'+kind).status_code==404
        repo.dispose()
    print(kind,'graph API recovery, CAS/audit, confirmation/SW, rename/manual clear, isolation passed')

if __name__=='__main__':
    exercise('synthetic',[drawing()],{'F1':22.5,'F2':20})
    if '--local' in sys.argv:
        for kind,expected in [('return',{'F1':22.5,'F2':20}),('main',{'F1':32,'F2':29})]:
            folder=ROOT/'outputs/load-geometry-fixtures'/kind;saved=json.loads((folder/'review.json').read_text(encoding='utf-8'))
            exercise(kind,raster_pages(folder,saved,allow_ocr=False),expected,saved)
