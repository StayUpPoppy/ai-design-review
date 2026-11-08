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
const frontend = path.resolve("frontend");
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, "http://localhost").pathname.slice(1) || "index.html");
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
  response.end(fs.readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.UNIT_TEST_BROWSER_CHANNEL || "msedge" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let saved = structuredClone(cases.find(test => test.name === "optional_all").review), revision = 1, patches = 0, failSave = false;
  saved.spring_parameters.free_length.evidence = '参数识别依据验收原文';
  saved.spring_parameters.free_length.suggested_region = '参数位置验收摘要';
  saved.spring_parameters.load_points[0].evidence = '载荷识别依据验收原文';
  await page.route("**/api/**", async route => {
    const request = route.request(), apiPath = new URL(request.url()).pathname;
    let body;
    if (apiPath === "/api/session") body = { mode: "mock", identity: { user_id: "optional-user", username: "SW 测试账号", org_id: "optional-org", org_name: "不应显示的测试厂名", identity_display_enabled: true, is_mock: true } };
    else if (apiPath === "/api/material-catalog") body = catalog;
    else if (apiPath === "/api/reviews/optional" && request.method() === "PATCH") {
      if (failSave) return route.fulfill({ status: 503, json: { detail: '模拟公差保存失败' } });
      const input = request.postDataJSON();
      assert.equal(input.expected_revision, revision);
      saved = input.review; patches++;
      body = { review_revision: ++revision, events: (input.events || []).map(event => ({ ...event, sync_status: "saved" })) };
    } else if (apiPath === "/api/reviews/optional") body = { ...saved, job_id: "optional", review_revision: revision, image_url: "" };
    else if (apiPath === "/api/reviews") body = { reviews: [] };
    else if (apiPath.endsWith("/changes")) body = { events: [] };
    else if (apiPath.endsWith("/generation-package")) body = { parameter_package: await page.evaluate(() => makeGenerationParameterPackage()) };
    else if (apiPath.endsWith("/generation-jobs")) body = { generation_jobs: [], generation_queue_available: false };
    else if (apiPath.endsWith("/generation-readiness")) body = { generation_readiness: { status: "ready", warnings: [], missing_fields: [], pending_fields: [], confirmed_core_count: 8, core_field_count: 8 }, generation_queue_available: false };
    else if (apiPath.endsWith("/reasonableness")) body = { parameter_reasonableness: { status: "ok", issues: [], suggestions: [] } };
    else if (apiPath.endsWith("/annotations")) body = { schema_version: "original_annotations/v1", source_document_id: "test", annotation_revision: 1, pages: [], annotations: [], warnings: [] };
    else body = { status: "ok", generation_runtime: { status: "not_configured" }, recognition_queue_runtime: { status: "not_configured" } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  const reopen = () => page.evaluate(async () => { await openPersistedReview("optional"); state.compareTab = "parameters"; renderCompareOverlay(); });
  const preview = () => page.evaluate(() => makeGenerationParameterPackage().solidworks_preview);
  await page.goto(process.env.SW_EXPORT_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.materialCatalog.status === "ready");
  await reopen();
  assert.equal(await page.locator("#identityProfileName").innerText(), "SW 测试账号");
  assert.equal(await page.locator("#identityProfileSource").innerText(), "开发模拟");
  assert.equal(await page.locator("#identityProfileOrg").count(), 0);
  assert.equal(await page.getByText("不应显示的测试厂名", { exact: true }).count(), 0);
  assert.equal(await page.evaluate(() => state.identity.org_id), "optional-org", "Organization identity is retained for authorization");
  let current = await preview();
  assert.deepEqual(current.modelParametersTolerance, { "外径": 1.5, "自由高度": .5, "中径": .2 });
  assert.equal(current.titleBlockProperties["垂直度A"], .01);
  const panel = page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
  const length = panel.locator('[data-kind="param"][data-field="free_length"]');
  const tolerance = length.locator('[data-role="tolerance"]');
  await tolerance.fill("+1.25/-0.75"); await tolerance.dispatchEvent("change");
  await length.locator('[data-role="confirm"]').click();
  assert.deepEqual((await preview()).modelParametersTolerance["自由高度"], [1.25, .75], "Confirmed signed asymmetric tolerance exports upper/lower magnitudes");
  await tolerance.fill("±0.000012345"); await tolerance.dispatchEvent("change");
  assert.equal((await preview()).modelParametersTolerance["自由高度"], undefined, "Edited tolerance awaits confirmation");
  await length.locator('[data-role="confirm"]').click();
  assert.equal((await preview()).modelParametersTolerance["自由高度"], .000012345, "Small tolerances are not rounded to zero");
  await panel.locator(".advanced-parameters summary").click();
  const perpendicularity = panel.locator('[data-kind="param"][data-field="perpendicularity"]');
  await perpendicularity.locator('[data-role="value"]').fill("0");
  await perpendicularity.locator('[data-role="value"]').dispatchEvent("change");
  assert.equal((await preview()).titleBlockProperties["垂直度A"], undefined);
  await perpendicularity.locator('[data-role="confirm"]').click();
  assert.equal((await preview()).titleBlockProperties["垂直度A"], 0);
  assert.equal(await page.evaluate(() => flushReviewPersistence({ throwOnError: true })), true);
  const before = await preview();
  assert.ok(patches > 0);
  await page.reload(); await page.waitForFunction(() => state.identityReady && state.materialCatalog.status === "ready");
  await reopen();
  current = await preview();
  assert.deepEqual(current.modelParametersTolerance, before.modelParametersTolerance);
  assert.equal(current.titleBlockProperties["垂直度A"], 0);
  assert.equal(await page.evaluate(async () => {
    const originalDownload = downloadJson;
    downloadJson = value => { window.optionalExport = structuredClone(value); };
    try { return await exportCurrentGenerationPackage(); } finally { downloadJson = originalDownload; }
  }), true);
  const exported = await page.evaluate(() => window.optionalExport.solidworks_preview);
  assert.deepEqual(exported.modelParametersTolerance, current.modelParametersTolerance);
  assert.equal(exported.titleBlockProperties["垂直度A"], 0);
  // Inline editing stages signed drafts and guards all mutation/generation entry points.
  const editor = panel.locator('[data-tolerance-editor]');
  const edit = row => row.locator('[data-tolerance-action="open"]').click();
  const action = name => editor.locator(`[data-tolerance-action="${name}"]`);
  const pair = () => editor.locator('[data-tolerance-mode="pair"]').click();
  const upper = () => editor.locator('[data-tolerance-input="upper"]');
  const lower = () => editor.locator('[data-tolerance-input="lower"]');
  await edit(length); await pair(); await upper().fill('+0.1'); await lower().fill('-0.2');
  assert.equal(await editor.locator('.tolerance-editor-preview small').first().innerText(), '尺寸范围（按公差计算）');
  assert.match(await editor.locator('.tolerance-editor-preview small').last().innerText(), /^当前数值：/);
  assert.match(await editor.locator('[data-tolerance-preview]').innerText(), /18.8 ～ 19.1 mm/);
  assert.equal(await page.evaluate(() => state.review.spring_parameters.free_length.tolerance_upper), .000012345, 'Draft never changes actual tolerance');
  assert.equal(await page.evaluate(() => runStandardization()), false, 'Dirty draft blocks standardization');
  await length.locator('[data-role="confirm"]').dispatchEvent('click');
  assert.equal(await editor.count(), 1, 'Confirmation cannot discard an edited draft');
  await page.evaluate(() => renderCompareOverlay());
  assert.equal(await upper().inputValue(), '+0.1', 'Draft survives redraw');
  await lower().fill(''); assert.equal(await action('save').isDisabled(), true, 'Missing side cannot silently become zero');
  await lower().fill('+0.2'); assert.equal(await action('save').isDisabled(), true, 'Upper must not be lower than lower');
  await lower().fill('-0.2'); await action('cancel').click();
  assert.equal(await page.evaluate(() => state.review.spring_parameters.free_length.tolerance_upper), .000012345);
  await edit(length); await pair(); await upper().fill('+0.1'); await lower().fill('-0.2'); await upper().press('Enter');
  assert.equal(await editor.count(), 0);
  assert.equal(await page.evaluate(() => state.review.spring_parameters.free_length.need_human_review), true);
  await length.locator('[data-role="confirm"]').click();
  assert.deepEqual((await preview()).modelParametersTolerance['自由高度'], [.1, .2]);
  await page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  const beforeNoop = await page.evaluate(() => JSON.stringify(state.review.spring_parameters.free_length));
  await edit(length); await upper().fill('+0.1000'); await action('save').click();
  assert.equal(await page.evaluate(() => JSON.stringify(state.review.spring_parameters.free_length)), beforeNoop, 'Format-only save preserves source and confirmation');
  const load = panel.locator('[data-kind="load_point"]').first();
  await edit(load); await pair(); await upper().fill('+0.13'); await lower().fill('-0.27'); await action('save').click();
  const point = await page.evaluate(() => state.review.spring_parameters.load_points[0]);
  assert.equal(point.load_tolerance_upper, .13); assert.equal(point.load_tolerance_lower, -.27);
  assert.equal(point.load_tolerance_percent, null); assert.equal(point.force_tolerance_percent, null);
  await load.locator('[data-role="confirm"]').click();
  assert.match((await preview()).extraProperties['技术要求'], /\+0.13\/-0.27 N/);
  await edit(load); await editor.locator('[data-tolerance-mode="percent"]').click();
  assert.equal(await editor.locator('.tolerance-editor-preview small').first().innerText(), '力值范围（按公差计算）');
  assert.match(await editor.locator('.tolerance-editor-preview small').last().innerText(), /^当前力值：/);
  await editor.locator('[data-tolerance-input="magnitude"]').fill('7.5'); await action('save').click();
  assert.deepEqual(await page.evaluate(() => {
    const p = state.review.spring_parameters.load_points[0]; return [p.load_tolerance_upper, p.load_tolerance_lower, p.load_tolerance_percent];
  }), [null, null, 7.5]);
  await load.locator('[data-role="confirm"]').click();
  assert.match((await preview()).extraProperties['技术要求'], /±7.5%/);
  await page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  failSave = true;
  await edit(length); await upper().fill('0'); await action('save').click();
  await page.waitForFunction(() => Object.keys(state.reviewPersistenceFailedFields).length > 0);
  assert.equal(await page.evaluate(() => state.review.spring_parameters.free_length.tolerance_upper), 0, 'Failed save retains selection in page');
  assert.equal(await page.evaluate(() => flushReviewPersistence()), false);
  failSave = false;
  await page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  await length.locator('[data-role="confirm"]').click();
  assert.deepEqual((await preview()).modelParametersTolerance['自由高度'], [0, .2]);
  await edit(length); await upper().fill('+0.2'); await lower().fill('+0.1'); await action('save').click();
  await length.locator('[data-role="confirm"]').click();
  const blocked = await page.evaluate(() => assessGenerationReadiness(state.review));
  assert.equal(blocked.status, 'blocked'); assert.match(blocked.summary, /自由高度.*同方向/);
  await edit(length); await upper().fill('+0.1'); await lower().fill('-0.2'); await action('save').click();
  await length.locator('[data-role="confirm"]').click();
  await page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  await page.reload(); await page.waitForFunction(() => state.identityReady && state.materialCatalog.status === 'ready'); await reopen();
  assert.deepEqual((await preview()).modelParametersTolerance['自由高度'], [.1, .2]);
  assert.equal(await length.locator('.data-label').getByText('参数识别依据验收原文').count(), 0);
  assert.equal(await load.locator('.data-label').getByText('载荷识别依据验收原文').count(), 0);
  assert.equal(await load.locator('.load-height-evidence').count(), 0);
  assert.deepEqual(await page.evaluate(() => [state.review.spring_parameters.free_length.evidence, state.review.spring_parameters.free_length.suggested_region, state.review.spring_parameters.load_points[0].evidence]),
    ['参数识别依据验收原文', '参数位置验收摘要', '载荷识别依据验收原文']);
  await edit(length); await upper().fill('+0.05'); await lower().fill('-0.04'); await action('save').click();
  await length.locator('[data-role="confirm"]').click();
  await edit(load); await pair(); await upper().fill('+0.15'); await lower().fill('-0.25'); await action('save').click();
  await load.locator('[data-role="confirm"]').click();
  await page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  assert.match(await load.locator('.load-point-tolerance').innerText(), /图纸原公差/);
  await length.locator('[data-role="value"]').fill('133.35');
  await length.locator('[data-role="value"]').dispatchEvent('change');
  await length.locator('[data-role="confirm"]').click();
  await page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  const wireRow = panel.locator('[data-field="wire_diameter"]');
  await wireRow.locator('[data-role="tolerance"]').fill('±0.05');
  await wireRow.locator('[data-role="tolerance"]').dispatchEvent('change');
  await wireRow.locator('[data-role="confirm"]').click();
  await page.evaluate(() => flushReviewPersistence({ throwOnError: true }));
  const layoutMetrics = () => panel.evaluate(panel => {
    const box = node => { const {x, y, right, bottom, width} = node.getBoundingClientRect(); return {x, y, right, bottom, width}; };
    const row = panel.querySelector('[data-field="free_length"]'), load = panel.querySelector('[data-kind="load_point"]');
    const parameterTable = row.closest('.data-table'), wire = panel.querySelector('[data-field="wire_diameter"]');
    const fit = (input, values) => {
      const style = getComputedStyle(input), canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
      ctx.font = style.font;
      // Native text inputs expose their inner editor as clientWidth in Chromium.
      // Compute the CSS content box so padding is counted exactly once.
      const contentWidth = parseFloat(style.width) - (style.boxSizing === 'border-box'
        ? parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth) : 0);
      return values.every(value => ctx.measureText(value).width <= contentWidth + 1);
    };
    return {
      paramWidth: row.closest('.data-table').clientWidth, loadWidth: load.closest('.data-table').clientWidth,
      scale: row.getBoundingClientRect().width / row.offsetWidth,
      param: ['.data-label', '.data-primary', '.data-secondary', '.confirm-button'].map(s => box(row.querySelector(s))),
      load: ['.data-label', '.data-primary', '.data-secondary', '.data-tertiary', '.load-point-actions'].map(s => box(load.querySelector(s))),
      fits: [fit(row.querySelector('[data-role="tolerance"]'), ['+0.05/-0.04', '0/-0.2']), fit(load.querySelector('[data-role="load-tolerance"]'), ['+0.15/-0.25N', '±10%'])],
      valueFits: fit(row.querySelector('[data-role="value"]'), ['1.8', '133.35']),
      paramHeaderVisible: getComputedStyle(parameterTable.querySelector('.data-table-head')).display !== 'none',
      paramHeaderAligned: [...parameterTable.querySelectorAll('.data-table-head span')].every((cell, index) => Math.abs(box(cell).x - box(row.children[index]).x) < 1),
      inlineFieldLabelsHidden: [...row.querySelectorAll('.parameter-field-label')].every(node => getComputedStyle(node).display === 'none'),
      wire: ['.data-label strong', '.parameter-annotation-number', '.data-primary', '.data-secondary'].map(s => box(wire.querySelector(s))),
      controls: [box(row.querySelector('.tolerance-input-control')), box(load.querySelector('.tolerance-input-control'))],
      headerAligned: [...load.closest('.data-table').querySelectorAll('.data-table-head span')].every((cell, index) => Math.abs(box(cell).x - box(load.children[index]).x) < 1),
      clipped: [...panel.querySelectorAll('.parameter-data-table > .data-row, .load-point-table > .data-row')].some(node => node.getClientRects().length && node.scrollWidth > node.clientWidth + 2),
    };
  });
  fs.mkdirSync('outputs/pc-parameter-row-qa', { recursive: true });
  for (const scenario of [{name:'wide', pane:760}, {name:'mid', pane:560}, {name:'sidebar', pane:430}, {name:'zoom125', pane:430, zoom:1.25}, {name:'compact', pane:360}, {name:'mobile', viewport:390}]) {
    await page.setViewportSize({ width: scenario.viewport || 1440, height: 1000 });
    await page.evaluate(zoom => { document.documentElement.style.zoom = zoom === 1 ? '' : String(zoom); }, scenario.zoom || 1);
    await page.evaluate(pane => {
      let style = document.getElementById('layout-qa-width');
      if (!style) { style = document.createElement('style'); style.id = 'layout-qa-width'; document.head.append(style); }
      style.textContent = pane ? `#compareOverlay .compare-layout { grid-template-columns: minmax(0, 1fr) ${pane}px; }` : '';
    }, scenario.pane || 0);
    const metrics = await layoutMetrics();
    assert.deepEqual(metrics.fits, [true, true], `${scenario.name}: normal tolerances fit at actual input width`);
    assert.ok(metrics.controls[0].width >= (metrics.paramWidth < 400 ? 150 : 140) * metrics.scale - 1, `${scenario.name}: parameter tolerance has priority`);
    assert.ok(metrics.controls[1].width >= 150 * metrics.scale - 1, `${scenario.name}: load tolerance width is unchanged`);
    assert.equal(metrics.valueFits, true, `${scenario.name}: common numeric values fit completely`);
    assert.equal(metrics.clipped, false, `${scenario.name}: no clipped rows`);
    const [label, value, tolerance, confirm] = metrics.param;
    if (metrics.paramWidth < 400) assert.ok(label.bottom <= value.y + 1, `${scenario.name}: extreme narrow layout remains unchanged`);
    else {
      assert.ok(label.right <= value.x + 1);
      assert.ok(Math.max(label.y, value.y, tolerance.y, confirm.y) < Math.min(label.bottom, value.bottom, tolerance.bottom, confirm.bottom), `${scenario.name}: parameter cells stay on one row`);
      assert.equal(metrics.paramHeaderVisible, true); assert.equal(metrics.paramHeaderAligned, true);
      assert.equal(metrics.inlineFieldLabelsHidden, true);
      const [name, badge, number, allowance] = metrics.wire;
      assert.ok(badge.right <= name.x + 1 && name.right <= number.x + 1);
      assert.ok(Math.max(name.y, badge.y, number.y, allowance.y) < Math.min(name.bottom, badge.bottom, number.bottom, allowance.bottom), `${scenario.name}: wire badge/name and inputs stay together`);
    }
    if (metrics.paramWidth < 360) assert.ok(confirm.y >= Math.max(value.bottom, tolerance.bottom) - 1, `${scenario.name}: confirmation wraps`);
    else assert.ok(confirm.x >= tolerance.right - 1);
    const [name, height, force, loadTolerance, actions] = metrics.load;
    if (metrics.loadWidth < 640) assert.ok(loadTolerance.y >= Math.max(height.bottom, force.bottom) - 1, `${scenario.name}: force tolerance gets its own row`);
    else { assert.ok(Math.abs(name.width - 88 * metrics.scale) < 1); assert.ok(force.right <= loadTolerance.x); assert.equal(metrics.headerAligned, true); }
    assert.ok(actions.y >= Math.max(height.bottom, force.bottom, loadTolerance.bottom) - 1, `${scenario.name}: load actions stay below inputs`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
    if (scenario.name === 'sidebar') {
      const extra = await panel.evaluate(panel => {
        const material = panel.querySelector('[data-field="material"]'), row = panel.querySelector('[data-field="free_length"]');
        const box = node => node.getBoundingClientRect();
        const mergedMaterial = box(material.querySelector('.data-primary')).right >= box(row.querySelector('.data-secondary')).right - 1;
        const button = row.querySelector('.confirm-button'), text = button.textContent;
        button.textContent = '保存失败·重试保存';
        const failureFits = button.scrollWidth <= button.clientWidth + 1 && row.scrollWidth <= row.clientWidth + 1;
        button.textContent = text;
        const details = panel.querySelector('.advanced-parameters'), wasOpen = details.open; details.open = true;
        const rows = [...details.querySelectorAll('.data-row[data-kind="param"]')];
        const advancedAligned = rows.every(row => {
          const label = box(row.querySelector('.data-label')), value = box(row.querySelector('.data-primary')), tolerance = box(row.querySelector('.data-secondary'));
          return label.right <= value.x + 1 && Math.max(label.y, value.y, tolerance.y) < Math.min(label.bottom, value.bottom, tolerance.bottom) && row.scrollWidth <= row.clientWidth + 1;
        });
        details.open = wasOpen;
        return { mergedMaterial, failureFits, advancedAligned, advancedRows: rows.length };
      });
      assert.ok(extra.advancedRows > 0); assert.deepEqual({...extra, advancedRows:0}, {mergedMaterial:true, failureFits:true, advancedAligned:true, advancedRows:0});
    }
    if (!process.env.SKIP_UI_QA_SCREENSHOTS && ['wide','sidebar','zoom125'].includes(scenario.name)) {
      await panel.locator('.parameter-data-table').first().locator('.data-table-head').scrollIntoViewIfNeeded();
      await page.screenshot({ path: `outputs/pc-parameter-row-qa/${scenario.name}-table.png` });
    }
    for (const [kind, row] of [['parameter', length], ['load', load]]) {
      await edit(row); await editor.scrollIntoViewIfNeeded();
      await editor.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.ok(await action('save').isVisible());
      assert.equal(await editor.evaluate(node => node.closest('.data-table').clientWidth), kind === 'parameter' ? metrics.paramWidth : metrics.loadWidth, 'Rerender preserves the tested container width');
      assert.equal(await editor.evaluate(node => {
        const box = node.getBoundingClientRect();
        return node.scrollWidth <= node.clientWidth + 1 && [...node.querySelectorAll('input')].every(input => input.getBoundingClientRect().x >= box.x && input.getBoundingClientRect().right <= box.right + 1);
      }), true, 'Expanded editor and inputs stay inside the row');
      assert.equal(await editor.evaluate(node => node.getBoundingClientRect().width > node.parentElement.getBoundingClientRect().width + 1), false);
      if (!process.env.SKIP_UI_QA_SCREENSHOTS && kind === 'parameter' && ['wide','sidebar','zoom125'].includes(scenario.name)) await page.screenshot({ path: `outputs/pc-parameter-row-qa/${scenario.name}.png` });
      await action('cancel').click();
    }
  }
  await page.evaluate(() => closeCompareOverlay());
  fs.mkdirSync("outputs/sw-optional-fields-qa", { recursive: true });
  for (const width of process.env.SKIP_UI_QA_SCREENSHOTS ? [] : [1440, 1100, 390]) {
    await page.setViewportSize({ width, height: width < 500 ? 1100 : 1000 });
    assert.equal(await page.locator("#identityProfileOrg").count(), 0);
    if (width > 720) assert.equal(await page.locator("#identityProfileName").isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
    await page.screenshot({ path: `outputs/sw-optional-fields-qa/identity-${width}.png` });
  }
  assert.deepEqual(errors, []);
  console.log("PASS: PC parameter rows and headers align at narrow/wide/125%, full values and tolerances, unchanged load layout, editing, save/retry/reopen and asymmetric SW output; mocked API only.");
} finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
