import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const helperStart = appSource.indexOf("function buildSafeConfirmationPlan");
const helperEnd = appSource.indexOf("function applyAvailableStandardizationSuggestions", helperStart);
assert.notEqual(helperStart, -1, "bulk confirmation helper must exist");
assert.notEqual(helperEnd, -1, "bulk confirmation helper block must be complete");

const context = {
  COMPRESSION_GENERATION_CORE_FIELDS: [
    "wire_diameter", "mean_diameter", "free_length", "total_coils", "active_coils",
    "handedness", "end_grinding", "end_coils_closed",
  ],
  TECH_LABELS: { surface: "表面处理", other: "其他要求" },
  state: {
    review: null,
    pendingReviewAuditEvents: [],
    reviewPersistenceInFlightEvents: [],
  },
  ensureLoadPointIds(review) {
    review.spring_parameters ||= {};
    review.spring_parameters.load_points ||= [];
    review.spring_parameters.load_points.forEach((item, index) => {
      item.load_point_id ||= `loadpt-test-${index + 1}`;
      item.label = String(item.label || "").trim();
    });
    return review;
  },
  normalizeLoadPointLabel(value) { return String(value || "").trim().replace(/\s+/g, " "); },
  canonicalLoadPointLabel(value) { return String(value || "").trim().replace(/\s+/g, " ").toLowerCase(); },
  loadPointField(point, index = -1) { return `load_points.${String(point?.label || index + 1).trim() || index + 1}`; },
  loadPointConfirmationKey(point, index = -1) { return `load_point_${point?.load_point_id || index}`; },
  isValidLoadPoint(point) {
    return point?.height != null && point.height !== "" && point?.force != null && point.force !== ""
      && Boolean(String(point?.label || "").trim()) && Number(point?.height) > 0 && Number.isFinite(Number(point?.force)) && Number(point?.force) >= 0;
  },
  isDuplicateLoadPointLabel(review, label, excludedId = "") {
    const canonical = String(label || "").trim().toLowerCase();
    return (review.spring_parameters?.load_points || []).some((item) => String(item?.load_point_id || "") !== String(excludedId)
      && String(item?.label || "").trim().toLowerCase() === canonical);
  },
  getParameterFields(parameters) {
    return Object.keys(parameters).filter((field) => field !== "load_points");
  },
  getParameterFieldGroups(parameters) {
    const coreNames = new Set(["wire_diameter", "free_length", "total_coils", "active_coils", "standard_no"]);
    const fields = Object.keys(parameters).filter((field) => field !== "load_points");
    return {
      core: fields.filter((field) => coreNames.has(field)),
      advanced: fields.filter((field) => !coreNames.has(field)),
    };
  },
  sourceValues(source) {
    return (Array.isArray(source) ? source : [source]).filter(Boolean).map(String);
  },
  DEFAULT_CANDIDATE_NOTICE: "未在图中识别，请单独确认。",
  usesSystemDefaultCandidate(item) {
    const sources = context.sourceValues(item?.source).map((source) => source.toLowerCase());
    return Boolean(item?.default_source)
      || sources.some((source) => source.includes("company_default") || source.includes("system_default") || source.includes("protocol_default"));
  },
  targetFieldLabel(field) {
    return {
      wire_diameter: "线径",
      free_length: "自由长度",
      total_coils: "总圈数",
      active_coils: "有效圈数",
      standard_no: "适用标准",
      perpendicularity: "垂直度",
      spring_rate: "刚度",
      solid_height: "压并高度",
      straightness: "直线度",
      pitch: "节距",
    }[field] || field;
  },
  reasonablenessSeverityForField(review, field) {
    const issue = (review.parameter_reasonableness?.issues || []).find((item) => (item.fields || []).includes(field));
    return issue?.severity || "";
  },
  reasonablenessSeverityLabel(severity) {
    return { blocked: "阻断问题", warning: "风险提示", needs_input: "待补充" }[severity] || severity;
  },
  generationContractValue(field, rawValue) {
    if (["wire_diameter", "mean_diameter", "free_length"].includes(field)) {
      const value = Number(rawValue);
      if (!Number.isFinite(value) || value <= 0) throw new Error(`${field}必须大于0`);
      return value;
    }
    if (["total_coils", "active_coils"].includes(field)) {
      const value = Number(rawValue);
      if (!Number.isInteger(value) || value <= 0) throw new Error(`${field}必须是正整数`);
      return value;
    }
    return rawValue;
  },
  supplementInputMode(field) {
    return new Set(["perpendicularity", "spring_rate", "solid_height", "straightness", "pitch", "body_length", "coil_index"]).has(field) ? "decimal" : "text";
  },
  confirmParam(param, field) {
    param.need_human_review = false;
    context.state.review.manual_confirmations[field] = { confirmed: true, value: param.value ?? param.content ?? null };
  },
  technicalRequirementConfirmationKey(item, index = -1) {
    const requirementId = String(item?.requirement_id || "").trim();
    return requirementId ? `technical_requirement_${requirementId}` : `technical_${Math.max(index, 0)}`;
  },
  technicalRequirementField(item, index = -1) {
    const requirementId = String(item?.requirement_id || "").trim();
    return `technical_requirements.${requirementId || Math.max(index + 1, 1)}`;
  },
  ensureTechnicalRequirementIds(review) {
    review.technical_requirements ||= [];
    review.technical_requirements.forEach((item, index) => { item.requirement_id ||= `techreq-test-${index + 1}`; });
    return review;
  },
  isDuplicateTechnicalRequirement(review, target) {
    const type = String(target?.type || "other");
    const content = String(target?.content || "").trim().replace(/\s+/g, " ").toLowerCase();
    return (review?.technical_requirements || []).some((item) => item !== target
      && String(item?.type || "other") === type
      && String(item?.content || "").trim().replace(/\s+/g, " ").toLowerCase() === content);
  },
  confirmationControlState(item, options = {}) {
    if (options.kind === "load_point" && !context.isValidLoadPoint(item)) {
      return { state: "invalid", disabled: true, reason: "高度和力值需要完整填写为有效数字" };
    }
    if (options.kind === "technical") {
      if (!String(item?.content || "").trim()) return { state: "invalid", disabled: true, reason: "技术要求内容不能为空" };
      if (item?.type === "surface" && !["matched", "alias_matched", "llm_auto_matched", "human_confirmed"].includes(item?.normalization_status)) {
        return { state: "invalid", disabled: true, reason: "请先明确表面处理标准术语" };
      }
    }
    if (options.kind === "parameter" && (item?.value == null || String(item.value).trim() === "")) {
      return { state: "invalid", disabled: true, reason: "请先填写参数值" };
    }
    if (options.kind === "parameter" && context.supplementInputMode(options.field) === "decimal" && !Number.isFinite(Number(item?.value))) {
      return { state: "invalid", disabled: true, reason: "请输入有效数字" };
    }
    return { state: "pending", disabled: false, reason: "" };
  },
};
vm.createContext(context);
const standardHelperStart = appSource.indexOf("function standardNumberSuggestionEligible");
const standardHelperEnd = appSource.indexOf("function reasonablenessSuggestionIsFresh", standardHelperStart);
assert.ok(standardHelperStart >= 0 && standardHelperEnd > standardHelperStart);
vm.runInContext(appSource.slice(standardHelperStart, standardHelperEnd), context);
const confirmSelectionStart = appSource.indexOf("function confirmStandardSelection");
const confirmSelectionEnd = appSource.indexOf("function switchSpringType", confirmSelectionStart);
assert.ok(confirmSelectionStart >= 0 && confirmSelectionEnd > confirmSelectionStart);
vm.runInContext(appSource.slice(confirmSelectionStart, confirmSelectionEnd), context);
vm.runInContext(appSource.slice(helperStart, helperEnd), context);

const confirmed = (value, extra = {}) => ({ value, need_human_review: false, source: ["qwen_vision"], ...extra });
const pending = (value, extra = {}) => ({ value, need_human_review: true, source: ["qwen_vision"], ...extra });
const review = {
  spring_parameters: {
    wire_diameter: pending(2),
    mean_diameter: confirmed(18),
    free_length: pending(45, { source: ["solidworks_protocol_default"], default_source: "spring_generation_parameters/v2" }),
    total_coils: pending(10),
    active_coils: confirmed(8),
    standard_no: pending("GB/T 1239.2-2009"),
    perpendicularity: pending(0.5),
    spring_rate: pending(1.2, { source: ["formula_calculation"], source_fields: ["active_coils", "mean_diameter"] }),
    solid_height: pending(20, { source: ["formula_calculation"], source_fields: ["total_coils"] }),
    formula_chain: pending(22, { source: ["formula_calculation"], source_fields: ["solid_height"] }),
    stale_formula: pending(23, { source: ["formula_calculation"], source_fields: ["total_coils"], derived_value_stale: true }),
    straightness: pending(0.4),
    pitch: pending("bad-number"),
    body_length: pending("bad-number", { source: ["human_added"] }),
    coil_index: pending(null, { tolerance_upper: 0.2, evidence: "图纸仅识别到公差" }),
    blank_parameter: pending(null),
    load_points: [
      { label: "F1", height: 30, force: 100, need_human_review: true, source: ["qwen_vision"] },
      { label: "F2", height: 20, force: null, need_human_review: true, source: ["rapidocr"] },
      { label: "F3", height: 15, force: 180, need_human_review: true, source: ["geometry"] },
      { label: "F4", height: null, force: null, need_human_review: true, source: ["qwen_vision"] },
    ],
  },
  technical_requirements: [
    { type: "other", content: "去除毛刺。", need_human_review: true, source: ["qwen_vision"] },
    { type: "surface", content: "表面镀锌。", normalization_status: "matched", need_human_review: true, source: ["baidu_ocr"] },
    { type: "surface", content: "特殊处理。", normalization_status: "unmatched", need_human_review: true, source: ["werk24_semantic"] },
    { type: "other", content: "", need_human_review: true, source: ["qwen_vision"] },
  ],
  standard_selection: { selected_standard: "GB/T 1239.2-2009", need_human_review: true, human_confirmed: false },
  standardization_results: [{ target_field: "free_length", status: "suggested", need_human_review: true }],
  parameter_reasonableness: {
    issues: [
      { severity: "warning", fields: ["straightness"] },
      { severity: "blocked", fields: ["load_points.F3"] },
    ],
  },
  manual_confirmations: {},
};

const standardSelectionBefore = structuredClone(review.standard_selection);
const standardizationBefore = structuredClone(review.standardization_results);
const plan = context.buildSafeConfirmationPlan(review);
assert.deepEqual(JSON.parse(JSON.stringify(plan.group_counts)), { core: 2, advanced: 2, load_point: 1, technical: 2 });
assert.equal(plan.items.length, 7);
assert.deepEqual(
  [...plan.items].map((item) => item.field),
  [
    "wire_diameter", "total_coils", "perpendicularity", "spring_rate",
    "load_points.F1", "technical_requirements.1", "technical_requirements.2",
  ],
);
assert.equal(plan.skipped.some((item) => item.field === "free_length" && item.reason.includes("未在图中识别，请单独确认")), true);
assert.equal(plan.skipped.some((item) => item.field === "standard_no" && item.reason.includes("标准号与当前适用标准不一致")), true);
assert.equal(plan.skipped.some((item) => item.field === "solid_height" && item.reason.includes("公式来源字段")), true);
assert.equal(plan.skipped.some((item) => item.field === "formula_chain" && item.reason.includes("公式来源字段")), true);
assert.equal(plan.skipped.some((item) => item.field === "stale_formula" && item.reason.includes("公式结果已过期")), true);
assert.equal(plan.skipped.some((item) => item.field === "straightness" && item.reason.includes("风险提示")), true);
assert.equal(plan.skipped.some((item) => item.field === "pitch" && item.reason.includes("有效数字")), true);
assert.equal(plan.skipped.some((item) => item.field === "load_points.F2" && item.reason.includes("完整填写")), true);
assert.equal(plan.skipped.find((item) => item.field === "load_points.F2")?.kind, "load_point");
assert.equal(plan.skipped.find((item) => item.field === "load_points.F2")?.load_point_id, "loadpt-test-2");
assert.equal(plan.skipped.some((item) => item.field === "load_points.F3" && item.reason.includes("阻断问题")), true);
assert.equal(plan.skipped.some((item) => item.field === "technical_requirements.3" && item.reason.includes("尚未明确匹配")), true);
context.state.review = review;
const result = context.confirmSafeRecognizedFields(plan);
assert.equal(result.count, 9);
assert.deepEqual(JSON.parse(JSON.stringify(result.auto_formula_fields)), ["spring_rate", "solid_height", "formula_chain"]);
assert.equal(review.spring_parameters.wire_diameter.need_human_review, false);
assert.equal(review.spring_parameters.spring_rate.need_human_review, false);
assert.equal(review.spring_parameters.load_points[0].need_human_review, false);
assert.equal(review.technical_requirements[0].need_human_review, false);
assert.equal(review.spring_parameters.free_length.need_human_review, true);
assert.equal(review.spring_parameters.solid_height.need_human_review, false);
assert.equal(review.spring_parameters.formula_chain.need_human_review, false);
assert.equal(review.spring_parameters.stale_formula.need_human_review, true);
assert.equal(review.spring_parameters.load_points[1].need_human_review, true);
assert.equal(review.technical_requirements[2].need_human_review, true);
assert.deepEqual(review.standard_selection, standardSelectionBefore);
assert.deepEqual(review.standardization_results, standardizationBefore);

const supportedStandardReview = structuredClone(review);
supportedStandardReview.standard_selection.rules_available = true;
supportedStandardReview.standard_selection.metadata = { conflicts: [] };
supportedStandardReview.standardization_results.push({
  target_field: "standard_no", suggested_value: "GB/T 1239.2-2009", status: "need_context",
});
context.state.review = supportedStandardReview;
const standardPlan = context.buildSafeConfirmationPlan(supportedStandardReview);
assert.equal(standardPlan.items.some((item) => item.field === "standard_no"), true);
supportedStandardReview.standardization_results.push({
  target_field: "standard_no", suggested_value: "OTHER-STANDARD", status: "need_context",
});
assert.equal(context.buildSafeConfirmationPlan(supportedStandardReview).items.some((item) => item.field === "standard_no"), false);
supportedStandardReview.standardization_results.pop();
context.confirmSafeRecognizedFields(standardPlan);
assert.equal(supportedStandardReview.spring_parameters.standard_no.need_human_review, false);
assert.equal(supportedStandardReview.standard_selection.human_confirmed, true);
assert.equal(supportedStandardReview.manual_confirmations.standard_selection.confirmed, true);
context.state.review = review;

review.change_history = [{
  client_event_id: "bulk-event-1",
  event_type: "safe_fields_confirmed",
  sync_status: "saved",
  after_state: { confirmed_count: result.count },
  metadata: { skipped: plan.skipped.map((item) => ({ ...item })) },
}];
let followup = context.bulkConfirmationFollowupReport(review);
assert.equal(followup.confirmed_count, 9);
assert.equal(followup.items.some((item) => item.field === "pitch" && item.state === "blocked"), true);
assert.equal(followup.items.some((item) => item.field === "straightness" && item.state === "manual"), true);
assert.equal(followup.items.some((item) => item.field === "standard_no" && item.state === "manual"), true);
assert.equal(followup.items.some((item) => item.kind === "technical" && item.state === "blocked"), true);
assert.equal(followup.items.some((item) => item.field === "free_length" && item.state === "manual"), true, "visible defaults must be listed");
assert.equal(followup.items.some((item) => item.field === "solid_height"), false, "formula values unlocked in the same batch must not remain in follow-up");
assert.equal(followup.items.some((item) => item.field === "body_length" && item.state === "blocked"), true, "visible manual values must be listed");
assert.equal(followup.items.some((item) => item.field === "coil_index" && item.state === "blocked"), true, "partial recognized content must be listed");
assert.equal(followup.items.some((item) => item.field === "blank_parameter"), false, "blank parameter rows must be hidden");
assert.equal(followup.items.some((item) => item.field === "load_points.F4"), false, "label-only load points must be hidden");
assert.equal(followup.items.some((item) => item.field === "technical_requirements.4"), false, "empty requirements must be hidden");

review.spring_parameters.straightness.source.push("human_edited");
followup = context.bulkConfirmationFollowupReport(review);
assert.equal(followup.items.some((item) => item.field === "straightness"), true, "editing a visible value must not remove it from the follow-up list");

review.spring_parameters.load_points[1].label = "FX";
followup = context.bulkConfirmationFollowupReport(review);
assert.equal(followup.items.some((item) => item.load_point_id === "loadpt-test-2" && item.field === "load_points.FX"), true);

review.spring_parameters.free_length.need_human_review = false;
review.spring_parameters.pitch.value = 2.5;
followup = context.bulkConfirmationFollowupReport(review);
assert.equal(followup.items.some((item) => item.field === "free_length"), false);
assert.equal(followup.items.some((item) => item.field === "pitch" && item.state === "available"), true);
review.spring_parameters.pitch.need_human_review = false;
review.spring_parameters.straightness.need_human_review = false;
review.spring_parameters.standard_no.need_human_review = false;
review.spring_parameters.solid_height.need_human_review = false;
review.spring_parameters.body_length.need_human_review = false;
review.spring_parameters.coil_index.need_human_review = false;
review.spring_parameters.stale_formula.need_human_review = false;
review.spring_parameters.load_points[1].need_human_review = false;
review.spring_parameters.load_points[2].need_human_review = false;
review.technical_requirements[2].need_human_review = false;
followup = context.bulkConfirmationFollowupReport(review);
assert.equal(followup, null, "blank skipped items must not keep the panel visible");

const focusStart = appSource.indexOf("function highlightReviewTarget");
const focusEnd = appSource.indexOf("function createCompareOverlay", focusStart);
assert.notEqual(focusStart, -1, "focus helper must exist");
assert.notEqual(focusEnd, -1, "focus helper block must be complete");
const animationFrames = [];
const advancedDetails = { open: false };
const valueInput = {
  focusCount: 0,
  selectCount: 0,
  focus() { this.focusCount += 1; },
  select() { this.selectCount += 1; },
};
const parameterRow = {
  dataset: { field: "solid_height" },
  offsetWidth: 320,
  scrollCount: 0,
  highlightCount: 0,
  closest(selector) { return selector === "details" ? advancedDetails : null; },
  scrollIntoView() { this.scrollCount += 1; },
  querySelector(selector) { return selector === '[data-role="value"]' ? valueInput : null; },
  classList: {
    remove() {},
    add() { parameterRow.highlightCount += 1; },
  },
};
const focusContext = {
  state: {
    review: { spring_parameters: { load_points: [] }, technical_requirements: [] },
    compareOpen: true,
    compareTab: "workbench",
    activeReviewMessageId: "message-1",
  },
  renderCount: 0,
  activateReviewContext() {},
  openCompareOverlay() {},
  renderCompareOverlay() { focusContext.renderCount += 1; },
  requestAnimationFrame(callback) { animationFrames.push(callback); },
  window: { setTimeout() {} },
  compareOverlay: {
    querySelector() { return null; },
    querySelectorAll(selector) { return selector === '[data-kind="param"]' ? [parameterRow] : []; },
  },
  parseLoadPointTarget() { return null; },
  canonicalLoadPointLabel(value) { return String(value || "").trim().toLowerCase(); },
  isFiniteReviewNumber(value) { return Number.isFinite(Number(value)); },
};
vm.createContext(focusContext);
vm.runInContext(appSource.slice(focusStart, focusEnd), focusContext);
focusContext.focusMissingStandardizationField("solid_height", "message-1", { highlight: true });
assert.equal(focusContext.state.compareTab, "parameters");
assert.equal(focusContext.renderCount, 1);
assert.equal(parameterRow.scrollCount, 0, "target must wait for the overlay scroll restoration pass");
animationFrames.shift()();
assert.equal(parameterRow.scrollCount, 0, "target must wait for the second layout frame");
animationFrames.shift()();
assert.equal(advancedDetails.open, true);
assert.equal(parameterRow.scrollCount, 1);
assert.equal(parameterRow.highlightCount, 1);
assert.equal(valueInput.focusCount, 1);
assert.equal(valueInput.selectCount, 1);

const handlerStart = appSource.indexOf("root.querySelector('[data-action=\"confirm-all-review-items\"]')");
const handlerEnd = appSource.indexOf("root.querySelectorAll('[data-action=\"focus-workbench-field\"]')", handlerStart);
const handlerSource = appSource.slice(handlerStart, handlerEnd);
assert.equal((handlerSource.match(/queueReviewAuditEvent/g) || []).length, 1);
assert.match(handlerSource, /group_counts/);
assert.match(handlerSource, /auto_formula_fields/);
assert.match(handlerSource, /skipped/);
assert.match(handlerSource, /load_point_id/);
assert.match(handlerSource, /requirement_id/);
assert.doesNotMatch(handlerSource, /window\.confirm/);
assert.doesNotMatch(appSource, /function buildSafeConfirmationPreview/);
assert.doesNotMatch(appSource, /data-action="confirm-safe-fields"/);
assert.doesNotMatch(appSource, /function confirmAllFields/);
assert.match(appSource, /data-action="confirm-all-review-items"/);
assert.match(appSource, /data-role="focus-bulk-confirmation-target"/);
assert.match(appSource, /review-target-highlight/);

const defaultNoticeStart = appSource.indexOf("const DEFAULT_CANDIDATE_NOTICE");
const defaultNoticeEnd = appSource.indexOf("function hasStandardizationForField", defaultNoticeStart);
const defaultNoticeContext = {
  sourceValues(source) { return (Array.isArray(source) ? source : [source]).filter(Boolean); },
};
vm.createContext(defaultNoticeContext);
vm.runInContext(appSource.slice(defaultNoticeStart, defaultNoticeEnd), defaultNoticeContext);
assert.equal(
  defaultNoticeContext.pendingDefaultCandidateNotice({ need_human_review: true, default_source: "company_default", source: ["company_default"] }),
  "未在图中识别，请单独确认。",
);
assert.equal(defaultNoticeContext.pendingDefaultCandidateNotice({ need_human_review: false, default_source: "company_default" }), "");
assert.equal(defaultNoticeContext.pendingDefaultCandidateNotice({ need_human_review: true, default_source: "company_default", source: ["formula_calculation"] }), "");
assert.equal(defaultNoticeContext.pendingDefaultCandidateNotice({ need_human_review: true, default_source: "company_default", source: ["human_edited"] }), "");
assert.match(appSource, /parameter-default-candidate-note/);

console.log("bulk confirmation UI test passed");
