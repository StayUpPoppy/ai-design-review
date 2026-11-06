"""Offline bounded pages, pure reads, local worker CAS and timing acceptance."""
from pathlib import Path
from copy import deepcopy
import json, sys, tempfile, time, statistics, threading, gc
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review
from fastapi.testclient import TestClient
from ai_design_review.review_persistence import ReviewPersistence, RecognitionJobRecord, ReviewRecord
from ai_design_review import review_loading, recognition_worker as workers
from ai_design_review.preprocessing import render_pdf_with_pdftoppm
from ai_design_review import page_images
from ai_design_review.engines import ocr_providers
from ai_design_review.engines.qwen_vision_adapter import QwenVisionEngine
from PIL import Image

PDF=Path('C:/Users/29580/Desktop/扫描全能王 2024-09-09 10.38.pdf')

class TemporaryDirectory(tempfile.TemporaryDirectory):
  def cleanup(self):
    for attempt in range(5):
      try: return super().cleanup()
      except (PermissionError, NotADirectoryError):
        if attempt == 4: raise
        gc.collect(); time.sleep(.25)


def main():
  with TemporaryDirectory() as temp:
    root=Path(temp)
    if PDF.is_file():
      source=root/'source.pdf';source.write_bytes(PDF.read_bytes())
      from ai_design_review import preprocessing
      original=preprocessing._render_pdf_uncached
      with patch.object(preprocessing,'_render_pdf_uncached',wraps=original) as render:
        started=time.perf_counter(); images=render_pdf_with_pdftoppm(source,root/'pages');elapsed=time.perf_counter()-started
        assert len(images)==6 and render.call_count==6
        for p in images:
          with Image.open(p) as im: assert max(im.size)<=3000
        render_pdf_with_pdftoppm(source,root/'ocr',dpi=240);assert render.call_count==6,'OCR must reuse rendered pages'
      metadata=page_images.read_json(root/'pages/.page_metadata.json')
      assert metadata['page-5.png']['width']==7528 and metadata['page-5.png']['height']==10189
      jpeg=page_images.qwen_images(images,root/'qwen')
      for p in jpeg:
        with Image.open(p) as im:assert im.format=='JPEG' and max(im.size)<=3000
        assert p.stat().st_size<=8*1024**2
      print('Six original pages render_s=',round(elapsed,2),'preview_MB=',round(sum(Path(p).stat().st_size for p in images)/1024**2,2))
      crop=page_images.render_region(source,5,(.2,.2,.4,.3));assert max(crop.size)<=1800
    # One model per process; concurrent calls never infer against the same session simultaneously.
    counter={'create':0,'active':0,'max':0}
    class Engine:
      def __init__(self):counter['create']+=1
      def __call__(self,path):
        counter['active']+=1;counter['max']=max(counter['max'],counter['active']);time.sleep(.015);counter['active']-=1;return []
    fake=type('RapidModule',(),{'RapidOCR':Engine})
    with patch.dict(sys.modules,{'rapidocr':fake}),patch.object(ocr_providers,'_rapid_engine',None):
      with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:ocr_providers.RapidOcrProvider().recognize([root/'unused.png'],{}),range(4)))
    assert counter['create']==1 and counter['max']==1,counter
    # Diagnostics must retain the rejection reason without leaking credentials or image data.
    import httpx
    target=root/'qwen-rejection';image=root/'small.png';Image.new('RGB',(200,100),'white').save(image)
    error=httpx.HTTPStatusError('bad',request=httpx.Request('POST','https://offline.test'),response=httpx.Response(400,json={'error':{'code':'InvalidParameter','message':'invalid image Bearer secret-token data:image/png;base64,abc'}}))
    with patch.object(QwenVisionEngine,'_call_qwen',side_effect=error):
      try:QwenVisionEngine(api_key='offline',work_dir=target).extract_with_raw(image,[image])
      except httpx.HTTPStatusError:pass
      else:raise AssertionError('Expected rejection')
    diagnostic=json.loads((root/'qwen_error_diagnostics.json').read_text());assert diagnostic['http_status']==400 and diagnostic['code']=='InvalidParameter'
    assert 'secret-token' not in diagnostic['message'] and 'base64' not in diagnostic['message']
    repo=ReviewPersistence(f'sqlite+pysqlite:///{root/"read.db"}');repo.create_schema_for_testing()
    directory=root/'order';(directory/'inputs').mkdir(parents=True);Image.new('RGB',(500,300),'white').save(directory/'inputs/original.png');(directory/'pages').mkdir();Image.new('RGB',(500,300),'white').save(directory/'pages/source.png')
    review=ready_review();review['drawing_annotations']={'schema_version':'original_annotations/v1','source_document_id':'original-frame','annotation_revision':3,'annotations':[],'pages':[{'page':1,'width':500,'height':300}]}
    repo.create_review('order',review,owner=OWNER,artifact_dir=str(directory))
    with patch.object(api,'REVIEW_PERSISTENCE',repo),patch.object(api,'API_RUN_ROOT',root),patch.object(workers,'REVIEW_PERSISTENCE',repo),patch.object(workers,'API_RUN_ROOT',root),TestClient(api.app) as client:
      forbidden=[patch.object(api,name,side_effect=AssertionError(f'{name} ran during an ordinary read')) for name in ['verify_review_roughness','reconcile_load_points','_prepare_review_reasonableness']]
      from contextlib import ExitStack
      with ExitStack() as stack:
        for guard in forbidden:stack.enter_context(guard)
        stack.enter_context(patch.object(QwenVisionEngine,'_call_qwen',side_effect=AssertionError('No cloud calls')))
        stack.enter_context(patch.object(ocr_providers.RapidOcrProvider,'recognize',side_effect=AssertionError('No OCR on reads')))
        times=[]
        for _ in range(20):
          start=time.perf_counter();r=client.get('/api/reviews/order');assert r.status_code==200,r.text;times.append(time.perf_counter()-start)
        meta=client.get('/api/reviews/order?metadata_only=true');assert meta.status_code==200 and meta.json()['annotation_revision']==3
        assert client.get('/api/reviews/order/artifacts/pages/source.png').status_code==200
        assert client.get('/api/reviews/order/annotations').json()['source_document_id']=='original-frame'
        assert client.get('/api/reviews/order/generation-readiness').status_code==200
      assert len(repo.list_recognition_jobs(owner_user_id=OWNER['user_id']))==0,'Local tasks stay out of history'
      claimed=repo.claim_next_recognition_job('local-qa');assert claimed['options']['task_kind']=='local_verification'
      baseline=repo.get_review('order',owner_user_id=OWNER['user_id'])['revision']
      with patch.object(api,'verify_review_roughness',return_value=False),patch.object(api,'reconcile_load_points'),patch('ai_design_review.drawing_annotations.build_annotations',return_value=deepcopy(review['drawing_annotations'])):
        assert review_loading.execute(repo,claimed,'local-qa',root,lambda *_:None)
      repo.complete_recognition_job(claimed['job_id'],worker_id='local-qa')
      saved=repo.get_review('order',owner_user_id=OWNER['user_id']);assert saved['revision']==baseline+1
      assert saved['review']['spring_parameters']['wire_diameter']==review['spring_parameters']['wire_diameter']
      assert saved['review']['drawing_annotations']['annotation_revision']>=3
      # Exercise the actual worker dispatch; local tasks never enter recognition/Qwen.
      worker_review=deepcopy(review); worker_review['drawing_summary']['spring_type']='unknown'
      repo.create_review('workerlocal',worker_review,owner=OWNER,artifact_dir=str(directory))
      client.get('/api/reviews/workerlocal'); task=repo.claim_next_recognition_job('worker-qa')
      runner=workers.RecognitionWorker();runner.worker_id='worker-qa'
      with patch.object(api,'verify_review_roughness',return_value=False),patch.object(api,'reconcile_load_points'),patch.object(workers,'run_recognition_job_record',side_effect=AssertionError('Local verification must not recognize again')):
        runner._process_job(task)
      assert repo.get_recognition_job(task['job_id'],owner_user_id=OWNER['user_id'])['status']=='completed'
      assert repo.get_review('workerlocal',owner_user_id=OWNER['user_id'])['review']['local_verification']['version']==review_loading.VERSION
      assert client.get('/api/reviews/order?metadata_only=true').json()['verification_state']=='completed'
      assert repo.claim_next_recognition_job('local-qa') is None,'Repeated reads do not reschedule completed work'
      # Manual changes win a late background result.
      repo.create_review('race',deepcopy(review),owner=OWNER,artifact_dir=str(directory))
      client.get('/api/reviews/race');job=repo.claim_next_recognition_job('race-worker')
      def update(stage,percent):
        if percent==95:
          current=repo.get_review('race',owner_user_id=OWNER['user_id']);edited=current['review'];edited['drawing_summary']['drawing_name']='人工新名称';repo.save_review('race',edited,expected_revision=current['revision'],owner=OWNER)
      with patch.object(api,'verify_review_roughness',return_value=False),patch.object(api,'reconcile_load_points'),patch('ai_design_review.drawing_annotations.build_annotations',return_value=deepcopy(review['drawing_annotations'])):
        assert review_loading.execute(repo,job,'race-worker',root,update) is False
      assert repo.get_review('race',owner_user_id=OWNER['user_id'])['review']['drawing_summary']['drawing_name']=='人工新名称'
      p95=sorted(times)[18];assert p95<1,p95
      print('Read P95_ms=',round(p95*1000,1))
    repo.dispose()
  print('PASS bounded six-page rendering/JPEG, shared rendering, crop budget, OCR singleton/lock, safe 400 diagnostics, pure reads, hidden local tasks, CAS/manual protection and read P95<1s')
if __name__=='__main__':main()
