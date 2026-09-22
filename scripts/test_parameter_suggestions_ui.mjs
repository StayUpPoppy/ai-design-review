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
  targetFieldLabel: (field) => ({
    solid_height: "压并高度",
    free_length: "自由长度",
    active_coils: "有效圈数",
    total_coils: "总圈数",
    spring_rate: "刚度",
    outer_diameter: "外径",
    perpendicularity: "垂直度",
  }[field] || field),
  formatCompactNumber: (value) => String(value ?? ""),
  formatParameterDisplayValue: (field, value, unit = "") => value == null ? "未填写" : `${value}${unit || ""}`,
  lastStandardizationApplyHistory: () => null,
  parseLoadPointTarget(target) {
    const match = String(target || "").match(/^load_points\.([^.]+)\.(force|height)$/);
    return match ? { label: match[1], field: match[2] } : null;
  },
  normalizeReview: (review) => structuredClone(review),
  dependencyFieldsIncludeField(sourceFields, field) {
    return (sourceFields || []).some((sourceField) => String(sourceField) === String(field));
  },
  standardizationResultDependsOnField(result, field) {
    const sourceFields = result?.metadata?.source_fields || result?.source_fields;
    return !Array.isArray(sourceFields) || !sourceFields.length
      || context.dependencyFieldsIncludeField(sourceFields, field);
  },
  parameterPersistenceState: () => null,
  bulkConfirmationFollowupReport: () => null,
  getFieldMeta: () => ({ unit: "mm" }),
  blankParam: (unit) => ({ value: null, unit, source: [], need_human_review: true }),
  sourceValues: (value) => Array.isArray(value) ? value : value ? [value] : [],
  confirmParam(param) {
    param.need_human_review = false;
    param.source = Array.from(new Set(["human_confirmed", ...context.sourceValues(param.source)]));
  },
  confirmStandardSelection() {
    context.state.review.standard_selection.human_confirmed = true;
    context.state.review.standard_selection.need_human_review = false;
    context.state.review.manual_confirmations.standard_selection = { confirmed: true, value: "GB/T 1239.2-2009" };
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
vm.runInContext(extract("function undoLastStandardizationApplication", "function standardizationChatConstraints"), context);

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
  standardization_result_index: 0,
  standardization_result_indexes: [0],
});
context.state.review.standardization_results = [{
  target_field: "solid_height",
  rule_id: "GBT1239.2-SOLID",
  basis: "表3-12：压并高度参考值。",
  status: "stale",
  metadata: {
    stale_by_fields: ["active_coils"],
    stale_by_field: "active_coils",
    stale_reason: "dependency_value_changed",
    stale_dependency_changes: [{ field: "active_coils", before_value: 12, after_value: 8, unit: "turns" }],
  },
}];
context.state.review.parameter_reasonableness.suggestions = [staleStandardization];
const staleHtml = context.renderParameterReasonablenessHtml(context.state.review);
assert.match(staleHtml, /1 条标准化建议因相关参数变化已过期/);
assert.match(staleHtml, /按当前参数重新计算（1项）/);
assert.match(staleHtml, /<details class="stale-standardization-details">/);
assert.match(staleHtml, /查看过期详情/);
assert.match(staleHtml, /有效圈数由 12turns 修改为 8turns/);
assert.match(staleHtml, /旧建议/);
assert.match(staleHtml, /仅供对照，不可应用/);
assert.match(staleHtml, /GBT1239\.2-SOLID · 表3-12：压并高度参考值/);
assert.match(staleHtml, /data-role="focus-reasonableness-field" data-field="solid_height"/);
assert.doesNotMatch(staleHtml, /data-suggestion-id="stale-standardization"/);
assert.equal(context.reasonablenessSuggestionControlState(staleStandardization, context.state.review).label, "已过期");

context.state.review.standardization_results[0].metadata = { stale_by_field: "active_coils" };
const historicalStaleHtml = context.renderParameterReasonablenessHtml(context.state.review);
assert.match(historicalStaleHtml, /有效圈数发生变化，需要按当前参数重新计算/);
context.state.review.standardization_results[0].metadata = {};
const unknownStaleHtml = context.renderParameterReasonablenessHtml(context.state.review);
assert.match(unknownStaleHtml, /相关依赖参数已变化，需要按当前参数重新计算/);

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
assert.equal(
  context.reasonablenessSuggestionControlState(solid, context.state.review).label,
  "应用建议",
  "an unrelated revision change must not invalidate identical target/dependency values",
);
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

context.state.review = {
  spring_parameters: {
    outer_diameter: { value: 8.25, tolerance_upper: 0.2, tolerance_lower: -0.2, unit: "mm", need_human_review: false },
    free_length: { value: 30.25, tolerance_upper: 0.5, tolerance_lower: -0.5, unit: "mm", need_human_review: false },
    perpendicularity: { value: 0.605, tolerance_upper: 0.605, tolerance_lower: 0, unit: "mm", need_human_review: false },
    spring_rate: { value: 1.8331, tolerance_upper: 0.0917, tolerance_lower: -0.0917, unit: "N/mm", need_human_review: false },
    active_coils: { value: 8, unit: "turns", need_human_review: false },
    accuracy_grade: { value: "2级", need_human_review: false },
    load_points: [
      { label: "F1", height: 20, force: 16, load_tolerance_upper: 0.8, load_tolerance_lower: -0.8 },
      { label: "F2", height: 15, force: 35, load_tolerance_upper: 1.75, load_tolerance_lower: -1.75 },
    ],
  },
  standardization_results: [],
  standardization_apply_history: [],
  manual_confirmations: {},
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [], suggestions: [] },
};
function toleranceSuggestion(overrides) {
  const item = {
    source: "standardization",
    status: "available",
    application_mode: "tolerance",
    current_tolerance_upper: null,
    current_tolerance_lower: null,
    suggested_tolerance_upper: null,
    suggested_tolerance_lower: null,
    ...overrides,
  };
  item.dependency_snapshot = context.reasonablenessDependencySnapshot(context.state.review.spring_parameters, item.source_fields);
  item.dependency_token = context.reasonablenessDependencyToken(item.dependency_snapshot);
  return item;
}
const toleranceSuggestions = [
  toleranceSuggestion({ suggestion_id: "tol-outer", target_field: "outer_diameter", current_value: 8.25, suggested_value: 8.25, current_tolerance_upper: 0.2, current_tolerance_lower: -0.2, suggested_tolerance_upper: 0.3, suggested_tolerance_lower: -0.3, source_fields: ["outer_diameter"], rule_id: "DIA" }),
  toleranceSuggestion({ suggestion_id: "tol-free", target_field: "free_length", current_value: 30.25, suggested_value: 30.25, current_tolerance_upper: 0.5, current_tolerance_lower: -0.5, suggested_tolerance_upper: 0.9075, suggested_tolerance_lower: -0.9075, source_fields: ["free_length", "outer_diameter"], rule_id: "FREE" }),
  toleranceSuggestion({ suggestion_id: "tol-perp", target_field: "perpendicularity", current_value: 0.605, suggested_value: 1.5125, current_tolerance_upper: 0.605, current_tolerance_lower: 0, suggested_tolerance_upper: 1.5125, suggested_tolerance_lower: 0, source_fields: ["free_length", "outer_diameter"], rule_id: "PERP" }),
  toleranceSuggestion({ suggestion_id: "tol-f1", target_field: "load_points.F1.force", current_value: 16, suggested_value: 16, current_tolerance_upper: 0.8, current_tolerance_lower: -0.8, suggested_tolerance_upper: 1.6, suggested_tolerance_lower: -1.6, source_fields: ["active_coils", "accuracy_grade", "load_points"], rule_id: "LOAD-F1" }),
  toleranceSuggestion({ suggestion_id: "tol-f2", target_field: "load_points.F2.force", current_value: 35, suggested_value: 35, current_tolerance_upper: 1.75, current_tolerance_lower: -1.75, suggested_tolerance_upper: 3.5, suggested_tolerance_lower: -3.5, source_fields: ["active_coils", "accuracy_grade", "load_points"], rule_id: "LOAD-F2" }),
  toleranceSuggestion({ suggestion_id: "tol-rate", target_field: "spring_rate", current_value: 1.8331, suggested_value: 1.8331, current_tolerance_upper: 0.0917, current_tolerance_lower: -0.0917, suggested_tolerance_upper: 0.1833, suggested_tolerance_lower: -0.1833, source_fields: ["active_coils", "spring_rate"], rule_id: "RATE" }),
];
toleranceSuggestions.forEach((item, index) => {
  item.standardization_result_index = index;
  item.standardization_result_indexes = [index];
  context.state.review.standardization_results.push({
    target_field: item.target_field,
    rule_id: item.rule_id,
    status: "suggested",
    need_human_review: true,
    metadata: { source_fields: item.source_fields },
  });
});
context.state.review.parameter_reasonableness.suggestions = toleranceSuggestions;
const tolerancePlan = context.reasonablenessSuggestionBatchPlan(context.state.review);
assert.equal(tolerancePlan.items.length, 6, "all six tolerance-only suggestions must be counted as batch-applicable");
assert.equal(tolerancePlan.dependency_blocks.length, 0);
const toleranceLayers = context.reasonablenessSuggestionBatchLayers(tolerancePlan.items);
assert.equal(toleranceLayers.layers.length, 1, "tolerance-only changes must not create upstream value dependencies");
assert.equal(toleranceLayers.layers[0].length, 6);
assert.equal(toleranceLayers.cycles.length, 0, "F1 and F2 must not form a cycle through aggregate load_points");
const toleranceInvalidationReview = {
  standardization_results: [{
    target_field: "free_length",
    status: "suggested",
    need_human_review: true,
    metadata: { source_fields: ["outer_diameter"] },
  }],
};
context.markStandardizationResultsAfterSuggestion(toleranceInvalidationReview, [{
  ...toleranceSuggestions[0],
  standardization_result_index: null,
  standardization_result_indexes: [],
}]);
assert.equal(
  toleranceInvalidationReview.standardization_results[0].status,
  "suggested",
  "changing only outer-diameter tolerance must not stale a downstream value-dependent standard result",
);
context.apiFetch = async () => ({
  ok: true,
  async json() {
    return { parameter_reasonableness: { status: "pass", summary: "通过", issues: [], suggestions: [] } };
  },
});
const tolerancePreflight = await context.preflightReasonablenessSuggestionBatch(tolerancePlan);
assert.equal(tolerancePreflight.ok, true);
assert.equal(tolerancePreflight.items.length, 6);
const toleranceApplied = context.applyReasonablenessSuggestions(tolerancePreflight.items, { mode: "reasonableness_batch", prevalidated: true });
assert.equal(toleranceApplied.count, 6);
assert.equal(context.state.review.standardization_results.every((item) => item.status === "human_confirmed"), true);
assert.equal(context.state.review.standardization_results.some((item) => item.status === "stale"), false);

context.state.review = {
  spring_parameters: {
    alpha: { value: 1, need_human_review: false },
    beta: { value: 2, need_human_review: false },
  },
  standardization_results: [],
  standardization_apply_history: [],
  manual_confirmations: {},
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [], suggestions: [] },
};
const cycleA = chainSuggestion({ suggestion_id: "cycle-a", target_field: "alpha", current_value: 1, suggested_value: 3, source_fields: ["beta"] });
const cycleB = chainSuggestion({ suggestion_id: "cycle-b", target_field: "beta", current_value: 2, suggested_value: 4, source_fields: ["alpha"] });
context.state.review.parameter_reasonableness.suggestions = [cycleA, cycleB];
const cyclePlan = context.reasonablenessSuggestionBatchPlan(context.state.review);
assert.equal(cyclePlan.items.length, 0, "true value cycles must not be included in the one-click count");
assert.equal(cyclePlan.dependency_blocks.length, 2);

context.state.review = {
  spring_parameters: {
    active_coils: { value: 12, unit: "turns", need_human_review: false },
    total_coils: { value: 10, unit: "turns", need_human_review: false },
    end_type: { value: "两端并紧", need_human_review: false },
    support_coils: { value: 1, unit: "turns", need_human_review: false },
    wire_diameter: { value: 0.9, unit: "mm", need_human_review: false },
    mean_diameter: { value: 7.35, unit: "mm", need_human_review: false },
    spring_rate: { value: 1.8331, unit: "N/mm", need_human_review: false },
  },
  standardization_results: [],
  standardization_apply_history: [],
  manual_confirmations: {},
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [], suggestions: [] },
};
function chainSuggestion(overrides) {
  const item = {
    current_tolerance_upper: null,
    current_tolerance_lower: null,
    suggested_tolerance_upper: null,
    suggested_tolerance_lower: null,
    application_mode: "value",
    source: "formula",
    status: "available",
    ...overrides,
  };
  item.dependency_snapshot = context.reasonablenessDependencySnapshot(context.state.review.spring_parameters, item.source_fields);
  item.dependency_token = context.reasonablenessDependencyToken(item.dependency_snapshot);
  return item;
}
const activeCoilsSuggestion = chainSuggestion({
  suggestion_id: "active-12-to-8",
  target_field: "active_coils",
  current_value: 12,
  suggested_value: 8,
  rule_id: "COMPANY-ACTIVE-COILS",
  source_fields: ["total_coils", "end_type", "support_coils"],
});
const staleRateSuggestion = chainSuggestion({
  suggestion_id: "rate-based-on-12",
  target_field: "spring_rate",
  current_value: 1.8331,
  suggested_value: 1.2221,
  rule_id: "FORMULA-SPRING-RATE",
  source_fields: ["wire_diameter", "mean_diameter", "active_coils"],
});
const metadataReview = structuredClone(context.state.review);
metadataReview.standardization_results = [{
  target_field: "spring_rate",
  rule_id: "RATE-TOLERANCE",
  status: "suggested",
  need_human_review: true,
  metadata: { source_fields: ["active_coils", "spring_rate"] },
}];
context.markStandardizationResultsAfterSuggestion(metadataReview, [activeCoilsSuggestion]);
assert.equal(metadataReview.standardization_results[0].status, "stale");
assert.deepEqual(JSON.parse(JSON.stringify(metadataReview.standardization_results[0].metadata.stale_by_fields)), ["active_coils"]);
assert.equal(metadataReview.standardization_results[0].metadata.stale_reason, "dependency_value_changed");
assert.deepEqual(
  JSON.parse(JSON.stringify(metadataReview.standardization_results[0].metadata.stale_dependency_changes[0])),
  { field: "active_coils", before_value: 12, after_value: 8, unit: "" },
);
context.state.review.parameter_reasonableness.suggestions = [activeCoilsSuggestion, staleRateSuggestion];
context.apiFetch = async (_url, options) => {
  const workingReview = JSON.parse(options.body).review;
  assert.equal(workingReview.spring_parameters.active_coils.value, 8);
  const suggestions = [
    {
      ...activeCoilsSuggestion,
      suggestion_id: "active-now-correct",
      current_value: 8,
      suggested_value: 8,
      status: "informational",
    },
    {
      ...staleRateSuggestion,
      suggestion_id: "rate-now-correct",
      current_value: 1.8331,
      suggested_value: 1.8331,
      status: "informational",
      dependency_snapshot: context.reasonablenessDependencySnapshot(workingReview.spring_parameters, staleRateSuggestion.source_fields),
      dependency_token: context.reasonablenessDependencyToken(context.reasonablenessDependencySnapshot(workingReview.spring_parameters, staleRateSuggestion.source_fields)),
    },
  ];
  return { ok: true, async json() { return { parameter_reasonableness: { status: "pass", summary: "通过", issues: [], suggestions } }; } };
};
const dependencyPlan = context.reasonablenessSuggestionBatchPlan(context.state.review);
assert.deepEqual(JSON.parse(JSON.stringify(dependencyPlan.items.map((item) => item.target_field))), ["active_coils", "spring_rate"]);
const dependencyPreflight = await context.preflightReasonablenessSuggestionBatch(dependencyPlan);
assert.equal(dependencyPreflight.ok, true);
assert.deepEqual(JSON.parse(JSON.stringify(dependencyPreflight.items.map((item) => item.target_field))), ["active_coils"]);
assert.deepEqual(JSON.parse(JSON.stringify(dependencyPreflight.resolved.map((item) => item.target_field))), ["spring_rate"]);
assert.equal(context.state.review.spring_parameters.active_coils.value, 12, "preflight must not mutate live parameters");
assert.equal(context.state.review.spring_parameters.spring_rate.value, 1.8331);
const dependencyApplied = context.applyReasonablenessSuggestions(dependencyPreflight.items, { mode: "reasonableness_batch", prevalidated: true });
assert.equal(dependencyApplied.count, 1);
assert.equal(context.state.review.spring_parameters.active_coils.value, 8);
assert.equal(context.state.review.spring_parameters.spring_rate.value, 1.8331, "old downstream stiffness must never be written");

context.state.review.spring_parameters.active_coils.value = 12;
delete context.state.review.spring_parameters.active_coils.last_applied_suggestion_id;
context.state.review.parameter_reasonableness.suggestions = [activeCoilsSuggestion, staleRateSuggestion];
context.state.reviewEditSerial = 20;
let releaseSlowAssessment;
context.apiFetch = async (_url, options) => {
  const workingReview = JSON.parse(options.body).review;
  return new Promise((resolve) => {
    releaseSlowAssessment = () => resolve({
      ok: true,
      async json() {
        return {
          parameter_reasonableness: {
            status: "pass",
            summary: "通过",
            issues: [],
            suggestions: [{
              ...activeCoilsSuggestion,
              current_value: workingReview.spring_parameters.active_coils.value,
              suggested_value: workingReview.spring_parameters.active_coils.value,
              status: "informational",
            }],
          },
        };
      },
    });
  });
};
const guardedPreflightPromise = context.preflightReasonablenessSuggestionBatch(
  context.reasonablenessSuggestionBatchPlan(context.state.review),
);
context.state.reviewEditSerial += 1;
releaseSlowAssessment();
const guardedPreflight = await guardedPreflightPromise;
assert.equal(guardedPreflight.ok, false);
assert.equal(context.state.review.spring_parameters.active_coils.value, 12, "a slow response must not overwrite a newer edit");
context.state.reviewEditSerial = 4;

context.state.review = {
  spring_parameters: {
    standard_no: { value: null, unit: "", source: [], need_human_review: true },
    wire_diameter: { value: 2, unit: "mm", need_human_review: false },
  },
  standard_selection: {
    selected_standard: "GB/T 1239.2-2009",
    rules_available: true,
    metadata: { conflicts: [] },
    need_human_review: true,
    human_confirmed: false,
  },
  standardization_results: [{ target_field: "standard_no", suggested_value: "GB/T 1239.2-2009", status: "need_context", need_human_review: true }],
  standardization_apply_history: [],
  manual_confirmations: {},
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [], suggestions: [] },
};
const standardSuggestion = {
  suggestion_id: "suggestion-standard",
  source: "standardization",
  target_field: "standard_no",
  current_value: null,
  current_tolerance_upper: null,
  current_tolerance_lower: null,
  suggested_value: "GB/T 1239.2-2009",
  suggested_tolerance_upper: null,
  suggested_tolerance_lower: null,
  application_mode: "value",
  rule_id: "GBT1239.2-CTX",
  source_fields: ["standard_no", "wire_diameter"],
  based_on_revision: 6,
  status: "available",
  standardization_result_index: 0,
};
standardSuggestion.dependency_snapshot = context.reasonablenessDependencySnapshot(context.state.review.spring_parameters, standardSuggestion.source_fields);
standardSuggestion.dependency_token = context.reasonablenessDependencyToken(standardSuggestion.dependency_snapshot);
context.state.review.parameter_reasonableness.suggestions = [standardSuggestion];
assert.equal(context.reasonablenessSuggestionBatchPlan(context.state.review).items.length, 1);
assert.match(context.renderParameterReasonablenessHtml(context.state.review), /系统推荐 · 图纸未标注/);
const appliedStandard = context.applyReasonablenessSuggestions(context.reasonablenessSuggestionBatchPlan(context.state.review).items, { mode: "reasonableness_batch" });
assert.equal(appliedStandard.count, 1);
assert.equal(context.state.review.spring_parameters.standard_no.value, "GB/T 1239.2-2009");
assert.equal(context.state.review.spring_parameters.standard_no.need_human_review, false);
assert.equal(context.state.review.standard_selection.human_confirmed, true);
assert.equal(context.state.review.manual_confirmations.standard_selection.confirmed, true);
assert.equal(context.state.review.standardization_results[0].status, "human_confirmed");

const revertedStandard = context.undoLastStandardizationApplication();
assert.equal(revertedStandard.applied_count, 1);
assert.equal(context.state.review.spring_parameters.standard_no.value, null);
assert.equal(context.state.review.standard_selection.human_confirmed, false);
assert.equal(context.state.review.manual_confirmations.standard_selection, undefined);

context.state.review.spring_parameters.standard_no.value = "GB/T 23934-2015";
context.state.review.spring_parameters.standard_no.source = ["human_confirmed"];
assert.equal(context.reasonablenessSuggestionBatchPlan(context.state.review).items.length, 0);
assert.equal(context.reasonablenessSuggestionControlState(standardSuggestion, context.state.review).label, "需单独核对");

console.log("parameter suggestion unified UI tests passed");
