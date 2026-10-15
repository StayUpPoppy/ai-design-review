import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_NODE_MODULES ? path.join(process.env.CODEX_NODE_MODULES, "playwright") : "C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const frontend = path.resolve("frontend");
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const param = (value, unit = null) => ({ value, unit, need_human_review: false, source: ["manual"] });
const review = { drawing_summary: { spring_type: "compression_spring", drawing_name: "最终版本交互测试" }, spring_parameters: {
  material: param("SUS304"), wire_diameter: param(1.8, "mm"), mean_diameter: param(25.2, "mm"),
  free_length: param(19, "mm"), total_coils: param(4), active_coils: param(2), handedness: param("right"),
  end_type: param("两端并紧"), end_grinding: param("两端磨削"), load_points: [],
}, technical_requirements: [], standardization_results: [], derived_parameters: {}, change_history: [] };
const job = (id, reviewId = "final-selection") => ({ generation_id: id, review_id: reviewId, review_revision: 1, status: "completed", stage: "completed", progress: 100,
  template_code: "solidworks/test", template_version: "v1", is_final: false, is_stale: false, preview_status: "ready", artifacts: [], approved_by: null, approved_at: null });
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, "http://localhost").pathname.slice(1) || "index.html");
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser, release;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.UNIT_TEST_BROWSER_CHANNEL || "msedge" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = [], posts = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const jobs = [job("1000000002"), job("1000000001")], otherJobs = [job("1000000003", "other-order")];
  let failCancel = false, holdCancel = false;
  await page.route("**/api/**", async (route) => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body = {}, status = 200;
    if (apiPath === "/api/material-catalog") body = catalog;
    else if (apiPath === "/api/session") body = { identity: { user_id: "qa", username: "最终版本测试" }, mode: "mock" };
    else if (/\/api\/generation-jobs\/\d+\/(?:unapprove|approve)$/.test(apiPath)) {
      posts.push(apiPath);
      const parts = apiPath.split("/"), target = jobs.find((j) => j.generation_id === parts.at(-2));
      if (parts.at(-1) === "approve") {
        const selected = jobs.find((j) => j.is_final);
        if (selected && selected !== target) { status = 409; body = { detail: { code: "final_generation_already_selected", current_final_generation_id: selected.generation_id, message: "请先取消当前最终版本，再选择其他版本。" } }; }
        else { Object.assign(target, { is_final: true, approved_by: { user_id: "qa" }, approved_at: "2026-10-15T00:00:00Z" }); body = { generation_job: structuredClone(target) }; }
      } else if (failCancel) { failCancel = false; status = 503; body = { detail: "模拟取消失败" }; }
      else {
        Object.assign(target, { is_final: false, approved_by: null, approved_at: null }); body = { generation_job: structuredClone(target) };
        if (holdCancel) { holdCancel = false; await new Promise((resolve) => { release = resolve; }); }
      }
    } else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: apiPath.includes("other-order") ? otherJobs : jobs, generation_queue_available: true };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "ready", summary: "核心参数已确认，可继续生成图纸。", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 8, core_field_count: 8 }, generation_queue_available: true };
    else if (/\/api\/reviews\/(?:final-selection|other-order)$/.test(apiPath)) body = { ...structuredClone(review), job_id: apiPath.split("/").at(-1), review_revision: 1, image_url: "" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "qa", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const reopen = (id = "final-selection") => page.evaluate(async (id) => { await openPersistedReview(id); await loadGenerationState(id); state.compareTab = "generation"; renderCompareOverlay(); }, id);
  const settled = () => page.waitForFunction(() => !state.generationBusy);
  const action = (name, id) => page.locator(`.compare-tab-panel[data-compare-panel="generation"] [data-action="${name}-generation"][data-generation-id="${id}"]`);
  await reopen();
  assert.equal(await action("approve", "1000000001").isEnabled(), true);
  await action("approve", "1000000001").click(); await settled();
  assert.equal(await action("unapprove", "1000000001").isEnabled(), true);
  assert.equal(await action("approve", "1000000002").isDisabled(), true);
  assert.equal(await page.locator('.compare-tab-panel[data-compare-panel="generation"] .generation-final-hint').isVisible(), true);
  assert.notEqual(await action("approve", "1000000002").evaluate((el) => getComputedStyle(el).backgroundColor), "rgb(22, 101, 52)", "disabled selection has a visibly disabled style");
  const postCount = posts.length;
  await page.evaluate(() => approveGenerationJob("1000000002"));
  assert.equal(posts.length, postCount, "client guard prevents bypassing the disabled button");
  failCancel = true;
  await action("unapprove", "1000000001").click(); await settled();
  assert.equal(await action("unapprove", "1000000001").isEnabled(), true);
  assert.equal(await action("approve", "1000000002").isDisabled(), true, "failure retains selection");
  holdCancel = true;
  await action("unapprove", "1000000001").click();
  await page.waitForFunction(() => state.generationBusy);
  assert.equal(await action("unapprove", "1000000001").isDisabled(), true);
  assert.equal(await action("approve", "1000000002").isDisabled(), true);
  while (!release) await new Promise((resolve) => setTimeout(resolve, 10));
  const pendingCount = posts.length;
  await page.evaluate(() => unapproveGenerationJob("1000000001"));
  assert.equal(posts.length, pendingCount, "double click issues no second request");
  release(); release = null; await settled();
  assert.equal(await action("approve", "1000000001").isEnabled(), true);
  assert.equal(await action("approve", "1000000002").isEnabled(), true);
  await action("approve", "1000000002").click(); await settled();
  await page.reload(); await reopen();
  assert.equal(await action("unapprove", "1000000002").isEnabled(), true);
  assert.equal(await action("approve", "1000000001").isDisabled(), true);
  // A stale tab may not know that another tab already selected version B.
  await page.evaluate(() => { state.generationJobs.forEach((j) => { j.is_final = false; }); refreshReviewSurfaces(); });
  await action("approve", "1000000001").click(); await settled();
  assert.equal(await action("approve", "1000000001").isDisabled(), true, "409 reload restores authoritative selection");
  assert.equal(await action("unapprove", "1000000002").isEnabled(), true);
  assert.deepEqual(await page.evaluate(() => state.review.technical_requirements), []);
  fs.mkdirSync("outputs/final-selection-qa", { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const panel = page.locator('.compare-tab-panel[data-compare-panel="generation"]');
    await panel.locator('.generation-version-section').evaluate((el) => el.scrollIntoView({ block: "start" }));
    assert.equal(await panel.evaluate((el) => el.scrollWidth > el.clientWidth + 2), false);
    await panel.locator(".generation-version-section").screenshot({ path: `outputs/final-selection-qa/selection-${width}.png` });
  }
  holdCancel = true;
  await action("unapprove", "1000000002").click();
  while (!release) await new Promise((resolve) => setTimeout(resolve, 10));
  await reopen("other-order");
  release(); release = null;
  await page.waitForLoadState("networkidle");
  assert.deepEqual(await page.evaluate(() => state.generationJobs.map((j) => j.generation_id)), ["1000000003"], "old-order response does not contaminate new order");
  assert.equal(await action("approve", "1000000003").isEnabled(), true);
  assert.deepEqual(errors, []);
  console.log("PASS: final selection/cancel, disabled alternatives, duplicate click, failure retention, 409 refresh, save/reopen, desktop/narrow and inactive-order response");
} finally {
  release?.(); await browser?.close(); await new Promise((resolve) => server.close(resolve));
}
