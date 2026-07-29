import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = appSource.indexOf("async function runStandardization(");
const end = appSource.indexOf("async function runStandardizationChat(", start);

assert.notEqual(start, -1, "runStandardization must exist");
assert.notEqual(end, -1, "runStandardization must end before chat handler");

function reviewWithGrade(grade = "2级") {
  return {
    spring_parameters: {
      accuracy_grade: {
        value: grade,
        source: ["company_default"],
        need_human_review: true,
      },
    },
    standardization_results: [],
  };
}

function createContext({ responseOk = true } = {}) {
  const requests = [];
  const audits = [];
  const statuses = [];
  const initialReview = reviewWithGrade();
  const context = {
    state: {
      review: initialReview,
      lastJob: { job_id: "review-1", review_revision: 5 },
      pendingAccuracyGrade: "1级",
      accuracyGradeUpdate: { phase: "ready", grade: "1级", operation: "accuracy", timer: null },
      automaticStandardizationTimer: null,
      busy: false,
      imageUrl: "/drawing.png",
      reviewContexts: {},
    },
    structuredClone,
    clearTimeout: () => {},
    normalizeAccuracyGrade: (value) => String(value || "").match(/[123]级/)?.[0] || "",
    activateReviewContext: () => null,
    setAccuracyGradeUpdate: (phase, grade, operation = "") => {
      context.state.accuracyGradeUpdate = { ...context.state.accuracyGradeUpdate, phase, grade, operation };
      statuses.push({ phase, grade, operation });
    },
    flushReviewPersistence: async () => {},
    normalizeReview: (review) => structuredClone(review),
    prepareAccuracyGradeCommit: (review, grade) => {
      const param = review.spring_parameters.accuracy_grade;
      const beforeState = { value: param.value };
      param.value = grade;
      param.source = ["human_selected"];
      param.need_human_review = false;
      return { grade, beforeState };
    },
    captureReviewScrollState: () => ({}),
    restoreReviewScrollState: () => {},
    setBusy: (busy) => { context.state.busy = busy; },
    apiUrl: (path) => path,
    appendAssistantText: () => "thinking-1",
    removeMessage: () => {},
    fetch: async (_url, options) => {
      const payload = JSON.parse(options.body);
      requests.push(payload);
      if (!responseOk) {
        return { ok: false, json: async () => ({ detail: "request failed" }) };
      }
      return {
        ok: true,
        json: async () => ({
          job_id: "review-1",
          review_revision: 6,
          warnings: [],
          llm_standardization: null,
          review: payload.review,
        }),
      };
    },
    setReview: (review) => { context.state.review = review; },
    syncBubbleValue: () => {},
    parameterAuditState: (param) => ({ value: param?.value ?? null }),
    queueReviewAuditEvent: (event) => audits.push(event),
    getReviewContext: () => null,
    updateLatestReviewMessage: () => {},
    appendAssistantText: () => "thinking-1",
    replaceMessage: () => {},
  };
  vm.createContext(context);
  vm.runInContext(appSource.slice(start, end), context);
  return { context, requests, audits, statuses, initialReview };
}

{
  const { context, requests, audits, statuses, initialReview } = createContext();
  const completed = await context.runStandardization(undefined, {
    workbench_feedback: true,
    pending_accuracy_grade: "1级",
  });

  assert.equal(completed, true);
  assert.equal(initialReview.spring_parameters.accuracy_grade.value, "2级");
  assert.equal(requests.length, 1);
  assert.equal(requests[0].review.spring_parameters.accuracy_grade.value, "1级");
  assert.deepEqual(Array.from(requests[0].review.spring_parameters.accuracy_grade.source), ["human_selected"]);
  assert.equal(requests[0].use_llm_standardization, true);
  assert.equal(context.state.review.spring_parameters.accuracy_grade.value, "1级");
  assert.equal(context.state.pendingAccuracyGrade, "");
  assert.equal(audits.length, 1);
  assert.equal(audits[0].event_type, "accuracy_grade_selected");
  assert.deepEqual(statuses.at(-1), { phase: "success", grade: "1级", operation: "accuracy" });
}

{
  const { context, requests, audits, statuses } = createContext({ responseOk: false });
  const completed = await context.runStandardization(undefined, {
    workbench_feedback: true,
    pending_accuracy_grade: "1级",
  });

  assert.equal(completed, false);
  assert.equal(requests.length, 1);
  assert.equal(context.state.review.spring_parameters.accuracy_grade.value, "2级");
  assert.equal(context.state.pendingAccuracyGrade, "1级");
  assert.equal(audits.length, 0);
  assert.deepEqual(statuses.at(-1), { phase: "error", grade: "1级", operation: "accuracy" });
}

console.log("pending accuracy standardization UI test passed");
