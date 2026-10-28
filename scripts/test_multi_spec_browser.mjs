import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const frontend = path.resolve('frontend'), output = path.resolve('outputs/multi-spec-qa');
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((req,res) => {
  const file = path.resolve(frontend, new URL(req.url,'http://localhost').pathname.slice(1) || 'index.html');
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); res.end(fs.readFileSync(file));
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const browser = await chromium.launch({ headless:true, channel:'msedge' });
const page = await browser.newPage({viewport:{width:1440,height:1000}}), errors = [], calls = [], receipts = new Map();
page.on('pageerror',e => errors.push(e.message));
const material = JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
let revision = 1, childCounter = 0, loseResponse = false, failAutoLoad = false, childGate = null;
const variants = Array.from({length:13},(_,i) => ({variant_id:`v${i}`,order:i+1,code:`FTA-${10+i}/85-260`,page:1,region:{x:.22,y:.22+i*.033,width:.72,height:.03},
  parameters:{wire_diameter:{value:10+i},mean_diameter:{value:85+i},free_length:{value:260},total_coils:{value:12-i*.25},active_coils:{value:10-i*.25}},issues:i===2?['部位及单位待核对']:[],review:null}));
const source = {job_id:'source',record_kind:'source',drawing_name:'弹簧多规格图纸',recognition_status:'completed',revision:1,variant_count:13,created_count:0,creation_mode:'manual'};
const auto = {...source,job_id:'auto',creation_mode:'auto',recognition_attempt_count:1,created_count:3,variant_count:3,drawing_name:'新自动三规格'};
const automatic = variants.slice(0,3).map((v,i)=>({...v,creation_status:'created',review:{job_id:`auto-child${i}`,record_kind:'variant',parent_review_id:'auto',drawing_name:`自动规格${i+1}`,revision:1}}));
const roots=[source];
const checklist = (id='source') => ({source_id:id,source_revision:revision,creation_mode:id==='auto'?'auto':'manual',drawing_summary:{drawing_name:source.drawing_name},created_count:(id==='auto'?automatic:variants).filter(v=>v.review).length,variants:id==='auto'?automatic:variants,pages:[{page:1,width:2048,height:1243,image_url:'/api/spec-image'}]});
await page.route('**/api/**', async route => {
  const req=route.request(), url=new URL(req.url()), p=url.pathname, method=req.method(); calls.push({p,method,body:req.postDataJSON?.()});
  if(p==='/api/session') return route.fulfill({json:{identity:{user_id:'spec-test',username:'离线验收',org_name:'测试组织',identity_display_enabled:true,is_mock:false}}});
  if(p==='/api/material-catalog') return route.fulfill({json:material});
  if(p==='/api/surface-treatment-catalog') return route.fulfill({json:{version:'test',items:[]}});
  if(p==='/api/spec-image') return route.fulfill({path:'C:/Users/29580/Desktop/多规格2.jpg',contentType:'image/jpeg'});
  if(p==='/api/reviews') return route.fulfill({json:{reviews:roots}});
  if(p==='/api/reviews/source/variants') return route.fulfill({json:checklist()});
  if(p==='/api/reviews/auto/variants') {
    if(failAutoLoad) return route.fulfill({status:503,json:{detail:'本地读取异常'}});
    return route.fulfill({json:checklist('auto')});
  }
  if(p.endsWith('/create-reviews')) {
    const body=req.postDataJSON();
    if(receipts.has(body.idempotency_key)) return route.fulfill({json:receipts.get(body.idempotency_key)});
    if(body.expected_source_revision!==revision) return route.fulfill({status:409,json:{detail:'来源版本已变化，请刷新。'}});
    const reviews=body.variant_ids.map(id=>{const v=variants.find(v=>v.variant_id===id); v.review ||= {job_id:`child${++childCounter}`,parent_review_id:'source',record_kind:'variant',variant_id:id,drawing_name:`弹簧 · ${v.code}`,recognition_status:'completed',revision:1}; v.creation_status='created'; return v.review;});
    source.created_count=variants.filter(v=>v.review).length;
    const result={reviews,source_revision:++revision}; source.revision=revision; receipts.set(body.idempotency_key,result);
    if(loseResponse){loseResponse=false;return route.abort('connectionfailed');} return route.fulfill({json:result});
  }
  if(p==='/api/reviews/source'&&method==='GET') return route.fulfill({json:{record_kind:'source',review_revision:revision,drawing_summary:{drawing_name:source.drawing_name},multi_spec:{variants}}});
  if(p==='/api/reviews/auto'&&method==='GET') return route.fulfill({json:{record_kind:'source',review_revision:revision,drawing_summary:{drawing_name:auto.drawing_name},multi_spec:{variants:automatic}}});
  if(p==='/api/reviews/source'&&method==='DELETE') return route.fulfill({json:{deleted:true,status:'deleted',deleted_ids:['source',...variants.filter(v=>v.review).map(v=>v.review.job_id)],artifact_cleanup:'deleted'}});
  const child=[...variants,...automatic].find(v=>p===`/api/reviews/${v.review?.job_id}`);
  if(child) { if(childGate){const gate=childGate;childGate=null;await gate;} return route.fulfill({json:{record_kind:'variant',review_revision:1,drawing_summary:{drawing_name:child.review.drawing_name,spring_type:'compression_spring'},spring_parameters:{},technical_requirements:[]}}); }
  if(p.endsWith('/generation-jobs')) return route.fulfill({json:{generation_jobs:[],generation_queue_available:false}});
  if(p.endsWith('/annotations')) return route.fulfill({json:{pages:[],annotations:[],warnings:[]}});
  if(p.endsWith('/changes')) return route.fulfill({json:{events:[]}});
  if(p.endsWith('/reasonableness')) return route.fulfill({json:{parameter_reasonableness:{status:'ok',issues:[],suggestions:[]}}});
  return route.fulfill({json:{status:'ok',generation_runtime:{status:'not_configured'},recognition_queue_runtime:{status:'not_configured'}}});
});
const dialog=page.locator('.specification-workbench');
try {
  await page.goto(`http://127.0.0.1:${server.address().port}`); await page.waitForFunction(()=>state.identityReady && state.recentReviews.length===1);
  await page.locator('[data-history-job-id="source"] > [data-role="open-recent-review"]').click(); await dialog.waitFor();
  assert.equal(await dialog.locator('tbody tr').count(),13); assert.equal(await dialog.locator('input').count(),0);
  assert.equal(await dialog.locator('[data-action="create"],[data-action="select-all"]').count(),0);
  assert.match(await dialog.locator('[data-action="fill-missing"]').innerText(),/13/);
  assert.equal(await page.locator('#identityProfileSource').isVisible(),false);
  assert.equal(await page.locator('#identityProfileName').innerText(),'离线验收');
  await dialog.locator('tbody tr').nth(2).locator('.specification-locate').click(); assert.equal(await dialog.locator('rect').getAttribute('y'),'28.6');
  await dialog.locator('img').evaluate(img=>img.decode());
  // An unknown source region must hide the SVG, not leave the previous rect.
  variants[1].region = null;
  await dialog.locator('[data-action="refresh"]').click(); await page.waitForFunction(()=>document.querySelector('.specification-message').textContent.includes('已刷新'));
  await dialog.locator('tbody tr').nth(1).locator('.specification-locate').click();
  assert.equal(await dialog.locator('svg').evaluate(el=>getComputedStyle(el).display),'none');
  await dialog.locator('tbody tr').nth(2).locator('.specification-locate').click();
  assert.notEqual(await dialog.locator('svg').evaluate(el=>getComputedStyle(el).display),'none');
  await page.screenshot({path:path.join(output,'desktop.png')});
  await page.setViewportSize({width:390,height:844}); await page.screenshot({path:path.join(output,'mobile.png')});
  assert.equal(await dialog.evaluate(d=>d.scrollWidth<=d.clientWidth+1),true); await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>{window.originalFlush=flushReviewPersistence;flushReviewPersistence=async()=>false;});
  await dialog.locator('[data-action="fill-missing"]').click(); await page.waitForFunction(()=>document.querySelector('.specification-message').textContent.includes('未保存'));
  assert.equal(calls.filter(c=>c.p.endsWith('/create-reviews')).length,0);
  await page.evaluate(()=>{flushReviewPersistence=window.originalFlush;}); loseResponse=true;
  await dialog.locator('[data-action="fill-missing"]').click(); await page.waitForFunction(()=>document.querySelector('.specification-message').textContent.includes('网络结果不明'));
  await dialog.locator('[data-action="fill-missing"]').click(); await page.waitForFunction(()=>document.querySelector('.specification-message').textContent.includes('已创建或找到13'));
  const creates=calls.filter(c=>c.p.endsWith('/create-reviews')); assert.equal(creates[0].body.idempotency_key,creates[1].body.idempotency_key);assert.equal(childCounter,13);
  assert.equal(await dialog.locator('[data-action="fill-missing"]').isVisible(),false);
  variants[0].review=null;variants[0].creation_status='deleted';source.created_count=12;source.revision=++revision;
  await dialog.locator('[data-action="refresh"]').click(); await page.waitForFunction(()=>document.querySelector('.specification-message').textContent.includes('已刷新'));
  assert.equal(await dialog.locator('[data-action="fill-missing"]').isVisible(),false,'Deleted children are excluded from fill-missing');
  await dialog.getByRole('button',{name:'重新创建审图',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.specification-message').textContent.includes('已创建或找到1'));
  assert.equal(childCounter,14);
  assert.equal(await page.evaluate(()=>state.review),null,'creating does not open a child');
  await dialog.locator('[data-action="close"]').click();
  await page.locator('[data-role="expand-specifications"]').click(); await page.waitForFunction(()=>document.querySelectorAll('.history-source-children .history-order-item').length===13);
  await page.reload(); await page.waitForFunction(()=>state.identityReady && state.recentReviews.length===1);
  await page.locator('[data-history-job-id="source"] > [data-role="open-recent-review"]').click(); await dialog.waitFor();
  assert.equal(await dialog.locator('input').count(),0); assert.equal(await dialog.getByRole('button',{name:'打开审图',exact:true}).count(),13);
  await dialog.getByRole('button',{name:'打开审图',exact:true}).first().click(); await page.waitForFunction(()=>state.lastJob?.job_id==='child14');
  assert.equal(await dialog.count(),0);assert.equal(calls.some(c=>c.p.endsWith('/generation-jobs')&&c.method==='POST'),false);
  await page.evaluate(()=>closeCompareOverlay());
  // Completion automatically expands all children, keeps focus/current draft and leaves the new-result dot.
  roots.push(auto); const beforeCreates=calls.filter(c=>c.p.endsWith('/create-reviews')).length;
  await page.locator('#refreshRecentReviewsButton').focus();
  await page.evaluate(()=>{
    mergeRecognitionStatus('auto',{status:'processing',attempt_count:1,progress:96,record_kind:'source',variant_count:3,created_count:0},{submission:true});
    mergeRecognitionStatus('auto',{status:'completed',attempt_count:1,progress:100,record_kind:'source',variant_count:3,created_count:3,creation_mode:'auto'});
  });
  const autoRow=page.locator('[data-history-job-id="auto"]');
  await page.waitForFunction(()=>document.querySelectorAll('[data-history-job-id="auto"] .history-source-children .history-order-item').length===3);
  assert.equal(await autoRow.locator(':scope > .history-select-button .history-unread-dot').isVisible(),true);
  assert.equal(await page.evaluate(()=>state.lastJob.job_id),'child14');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'refreshRecentReviewsButton');
  assert.equal(calls.filter(c=>c.p.endsWith('/create-reviews')).length,beforeCreates);
  await page.screenshot({path:path.join(output,'automatic-history.png')});
  await autoRow.locator('[data-role="expand-specifications"]').click();
  await page.evaluate(()=>renderRecentReviews());assert.equal(await autoRow.locator('.history-source-children').isVisible(),false);
  await page.reload();await page.waitForFunction(()=>state.recentReviews.length===2);
  assert.equal(await autoRow.locator('.history-source-children').isVisible(),false,'Manual collapse persists across reload');
  await autoRow.locator('[data-role="expand-specifications"]').click();
  await autoRow.locator('[data-history-job-id="auto-child0"] [data-role="open-recent-review"]').click();
  await page.waitForFunction(()=>state.lastJob?.job_id==='auto-child0'&&state.compareOpen);
  assert.equal(await autoRow.locator(':scope > .history-select-button .history-unread-dot').isVisible(),false,'Opening a displayed child acknowledges its source round');
  await page.evaluate(()=>closeCompareOverlay());
  await autoRow.locator(':scope > [data-role="open-recent-review"]').click();await dialog.waitFor();
  assert.equal(await dialog.locator('[data-action="fill-missing"]').isVisible(),false);
  assert.equal(await dialog.getByRole('button',{name:'打开审图',exact:true}).count(),3);
  await dialog.locator('img').evaluate(img=>img.decode());await page.screenshot({path:path.join(output,'automatic-desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'automatic-mobile.png')});
  assert.equal(await dialog.evaluate(d=>d.scrollWidth<=d.clientWidth+1),true);
  await page.setViewportSize({width:1440,height:1000});await dialog.locator('[data-action="close"]').click();
  // A later round expands again. A failed manifest read is retryable, not recognition failure.
  auto.recognition_attempt_count=2;auto.revision=++revision;failAutoLoad=true;
  await page.evaluate(()=>{
    mergeRecognitionStatus('auto',{status:'queued',attempt_count:1,progress:0,record_kind:'source'},{restart:true});
    mergeRecognitionStatus('auto',{status:'processing',attempt_count:2,progress:97,record_kind:'source'});
    mergeRecognitionStatus('auto',{status:'completed',attempt_count:2,progress:100,record_kind:'source',variant_count:3,created_count:3,creation_mode:'auto'});
  });
  await autoRow.getByRole('button',{name:'规格加载失败，点击重试'}).waitFor();
  assert.equal(await autoRow.locator('[data-role="recognition-label"]').first().innerText(),'识别完成');
  failAutoLoad=false;await autoRow.getByRole('button',{name:'规格加载失败，点击重试'}).click();
  await autoRow.locator('[data-history-job-id="auto-child0"]').waitFor();
  // Late child response cannot acknowledge a newer source round.
  let release;childGate=new Promise(r=>release=r);
  await autoRow.locator('[data-history-job-id="auto-child0"] [data-role="open-recent-review"]').click();
  await page.waitForFunction(()=>state.busy);
  await page.evaluate(()=>{
    mergeRecognitionStatus('auto',{status:'queued',attempt_count:2,progress:0,record_kind:'source'},{restart:true});
    mergeRecognitionStatus('auto',{status:'processing',attempt_count:3,progress:97,record_kind:'source'});
    mergeRecognitionStatus('auto',{status:'completed',attempt_count:3,progress:100,record_kind:'source',variant_count:3,created_count:3,creation_mode:'auto'});
  });release(); await page.waitForFunction(()=>!state.busy&&state.compareOpen);
  assert.equal(await autoRow.locator(':scope > .history-select-button .history-unread-dot').isVisible(),true);
  await page.evaluate(()=>closeCompareOverlay());
  await autoRow.locator(':scope > [data-role="expand-specifications"]').click();
  roots.pop();await page.evaluate(()=>{state.recentReviews=state.recentReviews.filter(v=>v.job_id!=='auto');renderRecentReviews();});
  await page.locator('[data-history-job-id="source"] > [data-role="expand-specifications"]').click();
  await page.locator('#enterHistoryManagement').click(); await page.locator('#historySelectAll').click(); await page.locator('#historyDeleteSelected').click();
  await page.locator('.delete-review-dialog').waitFor(); assert.match(await page.locator('.delete-review-dialog').innerText(),/共13条实际审图记录/);
  await page.locator('[data-role="confirm-delete-review"]').click(); await page.waitForFunction(()=>state.deletedReviewIds.has('child2'));
  assert.equal(calls.filter(c=>c.method==='DELETE').length,1,'parent/child selection deduplicates');
  assert.deepEqual(errors,[]); console.log('PASS automatic expansion, collapse persistence, source read receipts/late response, load retry, legacy supplement/recreation, save guard, lost-response idempotency, ERP visibility, parent deletion, desktop/mobile');
} finally {await browser.close();server.close();}
