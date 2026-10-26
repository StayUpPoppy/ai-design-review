import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const {chromium} = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const output = path.resolve('outputs/drawing-rotation-qa'), frontend = path.resolve('frontend'); fs.mkdirSync(output,{recursive:true});
const cases = JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_solidworks_export.py','--json'],{encoding:'utf8',maxBuffer:4*1024*1024}));
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
const localImage='C:/Users/29580/Desktop/多规格2.jpg', fixtureImage=fs.existsSync(localImage)?localImage:'data/samples/compression_spring_demo.png';
const image = fs.readFileSync(fixtureImage), imageMime=fixtureImage.endsWith('.png')?'image/png':'image/jpeg';
const server = http.createServer((req,res)=>{
  const file = path.resolve(frontend,new URL(req.url,'http://localhost').pathname.slice(1)||'index.html');
  if(!file.startsWith(frontend+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser = await chromium.launch({headless:true,channel:'msedge'}),page = await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[],requests=[],patches=[]; page.on('pageerror',e=>errors.push(e.message));
const originals = id=>({source_document_id:id,annotation_revision:1,pages:[1,2].map(p=>({page:p,image_url:`/api/reviews/${id}/artifacts/page${p}.jpg`,width:2800,height:1700})),warnings:[],text_obstacles:[],annotations:[
  {annotation_id:'wire_diameter',field:'wire_diameter',number:4,label:'线径',original_value:10,locations:[{location_id:'wire',source:'ocr',page:1,anchor:{x:.2,y:.3},bubble:{x:.3,y:.27}}]},
  {annotation_id:'free_length',field:'free_length',number:8,label:'自由高度',original_value:260,locations:[{location_id:'height',source:'ocr',page:1,anchor:{x:.75,y:.55},bubble:{x:.8,y:.5}},{location_id:'height-page2',source:'ocr',page:2,anchor:{x:.6,y:.4},bubble:{x:.7,y:.3}}]},
  {annotation_id:'mean_diameter',field:'mean_diameter',number:7,label:'中径',original_value:null,reason:'待人工定位',locations:[]},
]});
const docs=new Map(['normal','variant'].map(id=>[id,originals(id)])); let failImage=false;
await page.route('**/api/**',async route=>{
  const req=route.request(),p=new URL(req.url()).pathname,m=req.method();requests.push({p,m});
  if(p.includes('/artifacts/'))return failImage?route.fulfill({status:404,body:'missing image'}):route.fulfill({contentType:imageMime,body:image});
  if(p==='/api/session')return route.fulfill({json:{identity:{user_id:'rotation-test',username:'旋转离线测试'}}});
  if(p==='/api/material-catalog')return route.fulfill({json:catalog});
  if(p==='/api/reviews')return route.fulfill({json:{reviews:[{job_id:'normal',drawing_name:'原图预览旋转',revision:1,image_url:'/api/reviews/normal/artifacts/page1.jpg'}]}});
  const match=p.match(/^\/api\/reviews\/(normal|variant)(?:\/(annotations))?$/);
  if(match){const[,id,action]=match;
    if(action){const doc=docs.get(id);if(m==='PATCH'){const body=req.postDataJSON();patches.push(body);assert.equal(body.expected_annotation_revision,doc.annotation_revision);
      for(const c of body.changes){const a=doc.annotations.find(a=>a.field===c.annotation_id);let l=a.locations.find(l=>l.location_id===c.location_id);if(!l){l={};a.locations.push(l);}Object.assign(l,c,{source:'manual'});}doc.annotation_revision++;}
      return route.fulfill({json:doc});}
    return route.fulfill({json:{...structuredClone(cases[0].review),record_kind:id==='variant'?'variant':'single',review_revision:1,image_url:`/api/reviews/${id}/artifacts/page1.jpg`}});
  }
  if(p.endsWith('/generation-jobs'))return route.fulfill({json:{generation_jobs:[],generation_queue_available:false}});
  if(p.endsWith('/generation-readiness'))return route.fulfill({json:{generation_readiness:{status:'ready',missing_fields:[],pending_fields:[],warnings:[]}}});
  if(p.endsWith('/reasonableness'))return route.fulfill({json:{parameter_reasonableness:{status:'pass',issues:[],suggestions:[]}}});
  if(p.endsWith('/changes'))return route.fulfill({json:{events:[]}});
  return route.fulfill({json:{status:'ok',generation_runtime:{status:'not_configured'},recognition_queue_runtime:{status:'not_configured'}}});
});
const ready = ()=>page.waitForFunction(()=>document.querySelector('#compareImage')?.naturalWidth && !document.querySelector('[data-view-action="rotate-right"]').disabled && DrawingAnnotations.entry()?.document);
const angle = ()=>page.evaluate(()=>state.compareView.rotation);
const snapshot = ()=>page.evaluate(()=>{
  const image=document.querySelector('#compareImage'),viewport=document.querySelector('#compareViewport'),v=state.compareView;
  const inverse=new DOMMatrix(image.style.transform).inverse(),center=new DOMPoint(viewport.clientWidth/2,viewport.clientHeight/2).matrixTransform(inverse);
  return{rotation:v.rotation,scale:v.scale,x:v.x,y:v.y,center:[center.x,center.y],key:DrawingAnnotations.entry().layout.key,document:JSON.stringify(DrawingAnnotations.entry().document),review:JSON.stringify(state.review)};
});
const near=(a,b)=>assert.ok(Math.abs(a-b)<.02,`${a} != ${b}`);
const geometry = ()=>page.evaluate(()=>{
  const image=document.querySelector('#compareImage'),matrix=new DOMMatrix(image.style.transform),entry=DrawingAnnotations.entry();
  const locations=entry.document.annotations.flatMap(a=>a.locations.filter(l=>l.page===entry.page));
  return [...document.querySelectorAll('.annotation-anchor')].every((el,i)=>{
    const l=locations[i],p=new DOMPoint(l.anchor.x*image.naturalWidth,l.anchor.y*image.naturalHeight).matrixTransform(matrix);
    if(Math.abs(p.x-Number(el.getAttribute('cx')))>.01||Math.abs(p.y-Number(el.getAttribute('cy')))>.01)return false;
    const group=el.nextElementSibling,g=group.transform.baseVal.consolidate().matrix;if(g.a!==1||g.d!==1||g.b!==0||g.c!==0)return false;
    const distance=Math.hypot(p.x-g.e,p.y-g.f),line=el.previousElementSibling;
    return distance<=15?line?.tagName!=='line':line?.tagName==='line'&&Math.abs(Math.hypot(Number(line.getAttribute('x2'))-g.e,Number(line.getAttribute('y2'))-g.f)-15)<.01;
  });
});
try{
  await page.goto(`http://127.0.0.1:${server.address().port}`);await page.waitForFunction(()=>state.identityReady&&state.recentReviews.length);
  await page.evaluate(async()=>{await openPersistedReview('normal');state.compareTab='parameters';renderCompareOverlay();});await ready();
  assert.deepEqual(await page.locator('#compareOverlay .summary-strip').first().locator(':scope > .metric > span:first-child').allTextContents(),['类型','图纸名称','图号']);
  const initial=await snapshot(),callsBefore=requests.length;
  const input=page.locator('#compareOverlay [data-role="drawing-name"]');await input.evaluate(el=>{window.rotationDraft=el;el.value='尚未提交的本地输入';});
  for(let n=0;n<4;n++){
    await page.locator('[data-view-action="rotate-right"]').click();const s=await snapshot();assert.equal(s.rotation,((n+1)%4)*90);near(s.scale,initial.scale);near(s.center[0],initial.center[0]);near(s.center[1],initial.center[1]);assert.equal(s.key,initial.key);assert.equal(s.document,initial.document);assert.equal(s.review,initial.review);assert.equal(await geometry(),true);
    assert.equal(await page.locator('[data-view-action="rotate-right"]').evaluate(el=>el===document.activeElement),true);
  }
  near((await snapshot()).x,initial.x);near((await snapshot()).y,initial.y);
  assert.equal(await input.evaluate(el=>el===window.rotationDraft&&el.value==='尚未提交的本地输入'),true);
  assert.equal(requests.slice(callsBefore).filter(r=>r.m==='PATCH').length,0);
  await page.locator('[data-view-action="rotate-left"]').click();assert.equal(await angle(),270);await page.locator('[data-view-action="rotate-right"]').click();assert.equal(await angle(),0);
  await page.locator('[data-view-action="rotate-right"]').click();await page.locator('[data-view-action="actual"]').click();near((await snapshot()).scale,1);assert.equal(await angle(),90);
  await page.locator('[data-view-action="zoom-out"]').click();near((await snapshot()).scale,1/1.2);assert.equal(await geometry(),true);
  await page.locator('[data-view-action="fit"]').click();assert.equal(await angle(),90);
  await page.locator('[data-annotation-page]').selectOption('2');await ready();assert.equal(await angle(),0);
  await page.locator('[data-view-action="rotate-left"]').click();assert.equal(await angle(),270);
  await page.locator('[data-annotation-page]').selectOption('1');await ready();assert.equal(await angle(),90);
  await page.locator('[data-annotation-action="edit"]').click();await ready();
  for(const rotation of [0,90,180,270]){
    await page.evaluate(r=>{rotateCompareImage(r-state.compareView.rotation);fitCompareImage();},rotation);
    const bubble=page.locator('[data-location-id="wire"]');await bubble.focus();const before=await bubble.boundingBox(),count=patches.length;
    await page.keyboard.press('ArrowRight');await page.waitForFunction(count=>DrawingAnnotations.entry().phase==='saved'&&DrawingAnnotations.entry().document.annotation_revision>count+1,count);await ready();
    const after=await bubble.boundingBox();near(after.x-before.x,5);near(after.y-before.y,0);assert.equal(await geometry(),true);
    const bounds=await bubble.boundingBox();const target={x:bounds.x+15+12,y:bounds.y+15+9};
    const expected=await page.evaluate(point=>{const rect=document.querySelector('#compareViewport').getBoundingClientRect(),im=document.querySelector('#compareImage');const p=new DOMPoint(point.x-rect.left,point.y-rect.top).matrixTransform(new DOMMatrix(im.style.transform).inverse());return{x:p.x/im.naturalWidth,y:p.y/im.naturalHeight};},target);
    const oldCount=patches.length;await page.mouse.move(bounds.x+15,bounds.y+15);await page.mouse.down();await page.mouse.move(target.x,target.y,{steps:3});await page.mouse.up();
    await page.waitForFunction(n=>DrawingAnnotations.entry().document.annotation_revision>n+1&&DrawingAnnotations.entry().phase==='saved',oldCount);
    const change=patches.at(-1).changes.find(c=>c.location_id==='wire');near(change.bubble.x,expected.x);near(change.bubble.y,expected.y);assert.deepEqual(change.anchor,{x:.2,y:.3});assert.equal(await geometry(),true);
  }
  // Manual placement at 270 degrees persists source-space coordinates.
  await page.locator('.annotation-unlocated').evaluate(el=>el.open=true);await page.locator('[data-annotation-place="mean_diameter"]').click();await ready();
  const target=await page.evaluate(()=>{const im=document.querySelector('#compareImage'),rect=document.querySelector('#compareViewport').getBoundingClientRect();const p=new DOMPoint(.6*im.naturalWidth,.7*im.naturalHeight).matrixTransform(new DOMMatrix(im.style.transform));return{x:rect.left+p.x,y:rect.top+p.y};});
  const count=patches.length;await page.mouse.click(target.x,target.y);await page.waitForFunction(n=>DrawingAnnotations.entry().phase==='saved'&&DrawingAnnotations.entry().document.annotation_revision>n+1,count);
  const placed=patches.at(-1).changes.find(c=>c.annotation_id==='mean_diameter');near(placed.anchor.x,.6);near(placed.anchor.y,.7);
  // Per-parameter focus centers the rotated evidence, without losing rotation.
  await page.evaluate(()=>DrawingAnnotations.focusField('free_length'));await ready();assert.equal(await angle(),270);
  const centered=await page.evaluate(()=>{const p=DrawingAnnotations.screenPoint({x:.75,y:.55}),v=document.querySelector('#compareViewport');return[p.x-v.clientWidth/2,p.y-v.clientHeight/2];});near(centered[0],0);near(centered[1],0);
  await page.evaluate(()=>{closeCompareOverlay();openCompareOverlay();});await ready();assert.equal(await angle(),0);
  await page.locator('[data-annotation-page]').selectOption('2');await ready();assert.equal(await angle(),0);
  await page.evaluate(()=>rotateCompareImage(90));await page.evaluate(()=>openPersistedReview('variant'));await ready();assert.equal(await angle(),0);
  assert.equal(await page.evaluate(()=>state.review.record_kind),'variant');
  await page.locator('[data-view-action="rotate-right"]').click();await page.evaluate(()=>{state.compareTab='parameters';renderCompareOverlay();});await ready();await page.locator('[data-view-action="fit"]').click();assert.equal(await geometry(),true);
  await page.screenshot({path:path.join(output,'desktop.png')});await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector('#compareViewport')?.clientWidth>0);await page.screenshot({path:path.join(output,'mobile.png')});
  assert.equal(await page.locator('.compare-tools').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
  await page.evaluate(()=>{const im=document.querySelector('#compareImage');im.src='/api/reviews/variant/artifacts/broken.jpg';});failImage=true;
  await page.waitForFunction(()=>document.querySelector('#compareImage').complete&&!document.querySelector('#compareImage').naturalWidth);assert.equal(await page.locator('[data-view-action="rotate-right"]').isDisabled(),true);
  await page.reload();await page.waitForFunction(()=>state.identityReady&&state.recentReviews.length);failImage=false;await page.evaluate(()=>openPersistedReview('normal'));await ready();assert.equal(await angle(),0);
  assert.deepEqual(errors,[]);assert.equal(requests.filter(r=>r.m==='PATCH'&&!r.p.endsWith('/annotations')).length,0);
  console.log('PASS preview rotation: source/bitmap mapping, upright bubbles/leaders, unchanged scale/center/layout/drafts, PDF memory, manual drag/keyboard/placement saves, order/close/reload reset, image failure, three summary cards and desktop/mobile');
}finally{await browser.close();server.close();}
