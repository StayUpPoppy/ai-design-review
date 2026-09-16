import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const cssSource = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");
const start = appSource.indexOf("function renderParameterReasonablenessHtml");
const end = appSource.indexOf("function renderParameterTableHtml", start);

assert.notEqual(start, -1, "reasonableness renderer must exist");
assert.notEqual(end, -1, "reasonableness renderer block must be complete");

const context = {
  bulkReport: null,
  escapeHtml: (value) => String(value ?? ""),
  lastStandardizationApplyHistory: () => null,
  targetFieldLabel: (value) => String(value ?? ""),
  formatCompactNumber: (value) => String(value ?? ""),
  parseLoadPointTarget: () => null,
  parameterPersistenceState: () => null,
  bulkConfirmationFollowupReport: () => context.bulkReport,
  state: { reviewEditSerial: 0 },
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

const blocked = context.renderParameterReasonablenessHtml({
  parameter_reasonableness: {
    status: "blocked",
    summary: "外径与线径存在矛盾。",
    issues: [{
      severity: "blocked",
      rule_id: "SPRING-GEO-OUTER-INNER",
      fields: ["outer_diameter", "wire_diameter"],
      message: "外径必须大于两倍线径。",
      calculation: "Di=Do-2d=-1 mm",
      basis: "圆丝圆柱螺旋弹簧几何关系。",
      explanation: "当前截面几何不成立。",
      customer_question: "请客户确认外径或线径。",
    }],
  },
});

assert.match(blocked, /参数合理性/);
assert.match(blocked, /不可用/);
assert.match(blocked, /SPRING-GEO-OUTER-INNER/);
assert.match(blocked, /建议向客户确认/);
assert.match(blocked, /data-role="focus-reasonableness-field"/);
assert.match(cssSource, /\.parameter-reasonableness-item\.blocked/);
assert.match(cssSource, /\.data-row\.parameter-risk-warning/);

context.bulkReport = {
  confirmed_count: 8,
  persistence_state: "failed",
  items: [
    { kind: "parameter", field: "free_length", label: "自由长度", state: "manual", status_label: "需单独确认", reason: "默认候选值需要单独确认" },
    { kind: "load_point", field: "load_points.F2", load_point_id: "loadpt-2", label: "载荷测试点 F2", state: "blocked", status_label: "暂不可确认", reason: "高度和力值需要完整填写" },
    { kind: "technical", field: "technical_requirements.req-3", requirement_id: "req-3", label: "表面处理", state: "available", status_label: "现已可确认", reason: "当前已满足确认条件" },
  ],
};
const bulkFollowup = context.renderParameterReasonablenessHtml({
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [] },
});
assert.match(bulkFollowup, /批量确认待处理/);
assert.match(bulkFollowup, /已批量确认 8 项，还有 3 项待处理内容/);
assert.match(bulkFollowup, /定位参数/);
assert.match(bulkFollowup, /定位载荷点/);
assert.match(bulkFollowup, /定位要求/);
assert.match(bulkFollowup, /结果尚未保存/);
assert.match(bulkFollowup, /data-action="retry-bulk-confirmation-save"/);
assert.match(cssSource, /\.bulk-confirmation-followup-item/);
assert.match(cssSource, /@container \(max-width: 480px\)/);
context.bulkReport = null;

const pass = context.renderParameterReasonablenessHtml({
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [] },
});
assert.match(pass, /参数关系正常/);
assert.match(pass, /当前没有需要处理的参数合理性问题/);

console.log("parameter reasonableness UI test passed");
