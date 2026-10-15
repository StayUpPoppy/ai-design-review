import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES ? path.join(process.env.CODEX_NODE_MODULES, "playwright") : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const python = process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe";
const cases = JSON.parse(execFileSync(python, ["scripts/test_solidworks_export.py", "--json"], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const baseline = () => {
  const review = structuredClone(cases[0].review);
  review.spring_parameters.load_points = [
    { load_point_id: "one", label: "F1", height: 21.15, height_unit: "mm", force: 16, force_unit: "N", load_tolerance_percent: 10, need_human_review: false, source: ["human_confirmed"], evidence: "原图 H1/F1 ±10%", confirmation_snapshot: { kind: "load_point", height: 21.15, force: 16, load_tolerance_percent: 10 } },
    { load_point_id: "two", label: "F2", height: 9.668, height_unit: "mm", force: 35, force_unit: "N", load_tolerance_percent: 10, need_human_review: false, source: ["human_confirmed"] },
  ];
  Object.assign(review, { technical_requirements: [], manual_confirmations: {}, standardization_results: [], change_history: [] });
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
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const errors = [], requests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let saved = baseline(), revision = 1, failNext = false, holdNext = false, releasePatch;
  await page.route("**/api/**", async (route) => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body;
    if (apiPath === "/api/material-catalog") body = catalog;
    else if (apiPath === "/api/reviews/rename" && request.method() === "PATCH") {
      const input = request.postDataJSON(); requests.push(input);
      if (holdNext) { holdNext = false; await new Promise((resolve) => { releasePatch = resolve; }); }
      if (failNext) { failNext = false; return route.fulfill({ status: 503, json: { detail: "模拟保存失败" } }); }
      if (input.expected_revision !== revision) return route.fulfill({ status: 409, json: { detail: "版本冲突" } });
      saved = input.review;
      body = { review_revision: ++revision, events: input.events.map((event) => ({ ...event, sync_status: "saved" })) };
    } else if (apiPath === "/api/reviews/rename") body = { ...saved, job_id: "rename", review_revision: revision, image_url: "" };
    else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "载荷点改名测试" }, mode: "mock" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_confirmation", warnings: [], missing_fields: [], pending_fields: [] }, generation_queue_available: false };
    else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "test", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ status: 200, json: body });
  });
  await page.goto(process.env.LOAD_POINT_RENAME_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  const reopen = () => page.evaluate(async () => { await openPersistedReview("rename"); state.compareTab = "parameters"; renderCompareOverlay(); });
  await reopen(); await page.waitForFunction(() => state.materialCatalog.status === "ready");
  const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const row = (id = "one") => panel.locator(`[data-kind="load_point"][data-load-point-id="${id}"]`);
  const control = (role, id = "one") => row(id).locator(`[data-role="${role}"]`);
  const current = (id = "one") => page.evaluate((id) => structuredClone(state.review.spring_parameters.load_points.find((point) => point.load_point_id === id)), id);
  const flush = async () => assert.equal(await page.evaluate(() => flushReviewPersistence({ throwOnError: true })), true);
  const openEditor = async (label, id = "one") => { await control("rename-load-point", id).click(); await control("label", id).fill(label); };
  const settled = (id = "one") => control("rename-editor", id).waitFor({ state: "hidden" });
  const confirm = async (id = "one") => { await control("confirm", id).click(); await flush(); };
  const outputLabels = () => page.evaluate(() => makeGenerationParameterPackage().generation_parameters.load_points.map((point) => point.label));

  // Native input/blur never commits or revokes the confirmed point. Cancel/Escape discard drafts.
  const original = await current();
  await openEditor("F3"); await control("height").click();
  assert.deepEqual(await current(), original);
  assert.equal(await control("label").inputValue(), "F3");
  await page.evaluate(() => renderCompareOverlay());
  assert.equal(await control("label").inputValue(), "F3", "Rerender preserves the draft");
  await control("cancel-load-label").click(); assert.deepEqual(await current(), original);
  await openEditor("F3"); await control("label").press("Escape"); await settled();
  assert.deepEqual(await current(), original);
  await openEditor("  F1  "); await control("save-load-label").click(); await settled();
  assert.equal(requests.length, 0, "Unchanged normalized label is a true no-op");
  for (const invalid of [" ", " f2 ", "F2"]) {
    await openEditor(invalid); await control("save-load-label").click();
    assert.equal(await control("label").getAttribute("aria-invalid"), "true");
    assert.match(await control("rename-status").innerText(), /不能为空|已存在/);
    assert.deepEqual(await current(), original);
    await control("cancel-load-label").click();
  }

  // Explicit save and legacy snapshot upgrade, followed by independent confirmation.
  holdNext = true;
  await openEditor("F3"); await control("save-load-label").click();
  await page.waitForFunction(() => document.querySelector('.compare-tab-panel [data-role="save-load-label"]')?.textContent === "保存中…");
  assert.equal(await control("save-load-label").isDisabled(), true);
  assert.equal(await control("label").isDisabled(), true);
  while (!releasePatch) await new Promise((resolve) => setTimeout(resolve, 10));
  releasePatch(); await settled();
  const renamed = await current();
  assert.equal(renamed.label, "F3"); assert.equal(renamed.need_human_review, true);
  assert.equal(renamed.confirmation_snapshot.label, "F1");
  assert.equal(renamed.confirmation_snapshot.height_unit, "mm");
  assert.equal(renamed.confirmation_snapshot.force_unit, "N");
  for (const key of ["load_point_id", "height", "force", "height_unit", "force_unit", "load_tolerance_percent", "evidence"]) assert.deepEqual(renamed[key], original[key]);
  assert.equal(await control("confirm").innerText(), "确认修改");
  assert.deepEqual(await outputLabels(), ["F2"], "Unconfirmed rename is excluded from new SW input");
  assert.match(await panel.locator('.compression-work-stress[data-load-point-id="one"]').innerText(), /F3 工作应力/);
  assert.match(await control("force").getAttribute("aria-label"), /^F3/);
  const event = saved.change_history.find((event) => event.metadata?.new_label === "F3");
  assert.equal(event.metadata.load_point_id, "one"); assert.equal(event.before_state.label, "F1"); assert.equal(event.after_state.label, "F3");
  await confirm();
  assert.deepEqual(await outputLabels(), ["F3", "F2"]);
  await page.reload(); await reopen();
  assert.equal((await current()).label, "F3"); assert.equal(await control("confirm").innerText(), "已确认");
  const frozenPreview = await page.evaluate(() => makeGenerationParameterPackage().solidworks_preview);

  // Failed rename remains editable and retryable; no confirmation on a partial point.
  failNext = true;
  await openEditor("  检验   A  "); await control("label").press("Enter");
  await control("save-load-label").filter({ hasText: "重试保存" }).waitFor();
  assert.match(await control("rename-status").innerText(), /保存失败/);
  assert.equal((await current()).label, "检验 A");
  await control("save-load-label").click(); await settled();
  assert.equal(await control("confirm").innerText(), "确认修改"); await confirm();
  assert.deepEqual(await outputLabels(), ["检验 A", "F2"]);
  await page.evaluate(() => {
    state.review.spring_parameters.load_points.push({ load_point_id: "partial", label: "待补齐", height: null, force: null, need_human_review: true,
      confirmation_snapshot: { kind: "load_point", height: null, force: null } });
    renderCompareOverlay();
  });
  await openEditor("工况 B", "partial"); await control("save-load-label", "partial").click(); await settled("partial");
  assert.equal((await current("partial")).need_human_review, true);
  assert.equal(await control("confirm", "partial").isDisabled(), true);
  assert.deepEqual(await outputLabels(), ["检验 A", "F2"]);

  // Non-overlapping server changes merge by point ID, then same-point changes require a choice.
  saved.spring_parameters.load_points.find((point) => point.load_point_id === "two").force = 36; revision++;
  await openEditor("F4"); await control("save-load-label").click(); await settled();
  assert.equal((await current("two")).force, 36);
  assert.equal((await current()).label, "F4"); await confirm();
  saved.spring_parameters.load_points.find((point) => point.load_point_id === "one").label = "服务器工况"; revision++;
  await openEditor("F5"); await control("save-load-label").click();
  const dialog = page.getByRole("dialog", { name: /参数保存冲突/ });
  await dialog.waitFor(); assert.match(await dialog.innerText(), /服务器工况/);
  await dialog.getByRole("button", { name: "保留我的值并保存" }).click(); await settled();
  assert.equal((await current()).label, "F5");

  // A different point may claim a label concurrently. Never persist duplicate labels after merge.
  saved.spring_parameters.load_points.find((point) => point.load_point_id === "two").label = "F8"; revision++;
  await openEditor("F8"); await control("save-load-label").click();
  await control("save-load-label").filter({ hasText: "重试保存" }).waitFor();
  assert.match(await control("rename-status").innerText(), /服务器.*重复/);
  assert.equal(saved.spring_parameters.load_points.find((point) => point.load_point_id === "one").label, "F5");
  await control("label").fill("F9"); await control("save-load-label").click(); await settled(); await confirm();
  assert.deepEqual(await outputLabels(), ["F9", "F8"]);

  // Backend recalculates the same export from the saved snapshot; a previously frozen payload stays unchanged.
  const frontendPreview = await page.evaluate(() => makeGenerationParameterPackage().solidworks_preview);
  const backendPreview = JSON.parse(execFileSync(python, ["-c", "import json,sys;sys.path.insert(0,'src');from ai_design_review.generation_readiness import build_generation_parameter_package;sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8');print(json.dumps(build_generation_parameter_package(json.load(sys.stdin))['solidworks_preview'],ensure_ascii=False))"], { input: JSON.stringify(saved), encoding: "utf8" }));
  assert.equal(frontendPreview.extraProperties["技术要求"], backendPreview.extraProperties["技术要求"]);
  assert.match(frontendPreview.extraProperties["技术要求"], /F9 = 16 N/);
  assert.ok(frozenPreview.extraProperties["技术要求"].includes("F3 = 16 N"));
  assert.ok(!frozenPreview.extraProperties["技术要求"].includes("F9"));

  // Batch visual check at the supported desktop and narrow panel widths.
  const output = "outputs/load-point-rename-qa"; fs.mkdirSync(output, { recursive: true });
  await openEditor("工况 C");
  await row().scrollIntoViewIfNeeded(); await row().screenshot({ path: `${output}/desktop.png` });
  await page.setViewportSize({ width: 520, height: 1000 });
  await row().scrollIntoViewIfNeeded(); await row().screenshot({ path: `${output}/narrow.png` });
  assert.equal(await row().evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true, "Rename controls do not overflow the row");
  await control("cancel-load-label").click();
  await page.reload(); await reopen();
  assert.deepEqual(await outputLabels(), ["F9", "F8"]);
  assert.equal(saved.spring_parameters.load_points.length, 3, "Renaming never duplicates points");
  assert.deepEqual(errors, []);
  console.log("load point rename: native edit/save/cancel/keys, legacy confirmation, retry, partial points, ID-based conflicts, duplicate races, reopen and SW parity passed");
} finally {
  await browser?.close(); await new Promise((resolve) => server.close(resolve));
}
