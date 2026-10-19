import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = { window: {}, structuredClone, console, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(fs.readFileSync("frontend/technical-requirement-translation.js", "utf8"), context);
const service = context.window.TechnicalRequirementTranslation;
const original = "Arbeitsweg (Hub) sh = 0.85 mm";
const chinese = "工作行程（行程）sh = 0.85 mm";
let review, job, item, calls, events, saveCount, hold, mode, failingSave;
function setup() {
  item = { requirement_id: "stroke", type: "process", content: original, original_content: original,
    translation_status: "failed", translation_error: "译文仍包含外语说明", translation_error_code: "foreign_prose_remaining",
    translation_error_details: { candidate_content: chinese, remaining_text: "sh" },
    translation_input_snapshot: { content: original, type: "process" }, need_human_review: true };
  review = { technical_requirements: [item], manual_confirmations: {} }; job = "old-order";
  calls = []; events = []; saveCount = 0; hold = null; mode = "automatic"; failingSave = false;
  service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit: (event) => events.push(event),
    save: async () => { saveCount++; return !(failingSave && saveCount > 1); },
    fetch: async (_url, options) => {
      const request = JSON.parse(options.body); calls.push(request);
      if (hold) await hold;
      if (mode === "offline") throw new Error("network down");
      const row = request.requirements[0];
      const result = { ...row, content: original, original_content: original, translation_status: "failed",
        translation_error: "译文仍包含外语说明", translation_error_code: "foreign_prose_remaining",
        translation_error_details: structuredClone(item.translation_error_details), translation_input_snapshot: row.source_snapshot,
        translation_source: "saved_failed_translation", recovery_mode: mode };
      if (mode === "automatic") Object.assign(result, { content: chinese, translation_status: "translated", translation_error: "", translation_error_details: {} });
      if (mode === "partial_success") Object.assign(result, { content: "工作行程 Hub sh = 0.85 mm", translation_status: "translated", translation_error: "", translation_error_details: {} });
      if (mode === "preview") result.translation_candidates = [{ content: chinese, original_content: original, translation_source: "saved_failed_translation" }];
      return { ok: true, json: async () => ({ requirements: [result] }) };
    } });
}
setup();
assert.equal(await service.run(), true);
assert.equal(calls[0].mode, "revalidate");
assert.equal(item.content, chinese);
assert.equal(item.need_human_review, true);
assert.equal(item.human_confirmed, false);
assert.equal(service.blocksExport(item), false);
assert.equal(events[0].event_type, "technical_requirement_translation_recovered");
await service.run(); assert.equal(calls.length, 1);

setup(); mode = "unavailable";
await service.run(); await service.run(); assert.equal(calls.length, 1);
await service.run("stroke", "revalidate");
assert.equal(calls.length, 2);
assert.equal(calls[1].mode, "revalidate", "explicit local recheck must never invoke a model");
assert.equal(item.translation_error_details.candidate_content, chinese);
mode = "offline";
await service.run("stroke");
assert.equal(calls.at(-1).mode, "translate");
assert.equal(item.translation_error_details.candidate_content, chinese, "network errors preserve same-input candidates");
assert.equal(item.translation_error_code, "request_failed");

setup(); mode = "partial_success";
await service.run("stroke");
assert.equal(item.translation_status, "translated");
assert.equal(item.content, "工作行程 Hub sh = 0.85 mm");
assert.equal(service.blocksExport(item), false);
assert.equal(item.translation_output_snapshot.content, item.content);
await service.run(); assert.equal(calls.length, 1, "Accepted Latin-containing text is never retranslated");

for (const action of ["edit", "edit_back", "type", "delete", "switch"]) {
  setup(); let release; hold = new Promise((resolve) => { release = resolve; });
  const old = item, running = service.run();
  await new Promise((resolve) => setTimeout(resolve, 0));
  if (action === "edit") { item.content = "人工补充"; service.changed(item); }
  if (action === "edit_back") service.changed(item);
  if (action === "type") { item.type = "other"; service.changed(item); }
  if (action === "delete") review.technical_requirements = [];
  if (action === "switch") { review = { technical_requirements: [] }; job = "new-order"; }
  release(); await running;
  assert.equal(old.translation_status, "failed", action);
  assert.equal(events.length, 0);
}
setup(); mode = "preview";
await service.run();
assert.equal(item.content, original);
assert.equal(await service.adoptCandidate("stroke", 0), true);
assert.equal(item.content, chinese); assert.equal(item.need_human_review, true);
assert.equal(events[0].metadata.recovery_mode, "adopted");
setup(); failingSave = true;
assert.equal(await service.run(), false);
assert.equal(item.content, chinese); assert.equal(item.need_human_review, true);
await service.run(); assert.equal(calls.length, 1, "failed saving never automatically retranslates");

// Exercise the actual feedback renderer, including untrusted model text.
context.technicalRequirementField = () => "technical_requirements.stroke";
context.parameterPersistenceState = () => "saved";
context.technicalTranslationService = () => service;
context.technicalRequirementBlocksExport = (note) => service.blocksExport(note);
context.escapeHtml = (text) => String(text).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const app = fs.readFileSync("frontend/app.js", "utf8");
vm.runInContext(app.slice(app.indexOf("function technicalTranslationFeedbackHtml("), app.indexOf("function technicalTranslationDifferenceValue(")), context);
setup();
item.translation_error_details.candidate_content = "工作行程 Hub <img src=x onerror=alert(1)> sh=0.85 mm";
let html = context.technicalTranslationFeedbackHtml(review, item, 0);
assert.ok(html.includes("送译原文") && html.includes("未通过校验的候选译文"));
assert.ok(html.includes('data-translation-action="revalidate"'));
assert.ok(html.includes("&lt;img") && !html.includes("<img"));
assert.ok(!html.includes('data-translation-action="adopt"'), "unvalidated failed candidates cannot be adopted");
assert.ok(!html.includes(" open"), "failure details stay collapsed");
mode = "unavailable";
await service.run();
assert.equal(service.blocksExport(item), true);
console.log("PASS: German symbols, local candidate recheck, guarded adoption, failure retention, audit, save/switch races and escaped feedback");
