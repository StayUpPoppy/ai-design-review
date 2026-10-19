import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const frontend = path.resolve('frontend'), output = path.resolve('outputs/history-recognition-qa');
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
try {
  for (const [name, width] of [['desktop', 1440], ['narrow', 900], ['mobile', 430]]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    const errors = [], writes = [], polls = [];
    page.on('pageerror', (error) => errors.push(error.message));
    let time = 10, listFails = false;
    const offline = new Set();
    const stamp = () => `2026-10-19T01:00:${String(time++).padStart(2, '0')}Z`;
    let items = [
      { job_id: 'active', drawing_name: 'UQD08外弹簧(钢珠型)特别长的订单名称', drawing_no: 'YD4765020178', recognition_status: 'processing', recognition_progress: 35, recognition_attempt_count: 1 },
      { job_id: 'done', drawing_name: 'UQD08外弹簧(钢珠型)', drawing_no: 'YD4765020178', recognition_status: 'completed', recognition_progress: 100 },
      { job_id: 'failed', drawing_name: 'Spring(6.92x1.45)', drawing_no: 'H1742S0200', recognition_status: 'failed', recognition_progress: 55, recognition_attempt_count: 1, recognition_error: '模拟失败 <img src=x onerror=alert(1)>' },
      { job_id: 'queued', drawing_name: '压缩弹簧', drawing_no: '2426AM-95', recognition_status: 'queued', recognition_progress: 0, recognition_attempt_count: 0, queue_position: 3 },
      { job_id: 'legacy', drawing_name: '碳素弹簧钢丝', drawing_no: '2454BN-57', overall_status: 'need_review' },
      { job_id: 'unknown', drawing_name: '压缩弹簧', recognition_status: 'processing', recognition_progress: null, recognition_attempt_count: 1 },
      { job_id: 'cancelled', drawing_name: '待删除订单', recognition_status: 'cancel_requested' },
    ].map((item) => ({ ...item, spring_type: 'compression_spring', revision: 2, updated_at: stamp() }));
    const progress = new Map(items.map((item) => [item.job_id, { job_id: item.job_id, status: item.recognition_status,
      progress: item.recognition_progress, attempt_count: item.recognition_attempt_count, error_message: item.recognition_error,
      queue_position: item.queue_position, updated_at: item.updated_at }]));
    const update = (id, values) => {
      const entry = { ...progress.get(id), ...values, updated_at: stamp() }; progress.set(id, entry);
      const item = items.find((item) => item.job_id === id);
      Object.assign(item, { recognition_status: entry.status, recognition_progress: entry.progress,
        recognition_attempt_count: entry.attempt_count, recognition_error: entry.error_message, updated_at: entry.updated_at });
    };
    await page.route('**/api/**', async (route) => {
      const request = route.request(), apiPath = new URL(request.url()).pathname;
      if (request.method() !== 'GET') writes.push([request.method(), apiPath]);
      if (apiPath === '/api/session') return route.fulfill({ json: { identity: { user_id: 'demo', username: '本地状态验收' }, mode: 'mock' } });
      if (apiPath === '/api/material-catalog') return route.fulfill({ json: catalog });
      if (apiPath === '/api/reviews') return route.fulfill(listFails ? { status: 503, json: { detail: '模拟列表刷新失败' } } : { json: { reviews: items } });
      const match = apiPath.match(/^\/api\/reviews\/([^/]+)(?:\/(recognition-status|retry))?$/);
      if (match) {
        const [, id, action] = match;
        if (action === 'recognition-status') {
          polls.push(id);
          return route.fulfill(offline.has(id) ? { status: 503, json: { detail: '模拟进度网络失败' } }
            : { json: { job_id: id, recognition: progress.get(id) } });
        }
        if (action === 'retry') {
          update(id, { status: 'queued', progress: 0, error_message: '' });
          return route.fulfill({ status: 202, json: { job_id: id, recognition: progress.get(id) } });
        }
        if (request.method() === 'DELETE') { items = items.filter((item) => item.job_id !== id); return route.fulfill({ json: { deleted: true, job_id: id } }); }
        return route.fulfill({ json: { job_id: id, review_revision: 2, drawing_summary: { drawing_name: '本地模拟审图', spring_type: 'compression_spring' }, spring_parameters: {}, technical_requirements: [], manual_confirmations: {}, change_history: [] } });
      }
      if (apiPath.endsWith('/generation-jobs')) return route.fulfill({ json: { generation_jobs: [], generation_queue_available: false } });
      if (apiPath.endsWith('/annotations')) return route.fulfill({ json: { pages: [], annotations: [], warnings: [] } });
      if (apiPath.endsWith('/reasonableness')) return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
      if (apiPath.endsWith('/changes')) return route.fulfill({ json: { events: [] } });
      return route.fulfill({ json: { status: 'ok', generation_runtime: { status: 'not_configured' }, recognition_queue_runtime: { status: 'not_configured' } } });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => document.querySelectorAll('.history-order-item').length === 6 && !state.recentReviewsLoading);
    const row = (id) => page.locator(`[data-history-job-id="${id}"]`);
    assert.equal(await row('cancelled').count(), 0);
    assert.equal(await row('active').locator('.history-recognition-status').innerText(), '识别中\n35%');
    assert.equal(await row('done').locator('[data-role="recognition-label"]').textContent(), '识别完成');
    assert.equal(await row('legacy').locator('[data-role="recognition-label"]').textContent(), '识别完成');
    assert.equal(await row('failed').locator('[data-role="recognition-label"]').textContent(), '识别失败');
    assert.equal(await row('unknown').locator('[data-role="recognition-percentage"]').isVisible(), false);
    assert.equal(await row('queued').locator('[data-role="recognition-percentage"]').textContent(), '0%');
    assert.equal(await row('done').locator('[data-role="recognition-percentage"]').isVisible(), false);
    assert.equal(await row('failed').locator('img').count(), 0);
    const tooltip = await row('active').locator('.history-select-button').getAttribute('title');
    assert.ok(tooltip.includes('YD4765020178') && tooltip.includes('版本：2') && tooltip.includes('压缩弹簧'));
    assert.ok((await row('failed').locator('.history-select-button').getAttribute('title')).includes('模拟失败 <img'));
    assert.equal(await row('active').locator('.history-order-copy').innerText(), 'UQD08外弹簧(钢珠型)特别长的订单名称\n识别中\n35%');
    const order = await page.locator('.history-order-item').evaluateAll((rows) => rows.map((row) => row.dataset.historyJobId));
    await page.evaluate(() => { state.lastJob = { job_id: 'legacy' }; renderRecentReviews(); });
    await row('active').locator('.history-select-button').focus();
    await page.evaluate(() => {
      window.historyProbe = { button: document.activeElement, row: document.activeElement.closest('article'),
        spinner: document.querySelector('[data-history-job-id="active"] .is-spinning') };
      window.historyProbe.animation = window.historyProbe.spinner.getAnimations()[0];
    });
    update('active', { progress: 62 });
    await page.waitForFunction(() => document.querySelector('[data-history-job-id="active"] [data-role="recognition-percentage"]').textContent === '62%');
    assert.equal(await page.evaluate(() => document.activeElement === historyProbe.button
      && document.querySelector('[data-history-job-id="active"]') === historyProbe.row
      && document.querySelector('[data-history-job-id="active"] .is-spinning') === historyProbe.spinner
      && historyProbe.spinner.getAnimations()[0] === historyProbe.animation), true, 'Polling preserves nodes, animation and keyboard focus');
    assert.deepEqual(await page.locator('.history-order-item').evaluateAll((rows) => rows.map((row) => row.dataset.historyJobId)), order);
    assert.deepEqual(await row('active').locator('.history-recognition-status').evaluate((badge) => {
      const label = badge.querySelector('[data-role="recognition-label"]').getBoundingClientRect();
      const icon = badge.querySelector('[data-role="recognition-icon"]').getBoundingClientRect();
      const percentage = badge.querySelector('[data-role="recognition-percentage"]').getBoundingClientRect();
      return { width: icon.width, height: icon.height, gapBefore: icon.left - label.right, gapAfter: percentage.left - icon.right };
    }), { width: 14, height: 14, gapBefore: 6, gapAfter: 6 });
    for (const id of order) assert.equal(await row(id).evaluate((row) => {
      const outer = row.getBoundingClientRect();
      return [...row.querySelectorAll('button,.history-recognition-status')].some((element) => {
        const rect = element.getBoundingClientRect(); return rect.width && (rect.right > outer.right + 1 || rect.left < outer.left - 1);
      });
    }), false, `${id}: controls fit the row`);
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.locator('#recentReviews').screenshot({ path: path.join(output, `${name}.png`) });
    update('active', { progress: null });
    await page.waitForFunction(() => state.recentReviews.find((item) => item.job_id === 'active')?.updated_at !== undefined);
    await page.waitForTimeout(2100);
    assert.equal(await row('active').locator('[data-role="recognition-percentage"]').textContent(), '62%');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await row('active').locator('.is-spinning').evaluate((svg) => getComputedStyle(svg).animationName), 'none');
    update('active', { progress: 78 });
    await page.waitForFunction(() => document.querySelector('[data-history-job-id="active"] [data-role="recognition-percentage"]').textContent === '78%');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    update('active', { status: 'completed', progress: 100 });
    await page.waitForFunction(() => document.querySelector('[data-history-job-id="active"] .history-recognition-status').dataset.status === 'completed');
    assert.equal(await row('active').locator('.is-spinning').count(), 0);
    assert.equal(await row('active').locator('[data-role="recognition-percentage"]').isVisible(), false);
    assert.equal(await page.evaluate(() => Boolean(state.recognitionPollers.active)), false);
    await row('failed').getByRole('button', { name: '重试', exact: true }).click();
    await page.waitForFunction(() => state.recentReviews.find((item) => item.job_id === 'failed').recognition_status === 'queued');
    assert.equal(await page.locator('.history-order-item.active').count(), 1);
    assert.equal(await page.locator('.history-order-item.active').getAttribute('data-history-job-id'), 'failed');
    assert.equal(await row('failed').locator('[data-role="recognition-percentage"]').textContent(), '0%');
    assert.equal(await row('failed').getByRole('button', { name: '重试', exact: true }).count(), 0);
    offline.add('queued');
    await page.waitForFunction(() => state.recentReviews.find((item) => item.job_id === 'queued').recognition_sync_error);
    assert.equal(await row('queued').locator('[data-role="recognition-label"]').textContent(), '识别中');
    assert.ok((await row('queued').locator('.history-select-button').getAttribute('title')).includes('进度暂时无法刷新'));
    offline.delete('queued'); update('queued', { status: 'processing', progress: 55, attempt_count: 1 });
    items.reverse();
    await page.getByRole('button', { name: '刷新历史订单', exact: true }).click();
    await page.waitForFunction(() => state.recentReviews.find((item) => item.job_id === 'queued').recognition_progress === 55 && !state.recentReviewsLoading);
    assert.equal(await row('queued').locator('[data-role="recognition-percentage"]').textContent(), '55%');
    assert.deepEqual(await page.locator('.history-order-item').evaluateAll((rows) => rows.map((row) => row.dataset.historyJobId)), order, 'Server sorting caused by progress must not shuffle the visible history');
    assert.equal(await page.evaluate(() => document.querySelector('[data-history-job-id="active"]') === historyProbe.row), true, 'Explicit refresh also preserves row identity');
    listFails = true; await page.getByRole('button', { name: '刷新历史订单', exact: true }).click();
    await page.waitForFunction(() => !state.recentReviewsLoading);
    assert.equal(await page.locator('.history-order-item').count(), 6, 'List errors retain the last usable records');
    listFails = false;
    await row('done').getByRole('button', { name: '删除订单', exact: true }).click();
    await page.getByRole('button', { name: '删除', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('[data-history-job-id="done"]'));
    assert.equal(await page.evaluate(() => mergeRecognitionStatus('done', { status: 'completed', progress: 100 })), false, 'Deleted rows cannot be recreated by a late response');
    assert.ok(writes.some(([method, url]) => method === 'POST' && url.endsWith('/failed/retry')));
    assert.ok(writes.some(([method, url]) => method === 'DELETE' && url.endsWith('/done')));
    assert.equal(writes.some(([method]) => method === 'PATCH'), false, 'History updates never save review content');
    assert.deepEqual(errors, [], `${name}: no uncaught browser errors`);
    assert.ok(polls.includes('active'));
    await page.close();
  }
  console.log(`PASS: live history badges, SVGs, percentages, stable animation/focus/order, retry/delete, reduced motion and desktop/narrow/mobile. Screenshots: ${output}`);
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
