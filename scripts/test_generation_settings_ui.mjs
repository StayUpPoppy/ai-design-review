import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';

const context = vm.createContext({ structuredClone });
for (const file of ['generation-settings', 'compression-design-checks', 'technical-requirement-equivalence', 'solidworks-export']) {
  vm.runInContext(fs.readFileSync(`frontend/${file}.js`, 'utf8'), context);
}
const plain = value => JSON.parse(JSON.stringify(value));
const settings = context.GenerationSettings;
assert.equal(settings.values({}, { real_name: '甲' }).typeface, '宋体');
assert.equal(settings.normalized({ drawing_model: 'X型', username: '甲' }).typeface, '宋体');
for (const typeface of ['', '楷体', null, 123, [], {}]) {
  assert.throws(() => settings.normalized({ drawing_model: 'X型', username: '甲', typeface }), /字体/);
}
const cases = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_generation_settings.py', '--json'], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 }));
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
for (const sample of cases) {
  const before = structuredClone(sample);
  const preview = context.SolidWorksExport.buildPreview(sample.package, sample.review, catalog);
  assert.deepEqual(plain(preview), sample.package.solidworks_preview, sample.name);
  if (sample.name.startsWith('new-')) {
    assert.deepEqual(plain(settings.normalized(settings.values(sample.review))), sample.package.generation_settings);
    assert.equal(Object.keys(preview)[Object.keys(preview).indexOf('Username') + 1], 'typeface');
  } else assert.equal(Object.hasOwn(preview, 'typeface'), false);
  assert.deepEqual(sample, before, 'Projection does not rewrite frozen or review data');
}
console.log('PASS: shared Python/JS fonts, default/enum, model placement, legacy snapshots and read-only projection.');
