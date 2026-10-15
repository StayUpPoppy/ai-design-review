import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';

const fixtures = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_formula_candidates.py', '--json'], {encoding:'utf8'}));
const source = fs.readFileSync('frontend/app.js','utf8');
const ctx = { TextEncoder, structuredClone, clearTimeout, state: {reviewEditSerial:0, reviewDraftFields:new Set(),lastJob:{review_revision:7}},
  sourceValues: v=>v||[], parseLoadPointTarget:()=>null, parameterPersistenceState:()=>null, dependencyFieldsIncludeField:(fields,f)=>fields.includes(f),
  parameterAuditState:v=>structuredClone(v), syncBubbleValue(){}, revokeManualConfirmations(){}, invalidateStandardizationResults(){}, markDependentFormulaParametersPending(){},
  standardizationResultDependsOnField:()=>false, normalizeReview:structuredClone, markStandardizationBatchState(){},
  lastStandardizationApplyHistory: r=>r.standardization_apply_history?.at(-1), bulkConfirmationFollowupReport:()=>null,
  escapeHtml: v=>String(v??''), targetFieldLabel:v=>v, formatCompactNumber:String,
  formatParameterDisplayValue:(_f,v,u)=>`${v}${u||''}`,
};
vm.createContext(ctx);
for (const file of ['compression-design-checks.js','formula-candidates.js']) vm.runInContext(fs.readFileSync(`frontend/${file}`,'utf8'),ctx);
function extract(start,end) { return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start))); }
vm.runInContext(extract('function renderParameterReasonablenessHtml','function renderParameterTableHtml'),ctx);
vm.runInContext(extract('function findReasonablenessSuggestion','async function recordReasonablenessSuggestionApplications'),ctx);
vm.runInContext(extract('function suggestionUndoChanges','function standardizationChatConstraints'),ctx);
const normalize = v=>JSON.parse(JSON.stringify(v));
const canonical = s=>({id:s.suggestion_id, target:s.target_field, value:s.suggested_value, unit:s.unit, status:s.status,
  token:s.dependency_token, formula:s.formula_candidate.formula, inputs:s.formula_candidate.inputs, purpose:s.formula_candidate.purpose,
  source_fields:s.formula_candidate.source_fields});
for (const fixture of fixtures) {
  const local = normalize(ctx.FormulaCandidates.merge(fixture.review, fixture.suggestions,7));
  const actual = local.filter(s=>s.suggestion_kind==='formula_candidate').map(canonical);
  const expected = fixture.suggestions.filter(s=>s.suggestion_kind==='formula_candidate').map(canonical);
  assert.deepEqual(actual,expected,fixture.name);
  assert.ok(!local.some(s=>s.suggestion_kind==='formula_candidate' && s.target_field==='support_coils'));
}
const baseline=()=>structuredClone(fixtures[0].review);
ctx.state.review=baseline();
let candidate=ctx.reasonablenessSuggestions()[0];
assert.equal(candidate.current_value,3.4438); assert.equal(candidate.suggested_value,3.6125);
assert.match(ctx.renderParameterReasonablenessHtml(ctx.state.review),/新公式候选，应用后需重新确认/);
const before=structuredClone(ctx.state.review);
const applied=ctx.applyReasonablenessSuggestions([candidate]);
assert.equal(applied.count,1); assert.equal(ctx.state.review.spring_parameters.pitch.value,3.6125);
assert.equal(ctx.state.review.spring_parameters.pitch.need_human_review,true);
assert.equal(ctx.FormulaCandidates.build(ctx.state.review).length,0);
assert.match(ctx.renderParameterReasonablenessHtml(ctx.state.review),/撤销上次应用/);
ctx.state.review.spring_parameters.unrelated={value:123};
assert.ok(ctx.undoLastStandardizationApplication());
assert.deepEqual(ctx.state.review.spring_parameters.pitch,before.spring_parameters.pitch);
assert.equal(ctx.state.review.spring_parameters.unrelated.value,123);
candidate=ctx.reasonablenessSuggestions()[0];ctx.applyReasonablenessSuggestions([candidate]);
ctx.state.review.spring_parameters.pitch.value=3.8;
ctx.state.review.spring_parameters.pitch.human_modified=true;
assert.ok(!ctx.reasonablenessSuggestions().some(i=>i.suggestion_kind==='formula_candidate'),'Manual edit removes the previously applied candidate card');
assert.equal(ctx.undoLastStandardizationApplication(),null);assert.match(ctx.state.suggestionUndoConflict,/又有修改/);
// Batch candidate application and undo restore both targets without confirming.
ctx.state.review=structuredClone(fixtures.find(f=>f.name==='nominal').review);
const batchBefore=structuredClone(ctx.state.review.spring_parameters);
const batch=ctx.FormulaCandidates.build(ctx.state.review);
assert.equal(batch.length,2);
assert.equal(ctx.applyReasonablenessSuggestions(batch).count,2);
assert.equal(ctx.state.review.spring_parameters.solid_height.need_human_review,true);
assert.ok(ctx.undoLastStandardizationApplication());
assert.deepEqual(ctx.state.review.spring_parameters,batchBefore);
// Same value, new dependencies is actionable and still requires reconfirmation.
ctx.state.review=structuredClone(fixtures.find(f=>f.name==='same-value-new-inputs').review);
candidate=ctx.reasonablenessSuggestions()[0];assert.equal(ctx.reasonablenessSuggestionControlState(candidate).disabled,false);
assert.equal(ctx.applyReasonablenessSuggestions([candidate]).count,1);
assert.equal(ctx.state.review.spring_parameters.pitch.need_human_review,true);
// Snapshot freshness includes units, formula and height purpose, not merely numeric equality.
ctx.state.review=baseline();candidate=ctx.reasonablenessSuggestions()[0];ctx.state.review.spring_parameters.free_length.unit='cm';
assert.equal(ctx.FormulaCandidates.apply(ctx.state.review,candidate),false);
for (const name of ['reference','nominal']) {
  const r=structuredClone(fixtures.find(f=>f.name===name).review);
  const item=ctx.FormulaCandidates.build(r).find(s=>s.target_field==='solid_height');
  assert.ok(ctx.FormulaCandidates.apply(r,item));ctx.CompressionDesignChecks.applyPitch(r);
  assert.equal(r.spring_parameters.solid_height.value_kind,item.formula_candidate.purpose);
  assert.equal(r.spring_parameters.solid_height.need_human_review,true);
}
// Batch sees initial proposals only; downstream changed proposal is deferred.
const r=baseline();
ctx.state.review=r;ctx.state.lastJob.review_revision=7;
const upstream={suggestion_id:'free-new',source:'standardization',target_field:'free_length',current_value:28.9,suggested_value:32,
  application_mode:'value',rule_id:'NEW-FREE',source_fields:[],dependency_token:ctx.reasonablenessDependencyToken({}),status:'available'};
r.parameter_reasonableness.suggestions=[upstream];
ctx.fetchReasonablenessAssessmentForReview=async review=>({suggestions:ctx.FormulaCandidates.build(review,7)});
const plan=ctx.reasonablenessSuggestionBatchPlan(r);
const preview=await ctx.preflightReasonablenessSuggestionBatch(plan);
assert.equal(preview.ok,true);assert.ok(preview.items.some(i=>i.target_field==='free_length'));
assert.ok(preview.deferred.some(i=>i.target_field==='pitch' && /尚未查看/.test(i.reason)),JSON.stringify(preview));
assert.equal(r.spring_parameters.free_length.value,28.9,'preflight never mutates live review');
console.log(`formula candidate UI tests passed: ${fixtures.length} shared fixtures, apply/undo/conflict/purpose/batch`);
