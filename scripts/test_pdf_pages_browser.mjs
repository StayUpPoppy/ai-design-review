import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const {chromium}=createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixture=JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_solidworks_export.py','--json'],{encoding:'utf8',maxBuffer:4*1024*1024}))[0].review;
const frontend=path.resolve('frontend'),output=path.resolve('outputs/pdf-pages-qa');fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{const file=path.resolve(frontend,new URL(req.url,'http://localhost').pathname.slice(1)||'index.html');if(!file.startsWith(frontend+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],calls=[];
page.on('pageerror',e=>errors.push(e.message));
let tick=0,retries=0;
const entries=Array.from({length:6},(_,i)=>({variant_id:`page-${i+1}`,order:i+1,page:i+1,code:`第${i+1}页`,creation_status:'created',parameters:{},drawing_summary:{drawing_name:`演示图纸 · 第${i+1}页`,drawing_no:`00${i+1}`},issues:[],review:{job_id:`p${i+1}`,record_kind:'variant',parent_review_id:'pdf',page_origin:{source_review_id:'pdf',original_page:i+1,local_page:1},recognition_status:'queued',recognition_attempt_count:0,recognition_progress:0,drawing_name:`演示图纸 · 第${i+1}页`,revision:1}}));
const source=()=>({job_id:'pdf',record_kind:'source',source_kind:'pdf_pages',creation_mode:'auto',drawing_name:'六页独立图纸.pdf',revision:1,created_count:6,variant_count:6,page_state_revision:`state-${tick}`,recognition_status:'processing',recognition_progress:Math.min(99,tick*15),recognition_attempt_count:1,updated_at:new Date(2000000000000+tick*1000).toISOString(),page_results:entries.map(v=>v.review)});
const manifest=()=>({...source(),source_id:'pdf',source_revision:1,drawing_summary:{drawing_name:'六页独立图纸.pdf'},variants:entries,completed_count:entries.filter(v=>v.review.recognition_status==='completed').length,failed_count:entries.filter(v=>v.review.recognition_status==='failed').length,pages:entries.map(v=>({page:v.page,image_url:'/api/offline-image'}))});
await page.route('**/api/**',async route=>{const req=route.request(),p=new URL(req.url()).pathname;calls.push([p,req.method()]);
if(p==='/api/session')return route.fulfill({json:{identity:{user_id:'pdf-qa',username:'离线演示',real_name:'离线演示'}}});
if(p==='/api/material-catalog')return route.fulfill({json:JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'))});
if(p==='/api/surface-treatment-catalog')return route.fulfill({json:{version:'test',items:[]}});
if(p==='/api/offline-image')return route.fulfill({path:'outputs/pdf-intake-inspect/scan-1.png',contentType:'image/png'});
if(p==='/api/reviews')return route.fulfill({json:{reviews:[source()]}});
if(p==='/api/reviews/pdf/variants')return route.fulfill({json:manifest()});
if(p==='/api/reviews/pdf/recognition-status'){const s=source();return route.fulfill({json:{job_id:'pdf',recognition:{...s,status:s.recognition_status,stage:'recognizing_pages',progress:s.recognition_progress,attempt_count:1}}});}
const match=p.match(/^\/api\/reviews\/(p[1-6])(?:\/(.*))?$/);
if(match){const [,id,action]=match,v=entries.find(v=>v.review.job_id===id);
if(action==='retry'){retries++;v.review.recognition_status='queued';tick++;return route.fulfill({status:202,json:{job_id:id,recognition:{job_id:id,status:'queued',attempt_count:1}}});}
if(action==='recognition-status')return route.fulfill({json:{job_id:id,recognition:{job_id:id,status:v.review.recognition_status,progress:0,attempt_count:v.review.recognition_attempt_count}}});
if(!action)return route.fulfill({json:{...structuredClone(fixture),job_id:id,record_kind:'variant',page_origin:v.review.page_origin,drawing_summary:{...fixture.drawing_summary,...v.drawing_summary},image_url:'/api/offline-image',review_revision:1}});
if(action==='annotations')return route.fulfill({json:{pages:[],annotations:[]}});
if(action==='generation-jobs')return route.fulfill({json:{generation_jobs:[],generation_queue_available:true}});
if(action==='generation-readiness')return route.fulfill({json:{generation_readiness:{status:'ready',warnings:[]}}});
}
if(p.endsWith('/reasonableness'))return route.fulfill({json:{parameter_reasonableness:{status:'ok',issues:[],suggestions:[]}}});
return route.fulfill({json:{status:'ok',generation_runtime:{status:'available'},recognition_queue_runtime:{status:'available'}}});});
try{
await page.goto(process.env.PDF_PAGES_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);await page.waitForFunction(()=>state.identityReady&&state.recentReviews.length===1);
await page.waitForFunction(()=>document.querySelectorAll('.history-source-children .history-order-item').length===6);
assert.match(await page.locator('[data-role="expand-specifications"]').innerText(),/图纸/);
const complete=i=>{entries[i].review.recognition_status='completed';entries[i].review.recognition_attempt_count=1;tick++;};complete(0);complete(1);
await page.evaluate(()=>loadRecentReviews());await page.waitForFunction(()=>document.querySelectorAll('.history-source-children .history-unread-dot:not([hidden])').length===2);
await page.locator('[data-history-job-id="pdf"] > [data-role="open-recent-review"]').click();
const dialog=page.locator('dialog.specification-workbench');await dialog.waitFor({state:'visible'});
assert.equal(await dialog.locator('h2').innerText(),'页面核对');assert.equal(await dialog.locator('tbody tr').count(),6);
assert.equal(await dialog.locator('[data-action="fill-missing"]').isVisible(),false);
const manifestReads=calls.filter(c=>c[0].endsWith('/variants')).length;
await dialog.locator('tbody tr').first().evaluate(row=>window.firstPageRow=row);
entries[3].review.recognition_status='processing';entries[3].review.recognition_progress=35;tick++;
await page.evaluate(value=>mergeRecognitionStatus('pdf',value,{requestSerial:++state.recognitionRequestSerial}),source());
assert.equal(await dialog.locator('tbody tr').first().evaluate(row=>row===window.firstPageRow),true,'Unchanged page rows retain their nodes');
assert.match(await dialog.locator('tbody tr').nth(3).innerText(),/35%/);
assert.equal(calls.filter(c=>c[0].endsWith('/variants')).length,manifestReads,'Source and checklist share status updates');

await dialog.locator('tbody tr').nth(4).locator('.specification-locate').click();assert.match(await dialog.locator('[data-role="region-status"]').innerText(),/第5页/);
await dialog.locator('tbody tr').first().getByRole('button',{name:'打开审图',exact:true}).click();
await page.waitForFunction(()=>state.lastJob?.job_id==='p1'&&state.compareOpen);
assert.equal(await page.locator('.compare-overlay [data-role="material-code"]').inputValue(),'');
await page.waitForFunction(()=>!historyOrderIsUnread(findHistoryItem('p1'))&&historyOrderIsUnread(findHistoryItem('p2')));
assert.equal(await page.evaluate(()=>state.recentReviews.length),1,'Children stay inside their file group');
await page.evaluate(()=>closeCompareOverlay());
entries[2].review.recognition_status='failed';entries[2].review.recognition_attempt_count=1;entries[2].issues=['本地模拟失败'];tick++;
await page.evaluate(()=>openPersistedReview('pdf'));await dialog.waitFor({state:'visible'});
await dialog.locator('tbody tr').nth(2).getByRole('button',{name:'重试此页'}).click();assert.equal(retries,1);
assert.equal(await page.evaluate(()=>state.recentReviews.length),1,'Retry does not insert a duplicate top-level child');
await page.screenshot({path:path.join(output,'desktop.png')});await page.setViewportSize({width:420,height:900});await page.screenshot({path:path.join(output,'mobile.png')});
assert.deepEqual(errors,[]);console.log('PASS PDF auto-expand while processing, six independent rows, source checklist, page selection, immediate successful-page review, per-page unread/retry and no duplicate roots; desktop/mobile mock APIs only');
}finally{await browser.close();await new Promise(r=>server.close(r));}
