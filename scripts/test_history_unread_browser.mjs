import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const frontend = path.resolve('frontend'), output = path.resolve('outputs/history-unread-qa');
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, 'http://localhost').pathname.slice(1) || 'index.html');
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, channel: 'msedge' });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const model = { jobs: new Map(), errors: [], writes: [], reads: [], failRead: false, gate: null, listGate: null, hideClosed: false, user: 'local-user' };
let tick = Date.now();
const update = (id, values) => {
  model.jobs.set(id, { ...model.jobs.get(id), job_id: id, ...values, updated_at: new Date(++tick).toISOString() });
};
update('old', { drawing_name: '已存在的压缩弹簧', status: 'completed', attempt_count: 1 });
update('fresh', { drawing_name: 'UQD08外弹簧(钢珠型)特别长的订单名称', status: 'processing', attempt_count: 1, progress: 36 });
update('closed', { drawing_name: '页面关闭期间完成的图纸', status: 'queued', attempt_count: 0, progress: 0 });
await context.route('**/api/**', async (route) => {
  const request = route.request(), url = new URL(request.url()), api = url.pathname, method = request.method();
  if (method !== 'GET') model.writes.push([method, api]);
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: model.user, username: '离线红点验收' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') {
    const reviews = [...model.jobs.values()].filter((item) => !(model.hideClosed && item.job_id === 'closed')).map((item) => ({ ...item,
      recognition_status: item.status, recognition_progress: item.progress, recognition_attempt_count: item.attempt_count, revision: 2 }));
    if (model.listGate) { const gate = model.listGate; model.listGate = null; await gate.promise; }
    return route.fulfill({ json: { reviews } });
  }
  const match = api.match(/^\/api\/reviews\/([^/]+)(?:\/(recognition-status|retry))?$/);
  if (match) {
    const [, id, action] = match, item = model.jobs.get(id);
    if (action === 'recognition-status') return route.fulfill({ json: { job_id: id, recognition: item } });
    if (action === 'retry') {
      update(id, { status: 'queued', progress: 0 });
      return route.fulfill({ status: 202, json: { job_id: id, recognition: model.jobs.get(id) } });
    }
    if (method === 'DELETE') { model.jobs.delete(id); return route.fulfill({ json: { deleted: true, job_id: id } }); }
    model.reads.push(id);
    if (model.gate) { const gate = model.gate; model.gate = null; await gate.promise; }
    if (model.failRead) return route.fulfill({ status: 503, json: { detail: '模拟读取失败' } });
    return route.fulfill({ json: { job_id: id, review_revision: 2, drawing_summary: { drawing_name: item?.drawing_name,
      spring_type: 'compression_spring' }, spring_parameters: {}, technical_requirements: [], manual_confirmations: {}, change_history: [] } });
  }
  if (api.endsWith('/generation-jobs')) return route.fulfill({ json: { generation_jobs: [], generation_queue_available: false } });
  if (api.endsWith('/annotations')) return route.fulfill({ json: { pages: [], annotations: [], warnings: [] } });
  if (api.endsWith('/reasonableness')) return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
  if (api.endsWith('/changes')) return route.fulfill({ json: { events: [] } });
  return route.fulfill({ json: { status: 'ok', generation_runtime: { status: 'not_configured' }, recognition_queue_runtime: { status: 'not_configured' } } });
});
const origin = `http://127.0.0.1:${server.address().port}`;
async function newPage() {
  const page = await context.newPage();
  page.on('pageerror', (error) => model.errors.push(error.message));
  await page.goto(origin);
  await page.waitForFunction(() => state.identityReady && !state.recentReviewsLoading && state.recentReviews.length > 0);
  return page;
}
const dot = (page, id) => page.locator(`[data-history-job-id="${id}"] .history-unread-dot`);
const refresh = (page) => page.evaluate(() => loadRecentReviews());
try {
  let page = await newPage();
  assert.equal(await page.locator('#historyUnreadCount').isVisible(), false);
  assert.equal(await page.locator('#historyManagement').isVisible(), false, 'An idle management panel takes no extra row');
  assert.equal(await dot(page, 'old').isVisible(), false);
  update('fresh', { status: 'completed', progress: 100 });
  await refresh(page);
  await page.waitForFunction(() => !document.querySelector('[data-history-job-id="fresh"] .history-unread-dot').hidden);
  assert.equal(await page.locator('#historyUnreadCount').textContent(), '新完成 1');
  assert.equal(await page.locator('#uploadViewHistory').count(), 0);
  const order = await page.locator('.history-order-item').evaluateAll((rows) => rows.map((row) => row.dataset.historyJobId));
  await page.locator('#historyUnreadCount').click();
  assert.equal(await page.evaluate(() => document.activeElement.dataset.jobId), 'fresh');
  assert.deepEqual(model.reads, [], 'Unread count only focuses, never loads or opens');
  assert.deepEqual(await page.locator('.history-order-item').evaluateAll((rows) => rows.map((row) => row.dataset.historyJobId)), order);
  assert.equal(await dot(page, 'fresh').evaluate((node) => getComputedStyle(node).width), '6px');
  assert.ok((await page.locator('[data-history-job-id="fresh"] .history-select-button').getAttribute('aria-label')).includes('尚未查看'));
  for (const [name, width] of [['desktop', 1440], ['narrow', 900], ['mobile', 430]]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.equal(await page.locator('.history-sidebar-head').evaluate((head) => {
      const box = head.getBoundingClientRect();
      return [...head.children].some((node) => { const rect = node.getBoundingClientRect(); return rect.right > box.right + 1 || rect.left < box.left - 1; });
    }), false, `${name}: history heading, count and refresh fit`);
    assert.equal(await page.locator('.history-header-actions').evaluate((group) => {
      const manage = group.querySelector('#enterHistoryManagement').getBoundingClientRect();
      const refresh = group.querySelector('#refreshRecentReviewsButton').getBoundingClientRect();
      return manage.right <= refresh.left && Math.abs(manage.top + manage.height / 2 - refresh.top - refresh.height / 2) < 1;
    }), true, `${name}: batch management stays immediately left of refresh and vertically aligned`);
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.locator('#recentReviews').screenshot({ path: path.join(output, `${name}.png`) });
    await page.locator('#historyUnreadCount').evaluate((button) => { button.hidden = true; });
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.locator('#recentReviews').screenshot({ path: path.join(output, `${name}-without-count.png`) });
    await page.evaluate(() => updateHistoryUnreadCount());
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await page.waitForFunction(() => !state.recentReviewsLoading && state.recentReviews.length === 3);
  assert.equal(await dot(page, 'fresh').isVisible(), true, 'Unread survives reload');
  await page.evaluate(async () => { const original = flushReviewPersistence; flushReviewPersistence = async () => false;
    try { await openPersistedReview('fresh'); } finally { flushReviewPersistence = original; } });
  assert.equal(await dot(page, 'fresh').isVisible(), true, 'Save failure is not a view');
  assert.deepEqual(model.reads, []);
  model.failRead = true;
  await page.evaluate(() => openPersistedReview('fresh'));
  assert.equal(await dot(page, 'fresh').isVisible(), true, 'Load failure is not a view');
  model.failRead = false;
  await page.evaluate(() => openPersistedReview('fresh'));
  assert.equal(await dot(page, 'fresh').isVisible(), false);
  assert.equal(await page.locator('#historyUnreadCount').isVisible(), false);
  await page.evaluate(() => closeCompareOverlay());
  update('fresh', { status: 'completed', attempt_count: 2 });
  await refresh(page);
  assert.equal(await dot(page, 'fresh').isVisible(), true, 'A new recognition round lights once');
  const gate = deferred(); model.gate = gate;
  await page.evaluate(() => { window.pendingOpen = openPersistedReview('fresh'); });
  await page.waitForFunction(() => state.busy);
  update('fresh', { status: 'completed', attempt_count: 3 });
  await refresh(page);
  gate.resolve(); await page.evaluate(() => pendingOpen);
  assert.equal(await dot(page, 'fresh').isVisible(), true, 'Loaded older snapshot cannot acknowledge a newer completion');
  await page.evaluate(() => closeCompareOverlay());
  const tab = await newPage();
  assert.equal(await dot(tab, 'fresh').isVisible(), true);
  await tab.evaluate(() => openPersistedReview('fresh'));
  await page.waitForFunction(() => document.querySelector('[data-history-job-id="fresh"] .history-unread-dot').hidden);
  await page.evaluate(() => { const item = state.recentReviews.find((entry) => entry.job_id === 'fresh');
    mergeRecognitionStatus('fresh', { status: 'completed', attempt_count: 3, updated_at: item.updated_at }); });
  assert.equal(await dot(page, 'fresh').isVisible(), false, 'Stale polling cannot undo another tab receipt');

  update('fresh', { attempt_count: 4 }); await refresh(tab);
  await tab.evaluate(() => { closeCompareOverlay(); window.mockVisibility = 'hidden';
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => window.mockVisibility }); });
  await tab.evaluate(() => openPersistedReview('fresh'));
  assert.equal(await dot(tab, 'fresh').isVisible(), true, 'Background rendering is not yet a visible view');
  await tab.evaluate(() => { window.mockVisibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')); });
  assert.equal(await dot(tab, 'fresh').isVisible(), false);
  await tab.close(); await page.close();

  update('closed', { status: 'completed', attempt_count: 1, progress: 100 });
  model.hideClosed = true; // Saved tracking is independent of the history result window.
  page = await newPage();
  await page.waitForFunction(() => Boolean(document.querySelector('[data-history-job-id="closed"] .history-unread-dot:not([hidden])')));
  assert.equal(await page.locator('#historyUnreadCount').textContent(), '新完成 1');
  await page.locator('[data-history-job-id="closed"] [data-role="delete-recent-review"]').click();
  await page.locator('[data-role="confirm-delete-review"]').click();
  await page.waitForFunction(() => !document.querySelector('[data-history-job-id="closed"]'));
  assert.equal(await page.locator('#historyUnreadCount').isVisible(), false);
  assert.equal(await page.evaluate(() => mergeRecognitionStatus('closed', { status: 'completed', attempt_count: 1 })), false);

  update('fresh', { attempt_count: 5 }); await refresh(page);
  assert.equal(await dot(page, 'fresh').isVisible(), true);
  model.user = 'another-user';
  await page.evaluate(() => initializeIdentity());
  await page.waitForFunction(() => !state.recentReviewsLoading && state.recentReviews.length > 0);
  assert.equal(await dot(page, 'fresh').isVisible(), false, 'Different login has its own initial baseline');
  model.user = 'local-user';
  await page.evaluate(() => initializeIdentity());
  await page.waitForFunction(() => !state.recentReviewsLoading && state.recentReviews.length > 0);
  assert.equal(await dot(page, 'fresh').isVisible(), true, 'Original login keeps unread state');

  const stale = deferred(); model.listGate = stale;
  await page.evaluate(() => { window.staleList = loadRecentReviews(); });
  await page.waitForFunction(() => state.recentReviewsLoading);
  await page.locator('#apiBaseInput').evaluate((input) => { input.value = 'http://other-service.test'; input.dispatchEvent(new Event('change')); });
  await page.waitForFunction(() => state.identityReady && !state.recentReviewsLoading && state.recentReviews.length > 0);
  assert.equal(await dot(page, 'fresh').isVisible(), false, 'Different service has an independent baseline');
  stale.resolve(); await page.evaluate(() => staleList);
  assert.equal(await dot(page, 'fresh').isVisible(), false, 'Late old-service list cannot overwrite the new namespace');
  await page.close();

  const blocked = await context.newPage();
  blocked.on('pageerror', (error) => model.errors.push(error.message));
  await blocked.addInitScript(() => Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked storage'); } }));
  await blocked.goto(origin);
  await blocked.waitForFunction(() => state.identityReady && !state.recentReviewsLoading && state.recentReviews.length > 0);
  update('fresh', { attempt_count: 6 }); await refresh(blocked);
  assert.equal(await dot(blocked, 'fresh').isVisible(), true, 'Blocked storage uses session state');
  await blocked.close();
  assert.deepEqual(model.errors, [], 'No uncaught browser errors');
  assert.equal(model.writes.some(([method]) => method === 'PATCH'), false, 'Unread UI never saves review parameters');
  console.log(`PASS: unread dots/count/focus, load/save failures, refresh, recognition-round races, multi-tab receipts, hidden views, closed-page/out-of-window tasks, deletion, user/service isolation and storage fallback. Screenshots: ${output}`);
} finally { await context.close(); await browser.close(); await new Promise((resolve) => server.close(resolve)); }
