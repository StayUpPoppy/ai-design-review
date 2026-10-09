import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../frontend/technical-requirement-recovery.js", import.meta.url), "utf8");
const makeNote = (id, order = 9) => ({ requirement_id: id, recognition_key: `key-${id}`, source_order: order,
  original_number: String(order), page: 1, type: "process", content: `工艺正文 ${id}`, original_content: `Original ${id}`, need_human_review: false });
function harness() {
  let current = { technical_requirements: [{ requirement_id: "manual", content: "人工修改的工艺", type: "process", need_human_review: false }] };
  let jobId = "test", revision = 3, serial = 0, canOperate = true;
  let saveCount = 0, response = { job_id: "test", based_on_revision: 3, items: [{ status: "available", reason: "原始记录", requirement: makeNote("nine") },
    { status: "possible_existing", reason: "可能已存在", requirement: makeNote("ten", 10) }], order_hints: [] };
  const audit = [];
  const context = { window: {}, structuredClone, console };
  vm.createContext(context); vm.runInContext(source, context);
  const service = context.window.TechnicalRequirementRecovery;
  const hooks = { getReview: () => current, getJobId: () => jobId, getRevision: () => revision, getEditSerial: () => serial,
    canOperate: () => canOperate, save: async () => { saveCount++; return true; },
    fetch: async (_url, request) => { assert.equal(JSON.parse(request.body).expected_revision, revision); return { ok: true, json: async () => response }; },
    audit: (event) => { audit.push(event); serial++; }, changed: () => {}, update: () => {}, typeLabel: () => "工艺要求",
    escape: (text) => String(text ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;") };
  service.configure(hooks);
  return { service, hooks, audit, get review() { return current; }, set review(value) { current = value; },
    set serial(value) { serial = value; }, set jobId(value) { jobId = value; }, set canOperate(value) { canOperate = value; },
    set response(value) { response = value; }, get saveCount() { return saveCount; } };
}

const base = harness();
const baseline = structuredClone(base.review);
assert.equal(await base.service.preview(), true);
assert.deepEqual(base.review, baseline, "preview is non-mutating");
assert.equal(base.service.getState(base.review).selected.size, 1, "possible existing notes are not preselected");
assert.match(base.service.render(base.review), /查看原文与依据/);
assert.equal(await base.service.apply(), true);
assert.equal(base.review.technical_requirements.length, 2);
assert.equal(base.review.technical_requirements[1].need_human_review, true);
assert.equal(base.review.technical_requirements[0].content, "人工修改的工艺");
assert.equal(base.review.technical_requirements[0].need_human_review, false);
assert.equal(base.audit[0].event_type, "technical_requirement_recovered");
assert.equal(await base.service.apply(), false, "repeat click cannot duplicate additions");

const stale = harness();
await stale.service.preview(); stale.serial = 1;
assert.equal(await stale.service.apply(), false);
assert.equal(stale.review.technical_requirements.length, 1);
assert.match(stale.service.render(stale.review), /重新预览/);

const failure = harness();
await failure.service.preview();
failure.hooks.save = async () => false;
assert.equal(await failure.service.apply(), false);
assert.equal(failure.review.technical_requirements.length, 2, "save failure retains local additions");
assert.match(failure.service.render(failure.review), /重试保存/);
failure.hooks.save = async () => true;
assert.equal(await failure.service.retrySave(), true);
assert.equal(failure.review.technical_requirements.length, 2);
assert.equal(failure.audit.length, 1, "retry does not add or audit again");

const slow = harness();
let resolveResponse;
slow.hooks.fetch = async () => new Promise((resolve) => { resolveResponse = resolve; });
const pending = slow.service.preview();
await new Promise(setImmediate);
slow.serial = 1;
resolveResponse({ ok: true, json: async () => ({ job_id: "test", based_on_revision: 3, items: [] }) });
assert.equal(await pending, false);
assert.equal(slow.review.technical_requirements.length, 1);

const switched = harness();
let resolveSwitch;
switched.hooks.fetch = async () => new Promise((resolve) => { resolveSwitch = resolve; });
const switchPending = switched.service.preview();
await new Promise(setImmediate);
switched.review = { technical_requirements: [] }; switched.jobId = "another";
resolveSwitch({ ok: true, json: async () => ({ job_id: "test", based_on_revision: 3, items: [] }) });
assert.equal(await switchPending, false);
assert.equal(switched.review.technical_requirements.length, 0);

const blocked = harness(); blocked.canOperate = false;
assert.equal(await blocked.service.preview(), false);
assert.equal(blocked.saveCount, 0, "preview must not save unconfirmed drafts");

const escaped = harness();
escaped.response = { job_id: "test", based_on_revision: 3, items: [{ status: "available", reason: "<script>bad()</script>",
  requirement: { ...makeNote("safe"), content: '<img src=x onerror="bad()">' } }] };
await escaped.service.preview();
assert.doesNotMatch(escaped.service.render(escaped.review), /<img|<script>/);
console.log("PASS: recovery UI preview, pending confirmation, one-save retry, stale responses, order changes and escaping");
