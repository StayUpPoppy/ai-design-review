import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixtures=JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_formula_candidates.py','--json'],{encoding:'utf8'}));
const frontend=path.resolve('frontend'),catalog=JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
const server=http.createServer((req,res)=>{
  const file=path.resolve(frontend,new URL(req.url,'http://localhost').pathname.slice(1)||'index.html');
  if(!file.startsWith(frontend+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
let browser;
try {
  browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1600,height:1000}}), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  let saved=structuredClone(fixtures[0].review),revision=7,failNext=false,failUntilRetry=false;
  await page.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()).pathname;
    let body={status:'ok',generation_runtime:{status:'not_configured'},recognition_queue_runtime:{status:'not_configured'}};
    if(url==='/api/material-catalog')body=catalog;
    else if(url==='/api/reviews/candidate'&&req.method()==='PATCH'){
      if(failNext||failUntilRetry){failNext=false;return route.fulfill({status:503,json:{detail:'模拟保存失败'}});}
      const input=req.postDataJSON();saved=input.review;body={review_revision:++revision,events:input.events.map(e=>({...e,sync_status:'saved'}))};
    }else if(url==='/api/reviews/candidate')body={...saved,job_id:'candidate',review_revision:revision,image_url:''};
    else if(url==='/api/reviews/reasonableness')body={parameter_reasonableness:JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_formula_candidates.py','--assess'],{input:JSON.stringify(req.postDataJSON()),encoding:'utf8'}))};
    else if(url==='/api/session')body={identity:{user_id:'demo',username:'公式候选测试'},mode:'mock'};
    else if(url==='/api/reviews')body={reviews:[]};
    else if(url.endsWith('/changes'))body={events:[]};
    else if(url.endsWith('/generation-jobs'))body={generation_jobs:[],generation_queue_available:false};
    else if(url.endsWith('/generation-readiness'))body={generation_readiness:{status:'needs_confirmation',warnings:[],missing_fields:[],pending_fields:[]},generation_queue_available:false};
    else if(url.endsWith('/annotations'))body={schema_version:'original_annotations/v1',source_document_id:'test',annotation_revision:1,pages:[],annotations:[],warnings:[]};
    await route.fulfill({status:200,json:body});
  });
  await page.goto(process.env.FORMULA_CANDIDATES_FRONTEND_URL||`http://127.0.0.1:${server.address().port}`);
  const reopen=()=>page.evaluate(async()=>{await openPersistedReview('candidate');state.compareTab='parameters';renderCompareOverlay();});
  await reopen();await page.waitForFunction(()=>state.materialCatalog.status==='ready');
  const panel=page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const card=()=>panel.locator('[data-suggestion-id^="formula_candidate:pitch:"]');
  const row=()=>panel.locator('[data-kind="param"][data-field="pitch"]');
  const current=()=>page.evaluate(()=>structuredClone(state.review.spring_parameters.pitch));
  const flush=()=>page.evaluate(()=>flushReviewPersistence());
  await row().evaluate(e=>{for(let n=e.parentElement;n;n=n.parentElement)if(n.tagName==='DETAILS')n.open=true;});
  assert.match(await card().innerText(),/3.4438[\s\S]*3.6125/);
  assert.match(await row().innerText(),/新候选值.*3.6125/);
  assert.match(await card().innerText(),/新公式候选，应用后需重新确认/);
  // Both entry points use the same apply/save path, keep pending, and allow undo after cards disappear.
  await card().locator('[data-role="apply-reasonableness-suggestion"]').click();await flush();
  assert.equal((await current()).value,3.6125);assert.equal((await current()).need_human_review,true);
  await panel.locator('[data-action="undo-reasonableness-application"]').click();await flush();
  assert.equal((await current()).value,3.4438);assert.equal((await current()).need_human_review,false);
  await row().locator('[data-role="apply-formula-candidate"]').click();await flush();
  assert.equal((await current()).value,3.6125);assert.equal((await current()).need_human_review,true);
  await reopen();assert.equal((await current()).value,3.6125);assert.equal((await current()).need_human_review,true);
  // A failed save retains the applied value and exposes retry; retry does not confirm.
  await panel.locator('[data-action="undo-reasonableness-application"]').click();await flush();
  failUntilRetry=true;
  await card().locator('[data-role="apply-reasonableness-suggestion"]').click();
  await page.waitForFunction(()=>Object.keys(state.reviewPersistenceFailedFields).length>0);
  assert.equal((await current()).value,3.6125);assert.equal((await current()).need_human_review,true);
  assert.match(await card().innerText(),/保存失败/);
  failUntilRetry=false;await card().locator('[data-role="apply-reasonableness-suggestion"]').click();await flush();
  // A later independent edit is preserved; a later edit of the applied target blocks undo.
  await row().locator('[data-role="value"]').fill('3.8');
  await panel.locator('[data-action="undo-reasonableness-application"]').click();
  assert.equal((await current()).value,3.8);
  assert.match(await page.evaluate(()=>state.suggestionUndoConflict),/又有修改/);
  // Instant synchronization while typing preserves the source input/caret.
  await flush(); saved=structuredClone(fixtures[0].review);revision++;await reopen();
  const input=panel.locator('[data-kind="param"][data-field="free_length"] [data-role="value"]');
  await input.fill('30.4');
  assert.equal(await input.evaluate(e=>document.activeElement===e),true);
  assert.match(await card().innerText(),/3.8/);
  assert.match(await row().innerText(),/新候选值.*3.8/);
  if (process.env.CAPTURE_FORMULA_CANDIDATES === '1') {
  // Capture the actual card after responsive layout settles; section captures can clip inside the scroll panel.
  fs.mkdirSync('outputs/formula-candidates',{recursive:true});
  await card().screenshot({path:'outputs/formula-candidates/desktop.png'});
  await page.setViewportSize({width:850,height:1000});
  await card().scrollIntoViewIfNeeded();
  await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  assert.ok(await card().evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Card must not overflow');
  await card().screenshot({path:'outputs/formula-candidates/narrow.png'});
  }
  assert.deepEqual(errors,[]);
  console.log('formula candidates browser passed: both entry points, pending, undo, retry, reload, live focus and responsive screenshots');
}finally{await browser?.close();await new Promise(r=>server.close(r));}
