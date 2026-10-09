import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = { window: {}, structuredClone, setTimeout, clearTimeout, console };
vm.createContext(context);
vm.runInContext(fs.readFileSync(new URL("../frontend/technical-requirement-translation.js", import.meta.url), "utf8"), context);
const service = context.window.TechnicalRequirementTranslation;
const original = "9. Заневолить силой F₃ с выдержкой под нагрузкой не менее 6 часов";
const chinese = "在力 F3 作用下强压处理，保载时间不少于 6 小时";
let review, job, calls, saves, events, mode, hold, failSave, item;
function setup() {
  item = { requirement_id: "r9", type: "process", content: original, original_content: original,
    need_human_review: true, source: ["qwen_vision"], translation_status: "failed", translation_error: "旧校验误判",
    translation_input_snapshot: { content: original, type: "process" }, confirmation_snapshot: { content: original }, human_confirmed: true };
  review = { technical_requirements: [item], spring_parameters: { free_length: { value: 50 } }, manual_confirmations: { technical_requirement_r9: { confirmed: true } } };
  job = "one"; calls = []; saves = 0; events = []; mode = "automatic"; hold = null; failSave = false;
  service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit: (event) => events.push(event),
    save: async () => { saves++; return !(failSave && saves > 1); }, fetch: async (_url, options) => {
      const body = JSON.parse(options.body); calls.push(body);
      if (hold) await hold;
      if (mode === "offline") throw new Error("offline");
      const result = { requirement_id: item.requirement_id, source_snapshot: body.requirements[0].source_snapshot,
        content: original, original_content: original, source_language: "ru", translation_input_snapshot: body.requirements[0].source_snapshot,
        translation_status: "failed", translation_error: "没有可靠候选", recovery_mode: mode };
      if (mode === "automatic") Object.assign(result, { content: chinese, translation_status: "translated", translation_error: "", translation_source: "saved_recognition" });
      if (mode === "preview") Object.assign(result, { recovery_reason: "已有人工编辑，请对照后选择", translation_candidates: [{ content: chinese, original_content: original, source_language: "ru", translation_source: "saved_recognition" }] });
      return { ok: true, json: async () => ({ requirements: [result] }) };
    } });
}
setup();
assert.equal(await service.run(), true);
assert.equal(calls[0].mode, "revalidate");
assert.equal(item.content, chinese);
assert.equal(item.need_human_review, true);
assert.equal(item.human_confirmed, false);
assert.equal(item.confirmation_snapshot, undefined);
assert.deepEqual(Object.keys(review.manual_confirmations), []);
assert.deepEqual(item.source, ["qwen_vision"]);
assert.equal(events[0].event_type, "technical_requirement_translation_recovered");
assert.equal(events[0].source, "translation_validation");
assert.equal(saves, 2);
await service.run();
assert.equal(calls.length, 1);
assert.equal(review.spring_parameters.free_length.value, 50);

setup(); mode = "preview"; item.source = ["human_edited"];
await service.run();
assert.equal(item.content, original);
assert.equal(events.length, 0);
assert.equal(service.preview(review, item).translation_candidates.length, 1);
assert.equal(await service.adoptCandidate("r9", 0), true);
assert.equal(item.content, chinese);
assert.equal(item.need_human_review, true);
assert.equal(events[0].metadata.recovery_mode, "adopted");
assert.equal(service.preview(review, item), null);

setup(); mode = "unavailable";
await service.run(); await service.run();
assert.equal(calls.length, 1, "identical failed evidence is checked only once per page");
assert.equal(item.translation_status, "failed");
await service.run("r9");
assert.equal(calls.at(-1).mode, "translate", "explicit retry, not revalidation, invokes text translation");

setup(); mode = "offline";
await service.run(); await service.run();
assert.equal(calls.length, 1);
assert.equal(item.translation_error, "旧校验误判", "request failure must not replace recovery evidence");
assert.equal(events.length, 0);

for (const action of ["edit", "edit_back", "type", "delete", "switch"]) {
  setup(); let release; hold = new Promise((resolve) => { release = resolve; });
  const old = item, running = service.run();
  await new Promise((resolve) => setTimeout(resolve, 0));
  if (action === "edit") { item.content = "新输入"; service.changed(item); }
  if (action === "edit_back") service.changed(item);
  if (action === "type") { item.type = "other"; service.changed(item); }
  if (action === "delete") review.technical_requirements = [];
  if (action === "switch") { job = "two"; review = { technical_requirements: [] }; }
  release(); await running;
  assert.equal(old.translation_status, "failed", action);
  assert.equal(events.length, 0);
}
setup(); mode = "preview";
await service.run(); service.changed(item);
assert.equal(await service.adoptCandidate("r9", 0), false, "edited-back drafts invalidate preview too");
assert.equal(item.content, original);

setup(); failSave = true;
assert.equal(await service.run(), false);
assert.equal(item.content, chinese);
await service.run();
assert.equal(calls.length, 1, "save retry never retranslates or revalidates a recovered Chinese note");
setup(); mode = "preview"; await service.run(); failSave = true;
assert.equal(await service.adoptCandidate("r9", 0), false);
assert.equal(item.content, original, "a failed pre-save cannot adopt preview");
setup(); mode = "preview"; await service.run();
service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit: (event) => events.push(event), save: async () => ++saves < 3 });
assert.equal(await service.adoptCandidate("r9", 0), false);
assert.equal(item.content, chinese, "a failed final save preserves the chosen local Chinese text");
assert.equal(item.need_human_review, true);
setup();
review.technical_requirements = Array.from({ length: 55 }, (_, index) => ({ ...structuredClone(item), requirement_id: `many-${index}` }));
let checkedRows = 0;
service.configure({ getReview: () => review, getJobId: () => job, update() {}, audit() {}, save: async () => true,
  fetch: async (_url, options) => { const body = JSON.parse(options.body); assert.equal(body.mode, "revalidate"); checkedRows += body.requirements.length;
    return { ok: true, json: async () => ({ requirements: body.requirements.map((row) => ({ ...row, content: row.source_snapshot.content, translation_status: "failed", recovery_mode: "unavailable", translation_error: "无候选" })) }) }; } });
await service.run();
await new Promise((resolve) => setTimeout(resolve, 20));
assert.equal(checkedRows, 55, "more than 50 failed notes finish bounded local checks without calling translation");
await service.run();
assert.equal(checkedRows, 55);
console.log("PASS: historical translation recovery, explicit preview adoption, snapshots, audit, races and save retry");
