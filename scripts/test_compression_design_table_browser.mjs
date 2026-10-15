import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES
  ? path.join(process.env.CODEX_NODE_MODULES, "playwright")
  : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const fixture = JSON.parse(fs.readFileSync("data/test/compression_design_checks.json", "utf8"));
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const book = fixture.cases.find((item) => item.name === "book-order2-baseline");
const baseline = () => {
  const review = structuredClone(fixture.base);
  for (const [field, value] of Object.entries(book.overrides)) {
    if (value && !Array.isArray(value) && typeof value === "object") Object.assign(review.spring_parameters[field] ||= {}, value);
    else review.spring_parameters[field] = structuredClone(value);
  }
  Object.assign(review.spring_parameters, { outer_diameter: { value: 27, unit: "mm" }, handedness: { value: "right" } });
  review.spring_parameters.load_points.forEach((point, index) => {
    Object.assign(point, { load_point_id: `point-${index}`, height: index ? 12.284 : 14.284, height_unit: "mm", force_unit: "N" });
  });
  Object.assign(review, { technical_requirements: [], manual_confirmations: {}, standardization_results: [], derived_parameters: {}, change_history: [] });
  return review;
};
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
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let saved = baseline(), revision = 1, catalogReleased = false, releaseCatalog;
  const gate = new Promise((resolve) => { releaseCatalog = () => { catalogReleased = true; resolve(); }; });
  await page.route("**/api/**", async (route) => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body;
    if (apiPath === "/api/material-catalog") { if (!catalogReleased) await gate; body = catalog; }
    else if (apiPath === "/api/reviews/table-layout" && request.method() === "PATCH") {
      const input = request.postDataJSON();
      assert.equal(input.expected_revision, revision);
      saved = input.review;
      body = { review_revision: ++revision, events: (input.events || []).map((event) => ({ ...event, sync_status: "saved" })) };
    } else if (apiPath === "/api/reviews/table-layout") body = { ...saved, job_id: "table-layout", review_revision: revision, image_url: "" };
    else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "表格布局回归测试" }, mode: "mock" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_confirmation", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 0, core_field_count: 8 }, generation_queue_available: false };
    else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "test", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  const url = `http://127.0.0.1:${server.address().port}`;
  await page.goto(url);
  const reopen = () => page.evaluate(async () => { await openPersistedReview("table-layout"); state.compareTab = "parameters"; renderCompareOverlay(); });
  await reopen();
  const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const checks = panel.locator('[data-kind="compression-design-check"]');
  const value = (metric) => checks.locator(`[data-role="design-check-value"][data-metric="${metric}"]`);
  const input = (field) => panel.locator(`[data-kind="param"][data-field="${field}"] [data-role="value"]`);
  const basis = checks.locator('[data-design-disclosure="basis"]');
  const formulas = checks.locator('[data-design-disclosure="formulas"]');
  const edit = async (field, text) => { await input(field).fill(text); await input(field).dispatchEvent("change"); };
  const flush = async () => assert.equal(await page.evaluate(() => flushReviewPersistence({ throwOnError: true })), true);
  assert.equal(await basis.getAttribute("open"), null, "Calculation basis is collapsed on first open");
  assert.equal(await formulas.getAttribute("open"), null);
  await basis.locator(":scope > summary").click();
  assert.equal(await value("theoretical_spring_rate").innerText(), "--");
  assert.equal(await checks.locator('[data-role="design-check-unit"][data-metric="theoretical_spring_rate"]').innerText(), "N/mm");
  await formulas.locator(":scope > summary").click();
  releaseCatalog();
  await page.waitForFunction(() => state.materialCatalog.status === "ready");
  assert.equal(await formulas.getAttribute("open"), "", "Async catalog refresh preserves formula disclosure");
  const expected = { spring_index: "14", slenderness_ratio: "0.754", theoretical_spring_rate: "2.9314", solid_stress: "451.2669", unit_mass: "0.00642403" };
  for (const [metric, result] of Object.entries(expected)) assert.equal(await value(metric).innerText(), result);
  assert.deepEqual(await checks.locator('.compression-design-primary tr:not(.design-mobile-basis) th[scope="row"]').allTextContents(), ["旋绕比 C", "细长比 b", "理论刚度 P′", "压并应力 τ_b", "单件重量 Q", "F1 工作应力", "F2 工作应力"]);
  assert.deepEqual(await checks.locator('.compression-work-stress [data-role="design-check-value"]').allTextContents(), ["160.0034", "229.0958"]);
  assert.equal(await value("reference_solid_height_limit").innerText(), "≤ 7.4");
  assert.equal(await checks.locator('[data-role="design-check-unit"][data-metric="spring_index"]').innerText(), "—");
  assert.equal(await value("theoretical_spring_rate").count(), 1, "No duplicate stiffness result in basis");
  assert.match(await checks.locator('[data-role="solid-load-note"]').innerText(), /Pb = 37\.2287 N.*Hb = 6\.3 mm（书页名义高度）/);
  assert.match(await formulas.innerText(), /G\*d\^4/);
  assert.match(await formulas.innerText(), /剪切模量 G\s+71500 MPa/);

  // Both disclosures survive real edits and a full editor rerender independently.
  await basis.locator(":scope > summary").click();
  const focus = await input("free_length").evaluate((element) => {
    element.focus(); element.value = "20"; element.setSelectionRange(1, 1);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    return { focused: document.activeElement === element, caret: element.selectionStart };
  });
  assert.deepEqual(focus, { focused: true, caret: 1 });
  assert.equal(await basis.getAttribute("open"), null);
  assert.equal(await formulas.getAttribute("open"), "");
  await input("free_length").dispatchEvent("change");
  await page.evaluate(() => renderCompareOverlay());
  assert.equal(await basis.getAttribute("open"), null);
  assert.equal(await formulas.getAttribute("open"), "");
  await basis.locator(":scope > summary").click();
  await formulas.locator(":scope > summary").click();
  await edit("free_length", "19");
  assert.equal(await formulas.getAttribute("open"), null);
  await input("material").selectOption("65Mn");
  assert.notEqual(await value("unit_mass").innerText(), expected.unit_mass);
  await input("material").selectOption("SUS304");
  assert.equal(await value("unit_mass").innerText(), expected.unit_mass);

  const load = (id, role) => panel.locator(`[data-kind="load_point"][data-load-point-id="${id}"] [data-role="${role}"]`);
  await load("point-0", "force").fill("0"); await load("point-0", "force").dispatchEvent("change");
  assert.equal(await checks.locator('.compression-work-stress[data-load-point-id="point-0"] [data-role="design-check-value"]').innerText(), "0");
  await load("point-0", "force").fill("13.2"); await load("point-0", "force").dispatchEvent("change");
  await panel.locator('[data-action="show-load-point-create"]').click();
  await panel.locator('[data-role="new-load-label"]').fill("F3");
  await panel.locator('[data-role="new-load-height"]').fill("17");
  await panel.locator('[data-kind="load_point_create"]').evaluate((form) => form.requestSubmit());
  const added = await page.evaluate(() => state.review.spring_parameters.load_points.find((point) => point.label === "F3").load_point_id);
  const addedRow = checks.locator(`.compression-work-stress[data-load-point-id="${added}"]`);
  assert.equal(await addedRow.locator('[data-role="design-check-basis"]').textContent(), "估算载荷");
  await load(added, "rename-load-point").click();
  await load(added, "label").fill("F3-new"); await load(added, "save-load-label").click();
  await load(added, "rename-editor").waitFor({ state: "hidden" });
  assert.match(await addedRow.innerText(), /F3-new/);
  await load(added, "delete-load-point").click();
  assert.equal(await addedRow.count(), 0);
  assert.equal(await basis.getAttribute("open"), "");
  assert.equal(await formulas.getAttribute("open"), null);
  await flush(); await page.reload(); await reopen();
  await page.waitForFunction(() => state.materialCatalog.status === "ready");
  for (const [metric, result] of Object.entries(expected)) assert.equal(await value(metric).innerText(), result);

  assert.equal(await basis.getAttribute("open"), null, "Browser refresh resets basis to collapsed");
  await basis.locator(":scope > summary").click();

  // Provided zero solid force remains valid and does not invent a height basis.
  await page.evaluate(() => {
    state.review.spring_parameters.load_points.push({ load_point_id: "solid", label: "Fb", force: 0, force_unit: "N" });
    refreshCompressionDesignChecks(document, state.review);
  });
  assert.equal(await value("solid_stress").innerText(), "0");
  assert.equal(await checks.locator('[data-role="solid-load-note"]').innerText(), "压并应力依据：已有压并载荷 Pb = 0 N");
  await page.evaluate(() => { state.review.spring_parameters.load_points.pop(); refreshCompressionDesignChecks(document, state.review); });
  await edit("wire_diameter", "abc");
  assert.equal(await value("unit_mass").innerText(), "--");
  assert.ok((await checks.locator('[data-role="design-check-basis"][data-metric="unit_mass"]').textContent()).length > 4);
  await edit("wire_diameter", "1.8");
  await flush();

  const output = "outputs/design-check-compact-qa";
  fs.mkdirSync(output, { recursive: true });
  // Keep a surrounding parameter row in the capture to check the local type scale.
  await panel.locator('[data-kind="param"][data-field="end_grinding"]').evaluate((node) => {
    node.scrollIntoView({ block: "start" });
  });
  const contextStyles = await panel.evaluate((node) => ({
    parameterLabel: getComputedStyle(node.querySelector('.data-label strong')).fontSize,
    checkLabel: getComputedStyle(node.querySelector('.compression-design-primary th[scope="row"]')).fontSize,
    title: getComputedStyle(node.querySelector('.compression-design-check-head')).fontSize,
    basisLabel: getComputedStyle(node.querySelector('.compression-design-basis > summary')).fontSize,
  }));
  assert.equal(contextStyles.checkLabel, contextStyles.parameterLabel, "Check labels match surrounding parameter labels");
  assert.equal(contextStyles.title, "14px");
  assert.equal(contextStyles.basisLabel, "13px");
  await panel.screenshot({ path: `${output}/context.png` });

  // Capture the production component in isolation at a matching panel width.
  await page.evaluate(() => {
    document.body.innerHTML = renderCompressionDesignCheckHtml(state.review);
    document.documentElement.style.cssText = "height:auto;overflow:visible";
    document.body.style.cssText = "height:auto;overflow:visible;background:#fff";
    const container = document.querySelector('[data-kind="compression-design-check"]');
    container.style.margin = "0";
    bindCompressionDesignDisclosures(document, state.review);
  });
  const component = page.locator('[data-kind="compression-design-check"]');
  await page.setViewportSize({ width: 768, height: 1100 });
  const styles = await component.locator('.compression-design-primary').evaluate((table) => ({
    fontFamily: getComputedStyle(table).fontFamily,
    labels: [...table.querySelectorAll('th[scope="row"]')].map((node) => getComputedStyle(node).fontSize),
    values: [...table.querySelectorAll('[data-role="design-check-value"]')].map((node) => getComputedStyle(node).fontSize),
    units: [...table.querySelectorAll('[data-role="design-check-unit"]')].map((node) => getComputedStyle(node).fontSize),
  }));
  assert.ok(styles.labels.every((size) => size === "13px"));
  assert.ok(styles.values.every((size) => size === "14px"));
  assert.ok(styles.units.every((size) => size === "11.5px"));
  fs.writeFileSync(`${output}/typography.json`, JSON.stringify({ ...styles, context: contextStyles }, null, 2));
  assert.equal(await component.locator('thead .design-basis-column').isVisible(), true);
  await component.screenshot({ path: `${output}/desktop.png` });
  for (const width of [519, 390, 320]) {
    await page.setViewportSize({ width, height: 1500 });
    assert.equal(await component.locator('thead .design-basis-column').isVisible(), false);
    assert.equal(await component.locator('.design-mobile-basis').first().isVisible(), true);
    const overflow = await component.evaluate((node) => ({ panel: node.scrollWidth - node.clientWidth, page: document.documentElement.scrollWidth - innerWidth }));
    assert.ok(overflow.panel <= 1 && overflow.page <= 1, `No overflow at ${width}: ${JSON.stringify(overflow)}`);
    if (width === 390) await component.screenshot({ path: `${output}/narrow.png` });
  }
  await page.setViewportSize({ width: 768, height: 1500 });
  await component.locator('[data-design-disclosure="formulas"] > summary').click();
  await component.screenshot({ path: `${output}/formulas.png` });
  await page.evaluate(() => {
    const review = structuredClone(state.review);
    review.job_id = "exception-preview";
    review.spring_parameters.wire_diameter.value = "abc";
    document.body.innerHTML = renderCompressionDesignCheckHtml(review);
    document.querySelector('[data-kind="compression-design-check"]').style.margin = "0";
  });
  await component.screenshot({ path: `${output}/missing.png` });
  await page.setViewportSize({ width: 390, height: 1800 });
  assert.ok((await component.locator('[data-role="design-check-mobile-basis"][data-metric="unit_mass"]').innerText()).includes("线径"));
  assert.equal(await component.evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
  await component.screenshot({ path: `${output}/missing-narrow.png` });
  assert.deepEqual(errors, []);
  console.log("design check table: alignment, units, baseline, disclosures, live edits, async material, work points, missing/zero values, save/reopen and responsive screenshots passed");
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
