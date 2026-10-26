import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';

const cases = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_accuracy_inference.py', '--json'], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }));
const scope = vm.createContext({});
vm.runInContext(fs.readFileSync('frontend/compression-design-checks.js', 'utf8'), scope);
vm.runInContext(fs.readFileSync('frontend/accuracy-inference.js', 'utf8'), scope);
const engine = scope.AccuracyInference;
assert.deepEqual(JSON.parse(JSON.stringify(engine.HOT_RULES)), JSON.parse(fs.readFileSync('config/spring_standards/gbt_23934_2015.json', 'utf8')));
assert.deepEqual(JSON.parse(JSON.stringify(engine.RULES)), JSON.parse(fs.readFileSync('config/spring_standards/gbt_1239_2_2009.json', 'utf8')));
for (const test of cases) {
  const review = structuredClone(test.review);
  engine.refresh(review, { initialize: true });
  assert.deepEqual(JSON.parse(JSON.stringify(review)), test.expected, test.name);
}
const r = structuredClone(cases[0].review);
engine.refresh(r, { initialize: true });
const snapshot = structuredClone(r.accuracy_inference.input_snapshot);
r.spring_parameters.free_length.tolerance_upper = 1.2;
r.spring_parameters.free_length.tolerance_lower = -1.2;
engine.markInput(r, 'free_length', { generated: true });
assert.deepEqual(JSON.parse(JSON.stringify(r.accuracy_inference.input_snapshot)), snapshot);
engine.manual(r); r.spring_parameters.accuracy_grade.value = '2级';
for (let i = 0; i < 5; i++) { engine.refresh(r); assert.equal(r.spring_parameters.accuracy_grade.value, '2级'); }
assert.equal(r.accuracy_inference.inferred_grade, '1级');
console.log(`Accuracy inference UI: ${cases.length} shared fixtures and generated/manual lifecycle checks passed`);
