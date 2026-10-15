import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
const fixtures=JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_support_coils.py','--json'],{encoding:'utf8',maxBuffer:4*1024*1024}));
const ctx={structuredClone,state:{review:null,reviewEditSerial:0,reviewDraftFields:new Set()},sourceValues:v=>v||[]};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('frontend/compression-design-checks.js','utf8'),ctx);
const normalize=v=>JSON.parse(JSON.stringify(v));
for(const fixture of fixtures){
  const r=structuredClone(fixture.review);ctx.CompressionDesignChecks.applySupportCoils(r);
  assert.deepEqual(normalize(r),fixture.expected,fixture.name);
}
const source=fs.readFileSync('frontend/app.js','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
vm.runInContext(extract('function confirmParam(','function makeExportReview('),ctx);
const r=structuredClone(fixtures[0].review);ctx.state.review=r;ctx.CompressionDesignChecks.applySupportCoils(r);
const p=r.spring_parameters;
ctx.confirmParam(p.total_coils,'total_coils');ctx.confirmParam(p.active_coils,'active_coils');ctx.confirmParam(p.support_coils,'support_coils');
const original=structuredClone(p.support_coils);
p.total_coils.value=18;p.total_coils.source=['human_edited'];p.total_coils.need_human_review=true;
ctx.CompressionDesignChecks.applySupportCoils(r);assert.equal(p.support_coils.value,1);assert.equal(p.support_coils.support_coils_waiting_confirmation,true);
ctx.confirmParam(p.total_coils,'total_coils');assert.equal(p.support_coils.value,2);assert.equal(p.support_coils.need_human_review,true);
assert.ok(!r.manual_confirmations.support_coils);assert.ok(!p.support_coils.confirmation_snapshot);
// A second upload/edit sequence confirms the counts in the opposite order.
for(const reverse of [false,true]){
  const review=structuredClone(fixtures[0].review);ctx.state.review=review;
  ctx.CompressionDesignChecks.applySupportCoils(review);
  const params=review.spring_parameters;
  params.total_coils={...params.total_coils,value:20,source:['human_edited'],need_human_review:true};
  params.active_coils={...params.active_coils,value:16,source:['human_edited'],need_human_review:true};
  const order=reverse?['active_coils','total_coils']:['total_coils','active_coils'];
  ctx.confirmParam(params[order[0]],order[0]);assert.equal(params.support_coils.value,1);
  ctx.confirmParam(params[order[1]],order[1]);assert.equal(params.support_coils.value,2);assert.equal(params.support_coils.need_human_review,true);
}
console.log(`Support coil UI: ${fixtures.length} full Python/JS snapshots, both confirmation orders and old-confirmation removal passed`);
