import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
const cases=JSON.parse(execFileSync('.venv/Scripts/python.exe',['scripts/test_compression_calculation_recovery.py','--json'],{encoding:'utf8'}));
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync('frontend/compression-design-checks.js','utf8'),ctx);
const catalog=JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
function compare(a,b,p=''){
  if(typeof b==='number')assert.ok(typeof a==='number' && Math.abs(a-b)<=1e-10*Math.max(1,Math.abs(b)),`${p}: ${a} != ${b}`);
  else if(b && typeof b==='object'){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),p);for(const k of Object.keys(b))compare(a[k],b[k],p+'.'+k);}
  else assert.equal(a,b,p);
}
for(const c of cases){
  const r=structuredClone(c.review);ctx.CompressionDesignChecks.applyPitch(r);
  const checks=JSON.parse(JSON.stringify(ctx.CompressionDesignChecks.calculate(r.spring_parameters,r.spring_features,catalog)));
  compare(checks,c.expected.design_checks,c.name);
  for(const f of ['active_coils','support_coils','pitch','solid_height']){
    assert.equal(r.spring_parameters[f]?.value,c.expected.spring_parameters[f]?.value,c.name+'.'+f);
    assert.equal(r.spring_parameters[f]?.need_human_review,c.expected.spring_parameters[f]?.need_human_review,c.name+'.'+f);
  }
}
const r=structuredClone(cases[0].review),p=r.spring_parameters;
ctx.CompressionDesignChecks.applyPitch(r);p.active_coils.need_human_review=false;r.manual_confirmations.active_coils={confirmed:true};
p.total_coils.value=8;ctx.CompressionDesignChecks.applyPitch(r);
assert.equal(p.active_coils.value,6);assert.equal(p.solid_height.value,12);assert.equal(p.pitch.value,2.57);
assert.equal(p.active_coils.need_human_review,true);assert.ok(!r.manual_confirmations.active_coils);
p.total_coils.value='invalid';ctx.CompressionDesignChecks.applyPitch(r);
assert.equal(p.active_coils.value,6);assert.equal(p.active_coils.derived_value_stale,true);
assert.equal(ctx.CompressionDesignChecks.calculate(p,r.spring_features,catalog).metrics.solid_stress.value,null);
console.log('Calculation recovery: six Python/JS result/dependency cases, immediate confirmation revocation and invalid-input isolation passed');
