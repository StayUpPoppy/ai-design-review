import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = { window: {}, structuredClone, console, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(fs.readFileSync(new URL("../frontend/technical-requirement-translation.js", import.meta.url), "utf8"), context);
const service = context.window.TechnicalRequirementTranslation;
const fixtures = JSON.parse(fs.readFileSync(new URL("./fixtures/technical_translation_classification.json", import.meta.url), "utf8"));
for (const text of fixtures.not_required) assert.equal(service.needsTranslation(text), false, text);
for (const text of fixtures.requires_translation) assert.equal(service.needsTranslation(text), true, text);
for (const foreign of ["Shear modulus G*=80000 MPa", "Модуль сдвига G*=80000 МПа", "涂层 Coating Zn15.hr GOST9306-85", "ばねの表面を研磨する", "تلميع سطح النابض"]) assert.equal(service.needsTranslation(foreign), true, foreign);
for (const neutral of ["去除毛刺", "G*=80000 MPa", "SUS304", "60Si2Mn", "12Х18Н10Т", "Ц15.хр", "B-1-1.5", "INCONEL 750", "Ra 12.5μm", "300°C+10°C/20min+1min", "按 GB/T 1239.2-2009 检验"]) assert.equal(service.needsTranslation(neutral), false, neutral);
let review, job, calls, saves, events, hold, responseFailure, saveFailure, responseMode, responseStatus;
function setup(content = "Shear modulus G*=80000 MPa") {
  review = { technical_requirements: [{ requirement_id: "note-1", type: "process", content, need_human_review: false, raw_content: "术语原文" }], spring_parameters: { free_length: { value: 50, need_human_review: false } }, manual_confirmations: { "technical_requirement_note-1": { confirmed: true }, technical_0: { confirmed: true } } };
  job = "one"; calls = 0; saves = 0; events = []; hold = null; responseFailure = false; saveFailure = false; responseMode = "translated"; responseStatus = 200;
  service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit: (event) => events.push(event),
    save: async () => { saves++; return !saveFailure; }, fetch: async (_url, options) => {
      calls++;
      if (hold) await hold;
      if (responseFailure) throw new Error("offline");
      if (responseStatus !== 200) return { ok: false, json: async () => ({ detail: "技术要求已变化，请保存最新内容后重试翻译。" }) };
      const rows = JSON.parse(options.body).requirements;
      return { ok: true, json: async () => ({ requirements: rows.map((row) => ({ ...row,
        content: responseMode === "not_required" ? row.source_snapshot.content : responseMode === "invalid_recovery" ? "未注尺寸以2D为准" : "剪切模量 G*=80000 MPa", original_content: row.source_snapshot.content,
        source_language: "en", translation_status: responseMode === "translated" ? "translated" : "not_required", translation_error: "", translation_source: "qwen_text:test", translation_input_snapshot: row.source_snapshot })) }) };
    } });
}
setup();
await service.run();
assert.equal(calls, 1);
assert.equal(review.technical_requirements[0].content, "剪切模量 G*=80000 MPa");
assert.equal(review.technical_requirements[0].need_human_review, true);
assert.equal(review.technical_requirements[0].raw_content, "术语原文");
assert.equal(review.spring_parameters.free_length.value, 50);
assert.deepEqual(Object.keys(review.manual_confirmations), []);
assert.equal(events[0].source, "machine_translation");
await service.run();
assert.equal(calls, 1, "valid Chinese must not be translated twice");
setup("去除毛刺");
await service.run();
assert.equal(calls, 0);
assert.equal(review.technical_requirements[0].need_human_review, false);
setup(); responseFailure = true;
await service.run();
assert.equal(review.technical_requirements[0].translation_status, "failed");
assert.equal(review.technical_requirements[0].need_human_review, true);
assert.equal(service.blocksExport(review.technical_requirements[0]), true);
await service.run();
assert.equal(calls, 1, "identical failure is not retried on refresh");
responseFailure = false;
await service.run("note-1");
assert.equal(calls, 2);
assert.equal(review.technical_requirements[0].translation_status, "translated");
setup();
let release;
hold = new Promise((resolve) => { release = resolve; });
let running = service.run();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(service.isPending(review, review.technical_requirements[0]), true);
review.technical_requirements[0].content = "人工新内容";
service.changed(review.technical_requirements[0]);
release(); await running;
assert.equal(review.technical_requirements[0].content, "人工新内容");
assert.equal(events.length, 0);
setup();
hold = new Promise((resolve) => { release = resolve; });
running = service.run(); await new Promise((resolve) => setTimeout(resolve, 0));
review.technical_requirements.splice(0, 1);
release(); await running;
assert.equal(review.technical_requirements.length, 0);
assert.equal(events.length, 0);
setup();
hold = new Promise((resolve) => { release = resolve; });
running = service.run(); await new Promise((resolve) => setTimeout(resolve, 0));
const previous = review;
job = "two"; review = { technical_requirements: [] };
release(); await running;
assert.equal(previous.technical_requirements[0].content, "Shear modulus G*=80000 MPa");
setup();
// Save failure after successful translation keeps the local Chinese text.
const baseSave = async () => { saves++; return saves === 1; };
service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit: (event) => events.push(event), save: baseSave,
  fetch: async (_url, options) => { calls++; const row = JSON.parse(options.body).requirements[0]; return { ok: true, json: async () => ({ requirements: [{ ...row, content: "剪切模量 G*=80000 MPa", original_content: row.source_snapshot.content, translation_status: "translated", translation_input_snapshot: row.source_snapshot }] }) }; } });
assert.equal(await service.run(), false);
assert.equal(review.technical_requirements[0].content, "剪切模量 G*=80000 MPa");
await service.run();
assert.equal(calls, 1, "retry save must not call translation again");

function setupRecovery() {
  setup("7.未注尺寸以3D为准");
  const item = review.technical_requirements[0];
  Object.assign(item, { original_content: item.content, source_language: "zh", translation_status: "failed",
    translation_error: "译文仍包含外语说明，请重试或人工填写中文。", translation_input_snapshot: service.snapshot(item),
    source: ["qwen_vision"], translation_source: "qwen_text:old", human_confirmed: true, confirmation_snapshot: { content: item.content } });
  responseMode = "not_required";
  return item;
}
let item = setupRecovery();
const beforeRecovery = structuredClone(item);
assert.equal(service.canRecover(item), true);
assert.equal(service.blocksExport(item), true);
await service.run();
assert.equal(calls, 1, "historical recovery uses the existing API once");
assert.equal(item.content, beforeRecovery.content);
assert.equal(item.original_content, beforeRecovery.original_content);
assert.equal(item.source_language, "zh");
assert.equal(item.translation_source, "qwen_text:old");
assert.deepEqual(item.source, beforeRecovery.source);
assert.equal(item.translation_status, "not_required");
assert.equal(item.translation_error, "");
assert.equal(item.need_human_review, true);
assert.equal(item.human_confirmed, false);
assert.equal(item.confirmation_snapshot, undefined);
assert.deepEqual(Object.keys(review.manual_confirmations), []);
assert.equal(events[0].event_type, "technical_requirement_translation_recovered");
assert.equal(events[0].source, "translation_validation");
assert.equal(service.blocksExport(item), false);
assert.equal(saves, 2, "recovery results use one final serial save");
await service.run();
assert.equal(calls, 1, "a recovered note is never retranslated");
setup("按2D图纸检验");
await service.run();
assert.equal(calls, 0, "new Chinese engineering notes need no translation API");

for (const change of [{ translation_error: "翻译改变了数值或公差，原文已保留，请核对后重试。" },
  { translation_error: "翻译未返回此条目或返回了重复ID，请重试。" }, { translation_input_snapshot: null },
  { original_content: "Dimensions according to 3D model" }, { original_content: "" }]) {
  item = setupRecovery(); Object.assign(item, change);
  assert.equal(service.canRecover(item), false);
  await service.run();
  await service.run("note-1");
  assert.equal(calls, 2, "uncertain failures may be revalidated locally but never cleared without evidence");
  assert.equal(item.translation_status, "failed");
}
for (const failure of ["offline", "409", "invalid_response"]) {
  item = setupRecovery();
  const originalFailure = item.translation_error;
  responseFailure = failure === "offline";
  responseStatus = failure === "409" ? 409 : 200;
  if (failure === "invalid_response") responseMode = "invalid_recovery";
  assert.equal(await service.run(), false);
  assert.equal(item.content, "7.未注尺寸以3D为准");
  assert.equal(item.translation_status, "failed");
  assert.equal(item.translation_error, originalFailure, "request failures preserve original recovery evidence");
  assert.ok(service.recoveryError(review, item));
  assert.equal(events.length, 0);
  await service.run();
  assert.equal(calls, 1, "a failed check is not automatically repeated");
  responseFailure = false; responseStatus = 200; responseMode = "not_required";
  await service.run("note-1");
  assert.equal(item.translation_status, "not_required");
  assert.equal(calls, 2, "explicit retry rechecks without rewriting the note");
}
for (const action of ["edit", "edit_back", "type", "delete", "switch"]) {
  item = setupRecovery();
  hold = new Promise((resolve) => { release = resolve; });
  running = service.run(); await new Promise((resolve) => setTimeout(resolve, 0));
  if (action === "edit") { item.content = "人工新内容"; service.changed(item); }
  if (action === "edit_back") { service.changed(item); }
  if (action === "type") { item.type = "process"; service.changed(item); }
  if (action === "delete") review.technical_requirements.splice(0, 1);
  if (action === "switch") { job = "two"; review = { technical_requirements: [] }; }
  release(); await running;
  assert.equal(item.translation_status, "failed", "stale recovery responses must be ignored");
  assert.equal(events.length, 0, action);
}
item = setupRecovery();
service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit: (event) => events.push(event),
  save: async () => { saves++; return saves === 1; }, fetch: async (_url, options) => {
    calls++; const row = JSON.parse(options.body).requirements[0];
    return { ok: true, json: async () => ({ requirements: [{ ...row, content: row.source_snapshot.content,
      translation_status: "not_required", translation_error: "", translation_input_snapshot: row.source_snapshot }] }) };
  } });
assert.equal(await service.run(), false, "failed final save must not report recovery saved");
assert.equal(item.translation_status, "not_required");
assert.equal(item.need_human_review, true);
await service.run();
assert.equal(calls, 1, "save retry keeps local recovery without another check");
setup(); responseMode = "not_required";
await service.run();
assert.equal(review.technical_requirements[0].translation_status, "failed", "a foreign note cannot trust a not_required response");
assert.equal(service.blocksExport(review.technical_requirements[0]), true);

// The existing serial-save conflict dialog must also compare technical text,
// not just numeric parameters. Unrelated server changes are preserved.
const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const conflictCode = appSource.slice(appSource.indexOf("function parameterConflictFingerprint("), appSource.indexOf("function refreshReviewChangeHistory()"));
const local = { spring_parameters: {}, technical_requirements: [{ requirement_id: "n", type: "process", content: "剪切模量 G*=80000 MPa", need_human_review: true, translation_status: "translated" }], manual_confirmations: {}, change_history: [], standardization_results: [] };
const server = { ...structuredClone(local), review_revision: 2, spring_parameters: { free_length: { value: 55 } }, technical_requirements: [{ requirement_id: "n", type: "process", content: "另一处人工输入", need_human_review: true }] };
const conflict = { structuredClone, state: { review: local, lastJob: { job_id: "one", review_revision: 1 }, pendingReviewAuditEvents: [], reviewDraftFields: new Set() },
  normalizeReview: structuredClone, apiFetch: async () => ({ ok: true, json: async () => structuredClone(server) }),
  setReview: (value) => { conflict.state.review = value; }, refreshReviewSurfaces() {} };
vm.createContext(conflict);
vm.runInContext(conflictCode, conflict);
let compared = false;
conflict.chooseParameterConflict = async (_field, a, b) => { compared = a.content === "另一处人工输入" && b.content === "剪切模量 G*=80000 MPa"; return "local"; };
const event = { target_field: "technical_requirements.n", client_event_id: "event-1", before_state: { type: "process", content: "Shear modulus G*=80000 MPa", need_human_review: false } };
let merged = await conflict.reconcileParameterRevisionConflict("one", [event]);
assert.equal(compared, true);
assert.equal(merged.review.technical_requirements[0].translation_status, "translated");
assert.equal(merged.review.spring_parameters.free_length.value, 55);
conflict.state.review = local;
conflict.chooseParameterConflict = async () => "server";
merged = await conflict.reconcileParameterRevisionConflict("one", [event]);
assert.equal(merged.review.technical_requirements[0].content, "另一处人工输入");
assert.equal(merged.events.length, 0);
console.log("PASS: translation UI, historical confirmation, batching, failed-text cache, retry, race guards and save failure");
