import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES
  ? path.join(process.env.CODEX_NODE_MODULES, "playwright")
  : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const cases = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe",
  ["scripts/test_solidworks_export.py", "--json"], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const imagePath = process.env.BULK_CONFIRMATION_TEST_IMAGE || "data/samples/compression_spring_demo.png";
const image = fs.readFileSync(imagePath), imageType = /\.png$/i.test(imagePath) ? "image/png" : "image/jpeg";
const pending = (value, unit = "mm", extra = {}) => ({ value, unit, source: ["qwen_vision"], need_human_review: true, ...extra });
function fixture(complete = false) {
  const review = structuredClone(cases[0].review);
  Object.assign(review, { drawing_summary: { spring_type: "compression_spring", drawing_name: "回位弹簧", drawing_no: "705G72" },
    manual_confirmations: {}, change_history: [], standardization_results: [], parameter_reasonableness: { status: "pass", issues: [], suggestions: [] } });
  review.spring_parameters = {
    material: pending("", null, { raw_value: "VDCrSi-1.6-GB/T18983-2003", material_match_status: "unmatched" }),
    standard_no: pending("GB/T 1239.2-2009", null),
    wire_diameter: pending(1.6), outer_diameter: pending(13), inner_diameter: pending(9.8), mean_diameter: pending(11.4),
    free_length: pending(28), total_coils: pending(7.5, "圈"), active_coils: pending(5.5, "圈"),
    handedness: pending("right", null), end_type: pending("两端并紧", null), end_grinding: pending("两端磨削", null),
    spring_rate: pending(5.32, "N/mm"),
    load_points: [
      { load_point_id: "f1", label: "F1", height: complete ? 22.5 : null, height_unit: "mm", force: 29.26, force_unit: "N", need_human_review: true, source: ["qwen_vision"] },
      { load_point_id: "f2", label: "F2", height: complete ? 20 : null, height_unit: "mm", force: 42.56, force_unit: "N", need_human_review: true, source: ["qwen_vision"] },
    ],
  };
  review.technical_requirements = [
    { requirement_id: "heat", type: "heat_treatment", content: "消除应力退火。", source: ["qwen_vision"], need_human_review: true },
    ...(complete ? [] : [{ requirement_id: "untranslated", type: "other", content: "Arbeitsweg (Hub) sh = 0.85 mm",
      original_content: "Arbeitsweg (Hub) sh = 0.85 mm", translation_status: "failed", translation_error: "模拟请求失败",
      source: ["qwen_vision"], need_human_review: true }]),
  ];
  return review;
}
const orders = new Map(["partial", "complete", "failed", "slow"].map(id => [id, { review: fixture(id === "complete"), revision: 1 }]));
const frontend = path.resolve("frontend"), server = http.createServer((req, res) => {
  const file = path.resolve(frontend, new URL(req.url, "http://localhost").pathname.slice(1) || "index.html");
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
  res.end(fs.readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser, releaseSave;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.UNIT_TEST_BROWSER_CHANNEL || "msedge" });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } }), errors = [], warnings = [], mutations = [], calls = [];
  page.on("pageerror", error => errors.push(error.stack || error.message));
  page.on("console", message => { if (message.type() === "warning") warnings.push(message.text()); });
  let failSave = false, holdSave = false;
  await page.route("**/api/**", async route => {
    const req = route.request(), pathname = new URL(req.url()).pathname, method = req.method();
    calls.push({ pathname, method, mode: method === "POST" ? req.postDataJSON()?.mode : null });
    if (pathname.includes("/artifacts/")) return route.fulfill({ contentType: imageType, body: image });
    let body;
    if (pathname === "/api/session") body = { identity: { user_id: "bulk-test", username: "离线测试" }, mode: "mock" };
    else if (pathname === "/api/material-catalog") body = catalog;
    else if (pathname === "/api/reviews") body = { reviews: [] };
    else if (/^\/api\/reviews\/(partial|complete|failed|slow)$/.test(pathname)) {
      const id = pathname.split("/").at(-1), order = orders.get(id);
      if (method === "PATCH") {
        const input = req.postDataJSON(); mutations.push({ id, input });
        if (holdSave) { holdSave = false; await new Promise(resolve => { releaseSave = resolve; }); }
        if (failSave) return route.fulfill({ status: 503, json: { detail: "模拟保存失败" } });
        assert.equal(input.expected_revision, order.revision);
        order.review = input.review;
        body = { review_revision: ++order.revision, events: input.events.map(event => ({ ...event, sync_status: "saved" })) };
      } else body = { ...structuredClone(order.review), job_id: id, review_revision: order.revision, image_url: `/api/reviews/${id}/artifacts/page.jpg` };
    } else if (pathname.endsWith("/annotations")) body = {
      source_document_id: pathname.split("/")[3], annotation_revision: 1,
      pages: [{ page: 1, image_url: pathname.replace(/annotations$/, "artifacts/page.jpg") }], text_obstacles: [], warnings: [],
      annotations: [{ annotation_id: "wire_diameter", field: "wire_diameter", number: 4, label: "线径", original_value: 1.6,
        locations: [{ location_id: "wire", page: 1, source: "ocr", anchor: { x: .32, y: .4 }, bubble: { x: .38, y: .37 } }] }],
    };
    else if (pathname.endsWith("/changes")) body = { events: [] };
    else if (pathname.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (pathname.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_confirmation", missing_fields: [], pending_fields: [], warnings: [] } };
    else if (pathname.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "pass", issues: [], suggestions: [] } };
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ json: body });
  });
  await page.goto(process.env.BULK_TEST_BASE_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady);
  const panel = page.locator('#compareOverlay [data-compare-panel="parameters"]');
  const loadRow = id => panel.locator(`.load-point[data-kind="load_point"][data-load-point-id="${id}"]`);
  const action = name => page.locator(`#compareOverlay [data-view-action="${name}"]`);
  const view = () => page.evaluate(() => ({ scale: state.compareView.scale, x: state.compareView.x, y: state.compareView.y, rotation: state.compareView.rotation }));
  const near = (a, b) => assert.ok(Math.abs(a - b) < .01, `${a} != ${b}`);
  const ready = () => page.waitForFunction(() => document.querySelector("#compareImage")?.naturalWidth
    && !document.querySelector('[data-view-action="rotate-right"]')?.disabled && DrawingAnnotations.entry()?.document);
  const saved = () => page.waitForFunction(() => !state.reviewPersistenceSaving && state.pendingReviewAuditEvents.length === 0);
  async function open(id) {
    await page.evaluate(async id => { await openPersistedReview(id); state.compareTab = "parameters"; renderCompareOverlay(); }, id);
    await ready(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
    await panel.locator('[data-field="material"] [data-role="value"]').selectOption("55CrSi");
  }
  async function viewerWorks() {
    const count = mutations.length, start = await view();
    await action("zoom-in").click(); near((await view()).scale, start.scale * 1.2);
    await action("zoom-out").click(); near((await view()).scale, start.scale);
    await action("actual").click(); near((await view()).scale, 1);
    await action("fit").click(); const fitted = await view();
    await action("rotate-right").click(); assert.equal((await view()).rotation, (fitted.rotation + 90) % 360); near((await view()).scale, fitted.scale);
    await action("rotate-left").click();
    for (const [key, value] of Object.entries(fitted)) near((await view())[key], value);
    const rect = await page.locator("#compareViewport").boundingBox();
    await page.mouse.move(rect.x + 70, rect.y + 70); await page.mouse.down();
    await page.mouse.move(rect.x + 100, rect.y + 90, { steps: 3 }); await page.mouse.up();
    const moved = await view(); near(moved.x, fitted.x + 30); near(moved.y, fitted.y + 20);
    await page.mouse.wheel(0, -100);
    await page.waitForFunction(scale => state.compareView.scale > scale, moved.scale);
    assert.equal(await page.locator(".annotation-bubble").count(), 1);
    await page.locator('[data-annotation-action="visible"]').click(); assert.equal(await page.locator(".annotation-bubble").count(), 0);
    await page.locator('[data-annotation-action="visible"]').click(); await ready(); assert.equal(await page.locator(".annotation-bubble").count(), 1);
    assert.equal(mutations.length, count, "Viewer actions do not save parameters");
  }

  await open("partial");
  assert.equal(await panel.locator('[data-kind="param"][data-field="standard_no"]').count(), 0);
  const untouchedStandard = await page.evaluate(() => structuredClone(state.review.spring_parameters.standard_no));
  const displayCheck = await page.evaluate(async () => {
    const review = state.review, count = getEditorParameterFieldGroups(review.spring_parameters, review);
    const model = await buildConfirmationSheetSnapshot(activeReviewContext());
    return { visibleCount: count.core.length + count.advanced.length,
      commonHasStandard: getParameterFieldGroups(review.spring_parameters, review).core.includes("standard_no"),
      printIncludesStandard: JSON.stringify(model).includes("标准号") };
  });
  assert.ok(displayCheck.commonHasStandard && displayCheck.printIncludesStandard, "Keep template and confirmation sheet standard");
  assert.equal(await panel.locator('[data-kind="param"]').count(), displayCheck.visibleCount);
  const countBeforeNavigation = mutations.length;
  await page.evaluate(() => focusMissingStandardizationField("standard_no", { parameterRow: true }));
  assert.equal(await page.evaluate(() => state.compareTab), "standards");
  await page.evaluate(() => { state.compareTab = "parameters"; renderCompareOverlay(); }); await ready();
  assert.equal(mutations.length, countBeforeNavigation, "Hiding/navigation cannot save or confirm the standard");
  assert.deepEqual(await page.evaluate(() => state.review.spring_parameters.standard_no), untouchedStandard);
  await action("actual").click(); await action("rotate-right").click();
  const beforeBulk = await view();
  await panel.locator('[data-action="confirm-all-review-items"]').click();
  await page.waitForFunction(() => state.review.change_history.some(event => event.event_type === "safe_fields_confirmed"));
  assert.deepEqual(errors, [], "Partial F1/F2 follow-up must not interrupt viewer initialization");
  await saved(); await ready(); assert.deepEqual(await view(), beforeBulk, "Confirmation/save refresh preserves view");
  assert.equal(await panel.locator('[data-role="focus-bulk-confirmation-target"][data-target-kind="load_point"]').count(), 2);
  assert.equal(await panel.locator('[data-role="focus-bulk-confirmation-target"][data-kind]').count(), 0);
  assert.equal(await panel.locator('[data-role="focus-bulk-confirmation-target"][data-target-kind="technical"]').count(), 1);
  assert.equal(orders.get("partial").review.spring_parameters.material.value, "55CrSi");
  assert.equal(orders.get("partial").review.spring_parameters.material.need_human_review, false);
  assert.deepEqual(orders.get("partial").review.spring_parameters.standard_no, untouchedStandard, "Batch confirmation leaves hidden standard unchanged");
  assert.ok(orders.get("partial").review.spring_parameters.load_points.every(point => point.height == null && point.need_human_review));
  assert.equal(orders.get("partial").review.technical_requirements.find(item => item.requirement_id === "untranslated").need_human_review, true);
  await viewerWorks();

  for (const [id, height] of [["f1", "22.5"], ["f2", "20"]]) {
    await panel.locator(`[data-role="focus-bulk-confirmation-target"][data-load-point-id="${id}"]`).click();
    await page.waitForFunction(id => document.activeElement?.dataset.role === "height"
      && document.activeElement.closest(".load-point")?.dataset.loadPointId === id, id);
    await loadRow(id).locator('[data-role="height"]').fill(height);
    await loadRow(id).locator('[data-role="height"]').dispatchEvent("change");
    await loadRow(id).locator('[data-role="confirm"]').click(); await saved();
  }
  await page.reload(); await page.waitForFunction(() => state.identityReady);
  await page.evaluate(async () => { await openPersistedReview("partial"); state.compareTab = "parameters"; renderCompareOverlay(); }); await ready();
  assert.equal(await loadRow("f1").locator('[data-role="height"]').inputValue(), "22.5");
  assert.equal(await loadRow("f2").locator('[data-role="height"]').inputValue(), "20");
  assert.ok(orders.get("partial").review.spring_parameters.load_points.every(point => point.need_human_review === false));

  await open("complete"); await panel.locator('[data-action="confirm-all-review-items"]').click(); await saved(); await ready();
  assert.equal(await panel.locator('[data-role="focus-bulk-confirmation-target"][data-target-kind="load_point"]').count(), 0);
  assert.ok(orders.get("complete").review.spring_parameters.load_points.every(point => point.need_human_review === false));
  const bulkCount = mutations.flatMap(item => item.input.events).filter(event => event.event_type === "safe_fields_confirmed").length;
  await panel.locator('[data-action="confirm-all-review-items"]').evaluate(button => button.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await page.evaluate(() => flushReviewPersistence()); await ready();
  assert.equal(mutations.flatMap(item => item.input.events).filter(event => event.event_type === "safe_fields_confirmed").length, bulkCount, "Repeated completed confirmation does not duplicate audit writes");
  await viewerWorks();

  await open("failed"); await page.evaluate(() => flushReviewPersistence()); failSave = true;
  await panel.locator('[data-action="confirm-all-review-items"]').click();
  await panel.locator('[data-action="retry-bulk-confirmation-save"]').waitFor(); await ready();
  assert.equal(await page.evaluate(() => state.review.spring_parameters.material.need_human_review), false, "Failed save keeps local confirmation");
  await viewerWorks(); failSave = false;
  await panel.locator('[data-action="retry-bulk-confirmation-save"]').click(); await saved();
  assert.equal(orders.get("failed").review.spring_parameters.material.need_human_review, false);

  await open("slow"); await page.evaluate(() => flushReviewPersistence()); holdSave = true;
  await panel.locator('[data-action="confirm-all-review-items"]').click();
  await page.waitForFunction(() => state.reviewPersistenceSaving); assert.equal(typeof releaseSave, "function");
  await viewerWorks(); const duringSave = await view(); releaseSave(); releaseSave = null;
  await saved(); await ready(); assert.deepEqual(await view(), duringSave, "Late save/readiness refresh preserves the current view");

  // A malformed editor is diagnosed and skipped, without rebinding valid rows.
  await page.evaluate(() => {
    const root = document.createElement("div"); root.innerHTML = '<div class="load-point" data-kind="load_point" data-load-point-id="f1"><input data-role="height"></div>';
    bindReviewEditors(root);
  });
  assert.ok(warnings.some(message => message.includes("载荷编辑区域缺少必要控件")));
  // An unrelated future editor error must not remove the viewer's handlers.
  const fault = await page.evaluate(() => {
    const original = bindReviewEditors;
    bindReviewEditors = () => { throw new Error("editor isolation probe"); };
    try { renderCompareOverlay(); } catch (error) { return error.message; }
    finally { bindReviewEditors = original; }
  });
  assert.equal(fault, "editor isolation probe"); await ready(); await viewerWorks();
  await page.evaluate(() => renderCompareOverlay()); await ready();
  assert.deepEqual(errors, []);
  assert.equal(calls.filter(call => call.method === "PATCH" && call.pathname.endsWith("/annotations")).length, 0);
  assert.equal(calls.filter(call => call.method === "POST" && (call.pathname === "/api/reviews"
    || call.pathname.endsWith("/generation-jobs") || call.pathname.endsWith("/translate") && call.mode !== "revalidate")).length,
  0, "Only local revalidation of old failures is allowed; no recognition, model translation or SW submission");
  fs.mkdirSync("outputs/load-graph-ui-qa", { recursive: true });
  await page.screenshot({ path: "outputs/load-graph-ui-qa/desktop.png", fullPage: false });
  await page.setViewportSize({ width: 390, height: 844 });
  await ready();
  assert.equal(await panel.locator('[data-kind="param"][data-field="standard_no"]').count(), 0);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: "outputs/load-graph-ui-qa/mobile.png", fullPage: false });
  console.log("PASS bulk confirmation viewer: material selection, partial/complete loads, technical follow-ups, correct focus, save/reopen, failure/retry, slow responses, repeat click, malformed editors, viewer isolation and no cloud/SW calls");
} finally {
  releaseSave?.();
  await browser?.close(); server.close();
}
