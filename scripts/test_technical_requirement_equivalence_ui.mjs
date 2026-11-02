import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
const data = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe", ["scripts/test_technical_requirement_equivalence.py", "--json"], { encoding: "utf8" }));
const context = vm.createContext({ structuredClone });
for (const file of ["compression-design-checks.js", "technical-requirement-equivalence.js", "solidworks-export.js"]) vm.runInContext(fs.readFileSync(`frontend/${file}`, "utf8"), context);
const clean = (value) => JSON.parse(JSON.stringify(value));
const service = context.TechnicalRequirementEquivalence;
for (const test of data.prefixes) {
  const before = JSON.stringify(test);
  assert.equal(service.format(test), test.expected);
  assert.equal(context.SolidWorksExport.technicalText({generation_parameters:{technical_requirements:[test]}},{}), test.expected ? `1.${test.expected}` : "");
  assert.equal(JSON.stringify(test), before);
}
for (const generation_parameters of [
  {technical_requirements:[{type:"heat_treatment",content:"720h"},{type:"salt_spray",content:"720h"}]},
  {technical_requirements_text:"1.热处理：720h\n2.盐雾试验：720h"},
]) assert.equal(context.SolidWorksExport.technicalText({generation_parameters},{}),"1.720h\n2.720h");
for (const test of data.pairs) {
  assert.equal(service.equivalent(test.a, test.b), test.same, test.left);
  assert.deepEqual(clean(service.key(test.a)), test.key_a);
  assert.deepEqual(clean(service.key(test.b)), test.key_b);
  assert.equal(service.formatText([test.a, test.b]), test.text);
  assert.equal(service.groups([test.a, test.b]).length, test.same ? 1 : 2, "front-end grouping follows the same engineering equivalence as SW");
  if (test.sw_text != null) assert.equal(context.SolidWorksExport.technicalText({ generation_parameters: { technical_requirements: [test.a, test.b] } }, {}), test.sw_text, `${test.id || test.left} final SW append path`);
}
const original = JSON.stringify(data.review.technical_requirements);
const groups = service.groups(data.review.technical_requirements);
assert.equal(groups.length, 6);
assert.deepEqual(clean(groups.map((group) => group.members.length)), [2, 2, 1, 2, 1, 1]);
assert.equal(JSON.stringify(data.review.technical_requirements), original);
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
assert.deepEqual(clean(context.SolidWorksExport.buildPreview(structuredClone(data.package), data.review, catalog)), data.package.solidworks_preview);
for (const [review, expected, count] of [[data.hardness_review, data.hardness_package, 2], [data.eight_review, data.eight_package, 8]]) {
  const before = JSON.stringify(review.technical_requirements);
  const grouped = service.groups(review.technical_requirements);
  assert.equal(grouped.length, count);
  if (count === 8) {
    assert.ok(grouped.every((group) => group.members.length === 2 && group.exportable && !group.confirmed));
    assert.equal(review.technical_requirements.length, 16);
  } else {
    assert.deepEqual(clean(grouped.map((group) => group.members.length)), [2, 1]);
    assert.equal(service.format(grouped[0].representative.item), "HRC45-50");
  }
  assert.equal(JSON.stringify(review.technical_requirements), before, "display never mutates originals");
  assert.deepEqual(clean(context.SolidWorksExport.buildPreview(structuredClone(expected), review, catalog)), expected.solidworks_preview);
}
assert.deepEqual(clean(context.SolidWorksExport.buildPreview(structuredClone(data.eight_pending_package), data.eight_review, catalog)), data.eight_pending_package.solidworks_preview);
console.log(`PASS: ${data.pairs.length} engineering-note fixtures, ${data.prefixes.length} prefix cases, eight groups and hardness 10 -> 7 SW notes match Python exactly`);
