import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = appSource.indexOf("function renderAccuracyStandardizationResultHtml");
const end = appSource.indexOf("function currentParameterChangeProposal", start);
assert.notEqual(start, -1, "accuracy standardization result renderer must exist");
assert.notEqual(end, -1, "accuracy result renderer block must be complete");

const context = {
  escapeHtml: (value) => String(value ?? ""),
  targetFieldLabel: (field) => ({ free_length: "自由长度" }[field] || field),
  formatStandardValue: (value, unit = "") => `${value}${unit}`,
  formatTolerancePair: (value, unit = "") => {
    if (Number(value?.upper) === Math.abs(Number(value?.lower))) return `±${Math.abs(Number(value.upper))}${unit}`;
    return `${value?.upper ?? ""}/${value?.lower ?? ""}${unit}`;
  },
  state: { lastJob: { review_revision: 8 } },
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

const html = context.renderAccuracyStandardizationResultHtml({
  status: "completed",
  requested_grade: "1级",
  previous_grade: "2级",
  scope: "general",
  selection_changed: true,
  specialized_grades_retained: {
    diameter_accuracy_grade: "2级",
    load_accuracy_grade: "3级",
  },
  standardization_result_count: 7,
  warnings: ["载荷点需要人工核对"],
});

assert.match(html, /精度标准化已完成/);
assert.match(html, /2级 → 1级/);
assert.match(html, /重新生成 7 项标准化建议/);
assert.match(html, /直径精度等级/);
assert.match(html, /载荷精度等级/);
assert.match(html, /保持不变并继续优先/);
assert.match(html, /载荷点需要人工核对/);
assert.doesNotMatch(html, /diameter_accuracy_grade/);

const batchHtml = context.renderAccuracyStandardizationResultHtml({
  status: "completed",
  requested_grade: "1级",
  previous_grade: "2级",
  standardization_result_count: 2,
}, {
  batch_id: "standardization_batch_demo",
  status: "ready",
  review_revision: 8,
  applicable_count: 1,
  skipped_count: 1,
  items: [{
    result_index: 0,
    target_field: "free_length",
    label: "自由长度",
    unit: "mm",
    before: { exists: true, value: 45, tolerance_upper: 1, tolerance_lower: -1, unit: "mm", confirmed: true },
    after: { exists: true, value: 45, tolerance_upper: 0.6, tolerance_lower: -0.6, unit: "mm", confirmed: true },
    can_apply: true,
    basis: "按标准表计算公差。",
  }],
  skipped_items: [{
    target_field: "spring_rate",
    label: "刚度",
    reason: "缺少有效圈数，暂时无法计算。",
  }],
}, 3);
assert.match(batchHtml, /本次标准化修改/);
assert.match(batchHtml, /自由长度/);
assert.match(batchHtml, /45mm，公差 ±1mm/);
assert.match(batchHtml, /45mm，公差 ±0.6mm/);
assert.match(batchHtml, /应用全部 · 1/);
assert.match(batchHtml, /跳过 1 项/);
assert.match(batchHtml, /缺少有效圈数/);
assert.doesNotMatch(batchHtml, /free_length/);
assert.doesNotMatch(batchHtml, /formula/);

context.state.lastJob.review_revision = 9;
const staleHtml = context.renderChatStandardizationBatchHtml({
  batch_id: "standardization_batch_demo",
  status: "ready",
  review_revision: 8,
  items: [{ label: "自由长度", can_apply: true, before: {}, after: {} }],
  skipped_items: [],
}, 3);
assert.match(staleHtml, /结果已过期/);
assert.match(staleHtml, /disabled/);

console.log("accuracy standardization UI tests passed");
