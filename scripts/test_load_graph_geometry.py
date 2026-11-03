"""Geometry fallback fixtures and optional saved-photo new-upload/old-order replay."""
from copy import deepcopy
import json
import hashlib
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from ai_design_review.load_graph_geometry import geometry_relations,_frame
from ai_design_review.load_point_evidence import extract_page_points,original_points,raster_pages,reconcile_load_points
from ai_design_review.load_height_relations import refresh_load_heights,normalize_relation

def drawing():
    return {'page':1,'width':500,'height':300,'texts':[
        {'text':'F2=42.56N','bbox':[210,25,280,40]}, {'text':'F1=29.26N','bbox':[252,52,322,67]},
        {'text':'20','bbox':[120,114,145,125]}, {'text':'22.5','bbox':[120,144,150,155]},
        {'text':'28','bbox':[120,174,145,185]}], 'lines':[],
        'line_segments':[[40,110,40,240],[220,50,220,140],[260,70,260,170],[320,100,320,220],
            [220,50,320,100],[220,100,320,100],[40,130,220,130],[40,160,260,160],[40,190,320,190]]}

def result(page,**kwargs):
    points=extract_page_points(page,**kwargs)
    r={'spring_parameters':{'load_points':points}};refresh_load_heights(r)
    return {p['label']:p['height'] for p in points},points

class GeometryTests(unittest.TestCase):
    def test_no_L0_direct_heights_and_metadata(self):
        heights,points=result(drawing());self.assertEqual(heights,{'F2':20,'F1':22.5})
        for p in points:
            self.assertEqual(p['height_relation']['kind'],'absolute_height')
            self.assertEqual(p['height_relation']['verification_method'],'dimension_graph')
            self.assertTrue(p['need_human_review'])
            self.assertIn('geometry_evidence',normalize_relation(p['height_relation'],trusted=True))
            self.assertNotIn('geometry_evidence',normalize_relation(p['height_relation'],trusted=False))

    def test_rotated_and_skewed(self):
        for turn in range(4):
            page=_frame(drawing(),turn);heights,points=result(page)
            self.assertEqual(heights,{'F2':20,'F1':22.5},turn)
            for p in points:
                for q in p['height_relation']['geometry_evidence']['dimension_endpoints']:
                    self.assertTrue(0<=q['x']<=1 and 0<=q['y']<=1)
        page=drawing()
        def skew(x,y):return [x+.03*y,y+.025*x]
        page['line_segments']=[[*skew(*l[:2]),*skew(*l[2:])] for l in page['line_segments']]
        for t in page['texts']:
            x,y,xx,yy=t['bbox'];cs=[skew(a,b) for a,b in [(x,y),(x,yy),(xx,y),(xx,yy)]]
            t['bbox']=[min(p[0] for p in cs),min(p[1] for p in cs),max(p[0] for p in cs),max(p[1] for p in cs)]
        self.assertEqual(result(page)[0],{'F2':20,'F1':22.5})

    def test_polyline_leader_and_crossing(self):
        page=drawing();page['texts'][1]['bbox']=[360,15,430,30]
        page['line_segments'] += [[360,30,300,30],[300,30,260,70]]
        heights,points=result(page);self.assertEqual(heights,{'F2':20,'F1':22.5})
        p=next(p for p in points if p['label']=='F1')
        self.assertEqual(p['height_relation']['verification_method'],'dimension_leader')
        self.assertEqual(len(p['height_relation']['geometry_evidence']['leader_path']),2)
        page['line_segments'] += [[300,30,220,50]]
        self.assertIsNone(result(page)[0]['F1'],'Branching leaders cannot choose the nearest height')

    def test_existing_success_preserved(self):
        page=drawing();page['texts'].append({'text':'H1=18mm/F1=29.26N','bbox':[20,255,240,270]})
        heights,points=result(page);self.assertEqual(heights['F1'],18)
        relation=next(p for p in points if p['label']=='F1')['height_relation']
        self.assertEqual(relation['verification_method'],'explicit_height')
        self.assertEqual(relation['geometry_candidate']['value'],22.5)

    def test_unrelated_numbers_ambiguity_and_scope(self):
        page=drawing();page['texts'].append({'text':'26','bbox':[350,180,370,192]})
        self.assertEqual(result(page)[0],{'F2':20,'F1':22.5})
        page['texts'].append({'text':'23.5','bbox':[120,144,150,155]})
        self.assertIsNone(result(page)[0]['F1'],'Equal-strength OCR disagreements cannot be chosen')
        self.assertEqual(geometry_relations(drawing(),region={'page':2,'x':0,'y':0,'width':1,'height':1}),[])
        heights,_=result(drawing(),region={'page':1,'x':.35,'y':0,'width':.65,'height':1})
        self.assertTrue(all(v is None for v in heights.values()),'Do not borrow a datum outside the variant')
        page=drawing();page['line_segments']=[l for l in page['line_segments'] if l!=[220,50,320,100]]
        self.assertTrue(all(v is None for v in result(page)[0].values()),'Digits and extension lines alone do not prove a load diagram')
        page=drawing();page['texts'].append({'text':'UNITS: inch','bbox':[10,270,100,280]})
        self.assertTrue(all(v is None for v in result(page)[0].values()))

    def test_legacy_verified_cache_and_mixed_pending_siblings(self):
        with tempfile.TemporaryDirectory(prefix='graph-cache-') as directory:
            folder=Path(directory);(folder/'inputs').mkdir();source=folder/'inputs/source.png';source.write_bytes(b'local-test-image')
            points=original_points(source,pages=[drawing()])
            next(p for p in points if p['label']=='F1')['height_relation']['value']=18
            old={'drawing_summary':{'spring_type':'compression_spring'},'spring_parameters':{'load_points':deepcopy(points)}};refresh_load_heights(old)
            for p in old['spring_parameters']['load_points']:
                p['load_point_id']='stable-'+p['label'];p['source']=['local_load_evidence']
            stat=source.stat()
            fingerprint=hashlib.sha256(f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:load-evidence/v3:null:[None, None]".encode()).hexdigest()
            cache=folder/'load_point_evidence.json'
            cache.write_text(json.dumps({'fingerprint':fingerprint,'points':points}),encoding='utf-8')
            before=deepcopy(old['spring_parameters']['load_points'])
            with patch('ai_design_review.load_point_evidence.raster_pages',return_value=[drawing()]),patch('ai_design_review.load_point_evidence.original_points',side_effect=AssertionError('Successful v3 cache must not be reinterpreted')):
                reconcile_load_points(old,folder)
            self.assertEqual(old['spring_parameters']['load_points'],before)
            # A pending sibling upgrades; a successful old height/confirmation stays verbatim.
            points[0]['height_relation'].update(kind='unknown',verified=False,value=None)
            cache.write_text(json.dumps({'fingerprint':fingerprint,'points':points}),encoding='utf-8')
            old['spring_parameters']['load_points'][0].update(height=None,need_human_review=True)
            old['spring_parameters']['load_points'][0]['height_relation']={'kind':'unknown','verified':False}
            successful=deepcopy(next(p for p in old['spring_parameters']['load_points'] if p['label']=='F1'))
            with patch('ai_design_review.load_point_evidence.raster_pages',return_value=[drawing()]):reconcile_load_points(old,folder)
            self.assertEqual(next(p for p in old['spring_parameters']['load_points'] if p['label']=='F1'),successful)
            self.assertEqual(next(p for p in old['spring_parameters']['load_points'] if p['label']=='F2')['height'],20)

    def test_label_identity_and_missing_tolerance(self):
        page=drawing();page['texts'][0]['text']='工况甲=42.56N';page['texts'][1]['text']='P₁=29.26N±0N'
        heights,points=result(page);self.assertEqual(heights,{'工况甲':20,'P1':22.5})
        self.assertIsNone(next(p for p in points if p['label']=='工况甲')['load_tolerance_upper'])
        self.assertEqual(next(p for p in points if p['label']=='P1')['load_tolerance_upper'],0)

def local_replay():
    from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
    from ai_design_review.load_point_evidence import ground_job_candidates
    from ai_design_review.workflow import DrawingReviewWorkflow
    workflow=DrawingReviewWorkflow(json.loads((ROOT/'config/factory_rules.json').read_text(encoding='utf-8')))
    for kind,expected in [('return',{'F1':22.5,'F2':20}),('main',{'F1':32,'F2':29})]:
        folder=ROOT/'outputs/load-geometry-fixtures'/kind
        raw=json.loads((folder/'qwen_vision_raw.json').read_text(encoding='utf-8'))['parsed']
        saved=json.loads((folder/'review.json').read_text(encoding='utf-8'));before=(folder/'review.json').read_bytes()
        pages=raster_pages(folder,saved,allow_ocr=False)
        heights,points=result(pages[0]);assert heights==expected,(kind,heights)
        # New-upload path, reuse local cache and forbid cloud/model or extra OCR.
        with patch('ai_design_review.load_point_evidence.raster_pages',return_value=pages):
            candidates=ground_job_candidates(folder,qwen_payload_to_candidates(raw,require_height_relation=True),{})
            new=workflow.run(None,candidates,run_standardization=False)
            assert {p['label']:p['height'] for p in new['spring_parameters']['load_points']}==expected
            old=deepcopy(saved)
            # No original height, prior location, or cache point is allowed to solve the test.
            for p in old['spring_parameters']['load_points']:
                p.update(height=None,need_human_review=True,source=['qwen_vision'])
                p['height_relation']={'kind':'unknown','mode':'automatic','verified':False}
            reconcile_load_points(old,folder)
            assert {p['label']:p['height'] for p in old['spring_parameters']['load_points']}==expected
        assert (folder/'review.json').read_bytes()==before,'The offline replay does not mutate saved orders'
        print(kind,expected,'new upload + old pending recovery passed')

def browser_cases():
    base=json.loads((ROOT/'data/test/compression_design_checks.json').read_text(encoding='utf-8'))['base']
    cases=[]
    for name,page,expected in [('graph',drawing(),{'F1':22.5,'F2':20})]:
        r=deepcopy(base);r['spring_parameters']['load_points']=extract_page_points(page)
        for i,p in enumerate(r['spring_parameters']['load_points']):p['load_point_id']=f'graph-{i}'
        refresh_load_heights(r);cases.append({'name':name,'review':r,'expected':expected})
    for name,expected in [('return',{'F1':22.5,'F2':20}),('main',{'F1':32,'F2':29})]:
        folder=ROOT/'outputs/load-geometry-fixtures'/name
        if not (folder/'review.json').exists():continue
        saved=json.loads((folder/'review.json').read_text(encoding='utf-8'))
        r=deepcopy(base);r['manual_confirmations']={}
        r['spring_parameters']['load_points']=extract_page_points(raster_pages(folder,saved,allow_ocr=False)[0])
        for i,p in enumerate(r['spring_parameters']['load_points']):p['load_point_id']=f'graph-{i}'
        refresh_load_heights(r);cases.append({'name':name,'review':r,'expected':expected})
    print(json.dumps(cases,ensure_ascii=False))

if __name__=='__main__':
    if '--json' in sys.argv:browser_cases()
    elif '--local'  in sys.argv:local_replay()
    else:unittest.main()
