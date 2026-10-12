import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
function extract(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `Cannot extract ${start}`);
  return source.slice(first, last);
}
const drawing = (value) => ({ value, unit: "mm", source: ["qwen_vision"], need_human_review: true });
const confirmed = (value) => ({ ...drawing(value), source: ["human_confirmed"], need_human_review: false });
const formula = (value, fields, extra = {}) => ({
  ...drawing(value), source: ["formula_calculation"], source_fields: fields,
  formula_calculation_kind: "diameter_completion", formula_calculation_status: "calculated", ...extra,
});
function baseline() {
  return {
    wire_diameter: confirmed(2), outer_diameter: confirmed(20),
    mean_diameter: formula(18, ["outer_diameter", "wire_diameter"]),
    inner_diameter: formula(16, ["outer_diameter", "wire_diameter"]), free_length: confirmed(36),
  };
}

function setup(parameters = baseline()) {
  const review = {
    spring_parameters: parameters, manual_confirmations: {}, standardization_results: [],
    parameter_reasonableness: { suggestions: [] },
    balloons: Object.keys(parameters).map((field) => ({ field, value: String(parameters[field].value) })),
  };
  const context = {
    state: { review, reviewEditSerial: 0, reviewDraftFields: new Set() }, structuredClone,
    formatCompactNumber: (value) => String(Number(Number(value).toFixed(4))),
    targetFieldLabel: (field) => field,
    syncConfirmationControl(row, item) {
      row.confirmation = { pending: item.need_human_review, stale: Boolean(item.derived_value_stale) };
    },
  };
  vm.createContext(context);
  vm.runInContext(extract("function confirmParam(", "function makeExportReview("), context);
  vm.runInContext(extract("function compressionDesignCheckValues(", "function loadPointTableHeadHtml("), context);
  const rows = Object.fromEntries(Object.entries(parameters).map(([field, item]) => [field, {
    dataset: { field }, input: { value: String(item.value ?? "") },
    querySelector() { return this.input; },
  }]));
  const metrics = {};
  const container = { querySelector(selector) {
    const key = `${selector.includes("design-check-basis") ? "basis" : "value"}:${selector.match(/data-metric="([^"]+)"/)[1]}`;
    return metrics[key] ||= { textContent: "" };
  } };
  const root = { querySelectorAll(selector) {
    return selector.includes("compression-design-check") ? [container] : Object.values(rows);
  } };
  const refresh = () => context.refreshCompressionDesignChecks(root, review);
  const edit = (field, value) => {
    const item = parameters[field];
    context.rememberConfirmedSnapshot(item);
    item.value = value;
    rows[field].input.value = String(value ?? "");
    context.applyEditedConfirmationState(item, field);
    context.syncDependentFormulaParameterRows(root, review, field);
    refresh();
  };
  refresh();
  return { context, review, rows, metrics, root, edit, refresh };
}
function assertChecks(test, springIndex, slendernessRatio) {
  assert.equal(test.metrics["value:spring_index"].textContent, springIndex);
  assert.equal(test.metrics["value:slenderness_ratio"].textContent, slendernessRatio);
}

// A stale DOM value must never override an already updated parameter.
{
  const test = setup();
  assertChecks(test, "9", "2");
  test.review.spring_parameters.outer_diameter.value = 22;
  test.context.markDependentFormulaParametersPending("outer_diameter");
  assert.equal(test.rows.mean_diameter.input.value, "18");
  test.refresh();
  assertChecks(test, "10", "1.8");
  test.context.syncDependentFormulaParameterRows(test.root, test.review, "outer_diameter");
  assert.equal(test.rows.mean_diameter.input.value, "20");
  assert.equal(test.rows.inner_diameter.input.value, "18");
  assert.deepEqual(test.rows.mean_diameter.confirmation, { pending: true, stale: false });
  assert.equal(test.review.balloons.find((item) => item.field === "mean_diameter").value, "20");
}
{
  const test = setup();
  test.review.standardization_results.push({ status: "suggested", metadata: { source_fields: ["mean_diameter"] } });
  test.review.parameter_reasonableness.suggestions.push({ status: "suggested", source_fields: ["mean_diameter"] });
  test.edit("outer_diameter", 22);
  assertChecks(test, "10", "1.8");
  assert.equal(test.review.standardization_results[0].status, "stale");
  assert.equal(test.review.parameter_reasonableness.suggestions[0].status, "stale");
  test.edit("outer_diameter", 20);
  assertChecks(test, "9", "2");
  assert.equal(test.rows.mean_diameter.input.value, "18", "Restoring a confirmed input still updates its dependents");
  assert.equal(test.review.spring_parameters.outer_diameter.need_human_review, false);
}
// All declared diameter relations, including downstream calculations stored
// before their parents, must use the current sources rather than array order.
{
  const test = setup({ wire_diameter: confirmed(2), inner_diameter: drawing(16),
    mean_diameter: formula(18, ["inner_diameter", "wire_diameter"]), free_length: confirmed(36) });
  test.edit("inner_diameter", 18);
  assertChecks(test, "10", "1.8");
}
{
  const test = setup({ wire_diameter: confirmed(2),
    mean_diameter: formula(18, ["outer_diameter", "inner_diameter"]),
    outer_diameter: formula(20, ["inner_diameter", "wire_diameter"]),
    inner_diameter: drawing(16), free_length: confirmed(36) });
  test.edit("wire_diameter", 3);
  assert.equal(test.rows.outer_diameter.input.value, "22");
  assert.equal(test.rows.mean_diameter.input.value, "19");
  assertChecks(test, "6.3333", "1.8947");
}
{
  const test = setup({ wire_diameter: formula(2, ["outer_diameter", "inner_diameter"]),
    mean_diameter: formula(18, ["outer_diameter", "inner_diameter"]),
    outer_diameter: drawing(20), inner_diameter: drawing(16), free_length: confirmed(36) });
  test.edit("outer_diameter", 22);
  assert.equal(test.rows.wire_diameter.input.value, "3");
  assert.equal(test.rows.mean_diameter.input.value, "19");
  assertChecks(test, "6.3333", "1.8947");
}
{
  const test = setup({ wire_diameter: confirmed(2), mean_diameter: drawing(18),
    outer_diameter: formula(20, ["mean_diameter", "wire_diameter"]),
    inner_diameter: formula(16, ["mean_diameter", "wire_diameter"]), free_length: confirmed(36) });
  test.edit("mean_diameter", 24);
  assert.equal(test.rows.outer_diameter.input.value, "26");
  assert.equal(test.rows.inner_diameter.input.value, "22");
  assertChecks(test, "12", "1.5");
}
{
  const test = setup();
  test.edit("outer_diameter", 22.12346);
  assert.equal(test.rows.mean_diameter.input.value, "20.1235");
}
for (const middle of [drawing(18), confirmed(18),
  formula(18, ["outer_diameter", "wire_diameter"], { source: ["formula_calculation", "human_confirmed"], need_human_review: false }),
  formula(18, ["outer_diameter", "wire_diameter"], { source: ["formula_calculation", "human_edited"] }),
  formula(18, ["outer_diameter", "wire_diameter"], { source: ["formula_calculation", "manual"] }),
  formula(18, ["outer_diameter", "wire_diameter"], { source: ["formula_calculation", "manual_input"] }),
]) {
  const parameters = baseline();
  parameters.mean_diameter = middle;
  const test = setup(parameters);
  const previous = structuredClone(middle);
  test.edit("outer_diameter", 22);
  assertChecks(test, "9", "2");
  assert.equal(test.rows.mean_diameter.input.value, "18");
  assert.equal(middle.need_human_review, previous.need_human_review);
  assert.deepEqual(middle.source, previous.source);
}
for (const field of ["wire_diameter", "outer_diameter"]) {
  for (const invalid of [null, "", " ", "abc", 0, -2, NaN, Infinity]) {
    const test = setup();
    test.edit(field, invalid);
    assertChecks(test, "--", "--");
    assert.equal(test.review.spring_parameters.mean_diameter.value, 18, "Retain the recorded value for review");
    assert.equal(test.review.spring_parameters.mean_diameter.derived_value_stale, true);
    test.edit(field, field === "wire_diameter" ? 2 : 20);
    assertChecks(test, "9", "2");
    assert.equal(test.review.spring_parameters.mean_diameter.derived_value_stale, false);
  }
}
{
  const test = setup();
  test.edit("free_length", "");
  assertChecks(test, "9", "--");
  test.edit("free_length", 40);
  assertChecks(test, "9", "2.2222");
}
{
  const test = setup();
  test.review.spring_parameters.mean_diameter.derived_value_stale = true;
  test.edit("mean_diameter", 20);
  assertChecks(test, "10", "1.8");
  assert.equal(test.review.spring_parameters.mean_diameter.derived_value_stale, undefined);
}
{
  const test = setup({ wire_diameter: confirmed(2),
    mean_diameter: formula(18, ["outer_diameter", "wire_diameter"]),
    outer_diameter: formula(20, ["mean_diameter", "wire_diameter"]),
    inner_diameter: formula(16, ["outer_diameter", "wire_diameter"]), free_length: confirmed(36) });
  test.edit("wire_diameter", 3);
  assertChecks(test, "--", "--");
  for (const field of ["mean_diameter", "outer_diameter", "inner_diameter"]) {
    assert.equal(test.review.spring_parameters[field].derived_value_stale, true);
    assert.equal(test.review.spring_parameters[field].need_human_review, true);
  }
}
{
  const test = setup({ wire_diameter: drawing(1e-308), mean_diameter: drawing(1e308), free_length: drawing(36) });
  assertChecks(test, "--", "0");
}
assert.doesNotMatch(source, /function designCheckInputOverrides\(/);
console.log("compression design check UI tests passed: current data, relations, dependencies, protected values and invalid inputs");
