import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const helperStart = appSource.indexOf("function confirmationItemWasEdited");
const helperEnd = appSource.indexOf("function renderDerivedParametersHtml", helperStart);
assert.notEqual(helperStart, -1, "confirmation state helpers must exist");
assert.notEqual(helperEnd, -1, "confirmation state helper block must be complete");

const context = {
  state: { review: null },
  sourceValues(source) {
    return (Array.isArray(source) ? source : [source]).filter(Boolean).map(String);
  },
  bulkParameterInvalidReason(field, item) {
    if (item?.value == null || item.value === "") return "参数值缺失";
    if (["wire_diameter", "mean_diameter", "free_length"].includes(field) && Number(item.value) <= 0) return "参数必须大于0";
    return "";
  },
  isFiniteReviewNumber(value) {
    return value != null && value !== "" && Number.isFinite(Number(value));
  },
  reasonablenessSeverityForField(review, field) {
    return review?.severities?.[field] || "";
  },
  escapeHtml(value) {
    return String(value);
  },
};
vm.createContext(context);
vm.runInContext(appSource.slice(helperStart, helperEnd), context);

const confirmed = { value: 3, need_human_review: false, source: ["human_confirmed"] };
let control = context.confirmationControlState(confirmed, { field: "wire_diameter", review: {} });
assert.deepEqual(JSON.parse(JSON.stringify(control)), {
  state: "confirmed",
  label: "已确认",
  disabled: true,
  reason: "该项已经确认；修改内容后可重新确认。",
});

control = context.confirmationControlState(
  { value: 3, need_human_review: true, source: ["drawing"] },
  { field: "wire_diameter", review: {} },
);
assert.equal(control.label, "确认");
assert.equal(control.disabled, false);

const edited = { value: 3.2, need_human_review: true, source: ["human_edited"] };
control = context.confirmationControlState(edited, {
  field: "wire_diameter",
  review: { parameter_reasonableness_stale: true },
});
assert.equal(control.label, "校验中");
assert.equal(control.disabled, true);

control = context.confirmationControlState(edited, {
  field: "wire_diameter",
  review: { parameter_reasonableness_stale: false },
});
assert.equal(control.label, "确认修改");
assert.equal(control.disabled, false);

control = context.confirmationControlState(
  { value: -1, need_human_review: true, source: ["human_edited"] },
  { field: "wire_diameter", review: {} },
);
assert.equal(control.label, "无法确认");
assert.equal(control.disabled, true);

control = context.confirmationControlState(
  { value: 3, need_human_review: true, source: ["drawing"] },
  { field: "wire_diameter", review: { severities: { wire_diameter: "warning" } } },
);
assert.equal(control.state, "warning");
assert.equal(control.disabled, false);

control = context.confirmationControlState(
  { value: 3, need_human_review: true, source: ["drawing"] },
  { field: "wire_diameter", review: { severities: { wire_diameter: "blocked" } } },
);
assert.equal(control.label, "无法确认");
assert.equal(control.disabled, true);

control = context.confirmationControlState(
  { value: 3, need_human_review: true, source: ["protocol_default"], default_source: "protocol" },
  { field: "wire_diameter", review: {} },
);
assert.equal(control.label, "确认", "default candidates remain individually confirmable");
assert.equal(control.disabled, false);

const lifecycleStart = appSource.indexOf("function confirmParam");
const lifecycleEnd = appSource.indexOf("function sourceValues", lifecycleStart);
assert.notEqual(lifecycleStart, -1, "confirmation lifecycle helpers must exist");
assert.notEqual(lifecycleEnd, -1, "confirmation lifecycle helper block must be complete");
const lifecycle = {
  state: { review: { manual_confirmations: {}, spring_parameters: {}, standardization_results: [] } },
  sourceValues: context.sourceValues,
  confirmationItemWasEdited(item) {
    return Boolean(item?.need_human_review) && context.sourceValues(item?.source).includes("human_edited");
  },
  reasonablenessSeverityForField() { return ""; },
  revokeManualConfirmations() { return false; },
  invalidateStandardizationResults() { return 0; },
  scheduleAutomaticStandardization() {},
  normalizeAccuracyGrade(value) { return String(value || ""); },
};
vm.createContext(lifecycle);
vm.runInContext(appSource.slice(lifecycleStart, lifecycleEnd), lifecycle);

const editable = { value: 3, need_human_review: false, source: ["human_confirmed"] };
lifecycle.rememberConfirmedSnapshot(editable);
editable.value = 3.2;
assert.equal(lifecycle.applyEditedConfirmationState(editable, "wire_diameter"), "modified");
assert.equal(editable.need_human_review, true);
assert.equal(editable.source.includes("human_edited"), true);
editable.value = 3;
assert.equal(lifecycle.applyEditedConfirmationState(editable, "wire_diameter"), "restored");
assert.equal(editable.need_human_review, false);
assert.equal(editable.source.includes("human_edited"), false);

editable.value = 3.4;
lifecycle.applyEditedConfirmationState(editable, "wire_diameter");
lifecycle.confirmParam(editable, "wire_diameter");
assert.equal(editable.need_human_review, false);
assert.equal(editable.confirmation_snapshot.value, 3.4);
assert.equal(lifecycle.state.review.manual_confirmations.wire_diameter.confirmed, true);

assert.match(appSource, /window\.addEventListener\("beforeunload"/);
assert.match(appSource, /event_type: eventType/);
assert.match(appSource, /modified_value_confirmed/);
assert.match(appSource, /recognized_value_confirmed/);
assert.doesNotMatch(appSource, /function toggleParamConfirmation/);
assert.doesNotMatch(appSource, /confirmationActionLabel/);
assert.match(appSource, /control\.disabled \? " disabled"/);

console.log("parameter confirmation state UI test passed");
