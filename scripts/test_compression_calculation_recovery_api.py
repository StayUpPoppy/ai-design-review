"""Temporary SQLite integration: local recovery, CAS/audit, confirmed export and freezing."""
import os
import sys
import tempfile
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
os.environ['AI_REVIEW_IDENTITY_MODE']='mock'
os.environ['AI_REVIEW_MOCK_USER_ID']='calculation-recovery'
from fastapi.testclient import TestClient
from PIL import Image
from ai_design_review import api
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_readiness import build_generation_parameter_package
from test_compression_calculation_recovery import base,table_page,param

with tempfile.TemporaryDirectory(prefix='calculation-recovery-') as directory:
    root=Path(directory);job=root/'job';(job/'inputs').mkdir(parents=True)
    Image.new('RGB',(400,300),'white').save(job/'inputs/source.png')
    review=base();p=review['spring_parameters'];p['pitch']=param(None)
    point=p['load_points'][0];point.update(height=None,source=['qwen_vision'],page=1)
    point['height_relation']={'kind':'absolute_height','value':15,'unit':'mm','mode':'automatic','verified':False}
    page=table_page();page['texts'].append({'text':'Pitch: 2.57 mm','bbox':[220,220,360,230]})
    repo=ReviewPersistence(f"sqlite+pysqlite:///{root/'reviews.db'}");repo.create_schema_for_testing()
    repo.create_review('job',review,file_info={'kind':'image'},artifact_dir=str(job),owner={'user_id':'calculation-recovery'})
    original=deepcopy(repo.get_review('job')['review'])
    with patch.object(api,'API_RUN_ROOT',root),patch.object(api,'REVIEW_PERSISTENCE',repo),patch.object(api,'verify_review_roughness',lambda *a,**kw:None),patch('ai_design_review.load_point_evidence.raster_pages',return_value=[page]),TestClient(api.app) as client:
        response=client.get('/api/reviews/job');assert response.status_code==200,response.text
        loaded=response.json();p=loaded['spring_parameters']
        assert p['active_coils']['value']==5 and p['solid_height']['value']==10.4 and p['pitch']['value']==2.57
        assert p['load_points'][0]['height']==15 and p['load_points'][0]['load_tolerance_upper']==5
        assert repo.get_review('job')['review']==original,'Read-only repair must not persist confirmations'
        result=client.patch('/api/reviews/job',json={'review':loaded,'expected_revision':1});assert result.status_code==200,result.text
        revision=result.json()['review_revision'];events=repo.list_change_events('job')
        assert any(e['event_type']=='pitch_evidence_reconciled' for e in events)
        assert any(e['event_type']=='automatic_calculation_reconciled' for e in events)
        assert any(e['event_type']=='load_height_evidence_reconciled' for e in events)
        loaded=client.get('/api/reviews/job').json();p=loaded['spring_parameters']
        for f in ['total_coils','active_coils','support_coils','wire_diameter','mean_diameter','free_length','solid_height','pitch','spring_rate','end_type','end_grinding']:
            p[f]['need_human_review']=False
        p['load_points'][0]['need_human_review']=False
        assert client.patch('/api/reviews/job',json={'review':loaded,'expected_revision':revision}).status_code==200
        loaded=client.get('/api/reviews/job').json();frozen=build_generation_parameter_package(loaded);snapshot=deepcopy(frozen)
        assert frozen['generation_parameters']['load_points'][0]['height']['value']==15
        assert frozen['solidworks_preview']['modelParameters']['有效圈数n']==5
        p=loaded['spring_parameters'];p['total_coils'].update(value=8,source=['human_edited'],need_human_review=True)
        result=client.patch('/api/reviews/job',json={'review':loaded,'expected_revision':loaded['review_revision']});assert result.status_code==200,result.text
        reopened=client.get('/api/reviews/job').json();p=reopened['spring_parameters']
        assert p['active_coils']['value']==6 and p['active_coils']['need_human_review']
        assert p['solid_height']['value']==12 and p['solid_height']['need_human_review']
        assert p['pitch']['value']==2.57 and p['pitch']['need_human_review'] is False
        assert p['load_points'][0]['height']==15,'Direct height must not follow free-height subtraction'
        assert frozen==snapshot,'Old frozen parameter packages stay unchanged'
        assert client.patch('/api/reviews/job',json={'review':loaded,'expected_revision':1}).status_code==409
        with patch.dict(os.environ,{'AI_REVIEW_MOCK_USER_ID':'other-user'}):assert client.get('/api/reviews/job').status_code==404
print('Calculation recovery API: local table/pitch repair, read-only GET, CAS/audit, confirmed export, immediate updates and frozen snapshots passed')
