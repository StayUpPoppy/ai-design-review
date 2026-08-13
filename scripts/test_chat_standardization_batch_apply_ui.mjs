import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = appSource.indexOf("function currentStandardizationBatchTargetValue");
const end = appSource.indexOf("function normalizeAccuracyGrade", start);
assert.notEqual(start, -1);
assert.notEqual(end, -1);

const batch = {
  batch_id: "standardization_batch_apply",
  status: "ready",
  review_revision: 4,
  skipped_count: 1,
  items: [{
    result_index: 0,
    target_field: "free_length",
    rule_id: "FREE",
    before: { exists: true, value: 45, tolerance_upper: 1, tolerance_lower: -1, unit: "mm", confirmed: true },
    after: { exists: true, value: 45, tolerance_upper: 0.6, tolerance_lower: -0.6, unit: "mm", confirmed: true },
  }],
};
const review = {
  spring_parameters: {
    free_length: { value: 45, unit: "mm", tolerance_upper: 1, tolerance_lower: -1, need_human_review: false },
    load_points: [],
  },
  standardization_results: [{
    target_field: "free_length",
    rule_id: "FREE",
    status: "suggested",
    suggested_value: 45,
    suggested_tolerance_upper: 0.6,
    suggested_tolerance_lower: -0.6,
    unit: "mm",
  }],
  standardization_chat: [{ standardization_batch: batch }],
  change_history: [],
};

let saveCount = 0;
let applyCount = 0;
let lastMessage = "";
const context = {
  structuredClone,
  state: {
    review,
    lastJob: { job_id: "review-1", review_revision: 4 },
    pendingReviewAuditEvents: [],
    busy: false,
    standardizationChatBusy: false,
    imageUrl: "",
  },
  parseLoadPointTarget: () => null,
  activateReviewContext: () => {},
  setBusy: (value) => { context.state.busy = value; },
  flushReviewPersistence: async () => { saveCount += context.state.pendingReviewAuditEvents.length ? 1 : 0; context.state.pendingReviewAuditEvents = []; },
  standardizationBatchDisplayStatus: (value) => value.status,
  standardizationBatchPlan: () => ({ items: [{ index: 0, item: context.state.review.standardization_results[0] }], conflicts: [] }),
  applyStandardizationResults: (items) => {
    applyCount += 1;
    context.state.review.spring_parameters.free_length.tolerance_upper = 0.6;
    context.state.review.spring_parameters.free_length.tolerance_lower = -0.6;
    items[0].status = "human_confirmed";
    return { count: 1, history_id: "history-1" };
  },
  queueReviewAuditEvent: (event) => {
    const entry = { client_event_id: "event-1", ...event };
    context.state.pendingReviewAuditEvents.push(entry);
    context.state.review.change_history.unshift(entry);
    return entry;
  },
  refreshParameterReasonableness: async () => {},
  loadGenerationState: async () => {},
  updateLatestReviewMessage: (message) => { lastMessage = message; },
  setReview: (value) => { context.state.review = value; },
  normalizeReview: (value) => value,
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

const applied = await context.applyChatStandardizationBatch(batch, "message-1");
assert.equal(applied, true);
assert.equal(applyCount, 1);
assert.equal(saveCount, 1);
assert.equal(context.state.review.spring_parameters.free_length.tolerance_upper, 0.6);
assert.equal(context.state.review.standardization_chat[0].standardization_batch.status, "applied");
assert.equal(context.state.review.standardization_chat[0].standardization_batch.applied_count, 1);
assert.match(lastMessage, /已应用 1 项/);

const repeated = await context.applyChatStandardizationBatch(batch, "message-1");
assert.equal(repeated, false);
assert.equal(applyCount, 1);

const conflictBatch = structuredClone(batch);
conflictBatch.batch_id = "standardization_batch_conflict";
conflictBatch.status = "ready";
conflictBatch.applied_count = 0;
const conflictReview = structuredClone(review);
conflictReview.spring_parameters.free_length.tolerance_upper = 1;
conflictReview.spring_parameters.free_length.tolerance_lower = -1;
conflictReview.standardization_results[0].status = "suggested";
conflictReview.standardization_chat = [{ standardization_batch: conflictBatch }];
conflictReview.change_history = [];
context.state.review = conflictReview;
context.state.lastJob.review_revision = 4;
context.state.pendingReviewAuditEvents = [];
let flushCalls = 0;
context.flushReviewPersistence = async () => {
  flushCalls += 1;
  if (flushCalls === 2) throw new Error("当前审查数据已被其他操作更新，请刷新后重试。");
};
const conflicted = await context.applyChatStandardizationBatch(conflictBatch, "message-1");
assert.equal(conflicted, false);
assert.equal(context.state.review.spring_parameters.free_length.tolerance_upper, 1);
assert.equal(context.state.review.standardization_chat[0].standardization_batch.status, "stale");
assert.match(lastMessage, /其他操作更新/);

console.log("chat standardization batch apply UI tests passed");
