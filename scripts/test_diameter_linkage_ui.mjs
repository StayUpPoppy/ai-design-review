import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
const fixtures = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_diameter_linkage.py', '--json'], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }));
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('frontend/diameter-linkage.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('frontend/accuracy-inference.js', 'utf8'), context);
for (const fixture of fixtures) {
  const r = structuredClone(fixture.review);
  for (const [field, value] of fixture.edits) { r.spring_parameters[field].value = value; context.DiameterLinkage.apply(r, field); if (fixture.inference) context.AccuracyInference.refresh(r); }
  context.DiameterLinkage.apply(r);
  if (fixture.inference) context.AccuracyInference.refresh(r);
  assert.deepEqual(JSON.parse(JSON.stringify(r)), fixture.expected, fixture.name);
}
console.log(`Diameter linkage Python/JS parity: ${fixtures.length} shared fixtures passed`);
