import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = process.env.CODEX_NODE_MODULES
  ? require(path.join(process.env.CODEX_NODE_MODULES, "playwright"))
  : require("C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const root = path.resolve("frontend"), output = path.resolve("outputs/parameter-units-qa");
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((request, response) => {
  const file = path.resolve(root, request.url.split("?")[0].replace(/^\//, "") || "index.html");
  if (file !== path.join(root, "index.html") && !file.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
  if (!fs.existsSync(file)) { response.writeHead(404).end(); return; }
  response.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.UNIT_TEST_BROWSER_CHANNEL ? { channel: process.env.UNIT_TEST_BROWSER_CHANNEL } : {}) });
  for (const [size, width, height] of [["desktop", 1440, 1000], ["narrow", 1100, 900], ["mobile", 390, 900]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [], mutations = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let revision = 1;
    const param = (value, unit = null, extra = {}) => ({ value, unit, need_human_review: false, source: ["human_confirmed"], ...extra });
    let review = {
      drawing_summary: { spring_type: "compression_spring", drawing_name: "参数单位回归演示（模拟测试数据）", drawing_no: "DEMO-UNITS" },
      spring_parameters: {
        material: param("SUS304"), standard_no: param("GB/T 1239.2-2009"), accuracy_grade: param("2级"),
        wire_diameter: param(2, "mm"), outer_diameter: param(20, "mm"), inner_diameter: param(16, "mm"), mean_diameter: param(18, "mm"),
        free_length: param(40, "mm"), solid_height: param(24, "mm", { need_human_review: true, source: ["formula_calculation"] }),
        total_coils: param(12, "turns"), active_coils: param(10, "turns"), surface_roughness_ra: param(12.5, "μm"),
        handedness: param("right"), end_type: param("两端并紧"), end_grinding: param("两端磨削"),
        pitch: param(3.6, "mm"), support_coils: param(1, "turns"), spring_rate: param(8.8, "N/mm"),
        load_points: [{ load_point_id: "load-one", label: "F1", height: 25, force: 100, height_unit: "mm", force_unit: "N", load_tolerance_upper: 5, load_tolerance_lower: -5, need_human_review: false },
          { load_point_id: "load-two", label: "F2", height: 2, force: .12, height_unit: "cm", force_unit: "kN", load_tolerance_percent: 10, need_human_review: false }],
      },
      technical_requirements: [], standardization_results: [], derived_parameters: {},
      manual_confirmations: {}, change_history: [], parameter_reasonableness: { status: "ok", issues: [], suggestions: [] },
    };
    await page.route("**/api/**", async (route) => {
      const request = route.request(), apiPath = new URL(request.url()).pathname;
      let body = {};
      if (request.method() === "PATCH") {
        const input = request.postDataJSON();
        mutations.push(input);
        review = input.review;
        body = { review_revision: ++revision, events: input.events.map((event) => ({ ...event, sync_status: "saved" })) };
      } else if (apiPath === "/api/reviews/unit-order") body = { ...review, job_id: "unit-order", review_revision: revision, image_url: "" };
      else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "模拟测试用户" }, mode: "mock" };
      else if (apiPath === "/api/reviews") body = { reviews: [] };
      else if (apiPath.endsWith("/changes")) body = { events: [] };
      else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
      else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_input", summary: "模拟数据不发起生图", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 0, core_field_count: 8 }, generation_queue_available: false };
      else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
      else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "demo", annotation_revision: 1, pages: [], annotations: [{ annotation_id: "wire_diameter", field: "wire_diameter", label: "线径", number: 4, original_value: 2, locations: [], reason: "模拟数据无图纸位置" }], warnings: [] };
      else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => {
      await openPersistedReview("unit-order");
      state.compareTab = "parameters";
      renderCompareOverlay();
    });
    await page.waitForLoadState("networkidle");
    const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
    const wire = panel.locator('[data-kind="param"][data-field="wire_diameter"]');
    await assert.doesNotReject(() => wire.waitFor({ state: "visible" }));
    assert.match(await wire.locator(".data-label strong").innerText(), /线径（mm）/);
    assert.equal(await wire.locator('[data-role="value"]').getAttribute("aria-label"), "线径（mm）数值");
    assert.equal(await wire.locator('[data-role="value"]').inputValue(), "2");
    assert.equal(await panel.locator('[data-field="surface_roughness_ra"] .parameter-label-unit').count(), 1);
    assert.equal(await panel.locator('[data-field="material"] .parameter-label-unit').count(), 0);
    assert.match(await panel.locator('[data-field="solid_height"] .data-label strong').innerText(), /压并高度（参考）（mm）/);
    await panel.locator(".advanced-parameters summary").click();
    assert.match(await panel.locator('[data-field="support_coils"] .data-label strong').innerText(), /支承圈数（单端）（圈）/);
    assert.match(await panel.locator('[data-load-point-id="load-two"] .data-primary').innerText(), /高度（cm）/);
    assert.match(await panel.locator('[data-load-point-id="load-two"] .data-secondary').innerText(), /力值（kN）/);
    assert.equal(await panel.locator('[data-load-point-id="load-one"] [data-role="load-tolerance"]').inputValue(), "±5N", "Existing load tolerance formatting remains unchanged");
    assert.equal(await panel.locator('[data-load-point-id="load-two"] [data-role="load-tolerance"]').inputValue(), "±10%");

    const before = await page.evaluate(() => ({ parameters: JSON.stringify(state.review.spring_parameters), confirmations: JSON.stringify(state.review.manual_confirmations), events: JSON.stringify(state.review.change_history), exportParameters: JSON.stringify(makeGenerationParameterPackage().generation_parameters) }));
    await page.evaluate(() => { renderCompareOverlay(); renderCompareOverlay(); });
    const after = await page.evaluate(() => ({ parameters: JSON.stringify(state.review.spring_parameters), confirmations: JSON.stringify(state.review.manual_confirmations), events: JSON.stringify(state.review.change_history), exportParameters: JSON.stringify(makeGenerationParameterPackage().generation_parameters) }));
    assert.deepEqual(after, before, "Rerendering unit labels cannot alter saved values, confirmations, audit or exported parameters");
    assert.equal(mutations.length, 0, "Loading/displaying units must not save the review");

    await page.evaluate(() => focusMissingStandardizationField("support_coils"));
    await page.waitForFunction(() => document.activeElement?.closest('[data-field="support_coils"]'));
    assert.equal(await panel.locator(".advanced-parameters").getAttribute("open"), "");
    await page.evaluate(() => focusMissingStandardizationField("wire_diameter"));
    await page.waitForFunction(() => document.activeElement?.closest('[data-field="wire_diameter"]'));
    if (await wire.locator(".parameter-annotation-number").count()) {
      assert.equal(await wire.locator(".parameter-annotation-number").innerText(), "4");
      await wire.locator(".parameter-annotation-number").click();
    }
    const overflow = await panel.evaluate((element) => [...element.querySelectorAll('.data-row[data-kind="param"], .load-point')].filter((row) => !row.closest("details:not([open])")).some((row) => {
      const outer = row.getBoundingClientRect();
      return [...row.querySelectorAll("input, select, .confirm-button, .load-point-delete-button, .parameter-label-unit")].some((control) => {
        const box = control.getBoundingClientRect();
        return box.width && (box.left < outer.left - 1 || box.right > outer.right + 1);
      });
    }));
    assert.equal(overflow, false, `${size}: units/inputs/buttons must stay inside rows`);
    assert.equal(await wire.locator(".data-label strong").evaluate((element) => getComputedStyle(element).whiteSpace), "normal");
    assert.equal(await wire.locator(".parameter-label-unit").evaluate((element) => getComputedStyle(element).whiteSpace), "nowrap");
    if (size === "mobile") {
      assert.equal(await panel.locator(".load-point-actions").first().evaluate((element) => getComputedStyle(element).flexDirection), "column");
      assert.equal(await panel.locator(".load-point-actions button").first().evaluate((element) => getComputedStyle(element).whiteSpace), "nowrap");
    }
    await page.screenshot({ path: path.join(output, `${size}.png`) });
    await panel.locator(".load-point-section").screenshot({ path: path.join(output, `${size}-loads.png`) });
    assert.deepEqual(errors, [], `${size}: no uncaught browser errors`);
    await page.close();
  }
  console.log(`PASS: real workbench units, read-only rerender/export, focus and desktop/narrow/mobile layout. Screenshots: ${output}`);
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
