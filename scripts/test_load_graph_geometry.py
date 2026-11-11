"""Geometry fallback fixtures and optional saved-photo new-upload/old-order replay."""
from copy import deepcopy
import json
import hashlib
import os
import shutil
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

def single_station():
    page=drawing()
    page['texts']=[t for t in page['texts'] if t['text'] not in ('F1=29.26N','22.5')]
    page['line_segments']=[line for line in page['line_segments'] if line not in ([260,70,260,170],[40,160,260,160])]
    return page


class GeometryTests(unittest.TestCase):
    def test_provisional_model_value_requires_documented_direct_pairing(self):
        from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
        from ai_design_review.fusion import fuse_candidates
        from ai_design_review.load_points import load_point_is_confirmed
        point={"label":"P","height":225,"height_unit":"mm","force":83300,"force_unit":"N","evidence":"P=83300N，工作高度225"}
        point["height_relation"]={"kind":"absolute_height","value":225,"unit":"mm","evidence":"尺寸线标注225对应P=83300N"}
        def review_for(raw):
            candidates=qwen_payload_to_candidates({"load_points":[raw]},require_height_relation=True)
            fused=fuse_candidates(candidates)["load_points"][0]
            return {"spring_parameters":{"load_points":[{**fused["value"],"need_human_review":fused["need_human_review"]}]}}
        review=review_for(point)
        refresh_load_heights(review)
        draft=review["spring_parameters"]["load_points"][0]
        self.assertEqual((draft["height"],draft["height_relation"]["status"],draft["height_relation"]["verified"]),(225,"model_pending",False))
        self.assertFalse(load_point_is_confirmed(draft))
        draft["need_human_review"]=False
        self.assertEqual(refresh_load_heights(review),[])
        self.assertTrue(load_point_is_confirmed(draft))
        for value, evidence, kind in [(225,"估算工作高度约225","absolute_height"),(225,"原图P=83300N，工作高度225","free_deflection"),
                                      (235,"尺寸线标注225对应P=83300N","absolute_height")]:
            invalid=review_for({**point,"height_relation":{"kind":kind,"value":value,"unit":"mm","evidence":evidence}})
            refresh_load_heights(invalid)
            self.assertIsNone(invalid["spring_parameters"]["load_points"][0]["height"])

    def test_overlapping_force_reads_are_one_station_and_height_is_independent(self):
        from ai_design_review.load_points import load_point_is_confirmed
        page=single_station()
        page["texts"][0]["text"]="P=83300N"
        page["texts"].append({"text":"P=8330N","bbox":[210,25,280,40]})
        page["texts"].append({"text":"2","bbox":page["texts"][1]["bbox"]})
        # The force fragment and equal-vote height fragment must not displace the complete reads.
        heights,points=result(page)
        self.assertEqual(heights,{"P":20})
        self.assertEqual(points[0]["force"],83300)
        page["texts"][-2]["text"]="P=83100N"
        heights,points=result(page)
        self.assertEqual(heights,{"P":20})
        p=points[0]
        self.assertEqual(p["force_alternatives"],[83100,83300])
        p["need_human_review"]=False
        self.assertFalse(load_point_is_confirmed(p))

    def test_single_force_and_height_tolerance(self):
        for force,label in [('42.56 N','F'),('F=42.56N','F'),('P=42.56N','P'),('W7=42.56N','W7'),('工况A=42.56N','工况A')]:
            page=single_station()
            page['texts'][0]['text']=force
            page['texts'][1]['text']='20+2/0'
            for turn in range(4):
                heights,points=result(_frame(page,turn))
                self.assertEqual(heights,{label:20},(label,turn))
                p=points[0]
                self.assertEqual((p['height_label'],p['height_tolerance_upper'],p['height_tolerance_lower']),
                                 ('H7' if label=='W7' else 'H',2,0))
            page['line_segments'].remove([220,100,320,100])
            self.assertEqual(result(page)[0],{} if force=='42.56 N' else {label:None})

    def test_unlabelled_duplicates_and_occupied_labels(self):
        page=drawing()
        page['texts'][0]['text']='42.56 N'
        page['texts'][1]['text']='42.56N'
        page['texts'].append({'text':'42.56N','bbox':[212,26,280,39]})
        page['texts'].append({'text':'123 N','bbox':[30,250,80,260]})
        self.assertEqual(result(page)[0],{'F1':20,'F2':22.5})
        page['texts'][1]['text']='F1=42.56N'
        heights,points=result(page)
        self.assertEqual(heights,{'F2':20,'F1':22.5})
        self.assertEqual({p['label']:p['height_label'] for p in points},{'F2':'H2','F1':'H1'})

    def test_equal_force_and_printed_name_at_distinct_stations(self):
        from ai_design_review.fusion import fuse_candidates
        from ai_design_review.load_point_evidence import _point_candidates
        page=drawing()
        page['texts'][0]['text']=page['texts'][1]['text']='P=42.56N'
        _,points=result(page)
        fused=fuse_candidates(_point_candidates(points))["load_points"]
        self.assertEqual(sorted((item["value"]["label"],item["value"]["height"]) for item in fused),[('P',20),('P',22.5)])

    def test_verified_deflection_uses_free_height_and_keeps_offsets_local(self):
        page=single_station()
        page['texts'][1].update(text='10±2',bbox=[260,114,282,125])
        page['line_segments'].remove([40,130,220,130])
        page['line_segments'].append([220,130,320,130])
        heights,points=result(page)
        self.assertEqual(heights,{'F2':18})
        p=points[0]
        self.assertEqual(p['height_relation']['kind'],'free_deflection')
        self.assertNotIn('height_tolerance_upper',p)
        self.assertEqual(p['height_relation']['last_inputs']['free_length_mm'],28)

    def test_work_height_offsets_do_not_borrow_free_height_or_force_offsets(self):
        page=single_station()
        page['texts'][0]['text']='F=42.56N±3%'
        page['texts'][-1]['text']='28±3'
        page['texts'] += [{'text':'+2','bbox':[145,110,158,117]},{'text':'-1','bbox':[145,118,158,126]}]
        _,points=result(page)
        p=points[0]
        self.assertEqual((p['height'],p['height_tolerance_upper'],p['height_tolerance_lower'],p['load_tolerance_percent']),
                         (20,2,-1,3))
        self.assertIn('+2\n-1',p['height_relation']['evidence'])
        page['texts'].pop()
        _,points=result(page)
        self.assertEqual((points[0]['height'],points[0].get('height_tolerance_status')),(20,'uncertain'))

    def test_unlabelled_in_work_requirement_and_table(self):
        page={'page':1,'width':500,'height':300,'line_segments':[],'lines':[],
              'texts':[{'text':'工作高度104 ±2 mm，载荷为190 N','bbox':[30,40,300,54]}]}
        heights,points=result(page)
        self.assertEqual(heights,{'F':104})
        self.assertEqual(points[0]['height_tolerance_upper'],2)
        page['texts']=[
            {'text':'高度(mm)','bbox':[30,30,100,40]}, {'text':'载荷(N)','bbox':[150,30,220,40]},
            {'text':'104+2/-1','bbox':[40,50,90,60]}, {'text':'190','bbox':[170,50,200,60]},
        ]
        heights,points=result(page)
        self.assertEqual(heights,{'F':104})
        self.assertEqual(points[0]['height_tolerance_lower'],-1)
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
            with patch('ai_design_review.load_point_evidence.raster_pages',return_value=[drawing()]):
                reconcile_load_points(old,folder)
            self.assertEqual([{k:v for k,v in p.items() if k!='load_relation_candidate'} for p in old['spring_parameters']['load_points']],before)
            # A pending sibling upgrades; a successful old height/confirmation stays verbatim.
            points[0]['height_relation'].update(kind='unknown',verified=False,value=None)
            cache.write_text(json.dumps({'fingerprint':fingerprint,'points':points}),encoding='utf-8')
            old['spring_parameters']['load_points'][0].update(height=None,need_human_review=True)
            old['spring_parameters']['load_points'][0]['height_relation']={'kind':'unknown','verified':False}
            successful=deepcopy(next(p for p in before if p['label']=='F1'))
            with patch('ai_design_review.load_point_evidence.raster_pages',return_value=[drawing()]):reconcile_load_points(old,folder)
            current=next(p for p in old['spring_parameters']['load_points'] if p['label']=='F1')
            self.assertEqual({k:v for k,v in current.items() if k!='load_relation_candidate'},successful)
            self.assertEqual(current['load_relation_candidate']['original']['height'],22.5)
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

def scan_replay(first, second):
    from ai_design_review.load_point_evidence import ground_job_candidates
    from ai_design_review.page_images import render_pdf
    from ai_design_review.workflow import DrawingReviewWorkflow

    expected=[
        [(p,'P',force,height,2 if p==3 else None,-2 if p==3 else None,None,False)
         for p,(force,height) in enumerate(zip([29500,79100,3881,9384,32700,83300],[225,225,104,199,225,225]),1)],
        [(1,'F1',11.9,11.414,None,None,10,False),(1,'F2',15.3,9.474,None,None,10,True)],
    ]
    rules=json.loads((ROOT/'config/factory_rules.json').read_text(encoding='utf-8'))
    workflow=DrawingReviewWorkflow(rules)
    root=ROOT/'outputs/load-height-offline-replay'

    def outcomes(review):
        return sorted((p['page'],p['label'],p['force'],p['height'],p.get('height_tolerance_upper'),
                       p.get('height_tolerance_lower'),p.get('load_tolerance_percent'),
                       bool(p['height_relation'].get('reference_only'))) for p in review['spring_parameters']['load_points'])

    with patch.dict(os.environ,{'QWEN_MAX_PAGES':'6'}):
        for index,source in enumerate((Path(first),Path(second)),1):
            folder=root/str(index)
            (folder/'inputs').mkdir(parents=True,exist_ok=True)
            local=folder/'inputs'/source.name
            assert not local.exists() or local.read_bytes()==source.read_bytes()
            if not local.exists():
                shutil.copyfile(source,local)
            render_pdf(local,folder/'pages','page',220,False)
            pages=raster_pages(folder,{},allow_ocr=True,diameter_geometry=True)
            base={'field':'spring_type','value':'compression_spring','source':'manual','confidence':1}
            with patch('ai_design_review.load_point_evidence.raster_pages',return_value=pages):
                candidates=ground_job_candidates(folder,[base],{})
                fresh=workflow.run(None,candidates,run_standardization=False)
                assert outcomes(fresh)==expected[index-1],outcomes(fresh)
                old=deepcopy(fresh)
                ids={}
                for p in old['spring_parameters']['load_points']:
                    ids[p['page'],p['label']]=p['load_point_id']
                    p.update(height=None,need_human_review=True,source=['qwen_vision'])
                    p['height_relation']={'kind':'unknown','verified':False,'mode':'automatic'}
                    for key in ('height_label','height_tolerance_upper','height_tolerance_lower'):
                        p.pop(key,None)
                reconcile_load_points(old,folder)
                assert outcomes(old)==expected[index-1],outcomes(old)
                assert {(p['page'],p['label']):p['load_point_id'] for p in old['spring_parameters']['load_points']}==ids
            print(source.name, outcomes(fresh), '新识别及旧单补核通过',flush=True)


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
    elif '--scans' in sys.argv:scan_replay(*sys.argv[2:])
    else:unittest.main()
