"""Replay saved artifacts in a COPY directory, without network/model calls.

Usage: python scripts/replay_simplified_diameters.py <copied-api-runs-root>
Each subdirectory must contain candidates.json, original inputs and OCR caches.
"""
import argparse
import json
from copy import deepcopy
from pathlib import Path

from ai_design_review.diameter_evidence import PENDING
from ai_design_review.drawing_annotations import locate_fields, recover_pdf_dimension_candidates
from ai_design_review.generation_contract import apply_generation_defaults
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.load_point_evidence import ground_job_candidates
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.workflow import DrawingReviewWorkflow

CASES = {
    '2426AM-95': (2,26,28,30,('mean_diameter',)),
    '1624CA-38': (6,42,48,54,('mean_diameter',)),
    '3624CA-38': (7,40,47,54,('mean_diameter','inner_diameter')),
    'TH-TZ-01-619': (20,67,87,107,('outer_diameter',)),
    'TH-TZ-01-618': (32,111,143,175,('inner_diameter',)),
    'TH-TZ-01-073': (9,34,43,52,('inner_diameter',)),
    'TH-TZ-01-072': (12,44,56,68,('outer_diameter',)),
    'TH-TZ-01-071': (20,68,88,108,('outer_diameter',)),
    'TH-TZ-01-070': (32,111,143,175,('inner_diameter',)),
    'YD4765020175': (1.5,22,23.5,25,('outer_diameter',)),
    'YD4765020178': (1.8,23.4,25.2,27,('outer_diameter',)),
}


def main(root):
    passed=[]
    for folder in sorted(Path(root).iterdir()):
        if not folder.is_dir() or not (folder/'candidates.json').is_file():continue
        data=json.loads((folder/'candidates.json').read_text(encoding='utf-8'))
        raw=data['raw_payloads']
        # Reconstruct the input, not the already verified diameter output.
        candidates=raw['qwen_vision']['candidates']+raw.get('rapidocr_dimension_grounding',{}).get('candidates',[])
        no=next((str(c['value']) for c in candidates if c.get('field')=='drawing_no'),None)
        if no not in CASES:continue
        source=next(p for p in (folder/'inputs').iterdir() if p.is_file())
        if source.suffix.lower()=='.pdf':candidates=recover_pdf_dimension_candidates(source,candidates)
        candidates=ground_job_candidates(folder,candidates,raw)
        review=DrawingReviewWorkflow({}).run(str(source),candidates,run_standardization=False,verify_diameter_roles=True)
        apply_generation_defaults(review)
        params=review['spring_parameters']; expected=CASES[no]
        actual=tuple(params.get(f,{}).get('value') for f in ('wire_diameter','inner_diameter','mean_diameter','outer_diameter'))
        assert actual==expected[:4],(no,actual,expected[:4],review.get(PENDING))
        annotations=locate_fields(review,candidates,[])
        for field in expected[4]:
            annotation=next(a for a in annotations if a['field']==field)
            assert annotation['status']=='located',(no,field,annotation)
            assert params[field]['need_human_review'],(no,field,'automatically confirmed')
        if no in ('2426AM-95','1624CA-38','3624CA-38'):
            assert not review.get(PENDING),(no,review.get(PENDING))
            pending_package=build_generation_parameter_package(deepcopy(review))
            assert 'mean_diameter' not in pending_package['generation_parameters']['spring_parameters']
            assert pending_package['solidworks_preview']['modelParameters']['中径'] is None
            confirmed=deepcopy(review)
            confirmed['generation_settings']={'drawing_model':'X型','username':'Offline QA','typeface':'宋体'}
            for field in ('wire_diameter','inner_diameter','mean_diameter','outer_diameter'):
                confirmed['spring_parameters'][field]['need_human_review']=False
            package=build_generation_parameter_package(confirmed)
            assert package['solidworks_preview']['modelParameters']['中径']==expected[2]
            command=build_solidworks_command('1000000001',package,confirmed)
            assert command['models'][0]['modelParameters']['中径']==expected[2]
        if no=='1624CA-38':assert params['free_length']['value']==70
        if no in ('YD4765020175','YD4765020178'):
            assert (params['outer_diameter']['tolerance_upper'],params['outer_diameter']['tolerance_lower'])==(0,-.02)
        print('PASS',no,actual,'anchors',expected[4],flush=True)
        passed.append(no)
    assert set(passed)==set(CASES),('missing fixtures',set(CASES)-set(passed))
    print('All 11 original drawings passed offline.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');main(parser.parse_args().root)
