import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/app.js', 'utf8');
const between = (start, end) => {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `${start} must exist`);
  return source.slice(a, b);
};
const optional = ['controlled_diameter_field', 'body_length', 'end_coils', 'straightness', 'permanent_set_limit'];
const fixed = ['support_coils', 'pitch', 'spring_rate', 'perpendicularity'];
const specialized = ['diameter_accuracy_grade', 'free_length_accuracy_grade', 'load_accuracy_grade', 'stiffness_accuracy_grade'];
const fields = ['wire_diameter', ...optional, ...fixed, ...specialized, 'legacy_value', 'legacy_empty'];
const context = vm.createContext({
  PARAMETER_COLLECTION_FIELDS: new Set(['load_points', 'torque_points']),
  COMPRESSION_CORE_PARAMETER_FIELDS: new Set(['wire_diameter']),
  getSpringTemplate: () => ({ fields: fields.map(key => ({ key })) }),
  isCompressionSpringReview: review => review.drawing_summary.spring_type === 'compression_spring',
});
vm.runInContext(between('const SPECIALIZED_ACCURACY_PARAMETER_FIELDS', 'const COMPRESSION_ACCURACY_GRADE_OPTIONS'), context);
vm.runInContext(between('function getParameterFields', 'const DEFAULT_CANDIDATE_NOTICE'), context);
vm.runInContext(between('function confirmationSheetIssues', 'function renderParameterTableHtml'), context);
const review = { drawing_summary: { spring_type: 'compression_spring' }, spring_parameters: {}, standardization_results: [] };
const visible = (field, value) => context.shouldShowAdvancedParameter(field, value, review);
for (const field of optional) {
  for (const item of [undefined, {}, { value: null }, { value: '' }, { value: '  ' },
    { evidence: '识别原文', source: ['qwen'], default_source: 'company_default', suggested_region: '图上区域' },
    { formula_recalculation_candidate: { value: 12 }, need_human_review: true }]) {
    review.standardization_results = [{ target_field: field, suggested_value: 20 }];
    assert.equal(visible(field, item), false, `${field}: metadata/suggestions do not create empty rows`);
  }
  for (const item of [{ value: 0 }, { value: 'invalid' }, { value: -1, derived_value_stale: true },
    { value: 12, source: ['formula_calculation'] }, { value: 1, source: ['human_edited'] },
    { value: null, tolerance_upper: 0 }, { tolerance_lower: -.1 }, { tolerance_input_draft: '±abc' }]) {
    assert.equal(visible(field, item), true, `${field}: actual values and unresolved input remain visible`);
  }
}
for (const field of fixed) assert.equal(visible(field, undefined), true, `${field}: blank input remains available`);
for (const field of specialized) assert.equal(visible(field, { value: 'T级', need_human_review: false, source: ['human_confirmed'] }), false);
review.spring_parameters = { legacy_value: { value: 7 }, legacy_empty: { evidence: '说明而非数值' } };
const before = JSON.stringify(review);
assert.deepEqual(Array.from(context.getParameterFieldGroups(review.spring_parameters, review).advanced), [...fixed, 'legacy_value']);
assert.equal(JSON.stringify(review), before, 'grouping never changes data or confirmations');
review.record_kind = 'variant'; review.multi_spec_origin = { variant_id: 'v1' };
assert.deepEqual(Array.from(context.getParameterFieldGroups(review.spring_parameters, review).advanced), [...fixed, 'legacy_value']);
review.drawing_summary.spring_type = 'torsion_spring';
assert.deepEqual(Array.from(context.getParameterFieldGroups(review.spring_parameters, review).core), fields, 'other spring types keep their current presentation');
review.parameter_reasonableness = { issues: [
  { severity: 'needs_input', fields: ['body_length'], message: '单纯缺值不询问客户' },
  { severity: 'warning', fields: ['straightness'], message: '实际冲突保留' },
  { fields: ['diameter_accuracy_grade'], message: '内部专项等级' },
  { fields: ['load_accuracy_grade', 'wire_diameter'], message: '关联的尺寸风险' },
  { fields: ['free_length', 'body_length'], message: '实际计算依赖不足' },
  { fields: [], message: '一般风险' },
] };
const diagnosticBefore = JSON.stringify(review);
const issues = JSON.parse(JSON.stringify(context.confirmationSheetIssues(review)));
assert.equal(issues.length, 4);
assert.deepEqual(issues[1].fields, ['wire_diameter']);
assert.equal(JSON.stringify(review), diagnosticBefore, 'report filtering does not edit saved diagnostics');
console.log('Advanced parameter visibility tests passed: empty/value/tolerance/stale, specialized grades, multi-spec, legacy data and report issues.');
