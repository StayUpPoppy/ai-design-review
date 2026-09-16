import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");

function extract(start, end) {
  const first = appSource.indexOf(start);
  const last = appSource.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `Cannot extract ${start}`);
  return appSource.slice(first, last);
}

const context = {
  TextEncoder,
  structuredClone,
  clearTimeout,
  persistenceOrder: [],
  persistedSuggestionValue: null,
  state: {
    review: null,
    reviewEditSerial: 4,
    lastJob: { job_id: "review-1", review_revision: 7 },
    pendingReviewAuditEvents: [],
    reviewPersistenceInFlightEvents: [],
    reviewPersistenceFailedFields: {},
  },
  escapeHtml: (value) => String(value ?? ""),
  targetFieldLabel: (field) => ({ solid_height: "压并高度", free_length: "自由长度" }[field] || field),
  formatCompactNumber: (value) => String(value ?? ""),
  formatParameterDisplayValue: (field, value, unit = "") => value == null ? "未填写" : `${value}${unit || ""}`,
  lastStandardizationApplyHistory: () => null,
  parseLoadPointTarget: () => null,
  parameterPersistenceState: () => null,
  bulkConfirmationFollowupReport: () => null,
  getFieldMeta: () => ({ unit: "mm" }),
  blankParam: (unit) => ({ value: null, unit, source: [], need_human_review: true }),
  sourceValues: (value) => Array.isArray(value) ? value : value ? [value] : [],
  confirmParam(param) {
    param.need_human_review = false;
    param.source = Array.from(new Set(["human_confirmed", ...context.sourceValues(param.source)]));
  },
  syncBubbleValue() {},
  parameterAuditState: (param) => ({ value: param?.value ?? null, need_human_review: Boolean(param?.need_human_review) }),
  loadPointAuditState: (point) => structuredClone(point),
  queueReviewAuditEvent() {
    context.persistenceOrder.push("audit");
  },
  refreshReviewSurfaces() {
    context.persistenceOrder.push("render");
  },
  updateLatestReviewMessage() {},
  async flushReviewPersistence() {
    context.persistenceOrder.push("save");
    context.persistedSuggestionValue = context.state.review.spring_parameters.solid_height.value;
    return true;
  },
  scheduleParameterReasonablenessRefresh() {
    context.persistenceOrder.push("reasonableness");
  },
  refreshReasonablenessSuggestionControls() {},
};
vm.createContext(context);
vm.runInContext(extract("function renderParameterReasonablenessHtml", "function reasonablenessSeverityLabel"), context);
vm.runInContext(extract("function findReasonablenessSuggestion", "function animateStandardizationChatReply"), context);

function formulaSuggestion(overrides = {}) {
  const item = {
    suggestion_id: "suggestion-solid",
    source: "formula",
    target_field: "solid_height",
    current_value: 35,
    current_tolerance_upper: null,
    current_tolerance_lower: null,
    suggested_value: 32.025,
    suggested_tolerance_upper: null,
    suggested_tolerance_lower: null,
    unit: "mm",
    application_mode: "value",
    rule_id: "FORMULA-SOLID-HEIGHT",
    basis: "Hb=(n1+1.5)×dmax",
    source_fields: ["total_coils", "wire_diameter", "end_grinding"],
    based_on_revision: 7,
    status: "available",
    standardization_result_index: null,
    _client_edit_serial: 4,
    ...overrides,
  };
  item.dependency_snapshot = context.reasonablenessDependencySnapshot(
    context.state.review.spring_parameters,
    item.source_fields,
  );
  item.dependency_token = context.reasonablenessDependencyToken(item.dependency_snapshot);
  return item;
}

context.state.review = {
  spring_parameters: {
    solid_height: { value: 35, unit: "mm", source: ["human_confirmed"], need_human_review: false },
    free_length: { value: 50, unit: "mm", source: ["human_confirmed"], need_human_review: false },
    total_coils: { value: 9, unit: "turns", need_human_review: false },
    wire_diameter: { value: 3, tolerance_upper: 0.05, tolerance_lower: -0.05, need_human_review: false },
    end_grinding: { value: "两端不磨削", need_human_review: false },
  },
  standardization_results: [],
  standardization_apply_history: [],
  manual_confirmations: {},
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [], suggestions: [] },
};

const paritySnapshot = {
  active_coils: { value: 4, tolerance_upper: null, tolerance_lower: null },
  support_coils: null,
  total_coils: { value: 9, tolerance_upper: 0.25, tolerance_lower: -0.25 },
};
assert.equal(context.reasonablenessDependencyToken(paritySnapshot), "fnv1a32:26b145c2");

const solid = formulaSuggestion();
context.state.review.parameter_reasonableness.suggestions = [solid];
const html = context.renderParameterReasonablenessHtml(context.state.review);
assert.match(html, /参数合理性与建议/);
assert.match(html, /35mm/);
assert.match(html, /32.025mm/);
assert.match(html, /应用建议/);
assert.match(html, /Hb=\(n1\+1\.5\)×dmax/);
assert.doesNotMatch(html, /FORMULA-SOLID-HEIGHT/);
assert.doesNotMatch(html, /依赖：/);

const matching = formulaSuggestion({
  suggestion_id: "suggestion-matching-solid",
  suggested_value: 35,
  status: "informational",
});
context.state.review.parameter_reasonableness.suggestions = [matching];
const matchingHtml = context.renderParameterReasonablenessHtml(context.state.review);
assert.match(matchingHtml, /当前没有需要处理的参数合理性问题/);
assert.doesNotMatch(matchingHtml, /应用全部可用建议/);
assert.doesNotMatch(matchingHtml, /FORMULA-SOLID-HEIGHT/);

const legacyMatching = formulaSuggestion({
  suggestion_id: "legacy-matching-solid",
  suggested_value: 35,
  status: "available",
});
context.state.review.parameter_reasonableness.suggestions = [legacyMatching];
const legacyMatchingHtml = context.renderParameterReasonablenessHtml(context.state.review);
assert.match(legacyMatchingHtml, /当前没有需要处理的参数合理性问题/);
assert.doesNotMatch(legacyMatchingHtml, /应用全部可用建议/);
assert.doesNotMatch(legacyMatchingHtml, /legacy-matching-solid/);
assert.equal(context.reasonablenessSuggestionControlState(legacyMatching, context.state.review).label, "无需修改");

context.state.review.parameter_reasonableness.suggestions = [solid];

const applied = context.applyReasonablenessSuggestions([solid]);
assert.equal(applied.count, 1);
assert.equal(context.state.review.spring_parameters.solid_height.value, 32.025);
assert.equal(context.state.review.spring_parameters.solid_height.need_human_review, false);
assert.equal(context.state.review.spring_parameters.solid_height.last_applied_suggestion_id, "suggestion-solid");
assert.equal(solid.status, "applied");
assert.equal(context.state.review.standardization_apply_history.length, 1);
await context.recordReasonablenessSuggestionApplications(applied, "message-1");
assert.equal(context.persistedSuggestionValue, 32.025, "the first application must reach persistence immediately");
assert.ok(
  context.persistenceOrder.indexOf("save") < context.persistenceOrder.indexOf("reasonableness"),
  "reasonableness must refresh only after the applied value has been saved",
);

const reappliedMarker = formulaSuggestion({
  current_value: 35,
  status: "available",
});
context.state.review.spring_parameters.solid_height.value = 35;
// Simulate a non-input edit path that accidentally retained audit provenance.
context.state.review.spring_parameters.solid_height.last_applied_suggestion_id = reappliedMarker.suggestion_id;
context.state.review.parameter_reasonableness.suggestions = [reappliedMarker];
assert.equal(context.reasonablenessSuggestionControlState(reappliedMarker, context.state.review).label, "应用建议");
assert.match(context.renderParameterReasonablenessHtml(context.state.review), /应用建议/);

const matchingResponseBeforeEdit = formulaSuggestion({
  current_value: 32.025,
  suggested_value: 32.025,
  status: "informational",
});
context.state.review.spring_parameters.solid_height.last_applied_suggestion_id = null;
context.state.review.parameter_reasonableness.suggestions = [matchingResponseBeforeEdit];
assert.equal(context.reasonablenessSuggestionControlState(matchingResponseBeforeEdit, context.state.review).label, "应用建议");
assert.match(
  context.renderParameterReasonablenessHtml(context.state.review),
  /35mm[\s\S]*32\.025mm[\s\S]*应用建议/,
  "a previously matching formula must reappear immediately after the live target changes",
);

const confirmedButDifferent = formulaSuggestion({ current_value: 35, status: "available" });
context.state.review.spring_parameters.solid_height.need_human_review = false;
context.state.review.spring_parameters.solid_height.last_applied_suggestion_id = null;
context.state.review.parameter_reasonableness.suggestions = [confirmedButDifferent];
assert.match(
  context.renderParameterReasonablenessHtml(context.state.review),
  /应用建议/,
  "confirming the current value must not hide a still-different recommendation",
);

const staleStandardization = formulaSuggestion({
  suggestion_id: "stale-standardization",
  source: "standardization",
  supporting_sources: ["standardization"],
  status: "stale",
});
context.state.review.parameter_reasonableness.suggestions = [staleStandardization];
assert.match(context.renderParameterReasonablenessHtml(context.state.review), /更新标准化建议 · 1/);
assert.equal(context.reasonablenessSuggestionControlState(staleStandardization, context.state.review).label, "已过期");

context.state.review.spring_parameters.solid_height.value = 35;
context.state.review.spring_parameters.solid_height.last_applied_suggestion_id = null;
context.state.review.spring_parameters.total_coils.value = 10;
solid.status = "available";
assert.equal(context.reasonablenessSuggestionIsFresh(solid, context.state.review), false);
assert.equal(context.reasonablenessSuggestionControlState(solid, context.state.review).label, "已过期");

context.state.review.spring_parameters.total_coils.value = 9;
solid.status = "available";
solid._client_edit_serial = context.state.reviewEditSerial;
solid.based_on_revision = 6;
assert.equal(context.reasonablenessSuggestionControlState(solid, context.state.review).label, "已过期");
solid.based_on_revision = 7;
solid.current_value = 34;
assert.equal(context.reasonablenessSuggestionControlState(solid, context.state.review).label, "已过期");
solid.current_value = 35;

context.state.review.reviewEditSerial = 4;
context.state.review.spring_parameters.total_coils.value = 9;
const optionA = formulaSuggestion({ suggestion_id: "option-a", target_field: "free_length", current_value: 50, suggested_value: 48, status: "conflict" });
const optionB = formulaSuggestion({ suggestion_id: "option-b", target_field: "free_length", current_value: 50, suggested_value: 52, status: "conflict" });
context.state.review.parameter_reasonableness.suggestions = [optionA, optionB];
const batch = context.reasonablenessSuggestionBatchPlan(context.state.review);
assert.equal(batch.items.length, 0);
assert.equal(batch.conflicts.length, 1);
context.state.review.spring_parameters.free_length.last_applied_suggestion_id = optionA.suggestion_id;
assert.equal(
  context.reasonablenessSuggestionControlState(optionB, context.state.review).label,
  "选择此建议",
  "an old application marker must not lock competing options when its value is no longer current",
);

console.log("parameter suggestion unified UI tests passed");
