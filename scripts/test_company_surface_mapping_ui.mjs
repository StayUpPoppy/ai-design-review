import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { execFileSync, spawnSync } from 'node:child_process';
const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };
const fixture = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_company_surface_mapping.py', '--json'], { encoding: 'utf8', env }));
const context = { structuredClone, console, window: {}, JSON };
vm.createContext(context);
for (const file of ['company-surface-mapping.js', 'compression-design-checks.js', 'technical-requirement-equivalence.js', 'solidworks-export.js']) vm.runInContext(fs.readFileSync(`frontend/${file}`, 'utf8'), context);
const mapping = context.CompanySurfaceMapping; mapping.setCatalog(fixture.catalog);
const id = (name) => fixture.catalog.items.find((v) => v.name === name).id;
const copy = () => structuredClone(fixture.review.technical_requirements[0]);
const checked = [];
function check(item, expected) { assert.equal(mapping.reason(item), expected); checked.push(structuredClone(item)); }
for (const value of fixture.catalog.items) assert.deepEqual([...mapping.namesInContent(value.name)], [value.id]);
let item = copy(); check(item, '');
mapping.choose(item, [id('电镀-镀白锌')]);
assert.equal(item.content, fixture.chinese.replace('电镀-镀彩锌', '电镀-镀白锌'));
check(item, ''); assert.match(item.content, /15 μm/); assert.match(item.content, /除氢/);
item.content = item.content.replace('电镀-镀白锌', '电镀-镀蓝锌'); mapping.edited(item);
assert.deepEqual([...item.surface_mapping.catalog_ids], [id('电镀-镀蓝锌')]); check(item, '');
const preserved = item.content; mapping.choose(item, []); check(item, '');
assert.equal(item.content, preserved); item.content += ' 保持清洁。'; mapping.edited(item);
assert.equal(item.surface_mapping.selection_mode, 'none'); assert.equal(item.surface_mapping.catalog_ids.length, 0); check(item, '');
item = copy(); item.content = '普通镀锌，保持清洁'; mapping.edited(item); check(item, '公司类型与正文不一致');
mapping.choose(item, []); check(item, '');
item = copy(); item.surface_mapping.catalog_ids = ['invented']; check(item, '公司类型无效，请重新选择或置空');
item = copy(); item.surface_mapping.conversion_status = 'needs_input'; check(item, '表面处理转换未完成，请补充中文要求');
mapping.choose(item, []); check(item, '表面处理转换未完成，请补充中文要求');
item.content = '人工补充中文工艺要求'; mapping.edited(item); check(item, '');
item = copy(); item.content = '电镀-镀彩锌，电镀-镀彩锌';
mapping.choose(item, [id('电镀-镀白锌')]);
assert.equal(item.content, '电镀-镀彩锌，电镀-镀彩锌'); check(item, '已选择公司类型，请核对正文中的工艺名称');
item = copy(); item.content = '清洗后上油'; mapping.edited(item);
assert.deepEqual([...item.surface_mapping.catalog_ids], [id('清洗')]); check(item, '');
assert.equal(item.content, '清洗后上油');
mapping.choose(item, [id('发黑')]); assert.equal(item.content, '发黑后上油'); check(item, '');
item = copy(); item.content = '表面处理：锌铝涂层，厚度8–12 μm，内侧不得涂覆。';
item.surface_mapping = { ...item.surface_mapping, catalog_ids: [], conversion_status: 'unmatched',
  verification: { version: 'surface-evidence/v1', status: 'verified', term: '锌铝涂层' } };
check(item, '');
mapping.choose(item, [id('达克罗')]); assert.equal(item.content, '表面处理：达克罗，厚度8–12 μm，内侧不得涂覆。'); check(item, '');
item = copy(); item.content = '喷丸。';
item.surface_mapping = { ...item.surface_mapping, catalog_ids: [], conversion_status: 'needs_input',
  verification: { version: 'surface-evidence/v1', status: 'uncertain', term: '' } };
check(item, '表面处理原文待核对，请对照原图补充正文');
mapping.choose(item, [id('抛丸')]); assert.equal(item.content, '抛丸。'); check(item, '表面处理原文待核对，请对照原图补充正文');
item.content = '抛丸。'; mapping.edited(item); check(item, '');
const uncertain = (content, readings = [], mode = 'auto') => ({ type: 'surface', content, need_human_review: true,
  surface_mapping: { catalog_ids: [], selection_mode: mode, conversion_status: 'needs_input', verification: { status: 'uncertain', readings } } });
const pending = uncertain('表面处理：表面处理\n镀锌五彩，厚度 8–12 μm；表面处理后烘干。');
assert.equal(context.TechnicalRequirementEquivalence.format(pending), '表面处理：镀锌五彩，厚度 8–12 μm；表面处理后烘干。');
assert.equal(mapping.confirmation(pending, { batch: true }).review, true);
const outcome = mapping.confirm(pending, true);
assert.deepEqual([...outcome.catalog_ids], [id('电镀-镀彩锌')]);
assert.equal(pending.content, '电镀-镀彩锌，厚度 8–12 μm；表面处理后烘干。');
const conflicting = uncertain('抛丸。', [{ source: 'initial', text: '5. 抛丸。' }, { source: 'local_ocr', text: '5. 喷丸。' }]);
assert.match(mapping.confirmation(conflicting, { batch: true }).reason, /读数有冲突/);
assert.equal(mapping.confirmation(conflicting).review, true);
assert.equal(mapping.confirm(conflicting).mode, 'single');
assert.equal(conflicting.surface_mapping.verification.readings.length, 2);
const confirmationCases = [
  uncertain('涂清漆。', [{ source: 'initial', text: '5. 涂漆。' }, { source: 'local_ocr', text: '5. 涂清漆。' }]),
  uncertain('抛丸。', [{ source: 'initial', text: '5. 抛丸。' }, { source: 'local_ocr', text: '5. 混丸。' }]),
  uncertain('抛丸。', [{ source: 'initial', text: '5. 抛丸。' }, { source: 'local_ocr', text: '5. 喷丸。' }]),
  uncertain('涂清漆，厚度 8 μm。', [{ text: '涂清漆，厚度 8 μm。' }, { text: '涂清漆，厚度 8 mm。' }]),
  uncertain('表面处理：\n表面处理'),
  uncertain('表面处理。', [], 'none'),
  uncertain('表面处理：涂清漆，厚度 □。'),
  { ...uncertain('抛丸。'), surface_mapping: { catalog_ids: [], selection_mode: 'auto', conversion_status: 'needs_input' } },
  uncertain('喷丸。', [], 'none'),
  { ...uncertain('涂清漆。'), unit_pending: true },
];
const decisions = confirmationCases.flatMap(item => [false, true].map(batch => ({ item, batch })));
const decisionParity = spawnSync('.venv/Scripts/python.exe', ['-c', "import sys,json;sys.path.insert(0,'src');from ai_design_review.surface_catalog import surface_confirmation;print(json.dumps([surface_confirmation(v['item'],batch=v['batch'])[:2] for v in json.load(sys.stdin)],ensure_ascii=True))"], { input: JSON.stringify(decisions), encoding: 'utf8', env });
assert.equal(decisionParity.status, 0, decisionParity.stderr);
assert.deepEqual(JSON.parse(decisionParity.stdout), decisions.map(({ item, batch }) => {
  const decision = mapping.confirmation(item, { batch });
  return [decision.reason, decision.review];
}));
const sourceCases = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_surface_source_links.py', '--json'], { encoding: 'utf8', env }));
for (const test of sourceCases) {
  const original = JSON.stringify(test.review);
  assert.deepEqual(JSON.parse(JSON.stringify(mapping.sourceLinks(test.review))), test.links);
  assert.deepEqual(JSON.parse(JSON.stringify(mapping.outputSourceKeys(test.review))).sort(), test.output_keys.sort());
  assert.equal(JSON.stringify(test.review), original);
}
for (const text of ['不得发黑', '不得进行发黑', '无需采用电镀-镀白锌', '不采用电镀-镀白锌', '镀锌', '喷塑']) assert.deepEqual([...mapping.namesInContent(text)], []);
assert.deepEqual([...mapping.namesInContent('不得进行发黑，先清洗后上油')], [id('清洗'), id('上油')]);
const parity = spawnSync('.venv/Scripts/python.exe', ['-c', "import sys,json;sys.path.insert(0,'src');from ai_design_review.surface_catalog import mapping_reason;print(json.dumps([mapping_reason(v) for v in json.load(sys.stdin)],ensure_ascii=True))"], { input: JSON.stringify(checked), encoding: 'utf8', env });
assert.equal(parity.status, 0, parity.stderr);
assert.deepEqual(JSON.parse(parity.stdout), checked.map((v) => mapping.reason(v)));
const preview = context.SolidWorksExport.buildPreview(structuredClone(fixture.package), fixture.review, {});
assert.equal(preview.technicalRequirements['技术要求'], fixture.package.solidworks_preview.technicalRequirements['技术要求']);
const legacy = structuredClone(fixture.package); legacy.generation_parameters.technical_requirements = []; legacy.generation_parameters.technical_requirements_text = fixture.raw + '\n消除应力退火';
assert.equal(context.SolidWorksExport.buildPreview(legacy, fixture.review, {}).technicalRequirements['技术要求'].includes('Fe/Ep'), false);
console.log(`Company surface UI: 49 names, linked edits, explicit none, unsafe replacement, compounds, ${checked.length} Python/JS parity cases and SW output passed`);
