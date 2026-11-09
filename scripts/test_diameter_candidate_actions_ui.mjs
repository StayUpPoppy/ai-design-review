import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';

const fixtures = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['-B', 'scripts/test_diameter_candidate_actions.py', '--json'], {
  encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
}));
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('frontend/diameter-role-candidates.js', 'utf8'), context);
const api = context.DiameterRoleCandidates;
for (const fixture of fixtures) {
  const candidate = structuredClone(fixture.candidate), before = structuredClone(candidate);
  assert.equal(api.modelDerived(candidate), fixture.derived, candidate.evidence);
  assert.equal(api.pending({ diameter_role_candidates: [candidate] }).length, fixture.derived ? 0 : 1, candidate.evidence);
  for (const state of [{ ignored: true }, { selected_field: 'mean_diameter' }]) {
    assert.equal(api.pending({ diameter_role_candidates: [{ ...candidate, ...state }] }).length, 0);
  }
  assert.deepEqual(candidate, before);
}
console.log(`PASS: ${fixtures.length} shared provenance cases, historical read-only filtering, ignored/selected states`);
