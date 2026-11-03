"""Offline recovery, independent calculation dependencies and shared browser cases."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ai_design_review.standardizers.design_checks import refresh_design_checks
from ai_design_review.load_point_evidence import extract_page_points, extract_force_annotations
from ai_design_review.load_height_relations import refresh_load_heights
from ai_design_review.pitch_evidence import recover_pitch
from ai_design_review.coil_units import coil_unit_supported

def param(value,unit='mm',**extra):
    return dict(value=value,unit=unit,source=['qwen_vision'],need_human_review=True,**extra)

def base():
    return {'drawing_summary':{'spring_type':'compression_spring'},'spring_parameters':{
        'material':param('',''), 'wire_diameter':param(1.6),'mean_diameter':param(6.4),
        'total_coils':param(7,'coils'),'active_coils':param(8,'turns')|{'source':['solidworks_protocol_default']},
        'support_coils':param(1,'coils/end',evidence='Number of End Coils: Each One of Two Ends'),
        'free_length':param(18),'pitch':param(2.57,evidence='Original pitch 2.57'),
        'end_type':param('两端并紧',''),'end_grinding':param('两端磨削',''),
        'spring_rate':param(47.37,'N/mm')|{'need_human_review':False},
        'load_points':[{'load_point_id':'installation','label':'Pn','force':142.1,'force_unit':'N','height':15,'height_unit':'mm',
                        'load_tolerance_upper':5,'load_tolerance_lower':-5,'need_human_review':True,'load_role':'working'}]},
        'spring_features':{},'manual_confirmations':{}}

def shared_cases():
    result=[]
    for name,changes in [('drawing',{}),('catalog-material',{'material':param('SUS304','')}),
            ('unconfirmed-rate',{'spring_rate':param(47.37,'N/mm')}),
            ('invalid-rate',{'spring_rate':param(-1,'N/mm')|{'need_human_review':False}}),
            ('independent-pitch',{'support_coils':param(None,'turns'),'active_coils':param(None,'turns'),'material':param('SUS304','')}),
            ('manual-active',{'active_coils':param(3,'coils')|{'source':['human_edited'],'need_human_review':False}})]:
        review=base();review['spring_parameters'].update(changes)
        original=deepcopy(review);refresh_design_checks(review)
        result.append(dict(name=name,review=original,expected=review))
    return result

def table_page(label='Pn'):
    def t(text,x,y,w=35):return {'text':text,'bbox':[x,y,x+w,y+10]}
    return {'page':1,'width':400,'height':300,'lines':[], 'texts':[
        t(label+'=142.1N±5N',220,15,120),t('Installed Load',0,100,45),
        t('Height',50,80),t('(mm)',90,80),t('15',145,80),t('1',146,81,8),t('5',155,81,8),
        t('Load',50,100),t('(N)',90,100),t('142.1',145,100,45),t('13±0.5',220,150,60)]}

class RecoveryTests(unittest.TestCase):
    def test_drawing_chain_and_density(self):
        r=shared_cases()[0]['expected'];p=r['spring_parameters'];m=r['design_checks']['metrics']
        self.assertEqual(p['active_coils']['value'],5)
        self.assertEqual(p['solid_height']['value'],10.4)
        self.assertEqual(p['pitch']['value'],2.57)
        self.assertIn('3.12',p['pitch']['formula_check_warning'])
        self.assertIsNone(m['unit_mass']['value']);self.assertIn('密度',m['unit_mass']['reason'])
        stress=m['solid_stress'];self.assertAlmostEqual(stress['force_n'],47.37*(18-10.4))
        self.assertEqual(stress['inputs']['spring_rate_source'],'input')
        self.assertNotIn('active_coils',stress['source_fields'])
        self.assertAlmostEqual(stress['value'],8*stress['force_n']*6.4*m['curvature_factor']['value']/(math.pi*1.6**3))
        self.assertIsNone(m['theoretical_spring_rate']['value'])

    def test_independent_pitch_weight_and_rate_fallback(self):
        cases={c['name']:c['expected'] for c in shared_cases()}
        r=cases['independent-pitch'];p=r['spring_parameters'];m=r['design_checks']['metrics']
        self.assertIsNone(p['active_coils']['value']);self.assertIsNone(p['support_coils']['value'])
        self.assertGreater(m['unit_mass']['value'],0)
        self.assertAlmostEqual(m['wire_length']['value'],7*math.sqrt((math.pi*6.4)**2+2.57**2))
        self.assertIsNone(cases['unconfirmed-rate']['design_checks']['metrics']['solid_stress']['value'])
        r=base();r['spring_parameters']['material']=param('SUS304','');r['spring_parameters']['spring_rate']['need_human_review']=True
        refresh_design_checks(r);s=r['design_checks']['metrics']['solid_stress']
        self.assertEqual(s['inputs']['spring_rate_source'],'theoretical');self.assertGreater(s['value'],0)

    def test_units_defaults_and_manual_protection(self):
        for unit in ['coil','coils','turn','turns','圈',' COILS ']:self.assertTrue(coil_unit_supported('total_coils',unit))
        self.assertTrue(coil_unit_supported('support_coils','coils/end'))
        self.assertFalse(coil_unit_supported('total_coils','coils/end'))
        r=base();p=r['spring_parameters'];p['support_coils']=param(None,'turns');refresh_design_checks(r)
        self.assertIsNone(p['active_coils']['value']);self.assertIsNone(p['support_coils']['value'])
        r=base();p=r['spring_parameters'];p['active_coils']=param(3,'coils')|{'source':['human_edited'],'need_human_review':False}
        refresh_design_checks(r);self.assertEqual(p['active_coils']['value'],3);self.assertIn('support_coils_conflict',p['support_coils'])
        p['pitch']=param('')|{'source':['human_edited']};refresh_design_checks(r);self.assertEqual(p['pitch']['value'],'')

    def test_immediate_recalculation_and_confirmation(self):
        r=base();p=r['spring_parameters'];refresh_design_checks(r)
        p['active_coils']['need_human_review']=False;p['active_coils']['source'].append('human_confirmed');r['manual_confirmations']['active_coils']={'confirmed':True}
        p['total_coils'].update(value=8,source=['human_edited']);refresh_design_checks(r)
        self.assertEqual(p['active_coils']['value'],6);self.assertTrue(p['active_coils']['need_human_review'])
        self.assertNotIn('active_coils',r['manual_confirmations']);self.assertEqual(p['solid_height']['value'],12)
        p['total_coils']['value']='invalid';refresh_design_checks(r)
        self.assertEqual(p['active_coils']['value'],6);self.assertTrue(p['active_coils']['derived_value_stale'])
        self.assertIsNone(r['design_checks']['metrics']['solid_stress']['value'])
        p['total_coils']['value']=9;refresh_design_checks(r);self.assertEqual(p['active_coils']['value'],7);self.assertFalse(p['active_coils']['derived_value_stale'])

    def test_generic_table_load_and_no_dimension_mix(self):
        for label in ['Pn','Fmin','F_A','工况1','P₁','1']:
            pts=extract_page_points(table_page(label));r={'spring_parameters':{'load_points':pts}}
            refresh_load_heights(r);self.assertEqual(len(pts),1,label)
            self.assertEqual(pts[0]['height'],15,label);self.assertEqual(pts[0]['load_tolerance_upper'],5)
            self.assertEqual(pts[0]['height_relation']['verification_method'],'table_cells')
        for text in ['k=47.37N/mm','pressure=10MPa','torque=5N·mm']:
            self.assertEqual(extract_force_annotations(text),[],text)
        page=table_page();page['texts']=[t for t in page['texts'] if t['text']!='(mm)']
        pts=extract_page_points(page);self.assertFalse(pts[0]['height_relation']['verified'])
        self.assertFalse(extract_page_points(table_page(),region={'page':2,'x':0,'y':0,'width':1,'height':1}))

    def test_horizontal_table(self):
        page=table_page();page['texts']=page['texts'][:1]+[
            {'text':s,'bbox':[x,y,x+70,y+10]} for s,x,y in [('Height(mm)',30,60),('Load(N)',150,60),('15',35,90),('142.1',155,90)]]
        pts=extract_page_points(page);refresh_load_heights({'spring_parameters':{'load_points':pts}})
        self.assertEqual(pts[0]['height'],15)

    def test_pitch_local_and_manual_protection(self):
        r=base();r['spring_parameters']['pitch']=param(None)
        page={'page':1,'width':100,'height':100,'texts':[{'text':'Pitch: 2.57 mm','bbox':[10,10,70,20]}],'lines':[]}
        self.assertTrue(recover_pitch(r,[page]));self.assertEqual(r['spring_parameters']['pitch']['value'],2.57)
        r['spring_parameters']['pitch']=param('')|{'human_modified':True};self.assertFalse(recover_pitch(r,[page]))
        r['spring_parameters']['pitch']=param(3.12)|{'formula_calculation_kind':'pitch','need_human_review':False}
        self.assertFalse(recover_pitch(r,[page]));self.assertEqual(r['spring_parameters']['pitch']['value'],3.12)
        self.assertEqual(r['spring_parameters']['pitch']['pitch_evidence_candidate']['value'],2.57)

    def test_explicit_solid_load_precedence(self):
        r=base();p=r['spring_parameters'];p['load_points'].append({'label':'极限工况','force':100,'force_unit':'N','load_role':'solid'})
        refresh_design_checks(r);stress=r['design_checks']['metrics']['solid_stress']
        self.assertEqual(stress['force_n'],100);self.assertEqual(stress['status'],'calculated')
        self.assertNotIn('spring_rate',stress['source_fields'])

def local_replay():
    folder=ROOT/'outputs/nbm-recovery-fixture';pages=json.loads((folder/'pages-evidence.json').read_text(encoding='utf-8'))
    r=base();r['spring_parameters']['pitch']=param(None)
    assert recover_pitch(r,pages);assert r['spring_parameters']['pitch']['value']==2.57
    points=[p for page in pages for p in extract_page_points(page,hints=base()['spring_parameters']['load_points'])]
    r['spring_parameters']['load_points']=points;refresh_load_heights(r);refresh_design_checks(r)
    pn=next(p for p in points if p['label'].upper()=='PN');assert pn['height']==15 and pn['load_tolerance_upper']==5
    assert r['spring_parameters']['active_coils']['value']==5 and r['spring_parameters']['solid_height']['value']==10.4
    # Replay the complete new-upload parsing/fusion path, not just calculator inputs.
    from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
    from ai_design_review.load_point_evidence import ground_job_candidates
    from ai_design_review.workflow import DrawingReviewWorkflow
    raw=json.loads((folder/'qwen_vision_raw.json').read_text(encoding='utf-8'))['parsed']
    candidates=ground_job_candidates(folder,qwen_payload_to_candidates(raw,require_height_relation=True),{})
    review=DrawingReviewWorkflow(json.loads((ROOT/'config/factory_rules.json').read_text(encoding='utf-8'))).run(None,candidates,run_standardization=False)
    p=review['spring_parameters'];pn=next(p for p in p['load_points'] if p['label'].upper()=='PN')
    assert pn['height']==15 and pn['load_tolerance_upper']==5
    assert p['active_coils']['value']==5 and p['solid_height']['value']==10.4 and p['pitch']['value']==2.57
    print('Saved drawing OCR replay: pitch 2.57, load 15/142.1/±5, active 5, nominal Hb 10.4; no cloud calls')

if __name__=='__main__':
    if '--json' in sys.argv: print(json.dumps(shared_cases(),ensure_ascii=True))
    elif '--local' in sys.argv:local_replay()
    else:unittest.main()
