import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { catalogFixture, materialReviewFixture } from "./test_material_catalog_ui.mjs";

const require = createRequire(import.meta.url);
const { chromium } = process.env.CODEX_NODE_MODULES
  ? require(path.join(process.env.CODEX_NODE_MODULES, "playwright"))
  : require("C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const root = path.resolve("frontend"), output = path.resolve("outputs/material-catalog-qa");
const captureScreenshots = process.env.MATERIAL_TEST_SCREENSHOTS !== "0";
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((request, response) => {
  const file = path.resolve(root, request.url.split("?")[0].replace(/^\//, "") || "index.html");
  if (file !== path.join(root, "index.html") && !file.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
  if (!fs.existsSync(file)) { response.writeHead(404).end(); return; }
  response.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));

const materialRow = (page) => page.locator('.compare-tab-panel[data-compare-panel="parameters"] [data-kind="param"][data-field="material"]');
const materialSelect = (page) => materialRow(page).locator('select[data-role="value"][data-material-selector]');
const materialState = (page) => page.evaluate(() => structuredClone(state.review.spring_parameters.material));
const flush = (page) => page.evaluate(async () => { await flushReviewPersistence(); });

async function assertWideParameterInputs(page) {
  const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const wire = panel.locator('[data-kind="param"][data-field="wire_diameter"]');
  assert.equal(await wire.locator('[data-role="tolerance"]').isVisible(), true, "Numeric parameters retain empty tolerance controls");
  const reference = await wire.evaluate((row) => ({
    primary: row.querySelector(".data-primary").getBoundingClientRect().toJSON(),
    secondary: row.querySelector(".data-secondary").getBoundingClientRect().toJSON(),
    action: row.querySelector('[data-role="confirm"]').getBoundingClientRect().toJSON(),
  }));
  for (const field of ["material", "standard_no", "accuracy_grade"]) {
    const row = panel.locator(`[data-kind="param"][data-field="${field}"]`);
    assert.equal(await row.locator('[data-role="tolerance"]').count(), 1, "Existing editor bindings retain their control");
    assert.equal(await row.locator('[data-role="tolerance"]').isVisible(), false);
    const layout = await row.evaluate((element) => ({
      value: element.querySelector('[data-role="value"]').getBoundingClientRect().toJSON(),
      action: element.querySelector('[data-role="confirm"]').getBoundingClientRect().toJSON(),
    }));
    assert.ok(Math.abs(layout.value.left - reference.primary.left) < 1, `${field}: value starts in the original value column`);
    assert.ok(Math.abs(layout.value.right - reference.secondary.right) < 1, `${field}: value spans the original tolerance column`);
    assert.ok(Math.abs(layout.action.left - reference.action.left) < 1, `${field}: confirmation remains aligned`);
    assert.ok(layout.value.right < layout.action.left, `${field}: input does not crowd the action`);
  }
  for (const field of ["handedness", "end_type", "end_grinding"]) {
    const row = panel.locator(`[data-kind="param"][data-field="${field}"]`);
    assert.equal(await row.evaluate((element) => element.classList.contains("parameter-wide-input")), false, `${field}: not included in this change`);
  }
}

async function assertCompactMaterialRow(page) {
  const row = materialRow(page);
  assert.doesNotMatch(await row.innerText(), /当前材料：|原图材料：|公司材料表固定参考值/);
  const notes = row.locator(".material-selection-notes");
  assert.equal(await notes.isVisible(), false, "A selected material without warnings has no extra notes area");
  assert.equal(await notes.evaluate((element) => element.getBoundingClientRect().height), 0, "Hidden notes must not leave row padding or whitespace");
}

async function installApiMocks(page, options = {}) {
  const context = { review: materialReviewFixture(options.material), revision: 1, mutations: [], catalogRequests: 0, failCatalog: Boolean(options.failCatalog), failSave: false };
  Object.assign(context.review.spring_parameters, options.parameters || {});
  await page.route("**/api/**", async (route) => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body = {}, status = 200;
    if (apiPath === "/api/material-catalog") {
      context.catalogRequests += 1;
      if (context.failCatalog) { status = 503; body = { detail: "模拟材料目录请求失败" }; }
      else body = catalogFixture;
    } else if (request.method() === "PATCH") {
      const input = request.postDataJSON();
      context.mutations.push(input);
      if (context.failSave) { status = 503; body = { detail: "模拟保存失败" }; }
      else {
        context.review = input.review;
        body = { review_revision: ++context.revision, events: input.events.map((event) => ({ ...event, sync_status: "saved" })) };
      }
    } else if (apiPath === "/api/reviews/material-order") body = { ...context.review, job_id: "material-order", review_revision: context.revision, image_url: "" };
    else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "模拟测试用户" }, mode: "mock" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_input", summary: "模拟数据不发起生图", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 8, core_field_count: 8 }, generation_queue_available: false };
    else if (apiPath.endsWith("/generation-package")) {
      // Frozen server-format stub. The pure Python regression separately checks
      // the real backend contract and actual SolidWorks command.
      const param = context.review.spring_parameters.material;
      body = { parameter_package: { schema_version: "spring_generation_parameters/v2", generation_parameters: { spring_parameters: param.value && param.need_human_review === false ? { material: { label: "材料", value: param.value, unit: null, tolerance_upper: null, tolerance_lower: null, confirmation_source: "human_confirmed" } } : {} } } };
    } else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "demo", annotation_revision: 1, pages: [], annotations: [{ annotation_id: "material", field: "material", label: "材料", number: 1, original_value: "SUS304", locations: [], reason: "模拟数据无图纸位置" }, { annotation_id: "standard_no", field: "standard_no", label: "标准号", number: 2, original_value: null, locations: [], reason: "模拟数据无标准号位置" }], warnings: [] };
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  return context;
}

async function openReview(page) {
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.evaluate(async () => {
    await ensureMaterialCatalog();
    await openPersistedReview("material-order");
    state.compareTab = "parameters";
    renderCompareOverlay();
  });
  await page.waitForLoadState("networkidle");
  await materialSelect(page).waitFor({ state: "visible" });
}

async function downloadFromTab(page, tab) {
  await page.locator(`#compareOverlay [data-compare-tab="${tab}"]`).click();
  const button = page.locator(`.compare-tab-panel[data-compare-panel="${tab}"] [data-action="export-generation-package"]`);
  const downloaded = page.waitForEvent("download");
  await button.click();
  const download = await downloaded;
  const result = JSON.parse(fs.readFileSync(await download.path(), "utf8"));
  assert.equal(result.generation_parameters.spring_parameters.material.value, "SUS316 不锈钢", `${tab}: full material name is downloaded`);
  assert.ok(!("material_id" in result.generation_parameters.spring_parameters.material));
}

let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.UNIT_TEST_BROWSER_CHANNEL ? { channel: process.env.UNIT_TEST_BROWSER_CHANNEL } : {}) });
  for (const [size, width, height] of [["desktop", 1440, 1000], ["narrow", 1100, 900], ["mobile", 390, 900]]) {
    const page = await browser.newPage({ viewport: { width, height }, acceptDownloads: true });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const api = await installApiMocks(page);
    await openReview(page);
    assert.equal(await materialSelect(page).inputValue(), "SUS304 不锈钢");
    await assertCompactMaterialRow(page);
    await assertWideParameterInputs(page);
    const options = await materialSelect(page).locator("option").evaluateAll((items) => items.map((item) => ({ value: item.value, text: item.textContent, disabled: item.disabled })));
    assert.deepEqual(options.filter((item) => item.value).map((item) => item.value), catalogFixture.items.map((item) => item.display_name));
    assert.match(options.find((item) => item.value === "").text, /请选择材料/);
    assert.equal(options.length, 16, "Exactly 15 company options and one placeholder");
    assert.equal(await materialRow(page).locator(".parameter-label-unit").count(), 0);
    const before = await page.evaluate(() => JSON.stringify(state.review));
    await page.evaluate(() => { renderCompareOverlay(); renderCompareOverlay(); refreshMaterialCatalogControls(); });
    assert.equal(await page.evaluate(() => JSON.stringify(state.review)), before, "Rendering/loading options cannot mutate review content");
    assert.equal(api.mutations.length, 0, "Loading the directory must not save a review");
    await assertCompactMaterialRow(page);

    await materialSelect(page).selectOption("SUS316 不锈钢");
    await page.waitForFunction(() => state.review.spring_parameters.material.need_human_review === true);
    let selected = await materialState(page);
    assert.equal(selected.standard_value, "SUS316");
    assert.equal(String(selected.material_id), "5");
    assert.equal(selected.raw_value, "SUS304");
    assert.equal(selected.material_selection_source, "manual");
    await assertCompactMaterialRow(page);
    assert.equal(await page.evaluate(() => state.review.balloons.find((item) => item.field === "material").value), "SUS316 不锈钢");
    assert.equal(await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.spring_parameters.material), undefined, "Unconfirmed choice is not exported");
    await flush(page);
    assert.ok(api.mutations.length >= 1);
    await materialRow(page).locator('[data-role="confirm"]').click();
    await flush(page);
    assert.equal((await materialState(page)).need_human_review, false);
    await assertCompactMaterialRow(page);
    const singleAudit = api.mutations.flatMap((mutation) => mutation.events).find((event) => event.target_field === "material" && event.metadata?.material_selection);
    assert.ok(singleAudit, "Single material confirmation persists its selection audit");
    assert.equal(singleAudit.metadata.material_selection.raw_value, "SUS304");
    assert.equal(singleAudit.metadata.material_selection.standard_value, "SUS316");
    await page.evaluate(async () => { await openPersistedReview("material-order"); });
    assert.equal((await materialState(page)).raw_value, "SUS304", "Reopening retains original material data without showing an extra line");
    await assertCompactMaterialRow(page);
    const local = await page.evaluate(() => makeGenerationParameterPackage().generation_parameters.spring_parameters.material);
    assert.equal(local.value, "SUS316 不锈钢");
    assert.ok(!("material_id" in local));
    await downloadFromTab(page, "workbench");
    await downloadFromTab(page, "generation");
    await page.locator('#compareOverlay [data-compare-tab="parameters"]').click();

    await page.evaluate(() => focusMissingStandardizationField("material"));
    await page.waitForFunction(() => document.activeElement?.matches('select[data-material-selector]'));
    await materialSelect(page).press("Tab");
    assert.ok(await page.evaluate(() => document.activeElement?.closest('[data-field="standard_no"]')), "Tab skips the hidden tolerance and disabled confirmation control into the next parameter row");
    if (await materialRow(page).locator(".parameter-annotation-number").count()) {
      assert.equal(await materialRow(page).locator(".parameter-annotation-number").innerText(), "1");
      await materialRow(page).locator(".parameter-annotation-number").click();
    }
    const overflow = await materialRow(page).evaluate((row) => {
      const outer = row.getBoundingClientRect();
      return [...row.querySelectorAll("select, input, button")].some((control) => {
        const box = control.getBoundingClientRect();
        return box.width > 0 && (box.left < outer.left - 1 || box.right > outer.right + 1);
      });
    });
    assert.equal(overflow, false, `${size}: select, inputs and buttons fit inside the material row`);
    if (captureScreenshots) await page.screenshot({ path: path.join(output, `${size}.png`) });
    await materialSelect(page).selectOption("");
    await flush(page);
    selected = await materialState(page);
    assert.ok(selected.value == null || selected.value === "");
    assert.ok(selected.standard_value == null || selected.standard_value === "");
    assert.ok(selected.material_id == null || selected.material_id === "");
    assert.equal(selected.raw_value, "SUS304");
    assert.equal(selected.need_human_review, true);
    assert.equal(await materialRow(page).locator(".material-selection-notes").isVisible(), true);
    assert.match(await materialRow(page).locator(".material-selection-notes").innerText(), /请.*选择/);
    assert.equal(await materialRow(page).locator('[data-role="confirm"]').isDisabled(), true, "Empty selection cannot confirm");
    assert.deepEqual(errors, [], `${size}: no uncaught browser errors`);
    await page.close();
  }

  const tolerancePage = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const toleranceApi = await installApiMocks(tolerancePage, { parameters: {
    material: { ...materialReviewFixture().spring_parameters.material, tolerance_upper: 0, tolerance_lower: 0 },
    standard_no: { ...materialReviewFixture().spring_parameters.standard_no, tolerance_input_draft: "未完成公差" },
    accuracy_grade: { ...materialReviewFixture().spring_parameters.accuracy_grade, tolerance_upper: .1, tolerance_lower: -.1 },
  } });
  await openReview(tolerancePage);
  assert.equal(toleranceApi.mutations.length, 0, "Opening historical tolerances does not save or clear them");
  for (const field of ["material", "standard_no", "accuracy_grade"]) {
    const row = tolerancePage.locator(`.compare-tab-panel[data-compare-panel="parameters"] [data-kind="param"][data-field="${field}"]`);
    const tolerance = row.locator('[data-role="tolerance"]');
    assert.equal(await tolerance.isVisible(), true, `${field}: historical tolerance remains accessible`);
    await tolerance.fill("");
    await tolerance.press("Tab");
    await flush(tolerancePage);
    assert.equal(await tolerance.isVisible(), false, `${field}: clearing tolerance widens the value control`);
    const saved = toleranceApi.review.spring_parameters[field];
    assert.equal(saved.tolerance_upper, null);
    assert.equal(saved.tolerance_lower, null);
    assert.equal(saved.tolerance_input_draft, undefined);
    assert.ok(toleranceApi.mutations.flatMap((mutation) => mutation.events).some((event) => event.event_type === "parameter_tolerance_updated" && event.target_field === field), "Only user cleanup creates a tolerance audit");
  }
  await openReview(tolerancePage);
  await assertWideParameterInputs(tolerancePage);
  await tolerancePage.close();

  for (const [size, width, height] of [["narrow", 1100, 900], ["mobile", 390, 900]]) {
    const emptyPage = await browser.newPage({ viewport: { width, height } });
    const emptyApi = await installApiMocks(emptyPage, { parameters: {
      standard_no: { value: "", evidence: "", need_human_review: true, source: [] },
    } });
    await openReview(emptyPage);
    const standardRow = emptyPage.locator('.compare-tab-panel[data-compare-panel="parameters"] [data-kind="param"][data-field="standard_no"]');
    const badge = standardRow.locator('[data-annotation-field="standard_no"]');
    assert.equal(await badge.innerText(), "2", "Empty standard number keeps its fixed badge");
    const beforeFocus = await emptyPage.evaluate(() => JSON.stringify(state.review));
    await badge.focus();
    await badge.press("Enter");
    await emptyPage.waitForFunction(() => DrawingAnnotations.entry()?.selected === "standard_no");
    assert.equal(await emptyPage.evaluate(() => JSON.stringify(state.review)), beforeFocus, "Keyboard badge activation does not change parameters");
    assert.match(await emptyPage.evaluate(() => DrawingAnnotations.infoHtml()), /未找到可靠原图位置/);
    assert.equal(await emptyPage.evaluate(() => DrawingAnnotations.entry().document.annotations.find((item) => item.field === "standard_no").locations.length), 0, "Empty badges do not add drawing bubbles");
    assert.equal(emptyApi.mutations.length, 0);
    await openReview(emptyPage);
    assert.equal(await badge.innerText(), "2", "Reopening preserves the fixed empty-field number");
    const input = standardRow.locator('[data-role="value"]');
    await input.fill("GB/T 1239.2-2009");
    await input.press("Tab");
    await flush(emptyPage);
    await input.fill("");
    await input.press("Tab");
    await flush(emptyPage);
    await openReview(emptyPage);
    assert.equal(await input.inputValue(), "");
    assert.equal(await badge.innerText(), "2", "Clearing and saving the standard number does not remove its badge");
    await assertWideParameterInputs(emptyPage);
    if (captureScreenshots) await standardRow.screenshot({ path: path.join(output, `fixed-empty-standard-${size}.png`) });
    await emptyPage.close();
  }

  const historicalPage = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const original = "ХН70МВТЮБ ГОСТ 5632-72";
  const legacyApi = await installApiMocks(historicalPage, { material: { value: original, raw_value: original, standard_value: "ХН70МВТЮБ", material_id: null, material_selection_source: "legacy", material_match_status: "legacy" }, failCatalog: true });
  await openReview(historicalPage);
  assert.equal(await materialSelect(historicalPage).inputValue(), original);
  assert.equal(await materialSelect(historicalPage).isDisabled(), true);
  assert.equal((await materialState(historicalPage)).need_human_review, false);
  assert.equal(legacyApi.mutations.length, 0);
  const retry = materialRow(historicalPage).locator('[data-action="retry-material-catalog"]');
  await retry.waitFor({ state: "visible" });
  legacyApi.failCatalog = false;
  const focused = historicalPage.locator('.compare-tab-panel[data-compare-panel="parameters"] [data-field="wire_diameter"] [data-role="value"]');
  await focused.focus();
  await historicalPage.evaluate(async () => { await ensureMaterialCatalog({ force: true }); });
  await historicalPage.waitForFunction(() => state.materialCatalog.status === "ready");
  assert.equal(await focused.evaluate((element) => document.activeElement === element), true, "Directory retry must not lose unrelated keyboard focus");
  assert.equal(await materialSelect(historicalPage).inputValue(), original);
  assert.equal(await materialSelect(historicalPage).isDisabled(), false);
  const compatibility = materialSelect(historicalPage).locator("option", { hasText: "原有材料" });
  assert.equal(await compatibility.count(), 1);
  assert.equal(await compatibility.evaluate((element) => element.disabled), true, "Legacy compatibility item cannot be selected as a new grade");
  assert.equal(await compatibility.getAttribute("value"), original);
  assert.equal((await materialState(historicalPage)).value, original);
  assert.equal((await materialState(historicalPage)).need_human_review, false);
  assert.equal(legacyApi.mutations.length, 0);
  await assertCompactMaterialRow(historicalPage);
  if (captureScreenshots) await historicalPage.screenshot({ path: path.join(output, "legacy-preserved.png") });
  await historicalPage.close();

  const substitutePage = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const evidence = { value: "INCONEL750", evidence: "允许换用 INCONEL750 或类似材料", explicitly_allowed: true, page: 1 };
  const substituteApi = await installApiMocks(substitutePage, { material: { value: "Inconel X750 镍基合金钢", raw_value: original, standard_value: "Inconel X750", material_id: "10", need_human_review: true, source: ["qwen_vision"], material_selection_source: "drawing_substitute", material_match_status: "matched", material_substitution_evidence: evidence } });
  await openReview(substitutePage);
  assert.equal(await materialSelect(substitutePage).inputValue(), "Inconel X750 镍基合金钢");
  assert.doesNotMatch(await materialRow(substitutePage).innerText(), /当前材料：|原图材料：|公司材料表固定参考值/);
  const disclosure = materialRow(substitutePage).locator(".material-substitution-evidence");
  assert.equal(await disclosure.evaluate((element) => element.open), false, "Substitution evidence stays collapsed by default");
  await disclosure.locator("summary").click();
  assert.match(await disclosure.innerText(), /允许换用 INCONEL750/);
  assert.ok(await substitutePage.evaluate(() => buildSafeConfirmationPlan(state.review).items.some((item) => item.field === "material")), "Unique explicitly permitted substitute is batch-confirmable");
  await substitutePage.locator('.compare-tab-panel[data-compare-panel="parameters"] [data-action="confirm-all-review-items"]').click();
  await flush(substitutePage);
  assert.equal((await materialState(substitutePage)).need_human_review, false);
  const confirmationAudit = substituteApi.mutations.flatMap((mutation) => mutation.events).find((event) => event.event_type === "safe_fields_confirmed");
  assert.ok(confirmationAudit, "Batch confirmation is persisted in a single event");
  const acknowledgements = confirmationAudit.metadata.material_selection_acknowledgements;
  assert.ok(Array.isArray(acknowledgements) && acknowledgements.length === 1);
  assert.ok(JSON.stringify(acknowledgements).includes(original), "Audit retains original foreign grade");
  assert.ok(JSON.stringify(acknowledgements).includes("允许换用 INCONEL750"), "Audit retains substitute permission evidence");
  assert.equal(await substitutePage.evaluate(() => makeGenerationParameterPackage().generation_parameters.spring_parameters.material.value), "Inconel X750 镍基合金钢");
  await substitutePage.close();

  const unmatchedPage = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const unmatchedApi = await installApiMocks(unmatchedPage, { material: { value: "", raw_value: original, standard_value: "", material_id: null, need_human_review: true, source: ["qwen_vision"], material_selection_source: "drawing", material_match_status: "unmatched" } });
  await openReview(unmatchedPage);
  assert.equal(await materialSelect(unmatchedPage).inputValue(), "");
  assert.match(await materialRow(unmatchedPage).locator(".material-selection-notes").innerText(), /原图材料未匹配公司材料目录，请选择/);
  assert.equal((await materialState(unmatchedPage)).raw_value, original, "Unmatched original grade remains in data, not an extra material-row line");
  assert.equal(await materialRow(unmatchedPage).locator('[data-role="confirm"]').isDisabled(), true);
  assert.equal(unmatchedApi.mutations.length, 0);
  await unmatchedPage.close();

  const failedSavePage = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const failedSaveApi = await installApiMocks(failedSavePage);
  await openReview(failedSavePage);
  failedSaveApi.failSave = true;
  await materialSelect(failedSavePage).selectOption("SUS316 不锈钢");
  assert.equal(await failedSavePage.evaluate(async () => flushReviewPersistence()), false);
  assert.equal((await materialState(failedSavePage)).value, "SUS316 不锈钢", "Failed save retains the local final choice");
  assert.equal((await materialState(failedSavePage)).raw_value, "SUS304");
  assert.equal((await materialState(failedSavePage)).need_human_review, true);
  assert.equal(failedSaveApi.review.spring_parameters.material.value, "SUS304 不锈钢", "Failure does not pretend server changed");
  assert.ok(await failedSavePage.evaluate(() => state.pendingReviewAuditEvents.length > 0));
  failedSaveApi.failSave = false;
  assert.equal(await failedSavePage.evaluate(async () => flushReviewPersistence()), true);
  assert.equal(failedSaveApi.review.spring_parameters.material.value, "SUS316 不锈钢");
  assert.equal((await materialState(failedSavePage)).need_human_review, true, "Saving a selection never silently confirms it");
  await failedSavePage.close();

  console.log(`PASS: catalog select/edit/confirm, both downloads, pending omission, preserved legacy, directory/save failure retry, single/substitute batch audit, unknown-grade warning, focus/bubbles and desktop/narrow/mobile layout.${captureScreenshots ? ` Screenshots: ${output}` : " Screenshots disabled."}`);
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
