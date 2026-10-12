import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES ? path.join(process.env.CODEX_NODE_MODULES, "playwright") : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const fixture = JSON.parse(fs.readFileSync("data/test/compression_design_checks.json", "utf8"));
const baseline = structuredClone(fixture.base);
for (const [field, value] of Object.entries(fixture.cases.find((c) => c.name === "book-order2-baseline").overrides)) {
  if (value && typeof value === "object" && !Array.isArray(value)) Object.assign(baseline.spring_parameters[field] ||= {}, value);
  else baseline.spring_parameters[field] = structuredClone(value);
}
Object.assign(baseline, { technical_requirements: [], manual_confirmations: {}, standardization_results: [], derived_parameters: {}, change_history: [] });
baseline.spring_parameters.load_points.forEach((point, i) => Object.assign(point, { load_point_id: `point-${i}`, height: i ? 12.284 : 14.284, height_unit: "mm", force_unit: "N" }));
const diagnostic = (id, status, value, units = { height_unit: "cm", force_unit: "kN" }) => ({ candidate_id: id, status, page: 1,
  reason: "缺少原图载荷表头，请核对", evidence: "参数表载荷列第一行 <script>invalid</script>",
  source_context: { kind: "table", headers: [], row_text: "1.5 0.01" },
  original_candidate: { source: "qwen_vision", value: { label: "F1", height: 1.5, force: .01, height_unit: "cm", force_unit: "kN", load_tolerance_upper: .002, load_tolerance_lower: -.002, ...value }, reported_units: units } });
baseline.load_point_diagnostics = [diagnostic("candidate-1", "pending", {}), diagnostic("candidate-2", "pending", { label: "F4", height: null, force: null }), diagnostic("candidate-3", "pending", { label: "F5" }, { height_unit: null, force_unit: null }), diagnostic("excluded-1", "excluded", { label: "F3", height: 2000, force: 3200 })];
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const frontend = path.resolve("frontend");
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, "http://localhost").pathname.slice(1) || "index.html");
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.UNIT_TEST_BROWSER_CHANNEL || "msedge" });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  const errors = [], events = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let saved = structuredClone(baseline), revision = 1, delayNext = false, releaseSave;
  await page.route("**/api/**", async (route) => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body;
    if (apiPath === "/api/material-catalog") body = catalog;
    else if (apiPath === "/api/reviews/load-recognition" && request.method() === "PATCH") {
      const input = request.postDataJSON();
      assert.equal(input.expected_revision, revision);
      if (delayNext) { delayNext = false; await new Promise((resolve) => { releaseSave = resolve; }); }
      saved = input.review; events.push(...(input.events || []));
      body = { review_revision: ++revision, events: (input.events || []).map((e) => ({ ...e, sync_status: "saved" })) };
    } else if (apiPath === "/api/reviews/load-recognition") body = { ...saved, job_id: "load-recognition", review_revision: revision, image_url: "" };
    else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "载荷识别回归测试" }, mode: "mock" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_confirmation", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 0, core_field_count: 8 }, generation_queue_available: false };
    else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "pass", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "test", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const reopen = () => page.evaluate(async () => { await openPersistedReview("load-recognition"); state.compareTab = "parameters"; renderCompareOverlay(); });
  await reopen();
  await page.waitForFunction(() => state.materialCatalog.status === "ready");
  const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const row = (id) => panel.locator(`.load-candidate[data-candidate-id="${id}"]`);
  const form = panel.locator('[data-kind="load_point_create"]');
  const flush = async () => assert.equal(await page.evaluate(() => flushReviewPersistence({ throwOnError: true })), true);
  assert.equal(await panel.locator('.load-candidate-section:not(.load-candidate-history)').getAttribute("open"), "");
  assert.equal(await panel.locator('.load-candidate-history').getAttribute("open"), null);
  assert.equal(await panel.locator('[data-kind="load_point"]').count(), 2);
  assert.equal(await page.evaluate(() => state.review.design_checks.work_stresses.length), 2);
  assert.equal(await row("candidate-1").locator("script").count(), 0, "Raw evidence is escaped");
  const output = "outputs/load-recognition-qa";
  fs.mkdirSync(output, { recursive: true });
  await panel.locator('.load-point-section').screenshot({ path: `${output}/desktop.png` });
  await row("candidate-1").locator('[data-action="promote-load-candidate"]').click();
  assert.equal(await form.locator('[data-role="new-load-height"]').inputValue(), "15");
  assert.equal(await form.locator('[data-role="new-load-force"]').inputValue(), "10");
  assert.match(await form.locator('[data-role="new-load-tolerance"]').inputValue(), /2/);
  await form.evaluate((node) => node.requestSubmit());
  assert.match(await form.locator('[data-role="load-point-create-error"]').innerText(), /已经存在/);
  assert.equal(await panel.locator('[data-kind="load_point"]').count(), 2);
  await form.locator('[data-role="new-load-label"]').fill("F3");
  delayNext = true;
  await form.evaluate((node) => node.requestSubmit());
  await page.waitForFunction(() => state.reviewPersistenceInFlightEvents.length > 0);
  const promotedId = await page.evaluate(() => state.review.load_point_diagnostics[0].promoted_load_point_id);
  const pointRow = panel.locator(`[data-kind="load_point"][data-load-point-id="${promotedId}"]`);
  await pointRow.locator('[data-role="height"]').fill("16");
  await pointRow.locator('[data-role="height"]').dispatchEvent("change");
  await row("candidate-2").locator('[data-action="dismiss-load-candidate"]').click();
  assert.equal(await page.evaluate(() => state.review.load_point_diagnostics[0].status), "promoted");
  releaseSave(); await flush();
  assert.equal(saved.spring_parameters.load_points.find((p) => p.load_point_id === promotedId).height, 16, "Delayed save does not replace newer edits");
  assert.equal(saved.load_point_diagnostics[1].status, "dismissed");
  assert.equal(saved.spring_parameters.load_points.filter((p) => p.recognition_candidate_id === "candidate-1").length, 1);
  assert.ok(events.some((e) => e.event_type === "load_candidate_promoted"));
  assert.ok(events.some((e) => e.event_type === "load_candidate_dismissed"));
  assert.equal(await page.evaluate((id) => makeGenerationParameterPackage().generation_parameters.load_points.some((p) => p.label === "F3"), promotedId), false);
  await pointRow.locator('[data-role="confirm"]').click(); await flush();
  assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.load_points.some((p) => p.label === "F3")), true);
  await row("candidate-3").locator('[data-action="promote-load-candidate"]').click();
  assert.equal(await form.locator('[data-role="new-load-height"]').inputValue(), "");
  assert.equal(await form.locator('[data-role="new-load-force"]').inputValue(), "");
  assert.match(await form.locator('[data-role="load-point-create-error"]').innerText(), /单位/);
  await form.locator('[data-action="cancel-load-point-create"]').click();
  await flush(); await page.reload(); await reopen();
  assert.equal(await panel.locator('[data-kind="load_point"]').count(), 3);
  assert.equal(await page.evaluate(() => state.review.load_point_diagnostics.filter((d) => d.status === "pending").length), 1);
  assert.equal(await row("candidate-1").locator('[data-action="promote-load-candidate"]').count(), 0);
  // Check the actual diagnostics component at narrow widths without altering the production DOM structure.
  const html = await panel.locator('.load-point-section').evaluate((node) => node.outerHTML);
  await page.evaluate((html) => { document.body.innerHTML = html; document.documentElement.style.cssText = "height:auto;overflow:visible"; document.body.style.cssText = "height:auto;overflow:visible;margin:0"; }, html);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 1600 });
    const section = page.locator('.load-candidate-section:not(.load-candidate-history)');
    assert.equal(await section.evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
    if (width === 390) await section.screenshot({ path: `${output}/narrow.png` });
  }
  assert.deepEqual(errors, []);
  console.log("load candidate browser: isolation, evidence escaping, units/tolerance, duplicate protection, promote/dismiss, confirmation/export, delayed save, reopen and narrow display passed");
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
