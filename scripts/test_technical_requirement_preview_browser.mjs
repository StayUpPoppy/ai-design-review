import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES ? path.join(process.env.CODEX_NODE_MODULES, "playwright") : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const cases = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe", ["scripts/test_solidworks_export.py", "--json"], { encoding:"utf8", maxBuffer:4*1024*1024 }));
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const frontend = path.resolve("frontend"), server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, "http://localhost").pathname.slice(1) || "index.html");
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise(resolve => server.listen(0,"127.0.0.1",resolve));
let browser;
try {
  browser = await chromium.launch({headless:true,channel:process.env.UNIT_TEST_BROWSER_CHANNEL || "msedge"});
  const page = await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  const initial = structuredClone(cases[0].review);
  initial.technical_requirements=[];
  Object.assign(initial.spring_parameters.solid_height,{source:["manual"],value_kind:"input_height"});
  const orders={preview:{review:structuredClone(initial),revision:1},other:{review:structuredClone(initial),revision:1}};
  orders.other.review.spring_parameters.total_coils.value=10.5;
  orders.other.review.spring_parameters.active_coils.value=8.25;
  let patches=0, generationPosts=0, failPatch=false, conflictPatch=false, failPackage=false, holdPackage=false, releasePackage=null, serverText=null, invalidRevision=false;
  const packages=[];
  const waitForPackageRelease=async()=>{const deadline=Date.now()+10000;while(!releasePackage){if(Date.now()>deadline)throw new Error("No mocked package request arrived");await new Promise(resolve=>setTimeout(resolve,20));}};
  await page.route("**/api/**",async route=>{
    const request=route.request(), apiPath=new URL(request.url()).pathname;
    const match=apiPath.match(/^\/api\/reviews\/(preview|other)(?:\/(.*))?$/);
    let body;
    if(apiPath==="/api/session") body={mode:"mock",identity:{user_id:"preview-user",username:"预览测试"}};
    else if(apiPath==="/api/material-catalog") body=catalog;
    else if(apiPath==="/api/surface-treatment-catalog") body={version:"test",items:[{id:"zinc",name:"电镀-镀彩锌"}]};
    else if(match){
      const [,id,action]=match, order=orders[id];
      if(!action && request.method()==="PATCH"){
        patches++;
        if(failPatch){failPatch=false;return route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"模拟保存失败"})});}
        const input=request.postDataJSON();assert.equal(input.expected_revision,order.revision);
        if(conflictPatch){conflictPatch=false;order.revision++;order.review.drawing_summary.drawing_name="服务器保留名称";return route.fulfill({status:409,json:{detail:"模拟版本冲突"}});}
        order.review=input.review;body={review_revision:++order.revision,events:(input.events||[]).map(event=>({...event,sync_status:"saved"}))};
      }else if(!action) body={...order.review,job_id:id,review_revision:order.revision,image_url:""};
      else if(action==="generation-package"){
        const revision=order.revision, review=structuredClone(order.review), text=serverText, wrongRevision=invalidRevision;invalidRevision=false;
        packages.push({id,revision});
        if(holdPackage){holdPackage=false;await new Promise(resolve=>{releasePackage=resolve;});}
        if(failPackage){failPackage=false;return route.fulfill({status:503,contentType:"application/json",body:'{"detail":"模拟核对失败"}'});}
        const parameterPackage=await page.evaluate(review=>makeGenerationParameterPackage(review),review);
        if(text!==null) parameterPackage.solidworks_preview.extraProperties["技术要求"]=text;
        body={review_id:id,review_revision:wrongRevision ? revision-1 : revision,parameter_package:parameterPackage,
          ...(text===null ? {technical_requirements_projection:await page.evaluate(review=>technicalOutputPreviewModel(review),review)} : {})};
      }else if(action==="generation-readiness") body={review_id:id,review_revision:order.revision,generation_readiness:{status:order.readinessStatus || "ready",warnings:[],missing_fields:[],pending_fields:[],confirmed_core_count:8,core_field_count:8}};
      else if(action==="generation-jobs") {if(request.method()==="POST") generationPosts++;body={generation_jobs:[],generation_queue_available:false};}
      else if(action==="reasonableness") body={parameter_reasonableness:{status:"ok",issues:[],suggestions:[]}};
      else if(action==="annotations") body={schema_version:"original_annotations/v1",annotation_revision:1,source_document_id:id,pages:[],annotations:[],warnings:[]};
      else body={events:[]};
    }else if(apiPath==="/api/reviews") body={reviews:[]};
    else body={status:"ok",generation_runtime:{status:"not_configured"},recognition_queue_runtime:{status:"not_configured"}};
    await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
  const open=async(id="preview")=>{
    await page.evaluate(async id=>{await openPersistedReview(id);state.compareTab="parameters";renderCompareOverlay();},id);
    await page.waitForFunction(()=>state.materialCatalog.status==="ready");
  };
  const panel=page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const block=panel.locator(".technical-requirements-block"), preview=block.locator('[data-role="technical-output-preview"]');
  const shown=async()=> (await preview.locator('li > button:not([data-role="delete-technical-output"]), li > span').allTextContents()).join("\n");
  const expected=()=>page.evaluate(()=>technicalOutputPreviewModel(state.review).text);
  const flush=()=>page.evaluate(()=>flushReviewPersistence({throwOnError:true}));
  const checked=()=>preview.locator('[data-role="technical-output-status"]').filter({hasText:"已与服务器核对"}).waitFor();
  const readonlySnapshot=()=>page.evaluate(()=>JSON.stringify({parameters:state.review.spring_parameters,requirements:state.review.technical_requirements,confirmations:state.review.manual_confirmations,events:state.pendingReviewAuditEvents}));
  await page.goto(process.env.TECHNICAL_PREVIEW_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.identityReady);
  await open();await checked();
  assert.equal(await shown(),await expected());
  assert.equal(await preview.locator("li").count(),7,"Empty source list still exposes all eligible automatic notes");
  assert.equal(await preview.locator(".technical-output-auto").count(),7);
  assert.equal(await preview.locator("textarea,input,select").count(),0);
  assert.equal(await page.locator('.generation-readiness-block [data-kind="technical_output_preview"]').count(),0);
  const before=await readonlySnapshot(), beforePatches=patches;
  await preview.locator("summary").click();
  await page.evaluate(()=>{TechnicalRequirementPreview.refresh();renderCompareOverlay();});
  await page.waitForFunction(()=>document.querySelector('.compare-overlay [data-role="technical-output-preview"]')?.open===false);
  await preview.locator("summary").click();
  await preview.locator("li button").first().click();
  await page.waitForFunction(()=>document.activeElement?.closest('[data-field="handedness"]'));
  assert.equal(await readonlySnapshot(),before);
  assert.equal(patches,beforePatches,"Viewing, collapse and navigation do not save or confirm");
  assert.equal(packages.filter(item=>item.id==="preview"&&item.revision===1).length,1,"One successful server check per saved revision");

  const create=block.locator('[data-kind="technical_requirement_create"]');
  await block.locator('[data-action="show-technical-requirement-create"]').click();
  await create.locator('[data-role="new-technical-content"]').fill("绕制方向：右旋。");
  await create.locator('[data-role="technical-automatic-add-hint"]').waitFor({state:"visible"});
  await create.locator('button[type="submit"]').click();
  assert.equal(await page.evaluate(()=>state.review.technical_requirements.length),1);
  assert.equal(await page.evaluate(()=>state.review.technical_requirements[0].need_human_review),true);
  await block.locator('[data-role="technical-automatic-duplicate"]').waitFor({state:"visible"});
  assert.equal(await shown(),await expected());
  assert.ok((await block.locator('[data-role="technical-requirement-summary"]').innerText()).startsWith("原图／人工要求"));
  await block.locator('[data-action="show-technical-requirement-create"]').click();
  await create.locator('[data-role="new-technical-content"]').fill("绕制方向：右旋。");
  await create.locator('button[type="submit"]').click();
  assert.ok((await create.locator('[data-role="technical-requirement-create-error"]').innerText()).includes("已存在"));
  assert.equal(await page.evaluate(()=>state.review.technical_requirements.length),1,"Original-to-original duplicate rule remains intact");
  await create.locator('[data-action="cancel-technical-requirement-create"]').click();
  const original=block.locator('[data-kind="technical"]').first();
  await original.locator('[data-role="confirm"]').click();await flush();await checked();
  const confirmed=await shown();
  await original.locator('[data-role="delete-technical-requirement"]').click();await flush();await checked();
  assert.equal(await shown(),confirmed,"Deleting the original note never removes the automatic direction");
  await block.locator('[data-action="undo-technical-requirement-delete"]').click();await flush();await checked();
  assert.equal(await page.evaluate(()=>state.review.technical_requirements.length),1);
  assert.equal(await shown(),confirmed);

  const total=panel.locator('[data-field="total_coils"]'), input=total.locator('[data-role="value"]');
  failPatch=true;
  const readsBeforeTyping=packages.length;
  await input.fill("6.64");
  await preview.locator('[data-role="technical-output-status"]').filter({hasText:"草稿预览"}).waitFor();
  assert.equal(packages.length,readsBeforeTyping,"Typing does not request a parameter package");
  assert.equal(await input.evaluate(element=>element===document.activeElement),true);
  assert.equal(await shown(),await expected());
  await input.dispatchEvent("change");
  assert.equal(await page.evaluate(()=>flushReviewPersistence()),false);
  await preview.locator('[data-role="technical-output-status"]').filter({hasText:"保存失败"}).waitFor();
  assert.equal(await input.inputValue(),"6.64");
  await flush();await total.locator('[data-role="confirm"]').click();await flush();
  assert.equal(await shown(),await expected());
  assert.ok((await shown()).includes("总圈数：6.64"));
  await page.reload();await page.waitForFunction(()=>state.identityReady);await open();await checked();
  assert.ok((await shown()).includes("总圈数：6.64"));

  // Server authority, failure/retry and stale requests all use disposable in-memory orders.
  serverText="1.服务器核对正文，保持附加条件。";orders.preview.revision++;
  await open();await checked();
  assert.equal(await shown(),serverText);
  assert.equal(await preview.locator(".technical-output-auto").count(),0,"No invented provenance for unmatched server text");
  serverText=null;orders.preview.revision++;failPackage=true;
  await open();
  await preview.locator('[data-role="technical-output-retry"]').waitFor({state:"visible"});
  assert.equal(await shown(),await expected());
  assert.ok((await preview.locator('[data-role="technical-output-status"]').innerText()).includes("尚未完成服务端核对"));
  await preview.locator('[data-role="technical-output-retry"]').click();await checked();
  holdPackage=true;serverText="1.迟到的旧订单正文。";orders.preview.revision++;
  await open();await page.waitForTimeout(20);
  await waitForPackageRelease();
  serverText=null;await open("other");await checked();
  releasePackage();releasePackage=null;
  await page.waitForTimeout(70);
  assert.equal(await shown(),await expected());
  assert.ok(!(await shown()).includes("迟到"));
  assert.ok((await shown()).includes("总圈数：10.5，有效圈数：8.25"));
  assert.equal(await preview.evaluate(element=>element.open),true,"Changing orders resets disclosure to expanded");

  // A late response for the same saved revision must not overwrite uncommitted input.
  holdPackage=true;serverText="1.迟到的同订单正文。";orders.other.revision++;
  await open("other");
  await waitForPackageRelease();
  const liveTotal=panel.locator('[data-field="total_coils"] [data-role="value"]');
  await liveTotal.fill("11.625");
  releasePackage();releasePackage=null;serverText=null;
  await preview.locator('[data-role="technical-output-status"]').filter({hasText:"草稿预览"}).waitFor();
  await page.waitForTimeout(50);
  assert.ok(!(await shown()).includes("迟到"));
  assert.equal(await shown(),await expected());
  assert.equal(await liveTotal.evaluate(element=>element===document.activeElement),true);
  // Independent sessions clear cached server results and cannot reveal an old user's preview.
  const originalBase=await page.evaluate(()=>state.apiBaseUrl);
  await page.evaluate(()=>{state.apiBaseUrl="http://different-preview-service.test";TechnicalRequirementPreview.refresh();});
  await preview.waitFor({state:"hidden"});
  await page.evaluate(base=>{state.apiBaseUrl=base;TechnicalRequirementPreview.refresh();},originalBase);
  await preview.waitFor({state:"visible"});
  await page.evaluate(()=>{state.identity.user_id="another-preview-user";TechnicalRequirementPreview.refresh();});
  await preview.waitFor({state:"hidden"});
  await page.evaluate(()=>{state.identity.user_id="preview-user";TechnicalRequirementPreview.refresh();});
  await preview.waitFor({state:"visible"});
  await liveTotal.dispatchEvent("change");await flush();
  await panel.locator('[data-field="total_coils"] [data-role="confirm"]').click();await flush();

  await checked();
  // Wrong-revision responses are rejected; unrelated drawing settings do not suppress text.
  invalidRevision=true;orders.other.revision++;await open("other");
  await preview.locator('[data-role="technical-output-retry"]').waitFor({state:"visible"});
  assert.equal(await shown(),await expected());
  await preview.locator('[data-role="technical-output-retry"]').click();await checked();
  const beforeSettings=await expected();
  assert.equal(await page.evaluate(()=>{const review=structuredClone(state.review);review.generation_settings={drawing_model:"X型",username:""};return technicalOutputPreviewModel(review).text;}),beforeSettings);
  // Unconfirmed inputs cannot masquerade as output; an empty preview explains the next step.
  const confirmedReview=structuredClone(orders.other.review);
  for(const item of Object.values(orders.other.review.spring_parameters||{})) if(item&&typeof item==="object") item.need_human_review=true;
  for(const point of orders.other.review.spring_parameters.load_points||[]) point.need_human_review=true;
  orders.other.review.manual_confirmations=[];orders.other.readinessStatus="needs_confirmation";orders.other.revision++;
  await open("other");
  assert.equal(await expected(),"", "Unconfirmed inputs are not eligible for SW text");
  await preview.locator('[data-role="technical-output-empty"]').waitFor({state:"visible"});
  assert.equal(await preview.locator("li").count(),0);
  assert.equal(await preview.locator('[data-role="technical-output-empty"]').textContent(),"确认参数或技术要求后，将在此呈现成图内容。");
  orders.other.review=confirmedReview;delete orders.other.readinessStatus;orders.other.revision++;
  await open("other");await checked();

  // More than one viewport of notes, plus literal markup, for bounded visual QA.
  orders.other.review.technical_requirements=Array.from({length:6},(_,index)=>({requirement_id:`long-${index}`,type:"other",content:`检验说明${index+1}：<b>仅为文字</b>；尺寸、载荷与附加条件均须完整保留，不得截断。`,need_human_review:false}));
  orders.other.revision++;await open("other");await checked();
  assert.equal(await preview.locator("b,img,script").count(),0,"Requirement text is escaped");
  assert.equal(await shown(),await expected());
  await preview.locator('li button').filter({hasText:"检验说明1"}).click();
  await page.waitForFunction(()=>document.activeElement?.closest('[data-kind="technical"]'));
  assert.equal(await shown(),await expected());
  fs.mkdirSync("outputs/technical-preview-qa",{recursive:true});
  for(const width of process.env.SKIP_UI_QA_SCREENSHOTS ? [] : [1440,1100,390]){
    await page.setViewportSize({width,height:width<500?1200:1000});
    await preview.scrollIntoViewIfNeeded();
    assert.equal(await preview.evaluate(element=>element.scrollWidth>element.clientWidth+2),false);
    assert.equal(await preview.locator(".technical-output-scroll").evaluate(element=>element.scrollHeight>element.clientHeight),true);
    await page.screenshot({path:`outputs/technical-preview-qa/preview-${width}.png`});
  }
  // Four screenshot-style notes: three automatic notes and a company surface.
  await page.setViewportSize({width:1440,height:1000});
  const resetDeleteFixture=async()=>{
    orders.preview.review=structuredClone(initial);orders.preview.revision++;
    orders.preview.review.spring_parameters.load_points=[];
    Object.assign(orders.preview.review.spring_parameters.solid_height,{value:null,human_modified:true,source:["manual"],value_kind:"input_height"});
    orders.preview.review.technical_requirements=[
      {requirement_id:"direction-a",type:"other",content:"旋向：右旋。",need_human_review:false},
      {requirement_id:"direction-b",type:"other",content:"绕制方向：右旋。",need_human_review:false},
      {requirement_id:"surface",type:"surface",content:"表面处理：电镀-镀彩锌，镀层厚度≥15 μm。",normalization_status:"human_confirmed",source:["human_confirmed"],need_human_review:false},
    ];
    await open();await checked();assert.equal(await preview.locator("li").count(),4);
  };
  const erase=async text=>{await preview.locator("li").filter({hasText:text}).locator('[data-role="delete-technical-output"]').click();await flush();await checked();};
  const undo=async(serverCheck=true)=>{await block.locator('[data-action="undo-technical-requirement-delete"]').click();await flush();if(serverCheck)await checked();};
  const invariants=()=>page.evaluate(()=>JSON.stringify({parameters:state.review.spring_parameters,
    confirmations:Object.fromEntries(Object.entries(state.review.manual_confirmations||{}).filter(([key])=>!key.startsWith("technical")))}));
  await resetDeleteFixture();
  if(!process.env.SKIP_UI_QA_SCREENSHOTS){
    for(const width of [1440,390]){await page.setViewportSize({width,height:width<500?1200:1000});await preview.scrollIntoViewIfNeeded();
      await preview.screenshot({path:`outputs/technical-preview-qa/delete-controls-${width}.png`});
      assert.equal(await preview.evaluate(element=>element.scrollWidth>element.clientWidth+2),false);}
    await page.setViewportSize({width:1440,height:1000});
  }
  const inputs=await invariants();
  await erase("旋向");
  assert.equal(await shown(),await expected());assert.equal(await preview.locator("li").count(),3);
  assert.equal(await block.locator('[data-kind="technical"]').count(),1,"Both equivalent raw directions disappear with their automatic note");
  assert.equal(await invariants(),inputs,"Deleting automatic text preserves engineering inputs and confirmation");
  await undo();assert.equal(await preview.locator("li").count(),4);
  assert.equal(await page.evaluate(()=>state.review.technical_requirements.length),3);
  await erase("表面处理");assert.equal(await block.locator('[data-requirement-id="surface"]').count(),0);
  await undo();assert.equal(await block.locator('[data-requirement-id="surface"]').count(),1);
  await erase("总圈数");await erase("两端并紧");await undo();
  assert.ok(!(await shown()).includes("总圈数"));assert.ok((await shown()).includes("两端并紧"),"Only the latest deletion is undone");
  await page.reload();await page.waitForFunction(()=>state.identityReady);await open();await checked();
  assert.ok(!(await shown()).includes("总圈数"));assert.equal(await block.locator('[data-action="undo-technical-requirement-delete"]').count(),0);
  const free=panel.locator('[data-field="free_length"]');
  await free.locator('[data-role="value"]').fill("20");await free.locator('[data-role="value"]').dispatchEvent("change");await flush();
  await free.locator('[data-role="confirm"]').click();await flush();await checked();
  assert.ok(!(await shown()).includes("总圈数"),"An unrelated input does not restore a deleted coil note");
  const coils=panel.locator('[data-field="total_coils"]');
  await coils.locator('[data-role="value"]').fill("4.5");await coils.locator('[data-role="value"]').dispatchEvent("change");await flush();
  await coils.locator('[data-role="confirm"]').click();await flush();await checked();
  assert.ok((await shown()).includes("总圈数：4.5"),"A changed confirmed input regenerates its automatic note");
  await erase("总圈数");
  await block.locator('[data-action="show-technical-requirement-create"]').click();
  await create.locator('[data-role="new-technical-content"]').fill("总圈数：4.5，有效圈数：2。");
  await create.locator('button[type="submit"]').click();await flush();
  const explicit=block.locator('.requirement-row').filter({hasText:"总圈数：4.5"});
  await explicit.locator('[data-role="confirm"]').click();await flush();await checked();
  assert.ok((await shown()).includes("总圈数：4.5"),"A newly added original record is not blocked by the old automatic choice");
  const beforeAll=await invariants();
  const beforeModel=await page.evaluate(()=>{const p=makeGenerationParameterPackage().solidworks_preview;delete p.extraProperties["技术要求"];return p;});
  while(await preview.locator("li").count()){await preview.locator('[data-role="delete-technical-output"]').first().click();await flush();await checked();}
  assert.equal(await shown(),"");assert.equal(await expected(),"");assert.equal(await invariants(),beforeAll);
  assert.deepEqual(await page.evaluate(()=>{const p=makeGenerationParameterPackage().solidworks_preview;delete p.extraProperties["技术要求"];return p;}),beforeModel,"All other SW properties remain unchanged");
  await page.reload();await page.waitForFunction(()=>state.identityReady);await open();await checked();assert.equal(await shown(),"");

  await resetDeleteFixture();failPatch=true;
  await preview.locator("li").filter({hasText:"总圈数"}).locator('[data-role="delete-technical-output"]').click();
  await preview.locator('[data-role="technical-output-retry"]').filter({hasText:"重试保存"}).waitFor();
  assert.ok(!(await shown()).includes("总圈数"));
  await preview.locator('[data-role="technical-output-retry"]').click();await flush();await checked();
  assert.ok(!(await shown()).includes("总圈数"));
  conflictPatch=true;await erase("两端并紧");
  assert.equal(await page.evaluate(()=>state.review.drawing_summary.drawing_name),"服务器保留名称","Output choices merge with an unrelated server edit");
  assert.ok(!(await shown()).includes("总圈数"));assert.ok(!(await shown()).includes("两端并紧"));
  await undo();assert.ok((await shown()).includes("两端并紧"));

  await resetDeleteFixture();await erase("旋向");
  const direction=panel.locator('[data-field="handedness"]');
  await direction.locator('[data-role="value"]').selectOption("左旋");await flush();
  await direction.locator('[data-role="confirm"]').click();await flush();await checked();
  await undo(false);assert.ok((await shown()).includes("旋向：左"));assert.ok(!(await shown()).includes("旋向：右"));
  assert.ok(await page.evaluate(()=>state.review.technical_requirements.filter(item=>item.requirement_id.startsWith("direction-")).every(item=>item.need_human_review)),"Undo restores old evidence for review, not stale confirmed right-handed output");

  await resetDeleteFixture();holdPackage=true;orders.preview.revision++;await open();await waitForPackageRelease();
  await preview.locator("li").filter({hasText:"总圈数"}).locator('[data-role="delete-technical-output"]').click();await flush();
  releasePackage();releasePackage=null;await checked();
  assert.ok(!(await shown()).includes("总圈数"),"A late old package must not restore deleted text");
  await open("other");await checked();assert.equal(await block.locator('[data-action="undo-technical-requirement-delete"]').count(),0);
  assert.equal(generationPosts,0,"Preview never creates a generation task");
  assert.deepEqual(errors,[]);
  console.log("PASS: preview/provenance/cache/navigation, every-line automatic/raw delete, linked sources, latest undo, all-delete, unchanged engineering/SW fields, input regeneration, explicit re-add, save retry/conflict/reopen, late responses and responsive layout; mocked API only.");
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
