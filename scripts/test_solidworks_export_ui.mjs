import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
const python = process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe";
const cases = JSON.parse(execFileSync(python, ["scripts/test_solidworks_export.py", "--json"], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
const context = vm.createContext({ structuredClone });
for (const file of ["frontend/compression-design-checks.js", "frontend/technical-requirement-equivalence.js", "frontend/solidworks-export.js"]) vm.runInContext(fs.readFileSync(file, "utf8"), context);
const labelCases = JSON.parse(execFileSync(python, ["scripts/test_solidworks_export.py", "--label-json"], { encoding: "utf8" }));
for (const sample of labelCases) {
  const original = structuredClone(sample.review), generation = structuredClone(sample.package.generation_parameters);
  const result = context.SolidWorksExport.buildPreview(structuredClone(sample.package), sample.review);
  assert.equal(result.extraProperties["技术要求"], sample.expected_text, sample.name);
  assert.equal(result.customProperties["旋向"], ({left:"左旋",right:"右旋"})[sample.package.generation_parameters.spring_parameters.handedness?.value] ?? null);
  assert.deepEqual(sample.review, original, `${sample.name} keeps review text and confirmation`);
  assert.deepEqual(sample.package.generation_parameters, generation, `${sample.name} keeps internal text`);
}
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const appSource = fs.readFileSync("frontend/app.js", "utf8");
Object.assign(context, {
  currentSpringType: (review) => review.drawing_summary?.spring_type,
  getLocalTemplate: () => ({ fields: [] }),
  blankParam: (unit) => ({ value: null, unit, need_human_review: true }),
  sourceValues: (source) => (Array.isArray(source) ? source : [source]).filter(Boolean),
  TECH_REQUIREMENT_TYPES: ["surface", "surface_roughness", "hardness", "heat_treatment", "salt_spray", "environmental", "lifetime", "process", "other"],
});
for (const [start, end] of [["function normalizeTechnicalRequirementType", "function technicalRequirementConfirmationKey"],
  ["function ensureSurfaceRoughnessParameter", "function surfaceRoughnessMentions"]]) {
  const first = appSource.indexOf(start);
  vm.runInContext(appSource.slice(first, appSource.indexOf(end, first)), context);
}
for (const test of cases) {
  const normalized = structuredClone(test.input_review);
  context.ensureSurfaceRoughnessParameter(normalized);
  assert.deepEqual(normalized.technical_requirements, test.review.technical_requirements, `${test.name} legacy Ra promotion preserves other scopes/conditions`);
  for (const key of ["value", "unit", "surface_location", "need_human_review", "roughness_conflict"]) {
    assert.deepEqual(normalized.spring_parameters.surface_roughness_ra[key] ?? null,
      test.review.spring_parameters.surface_roughness_ra[key] ?? null, `${test.name} normalized ${key}`);
  }
  const beforeProjection = structuredClone(test.review);
  const projection = context.SolidWorksExport.technicalProjection(structuredClone(test.package), test.review, catalog);
  assert.equal(projection.text, test.package.solidworks_preview.extraProperties["技术要求"], `${test.name} projection text`);
  assert.equal(projection.entries.map((entry, index) => `${index + 1}.${entry.body}`).join("\n"), projection.text);
  assert.deepEqual(test.review, beforeProjection, `${test.name} projection is read-only`);
  const input = structuredClone(test.package);
  delete input.solidworks_preview;
  const preview = context.SolidWorksExport.buildPreview(input, test.review, catalog);
  assert.deepEqual(JSON.parse(JSON.stringify(preview)), test.package.solidworks_preview, test.name);
  assert.deepEqual(Object.keys(preview.titleBlockProperties), ["材料", "重量", "客户图号", "垂直度A", "表面粗糙度"].filter((key) => Object.hasOwn(preview.titleBlockProperties, key)), `${test.name} title-block order`);
  assert.deepEqual(input.source, test.package.source, `${test.name} source snapshot is not rewritten`);
  assert.deepEqual(JSON.parse(JSON.stringify(input.derived_parameters.solidworks_design_checks.metrics.unit_mass)),
    test.package.derived_parameters.solidworks_design_checks.metrics.unit_mass, `${test.name} frozen weight basis`);
  const points = test.review.spring_parameters.load_points.filter((p) => p.need_human_review === false)
    .map(context.SolidWorksExport.exportLoadPoint).filter(Boolean);
  assert.deepEqual(JSON.parse(JSON.stringify(points)), test.package.generation_parameters.load_points, `${test.name} load export`);
}
const baselineProjection = context.SolidWorksExport.technicalProjection(cases[0].package, cases[0].review, catalog);
for (const [text, scope, expected] of [
  ["绕制方向：右旋。", undefined, true], ["总圈数：4 圈。", undefined, true],
  ["总圈数：4，有效圈数：2。", undefined, true], ["两端并紧磨平，每端磨270°。", undefined, true],
  ["总圈数：4，有效圈数：3。", undefined, false], ["旋向：左旋。", undefined, false],
  ["旋向：右旋。", "备用弹簧", false], ["两端并紧磨平，每端磨300°。", undefined, false],
  ["有效圈数：2 圈，端面去毛刺。", undefined, false], ["材料：SUS304。", undefined, false],
]) assert.equal(context.SolidWorksExport.automaticMatches(baselineProjection, { type:"other",content:text,application_scope:scope }, catalog).length > 0, expected, text);
const loadNote = baselineProjection.entries.find(entry => entry.automatic && entry.body.includes("工作载荷 F1"));
assert.ok(loadNote.fields.includes("load_points.F1"));
assert.equal(context.SolidWorksExport.automaticMatches(baselineProjection, {type:"other",content:loadNote.body}, catalog).length, 1);
assert.equal(context.SolidWorksExport.automaticMatches(baselineProjection, {type:"other",content:loadNote.body.replace("F1", "P1")}, catalog).length, 0);
assert.equal(context.SolidWorksExport.automaticMatches(baselineProjection, {type:"other",content:loadNote.body.replace("±10%", "±11%")}, catalog).length, 0);
assert.equal(baselineProjection.entries.slice(0,3).every(entry => entry.automatic), true);
const originalCalculate = context.CompressionDesignChecks.calculate;
const base = cases[0];
for (const value of [NaN, Infinity, -Infinity, -1, 0]) {
  context.CompressionDesignChecks.calculate = (...args) => {
    const result = originalCalculate(...args);
    result.metrics.unit_mass = { ...result.metrics.unit_mass, value, status: "estimated" };
    return result;
  };
  assert.equal(context.SolidWorksExport.buildPreview(structuredClone(base.package), base.review, catalog).titleBlockProperties["重量"], undefined);
}
context.CompressionDesignChecks.calculate = originalCalculate;
// Rebuilding a preview against newer inputs must not reuse a stale end template.
for (const [field, updates] of [
  ["end_type", { value: "两端不并紧" }], ["end_grinding", { value: "invalid" }],
  ["end_type", { need_human_review: true }], ["end_grinding", { derived_value_stale: true }],
]) {
  const changed = structuredClone(base.review);
  Object.assign(changed.spring_parameters[field], updates);
  const rebuilt = context.SolidWorksExport.buildPreview(structuredClone(base.package), changed, catalog);
  assert.ok(!rebuilt.extraProperties["技术要求"].startsWith("1.两端"), `new snapshot ${field} does not reuse frozen end state`);
}
for (const value of [NaN, Infinity, -Infinity, 0, -1, true, "0x10", "1_2"]) {
  const invalid = structuredClone(base.review);
  invalid.spring_parameters.surface_roughness_ra.value = value;
  assert.equal(context.SolidWorksExport.buildPreview(structuredClone(base.package), invalid, catalog).titleBlockProperties["表面粗糙度"], undefined);
}
for (const value of [NaN, Infinity, -Infinity, true, {}, []]) {
  const invalid = structuredClone(base.review);
  invalid.spring_parameters.outer_diameter = { value:28.8, unit:"mm", need_human_review:false, tolerance_upper:value, tolerance_lower:-1 };
  invalid.spring_parameters.perpendicularity = { value, unit:"mm", need_human_review:false };
  const projected = context.SolidWorksExport.buildPreview(structuredClone(base.package), invalid, catalog);
  assert.equal(projected.modelParametersTolerance, undefined);
  assert.equal(projected.titleBlockProperties["垂直度A"], undefined);
}
console.log(`PASS: ${cases.length} shared SW cases match Python and JavaScript exactly`);
