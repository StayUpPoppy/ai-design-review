import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const {chromium}=createRequire(import.meta.url)(process.env.CODEX_NODE_MODULES ? path.join(process.env.CODEX_NODE_MODULES,'playwright') : 'C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixture=JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || '.venv/Scripts/python.exe',['-c',
  'import sys,json;sys.path[:0]=["src","scripts"];from test_template_pdf import fixture;from ai_design_review.template_pdf import readiness;r=fixture();r["generation_settings"]={"drawing_model":"X型","typeface":"宋体","username":""};print(json.dumps({"review":r,"ready":readiness(r)[0]},ensure_ascii=True))'],{encoding:'utf8',maxBuffer:3*1024*1024}));
const pdf=fs.readFileSync('outputs/template-pdf-qa/integration-example.pdf');
const frontend=path.resolve('frontend'),output=path.resolve('outputs/template-pdf-qa');fs.mkdirSync(output,{recursive:true});
const catalog=JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
const server=http.createServer((req,res)=>{
  const file=path.resolve(frontend,new URL(req.url,'http://localhost').pathname.slice(1)||'index.html');
  if(!file.startsWith(frontend+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,channel:process.env.UNIT_TEST_BROWSER_CHANNEL || 'msedge'});
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const reviews=new Map(['a','b'].map(id=>[id,{review:structuredClone(fixture.review),revision:1,pdfs:[]}]));
let failSave=false,hold=false,release=null,posts=0,swPosts=0,missing=false;
await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),api=url.pathname,method=req.method();
  if(api==='/api/session')return route.fulfill({json:{identity:{user_id:'pdf-browser-user',username:'pdf-user',real_name:'测试用户'}}});
  if(api==='/api/material-catalog')return route.fulfill({json:catalog});
  if(api==='/api/reviews')return route.fulfill({json:{reviews:[...reviews].map(([id,m])=>({job_id:id,drawing_name:`图纸${id}`,revision:m.revision,recognition_status:'completed'}))}});
  if(api.startsWith('/api/template-pdfs/'))return route.fulfill({status:200,contentType:'application/pdf',body:pdf});
  const match=api.match(/^\/api\/reviews\/(a|b)(?:\/(.*))?$/);
  if(match){
    const[,id,action]=match,m=reviews.get(id);
    if(!action){
      if(method==='PATCH'){
        if(failSave)return route.fulfill({status:503,json:{detail:'模拟保存失败'}});
        const body=req.postDataJSON();assert.equal(body.expected_revision,m.revision);m.review=body.review;m.revision++;
        return route.fulfill({json:{review_revision:m.revision,events:body.events||[]}});
      }
      return route.fulfill({json:{...m.review,job_id:id,review_revision:m.revision}});
    }
    if(action==='template-pdf-readiness')return route.fulfill({json:{...structuredClone(fixture.ready),review_id:id,review_revision:m.revision,
      readiness:{...fixture.ready.readiness,...(missing?{status:'blocked',summary:'模板 PDF 资源未配置',blocking_reasonableness:[{field:'template',reason:'模板 PDF 资源未配置'}]}:{})}}});
    if(action==='template-pdfs'){
      if(method==='POST'){
        posts++;const body=req.postDataJSON();assert.equal(body.expected_review_revision,m.revision);assert.equal(m.review.generation_settings.username,'');
        if(hold){hold=false;await new Promise(resolve=>release=resolve);}
        const row={pdf_id:`pdf-${posts}`,review_id:id,review_revision:m.revision,created_at:'2026-11-22T08:30:00Z',filename:`${m.review.drawing_summary.drawing_name}.pdf`,url:`/api/template-pdfs/pdf-${posts}/file`,inline_url:`/api/template-pdfs/pdf-${posts}/file?inline=true`};m.pdfs.unshift(row);
        return route.fulfill({status:201,json:{created:true,template_pdf:row}});
      }
      return route.fulfill({json:{review_id:id,template_pdfs:m.pdfs}});
    }
    if(action==='generation-readiness')return route.fulfill({json:{review_revision:m.revision,generation_readiness:{status:'ready',confirmed_core_count:8,core_field_count:8,warnings:[]}}});
    if(action==='generation-jobs'){if(method==='POST')swPosts++;return route.fulfill({json:{generation_jobs:[]}});}
    if(action==='generation-package')return route.fulfill({json:{review_id:id,review_revision:m.revision,parameter_package:{},technical_requirements_projection:fixture.ready.technical_requirements_projection}});
    if(action==='annotations')return route.fulfill({json:{pages:[],annotations:[]}});
    if(action==='changes')return route.fulfill({json:{events:[]}});
  }
  if(api.endsWith('/reasonableness'))return route.fulfill({json:{parameter_reasonableness:{status:'ok',issues:[],suggestions:[]}}});
  return route.fulfill({json:{status:'ok',generation_runtime:{status:'available'},recognition_queue_runtime:{status:'available'}}});
});
const root=page.locator('.compare-overlay');
const panel=()=>root.locator('.template-pdf-panel');
const create=()=>panel().locator('[data-template-pdf-action="create"]');
async function open(id){
  await page.evaluate(async id=>{await openPersistedReview(id);await loadGenerationState(id,{render:false});state.compareTab='generation';renderCompareOverlay();},id);
  await create().waitFor();await page.waitForFunction(()=>!document.querySelector('.compare-overlay [data-template-pdf-action="create"]')?.disabled);
}
async function waitFor(predicate,message){const deadline=Date.now()+15000;while(!predicate()){if(Date.now()>deadline)throw new Error(message);await new Promise(resolve=>setTimeout(resolve,30));}}
try{
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.identityReady&&state.recentReviews.length===2);
  await open('a');
  assert.equal(await page.evaluate(()=>GenerationSettings.error(GenerationSettings.values(state.review,state.identity))), '请填写生图人姓名。', 'SW still validates its required name');
  assert.equal(await create().isEnabled(),true,'blank SW name does not block template PDF');
  failSave=true;
  await page.evaluate(()=>{state.review.drawing_summary.drawing_name='待保存名称';queueReviewAuditEvent({event_type:'test_title',target_field:'drawing_summary.drawing_name',source:'human',after_state:{value:'待保存名称'}});});
  await panel().locator('[data-template-pdf-action="reload"]').click();await page.waitForTimeout(250);
  await create().click();await waitFor(()=>posts===0,'no generation before save');
  await panel().locator('.template-pdf-error').waitFor();assert.equal(posts,0);
  failSave=false;
  await page.evaluate(async()=>{await flushReviewPersistence({throwOnError:true});});
  await panel().locator('[data-template-pdf-action="reload"]').click();
  await page.waitForFunction(()=>!document.querySelector('.compare-overlay [data-template-pdf-action="create"]').disabled);
  await create().click();await waitFor(()=>posts===1,'PDF request did not arrive');
  await panel().locator('[data-template-pdf-action="preview"]').first().waitFor();
  assert.equal(swPosts,0);
  await panel().locator('[data-template-pdf-action="preview"]').first().click();
  const dialog=page.locator('.template-pdf-dialog');await dialog.waitFor();assert.match(await dialog.locator('iframe').getAttribute('src'),/^blob:/);
  const closeButton=dialog.getByRole('button',{name:'关闭模板 PDF 预览'});
  assert.equal(await closeButton.evaluate(el=>el.scrollWidth<=el.clientWidth),true,'close label fits its control');
  await page.waitForTimeout(1200);await page.screenshot({path:path.join(output,'preview-desktop.png')});
  await closeButton.click();await page.setViewportSize({width:390,height:844});
  await panel().locator('[data-template-pdf-action="preview"]').first().click();await dialog.waitFor();await page.waitForTimeout(1200);
  await page.screenshot({path:path.join(output,'preview-mobile.png')});
  await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
  assert.equal(await root.isVisible(),true,'Escape closes the PDF without closing the review workbench');
  await page.setViewportSize({width:1440,height:1050});
  const download=page.waitForEvent('download');await panel().locator('[data-template-pdf-action="download"]').first().click();
  await(await download).saveAs(path.join(output,'browser-download.pdf'));
  hold=true;await create().click();await waitFor(()=>release!==null,'pending generation did not arrive');
  assert.equal(await create().isDisabled(),true);
  await open('b');release();release=null;await page.waitForTimeout(300);
  assert.equal(await panel().locator('[data-template-pdf-action="preview"]').count(),0,'old order result must not appear in new order');
  await open('a');
  missing=true;await panel().locator('[data-template-pdf-action="reload"]').click();await page.waitForTimeout(250);
  assert.equal(await create().isDisabled(),true);
  await panel().locator('[data-template-pdf-action="preview"]').first().click();await dialog.waitFor();await dialog.getByRole('button',{name:'关闭模板 PDF 预览'}).click();
  missing=false;await panel().locator('[data-template-pdf-action="reload"]').click();await page.waitForTimeout(250);
  reviews.get('a').revision++;
  await panel().locator('[data-template-pdf-action="reload"]').click();
  await panel().locator('.template-pdf-error').filter({hasText:'审图版本已更新'}).waitFor();
  assert.equal(await create().isDisabled(),true,'unseen server revision must not silently become the PDF source');
  await open('a');
  await panel().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'desktop.png')});
  await page.setViewportSize({width:390,height:844});await panel().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'mobile.png')});
  const box=await panel().boundingBox();assert.ok(box.width<=390,'PDF panel must fit mobile width');
  assert.deepEqual(errors,[]);assert.equal(swPosts,0);
  console.log('PASS actual UI: blank SW settings, save-before-create, failed save, PDF generation/preview/download, busy state, order switching, missing resources, desktop/mobile');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
