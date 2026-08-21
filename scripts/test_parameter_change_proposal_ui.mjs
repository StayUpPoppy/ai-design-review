import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = appSource.indexOf("function currentParameterChangeProposal");
const end = appSource.indexOf("function renderStandardizationChatRollbackHtml", start);
assert.notEqual(start, -1, "proposal rendering helpers must exist");
assert.notEqual(end, -1, "proposal rendering helper block must be complete");

const context = {
  state: {
    lastJob: { job_id: "review-1", review_revision: 3 },
    review: { parameter_change_proposals: [] },
  },
  escapeHtml: (value) => String(value ?? ""),
  FIELD_LABELS: {
    mean_diameter: "中径",
    outer_diameter: "外径",
    inner_diameter: "内径",
    spring_index: "旋绕比",
  },
  TECH_LABELS: { surface: "表面处理", salt_spray: "盐雾试验", other: "其他要求" },
  normalizeTechnicalRequirementType: (value) => ["surface", "salt_spray", "other"].includes(String(value)) ? String(value) : "other",
  targetFieldLabel: (field) => field,
  formatParameterImpactValue: (value, unit = "") => value == null ? "-" : `${value}${unit || ""}`,
  generationReadinessStatusLabel: (status) => ({ ready: "可生成", ready_with_warnings: "可生成（有提示）" })[status] || status,
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

const proposal = {
  proposal_id: "proposal-1",
  version: 2,
  status: "ready",
  summary: "方案已完成整体校验",
  direct_changes: [{ field: "mean_diameter", label: "mean_diameter", before: 42, after: 26, unit: "mm" }],
  synchronized_changes: [
    { field: "outer_diameter", label: "outer_diameter", before: 48, after: 32, unit: "mm" },
    { field: "inner_diameter", label: "inner_diameter", before: 36, after: 20, unit: "mm" },
  ],
  derived_changes: [{ field: "spring_index", label: "spring_index", before: 7, after: 4.3333, formula: "D/d" }],
  recommendations: [],
  clarifying_questions: [],
  blocking_issues: [],
  risk_delta: { introduced: [] },
  generation_readiness: {
    before_status: "ready",
    after_status: "ready_with_warnings",
    parameter_package_changed: true,
  },
};
context.state.review.parameter_change_proposals = [proposal];

const html = context.renderParameterChangeProposalHtml(proposal, 1);
assert.match(html, /参数修改方案 V2/);
assert.match(html, /用户直接修改/);
assert.match(html, /自动同步参数/);
assert.match(html, /计算影响/);
assert.match(html, /中径/);
assert.match(html, /外径/);
assert.match(html, /内径/);
assert.match(html, /旋绕比/);
assert.doesNotMatch(html, />spring_index</);
assert.doesNotMatch(html, /D\/d/);
assert.match(html, /应用整个方案/);
assert.match(html, /已有生图版本不会覆盖/);

const technicalHtml = context.renderParameterChangeProposalHtml({
  ...proposal,
  direct_changes: [],
  synchronized_changes: [],
  derived_changes: [],
  technical_requirement_changes: [
    {
      operation: "add",
      requirement_id: "techreq-new",
      before: null,
      after: { requirement_id: "techreq-new", type: "surface", content: "表面镀锌。", need_human_review: false },
    },
    {
      operation: "update",
      requirement_id: "techreq-salt",
      before: { requirement_id: "techreq-salt", type: "salt_spray", content: "盐雾试验72小时。", need_human_review: false },
      after: { requirement_id: "techreq-salt", type: "salt_spray", content: "盐雾试验96小时。", need_human_review: false },
    },
    {
      operation: "delete",
      requirement_id: "techreq-old",
      before: { requirement_id: "techreq-old", type: "other", content: "旧技术要求。", need_human_review: false },
      after: null,
    },
  ],
}, 2);
assert.match(technicalHtml, /技术要求修改方案 V2/);
assert.match(technicalHtml, /新增·表面处理/);
assert.match(technicalHtml, /表面镀锌/);
assert.match(technicalHtml, /盐雾试验72小时。 → 盐雾试验：盐雾试验96小时。/);
assert.match(technicalHtml, /删除·其他要求/);
assert.match(technicalHtml, /SolidWorks参数包将变化/);

const turn = { change_proposal: { ...proposal, status: "ready" } };
context.state.review.parameter_change_proposals[0] = { ...proposal, status: "applied" };
assert.equal(context.currentParameterChangeProposal(turn).status, "applied", "registry state must override an old turn snapshot");

context.state.review.parameter_change_proposals[0] = { ...proposal, version: 3, status: "ready" };
assert.equal(context.currentParameterChangeProposal(turn).status, "stale", "an older turn version must never apply");

const blockedHtml = context.renderParameterChangeProposalHtml({
  ...proposal,
  status: "blocked",
  blocking_issues: [{ message: "直径关系冲突" }],
}, 1);
assert.match(blockedHtml, /直径关系冲突/);
assert.match(blockedHtml, /data-role="apply-parameter-change-proposal" disabled/);

console.log("parameter change proposal UI tests passed");
