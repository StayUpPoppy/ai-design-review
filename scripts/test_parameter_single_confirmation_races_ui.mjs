import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");

function extract(start, end) {
  const first = appSource.indexOf(start);
  const last = appSource.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `Cannot extract ${start}`);
  return appSource.slice(first, last);
}

async function testStaleStandardizationCannotUndoConfirmation() {
  const review = {
    spring_parameters: { free_length: { value: 50, need_human_review: false, source: ["human_confirmed"] } },
    standardization_results: [],
  };
  let finishRequest;
  let replaced = 0;
  const context = {
    state: {
      review,
      lastJob: { job_id: "review-1", review_revision: 1 },
      reviewEditSerial: 1,
      pendingReviewAuditEvents: [],
      busy: false,
      standardizationInFlight: false,
      standardizationChatBusy: false,
      imageUrl: null,
    },
    clearTimeout() {},
    normalizeAccuracyGrade() { return ""; },
    activateReviewContext() {},
    async flushReviewPersistence() { return true; },
    normalizeReview: structuredClone,
    structuredClone,
    captureReviewScrollState() { return {}; },
    restoreReviewScrollState() {},
    setBusy(value) { context.state.busy = value; },
    apiFetch() { return new Promise((resolve) => { finishRequest = resolve; }); },
    setReview() { replaced += 1; },
    updateLatestReviewMessage() {},
    refreshReviewSurfaces() {},
    scheduleReviewPersistence() {},
    getReviewContext() { return null; },
    appendAssistantText() {},
    loadGenerationState() {},
  };
  vm.createContext(context);
  vm.runInContext(extract("async function runStandardization(", "async function runStandardizationChat("), context);
  const running = context.runStandardization(null, { silent: true });
  for (let attempt = 0; attempt < 5 && !finishRequest; attempt += 1) await Promise.resolve();
  assert.equal(typeof finishRequest, "function");
  assert.equal(context.state.standardizationInFlight, true);
  context.state.review.spring_parameters.free_length.value = 55;
  context.state.reviewEditSerial += 1;
  finishRequest({
    ok: true,
    async json() {
      return { job_id: "review-1", review_revision: 2, review: {
        spring_parameters: { free_length: { value: 50, need_human_review: true } },
        standardization_results: [],
      } };
    },
  });
  assert.equal(await running, false);
  assert.equal(context.state.review.spring_parameters.free_length.value, 55);
  assert.equal(context.state.review.spring_parameters.free_length.need_human_review, false);
  assert.equal(context.state.lastJob.review_revision, 2);
  assert.equal(replaced, 0);
}

async function testSaveAcknowledgementDoesNotReplaceNewerInput() {
  let finishRequest;
  const confirmation = { client_event_id: "confirm-1", target_field: "free_length" };
  const context = {
    state: {
      review: {
        spring_parameters: { free_length: { value: 50, need_human_review: false } },
        change_history: [{ ...confirmation, sync_status: "pending" }],
      },
      lastJob: { job_id: "review-1", review_revision: 1 },
      pendingReviewAuditEvents: [confirmation],
      reviewPersistenceInFlightEvents: [],
      reviewPersistenceFailedFields: {},
      reviewPersistenceSaving: false,
      reviewPersistencePromise: null,
      standardizationInFlight: false,
      generationJobs: [],
    },
    clearTimeout() {},
    setTimeout() { return 1; },
    normalizeReview: structuredClone,
    structuredClone,
    apiFetch() { return new Promise((resolve) => { finishRequest = resolve; }); },
    refreshParameterPersistenceControls() {},
    refreshReviewChangeHistory() {},
    loadGenerationState() {},
  };
  vm.createContext(context);
  vm.runInContext(extract("function scheduleReviewPersistence()", "function refreshReviewChangeHistory()"), context);
  const saving = context.persistReviewChanges();
  assert.equal(context.state.reviewPersistenceInFlightEvents.length, 1);
  context.state.review.spring_parameters.free_length.value = 55;
  context.state.pendingReviewAuditEvents.push({ client_event_id: "edit-2", target_field: "free_length" });
  finishRequest({ ok: true, async json() { return { review_revision: 2, events: [{ client_event_id: "confirm-1" }] }; } });
  assert.equal(await saving, true);
  assert.equal(context.state.review.spring_parameters.free_length.value, 55);
  assert.equal(context.state.pendingReviewAuditEvents.length, 1);
  assert.equal(context.state.lastJob.review_revision, 2);

  context.state.pendingReviewAuditEvents = [confirmation];
  context.apiFetch = async () => { throw new Error("network offline"); };
  assert.equal(await context.persistReviewChanges(), false);
  assert.equal(context.state.pendingReviewAuditEvents.length, 1);
  assert.equal(context.state.reviewPersistenceFailedFields.free_length, "network offline");
}

async function testRevisionConflictKeepsUnrelatedServerChanges() {
  const event = {
    client_event_id: "edit-1",
    target_field: "free_length",
    before_state: { value: 45, need_human_review: true },
  };
  const local = {
    spring_parameters: {
      free_length: { value: 50, need_human_review: false },
      outer_diameter: { value: 30, need_human_review: false },
    },
    manual_confirmations: { free_length: { confirmed: true, value: 50 } },
    change_history: [event],
    standardization_results: [],
  };
  const server = {
    review_revision: 2,
    spring_parameters: {
      free_length: { value: 45, need_human_review: true },
      outer_diameter: { value: 32, need_human_review: false },
    },
    manual_confirmations: {},
    change_history: [],
    standardization_results: [],
  };
  const context = {
    state: {
      review: local,
      lastJob: { job_id: "review-1", review_revision: 1 },
      pendingReviewAuditEvents: [],
      reviewDraftFields: new Set(),
      generationReadiness: null,
      imageUrl: null,
    },
    normalizeReview: structuredClone,
    structuredClone,
    apiFetch: async () => ({ ok: true, async json() { return structuredClone(server); } }),
    setReview(review) { context.state.review = review; },
    refreshReviewSurfaces() {},
    formatTolerance() { return ""; },
    escapeHtml: String,
    targetFieldLabel: String,
  };
  vm.createContext(context);
  vm.runInContext(extract("function parameterConflictFingerprint", "function refreshReviewChangeHistory()"), context);
  const resolved = await context.reconcileParameterRevisionConflict("review-1", [event]);
  assert.equal(resolved.revision, 2);
  assert.equal(resolved.review.spring_parameters.free_length.value, 50);
  assert.equal(resolved.review.spring_parameters.outer_diameter.value, 32);
  assert.equal(resolved.events.length, 1);

  server.spring_parameters.free_length.value = 48;
  context.state.review = local;
  context.state.lastJob.review_revision = 1;
  let comparedValues = "";
  const listeners = {};
  const dialog = {
    setAttribute() {},
    set innerHTML(value) { comparedValues = value; },
    querySelector(selector) {
      return { addEventListener(_type, listener) { listeners[selector] = listener; } };
    },
    addEventListener() {},
    showModal() { queueMicrotask(() => listeners['[data-choice="server"]']()); },
    close() {},
    remove() {},
  };
  context.document = { createElement() { return dialog; }, body: { appendChild() {} } };
  const serverChoice = await context.reconcileParameterRevisionConflict("review-1", [event]);
  assert.match(comparedValues, /48/);
  assert.match(comparedValues, /50/);
  assert.equal(serverChoice.events.length, 0);
  assert.equal(serverChoice.review.spring_parameters.free_length.value, 48);
}

function testFreeEditingAndToleranceDraft() {
  const context = {
    supplementInputMode(field) { return ["free_length", "solid_height", "total_coils"].includes(field) ? "decimal" : "text"; },
    isFiniteReviewNumber(value) { return value != null && value !== "" && Number.isFinite(Number(value)); },
    generationContractValue() { return "right"; },
  };
  vm.createContext(context);
  vm.runInContext(extract("function parameterConfirmationInvalidReason", "function isFiniteReviewNumber"), context);
  vm.runInContext(extract("function formatTolerance(", "function applyLoadPointTolerance("), context);
  assert.equal(context.parameterConfirmationInvalidReason("free_length", { value: -5 }), "");
  assert.equal(context.parameterConfirmationInvalidReason("free_length", { value: "abc" }), "请输入有效数字");
  const param = { value: 50, tolerance_upper: 1.5, tolerance_lower: -1.5 };
  assert.equal(context.applyTolerance(param, "±"), false);
  assert.equal(param.tolerance_input_draft, "±");
  assert.equal(context.formatTolerance(param), "±");
  assert.match(context.parameterConfirmationInvalidReason("free_length", param), /公差格式/);
  assert.equal(context.applyTolerance(param, "±1.5"), true);
  assert.equal(param.tolerance_input_draft, undefined);
  assert.equal(param.tolerance_upper, 1.5);
  assert.equal(param.tolerance_lower, -1.5);
}

await testStaleStandardizationCannotUndoConfirmation();
await testSaveAcknowledgementDoesNotReplaceNewerInput();
await testRevisionConflictKeepsUnrelatedServerChanges();
testFreeEditingAndToleranceDraft();
console.log("parameter single-confirmation race UI tests passed");
