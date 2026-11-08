import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context = vm.createContext({});
for (const file of ['tolerance-values.js', 'tolerance-editor.js']) vm.runInContext(fs.readFileSync(`frontend/${file}`, 'utf8'), context);
const v = context.ToleranceValues, plain = value => JSON.parse(JSON.stringify(value));
for (const [input, expected] of [
  ['±0.1', [.1, -.1]], ['+0.1/-0.2', [.1, -.2]], ['0/-0.2', [0, -.2]], ['+0.1/0', [.1, 0]],
  ['0/0', [0, 0]], ['+0.2/+0.1', [.2, .1]], ['-0.1/-0.2', [-.1, -.2]], ['±1e-9', [1e-9, -1e-9]],
]) {
  const result = v.parse(input); assert.equal(result.ok, true, input);
  assert.deepEqual([result.upper, result.lower], expected, input);
  assert.equal(v.equals(result, v.parse(v.format(result))), true, input);
}
for (const input of ['1', '0.1/', '/-0.2', '±-1', 'NaN/0', 'Infinity/0', '-1/1', '++1/0']) assert.equal(v.parse(input).ok, false, input);
assert.equal(v.parse('±10%', { load: true }).percent, 10);
assert.equal(v.parse('10%').ok, false);
assert.equal(v.parse('-10%', { load: true }).ok, false);
assert.equal(v.preview(v.parse('+0.1/-0.2'), 10, 'mm'), '9.8 ～ 10.1 mm');
assert.match(v.preview(v.parse('±1'), '', 'mm'), /补齐/);
assert.deepEqual(plain(v.parse('')), { ok: true, upper: null, lower: null, percent: null });
assert.equal(v.format(v.read({ load_tolerance_upper: .1, load_tolerance_lower: -.2, load_tolerance_percent: 10 }, true)), '+0.1/-0.2');
let owner = 'a', committed = 0;
const items = { a: { value: 10, tolerance_upper: .1, tolerance_lower: -.2 }, b: { value: 12 } };
const controller = new context.ToleranceEditor.Controller({ owner: () => owner, resolve: () => ({ item: items[owner], nominal: items[owner].value, unit: 'mm' }), busy: () => false,
  render() {}, commit(d, r, result) { committed++; r.item.tolerance_upper = result.upper; r.item.tolerance_lower = result.lower; } });
controller.focus = () => {}; controller.restoreFocus = () => {};
controller.open('parameter', 'mean_diameter');
controller.current().upper = '+0.3'; assert.equal(items.a.tolerance_upper, .1);
controller.cancel(); assert.equal(items.a.tolerance_upper, .1);
controller.open('parameter', 'mean_diameter'); controller.current().upper = '+0.10'; controller.save(); assert.equal(committed, 0, 'format-only save preserves metadata');
controller.open('parameter', 'mean_diameter'); controller.current().upper = '+0.3';
owner = 'b'; assert.equal(controller.current(), undefined); controller.open('parameter', 'mean_diameter');
owner = 'a'; assert.equal(controller.current().upper, '+0.3', 'order-scoped draft retained');
items.a.value = 20; assert.match(controller.error(controller.current(), { item: items.a, nominal: 20, unit: 'mm' }, controller.result()), /已变化/);
controller.cancel(); controller.open('parameter', 'mean_diameter'); controller.current().upper = '+0.4'; controller.save();
assert.equal(committed, 1); assert.equal(items.a.tolerance_upper, .4);
console.log('PASS: signed tolerance parsing, validation, ranges, precision, canonical load priority, drafts, cancellation, no-op save, order isolation and baseline conflicts');
