"""Replay both supplied local images with transcribed model responses, no network."""
import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_multi_spec import api, OWNER, fixture, parameter
from ai_design_review.engines.qwen_vision_adapter import QwenVisionEngine
from ai_design_review.identity import IdentityContext
from ai_design_review.multi_spec import child_review, parse_multi_spec, source_review, MultiSpecError
from ai_design_review.review_persistence import ReviewPersistence
from starlette.datastructures import UploadFile


def table_response():
    # Manual transcription of the supplied 13-row image for offline replay.
    rows = [
        [10,85,260,10,12,31.7,485.2,76.9,1176,145,2219,15.3],
        [12,87,263,10,12,27.4,808.7,67.8,2003,125,3688,29.5],
        [13,88,262,9.5,11.5,31.3,1294,72.8,3015,125,5175,41.4],
        [15,90,265,9.5,11.5,29.5,2022,71.2,4879,100,6850,68.5],
        [16,91,264,8,11,31.7,3235,72.1,7349,96,9782,101.9],
        [18,93,263,8,10,31.7,4852,66.3,10139,92,14067,152.9],
        [19,94,263,7.5,10,33,6470,65.2,12794,82.5,16178,196.1],
        [20,95,264,7,9.5,32.4,8087,66.1,16511,84,20992,249.9],
        [21,96,263,6.5,9,33.2,10513,64.8,20548,84.5,26787,317],
        [22,97,260,6,8.5,32.3,12940,64.3,25799,84,33684,401],
        [24,99,264,6,8,30.3,16175,61.8,33041,84,44881,534.3],
        [26,101,266,5,7.5,29.2,20218,61.3,42511,84,58712,699.3],
        [28,103,274,5,7.5,29.4,25879,60.8,53443,78,68554,878.9],
    ]
    value = fixture(13); value["drawing_summary"] = {"drawing_name":"弹簧", "drawing_no":"FTA-11-A42-150-1~13"}
    for i,(candidate,row) in enumerate(zip(value["variants"], rows)):
        d, codeD, h, n, nt, delta1, f1, delta2, f2, limit_delta, limit_force, stiffness = row
        candidate.update(code=f"FTA-{d}/{codeD}-{h}", region={"x":.235,"y":.22+i*.0385,"width":.73,"height":.038},
            parameters={"wire_diameter":parameter(d), "free_length":parameter(h,tolerance_upper=4.5,tolerance_lower=-4.5), "total_coils":parameter(nt,"圈"), "active_coils":parameter(n,"圈")},
            # D1 is not guessed from the product code; ambiguous role retained.
            reference_values={"diameter_D1":parameter(75,tolerance_upper=1,tolerance_lower=0),"spring_rate":stiffness,"limit_deflection":limit_delta,"limit_force":limit_force},
            issues=["D1直径角色待核对，不从规格代号推断。"],
            load_points=[{"label":f"F{j+1}","deflection":delta,"deflection_unit":"mm","force":force,"force_unit":"N"} for j,(delta,force) in enumerate([(delta1,f1),(delta2,f2)])],
            source_context={"headers":["最小变形 mm","最小负荷 N","最大变形 mm","最大负荷 N","极限变形 mm","极限负荷 N"],"row_text":" ".join(map(str,row))})
    return value


def main():
    old_repo,old_root = api.REVIEW_PERSISTENCE,api.API_RUN_ROOT
    try:
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); repo=ReviewPersistence(f"sqlite+pysqlite:///{root/'pipeline.db'}");repo._engine.dispose()
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from sqlalchemy.pool import NullPool
            repo._engine=create_engine(f"sqlite+pysqlite:///{root/'pipeline.db'}",poolclass=NullPool);repo._session_factory=sessionmaker(repo._engine,expire_on_commit=False);repo.create_schema_for_testing()
            api.REVIEW_PERSISTENCE=repo;api.API_RUN_ROOT=root/'runs';api.API_RUN_ROOT.mkdir()
            identity=IdentityContext(**OWNER,source="mock")
            sources=[(Path('C:/Users/29580/Desktop/多规格1.png'),fixture()),(Path('C:/Users/29580/Desktop/多规格2.jpg'),table_response())]
            for i,(image,payload) in enumerate(sources):
                if not image.exists():
                    from PIL import Image
                    image=root/f'fixture{i}.png';Image.new('RGB',(600,400),'white').save(image)
                if i==0:
                    # Image 1 does not show explicit mm/N units; do not invent them.
                    payload['common']={}
                    for v in payload['variants']:
                        v['load_points'][0].pop('deflection_unit');v['load_points'][0].pop('force_unit');v['source_context']={'row_text':'压缩量 弹力'}
                response={"choices":[{"message":{"content":json.dumps(payload,ensure_ascii=False)}}]}
                with patch('ai_design_review.engines.qwen_vision_adapter._configured',return_value=True), patch.object(QwenVisionEngine,'_call_qwen',return_value=response) as call, patch('ai_design_review.surface_terms._decide_with_llm',side_effect=AssertionError('No per-spec calls')):
                    result=asyncio.run(api.run_recognition_execution(drawing=UploadFile(filename=image.name,file=io.BytesIO(image.read_bytes())),identity=identity,job_id=f'sample{i}',use_qwen=True,candidate_json=None,ocr_json=None,use_werk24=False,confirm_upload_to_werk24=False,use_cached_werk24=False,use_ocr=False,ocr_provider=None,use_geometry=False,use_vlm=False,use_llm_standardization=False,vision_provider="none",use_paddleocr=False,use_sample_ocr=False))
                    assert call.call_count==1
                    assert result['record_kind']=='source' and result['variant_count']==[3,13][i]
                    saved=repo.get_review(f'sample{i}',owner_user_id=OWNER['user_id'])['review']
                    children=[child_review(saved,c,f'sample{i}')[0] for c in saved['multi_spec']['variants']]
                    assert len(children)==[3,13][i]
                    assert all(v['spring_parameters']['wire_diameter']['need_human_review'] for v in children)
                    if i==1:
                        assert children[2]['spring_parameters']['active_coils']['value']==9.5
                        assert children[-1]['spring_parameters']['free_length']['value']==274
                        assert children[0]['spring_parameters']['load_points'][0]['height']==228.3
                        assert all(p.get('label')!='Fb' for v in children for p in v['spring_parameters']['load_points'])
                        assert children[0]['spring_parameters']['free_length']['tolerance_lower']==-4.5
                        assert children[0]['spring_parameters']['outer_diameter']['value'] is None
                    else:
                        assert all(p.get('height') is None for v in children for p in v['spring_parameters']['load_points'])
            # Incomplete and 51-row results fail before any whole-page parameter fusion.
            for mutation in ({'complete':False},{'spec_count':51},{'spring_type':'extension_spring'}):
                try: parse_multi_spec({**fixture(),**mutation})
                except MultiSpecError: pass
                else: raise AssertionError(mutation)
    finally: api.REVIEW_PERSISTENCE,api.API_RUN_ROOT=old_repo,old_root
    print('PASS two local images / mocked file-level responses: 3 blocks, 13 rows, decimal coils, tolerances, deflection, shared material, uncertain D1, no per-spec calls')


if __name__=='__main__':main()
