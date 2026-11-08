import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';

const reviews = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_execution_standards.py', '--json'], {
  encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
}));
const scope = vm.createContext({});
for (const file of ['accuracy-inference', 'execution-standards']) vm.runInContext(fs.readFileSync(`frontend/${file}.js`, 'utf8'), scope);
for (const review of reviews) {
  const fingerprint = execFileSync('.venv/Scripts/python.exe', ['-c', "import json,sys;sys.path.insert(0,'src');from ai_design_review.execution_standards import fingerprint;print(fingerprint(json.load(sys.stdin)))"], {
    encoding: 'utf8', input: JSON.stringify(review), env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  }).trim();
  assert.equal(scope.ExecutionStandards.fingerprint(review), fingerprint, 'Python and browser use the same freshness inputs');
}
const review = structuredClone(reviews[1]);
scope.ExecutionStandards.select(review, scope.ExecutionStandards.HOT);
review.spring_parameters.accuracy_grade.value = 'T级';
scope.AccuracyInference.refresh(review);
assert.equal(review.standard_selection.selected_standard, scope.ExecutionStandards.HOT);
scope.ExecutionStandards.select(review, scope.ExecutionStandards.COLD);
scope.AccuracyInference.refresh(review);
assert.equal(review.spring_parameters.accuracy_grade.value, null);
assert.equal(review.spring_parameters.accuracy_grade.requires_selection, true);
assert.equal(review.accuracy_inference.selection_mode, 'manual');
scope.ExecutionStandards.invalidate(review);
assert.ok(review.standardization_results.every(item => item.status === 'stale'));
console.log('Execution standards UI: shared fingerprints, manual standard precedence, T-grade switching and stale results passed');

const partial = structuredClone(reviews[0]);
partial.spring_parameters.load_points = [{ label: 'F1', force: 100, force_tolerance_percent: 10 }, { label: 'F2', force: 200, load_tolerance_upper: 4, load_tolerance_lower: -2 }];
partial.spring_parameters.spring_rate = { value: null, formula_calculation_missing_fields: ['active_coils'] };
partial.standardization_results = [
  { target_field: 'free_length', status: 'suggested', suggested_tolerance_upper: 1 },
  { target_field: 'free_length', status: 'llm_suggested', suggested_tolerance_upper: 2 },
  { target_field: 'standard_no', status: 'need_context', metadata: { missing_fields: ['standard_no'] } },
  { target_field: 'solid_height', status: 'need_context', metadata: { value_kind: 'reference_limit' } },
  { target_field: 'load_points', status: 'need_context', metadata: { missing_fields: ['spring_rate'] } },
];
function stamp(r) { r.standardization_context = { version: scope.ExecutionStandards.VERSION, input_fingerprint: scope.ExecutionStandards.fingerprint(r) }; }
stamp(partial);
const beforeReport = JSON.stringify(partial);
let report = scope.ExecutionStandards.report(partial);
assert.equal(report.generated, 1);
assert.equal(report.failed, 2, 'Legacy collection diagnostics expand to each load point');
assert.match(report.message, /已生成 1 项，2 项未能生成/);
assert.match(report.diagnostics[0].reason, /刚度.*有效圈数/);
assert.equal(JSON.stringify(partial), beforeReport, 'Reporting does not alter original/manual tolerances');
partial.standardization_results[4] = { target_field: 'load_points.F1.force', status: 'not_applicable', basis: '有效圈数超出查表范围，请手填公差。' };
stamp(partial);
report = scope.ExecutionStandards.report(partial);
assert.equal(report.failed, 1);
assert.match(report.diagnostics[0].reason, /查表范围.*手填公差/);
scope.ExecutionStandards.invalidate(partial, true);
report = scope.ExecutionStandards.report(partial);
assert.equal(report.stale, true);
assert.equal(report.generated, 0);
assert.equal(report.failed, 0);
assert.ok(report.diagnostics.every(item => item.stale && !/查表范围/.test(item.reason)));
partial.standardization_results = [{ target_field: 'load_points', status: 'need_context', metadata: { missing_fields: ['active_coils'] } }];
stamp(partial);
report = scope.ExecutionStandards.report(partial);
assert.equal(report.generated, 0);
assert.equal(report.failed, 2);
assert.equal(report.stale, false);
console.log('Standardization feedback: partial counts, legacy loads, formula dependencies, table limits, read-only reporting and stale diagnostics passed');

const diagnostics = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_standardization_diagnostics.py', '--json'], {
  encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
}));
for (const test of diagnostics) {
  const before = JSON.stringify(test.review);
  const actual = JSON.parse(JSON.stringify(scope.ExecutionStandards.diagnosticGroups(test.review, test.rate_calculation)));
  assert.deepEqual(actual, test.expected, test.name);
  assert.equal(JSON.stringify(test.review), before, `${test.name}: no input or tolerance mutations`);
}
assert.equal(scope.ExecutionStandards.navigationLabel(diagnostics[0].review, 'active_coils'), '补充有效圈数');
assert.equal(scope.ExecutionStandards.navigationLabel(diagnostics[2].review, 'material'), '核对材料');
console.log(`Diagnostic parity: ${diagnostics.length} shared Python/browser root-cause and merge cases passed`);
