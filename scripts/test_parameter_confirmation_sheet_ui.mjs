import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('frontend/parameter-confirmation-sheet.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('frontend/compression-design-checks.js', 'utf8'), context);
const api = context.ParameterConfirmationSheet;
const logoData = `data:image/png;base64,${fs.readFileSync('frontend/assets/incospring-logo.png').toString('base64')}`;
const render = (model, selected) => api.documentHtml(model, selected, { logoData, renderId: 'unit' });
assert.equal(api.tolerance({ tolerance_upper: .1, tolerance_lower: -.1 }), '±0.1');
assert.equal(api.tolerance({ tolerance_upper: 1, tolerance_lower: 0 }), '+1 / 0');
assert.equal(api.tolerance({ tolerance_upper: 1 }), '+1 / 未注明');
assert.equal(api.tolerance({ load_tolerance_percent: 10 }, true), '±10%');
assert.equal(api.tolerance({ tolerance_input_draft: '±abc' }), '±abc');
const data = { info: { drawingName: '<script>alert(1)</script>', drawingNo: '00123-A', date: '2026/10/27', local: true },
  parameters: [{ id: 'param:n', field: 'n', label: '总圈数', value: 10.5, state: '已确认', unit: '圈' },
    { id: 'param:a', field: 'a', label: '缺失值', value: null, state: '待补充' }],
  advanced: [{ id: 'param:optional', field: 'optional', label: '空高级参数', value: null, state: '待补充' }],
  loads: [{ id: 'load:zero', field: 'load_points.F1', label: 'F1', height: '5 mm', force: '0 N', state: '待确认', tolerance: '±10%' }],
  requirements: [{ id: 'technical:1', field: 'technical_requirements.1', label: '其他', content: '<img src=x onerror=alert(1)>', state: '待确认' }],
  issues: [{ fields: ['a'], message: '缺少依据' }, { fields: ['a'], message: '缺少依据' }],
  suggestions: [{ field: 'a', value: '12.5 μm', basis: '项目参考' }, { field: 'a', value: '6.3 μm', basis: '项目参考' },
    { field: 'a', value: '9999', stale: true }, { field: 'n', value: '500', basis: '不应展示' }] };
const before = JSON.stringify(data), model = api.buildModel(data), issues = model.sections.find(s => s.id === 'issues').rows;
assert.equal(JSON.stringify(data), before, 'building does not alter the report inputs');
assert.equal(issues.filter(i => i.field === 'a').length, 1);
assert.equal(issues.find(i => i.field === 'a').messages.filter(m => m === '缺少依据').length, 1);
assert.equal(issues.find(i => i.field === 'a').suggestions.length, 3, 'different proposals survive');
assert.equal(issues.some(i => i.field === 'n'), false, 'healthy confirmed fields do not acquire questions');
assert.equal(issues.some(i => i.field === 'load_points.F1'), false, 'pending internal confirmation alone is not a customer issue');
assert.equal(issues.some(i => i.field === 'technical_requirements.1'), false);
assert.deepEqual(Array.from(model.sections, s => s.label), ['输入参数', '载荷测试点', '设计校核结果', '技术要求', '问题与建议']);
assert.equal(model.sections.filter(s => s.id === 'parameters').length, 1);
assert.equal(model.sections.some(s => s.id === 'advanced'), false);
assert.deepEqual(Array.from(model.sections[0].rows, row => row.id), ['param:n', 'param:a', 'param:optional'], 'merge preserves the original order and row identities');
const html = render(model);
assert.match(html, /00123-A/); assert.match(html, /10\.5/); assert.match(html, /0 N/);
assert.match(html, /待补充/); assert.match(html, /本地数据/);
assert.match(html, /&lt;script&gt;/); assert.match(html, /&lt;img/);
assert.doesNotMatch(html, /<script>|<img src=x|9999|不应展示/);
assert.equal((html.match(/<img\b/g) || []).length, 1, 'the only image is the bundled logo');
assert.match(html, /alt="IncoSpring"/); assert.ok(html.includes(logoData));
assert.match(html, /margin: 32mm 14mm 14mm/); assert.match(html, /width: 38mm/);
assert.match(html, /@top-left/); assert.match(html, /@top-center/);
assert.throws(() => api.documentHtml(model, undefined, { logoData: 'https://example.com/logo.png' }), /Logo/);
assert.throws(() => api.documentHtml({ ...model, logoData }), /Logo/, 'review/model data cannot supply a logo');
assert.match(html, /size: A4 portrait/); assert.match(html, /table-header-group/);
assert.match(html, /客户确认/); assert.match(html, /修改意见/); assert.match(html, /空高级参数/);
assert.equal((html.match(/<h2>输入参数<\/h2>/g) || []).length, 1);
assert.doesNotMatch(html, /<h2>基础参数<\/h2>|<h2>高级参数<\/h2>/);
assert.doesNotMatch(html, /审图修订|已确认|>待确认<|<th scope="col">状态/);
assert.doesNotMatch(html, /<input|checked/);
const rowCount = model.sections.reduce((sum, section) => sum + section.rows.length, 0);
assert.equal((html.match(/class="paper-check"/g) || []).length, rowCount * 2, 'each row has two empty paper boxes');
const selected = new Set(['param:n']);
const reduced = render(model, selected);
assert.match(reduced, /10\.5/); assert.doesNotMatch(reduced, /缺失值|待确认建议/);
assert.match(reduced, /客户确认/);
const onlyAdvanced = render(model, new Set(['param:optional']));
assert.match(onlyAdvanced, /<h2>输入参数<\/h2>/); assert.match(onlyAdvanced, /空高级参数/);
assert.doesNotMatch(onlyAdvanced, /缺失值|总圈数/);
const fixture = JSON.parse(fs.readFileSync('data/test/compression_design_checks.json', 'utf8'));
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const review = structuredClone(fixture.base), engine = context.CompressionDesignChecks;
engine.applyPitch(review);
const original = JSON.stringify(review);
const checks = engine.calculate(review.spring_parameters, review.spring_features, catalog);
const calculations = api.calculationRows(checks);
const hiddenMetrics = new Set(['reference_solid_height_limit', 'solid_height_used']);
const printedMetricCount = metrics => Object.keys(metrics).filter(key => !hiddenMetrics.has(key)).length;
assert.equal(calculations.length, printedMetricCount(checks.metrics) + checks.work_stresses.length);
assert.equal(JSON.stringify(review), original, 'calculating and formatting do not apply values');
const row = key => calculations.find(r => r.id === `calculation:${key}`);
assert.equal(row('theoretical_spring_rate').value, Number(checks.metrics.theoretical_spring_rate.value.toFixed(4)));
assert.notEqual(row('theoretical_spring_rate').value, review.spring_parameters.spring_rate.value, 'drawing stiffness is kept separate');
assert.match(row('unit_mass').note, /估算/);
assert.equal(row('nominal_solid_height').label, '压并高度');
assert.equal(row('nominal_solid_height').value, Number(checks.metrics.nominal_solid_height.value.toFixed(4)));
assert.match(row('nominal_solid_height').note, /估算/);
for (const key of hiddenMetrics) assert.equal(row(key), undefined, `${key} stays internal to the calculator`);
const confirmation = api.buildModel({ info: {}, calculations });
assert.doesNotMatch(render(confirmation), /名义压并高度|压并高度上限参考|应力采用高度/);
for (const key of hiddenMetrics) assert.equal(confirmation.sections.at(-1).rows.some(item => item.field === `calculations.${key}`), false);
const abnormal = api.calculationRows({ metrics: {
  spring_index: { status: 'not_applicable', value: 999, reason: '变节距' },
  solid_height_used: { status: 'not_required', value: 888, reason: '已有明确压并力' },
  reference_solid_height_limit: { status: 'missing_context', value: null, reason: '缺少内部计算依据' },
  unit_mass: { value: 1e-10, unit: 'kg', status: 'calculated' },
}, work_stresses: [{ label: 'F1', load_point_id: 'p1', value: 0, unit: 'MPa', force_n: 0, status: 'calculated' },
  { label: 'F2', load_point_id: 'p2', value: null, status: 'missing_context', reason: '缺少高度' },
  { label: 'F3', load_point_id: 'p3', value: 15, force_n: 5, status: 'estimated' }] });
assert.equal(abnormal.find(r => r.id === 'calculation:spring_index').value, '不适用');
assert.equal(abnormal.find(r => r.id === 'calculation:solid_height_used'), undefined);
assert.equal(abnormal.find(r => r.id === 'calculation:reference_solid_height_limit'), undefined);
assert.equal(abnormal.find(r => r.id === 'calculation:unit_mass').value, 1e-10, 'small nonzero mass stays nonzero');
assert.equal(abnormal.find(r => r.id === 'calculation:work_stress:p1').value, 0);
assert.match(abnormal.find(r => r.id === 'calculation:work_stress:p2').note, /无法计算：缺少高度/);
assert.match(abnormal.find(r => r.id === 'calculation:work_stress:p3').note, /估算载荷：5 N；估算/);
const paper = render(api.buildModel({ info: {}, calculations: abnormal }));
assert.doesNotMatch(paper.replace(/<style>[\s\S]*?<\/style>/g, '').replace(/src="data:image\/png;base64,[^"]*"/g, ''), /999|888|无法计算 MPa|缺少内部计算依据|应力采用高度|压并高度上限参考/);
assert.match(paper, /工作应力（F1）/); assert.match(paper, /工作应力（F2）/);
const first = { review: {}, revision: 1, materialCatalog: { version: 'v1', items: [{ shear_modulus_mpa: 71500 }] } };
assert.notEqual(api.fingerprint(first), api.fingerprint({ ...first, revision: 2 }));
assert.notEqual(api.fingerprint(first), api.fingerprint({ ...first, materialCatalog: { ...first.materialCatalog, version: 'v2' } }));
for (const example of fixture.cases) {
  const copy = structuredClone(fixture.base);
  for (const [field, value] of Object.entries(example.overrides || {})) {
    if (value && !Array.isArray(value) && typeof value === 'object') Object.assign(copy.spring_parameters[field] ||= {}, value);
    else copy.spring_parameters[field] = value;
  }
  Object.assign(copy.spring_features, example.features || {}); engine.applyPitch(copy);
  const frozen = JSON.stringify(copy), result = engine.calculate(copy.spring_parameters, copy.spring_features, catalog), rows = api.calculationRows(result);
  assert.equal(JSON.stringify(copy), frozen, example.name);
  assert.equal(rows.length, printedMetricCount(result.metrics) + result.work_stresses.length, example.name);
  assert.ok(rows.every(r => r.value != null && r.value !== ''), example.name);
}
console.log('Parameter confirmation sheet model, escaping, selection and tolerance tests passed.');
