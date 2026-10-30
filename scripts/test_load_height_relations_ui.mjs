import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
const cases=JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || '.venv/Scripts/python.exe',['scripts/test_load_height_relations.py','--json'],{encoding:'utf8'}));
const context=vm.createContext({structuredClone});
vm.runInContext(fs.readFileSync('frontend/load-height-relations.js','utf8'),context);
for(const test of cases){
  const review=structuredClone(test.review);
  context.LoadHeightRelations.refresh(review);
  assert.deepEqual(JSON.parse(JSON.stringify(review)),test.expected,test.name);
  assert.equal(context.LoadHeightRelations.refresh(review).length,0,test.name+' stable');
}
console.log(`PASS: ${cases.length} Python/JavaScript load-height chains, manual/clear/rename, confirmation and dependency parity`);
