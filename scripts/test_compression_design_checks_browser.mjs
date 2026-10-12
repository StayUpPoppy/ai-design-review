import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = process.env.CODEX_NODE_MODULES
  ? require(path.join(process.env.CODEX_NODE_MODULES, "playwright"))
  : require("C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const frontend = path.resolve("frontend");
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, request.url.split("?")[0].replace(/^\//, "") || "index.html");
  if (file !== path.join(frontend, "index.html") && !file.startsWith(frontend + path.sep)) { response.writeHead(403).end(); return; }
  if (!fs.existsSync(file)) { response.writeHead(404).end(); return; }
  response.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : "text/html");
  response.end(fs.readFileSync(file));
});
const param = (value, unit = "mm", extra = {}) => ({ value, unit, source: ["human_confirmed"], need_human_review: false, ...extra });
const formula = (value, sourceFields) => param(value, "mm", {
  source: ["formula_calculation"], source_fields: sourceFields, need_human_review: true,
  formula_calculation_kind: "diameter_completion", formula_calculation_status: "calculated",
});
const createReview = (overrides = {}) => ({
  drawing_summary: { spring_type: "compression_spring", drawing_name: "旋绕比联动回归测试", drawing_no: "DEMO-CHECKS" },
  spring_parameters: {
    material: param("SUS304", null), standard_no: param("GB/T 1239.2-2009", null), accuracy_grade: param("2级", null),
    wire_diameter: param(2), outer_diameter: param(20),
    mean_diameter: formula(18, ["outer_diameter", "wire_diameter"]),
    inner_diameter: formula(16, ["outer_diameter", "wire_diameter"]), free_length: param(36),
    total_coils: param(12, "turns"), active_coils: param(10, "turns"),
    handedness: param("right", null), end_type: param("两端并紧", null), end_grinding: param("两端磨削", null),
    load_points: [], ...overrides,
  },
  technical_requirements: [], standardization_results: [], derived_parameters: {},
  manual_confirmations: {}, change_history: [],
  balloons: [{ field: "mean_diameter", value: "18" }],
  parameter_reasonableness: { status: "ok", issues: [], suggestions: [] },
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.UNIT_TEST_BROWSER_CHANNEL ? { channel: process.env.UNIT_TEST_BROWSER_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], mutations = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let saved = createReview(), revision = 1;
  await page.route("**/api/**", async (route) => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body = {};
    if (request.method() === "PATCH" && apiPath === "/api/reviews/design-checks") {
      const input = request.postDataJSON();
      assert.equal(input.expected_revision, revision);
      mutations.push(input);
      saved = input.review;
      body = { review_revision: ++revision, events: input.events.map((event) => ({ ...event, sync_status: "saved" })) };
    } else if (apiPath === "/api/reviews/design-checks") body = { ...saved, job_id: "design-checks", review_revision: revision, image_url: "" };
    else if (apiPath === "/api/session") body = { identity: { user_id: "demo", username: "回归测试用户" }, mode: "mock" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "needs_confirmation", summary: "模拟数据", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 0, core_field_count: 8 }, generation_queue_available: false };
    else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "demo", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  const base = `http://127.0.0.1:${server.address().port}`;
  const openSaved = async () => {
    await page.evaluate(async () => {
      await openPersistedReview("design-checks");
      state.compareTab = "parameters";
      renderCompareOverlay();
    });
    await page.waitForLoadState("networkidle");
  };
  const open = async (overrides = {}) => {
    saved = createReview(overrides);
    revision = 1;
    await page.goto(base);
    await openSaved();
  };
  const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const input = (field) => panel.locator(`[data-kind="param"][data-field="${field}"] [data-role="value"]`);
  const metric = (name) => panel.locator(`[data-role="design-check-value"][data-metric="${name}"]`);
  const check = async (c, b) => {
    const values = await page.evaluate(() => Object.fromEntries(
      ["wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length"].map((field) => [field, state.review.spring_parameters[field]]),
    ));
    assert.equal(await metric("spring_index").innerText(), c, JSON.stringify(values));
    assert.equal(await metric("slenderness_ratio").innerText(), b, JSON.stringify(values));
  };
  const edit = async (field, value) => {
    await input(field).fill(value);
    await input(field).dispatchEvent("change");
  };
  const flush = async () => {
    assert.equal(await page.evaluate(() => flushReviewPersistence({ throwOnError: true })), true);
  };

  await open();
  await check("9", "2");
  await input("outer_diameter").focus();
  const focused = await input("outer_diameter").evaluate((element) => {
    element.value = "22";
    element.setSelectionRange(1, 1);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    return {
      sameNode: element === document.querySelector('.compare-tab-panel[data-compare-panel="parameters"] [data-field="outer_diameter"] [data-role="value"]'),
      focused: document.activeElement === element, cursor: element.selectionStart,
    };
  });
  assert.deepEqual(focused, { sameNode: true, focused: true, cursor: 1 });
  await check("10", "1.8");
  assert.equal(await input("mean_diameter").inputValue(), "20");
  assert.equal(await input("inner_diameter").inputValue(), "18");
  assert.equal(await page.evaluate(() => state.review.spring_parameters.mean_diameter.value), 20);
  assert.equal(await page.evaluate(() => state.review.balloons.find((item) => item.field === "mean_diameter").value), "20");
  assert.equal(await page.evaluate(() => state.review.spring_parameters.mean_diameter.need_human_review), true);
  await input("outer_diameter").dispatchEvent("change");
  await flush();
  assert.equal(saved.spring_parameters.mean_diameter.value, 20);
  assert.equal(saved.spring_parameters.inner_diameter.value, 18);
  assert.ok(mutations.some((item) => item.events.some((event) => event.target_field === "outer_diameter")));
  await page.reload();
  await openSaved();
  await check("10", "1.8");
  assert.equal(await input("mean_diameter").inputValue(), "20");
  await edit("outer_diameter", "20");
  await check("9", "2");
  await flush();

  await open({ inner_diameter: param(16), outer_diameter: formula(20, ["inner_diameter", "wire_diameter"]),
    mean_diameter: formula(18, ["inner_diameter", "wire_diameter"]) });
  await edit("inner_diameter", "18");
  await check("10", "1.8");
  assert.equal(await input("outer_diameter").inputValue(), "22");
  await flush();

  await open({ inner_diameter: param(16), mean_diameter: formula(18, ["outer_diameter", "inner_diameter"]) });
  await edit("outer_diameter", "22");
  await check("9.5", "1.8947");
  assert.equal(await input("mean_diameter").inputValue(), "19");
  await flush();

  await open({ inner_diameter: param(16), mean_diameter: formula(18, ["outer_diameter", "inner_diameter"]),
    outer_diameter: formula(20, ["inner_diameter", "wire_diameter"]) });
  await edit("wire_diameter", "3");
  await check("6.3333", "1.8947");
  assert.equal(await input("outer_diameter").inputValue(), "22");
  assert.equal(await input("mean_diameter").inputValue(), "19");
  await flush();

  for (const middle of [param(18, "mm", { source: ["qwen_vision"], need_human_review: true }),
    param(18), { ...formula(18, ["outer_diameter", "wire_diameter"]), source: ["formula_calculation", "manual"] }]) {
    await open({ mean_diameter: middle });
    await edit("outer_diameter", "22");
    await check("9", "2");
    assert.equal(await input("mean_diameter").inputValue(), "18");
    assert.equal(await page.evaluate(() => state.review.spring_parameters.mean_diameter.need_human_review), middle.need_human_review);
    await flush();
  }

  await open();
  for (const invalid of ["", "0", "-2", "abc"]) {
    await edit("wire_diameter", invalid);
    await check("--", "--");
    assert.equal(await page.evaluate(() => state.review.spring_parameters.mean_diameter.derived_value_stale), true);
    if (invalid === "") {
      await flush();
      assert.equal(saved.spring_parameters.wire_diameter.value, "", "Saving must preserve an intentionally cleared input");
      await page.reload();
      await openSaved();
      assert.equal(await input("wire_diameter").inputValue(), "");
      await check("--", "--");
    }
    await edit("wire_diameter", "2");
    await check("9", "2");
  }
  await edit("outer_diameter", "");
  await check("--", "--");
  await edit("outer_diameter", "20");
  await check("9", "2");
  await edit("free_length", "");
  await check("9", "--");
  await edit("free_length", "36");
  await flush();

  await open({ outer_diameter: formula(20, ["mean_diameter", "wire_diameter"]) });
  await edit("wire_diameter", "3");
  await check("--", "--");
  const stale = await page.evaluate(() => ["mean_diameter", "outer_diameter", "inner_diameter"].map((field) => state.review.spring_parameters[field].derived_value_stale));
  assert.deepEqual(stale, [true, true, true]);
  await flush();

  assert.deepEqual(errors, [], "No uncaught browser errors");
  console.log("compression design check browser tests passed: live inputs, focus, save/reopen, dependencies, protected values and invalid inputs");
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
