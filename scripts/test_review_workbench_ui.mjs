import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
assert.match(appSource, /"end_type",\s*\n\s*"end_grinding"/);
assert.match(appSource, /COMPRESSION_END_GRINDING_OPTIONS = \["两端磨削", "两端不磨削"\]/);
assert.match(appSource, /COMPRESSION_END_TYPE_OPTIONS = \["两端并紧", "两端不并紧"\]/);
assert.equal(
  (appSource.match(/<button[^>]+data-action="export-generation-package"/g) || []).length,
  2,
  "工作台和生图参数包页应各有一个导出按钮",
);
assert.match(
  appSource,
  /querySelectorAll\('\[data-action="export-generation-package"\]'\)\.forEach/,
  "两个导出参数包按钮都必须绑定点击事件",
);
const start = appSource.indexOf("function safeConfirmableReviewItems");
const end = appSource.indexOf("function renderCompareDataPanelHtml", start);
const confirmationStart = appSource.indexOf("function confirmParam");
const confirmationEnd = appSource.indexOf("function sourceValues", confirmationStart);

assert.notEqual(start, -1, "review workbench helpers must exist");
assert.notEqual(end, -1, "review workbench helper block must be complete");
assert.notEqual(confirmationStart, -1, "parameter confirmation helper must exist");
assert.notEqual(confirmationEnd, -1, "parameter confirmation helper must be complete");

const invalidatedFields = [];

const context = {
  TECH_LABELS: { surface: "表面处理" },
  COMPRESSION_ACCURACY_GRADE_OPTIONS: ["1级", "2级", "3级"],
  state: {
    review: null,
    pendingAccuracyGrade: "",
    accuracyGradeUpdate: { phase: "idle", grade: "", operation: "", timer: null },
  },
  sourceValues: (value) => Array.isArray(value) ? value : value ? [value] : [],
  parameterAuditState: (param) => ({
    value: param?.value ?? null,
    source: Array.isArray(param?.source) ? param.source : [],
    need_human_review: Boolean(param?.need_human_review),
  }),
  isCompressionSpringReview: () => true,
  getParameterFields: (params) => Object.keys(params).filter((field) => field !== "load_points" && field !== "torque_points"),
  targetFieldLabel: (field) => ({
    wire_diameter: "线径",
    outer_diameter: "外径",
    accuracy_grade: "通用精度等级",
  }[field] || field),
  buildSafeConfirmationPlan: (review) => ({
    items: [
      { field: "wire_diameter", label: "线径" },
      { field: "load_points.F1", label: "载荷测试点 F1" },
      { field: "technical_requirements.1", label: "表面处理" },
    ],
    skipped: [],
  }),
  reasonablenessSeverityForField: (review, field) => review.risks?.[field] || "",
  standardizationBatchPlan: () => ({ items: [], conflicts: [] }),
  revokeManualConfirmations: () => false,
  invalidateStandardizationResults: (field) => {
    invalidatedFields.push(field);
    return 0;
  },
  scheduleAutomaticStandardization: () => {},
  scheduleParameterReasonablenessRefresh: () => {},
  syncBubbleValue: () => {},
  queueReviewAuditEvent: () => {},
  assessGenerationReadiness: () => ({
    status: "needs_confirmation",
    summary: "仍有参数需要人工确认。",
    confirmed_core_count: 2,
    core_field_count: 8,
    missing_fields: [{ field: "outer_diameter", label: "外径", reason: "缺少确认。" }],
    pending_fields: [],
  }),
  escapeHtml: (value) => String(value ?? ""),
  reasonablenessSeverityLabel: (value) => ({ blocked: "不可用", warning: "风险提示", needs_input: "待补充" }[value] || "待核对"),
  canFocusGenerationIssue: () => true,
  accuracyGradeFeedbackIsVisible: () => false,
  accuracyGradeUpdateMessage: () => "",
  pendingAccuracyGradeFor: (param) => {
    const pending = context.state.pendingAccuracyGrade;
    return pending && pending !== param?.value ? pending : "";
  },
  displayedAccuracyGrade: (param) => context.pendingAccuracyGradeFor(param) || param?.value || "",
  setAccuracyGradeUpdate: (phase, grade, operation = "") => {
    context.state.accuracyGradeUpdate = { ...context.state.accuracyGradeUpdate, phase, grade, operation };
  },
  updateAccuracyGradeFeedbackUi: () => {},
  refreshReviewSurfaces: () => {},
  clearTimeout: () => {},
  setTimeout: () => 1,
  document: { querySelectorAll: () => [] },
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);
vm.runInContext(appSource.slice(confirmationStart, confirmationEnd), context);

const review = {
  spring_parameters: {
    wire_diameter: { value: 2, need_human_review: true, source: ["qwen"] },
    outer_diameter: { value: 20, need_human_review: true, source: ["qwen"] },
    accuracy_grade: { value: "2级", need_human_review: true, default_source: "company_default", source: ["company_default"] },
    load_points: [{ label: "F1", height: 18, force: 100, need_human_review: true }],
  },
  technical_requirements: [{ type: "surface", content: "镀锌", need_human_review: true, normalization_status: "matched" }],
  parameter_reasonableness: {
    status: "warning",
    issues: [{ severity: "warning", fields: ["outer_diameter"], message: "外径需要核对。" }],
  },
  risks: { outer_diameter: "warning" },
  standardization_results: [],
};

const safeItems = context.safeConfirmableReviewItems(review);
assert.deepEqual(Array.from(safeItems, (item) => item.label), ["线径", "载荷测试点 F1", "表面处理"]);

const html = context.renderReviewWorkbenchHtml(review);
assert.match(html, /待处理/);
assert.match(html, /data-action="show-workbench-tab"/);
assert.match(html, /去参数页批量确认/);
assert.doesNotMatch(html, /data-action="confirm-safe-fields"/);
assert.match(html, /data-action="run-workbench-standardization"/);
assert.match(html, /data-action="export-generation-package"/);
assert.match(html, /data-action="workbench-ai"/);
assert.match(html, /data-action="select-workbench-accuracy-grade"/);
assert.match(html, /data-accuracy-grade-update-status/);
assert.match(html, /aria-live="polite"/);
assert.match(html, /外径需要核对/);

context.state.review = review;
const selected = context.selectAccuracyGrade({ closest: () => ({ querySelectorAll: () => [] }) }, review, "1级");
assert.equal(selected, true);
assert.equal(review.spring_parameters.accuracy_grade.value, "2级");
assert.equal(context.state.pendingAccuracyGrade, "1级");
assert.equal(context.state.accuracyGradeUpdate.phase, "ready");
assert.deepEqual(invalidatedFields, []);
assert.match(context.renderReviewWorkbenchHtml(review), /重新生成标准化方案/);

const commit = context.prepareAccuracyGradeCommit(review, "1级");
assert.equal(commit.grade, "1级");
assert.equal(review.spring_parameters.accuracy_grade.value, "1级");
assert.equal(review.spring_parameters.accuracy_grade.default_source, undefined);
assert.deepEqual(Array.from(review.spring_parameters.accuracy_grade.source), ["human_selected"]);
assert.equal(review.spring_parameters.accuracy_grade.need_human_review, false);
assert.equal(review.manual_confirmations.accuracy_grade.confirmed, true);
assert.deepEqual(invalidatedFields, []);

const defaultAccuracy = {
  value: "2级",
  source: ["company_default"],
  default_source: "company_default",
  default_reason: "图纸未标注精度等级。",
  need_human_review: true,
};
context.state.review = { manual_confirmations: {} };
context.confirmParam(defaultAccuracy, "accuracy_grade");
assert.equal(defaultAccuracy.default_source, undefined);
assert.equal(defaultAccuracy.default_reason, undefined);
assert.deepEqual(Array.from(defaultAccuracy.source), ["human_confirmed"]);
assert.equal(defaultAccuracy.need_human_review, false);
assert.equal(context.state.review.manual_confirmations.accuracy_grade.confirmed, true);
assert.deepEqual(invalidatedFields, ["accuracy_grade"]);

console.log("review workbench UI test passed");
