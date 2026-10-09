import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = { window: {}, structuredClone, setTimeout, clearTimeout, console };
vm.createContext(context);
vm.runInContext(fs.readFileSync(new URL("../frontend/technical-requirement-translation.js", import.meta.url), "utf8"), context);
const service = context.window.TechnicalRequirementTranslation;
const fixtures = JSON.parse(fs.readFileSync(new URL("./fixtures/technical_translation_warning_pairs.json", import.meta.url), "utf8"));
let review, item, calls, saves, events, failSave, hold, job, preview;
function setup() {
  const fixture = fixtures[0];
  item = { requirement_id: "r11", type: fixture.type, content: fixture.original_content, original_content: fixture.original_content,
    translation_status: "failed", translation_error: "旧工程差异拦截", need_human_review: true, source: ["qwen_vision"] };
  item.translation_input_snapshot = service.snapshot(item);
  review = { spring_parameters: { active_coils: { value: 8 } }, technical_requirements: [item], manual_confirmations: {} };
  calls = 0; saves = 0; events = []; failSave = false; hold = null; preview = false; job = "one";
  service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit: (event) => events.push(event),
    save: async () => { saves++; return !(failSave && saves > 1); }, fetch: async (_url, options) => {
      calls++; const body = JSON.parse(options.body); assert.equal(body.mode, "revalidate");
      if (hold) await hold;
      const candidate = { content: fixture.content, original_content: fixture.original_content, type: fixture.type,
        source_language: "ru", translation_source: "saved_recognition", translation_warnings: [
          { code: "engineering_mismatch", category: fixture.expected_category, original: "СТ ЦКБА 030-2006", translated: "STsKBA 030-2006" }],
        translation_warning_snapshot: { content: fixture.content, type: fixture.type } };
      return { ok: true, json: async () => ({ requirements: [{ ...body.requirements[0], ...candidate,
        translation_status: preview ? "failed" : "translated", translation_error: "", translation_error_code: "", translation_error_details: {},
        translation_input_snapshot: body.requirements[0].source_snapshot, recovery_mode: preview ? "preview" : "automatic",
        translation_candidates: preview ? [candidate] : [] }] }) };
    } });
}
setup();
assert.equal(await service.run(), true);
assert.equal(item.content, fixtures[0].content);
assert.equal(item.need_human_review, true);
assert.equal(service.blocksExport(item), false);
assert.equal(service.warnings(item).length, 1);
assert.equal(events[0].metadata.translation_warnings.length, 1);
await service.run();
assert.equal(calls, 1, "usable warning Chinese never invokes another model request");
assert.equal(review.spring_parameters.active_coils.value, 8);
item.content += "人工补充";
assert.equal(service.warnings(item).length, 0, "old differences do not describe a new edit");
item.content = fixtures[0].content; item.type = "process";
assert.equal(service.warnings(item).length, 0, "old type snapshots are not reused");
setup(); preview = true; item.type = "surface";
item.translation_input_snapshot = service.snapshot(item);
await service.run();
assert.equal(item.content, fixtures[0].original_content);
assert.equal(await service.adoptCandidate("r11", 0), true);
assert.equal(service.warnings(item).length, 1, "adopted preview warnings belong to the current row type");
assert.equal(item.need_human_review, true);
setup(); failSave = true;
assert.equal(await service.run(), false);
assert.equal(item.content, fixtures[0].content);
assert.equal(service.warnings(item).length, 1);
await service.run();
assert.equal(calls, 1, "failed final save keeps Chinese and warnings without retranslation");
for (const action of ["edit", "delete", "switch", "type", "edit_back"]) {
  setup(); let release; hold = new Promise((resolve) => { release = resolve; });
  const old = item; const running = service.run();
  await new Promise((resolve) => setTimeout(resolve, 0));
  if (action === "edit") { item.content = "最新输入"; service.changed(item); }
  if (action === "edit_back") service.changed(item);
  if (action === "type") { item.type = "surface"; service.changed(item); }
  if (action === "delete") review.technical_requirements = [];
  if (action === "switch") { review = { technical_requirements: [] }; job = "two"; }
  release(); await running;
  assert.equal(old.translation_status, "failed", action);
  assert.equal(events.length, 0, action);
}
for (const fixture of fixtures) assert.equal(service.needsTranslation(fixture.content), false);
assert.equal(service.blocksExport({ content: "中文 Force 16 N", need_human_review: false, translation_status: "translated" }), true);
assert.equal(service.blocksExport({ content: "力 ⟦ENG_9999⟧", need_human_review: false, translation_status: "translated" }), true);
assert.equal(service.blocksExport({ content: "G*=80000 MPa", translation_status: "not_required" }), false);
assert.equal(service.blocksExport({ content: "G*=80000 MPa", original_content: "Shear modulus G*=80000 MPa", translation_status: "translated" }), true);
console.log("PASS: engineering-warning Chinese, active snapshots, preview adoption, no retry loop, races and save failure");
