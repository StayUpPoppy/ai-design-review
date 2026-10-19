import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = { window: {}, structuredClone, console, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(fs.readFileSync("frontend/technical-requirement-translation.js", "utf8"), context);
const service = context.window.TechnicalRequirementTranslation;
const fixtures = JSON.parse(fs.readFileSync("scripts/fixtures/technical_translation_direct_results.json", "utf8"));
let review, calls, events, mode;
function configure() {
  service.configure({ getReview: () => review, getJobId: () => "direct-order", update() {},
    save: async () => true, audit: (event) => events.push(event), fetch: async (_url, options) => {
      calls++;
      const body = JSON.parse(options.body);
      return { ok: true, json: async () => ({ requirements: body.requirements.map((row) => {
        const fixture = fixtures.find((item) => item.requirement_id === row.requirement_id);
        const candidate = { content: fixture.content, original_content: fixture.original_content, type: fixture.type };
        return { ...row, ...candidate, translation_status: mode === "preview" ? "failed" : "translated",
          translation_error: "", translation_input_snapshot: row.source_snapshot,
          recovery_mode: mode === "preview" ? "preview" : body.mode === "revalidate" ? "automatic" : undefined,
          translation_candidates: mode === "preview" ? [candidate] : [] };
      }) }) };
    } });
}
function setup() {
  review = { technical_requirements: fixtures.map((row) => ({ ...row, content: row.original_content,
    need_human_review: false, human_confirmed: true })), manual_confirmations: {} };
  calls = 0; events = []; mode = "translated"; configure();
}
setup();
assert.equal(await service.run(), true);
assert.equal(calls, 1);
for (const [index, item] of review.technical_requirements.entries()) {
  assert.equal(item.content, fixtures[index].content);
  assert.equal(item.translation_status, "translated");
  assert.equal(item.need_human_review, true);
  assert.equal(item.human_confirmed, false);
  assert.equal(service.blocksExport(item), false);
  assert.equal(service.warnings(item).length, 0);
  assert.equal(item.translation_output_snapshot.content, item.content);
}
await service.run(); assert.equal(calls, 1);
const reopened = structuredClone(review); review = reopened; configure();
await service.run(); assert.equal(calls, 1, "Saved output snapshots prevent repeated model calls after reopen");
for (const item of review.technical_requirements) delete item.translation_output_snapshot;
configure(); await service.run(); assert.equal(calls, 1, "Old successful records are compatible without snapshots");

// Exercise the real app edit hook: type-only edits may remove a display label.
Object.assign(context, { technicalTranslationService: () => service,
  state: { reviewDraftFields: new Set(), generationReadiness: null },
  rememberConfirmedSnapshot() {}, sourceValues: (value) => value || [], revokeManualConfirmations() {},
  markParameterChangeProposalsStale() {} });
const app = fs.readFileSync("frontend/app.js", "utf8");
vm.runInContext(app.slice(app.indexOf("function markTechnicalRequirementEdited("), app.indexOf("function syncTechnicalRequirementSummary(")), context);
const item = review.technical_requirements[0];
item.need_human_review = false;
item.content = "hardness: " + item.content;
item.translation_output_snapshot = service.snapshot(item);
item.content = fixtures[0].content; item.type = "hardness";
context.markTechnicalRequirementEdited(item, "field", "confirmation", "type");
assert.equal(item.translation_status, "translated");
assert.equal(item.need_human_review, true);
assert.equal(item.translation_output_snapshot.type, "hardness");
await service.run(); assert.equal(calls, 1, "Type-only edits never request translation");
item.content = "New external prose";
context.markTechnicalRequirementEdited(item, "field", "confirmation");
assert.equal(item.translation_output_snapshot, null);
assert.equal(service.isCurrent(item), false);
assert.equal(service.blocksExport(item), true);

for (const fixture of fixtures) {
  setup(); mode = "preview";
  review.technical_requirements = [{ ...fixture, content: fixture.original_content,
    translation_status: "failed", translation_error: "Historical failure", source: ["human_edited"] }];
  const note = review.technical_requirements[0]; note.translation_input_snapshot = service.snapshot(note);
  await service.run(); assert.equal(note.content, fixture.original_content);
  assert.equal(await service.adoptCandidate(note.requirement_id, 0), true);
  assert.equal(note.content, fixture.content);
  assert.equal(note.need_human_review, true);
  assert.equal(service.blocksExport(note), false);
  await service.run(); assert.equal(calls, 1);
}
console.log("PASS: six shared results, Latin/same/changed output, legacy reopen, type/body edits, adoption and no translation loops");
