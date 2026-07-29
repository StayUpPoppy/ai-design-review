import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = appSource.indexOf("function clearAccuracyGradeUpdateTimer");
const end = appSource.indexOf("async function refreshParameterReasonableness", start);

assert.notEqual(start, -1, "accuracy grade feedback helpers must exist");
assert.notEqual(end, -1, "accuracy grade feedback helper block must be complete");

const timers = [];
const runCalls = [];
const feedbackRenders = [];
const context = {
  state: {
    review: {
      derived_parameters_stale: true,
      standardization_results: [{ status: "stale" }],
    },
    busy: false,
    automaticStandardizationTimer: null,
    accuracyGradeUpdate: { phase: "idle", grade: "", timer: null },
  },
  clearTimeout: (timer) => {
    if (timer) timer.cleared = true;
  },
  setTimeout: (callback, delay) => {
    const timer = { callback, delay, cleared: false };
    timers.push(timer);
    return timer;
  },
  updateAccuracyGradeFeedbackUi: () => {
    feedbackRenders.push({ ...context.state.accuracyGradeUpdate });
  },
  runStandardization: (...args) => runCalls.push(args),
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

assert.equal(context.scheduleAutomaticStandardization("review-1", {
  source: "accuracy_grade",
  grade: "1级",
}), true);
assert.equal(context.state.accuracyGradeUpdate.phase, "pending");
assert.equal(context.state.accuracyGradeUpdate.grade, "1级");

const pendingTimer = timers.find((timer) => timer.delay === 900);
assert.ok(pendingTimer, "accuracy grade update should keep the 900ms debounce");
pendingTimer.callback();
assert.equal(runCalls.length, 1);
assert.deepEqual(JSON.parse(JSON.stringify(runCalls[0][1])), {
  automatic: true,
  silent: true,
  accuracy_grade_update: { grade: "1级" },
});

context.state.review = { derived_parameters_stale: false, standardization_results: [] };
assert.equal(context.scheduleAutomaticStandardization("review-2", {
  source: "accuracy_grade",
  grade: "3级",
}), false);
assert.equal(context.state.accuracyGradeUpdate.phase, "ready");
assert.equal(context.state.accuracyGradeUpdate.grade, "3级");

context.setAccuracyGradeUpdate("success", "2级");
assert.equal(context.state.accuracyGradeUpdate.phase, "success");
assert.equal(timers.some((timer) => timer.delay === 3000), false, "success feedback should remain visible");
assert.equal(context.state.accuracyGradeUpdate.phase, "success");

context.setAccuracyGradeUpdate("error", "1级");
assert.equal(context.state.accuracyGradeUpdate.phase, "error");
assert.match(context.accuracyGradeUpdateMessage("error", "1级"), /1/);

context.setAccuracyGradeUpdate();
context.state.review = {
  derived_parameters_stale: true,
  standardization_results: [{ status: "stale" }],
};
assert.equal(context.scheduleAutomaticStandardization("review-3"), true);
assert.equal(context.state.accuracyGradeUpdate.phase, "idle");
assert.ok(feedbackRenders.length > 0);

console.log("accuracy grade feedback UI test passed");
