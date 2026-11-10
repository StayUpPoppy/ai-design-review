import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
const source = fs.readFileSync("frontend/app.js", "utf8"), context = vm.createContext({ structuredClone });
vm.runInContext(source.slice(source.indexOf("const Flattening ="), source.indexOf("const COMPRESSION_CORE_PARAMETER_FIELDS")) + "\nglobalThis.flat = Flattening;", context);
for (const file of ["compression-design-checks", "technical-requirement-equivalence", "solidworks-export"]) vm.runInContext(fs.readFileSync(`frontend/${file}.js`, "utf8"), context);
const cases = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe", ["scripts/test_flattening.py", "--json"], { encoding: "utf8" }));
for (const sample of cases) {
  const review = structuredClone(sample.review), item = review.spring_parameters.flattening;
  const preview = context.SolidWorksExport.buildPreview(structuredClone(sample.package), review, JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8")));
  assert.deepEqual(JSON.parse(JSON.stringify(preview)), sample.package.solidworks_preview, sample.name);
  assert.equal(context.flat.confirmed(item), sample.name.startsWith("confirmed-"), sample.name);
  assert.equal(!!context.flat.warning(item), !sample.name.startsWith("confirmed-"), sample.name);
}
const absent = { drawing_summary: { spring_type: "compression_spring" }, spring_parameters: {} };
assert.equal(context.flat.ensure(absent), true); assert.equal(absent.spring_parameters.flattening.value, 0);
assert.equal(context.flat.ensure(absent), false);
for (const item of [{ value: null, source: ["human_edited"] }, { value: null, flattening_conflict: true }, { value: 1 }, { value: 2 }]) {
  const review = { drawing_summary: { spring_type: "compression_spring" }, spring_parameters: { flattening: structuredClone(item) } };
  assert.equal(context.flat.ensure(review), false); assert.deepEqual(review.spring_parameters.flattening, item);
}
console.log(`PASS flattening UI: ${cases.length} shared eligibility/SW cases, defaults and manual/conflict preservation`);
