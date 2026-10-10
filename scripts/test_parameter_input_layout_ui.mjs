import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");
const declarations = [...source.matchAll(/^function ([A-Za-z_$][\w$]*)\([^]*?^\}/gm)];
const context = {
  state: { review: { drawing_summary: { spring_type: "compression_spring" } } },
  FIELD_LABELS: {},
  isCompressionSpringReview: (review) => review?.drawing_summary?.spring_type === "compression_spring",
  pendingDefaultCandidateNotice: () => "", sourceValues: () => [],
  reasonablenessSeverityForField: () => "", accuracyGradeStatusLabel: () => "",
  materialSelectionNotesHtml: () => "", surfaceRoughnessCandidatesHtml: () => "",
  parameterUnitLabel: (field, label) => ({ text: label }), parameterUnitLabelHtml: (label) => label.text,
  parameterValueControlHtml: () => '<input data-role="value">',
  confirmationButtonHtml: () => '<button data-role="confirm">确认</button>',
  escapeHtml: (value) => String(value ?? "").replaceAll('"', "&quot;"),
};
vm.createContext(context);
vm.runInContext(declarations.filter((item) => ["parameterRowHtml", "formatTolerance"].includes(item[1])).map((item) => item[0]).join("\n"), context);

for (const field of ["material", "standard_no", "accuracy_grade"]) {
  for (const need_human_review of [true, false]) {
    const param = { value: "测试值", need_human_review, raw_value: "原图值", tolerance_upper: null, tolerance_lower: null };
    const before = JSON.stringify(param);
    const html = context.parameterRowHtml(field, param, { label: field });
    assert.match(html, /class="data-row parameter-wide-input"/);
    assert.match(html, /data-role="tolerance"/, "Hidden tolerance control stays in the DOM for existing bindings");
    assert.equal(JSON.stringify(param), before, "Layout never changes saved data or confirmation");
  }
  for (const tolerance of [
    { tolerance_upper: .1, tolerance_lower: -.1 },
    { tolerance_upper: 0, tolerance_lower: 0 },
    { tolerance_lower: -.1 },
    { tolerance_input_draft: "尚未完成的公差" },
  ]) {
    const param = { value: "测试值", need_human_review: false, ...tolerance };
    const before = JSON.stringify(param);
    const html = context.parameterRowHtml(field, param, { label: field });
    assert.doesNotMatch(html, /parameter-wide-input/, "Existing tolerance/draft remains editable, including zero");
    assert.equal(JSON.stringify(param), before);
  }
}
for (const field of ["wire_diameter", "handedness", "end_type", "end_grinding", "diameter_accuracy_grade", "controlled_diameter_field", "unknown"]) {
  assert.doesNotMatch(context.parameterRowHtml(field, { value: 1 }, { label: field }), /parameter-wide-input/);
}
context.state.review.drawing_summary.spring_type = "extension_spring";
for (const field of ["material", "standard_no", "accuracy_grade"]) {
  assert.doesNotMatch(context.parameterRowHtml(field, { value: "测试值" }, { label: field }), /parameter-wide-input/);
}
assert.match(styles, /\.data-row\.parameter-wide-input \.data-primary\s*\{\s*grid-column: 2 \/ 4;/);
assert.match(styles, /\.data-row\.parameter-wide-input \.data-secondary\s*\{\s*display: none;/);
assert.match(styles, /"primary primary action"/);
assert.match(styles, /\.data-row\.parameter-wide-input \.data-primary\s*\{\s*grid-column: 1 \/ 3;/);
console.log("PASS: three compression inputs widen without changing data; legacy tolerances/drafts and other fields/types keep their layout");
