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
  parameterConfirmationInvalidReason(_field, item) {
    if (item?.value == null || item.value === "") return "请先填写参数值";
    return Number.isFinite(Number(item.value)) ? "" : "请输入有效数字";
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
assert.equal(control.label, "确认修改");
assert.equal(control.disabled, false);

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
assert.equal(control.label, "确认修改", "几何风险在生图边界校验，不阻止人工确认");
assert.equal(control.disabled, false);

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
assert.equal(control.label, "确认");
assert.equal(control.disabled, false);

context.state.lastJob = { job_id: "job-1" };
context.state.pendingReviewAuditEvents = [{ target_field: "wire_diameter" }];
context.state.reviewPersistenceInFlightEvents = [];
context.state.reviewPersistenceFailedFields = {};
control = context.confirmationControlState(confirmed, { field: "wire_diameter", review: {} });
assert.equal(control.label, "保存中");
context.state.reviewPersistenceFailedFields.wire_diameter = "网络断开";
control = context.confirmationControlState(confirmed, { field: "wire_diameter", review: {} });
assert.equal(control.label, "保存失败·重试保存");
context.state.pendingReviewAuditEvents = [];
control = context.confirmationControlState(confirmed, { field: "wire_diameter", review: {} });
assert.equal(control.label, "已确认");

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
  state: {
    review: { manual_confirmations: {}, spring_parameters: {}, standardization_results: [] },
    reviewEditSerial: 0,
    reviewDraftFields: new Set(),
  },
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
editable.last_applied_suggestion_id = "old-suggestion";
editable.last_applied_suggestion = { rule_id: "OLD" };
editable.value = 3.2;
assert.equal(lifecycle.applyEditedConfirmationState(editable, "wire_diameter"), "modified");
assert.equal(editable.need_human_review, true);
assert.equal(editable.source.includes("human_edited"), true);
assert.equal(editable.last_applied_suggestion_id, undefined);
assert.equal(editable.last_applied_suggestion, undefined);
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

const solid = {
  value: 32.025,
  need_human_review: false,
  source: ["formula_calculation", "human_confirmed"],
  source_fields: ["wire_diameter", "total_coils", "end_grinding"],
};
lifecycle.state.review.spring_parameters.solid_height = solid;
lifecycle.state.review.spring_parameters.wire_diameter = { value: 3.05, need_human_review: false };
lifecycle.markDependentFormulaParametersPending("wire_diameter");
assert.equal(solid.value, 32.025);
assert.equal(solid.need_human_review, false);
assert.equal(solid.formula_recommendation_stale, true);

assert.match(appSource, /window\.addEventListener\("beforeunload"/);
assert.match(appSource, /event_type: eventType/);
assert.match(appSource, /modified_value_confirmed/);
assert.match(appSource, /recognized_value_confirmed/);
assert.doesNotMatch(appSource, /function toggleParamConfirmation/);
assert.doesNotMatch(appSource, /confirmationActionLabel/);
assert.match(appSource, /control\.disabled \? " disabled"/);

console.log("parameter confirmation state UI test passed");
