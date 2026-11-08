import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const cases = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_solidworks_export.py', '--json'], {encoding:'utf8', maxBuffer:4*1024*1024}));
const base = structuredClone(cases.find(c=>c.name==='optional_all').review);
base.load_point_diagnostics = [1,2].map(i=>({candidate_id:`candidate-${i}`,status:'pending',reason:'候选验收',evidence:'原始候选依据',
  original_candidate:{reported_units:{height_unit:'cm',force_unit:'kN'},value:{label:`F${29+i}`,height:.5,height_unit:'cm',force:.02,force_unit:'kN',load_tolerance_upper:.001,load_tolerance_lower:-.002}}}));
const models = new Map(['a','b'].map(id=>[id,{review:structuredClone(base),revision:1}]));
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
const front=path.resolve('frontend'), server=http.createServer((req,res)=>{
  const file=path.resolve(front,new URL(req.url,'http://localhost').pathname.slice(1)||'index.html');
  if(!file.startsWith(front+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
let failSave=false,patches=0;
page.on('pageerror',e=>errors.push(e.stack));
await page.route('**/api/**',async route=>{
  const req=route.request(),api=new URL(req.url()).pathname,match=api.match(/^\/api\/reviews\/(a|b)(?:\/(.*))?$/);
  let body;
  if(api==='/api/session')body={identity:{user_id:'load-create-user',username:'新增载荷验收'}};
  else if(api==='/api/material-catalog')body=catalog;
  else if(api==='/api/reviews')body={reviews:[...models].map(([id,m])=>({job_id:id,drawing_name:`图纸${id}`,revision:m.revision,recognition_status:'completed'}))};
  else if(match){const[,id,action]=match,m=models.get(id);
    if(!action&&req.method()==='PATCH'){
      if(failSave)return route.fulfill({status:503,json:{detail:'模拟保存失败'}});
      const input=req.postDataJSON();assert.equal(input.expected_revision,m.revision);m.review=input.review;patches++;body={review_revision:++m.revision,events:input.events};
    }else if(!action)body={...m.review,job_id:id,review_revision:m.revision,image_url:''};
    else if(action==='reasonableness')body={parameter_reasonableness:{status:'ok',issues:[],suggestions:[]}};
    else if(action==='generation-readiness')body={generation_readiness:{status:'ready',warnings:[],pending_fields:[],missing_fields:[]}};
    else if(action==='generation-jobs')body={generation_jobs:[],generation_queue_available:false};
    else if(action==='annotations')body={pages:[],annotations:[],annotation_revision:1};
    else body={events:[]};
  }else body={status:'ok',generation_runtime:{status:'not_configured'},recognition_queue_runtime:{status:'not_configured'}};
  await route.fulfill({json:body});
});
const panel=page.locator('[data-compare-panel="parameters"]'),form=panel.locator('[data-kind="load_point_create"]');
const editor=form.locator('[data-tolerance-editor]'),field=name=>form.locator(`[data-role="new-load-${name}"]`);
const action=name=>editor.locator(`[data-tolerance-action="${name}"]`),mode=name=>editor.locator(`[data-tolerance-mode="${name}"]`).click();
const upper=()=>editor.locator('[data-tolerance-input="upper"]'),lower=()=>editor.locator('[data-tolerance-input="lower"]');
const edit=()=>form.locator('[data-tolerance-action="open"]').click(),cancel=()=>form.locator('[data-action="cancel-load-point-create"]').click();
const open=async(id='a')=>{await page.waitForFunction(()=>!state.busy);await page.evaluate(async id=>{await openPersistedReview(id);state.compareTab='parameters';renderCompareOverlay();},id);await page.waitForFunction(id=>state.lastJob?.job_id===id,id);};
const flush=()=>page.evaluate(()=>flushReviewPersistence({throwOnError:true}));
const fresh=async(label,force='10')=>{await panel.locator('[data-action="show-load-point-create"]').click();await field('label').fill(label);await field('height').fill('20');await field('force').fill(force);};
const add=async()=>{await form.evaluate(f=>{f.requestSubmit();f.requestSubmit();});await flush();};
const point=label=>page.evaluate(label=>structuredClone(state.review.spring_parameters.load_points.find(p=>p.label===label)),label);
const row=label=>panel.locator('[data-kind="load_point"]').filter({has:page.locator(`.data-label > strong[title="${label}"]`)});
try {
  await page.goto(process.env.LOAD_CREATE_FRONTEND_URL||`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.identityReady&&state.materialCatalog.status==='ready');await open();
  const baselineCount=await panel.locator('[data-kind="load_point"]').count();
  await fresh('F10');const beforeEditing=patches;
  await edit();await mode('pair');await upper().fill('+0.1');await lower().fill('-0.2');
  assert.equal(await editor.locator('[data-tolerance-preview]').innerText(),'9.8 ～ 10.1 N');
  await field('force').fill('12');
  assert.equal(await editor.locator('[data-tolerance-preview]').innerText(),'11.8 ～ 12.1 N');
  assert.match(await editor.locator('[data-tolerance-nominal]').innerText(),/12 N/);
  await page.evaluate(()=>renderCompareOverlay());
  assert.equal(await field('label').inputValue(),'F10');assert.equal(await upper().inputValue(),'+0.1');
  await form.evaluate(f=>f.requestSubmit());
  assert.equal(await editor.count(),1);assert.equal(await panel.locator('[data-kind="load_point"]').count(),baselineCount);
  await row('F1').locator('[data-tolerance-action="open"]').click();
  assert.equal(await editor.count(),1,'Only one tolerance draft is active');
  await upper().press('Enter');
  assert.equal(await editor.count(),0);assert.equal(await field('tolerance').inputValue(),'+0.1/-0.2');
  assert.equal(patches,beforeEditing,'Saving a new tolerance does not persist a point');
  await add();assert.equal(await form.isVisible(),false);
  let p=await point('F10');assert.deepEqual([p.load_tolerance_upper,p.load_tolerance_lower,p.load_tolerance_percent,p.need_human_review],[.1,-.2,null,true]);
  assert.equal(await page.evaluate(()=>state.review.spring_parameters.load_points.filter(p=>p.label==='F10').length),1,'Repeated submission creates one point');
  assert.equal(await page.evaluate(()=>makeGenerationParameterPackage().generation_parameters.load_points.some(p=>p.label==='F10')),false);
  await row('F10').locator('[data-tolerance-action="open"]').click();
  const existing=panel.locator('[data-tolerance-editor]');await existing.locator('[data-tolerance-mode="percent"]').click();
  await existing.locator('[data-tolerance-input="magnitude"]').fill('5');await existing.locator('[data-tolerance-action="save"]').click();
  await row('F10').locator('[data-role="confirm"]').click();await flush();
  await page.reload();await page.waitForFunction(()=>state.identityReady&&state.materialCatalog.status==='ready');await open();
  p=await point('F10');assert.deepEqual([p.load_tolerance_upper,p.load_tolerance_lower,p.load_tolerance_percent,p.need_human_review],[null,null,5,false]);
  await fresh('F11','8');await field('tolerance').fill('±1');await edit();
  await editor.locator('[data-tolerance-input="magnitude"]').fill('2');await editor.locator('[data-tolerance-input="magnitude"]').press('Escape');
  assert.equal(await form.isVisible(),true);assert.equal(await field('tolerance').inputValue(),'±1');
  await edit();await mode('pair');await upper().fill('3');await cancel();
  assert.equal(await form.isVisible(),false);assert.equal(await point('F11'),undefined);
  await fresh('F11','8');
  for(const invalid of ['+0.1/','-0.2/+0.1','±-1','Infinity/0']){
    await field('tolerance').fill(invalid);await form.evaluate(f=>f.requestSubmit());
    assert.ok(await form.locator('[data-role="load-point-create-error"]').innerText());
    assert.equal(await point('F11'),undefined);assert.equal(await field('label').inputValue(),'F11');
  }
  await edit();await mode('pair');await upper().fill('+0.1');await lower().fill('');assert.equal(await action('save').isDisabled(),true);
  await lower().fill('0');await action('save').click();await add();
  p=await point('F11');assert.deepEqual([p.load_tolerance_upper,p.load_tolerance_lower],[.1,0]);
  for(const [label,tolerance,expected] of [['F12','±0.2',[.2,-.2,null]],['F13','0/0',[0,0,null]],['F14','0/-0.2',[0,-.2,null]],['F15','±5%',[null,null,5]],['F16','',[null,null,null]]]){
    await fresh(label);await field('tolerance').fill(tolerance);await add();p=await point(label);
    assert.deepEqual([p.load_tolerance_upper,p.load_tolerance_lower,p.load_tolerance_percent],expected,label);
  }
  await fresh('F17','');await edit();await editor.locator('[data-tolerance-input="magnitude"]').fill('1');
  assert.match(await editor.locator('[data-tolerance-preview]').innerText(),/补齐/);
  await action('clear').click();await action('save').click();await add();
  assert.equal((await point('F17')).force,null);
  await fresh('F20','15');await field('tolerance').fill('±0.5');
  await page.evaluate(()=>renderCompareOverlay());assert.equal(await field('label').inputValue(),'F20');
  await open('b');assert.equal(await form.isVisible(),false);
  await fresh('F21','25');await edit();await mode('percent');await editor.locator('[data-tolerance-input="magnitude"]').fill('10');await action('save').click();
  await open('a');assert.equal(await field('label').inputValue(),'F20');assert.equal(await field('tolerance').inputValue(),'±0.5');
  await open('b');assert.equal(await field('label').inputValue(),'F21');assert.equal(await field('tolerance').inputValue(),'±10%');await cancel();
  await open('a');await cancel();
  const candidate=id=>panel.locator(`[data-candidate-id="candidate-${id}"] [data-action="promote-load-candidate"]`);
  await fresh('F22');await candidate(1).click();
  assert.equal(await field('label').inputValue(),'F22');assert.match(await form.locator('[data-role="load-point-create-error"]').innerText(),/先添加或取消/);
  await cancel();await candidate(1).click();
  assert.deepEqual(await Promise.all([field('label').inputValue(),field('height').inputValue(),field('force').inputValue()]),['F30','5','20']);
  await edit();await mode('pair');assert.equal(Number(await upper().inputValue()),1);assert.equal(Number(await lower().inputValue()),-2);
  assert.equal(await editor.locator('[data-tolerance-preview]').innerText(),'18 ～ 21 N');await action('save').click();
  await candidate(2).click();assert.equal(await field('label').inputValue(),'F30');
  await add();p=await point('F30');assert.equal(p.recognition_candidate_id,'candidate-1');assert.equal(p.evidence,'原始候选依据');
  assert.deepEqual([p.load_tolerance_upper,p.load_tolerance_lower],[1,-2]);
  assert.equal(await page.evaluate(()=>state.review.load_point_diagnostics[0].status),'promoted');
  await fresh('F99');await field('tolerance').fill('+0.5/-0.25');failSave=true;await form.evaluate(f=>f.requestSubmit());
  await page.waitForFunction(()=>Object.keys(state.reviewPersistenceFailedFields).length>0);
  const failedId=(await point('F99')).load_point_id;assert.equal(await form.isVisible(),false);
  failSave=false;await flush();await row('F99').locator('[data-role="confirm"]').click();await flush();
  assert.equal(models.get('a').review.spring_parameters.load_points.filter(p=>p.label==='F99').length,1);
  assert.equal((await point('F99')).load_point_id,failedId);
  await page.reload();await page.waitForFunction(()=>state.identityReady&&state.materialCatalog.status==='ready');await open();
  assert.equal((await point('F99')).load_tolerance_lower,-.25);
  await fresh('FX','20');await edit();await mode('pair');await upper().fill('+0.1');await lower().fill('-0.2');
  fs.mkdirSync('outputs/load-point-create-qa',{recursive:true});
  for(const [name,pane] of [['wide',760],['sidebar',430]]){
    await page.evaluate(pane=>{let style=document.getElementById('create-layout-qa');if(!style){style=document.createElement('style');style.id='create-layout-qa';document.head.append(style);}style.textContent=`#compareOverlay .compare-layout{grid-template-columns:minmax(0,1fr) ${pane}px}`;},pane);
    await editor.scrollIntoViewIfNeeded();
    const m=await form.evaluate(form=>{
      const box=n=>n.getBoundingClientRect(),all=[...form.querySelectorAll('[data-role^="new-load-"]')],edit=form.querySelector('.tolerance-editor');
      return {width:form.clientWidth,columns:getComputedStyle(form).gridTemplateColumns.split(' ').length,overflow:form.scrollWidth>form.clientWidth+1,
        editorFits:box(edit).width<=form.clientWidth,inputsFit:all.every(input=>box(input).x>=box(form).x&&box(input).right<=box(form).right),
        preview:edit.querySelector('[data-tolerance-preview]').textContent};
    });
    assert.equal(m.columns,name==='wide'?4:2);assert.equal(m.overflow,false);assert.equal(m.editorFits,true);assert.equal(m.inputsFit,true);assert.equal(m.preview,'19.8 ～ 20.1 N');
    if(!process.env.SKIP_UI_QA_SCREENSHOTS)await page.screenshot({path:`outputs/load-point-create-qa/${name}.png`});
  }
  await cancel();assert.deepEqual(errors,[]);
  console.log('PASS: new-load tolerance modes, live range, isolated drafts, keyboard, invalid-input blocking, candidate units, add/confirm, retry/reopen and wide/narrow layout; mocked API only');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
