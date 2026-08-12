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
  state: { review: null },
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
    return new Set(["perpendicularity", "spring_rate", "solid_height", "straightness", "pitch"]).has(field) ? "decimal" : "text";
  },
  confirmParam(param, field) {
    param.need_human_review = false;
    context.state.review.manual_confirmations[field] = { confirmed: true, value: param.value ?? param.content ?? null };
  },
};
vm.createContext(context);
vm.runInContext(appSource.slice(helperStart, helperEnd), context);

const confirmed = (value, extra = {}) => ({ value, need_human_review: false, source: ["drawing"], ...extra });
const pending = (value, extra = {}) => ({ value, need_human_review: true, source: ["drawing"], ...extra });
const review = {
  spring_parameters: {
    wire_diameter: pending(2),
    mean_diameter: confirmed(18),
    free_length: pending(45, { source: ["solidworks_protocol_default"], default_source: "spring_generation_parameters/v1" }),
    total_coils: pending(10),
    active_coils: confirmed(8),
    standard_no: pending("GB/T 1239.2-2009"),
    perpendicularity: pending(0.5),
    spring_rate: pending(1.2, { source: ["formula_calculation"], source_fields: ["active_coils", "mean_diameter"] }),
    solid_height: pending(20, { source: ["formula_calculation"], source_fields: ["total_coils"] }),
    straightness: pending(0.4),
    pitch: pending("bad-number"),
    load_points: [
      { label: "F1", height: 30, force: 100, need_human_review: true, source: ["drawing"] },
      { label: "F2", height: 20, force: null, need_human_review: true, source: ["drawing"] },
      { label: "F3", height: 15, force: 180, need_human_review: true, source: ["drawing"] },
    ],
  },
  technical_requirements: [
    { type: "other", content: "去除毛刺。", need_human_review: true },
    { type: "surface", content: "表面镀锌。", normalization_status: "matched", need_human_review: true },
    { type: "surface", content: "特殊处理。", normalization_status: "unmatched", need_human_review: true },
    { type: "other", content: "", need_human_review: true },
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
assert.equal(plan.skipped.some((item) => item.field === "free_length" && item.reason.includes("默认候选值")), true);
assert.equal(plan.skipped.some((item) => item.field === "standard_no" && item.reason.includes("不在批量确认范围")), true);
assert.equal(plan.skipped.some((item) => item.field === "solid_height" && item.reason.includes("公式来源字段")), true);
assert.equal(plan.skipped.some((item) => item.field === "straightness" && item.reason.includes("风险提示")), true);
assert.equal(plan.skipped.some((item) => item.field === "pitch" && item.reason.includes("有效数字")), true);
assert.equal(plan.skipped.some((item) => item.field === "load_points.F2" && item.reason.includes("完整填写")), true);
assert.equal(plan.skipped.some((item) => item.field === "load_points.F3" && item.reason.includes("阻断问题")), true);
assert.equal(plan.skipped.some((item) => item.field === "technical_requirements.3" && item.reason.includes("尚未明确匹配")), true);
context.state.review = review;
const result = context.confirmSafeRecognizedFields(plan);
assert.equal(result.count, 7);
assert.equal(review.spring_parameters.wire_diameter.need_human_review, false);
assert.equal(review.spring_parameters.spring_rate.need_human_review, false);
assert.equal(review.spring_parameters.load_points[0].need_human_review, false);
assert.equal(review.technical_requirements[0].need_human_review, false);
assert.equal(review.spring_parameters.free_length.need_human_review, true);
assert.equal(review.spring_parameters.solid_height.need_human_review, true);
assert.equal(review.spring_parameters.load_points[1].need_human_review, true);
assert.equal(review.technical_requirements[2].need_human_review, true);
assert.deepEqual(review.standard_selection, standardSelectionBefore);
assert.deepEqual(review.standardization_results, standardizationBefore);

const handlerStart = appSource.indexOf("root.querySelector('[data-action=\"confirm-all-review-items\"]')");
const handlerEnd = appSource.indexOf("root.querySelectorAll('[data-action=\"focus-workbench-field\"]')", handlerStart);
const handlerSource = appSource.slice(handlerStart, handlerEnd);
assert.equal((handlerSource.match(/queueReviewAuditEvent/g) || []).length, 1);
assert.match(handlerSource, /group_counts/);
assert.match(handlerSource, /skipped/);
assert.doesNotMatch(handlerSource, /window\.confirm/);
assert.doesNotMatch(appSource, /function buildSafeConfirmationPreview/);
assert.doesNotMatch(appSource, /data-action="confirm-safe-fields"/);
assert.doesNotMatch(appSource, /function confirmAllFields/);
assert.match(appSource, /data-action="confirm-all-review-items"/);

console.log("bulk confirmation UI test passed");
