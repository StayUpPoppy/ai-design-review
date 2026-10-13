import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
const python = process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe";
const cases = JSON.parse(execFileSync(python, ["scripts/test_solidworks_export.py", "--json"], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
const context = vm.createContext({ structuredClone });
for (const file of ["frontend/compression-design-checks.js", "frontend/technical-requirement-equivalence.js", "frontend/solidworks-export.js"]) vm.runInContext(fs.readFileSync(file, "utf8"), context);
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
for (const test of cases) {
  const input = structuredClone(test.package);
  delete input.solidworks_preview;
  const preview = context.SolidWorksExport.buildPreview(input, test.review, catalog);
  assert.deepEqual(JSON.parse(JSON.stringify(preview)), test.package.solidworks_preview, test.name);
  assert.deepEqual(JSON.parse(JSON.stringify(input.derived_parameters.solidworks_design_checks.metrics.unit_mass)),
    test.package.derived_parameters.solidworks_design_checks.metrics.unit_mass, `${test.name} frozen weight basis`);
  const points = test.review.spring_parameters.load_points.filter((p) => p.need_human_review === false)
    .map(context.SolidWorksExport.exportLoadPoint).filter(Boolean);
  assert.deepEqual(JSON.parse(JSON.stringify(points)), test.package.generation_parameters.load_points, `${test.name} load export`);
}
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
console.log(`PASS: ${cases.length} shared SW cases match Python and JavaScript exactly`);
