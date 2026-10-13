import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { translationTestHelpers } from "./translation_ui_test_support.mjs";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const stylesSource = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");

const helperStart = appSource.indexOf("function createTechnicalRequirementId");
const helperEnd = appSource.indexOf("function markParameterChangeProposalsStale", helperStart);
assert.notEqual(helperStart, -1, "technical requirement helpers must exist");
assert.notEqual(helperEnd, -1, "technical requirement helper block must be complete");

let sequence = 0;
const context = {
  structuredClone,
  crypto: { randomUUID: () => `uuid-${++sequence}` },
  state: { review: null },
  TECH_REQUIREMENT_TYPES: [
    "surface", "hardness", "heat_treatment", "salt_spray",
    "environmental", "lifetime", "process", "other",
  ],
  TECH_LABELS: {
    surface: "表面处理",
    hardness: "硬度要求",
    heat_treatment: "热处理",
    salt_spray: "盐雾试验",
    environmental: "环保要求",
    lifetime: "寿命要求",
    process: "工艺要求",
    other: "其他要求",
  },
  escapeHtml: (value) => String(value ?? ""),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(new URL("../frontend/technical-requirement-equivalence.js", import.meta.url), "utf8"), context);
translationTestHelpers(context);
vm.runInContext(appSource.slice(helperStart, helperEnd), context);

const review = {
  technical_requirements: [
    { type: "surface", content: "表面镀锌。", need_human_review: false },
    { type: "other", content: "去除毛刺。", need_human_review: true },
  ],
  manual_confirmations: { technical_0: { confirmed: true, value: "表面镀锌。" } },
};
context.ensureTechnicalRequirementIds(review);
assert.match(review.technical_requirements[0].requirement_id, /^techreq_/);
assert.notEqual(review.technical_requirements[0].requirement_id, review.technical_requirements[1].requirement_id);
const stableKey = context.technicalRequirementConfirmationKey(review.technical_requirements[0], 0);
assert.equal(review.manual_confirmations[stableKey].confirmed, true);
assert.deepEqual(JSON.parse(JSON.stringify(context.technicalRequirementCounts(review))), {
  total: 2,
  confirmed: 1,
  pending: 1,
  original: 2,
  exportable: 1,
});
assert.equal(context.isDuplicateTechnicalRequirement(review, {
  type: "surface",
  content: "  表面镀锌。  ",
}), true);
assert.match(context.technicalRequirementTypeOptionsHtml("salt_spray"), /value="salt_spray" selected/);

// Render grouping does not grant confirmation or erase either source record.
const grouped = { technical_requirements: [
  { requirement_id: "pending", type: "heat_treatment", content: "300 °C/20 min", need_human_review: true },
  { requirement_id: "other", type: "salt_spray", content: "720h无红锈", need_human_review: false },
  { requirement_id: "confirmed", type: "heat_treatment", content: "热处理：300°C/20min", need_human_review: false },
] };
const beforeGrouping = JSON.stringify(grouped);
const groups = context.technicalRequirementGroups(grouped);
assert.equal(groups.length, 2);
assert.equal(groups[1].representative.item.requirement_id, "confirmed", "display order follows the first exportable source, as in SW");
assert.equal(groups[1].confirmed, false);
assert.equal(context.technicalRequirementCounts(grouped).exportable, 2);
assert.equal(context.technicalRequirementCounts(grouped).pending, 1);
assert.equal(JSON.stringify(grouped), beforeGrouping);
assert.equal(context.technicalRequirementGroups({ technical_requirements: [{content:""}, {content:""}] }).length, 2);
context.sourceValues = (value) => (Array.isArray(value) ? value : [value]).filter(Boolean);
vm.runInContext(appSource.slice(appSource.indexOf("function confirmationItemWasEdited"), appSource.indexOf("function renderDerivedParametersHtml")), context);
assert.equal(context.technicalGroupControl(groups[1].members, grouped).label, "确认其余记录");
const failed = { ...grouped.technical_requirements[0], translation_status: "failed", translation_input_snapshot: { content: "300 °C/20 min", type: "heat_treatment" } };
assert.equal(context.technicalGroupControl([{ item: failed, index: 0 }, groups[1].members[1]], grouped).disabled, true, "a failed hidden source blocks whole-group confirmation");
assert.equal(context.technicalGroupControl([{ item: { type: "other", content: "", need_human_review: true }, index: 0 }], grouped).disabled, true);
assert.equal(context.technicalGroupControl([{ item: { type: "other", content: "", need_human_review: false }, index: 0 }], grouped).state, "invalid", "an old confirmation flag cannot validate an empty requirement");
assert.equal(grouped.technical_requirements[0].need_human_review, true);

const editorStart = appSource.indexOf("const createRequirementForm = root.querySelector");
const editorEnd = appSource.indexOf("function applyStandardizationResult", editorStart);
const editorSource = appSource.slice(appSource.indexOf("function restoreTechnicalRequirementGroup"), appSource.indexOf("function technicalRequirementsAreDuplicates")) + appSource.slice(editorStart, editorEnd);
assert.match(appSource, /data-action="show-technical-requirement-create"/);
assert.match(appSource, /data-role="new-technical-type"/);
assert.match(appSource, /data-role="delete-technical-requirement"/);
assert.match(appSource, /data-action="undo-technical-requirement-delete"/);
assert.match(appSource, /将写入二维图纸/);
assert.doesNotMatch(appSource, /按别名标准化/);
assert.doesNotMatch(appSource, /data-role="standard-candidate"/);
for (const eventType of [
  "technical_requirement_added",
  "technical_requirement_updated",
  "technical_requirement_deleted",
  "technical_requirement_restored",
  "technical_requirement_confirmed",
]) {
  assert.match(editorSource, new RegExp(eventType));
}
assert.doesNotMatch(editorSource, /window\.confirm/, "delete must be immediate and offer one undo instead of a modal");

assert.match(stylesSource, /\.requirement-actions\s*\{[^}]*grid-column:\s*2/s);
assert.match(stylesSource, /@media[^]*\.requirement-actions\s*\{[^}]*grid-column:\s*1/s);

const rollbackStart = appSource.indexOf("function technicalRequirementsAfterProposalChanges");
const rollbackEnd = appSource.indexOf("function standardizationChatValuesEqual", rollbackStart);
const rollbackContext = {
  structuredClone,
  normalizeTechnicalRequirementType: (value) => String(value || "other"),
};
vm.createContext(rollbackContext);
vm.runInContext(appSource.slice(rollbackStart, rollbackEnd), rollbackContext);
const baseline = [
  { requirement_id: "a", type: "other", content: "A", need_human_review: false },
  { requirement_id: "b", type: "salt_spray", content: "72小时", need_human_review: false },
];
const after = rollbackContext.technicalRequirementsAfterProposalChanges(baseline, [
  { operation: "update", requirement_id: "b", after: { type: "salt_spray", content: "96小时", need_human_review: false } },
  { operation: "delete", requirement_id: "a", after: null },
  { operation: "add", requirement_id: "c", after: { type: "surface", content: "镀锌", need_human_review: false } },
]);
assert.deepEqual(
  JSON.parse(JSON.stringify(rollbackContext.technicalRequirementRollbackState(after))),
  [
    { requirement_id: "b", type: "salt_spray", content: "96小时", need_human_review: false },
    { requirement_id: "c", type: "surface", content: "镀锌", need_human_review: false },
  ],
);

console.log("technical requirement UI tests passed");
