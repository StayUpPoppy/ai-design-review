import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const frontend = path.resolve('frontend'), output = path.resolve('outputs/history-bulk-delete-qa');
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
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const row = (page, id) => page.locator(`[data-history-job-id="${id}"]`);
async function scenario(count = 6) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const model = { page, jobs: new Map(), calls: [], reads: [], errors: [], faults: new Map(), gate: null, user: 'bulk-local', active: 0, peak: 0 };
  for (let index = 0; index < count; index++) model.jobs.set(String(index), { job_id: String(index), drawing_name: index === 0 ? '特别长的订单标题 <img src=x> 压缩弹簧' : `压缩弹簧 ${index}`,
    recognition_status: index === 1 ? 'processing' : 'completed', recognition_attempt_count: 1, recognition_progress: index === 1 ? 42 : 100, updated_at: new Date().toISOString() });
  page.on('pageerror', (error) => model.errors.push(error.message));
  await page.route('**/api/**', async (route) => {
    const request = route.request(), api = new URL(request.url()).pathname, method = request.method();
    if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: model.user, username: '批量删除离线验收' } } });
    if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
    if (api === '/api/reviews') return route.fulfill({ json: { reviews: [...model.jobs.values()] } });
    const match = api.match(/^\/api\/reviews\/([^/]+)(?:\/(recognition-status))?$/);
    if (match) {
      const [, id, action] = match, job = model.jobs.get(id);
      if (action) return route.fulfill({ json: { job_id: id, recognition: { ...job, status: job?.recognition_status, progress: job?.recognition_progress, attempt_count: job?.recognition_attempt_count } } });
      if (method === 'DELETE') {
        model.calls.push(id); model.peak = Math.max(model.peak, ++model.active);
        try {
          if (model.gate) { const gate = model.gate; model.gate = null; await gate.promise; }
          const fault = model.faults.get(id);
          if (fault === 'network') return route.abort('connectionfailed');
          if (typeof fault === 'number') return route.fulfill({ status: fault, json: { detail: `模拟删除失败 ${fault}` } });
          model.jobs.delete(id);
          return route.fulfill({ json: { job_id: id, deleted: true, ...(id === '1' ? { status: 'cancelling', artifact_cleanup: 'pending_worker_cancellation' }
            : { artifact_cleanup: id === '0' ? 'pending' : 'deleted' }) } });
        } finally { model.active--; }
      }
      model.reads.push(id);
      return route.fulfill({ json: { job_id: id, review_revision: 1, drawing_summary: { drawing_name: job?.drawing_name, spring_type: 'compression_spring' },
        spring_parameters: {}, technical_requirements: [], manual_confirmations: {}, change_history: [] } });
    }
    if (api.endsWith('/generation-jobs')) return route.fulfill({ json: { generation_jobs: [], generation_queue_available: false } });
    if (api.endsWith('/annotations')) return route.fulfill({ json: { pages: [], annotations: [], warnings: [] } });
    if (api.endsWith('/reasonableness')) return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
    if (api.endsWith('/changes')) return route.fulfill({ json: { events: [] } });
    return route.fulfill({ json: { status: 'ok', generation_runtime: { status: 'not_configured' }, recognition_queue_runtime: { status: 'not_configured' } } });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction((count) => state.identityReady && !state.recentReviewsLoading && state.recentReviews.length === count, count);
  return model;
}
async function manageAll(page) {
  await page.locator('#enterHistoryManagement').click(); await page.locator('#historySelectAll').click();
}
async function confirm(page) { await page.locator('[data-role="confirm-delete-review"]').click(); }
try {
  const model = await scenario(), { page } = model;
  await page.evaluate(() => { const item = state.recentReviews.find((entry) => entry.job_id === '0');
    mergeRecognitionStatus('0', { status: 'completed', attempt_count: 2, updated_at: new Date(Date.now() + 100).toISOString() }); });
  await page.locator('#enterHistoryManagement').click();
  assert.equal(await page.locator('#historyManagement').isVisible(), true, 'Selection controls still expand below the heading');
  await row(page, '0').locator('input[type="checkbox"]').focus(); await page.keyboard.press('Space');
  assert.equal(await row(page, '0').locator('input').isChecked(), true);
  await row(page, '2').locator('.history-select-button').click();
  assert.equal(await page.locator('#historySelectedCount').textContent(), '已选2项');
  assert.deepEqual(model.reads, []); assert.equal(await row(page, '0').locator('.history-unread-dot').isVisible(), true);
  assert.equal(await row(page, '0').locator('.history-delete-button').isVisible(), false);
  model.jobs.set('new', { job_id: 'new', drawing_name: '新到订单', recognition_status: 'completed', recognition_attempt_count: 1 });
  await page.evaluate(() => loadRecentReviews());
  assert.equal(await row(page, 'new').locator('input').isChecked(), false);
  assert.equal(await row(page, '0').locator('input').isChecked(), true);
  model.jobs.delete('new'); await page.evaluate(() => loadRecentReviews());
  await page.locator('#historySelectAll').click();
  await page.locator('#historyDeleteSelected').click();
  assert.equal(await page.locator('.delete-review-dialog li').count(), 6);
  assert.equal(await page.locator('.delete-review-dialog img').count(), 0, 'Order names are escaped');
  await page.evaluate(() => { window.originalFlush = flushReviewPersistence; flushReviewPersistence = async () => false; });
  await confirm(page);
  await page.waitForFunction(() => !historyDeletion.state.running);
  assert.deepEqual(model.calls, []); assert.equal(await page.locator('.delete-review-dialog').isVisible(), true);
  assert.ok((await page.locator('[data-role="delete-review-error"]').textContent()).includes('保存'));
  await page.keyboard.press('Escape');
  await page.locator('#exitHistoryManagement').click();
  assert.equal(await page.locator('#historyManagement').isVisible(), false);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'enterHistoryManagement');
  await row(page, '0').locator('.history-delete-button').click(); await confirm(page);
  await page.waitForFunction(() => !historyDeletion.state.running);
  assert.deepEqual(model.calls, [], 'Single deletion also obeys the save result');
  await page.keyboard.press('Escape');
  await page.evaluate(() => { flushReviewPersistence = originalFlush; });
  await page.evaluate(async () => { await openPersistedReview('0'); closeCompareOverlay(); });
  assert.equal(await page.evaluate(() => state.lastJob.job_id), '0');
  await manageAll(page);
  for (const [name, width] of [['desktop', 1440], ['narrow', 900], ['mobile', 430]]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.locator('#historyManagement').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('#historyManagement').evaluate((panel) => {
      const box = panel.getBoundingClientRect(); return [...panel.querySelectorAll('button:not([hidden])')].some((button) => {
        const rect = button.getBoundingClientRect(); return rect.width && (rect.right > box.right + 1 || rect.left < box.left - 1); });
    }), false, `${name}: management controls wrap within the sidebar`);
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.locator('#recentReviews').screenshot({ path: path.join(output, `${name}.png`) });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  model.faults.set('2', 500); model.faults.set('3', 'network'); model.faults.set('4', 401);
  const gate = deferred(); model.gate = gate;
  await page.locator('#historyDeleteSelected').click(); await confirm(page);
  await page.waitForFunction(() => historyDeletion.state.running);
  assert.equal(await page.locator('#exitHistoryManagement').isDisabled(), true);
  assert.equal(await page.locator('#apiBaseInput').isDisabled(), true);
  assert.equal(await page.evaluate(() => compareOverlay.inert && conversation.inert), true);
  await page.keyboard.press('Escape'); assert.equal(await page.locator('.delete-review-dialog').isVisible(), true);
  await page.evaluate(() => mergeRecognitionStatus('1', { status: 'processing', progress: 65, attempt_count: 1, updated_at: new Date(Date.now() + 200).toISOString() }));
  assert.equal(await row(page, '1').locator('[data-role="recognition-percentage"]').textContent(), '65%');
  gate.resolve();
  await page.waitForFunction(() => !historyDeletion.state.running && !document.querySelector('.delete-review-dialog'));
  assert.deepEqual(model.calls, ['0', '1', '2', '3', '4']);
  assert.equal(await page.evaluate(() => state.review), null, 'Deleting the current order clears its review');
  assert.equal(await page.locator('#historySelectedCount').textContent(), '已选4项');
  assert.equal(await page.evaluate(() => historyDeletion.summary().pending), 1);
  assert.ok((await page.locator('#historyDeletionSummary').textContent()).includes('文件清理未完成1'));
  assert.equal(await page.evaluate(() => mergeRecognitionStatus('0', { status: 'completed', attempt_count: 2 })), false);
  assert.equal(await page.locator('#historyUnreadCount').isVisible(), false);
  model.faults.delete('2'); model.faults.delete('4');
  await page.locator('#historyRetryFailed').click();
  assert.equal(await page.locator('.delete-review-dialog li').count(), 2); await confirm(page);
  await page.waitForFunction(() => !historyDeletion.state.running && !document.querySelector('.delete-review-dialog'));
  assert.deepEqual(model.calls, ['0', '1', '2', '3', '4', '2', '4']);
  assert.equal(await page.locator('#historySelectedCount').textContent(), '已选2项');
  assert.equal(await page.evaluate(() => historyDeletion.state.managing), true);
  await page.locator('#historyCheckUnknown').click();
  await page.waitForFunction(() => historyDeletion.state.results.get('3').checked);
  model.faults.delete('3'); await page.locator('#historyDeleteSelected').click(); await confirm(page);
  await page.waitForFunction(() => !historyDeletion.state.running && !historyDeletion.state.managing);
  assert.deepEqual(model.calls.slice(-2), ['3', '5']); assert.equal(model.peak, 1);
  assert.equal(await page.locator('.history-order-item').count(), 0);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'refreshRecentReviewsButton', 'After deleting every order, focus falls back to the available refresh action');
  await page.locator('#historyClearDeletionResults').click();
  assert.equal(await page.locator('#historyManagement').isVisible(), false, 'Clearing results restores the compact header');
  assert.equal(await page.evaluate(() => conversation.inert || compareOverlay.inert), false);
  assert.deepEqual(model.errors, []); await page.close();

  const hundred = await scenario(100);
  await hundred.page.evaluate(() => { window.keptReview = state.review = { marker: 'unsaved draft preserved' }; state.lastJob = { job_id: 'unselected-current' }; });
  await manageAll(hundred.page); await hundred.page.locator('#historyDeleteSelected').click(); await confirm(hundred.page);
  await hundred.page.waitForFunction(() => !historyDeletion.state.running && historyDeletion.summary().deleted === 99 && historyDeletion.summary().cancelling === 1, null, { timeout: 60000 });
  assert.equal(hundred.calls.length, 100); assert.equal(hundred.peak, 1);
  assert.equal(await hundred.page.evaluate(() => state.review === keptReview && state.lastJob.job_id === 'unselected-current'), true);
  assert.equal(await hundred.page.evaluate(() => historyDeletion.state.selected.size), 0);
  assert.deepEqual(hundred.errors, []); await hundred.page.close();

  const late = await scenario(2); const delayed = deferred(); late.gate = delayed;
  await manageAll(late.page); await late.page.locator('#historyDeleteSelected').click(); await confirm(late.page);
  await late.page.waitForFunction(() => historyDeletion.state.running);
  late.user = 'new-user'; await late.page.evaluate(() => initializeIdentity());
  await late.page.waitForFunction(() => state.identityReady && !state.recentReviewsLoading && state.recentReviews.length === 2);
  delayed.resolve();
  await late.page.waitForFunction(() => !document.querySelector('.delete-review-dialog'));
  assert.equal(await row(late.page, '0').count(), 1, 'Old response does not remove the new session row');
  assert.equal(late.calls.length, 1, 'Scope change stops the remaining batch');
  assert.deepEqual(late.errors, []); await late.page.close();
  console.log(`PASS: native selection/keyboard, progress stability, save guards, frozen batch, partial failures, unknown check, cancellation, auth stop, current review protection, 100 sequential HTTP deletes and stale-session response. Screenshots: ${output}`);
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
