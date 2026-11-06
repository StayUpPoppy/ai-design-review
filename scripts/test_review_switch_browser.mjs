import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import vm from 'node:vm';
import {createRequire} from 'node:module';import {execFileSync} from 'node:child_process';
const {chromium}=createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixture=JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_solidworks_export.py','--json'],{encoding:'utf8',maxBuffer:4*1024*1024}))[0].review;
const frontend=path.resolve('frontend'),output=path.resolve('outputs/review-performance-qa');fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{const p=path.resolve(frontend,new URL(req.url,'http://localhost').pathname.slice(1)||'index.html');if(!p.startsWith(frontend+path.sep)||!fs.existsSync(p))return res.writeHead(404).end();res.setHeader('Content-Type',p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(p));});await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
const reviews=new Map(['a','b','c','d'].map(id=>[id,{review:structuredClone(fixture),revision:1}]));let gate=null,release=null,held=false,failMetadata=false,failSave=false,expired=false;let fullReads=0,metadataReads=0;
function meta(id){return {job_id:id,review_revision:reviews.get(id).revision,annotation_revision:1,source_document_id:id,preview_version:'bounded-v1',verification_state:'completed'};}
function annotation(id){return {source_document_id:id,annotation_revision:1,annotations:[],pages:[{page:1,width:1200,height:800,preview_width:600,preview_height:400,image_url:'/api/demo-image'}]};}
await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),p=url.pathname;
if(p==='/api/session')return route.fulfill({json:{identity:{user_id:'performance-qa',username:'离线演示',real_name:'离线演示'}}});
if(p==='/api/material-catalog')return route.fulfill({json:JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'))});
if(p==='/api/surface-treatment-catalog')return route.fulfill({json:{version:'offline',items:[]}});
if(p==='/api/demo-image')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><rect width="600" height="400" fill="white"/><path d="M80 240L120 120L170 240L220 120L270 240L320 120L370 240L420 120L460 240" fill="none" stroke="#273444" stroke-width="2"/><text x="210" y="320" font-size="18">仅作演示</text></svg>'});
if(p==='/api/reviews')return route.fulfill({json:{reviews:[...reviews].map(([id,r])=>({job_id:id,drawing_name:`演示图纸${id}`,revision:r.revision,recognition_status:'completed',recognition_attempt_count:1}))}});
const match=p.match(/^\/api\/reviews\/([abcd])(?:\/(.*))?$/);if(match){const [,id,action]=match,r=reviews.get(id);
if(!action){if(req.method()==='PATCH'){if(failSave)return route.fulfill({status:503,json:{detail:'模拟保存失败'}});r.review=req.postDataJSON().review;r.revision++;return route.fulfill({json:{review_revision:r.revision,events:[]}});}
if(url.searchParams.has('metadata_only')){metadataReads++;if(expired)return route.fulfill({status:401,json:{detail:'登录已失效'}});if(gate===id){held=true;await new Promise(r=>release=r);}if(failMetadata)return route.fulfill({status:503,json:{detail:'模拟版本核对失败'}});return route.fulfill({json:meta(id)});}
fullReads++;return route.fulfill({json:{...structuredClone(r.review),drawing_summary:{...r.review.drawing_summary,drawing_name:`演示图纸${id}`},review_revision:r.revision,loading_metadata:meta(id),preview_pages:annotation(id).pages,drawing_annotations:annotation(id),image_url:'/api/demo-image'}});}
if(action==='annotations')return route.fulfill({json:annotation(id)});
if(action==='generation-jobs')return route.fulfill({json:{generation_jobs:[],generation_queue_available:true}});
if(action==='generation-readiness')return route.fulfill({json:{generation_readiness:{status:'ready',warnings:[]}}});
}
if(p.endsWith('/reasonableness'))return route.fulfill({json:{parameter_reasonableness:{status:'ok',issues:[],suggestions:[]}}});
return route.fulfill({json:{status:'ok',recognition_queue_runtime:{status:'available'},generation_runtime:{status:'available'}}});});
const open=id=>page.evaluate(id=>openPersistedReview(id),id);
try{
await page.goto(process.env.PERFORMANCE_FRONTEND_URL||`http://127.0.0.1:${server.address().port}`);await page.waitForFunction(()=>state.identityReady&&state.recentReviews.length===4);
await open('a');await page.waitForFunction(()=>document.querySelector('#compareImage')?.naturalWidth);await open('b');
await page.evaluate(()=>window.keptViewport=document.querySelector('#compareViewport'));
const originalReads=fullReads;gate='a';held=false;
await page.evaluate(()=>{window.switching=openPersistedReview('a');});await page.waitForFunction(()=>state.lastJob?.job_id==='a'&&reviewReadOnly());
while(!held)await new Promise(r=>setTimeout(r,10));
assert.equal(await page.locator('.compare-data-panel').evaluate(el=>el.inert),true);
const priorScale=await page.evaluate(()=>state.compareView.scale);await page.locator('[data-view-action="zoom-in"]').click();assert.ok(await page.evaluate(()=>state.compareView.scale)>priorScale);
await page.locator('[data-view-action="rotate-right"]').click();assert.equal(await page.evaluate(()=>state.compareView.rotation),90);
release();gate=null;await page.evaluate(()=>window.switching);assert.equal(await page.evaluate(()=>reviewReadOnly()),false);assert.equal(fullReads,originalReads,'Matching metadata avoids a second full read');
assert.equal(await page.evaluate(()=>window.keptViewport===document.querySelector('#compareViewport')),true,'Viewer node is reused');
// A failed check must retain an explicitly read-only cached snapshot.
await open('b');failMetadata=true;await open('a');assert.equal(await page.evaluate(()=>reviewReadOnly()),true);assert.match(await page.locator('#reviewLoadNotice').innerText(),/版本核对失败/);
failMetadata=false;await page.locator('#reviewLoadNotice button').click();await page.waitForFunction(()=>!reviewReadOnly());
// A new server revision replaces the saved snapshot after validation.
await open('b');reviews.get('a').revision++;reviews.get('a').review.spring_parameters.free_length.value=77;await open('a');assert.equal(await page.evaluate(()=>state.review.spring_parameters.free_length.value),77);
// Late validation of A cannot override C.
await open('b');gate='a';held=false;await page.evaluate(()=>{window.late=openPersistedReview('a');});while(!held)await new Promise(r=>setTimeout(r,10));await open('c');release();gate=null;await page.evaluate(()=>window.late);assert.equal(await page.evaluate(()=>state.lastJob.job_id),'c');assert.equal(await page.evaluate(()=>reviewReadOnly()),false);
const latencies=[];for(let n=0;n<21;n++){const id=['a','b','c'][n%3];const t=performance.now();await open(id);latencies.push(performance.now()-t);}
assert.ok(await page.evaluate(()=>reviewSwitchCache.stats().entries)<=3);assert.ok(await page.evaluate(()=>reviewSwitchCache.stats().pixelBytes)<=128*1024*1024);
assert.equal(await page.locator('.message-body[data-review-message-id]').count(),1,'Switching does not accumulate full review cards');
assert.equal(await page.locator('#compareViewport').count(),1);
assert.ok(Math.max(...latencies)<1000,JSON.stringify(latencies));
await open('d');assert.ok(await page.evaluate(()=>reviewSwitchCache.stats().entries)<=3);
// Dirty data must not enter the cache or allow a failed save to switch orders.
failSave=true;const beforeFailure=fullReads;const input=page.locator('[data-role="drawing-name"]:visible');
await input.fill('未保存草稿');await input.press('Tab');await open('b');
assert.equal(await page.evaluate(()=>state.lastJob.job_id),'d');assert.equal(fullReads,beforeFailure);
assert.equal(await page.evaluate(()=>state.review.drawing_summary.drawing_name),'未保存草稿');
failSave=false;await page.evaluate(()=>flushReviewPersistence());
// Session-only cache enforces the pixel budget even for a single very large decode.
const cacheProof=await page.evaluate(()=>{
 const previous=globalThis.Image;const images=[];
 globalThis.Image=class {naturalWidth=6000;naturalHeight=6000;set src(value){this.url=value;}constructor(){images.push(this);}};
 try {const cache=ReviewSwitchCache.create();cache.reset('service1/user1');cache.put('a',{review:{value:1}});cache.preload('a','mock');
 const bytes=cache.stats().pixelBytes;const released=images[0].url==='';cache.reset('service1/user2');const userCount=cache.stats().entries;
 cache.put('a',{review:{value:2}});cache.reset('service2/user2');return {bytes,released,userCount,serviceCount:cache.stats().entries};}
 finally{globalThis.Image=previous;}
});assert.deepEqual(cacheProof,{bytes:0,released:true,userCount:0,serviceCount:0});
await page.screenshot({path:path.join(output,'desktop.png')});await page.setViewportSize({width:420,height:900});await page.screenshot({path:path.join(output,'mobile.png')});
expired=true;await open('b');assert.equal(await page.evaluate(()=>reviewSwitchCache.stats().entries),0);assert.equal(await page.evaluate(()=>state.review),null);
assert.deepEqual(errors,[]);console.log('PASS cached display/metadata lock, usable viewer, matching and changed versions, failed check/retry, late-response isolation, 21 switches/LRU/pixel limits/node reuse; max switching_ms=',Math.round(Math.max(...latencies)),'full=',fullReads,'metadata=',metadataReads);
}finally{await browser.close();await new Promise(r=>server.close(r));}
