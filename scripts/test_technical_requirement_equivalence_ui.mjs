import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
const data = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe", ["scripts/test_technical_requirement_equivalence.py", "--json"], { encoding: "utf8" }));
const context = vm.createContext({ structuredClone });
for (const file of ["compression-design-checks.js", "technical-requirement-equivalence.js", "solidworks-export.js"]) vm.runInContext(fs.readFileSync(`frontend/${file}`, "utf8"), context);
const clean = (value) => JSON.parse(JSON.stringify(value));
const service = context.TechnicalRequirementEquivalence;
for (const test of data.pairs) {
  assert.equal(service.equivalent(test.a, test.b), test.same, test.left);
  assert.deepEqual(clean(service.key(test.a)), test.key_a);
  assert.deepEqual(clean(service.key(test.b)), test.key_b);
  assert.equal(service.formatText([test.a, test.b]), test.text);
  assert.equal(service.groups([test.a, test.b]).length, test.same ? 1 : 2, "front-end grouping follows the same engineering equivalence as SW");
}
const original = JSON.stringify(data.review.technical_requirements);
const groups = service.groups(data.review.technical_requirements);
assert.equal(groups.length, 6);
assert.deepEqual(clean(groups.map((group) => group.members.length)), [2, 2, 1, 2, 1, 1]);
assert.equal(JSON.stringify(data.review.technical_requirements), original);
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
assert.deepEqual(clean(context.SolidWorksExport.buildPreview(structuredClone(data.package), data.review, catalog)), data.package.solidworks_preview);
console.log(`PASS: ${data.pairs.length} engineering-note equivalence fixtures and order2 preview match Python exactly`);
