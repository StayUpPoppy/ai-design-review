import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const previewStart = appSource.indexOf("function buildParameterImpactBaselineState");
const previewEnd = appSource.indexOf("function canBatchSupplementChatAction", previewStart);
const validationStart = appSource.indexOf("function standardizationChatPatchCandidates");
const validationEnd = appSource.indexOf("function applyStandardizationChatActions", validationStart);

assert.notEqual(previewStart, -1, "impact preview helpers must exist");
assert.notEqual(previewEnd, -1, "impact preview helper block must be complete");
assert.notEqual(validationStart, -1, "chat validation helpers must exist");
assert.notEqual(validationEnd, -1, "chat validation helper block must be complete");

const context = {
  state: { review: null, generationJobs: [{ generation_id: "generation-1" }] },
  structuredClone,
  escapeHtml: (value) => String(value),
  FIELD_LABELS: {
    mean_diameter: "中径",
    outer_diameter: "外径",
    spring_index: "旋绕比",
    slenderness_ratio: "细长比",
  },
  targetFieldLabel: (field) => ({ mean_diameter: "中径", outer_diameter: "外径" })[field] || field,
  formatStandardValue: (value, unit = "") => value == null ? "-" : `${value}${unit || ""}`,
  formatTolerancePair: (value, unit = "") => `${value?.upper ?? ""}/${value?.lower ?? ""}${unit}`,
  parseLoadPointTarget: () => null,
};
vm.createContext(context);
vm.runInContext(appSource.slice(previewStart, previewEnd), context);
vm.runInContext(appSource.slice(validationStart, validationEnd), context);

context.state.review = {
  drawing_summary: { spring_type: "compression_spring" },
  spring_parameters: {
    mean_diameter: { value: 23, unit: "mm", need_human_review: false },
    outer_diameter: { value: 26, unit: "mm", need_human_review: false },
  },
  technical_requirements: [{ type: "surface", content: "镀锌", need_human_review: false }],
  standard_selection: { selected_standard: "GB/T 1239.2-2009", human_confirmed: true },
  standardization_results: [],
  derived_parameters_stale: false,
};

const baseline = context.buildParameterImpactBaselineState(context.state.review);
const preview = {
  status: "ready",
  summary: "修改后未发现新增阻断问题",
  impact_count: 3,
  direct_changes: [{
    field: "mean_diameter", label: "中径", change_type: "value", before: 23, after: 25, unit: "mm",
  }],
  derived_changes: [{
    field: "outer_diameter", label: "外径", before: 26, after: 28, unit: "mm", formula: "D+d",
  }, {
    field: "spring_index", label: "spring_index", before: 7, after: 4.3333, unit: null,
  }, {
    field: "slenderness_ratio", label: "slenderness_ratio", before: 1.6667, after: 2.6923, unit: null,
  }],
  risk_delta: { introduced: [], resolved: [], unchanged_count: 0 },
  generation_readiness: {
    before_status: "ready",
    after_status: "ready_with_warnings",
    parameter_package_changed: true,
    changed_frozen_fields: ["mean_diameter"],
  },
  workflow_effects: { standardization_recalculation_required: true, new_generation_required: true },
  baseline_state: baseline,
};
const action = {
  type: "propose_parameter_patch",
  target_field: "mean_diameter",
  proposed_value: 25,
  status: "pending",
  impact_preview: preview,
};

assert.equal(context.isParameterImpactPreviewStale(preview), false);
assert.equal(context.canApplyStandardizationChatAction(action), true);
const freshHtml = context.renderStandardizationChatImpactPreviewHtml(preview, 2);
assert.match(freshHtml, /预计影响 3 项/);
assert.match(freshHtml, /中径/);
assert.match(freshHtml, /23mm → 25mm/);
assert.match(freshHtml, /旋绕比/);
assert.match(freshHtml, /细长比/);
assert.doesNotMatch(freshHtml, />spring_index</);
assert.doesNotMatch(freshHtml, />slenderness_ratio</);
assert.doesNotMatch(freshHtml, /D\+d/);
assert.match(freshHtml, /旧生图版本不会被覆盖/);
assert.doesNotMatch(freshHtml, /重新计算影响/);

context.state.review.spring_parameters.mean_diameter.value = 24;
assert.equal(context.isParameterImpactPreviewStale(preview), true);
assert.equal(context.canApplyStandardizationChatAction(action), false);
assert.equal(context.canApplyStandardizationChatAction(action, { ignoreImpactFreshness: true }), true);
const staleHtml = context.renderStandardizationChatImpactPreviewHtml(preview, 2);
assert.match(staleHtml, /影响预览已过期/);
assert.match(staleHtml, /data-role="recalculate-impact"/);

context.state.review.spring_parameters.mean_diameter.value = 23;
const secondAction = {
  type: "propose_parameter_patch",
  target_field: "outer_diameter",
  proposed_value: 28,
  status: "pending",
  impact_preview: { ...preview, baseline_state: baseline },
};
const blockedBatch = context.validateStandardizationChatBatch({
  suggested_actions: [action, secondAction],
  impact_preview: { ...preview, status: "blocked", summary: "组合修改后有效圈数大于总圈数" },
});
assert.equal(blockedBatch.ok, false);
assert.match(blockedBatch.message, /组合修改/);

const validBatch = context.validateStandardizationChatBatch({
  suggested_actions: [action, secondAction],
  impact_preview: preview,
});
assert.equal(validBatch.ok, true);

const rescuedByBatch = context.validateStandardizationChatBatch({
  suggested_actions: [
    {
      type: "propose_parameter_patch",
      target_field: "active_coils",
      proposed_value: 13,
      status: "pending",
      validation: { status: "blocked" },
      impact_preview: { ...preview, status: "blocked", baseline_state: baseline },
    },
    {
      type: "propose_parameter_patch",
      target_field: "total_coils",
      proposed_value: 15,
      status: "pending",
      impact_preview: { ...preview, baseline_state: baseline },
    },
  ],
  impact_preview: { ...preview, status: "ready", baseline_state: baseline },
});
assert.equal(rescuedByBatch.ok, true, "the combined impact preview must be authoritative for a batch");

context.state.review.spring_parameters.mean_diameter.value = 24;
const staleBatch = context.validateStandardizationChatBatch({
  suggested_actions: [action, secondAction],
  impact_preview: preview,
});
assert.equal(staleBatch.ok, false);
assert.match(staleBatch.message, /预览已过期/);

console.log("parameter impact preview UI tests passed");
