// Group preferences, request races and large manifests, without the full app.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const browser=await chromium.launch({headless:true,channel:'msedge'});
try {
  const page=await browser.newPage();
  await page.route('http://groups.test/',r=>r.fulfill({contentType:'text/html',body:'<main></main>'}));
  await page.goto('http://groups.test/');
  await page.addScriptTag({content:fs.readFileSync('frontend/multi-spec-review.js','utf8')});
  const result=await page.evaluate(async()=>{
    const expect=(condition,message)=>{if(!condition)throw Error(message);};
    let identity='user-a',service='one',session=1,deleted=new Set(),gate=null,reads=0,viewed=0;
    const row=()=>{const r=document.createElement('article');document.querySelector('main').replaceChildren(r);return r;};
    let current=row(),item={job_id:'source',record_kind:'source',creation_mode:'auto',recognition_status:'completed',recognition_attempt_count:1,revision:1,created_count:50,variant_count:50};
    const manifest=()=>({created_count:50,variants:Array.from({length:50},(_,i)=>({review:{job_id:`child-${i}`}}))});
    let ui;
    const create=()=>MultiSpecReview.create({scope:()=>`${service}/${identity}/${session}`,storageScope:()=>`${service}/${identity}`,
      request:async()=>{reads++;if(gate)await gate;return new Response(JSON.stringify(manifest()),{status:200});},
      deleted:id=>deleted.has(id),save:async()=>true,openReview:()=>{},assetUrl:v=>v,viewed:()=>viewed++,
      changed:()=>ui.decorate(item,current),renderRow:(v,old)=>{const r=old||document.createElement('div');r.dataset.historyJobId=v.job_id;return r;}});
    const settle=async()=>{for(let i=0;i<15;i++)await new Promise(r=>setTimeout(r,0));};
    ui=create();ui.decorate(item,current);await settle();
    expect(current.querySelectorAll('[data-history-job-id]').length===50,'All 50 children remain in original order');
    expect([...current.querySelectorAll('[data-history-job-id]')].every((r,i)=>r.dataset.historyJobId===`child-${i}`),'Order unchanged');
    expect(viewed===0&&reads===1,'Automatic expansion is read-only and fetched once');
    const first=current.querySelector('[data-history-job-id]');ui.decorate({...item},current);
    expect(current.querySelector('[data-history-job-id]')===first,'Polling preserves child nodes');
    current.querySelector('button').click();ui.decorate({...item,revision:2},current);await settle();
    expect(current.querySelector('.history-source-children').hidden,'Same round stays collapsed');
    ui.reset();current=row();session++;ui.decorate(item,current);await settle();
    expect(current.querySelector('.history-source-children').hidden,'Stable storage scope survives new request sessions');
    identity='user-b';current=row();ui.decorate(item,current);await settle();
    expect(!current.querySelector('.history-source-children').hidden,'A different user does not inherit collapse');
    service='two';current=row();ui.decorate(item,current);await settle();
    expect(!current.querySelector('.history-source-children').hidden,'Service scopes remain independent');
    // Storage failures keep the page's choice, including a reset in the same session.
    Storage.prototype.getItem=()=>{throw Error('blocked');};Storage.prototype.setItem=()=>{throw Error('blocked');};
    current.querySelector('button').click();ui.reset();current=row();ui.decorate(item,current);await settle();
    expect(current.querySelector('.history-source-children').hidden,'Unavailable storage falls back to memory');
    // A completion received after page closure still expands a tracked source on next read.
    item={...item,recognition_attempt_count:2};ui.decorate(item,current);await settle();
    expect(!current.querySelector('.history-source-children').hidden,'A new recognition round expands once');
    // Root deletion while the GET is in flight cannot restore children or steal focus.
    let release;gate=new Promise(r=>release=r);ui.reset();current=row();item={...item,recognition_attempt_count:3};
    ui.decorate(item,current);deleted.add('source');ui.remove(['source']);release();await settle();
    expect(ui.items().length===0,'Deleted roots reject late manifests');
    // A user switch similarly rejects an old manifest.
    deleted.clear();gate=new Promise(r=>release=r);current=row();ui.decorate(item,current);identity='user-c';ui.reset();release();await settle();
    expect(ui.items().length===0,'New users reject prior session responses');
    return 'PASS 50-child order/node reuse, per-user/service preferences, storage fallback, new rounds, deletion and session races';
  });
  assert.ok(result);console.log(result);
} finally {await browser.close();}
