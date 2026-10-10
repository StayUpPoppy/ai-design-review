import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = { window: {}, console, setTimeout, clearTimeout, Map, JSON };
vm.createContext(context);
vm.runInContext(fs.readFileSync(new URL("../frontend/drawing-annotations.js", import.meta.url), "utf8"), context);
const ui = context.window.DrawingAnnotations;
const document = { source_document_id: "source-1", annotation_revision: 1, pages: [{ page: 1, image_url: "/one.png", width: 1000, height: 800 }, { page: 2, image_url: "/two.png", width: 1000, height: 800 }], annotations: [{ annotation_id: "wire_diameter", field: "wire_diameter", label: "线径", number: 4, original_value: 2, locations: [{ location_id: "wire_diameter-1", page: 2, anchor: { x: .2, y: .3 }, bubble: { x: .25, y: .25 } }] }, { annotation_id: "mean_diameter", field: "mean_diameter", label: "中径", number: 7, original_value: null, locations: [], reason: "无直接标注" }], warnings: [] };
const params = { wire_diameter: { value: 3 }, mean_diameter: { value: 26 } };
const beforeParams = JSON.stringify(params);
let job = "job-1", requestCount = 0, loadCount = 0, failLoad = false, fail = false, conflict = false, updates = 0, hold = null, isCompression = true;
const image = { naturalWidth: 1000, naturalHeight: 800 };
const view = { x: 20, y: 30, scale: .5 };
ui.configure({ getJobId: () => job, isCompression: () => isCompression, getParameter: (field) => params[field], fieldLabel: (field) => field,
  getImage: () => image, getViewport: () => job === "load-failure" ? null : ({ getBoundingClientRect: () => ({ left: 10, top: 20 }) }), getView: () => view,
  assetUrl: (url) => url, updateViewer: () => updates++, center: () => {}, fetch: async (path, options) => {
    if (!options) { loadCount++; if (failLoad) throw new Error("offline"); return { ok: true, json: async () => structuredClone(document) }; }
    requestCount++;
    if (hold) await hold;
    if (fail) throw new Error("offline");
    const body = JSON.parse(options.body);
    if (conflict) return { ok: false, status: 409, json: async () => ({ detail: { message: "冲突", annotations: { ...structuredClone(document), annotation_revision: 5 } } }) };
    return { ok: true, status: 200, json: async () => ({ ...structuredClone(document), annotation_revision: body.expected_annotation_revision + 1 }) };
  } });
await ui.focusField("wire_diameter");
assert.equal(ui.entry().page, 2);
assert.equal(ui.imageUrl(), "/two.png");
assert.match(ui.infoHtml(), /原图识别值：2/);
assert.match(ui.infoHtml(), /当前值：3/);
assert.equal(ui.screenPoint({ x: .2, y: .3 }).x, 120);
assert.equal(ui.imagePoint({ clientX: 130, clientY: 170 }).y, .3);
assert.match(ui.badgeHtml("wire_diameter", params.wire_diameter), />4<\/button>/);
assert.equal(ui.badgeHtml("pitch", { value: 5 }), "");
const numberedFields = ["material", "standard_no", "accuracy_grade", "wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "solid_height", "total_coils", "active_coils", "surface_roughness_ra", "handedness", "end_type", "end_grinding"];
for (const [index, field] of numberedFields.entries()) {
  for (const param of [undefined, {}, { value: null }, { value: "", evidence: "" }, { value: 0 }, { value: "识别值", need_human_review: true }, { value: "已确认值", need_human_review: false }]) {
    const before = JSON.stringify(param);
    assert.ok(ui.badgeHtml(field, param).includes(`>${index + 1}</button>`), `${field}: fixed number does not depend on content/confirmation`);
    assert.equal(JSON.stringify(param), before);
  }
}
isCompression = false;
for (const field of numberedFields) assert.equal(ui.badgeHtml(field, { value: "" }), "", "Other spring types do not gain numbers");
isCompression = true;
const beforeUnlocated = JSON.stringify(ui.entry().document);
await ui.focusField("standard_no");
assert.match(ui.infoHtml(), /未找到可靠原图位置/);
assert.equal(JSON.stringify(ui.entry().document), beforeUnlocated, "An empty/unlocated badge cannot fabricate a drawing location");
assert.equal(requestCount, 0, "Focusing a badge never saves annotations or parameters");
await ui.focusField("wire_diameter");
const item = ui.entry();
const change = { annotation_id: "wire_diameter", location_id: "wire_diameter-1", page: 2, anchor: { x: .2, y: .3 }, bubble: { x: .5, y: .5 } };
item.pending.set("wire_diameter:wire_diameter-1", change);
fail = true;
await ui.save();
assert.equal(item.phase, "failed");
assert.equal(item.pending.size, 1);
assert.equal(ui.hasUnsaved(), true);
fail = false;
await ui.save();
assert.equal(item.phase, "saved");
assert.equal(item.pending.size, 0);
assert.equal(item.document.annotation_revision, 2);
item.pending.set("wire_diameter:wire_diameter-1", change);
conflict = true;
await ui.save();
assert.equal(item.pending.size, 1);
assert.equal(item.conflict.annotation_revision, 5);
assert.match(ui.toolsHtml(), /使用服务器位置/);
assert.match(ui.toolsHtml(), /保留本地位置/);
item.conflict = null;
conflict = false;
let release;
hold = new Promise((resolve) => { release = resolve; });
const saving = ui.save();
item.pending.set("wire_diameter:wire_diameter-1", { ...change, bubble: { x: .6, y: .5 } });
job = "job-2";
const inactiveUpdates = updates;
release();
await saving;
assert.equal(updates, inactiveUpdates, "older order save must not redraw the newly opened review");
assert.equal(item.pending.size, 0, "newer edit must be serialized and saved, not discarded by an old response");
assert.equal(item.document.annotation_revision, 4);
assert.equal(JSON.stringify(params), beforeParams, "annotation logic must never change engineering parameters");
assert.ok(requestCount >= 5);
job = "load-failure";
failLoad = true;
const previousLoadCount = loadCount;
await ui.focusField("wire_diameter");
await ui.focusField("wire_diameter");
assert.equal(loadCount, previousLoadCount + 1, "a failed load must not start a re-render retry loop");
assert.match(ui.toolsHtml(), /重试加载标注/);
let retryLoad;
const loadButton = { dataset: { annotationAction: "load" }, addEventListener: (_type, action) => { retryLoad = action; } };
ui.bindViewer({ querySelectorAll: (selector) => selector === "[data-annotation-action]" ? [loadButton] : [], querySelector: () => null });
assert.equal(loadCount, previousLoadCount + 1);
failLoad = false;
retryLoad();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(loadCount, previousLoadCount + 2);
assert.ok(ui.entry().document);
// Annotation #2 must target its parameter row; legacy standardization links retain
// their standards-pane path and never confirm a field just because it was focused.
const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
assert.match(appSource, /focusParameter:.*parameterRow: true/);
const focusStart = appSource.indexOf("function focusMissingStandardizationField(");
const focusEnd = appSource.indexOf("function createCompareOverlay(", focusStart);
let rowFocused = false, standardFocused = false;
const fieldInput = { focus: () => { rowFocused = true; }, select: () => {} };
const row = { dataset: { field: "standard_no" }, closest: () => null, scrollIntoView: () => {}, querySelector: () => fieldInput };
const standardBlock = { querySelector: (selector) => selector === "details" ? {} : { focus: () => { standardFocused = true; } }, scrollIntoView: () => {} };
const navigation = { state: { review: {}, compareOpen: true, activeReviewMessageId: "demo" }, activateReviewContext: () => {}, renderCompareOverlay: () => {},
  afterCompareOverlayLayout: (callback) => callback(), parseLoadPointTarget: () => null, highlightReviewTarget: () => {},
  compareOverlay: { querySelectorAll: () => [row], querySelector: () => standardBlock } };
vm.createContext(navigation);
vm.runInContext(appSource.slice(focusStart, focusEnd), navigation);
navigation.focusMissingStandardizationField("standard_no", null, { highlight: true, parameterRow: true });
assert.equal(navigation.state.compareTab, "parameters");
assert.equal(rowFocused, true);
assert.equal(standardFocused, false);
navigation.focusMissingStandardizationField("standard_no", null, { highlight: true });
assert.equal(navigation.state.compareTab, "standards");
assert.equal(standardFocused, true);
console.log("drawing annotation UI tests passed: fixed empty-field numbers, coordinates, navigation, bounded loading, offline retry, conflict, serial saves and isolation");
