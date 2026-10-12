import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";

const fixture = JSON.parse(fs.readFileSync("data/test/compression_design_checks.json", "utf8"));
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const context = vm.createContext({});
vm.runInContext(fs.readFileSync("frontend/compression-design-checks.js", "utf8"), context);
const engine = context.CompressionDesignChecks;
const python = process.env.DESIGN_TEST_PYTHON || "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const serverResults = JSON.parse(execFileSync(python, ["scripts/test_compression_design_values.py", "--json"], { encoding: "utf8" }));
function compare(actual, expected, path) {
  if (typeof expected === "number") assert.ok(typeof actual === "number" && Math.abs(actual-expected) <= 1e-10 * Math.max(1,Math.abs(expected)), `${path}: ${actual} != ${expected}`);
  else if (expected && typeof expected === "object") {
    assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), path);
    for (const key of Object.keys(expected)) compare(actual[key], expected[key], `${path}.${key}`);
  } else assert.equal(actual, expected, path);
}
for (const [index, test] of fixture.cases.entries()) {
  const review = structuredClone(fixture.base);
  for (const [field, value] of Object.entries(test.overrides || {})) {
    if (value && !Array.isArray(value) && typeof value === "object") Object.assign(review.spring_parameters[field] ||= {}, value);
    else review.spring_parameters[field] = value;
  }
  Object.assign(review.spring_features, test.features || {});
  engine.applyPitch(review);
  const checks = engine.calculate(review.spring_parameters, review.spring_features, catalog);
  compare(JSON.parse(JSON.stringify(checks)), serverResults[index].checks, test.name);
  assert.equal(review.spring_parameters.spring_rate.value, 99);
}
const review = structuredClone(fixture.base);
engine.applyPitch(review);
const pitch = review.spring_parameters.pitch;
Object.assign(pitch, { need_human_review: false, source: ["formula_calculation", "human_confirmed"] });
review.spring_parameters.free_length.value = 40;
engine.applyPitch(review);
assert.equal(pitch.value, 3.3);
assert.equal(pitch.derived_value_stale, true);
assert.equal(engine.calculate(review.spring_parameters, review.spring_features, catalog).metrics.unit_mass.value, null);
review.spring_parameters.free_length.value = 36;
engine.applyPitch(review);
assert.equal(pitch.derived_value_stale, false);
const derived = structuredClone(fixture.base);
derived.spring_parameters.support_coils.value = null;
engine.applyPitch(derived);
const support = derived.spring_parameters.support_coils;
assert.equal(support.value, 1);
assert.equal(support.need_human_review, true);
Object.assign(support, { need_human_review: false, source: ["formula_calculation", "human_confirmed"] });
derived.spring_parameters.active_coils.value = 9;
engine.applyPitch(derived);
assert.equal(support.value, 1);
assert.equal(support.derived_value_stale, true);
assert.equal(engine.calculate(derived.spring_parameters, derived.spring_features, catalog).metrics.unit_mass.value, null);
derived.spring_parameters.active_coils.value = 10;
engine.applyPitch(derived);
assert.equal(support.derived_value_stale, false);
Object.assign(support, { value: "", source: ["human_edited"], need_human_review: true });
engine.applyPitch(derived);
assert.equal(support.value, "");
console.log(`compression design values UI: ${fixture.cases.length} Python/JS parity cases and confirmed pitch protection passed`);
