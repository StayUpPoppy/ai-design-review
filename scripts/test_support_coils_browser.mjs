import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixtures=JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_support_coils.py','--json'],{encoding:'utf8',maxBuffer:4*1024*1024}));
const frontend=path.resolve('frontend'),catalog=JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
const calculate=(review)=>JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_support_coils.py','--assess'],{input:JSON.stringify({review}),encoding:'utf8',maxBuffer:4*1024*1024}));
const server=http.createServer((req,res)=>{
  const file=path.resolve(frontend,new URL(req.url,'http://localhost').pathname.slice(1)||'index.html');
  if(!file.startsWith(frontend+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
let browser;
try {
  browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  let saved=structuredClone(fixtures[0].review),revision=1,failSave=false,holdNext=false,releasePatch;
  await page.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()).pathname;
    let body={status:'ok',generation_runtime:{status:'not_configured'},recognition_queue_runtime:{status:'not_configured'}};
    if(url==='/api/material-catalog')body=catalog;
    else if(url==='/api/reviews/support'&&req.method()==='PATCH'){
      const input=req.postDataJSON();requests.push(input);
      if(holdNext){holdNext=false;await new Promise(r=>{releasePatch=r;});}
      if(failSave)return route.fulfill({status:503,json:{detail:'模拟保存失败'}});
      if(input.expected_revision!==revision)return route.fulfill({status:409,json:{detail:'版本冲突'}});
      saved=calculate(input.review).review;body={review_revision:++revision,events:input.events.map(e=>({...e,sync_status:'saved'}))};
    }else if(url==='/api/reviews/support')body={...calculate(saved).review,job_id:'support',review_revision:revision,image_url:''};
    else if(url==='/api/reviews/reasonableness')body={parameter_reasonableness:calculate(req.postDataJSON().review).assessment};
    else if(url==='/api/session')body={identity:{user_id:'demo',username:'支承圈数测试'},mode:'mock'};
    else if(url==='/api/reviews')body={reviews:[]};
    else if(url.endsWith('/changes'))body={events:[]};
    else if(url.endsWith('/generation-jobs'))body={generation_jobs:[],generation_queue_available:false};
    else if(url.endsWith('/generation-readiness'))body={generation_readiness:{status:'needs_confirmation',warnings:[],missing_fields:[],pending_fields:[]},generation_queue_available:false};
    else if(url.endsWith('/annotations'))body={schema_version:'original_annotations/v1',source_document_id:'test',annotation_revision:1,pages:[],annotations:[],warnings:[]};
    await route.fulfill({status:200,json:body});
  });
  await page.goto(process.env.SUPPORT_COILS_FRONTEND_URL||`http://127.0.0.1:${server.address().port}`);
  const reopen=()=>page.evaluate(async()=>{await openPersistedReview('support');state.compareTab='parameters';renderCompareOverlay();});
  await reopen();await page.waitForFunction(()=>state.materialCatalog.status==='ready');
  const panel=page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const row=f=>panel.locator(`[data-kind="param"][data-field="${f}"]`);
  const current=()=>page.evaluate(()=>structuredClone(state.review.spring_parameters.support_coils));
  const flush=()=>page.evaluate(()=>flushReviewPersistence());
  const expand=()=>row('support_coils').evaluate(e=>{for(let n=e.parentElement;n;n=n.parentElement)if(n.tagName==='DETAILS')n.open=true;});
  const edit=(f,v)=>row(f).locator('[data-role="value"]').fill(String(v));
  const confirm=async f=>{await row(f).locator('[data-role="confirm"]').click();await flush();};
  const assertNoRecognitionDetails=async()=>{
    assert.equal(await row('support_coils').locator('.support-coils-recognition').count(),0);
    assert.doesNotMatch(await row('support_coils').innerText(),/查看原识别依据|原识别值：/);
  };
  await expand();await flush();
  assert.equal((await current()).value,1);assert.equal((await current()).need_human_review,true);
  assert.equal(saved.spring_parameters.support_coils.value,1);
  assert.equal(saved.spring_parameters.support_coils.support_coils_original.value,2);
  await assertNoRecognitionDetails();
  assert.ok(requests.some(r=>r.events.some(e=>e.event_type==='support_coils_recalculated'&&e.before_state.value===2&&e.after_state.value===1)));
  assert.equal(await panel.locator('[data-suggestion-id^="formula_candidate:support_coils:"]').count(),0);
  await confirm('total_coils');await confirm('active_coils');await confirm('support_coils');
  assert.equal((await current()).need_human_review,false);
  // One changed count waits for confirmation, then replaces the confirmed automatic value.
  await edit('total_coils',18);
  assert.equal((await current()).value,1);assert.equal((await current()).support_coils_waiting_confirmation,true);
  assert.equal(await row('total_coils').locator('[data-role="value"]').evaluate(e=>document.activeElement===e),true);
  assert.match(await row('support_coils').innerText(),/等待圈数确认/);
  await confirm('total_coils');
  assert.equal((await current()).value,2);assert.equal((await current()).need_human_review,true);
  assert.equal(await row('support_coils').locator('[data-role="value"]').inputValue(),'2');
  assert.ok(!await page.evaluate(()=>state.review.manual_confirmations.support_coils));
  await confirm('support_coils');
  // Both edited counts, reversed confirmation order; same numeric result reopens support confirmation.
  await edit('total_coils',20);await edit('active_coils',16);
  await confirm('active_coils');assert.equal((await current()).support_coils_waiting_confirmation,true);
  await confirm('total_coils');assert.equal((await current()).value,2);assert.equal((await current()).need_human_review,true);
  await confirm('support_coils');
  await edit('total_coils',22);await edit('active_coils',18);
  await panel.locator('[data-action="confirm-all-review-items"]').click();await flush();
  assert.equal((await current()).value,2);assert.equal((await current()).need_human_review,true,'New result is not confirmed in the same bulk action');
  await reopen();await expand();
  assert.equal((await current()).value,2);assert.equal((await current()).need_human_review,true);
  await assertNoRecognitionDetails();
  assert.equal(saved.spring_parameters.support_coils.support_coils_original.value,2);
  const adjustmentEvents=requests.flatMap(r=>r.events).filter(e=>e.event_type==='support_coils_recalculated');
  assert.ok(adjustmentEvents.some(e=>e.metadata.previous_confirmation?.confirmed));
  // Saving failure retains the computed value and independent pending confirmation.
  failSave=true;await edit('total_coils',24);
  await row('total_coils').locator('[data-role="confirm"]').click();
  await page.waitForFunction(()=>Object.keys(state.reviewPersistenceFailedFields).length>0);
  assert.equal((await current()).value,3);assert.equal((await current()).need_human_review,true);
  failSave=false;await row('total_coils').locator('[data-role="confirm"]').click();await flush();
  assert.equal((await current()).need_human_review,true,'Retry saves without confirming');
  // An older save response must not overwrite a newer confirmed count and support result.
  holdNext=true;await edit('total_coils',26);await row('total_coils').locator('[data-role="confirm"]').click();
  await page.waitForFunction(()=>state.reviewPersistenceSaving);
  while(!releasePatch)await new Promise(r=>setTimeout(r,10));
  await edit('active_coils',20);await row('active_coils').locator('[data-role="confirm"]').click();
  releasePatch();await flush();
  assert.equal((await current()).value,3);assert.equal((await current()).need_human_review,true);
  assert.equal(saved.spring_parameters.total_coils.value,26);assert.equal(saved.spring_parameters.active_coils.value,20);
  await reopen();await expand();assert.equal((await current()).value,3);
  if(process.env.CAPTURE_SUPPORT_COILS==='1'){
    fs.mkdirSync('outputs/support-coils',{recursive:true});await row('support_coils').screenshot({path:'outputs/support-coils/desktop.png'});
    await page.setViewportSize({width:850,height:1000});await row('support_coils').scrollIntoViewIfNeeded();
    await row('support_coils').screenshot({path:'outputs/support-coils/narrow.png'});
  }
  // Protected manual values expose a working formula candidate instead of being overwritten.
  await edit('support_coils',4);
  assert.equal((await current()).value,4);
  assert.match(await row('support_coils').innerText(),/圈数关系需核对/);
  await assertNoRecognitionDetails();
  await row('support_coils').locator('[data-role="apply-formula-candidate"]').click();await flush();
  assert.equal((await current()).value,3);assert.equal((await current()).need_human_review,true);
  assert.equal((await current()).formula_calculation_kind,'support_coils');
  await edit('support_coils','');await flush();await reopen();await expand();
  assert.equal((await current()).value,'','An intentional manual blank must remain blank');
  // A fresh record without a legacy recognition snapshot uses the same compact row.
  saved=structuredClone(fixtures[0].review);delete saved.spring_parameters.support_coils;revision++;
  await reopen();await expand();await flush();
  assert.equal((await current()).value,1);
  assert.ok(!(await current()).support_coils_original);
  await assertNoRecognitionDetails();
  await confirm('total_coils');await confirm('active_coils');await confirm('support_coils');
  await reopen();await expand();
  assert.equal((await current()).need_human_review,false);
  await assertNoRecognitionDetails();
  assert.deepEqual(errors,[]);
  console.log('Support coil browser passed: hidden recognition details for old/new records, retained raw snapshot, correction/audit, confirmations, retry, late-save race and reopen');
}finally{await browser?.close();await new Promise(r=>server.close(r));}
