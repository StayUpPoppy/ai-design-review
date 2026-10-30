import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const {chromium}=createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const python=process.env.DESIGN_TEST_PYTHON || '.venv/Scripts/python.exe';
const shared=JSON.parse(execFileSync(python,['scripts/test_load_height_relations.py','--json'],{encoding:'utf8'}));
const base=JSON.parse(execFileSync(python,['scripts/test_solidworks_export.py','--json'],{encoding:'utf8',maxBuffer:4*1024*1024}))[0].review;
const catalog=JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
base.technical_requirements=[];
base.spring_parameters.free_length.value=133.35;
base.spring_parameters.load_points=shared[0].expected.spring_parameters.load_points;
const orders={a:{review:structuredClone(base),revision:1},b:{review:structuredClone(base),revision:1}};
orders.b.review.spring_parameters.free_length.value=200;
const front=path.resolve('frontend');
const server=http.createServer((request,response)=>{const file=path.resolve(front,new URL(request.url,'http://local').pathname.slice(1)||'index.html');if(!file.startsWith(front+path.sep)||!fs.existsSync(file))return response.writeHead(404).end();response.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');response.end(fs.readFileSync(file));});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,channel:'msedge'});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',error=>errors.push(error.message));
let failSave=false,holdSave=false,releaseSave=null,generations=0;
await page.route('**/api/**',async route=>{
  const req=route.request(),api=new URL(req.url()).pathname,m=api.match(/^\/api\/reviews\/(a|b)(?:\/(.*))?$/);
  let body;
  if(api==='/api/session')body={mode:'mock',identity:{user_id:'load-height-ui',username:'载荷测试'}};
  else if(api==='/api/material-catalog')body=catalog;
  else if(api==='/api/reviews')body={reviews:[]};
  else if(m){const[,id,action]=m,order=orders[id];
    if(!action && req.method()==='PATCH'){
      const input=req.postDataJSON();
      if(failSave){failSave=false;return route.fulfill({status:503,json:{detail:'模拟保存失败'}});}
      if(holdSave){holdSave=false;await new Promise(resolve=>{releaseSave=resolve;});}
      assert.equal(input.expected_revision,order.revision);
      order.review=input.review;body={review_revision:++order.revision,events:input.events};
    }else if(!action)body={...order.review,job_id:id,review_revision:order.revision};
    else if(action==='generation-package')body={review_id:id,review_revision:order.revision,parameter_package:await page.evaluate(r=>makeGenerationParameterPackage(r),order.review)};
    else if(action==='generation-readiness')body={review_id:id,review_revision:order.revision,generation_readiness:{status:'ready',warnings:[],missing_fields:[],pending_fields:[]}};
    else if(action==='generation-jobs'){if(req.method()==='POST')generations++;body={generation_jobs:[],generation_queue_available:false};}
    else if(action==='reasonableness')body={parameter_reasonableness:{status:'ok',issues:[],suggestions:[]}};
    else if(action==='annotations')body={pages:[],annotations:[],annotation_revision:1};
    else body={events:[]};
  }else body={status:'ok',generation_runtime:{status:'not_configured'},recognition_queue_runtime:{status:'not_configured'}};
  await route.fulfill({json:body});
});
const panel=page.locator('[data-compare-panel="parameters"]'),row=id=>panel.locator(`[data-kind="load_point"][data-load-point-id="${id}"]`);
const height=id=>row(id).locator('[data-role="height"]');
const h0=()=>panel.locator('[data-field="free_length"] [data-role="value"]');
const open=async(id='a')=>{await page.evaluate(async id=>{await openPersistedReview(id);state.compareTab='parameters';renderCompareOverlay();},id);await page.waitForFunction(()=>state.materialCatalog.status==='ready');};
const flush=()=>page.evaluate(()=>flushReviewPersistence({throwOnError:true}));
try{
  await page.goto(process.env.LOAD_HEIGHT_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.identityReady);await open();
  assert.equal(await height('point1').inputValue(),'125.77');assert.equal(await height('point2').inputValue(),'95.44');
  assert.equal(await row('point1').locator('[data-role="load-tolerance"]').inputValue(),'');
  assert.ok((await row('point2').locator('[data-role="load-tolerance"]').inputValue()).includes('221.96'));
  assert.equal(await row('point1').locator('[data-role="height-relation-note"]').innerText(),'由行程换算，待确认');
  assert.ok((await row('point1').locator('.load-height-evidence').textContent()).includes('参考尺寸'));
  assert.equal(await row('point1').locator('.load-height-evidence').evaluate(e=>e.open),false);
  for(const id of ['point1','point2']){await row(id).locator('[data-role="confirm"]').click();await flush();}
  assert.ok(!(await row('point1').locator('[data-role="height-relation-note"]').innerText()).includes('待确认'));
  const exported=await page.evaluate(()=>makeGenerationParameterPackage());
  assert.equal(exported.generation_parameters.load_points.length,2);
  assert.ok(exported.solidworks_preview.extraProperties['技术要求'].includes('P2：高度 95.44 mm'));
  assert.ok(exported.solidworks_preview.extraProperties['技术要求'].includes('±221.96'));
  const frozen=structuredClone(exported);
  await h0().fill('140');
  assert.equal(await height('point1').inputValue(),'132.42');assert.equal(await height('point2').inputValue(),'102.09');
  assert.equal(await h0().evaluate(e=>e===document.activeElement),true);
  assert.equal(await page.evaluate(()=>state.review.spring_parameters.load_points.every(p=>p.need_human_review)),true);
  await h0().dispatchEvent('change');await flush();
  await row('point1').locator('[data-role="force"]').fill('1200');await row('point1').locator('[data-role="force"]').dispatchEvent('change');await flush();
  assert.equal(await page.evaluate(()=>state.review.spring_parameters.load_points[0].height_relation.mode),'automatic');
  await height('point1').fill('120');await height('point1').dispatchEvent('change');await flush();
  assert.equal(await height('point2').inputValue(),'89.67');
  await h0().fill('150');await h0().dispatchEvent('change');await flush();
  assert.equal(await height('point1').inputValue(),'120');assert.equal(await height('point2').inputValue(),'89.67');
  await open();assert.equal(await height('point1').inputValue(),'120');
  await row('point1').locator('[data-role="rename-load-point"]').click();
  await row('point1').locator('[data-role="label"]').fill('CUSTOM');
  await row('point1').locator('[data-role="save-load-label"]').click();await flush();
  assert.equal(await page.evaluate(()=>state.review.spring_parameters.load_points[1].height_relation.base_point_id),'point1');
  await height('point1').fill('');await height('point1').dispatchEvent('change');await flush();
  assert.equal(await height('point2').inputValue(),'');
  await open();assert.equal(await height('point1').inputValue(),'');
  await height('point1').fill('120');await height('point1').dispatchEvent('change');await flush();
  failSave=true;
  await height('point1').fill('121');await height('point1').dispatchEvent('change');
  assert.equal(await page.evaluate(()=>flushReviewPersistence()),false);
  assert.equal(await height('point1').inputValue(),'121');assert.equal(await height('point2').inputValue(),'90.67');
  await flush();await open();assert.equal(await height('point1').inputValue(),'121');
  holdSave=true;
  await height('point1').fill('122');await height('point1').dispatchEvent('change');
  const flushing=page.evaluate(()=>flushReviewPersistence());
  const deadline=Date.now()+10000;while(!releaseSave){if(Date.now()>deadline)throw new Error('No held save');await new Promise(r=>setTimeout(r,20));}
  // Navigation waits for the current save. Its old response cannot populate the new order.
  const opening=open('b');
  await page.waitForTimeout(30);releaseSave();await flushing;await opening;
  await page.waitForTimeout(40);
  assert.equal(await height('point1').inputValue(),'192.42');assert.equal(await height('point2').inputValue(),'162.09');
  assert.equal(frozen.generation_parameters.load_points[0].height.value,125.77,'Prior frozen export is unchanged');
  await flush();
  await row('point1').locator('.load-height-evidence summary').click();
  fs.mkdirSync('outputs/load-height-qa',{recursive:true});
  if(!process.env.SKIP_UI_QA_SCREENSHOTS)for(const width of [1440,1100,390]){await page.setViewportSize({width,height:width<500?1200:1000});await row('point1').scrollIntoViewIfNeeded();assert.equal(await row('point1').evaluate(e=>e.scrollWidth>e.clientWidth+2),false);await page.screenshot({path:`outputs/load-height-qa/load-${width}.png`});}
  assert.equal(generations,0);assert.deepEqual(errors,[]);
  console.log('PASS: chain heights/force tolerances, confirmation/export, dependency/focus, force-only edit, manual/clear/rename, save retry/reopen and late-order isolation; mocked API only');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
