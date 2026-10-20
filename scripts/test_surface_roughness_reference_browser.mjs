import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES ? path.join(process.env.CODEX_NODE_MODULES, "playwright") : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const cases = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe", ["scripts/test_solidworks_export.py", "--json"], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const pairedFixture = "outputs/roughness-v3-qa/891b8f3b749f";
const frontend = path.resolve("frontend"), server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, "http://localhost").pathname.slice(1) || "index.html");
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.UNIT_TEST_BROWSER_CHANNEL || "msedge" });
  const page = await browser.newPage(), errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let saved = structuredClone(cases[0].review), revision = 1, released = false;
  saved.spring_parameters.surface_roughness_ra = { value: null, unit: "μm", source: [], evidence: "", page: 1, position: null, need_human_review: true };
  let failNextPatch = false, holdNextPatch = false, heldPatchRelease = null;
  let annotationDocument = null, relocalizeUpdate = null, holdRelocalize = false, releaseRelocalize = null;
  // A confirmed human height starts independently of formula snapshot migration.
  Object.assign(saved.spring_parameters.solid_height, { source: ["manual"], value_kind: "input_height" });
  let release;
  const gate = new Promise((resolve) => { release = () => { released = true; resolve(); }; });
  await page.route("**/api/**", async (route) => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body;
    if (apiPath.endsWith("/artifacts/positive.png")) return route.fulfill({ contentType: "image/png", body: fs.readFileSync(`${pairedFixture}/pages/page-1.png`) });
    if (apiPath === "/api/material-catalog") { if (!released) await gate; body = catalog; }
    else if (apiPath === "/api/reviews/sw-export" && request.method() === "PATCH") {
      const input = request.postDataJSON();
      if (failNextPatch) { failNextPatch = false; return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "模拟保存失败" }) }); }
      if (holdNextPatch) { holdNextPatch = false; await new Promise((resolve) => { heldPatchRelease = resolve; }); }
      assert.equal(input.expected_revision, revision);
      saved = input.review;
      body = { review_revision: ++revision, events: (input.events || []).map((event) => ({ ...event, sync_status: "saved" })) };
    } else if (apiPath === "/api/reviews/roughness-other") body = { ...structuredClone(cases[0].review), job_id: "roughness-other", review_revision: 1, image_url: "" };
    else if (apiPath === "/api/reviews/sw-export") body = { ...saved, job_id: "sw-export", review_revision: revision, image_url: "" };
    else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "SW JSON 测试" }, mode: "mock" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_confirmation", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 8, core_field_count: 8 }, generation_queue_available: false };
    else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations/relocalize")) {
      const reply = { ...structuredClone(annotationDocument), roughness_update: { based_on_revision: revision, parameter: structuredClone(relocalizeUpdate) } };
      if (holdRelocalize) await new Promise((resolve) => { releaseRelocalize = resolve; });
      body = reply;
    }
    else if (apiPath.endsWith("/annotations")) {
      if (request.method() === "PATCH") {
        const patch = request.postDataJSON();
        assert.equal(patch.expected_annotation_revision, annotationDocument.annotation_revision);
        for (const change of patch.changes) {
          const a = annotationDocument.annotations.find((a) => a.annotation_id === change.annotation_id);
          let l = a.locations.find((l) => l.location_id === change.location_id);
          if (!l) { l = { location_id: change.location_id, source: "manual", bbox: null }; a.locations.push(l); }
          Object.assign(l, { page: change.page, anchor: change.anchor, bubble: change.bubble, source: "manual" });
          a.status = "located"; a.reason = "";
        }
        annotationDocument.annotation_revision++;
      }
      body = annotationDocument || { schema_version: "original_annotations/v1", source_document_id: "test", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
    }
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto(process.env.SW_EXPORT_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  const reopen = () => page.evaluate(async (imageUrl) => { await openPersistedReview("sw-export"); if (imageUrl) { state.imageUrl = toBackendAssetUrl(imageUrl); const context = state.reviewContexts[state.activeReviewMessageId]; if (context) context.imageUrl = state.imageUrl; } state.compareTab = "parameters"; renderCompareOverlay(); }, annotationDocument?.pages?.[0]?.image_url);
  await reopen();
  const preview = () => page.evaluate(() => makeGenerationParameterPackage().solidworks_preview);
  release(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
  const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const row = panel.locator('[data-kind="param"][data-field="surface_roughness_ra"]');
  const input = row.locator('[data-role="value"]');
  const action = (name, value = 12.5) => row.locator(`[data-action="${name}-roughness-reference"]${name === "adopt" ? `[data-reference-value="${value}"]` : ""}`);
  const flush = () => page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  const waitHeld = async () => { for (let n = 0; n < 250 && !heldPatchRelease; n++) await new Promise((resolve) => setTimeout(resolve, 20)); assert.ok(heldPatchRelease, "Expected held PATCH after adoption"); };
  const reset = async (extra = {}, end = {}, base = cases[0].review) => {
    assert.equal(await flush(), true);
    saved = structuredClone(base); revision++;
    saved.technical_requirements = saved.technical_requirements.filter((item) => !["surface_roughness", "roughness"].includes(item.type));
    Object.assign(saved.spring_parameters.solid_height, { source: ["manual"], value_kind: "input_height" });
    Object.assign(saved.spring_parameters, end);
    saved.spring_parameters.surface_roughness_ra = { value: null, unit: "μm", source: [], evidence: "", page: 1, position: null, need_human_review: true, ...extra };
    await page.reload(); await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
  };
  for (const value of [12.5, 6.3]) for (const end of [{}, { end_type: { value: "两端不并紧", need_human_review: false }, end_grinding: { value: "两端不磨削", need_human_review: false } }, { end_type: { value: null }, end_grinding: { value: null } }]) {
    await reset({}, end);
    assert.equal(await action("adopt").count(), 1);
    assert.equal(await row.locator('[data-action="adopt-roughness-reference"]').count(), 2);
    assert.equal(await action("customize").count(), 0);
    assert.equal(await input.inputValue(), "");
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], undefined);
    await action("adopt", value).click();
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], undefined);
    await row.locator('[data-role="confirm"]').click();
    assert.equal(await flush(), true);
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], value);
  }
  for (const extra of [{ value: 6.3 }, { value: 0 }, { value: -1 }, { roughness_conflict: true, roughness_candidates: [{ value: 6.3 }, { value: 12.5 }] }, { derived_value_stale: true }]) {
    await reset(extra);
    assert.equal(await action("adopt").count(), 0, "Recognized, invalid, stale and conflicting values are protected");
  }
  await reset({ source: ["human_edited"] });
  assert.equal(await action("show").count(), 1, "Old human clears start collapsed");
  await reset({ confirmation_snapshot: { kind: "parameter", value: 12.5, tolerance_upper: null, tolerance_lower: null } });
  const technicalCount = await panel.locator('[data-kind="technical"]').count();
  await action("adopt").click();
  assert.equal(await input.inputValue(), "12.5");
  assert.equal(await input.evaluate((el) => document.activeElement === el), true);
  assert.ok((await row.textContent()).includes("人工采用项目参考"));
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], undefined);
  assert.equal(await page.evaluate(() => state.review.spring_parameters.surface_roughness_ra.need_human_review), true);
  assert.equal(await page.evaluate(() => state.review.spring_parameters.surface_roughness_ra.confirmation_snapshot), undefined);
  assert.equal(await panel.locator('[data-kind="technical"]').count(), technicalCount);
  assert.equal(await flush(), true);
  assert.equal(saved.spring_parameters.surface_roughness_ra.evidence, "");
  assert.equal(saved.spring_parameters.surface_roughness_ra.position, null);
  assert.equal(saved.spring_parameters.surface_roughness_ra.surface_location, "两端面");
  await row.locator('[data-role="confirm"]').click();
  assert.equal(await flush(), true);
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 12.5);
  assert.ok(!(await preview()).extraProperties["技术要求"].includes("粗糙度"));
  await page.reload(); await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 12.5);
  await input.fill("6.3");
  await row.locator('[data-role="confirm"]').click();
  assert.equal(await flush(), true);
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 6.3);
  assert.ok((await row.textContent()).includes("人工填写"));
  assert.ok(!saved.spring_parameters.surface_roughness_ra.source.includes("human_roughness_reference"));
  await input.fill(""); await input.blur();
  assert.equal(await flush(), true);
  assert.equal(await action("show").count(), 1);
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], undefined);
  await page.reload(); await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
  assert.equal(await input.inputValue(), ""); assert.equal(await action("show").count(), 1);
  await action("show").click(); await input.click();
  assert.equal(await input.evaluate((el) => document.activeElement === el), true);
  await input.fill("3.2"); await row.locator('[data-role="confirm"]').click();
  assert.equal(await flush(), true);
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 3.2);
  await reset();
  failNextPatch = true;
  await action("dismiss").click();
  assert.equal(await page.evaluate(() => flushReviewPersistence()), false);
  assert.equal(await action("show").count(), 1);
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.action), "show-roughness-reference", "Persistence updates preserve the focused action");
  assert.ok((await row.textContent()).includes("保存失败"));
  await row.locator('[data-action="retry-roughness-reference-save"]').click();
  assert.equal(await flush(), true);
  assert.equal(saved.spring_parameters.surface_roughness_ra.roughness_reference_dismissed, true);
  await page.reload(); await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
  assert.equal(await action("show").count(), 1); assert.equal(await action("adopt").count(), 0);
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], undefined);
  await action("show").click(); await action("adopt").click();
  assert.equal(await flush(), true);
  assert.equal(await page.evaluate(() => buildSafeConfirmationPlan(state.review).items.some((item) => item.field === "surface_roughness_ra")), true);
  await panel.locator('[data-action="confirm-all-review-items"]').click();
  assert.equal(await flush(), true);
  assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 12.5);
  assert.ok((await row.textContent()).includes("已确认"));
  await input.fill(""); await input.blur(); assert.equal(await flush(), true);
  await action("show").click();
  holdNextPatch = true;
  await action("adopt").click();
  await page.evaluate(() => { void flushReviewPersistence(); });
  await waitHeld();
  await input.fill("3.2"); await input.blur();
  heldPatchRelease(); heldPatchRelease = null;
  assert.equal(await flush(), true);
  assert.equal(saved.spring_parameters.surface_roughness_ra.value, 3.2, "A late adoption response cannot overwrite a newer custom value");
  await input.fill(""); await input.blur(); assert.equal(await flush(), true);
  await action("show").click();
  holdNextPatch = true;
  await action("adopt").click(); await page.evaluate(() => { void flushReviewPersistence(); });
  await waitHeld();
  const switching = page.evaluate(async () => { await openPersistedReview("roughness-other"); state.compareTab = "parameters"; renderCompareOverlay(); });
  heldPatchRelease(); heldPatchRelease = null;
  await switching;
  await page.waitForFunction(() => !state.reviewPersistenceSaving);
  assert.equal(await input.inputValue(), "12.5");
  assert.equal(await page.evaluate(() => state.lastJob.job_id), "roughness-other");
  assert.equal(await page.evaluate(() => state.review.spring_parameters.surface_roughness_ra.need_human_review), false, "An old order's pending adoption cannot change the current order's confirmation");
  await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
  assert.equal(await page.evaluate(() => state.review.spring_parameters.surface_roughness_ra.need_human_review), true);
  await reset();
  if (process.env.ROUGHNESS_LEGACY_REVIEW) {
    const original = fs.readFileSync(process.env.ROUGHNESS_LEGACY_REVIEW);
    saved = JSON.parse(original); revision++;
    await page.reload(); await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
    assert.equal(await action("adopt").count(), 1, "A real saved legacy review with missing Ra offers the reference");
    await action("adopt").click();
    assert.equal(await flush(), true);
    assert.equal(saved.spring_parameters.surface_roughness_ra.value, 12.5);
    assert.equal(saved.spring_parameters.surface_roughness_ra.need_human_review, true);
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], undefined);
    assert.deepEqual(fs.readFileSync(process.env.ROUGHNESS_LEGACY_REVIEW), original, "Offline acceptance never changes the real order file");
    await reset();
  }
  fs.mkdirSync("outputs/roughness-reference-qa", { recursive: true });
  for (const width of process.env.SKIP_UI_QA_SCREENSHOTS ? [] : [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    await row.scrollIntoViewIfNeeded();
    assert.equal(await row.evaluate((el) => el.scrollWidth > el.clientWidth + 2), false);
    await row.screenshot({ path: `outputs/roughness-reference-qa/reference-${width}.png` });
  }
  const longEvidence = "示意图两端面处标有表面粗糙度符号，Ra12.5或Ra6.3。我们再看，surface_roughness_ra不能根据猜测填入，need_human_review=true。";
  const oldRoughness = { value: 6.3, evidence: longEvidence, source: ["qwen_vision"], need_human_review: true,
    roughness_candidates: [{ value: 12.5, location: "两端面", evidence: longEvidence, page: 1, source: "qwen_vision" }, { value: 6.3, location: "端面", evidence: longEvidence, page: 1 }] };
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 }); await reset(oldRoughness);
    assert.equal(await action("adopt").count(), 0);
    assert.equal(await input.inputValue(), "6.3");
    const before = await page.evaluate(() => JSON.stringify(state.review.spring_parameters.surface_roughness_ra));
    const details = row.locator('[data-role="roughness-evidence"]');
    assert.equal(await details.count(), 1);
    assert.equal(await details.getAttribute("open"), null);
    assert.equal(await details.locator('.roughness-evidence-entry').count(), 1, "The full original is not repeated per candidate");
    assert.equal(await row.locator('.roughness-candidates button[title]').count(), 0);
    assert.ok(!(await row.locator('.data-label').textContent()).includes('need_human_review'));
    assert.equal(await page.evaluate(() => JSON.stringify(state.review.spring_parameters.surface_roughness_ra)), before);
    await row.scrollIntoViewIfNeeded();
    assert.equal(await row.evaluate((el) => el.scrollWidth > el.clientWidth + 2), false);
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await row.screenshot({ path: `outputs/roughness-reference-qa/compact-${width}.png` });
    await details.locator('summary').press('Enter');
    await input.fill('3.2'); await input.blur(); assert.equal(await flush(), true);
    assert.equal(await details.getAttribute('open'), "", "Editing preserves disclosure state");
    await page.evaluate(() => renderCompareOverlay());
    assert.equal(await details.getAttribute('open'), "", "Rerender preserves disclosure state in the page session");
    assert.ok((await details.textContent()).includes(longEvidence));
    assert.equal((await preview()).titleBlockProperties['表面粗糙度'], undefined);
    assert.equal(await row.locator('[data-role="roughness-candidate"]').count(), 0, "Unverified values have no quick adoption");
    await input.fill('12.5'); await input.blur();
    await row.locator('[data-role="confirm"]').click(); assert.equal(await flush(), true);
    assert.equal((await preview()).titleBlockProperties['表面粗糙度'], 12.5);
    await page.reload(); await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
    assert.equal((await preview()).titleBlockProperties['表面粗糙度'], 12.5);
    assert.equal(await details.getAttribute('open'), null, "Reload starts with the original evidence collapsed");
    assert.equal(saved.spring_parameters.surface_roughness_ra.evidence, longEvidence);
  }
  const verifiedFixture = "outputs/roughness-verification-qa/3b6ab8b8b7f9/verified_review.json";
  if (fs.existsSync(verifiedFixture)) {
    const corrected = JSON.parse(fs.readFileSync(verifiedFixture, "utf8")).spring_parameters.surface_roughness_ra;
    await reset(corrected);
    assert.equal(await input.inputValue(), "");
    assert.equal(await row.locator('[data-role="roughness-candidate"]').count(), 0);
    assert.equal(await action("adopt").count(), 0, "An unverified model value is not a missing value");
    assert.ok(!(await row.innerText()).includes("3.2"), "Suspected numbers stay inside the collapsed evidence");
    const evidence = row.locator('[data-role="roughness-evidence"]');
    assert.equal(await evidence.getAttribute("open"), null);
    assert.equal(await evidence.locator('.roughness-evidence-entry').count(), 1);
    assert.equal(await flush(), true);
    assert.ok(saved.change_history.some((e) => e.event_type === "roughness_evidence_verified"));
    assert.equal(saved.spring_parameters.surface_roughness_ra.value, null);
    const count = saved.change_history.filter((e) => e.event_type === "roughness_evidence_verified").length;
    await page.reload(); await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
    assert.equal(await flush(), true);
    assert.equal(saved.change_history.filter((e) => e.event_type === "roughness_evidence_verified").length, count);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1100 }); await row.scrollIntoViewIfNeeded();
      assert.equal(await row.evaluate((el) => el.scrollWidth > el.clientWidth + 2), false);
      if (!process.env.SKIP_UI_QA_SCREENSHOTS) await row.screenshot({ path: `outputs/roughness-reference-qa/verified-${width}.png` });
    }
    await evidence.locator('summary').click();
    assert.ok((await evidence.innerText()).includes("疑似 Ra 3.2"));
    await input.fill('3.2'); await input.blur(); await row.locator('[data-role="confirm"]').click();
    assert.equal(await flush(), true);
    assert.equal((await preview()).titleBlockProperties['表面粗糙度'], 3.2, "Manual input remains confirmable");
  }
  const positiveFixture = `${pairedFixture}/v3_review.json`;
  if (fs.existsSync(positiveFixture)) {
    const positiveReview = JSON.parse(fs.readFileSync(positiveFixture, "utf8"));
    const positive = positiveReview.spring_parameters.surface_roughness_ra;
    annotationDocument = JSON.parse(fs.readFileSync(`${pairedFixture}/v3_annotations.json`, "utf8"));
    annotationDocument.pages[0].image_url = "/api/reviews/sw-export/artifacts/positive.png";
    const pairedAnnotations = structuredClone(annotationDocument);
    await reset({ ...positive, need_human_review: true }, {}, positiveReview);
    await page.waitForFunction(() => DrawingAnnotations.entry()?.document?.pages?.length && document.querySelectorAll('.annotation-bubble[data-annotation-id="surface_roughness_ra"]').length === 2);
    assert.equal(await input.inputValue(), "12.5");
    assert.equal(await action("adopt").count(), 0);
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], undefined);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1100 }); await row.scrollIntoViewIfNeeded();
      assert.equal(await row.evaluate((el) => el.scrollWidth > el.clientWidth + 2), false);
      if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: `outputs/roughness-reference-qa/restored-${width}.png` });
    }
    await row.locator('[data-role="confirm"]').click(); assert.equal(await flush(), true);
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 12.5);
    const valueOnly = { ...positive, need_human_review: true, value_verified: true, recognition_state: "needs_location", position: null,
      roughness_candidates: positive.roughness_candidates.map((c) => ({ ...c, evidence_status: "unverified", verification_method: "needs_location", recognition_state: "needs_location", independent_evidence: [], position: null })) };
    for (const a of annotationDocument.annotations) if (a.field === "surface_roughness_ra") { a.locations = []; a.status = "unlocated"; a.reason = "数值已核实，位置待核对"; }
    await reset(valueOnly, {}, positiveReview);
    await page.waitForFunction(() => DrawingAnnotations.entry()?.document?.pages?.length && document.querySelector('#compareImage')?.naturalWidth);
    assert.equal(await input.inputValue(), "12.5");
    assert.ok((await row.textContent()).includes("数值已核实，位置待核对"));
    assert.equal(await action("adopt").count(), 0);
    assert.equal(await page.locator('.annotation-bubble[data-annotation-id="surface_roughness_ra"]').count(), 0);
    await row.locator('[data-role="confirm"]').click(); assert.equal(await flush(), true);
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 12.5, "Position ambiguity does not block a confirmed verified scalar");
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.locator('.annotation-unlocated summary').click();
    await page.locator('[data-annotation-place="surface_roughness_ra"]').last().click();
    await page.locator('#compareViewport').scrollIntoViewIfNeeded();
    const anchor = pairedAnnotations.annotations.find((a) => a.field === "surface_roughness_ra").locations[0].anchor;
    const point = await page.evaluate((p) => DrawingAnnotations.screenPoint(p), anchor), viewport = await page.locator('#compareViewport').boundingBox();
    await page.mouse.click(viewport.x + point.x, viewport.y + point.y);
    await page.evaluate(() => DrawingAnnotations.save());
    assert.equal(annotationDocument.annotations.find((a) => a.field === "surface_roughness_ra").locations[0].source, "manual");
    await page.reload(); await reopen();
    await page.waitForFunction(() => document.querySelectorAll('.annotation-bubble[data-annotation-id="surface_roughness_ra"]').length === 1);
    assert.equal((await preview()).titleBlockProperties["表面粗糙度"], 12.5);
    annotationDocument = structuredClone(pairedAnnotations);
    const pending = { ...positive, value: null, need_human_review: true, recognition_state: "failed",
      roughness_candidates: positive.roughness_candidates.map((c) => ({ ...c, evidence_status: "unverified", recognition_state: "failed", independent_evidence: [] })) };
    await reset(pending);
    assert.equal(await action("adopt").count(), 0);
    assert.ok((await row.textContent()).includes("核验失败"));
    relocalizeUpdate = { ...positive, need_human_review: true };
    await page.evaluate(() => DrawingAnnotations.relocalize());
    assert.equal(await input.inputValue(), "12.5", "Retry synchronizes the roughness draft");
    assert.equal(await flush(), true);
    await reset(pending);
    holdRelocalize = true;
    const retry = page.evaluate(() => DrawingAnnotations.relocalize());
    for (let n = 0; n < 250 && !releaseRelocalize; n++) await new Promise((resolve) => setTimeout(resolve, 20));
    assert.ok(releaseRelocalize);
    await input.fill("6.3"); await input.blur();
    releaseRelocalize(); await retry;
    assert.equal(await input.inputValue(), "6.3", "Late OCR must preserve a newer manual edit");
    assert.equal(await flush(), true);
    holdRelocalize = false;
  }
  assert.deepEqual(errors, []);
  console.log("PASS: roughness reference native adoption/confirmation, custom values, decline/reopen, failures, races, cross-order protection and responsive layout");
} finally { await browser?.close(); await new Promise((resolve) => server.close(resolve)); }
