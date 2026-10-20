import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const frontend = path.resolve('frontend'), output = path.resolve('outputs/history-sidebar-qa');
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
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const jobs = Array.from({ length: 35 }, (_, index) => ({ job_id: `sidebar-${index}`, drawing_name: `压缩弹簧 ${index} · 较长的历史订单名称`,
  status: index === 0 ? 'processing' : 'completed', progress: index === 0 ? 20 : 100, attempt_count: 1, updated_at: new Date().toISOString() }));
const writes = [], errors = [];
await context.route('**/api/**', async (route) => {
  const request = route.request(), api = new URL(request.url()).pathname;
  if (request.method() !== 'GET') writes.push([request.method(), api]);
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'sidebar-test', username: '本地侧栏验收' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') return route.fulfill({ json: { reviews: jobs.map((item) => ({ ...item, recognition_status: item.status,
    recognition_progress: item.progress, recognition_attempt_count: item.attempt_count, revision: 1 })) } });
  const match = api.match(/^\/api\/reviews\/(sidebar-\d+)(?:\/(recognition-status))?$/);
  if (match) {
    const item = jobs.find((job) => job.job_id === match[1]);
    if (match[2]) return route.fulfill({ json: { job_id: item.job_id, recognition: item } });
    return route.fulfill({ json: { job_id: item.job_id, review_revision: 1, drawing_summary: { drawing_name: item.drawing_name,
      spring_type: 'compression_spring' }, spring_parameters: {}, technical_requirements: [], manual_confirmations: {}, change_history: [] } });
  }
  if (api.endsWith('/annotations')) return route.fulfill({ json: { pages: [], annotations: [], warnings: [] } });
  if (api.endsWith('/changes')) return route.fulfill({ json: { events: [] } });
  if (api.endsWith('/generation-jobs')) return route.fulfill({ json: { generation_jobs: [], generation_queue_available: false } });
  if (api.endsWith('/reasonableness')) return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
  return route.fulfill({ json: { status: 'ok', generation_runtime: { status: 'not_configured' }, recognition_queue_runtime: { status: 'not_configured' } } });
});
const origin = `http://127.0.0.1:${server.address().port}`;
async function ready(page) {
  await page.waitForFunction(() => state.identityReady && !state.recentReviewsLoading && state.recentReviews.length === 35);
}
const settled = (page) => page.waitForFunction(() => !document.querySelector('.app-workspace').classList.contains('is-history-animating'));
async function sampleNextToggle(page) {
  await page.evaluate(() => {
    window.sidebarMotionFrames = [];
    document.getElementById('toggleHistorySidebar').addEventListener('click', () => {
      const sample = () => {
        const sidebar = document.getElementById('recentReviews'), content = document.getElementById('historySidebarContent');
        const box = sidebar.getBoundingClientRect(), button = document.getElementById('toggleHistorySidebar').getBoundingClientRect();
        const running = sidebar.classList.contains('is-animating');
        sidebarMotionFrames.push({ running, width: box.width, height: box.height, contentWidth: content.getBoundingClientRect().width,
          hidden: content.hidden, inert: content.inert, transform: getComputedStyle(content).transform,
          duration: getComputedStyle(sidebar.closest('.app-workspace')).transitionDuration,
          buttonCenterX: button.left + button.width / 2, buttonCenterY: button.top + button.height / 2,
          buttonVisible: button.left >= box.left - 1 && button.right <= box.right + 1 && button.top >= box.top - 1 && button.bottom <= box.bottom + 1 });
        if (running) requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    }, { once: true });
  });
}
async function assertSliding(page, originalSize, mobile) {
  const frames = await page.evaluate(() => sidebarMotionFrames);
  const moving = frames.filter((frame) => frame.running);
  assert.ok(moving.some((frame) => frame[mobile ? 'height' : 'width'] > 40.5 && frame[mobile ? 'height' : 'width'] < originalSize - .5), 'A real intermediate layout is rendered, not an immediate jump');
  assert.ok(moving.every((frame) => !frame.hidden && frame.inert), 'Closing content stays rendered but cannot be interacted with');
  assert.ok(moving.every((frame) => frame.buttonVisible), 'The toggle remains inside the visible rail throughout the slide');
  assert.ok(Math.max(...moving.map((frame) => frame.contentWidth)) - Math.min(...moving.map((frame) => frame.contentWidth)) < 1, 'List text never squeezes or reflows during the slide');
  assert.ok(moving.some((frame) => frame.transform !== 'none' && frame.transform !== 'matrix(1, 0, 0, 1, 0, 0)'), 'Content slides rather than only changing the outer width');
  assert.ok(moving.every((frame) => frame.duration.split(',').every((duration) => Math.abs(parseFloat(duration) - .22) < .001)), 'Layout transitions use the agreed 220ms duration');
  const finalButton = await page.locator('#toggleHistorySidebar').boundingBox(), last = moving.at(-1);
  assert.ok(Math.hypot(finalButton.x + finalButton.width / 2 - last.buttonCenterX, finalButton.y + finalButton.height / 2 - last.buttonCenterY) < 3, 'The button does not jump to a different corner when the animation finishes');
}
try {
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => dialog.accept());
  await page.goto(origin); await ready(page);
  const toggle = page.locator('#toggleHistorySidebar'), sidebar = page.locator('#recentReviews');
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  const originalWidth = (await sidebar.boundingBox()).width;
  await page.evaluate(async () => { await openPersistedReview('sidebar-1'); closeCompareOverlay(); });
  await page.waitForFunction(() => state.review?.parameter_reasonableness?.status === 'ok');
  await page.evaluate(() => {
    state.review.spring_parameters.wire_diameter = { value: 1.8, unit: 'mm', need_human_review: true };
    state.reviewDraftFields.add('wire_diameter');
    window.sidebarDraft = state.review; window.sidebarDraftJson = JSON.stringify(state.review);
    window.sidebarSaveCalls = 0; window.sidebarOriginalFlush = flushReviewPersistence;
    flushReviewPersistence = async () => { sidebarSaveCalls++; return false; };
  });
  await page.locator('#drawingInput').setInputFiles({ name: '待上传.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-local-only') });
  await page.waitForFunction(() => drawingUploads.pending.length === 1);
  const pendingId = await page.evaluate(() => drawingUploads.pending[0].id);
  await page.locator('#enterHistoryManagement').click();
  await page.locator('[data-history-job-id="sidebar-1"] .history-selection-checkbox').check();
  await page.locator('[data-history-job-id="sidebar-2"] .history-selection-checkbox').check();
  const expandedStageWidth = (await page.locator('.chat-stage').boundingBox()).width;
  const scroll = await sidebar.evaluate((element) => { element.scrollTop = 310; return element.scrollTop; });
  assert.ok(scroll > 0);
  writes.length = 0; // Opening a review may POST a read-only design assessment; measure only the toggles below.
  await page.evaluate(() => { window.sidebarFirstRow = document.querySelector('[data-history-job-id="sidebar-1"]'); });
  await sampleNextToggle(page);
  await toggle.click();
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(await toggle.getAttribute('aria-label'), '展开历史订单');
  await settled(page);
  await assertSliding(page, originalWidth, false);
  assert.equal((await sidebar.boundingBox()).width, 40);
  assert.equal(await page.locator('#historySidebarContent').isVisible(), false);
  assert.equal(await page.locator('#newReviewButton').isVisible(), false);
  assert.ok((await page.locator('.chat-stage').boundingBox()).width > expandedStageWidth + 200);
  assert.equal(await toggle.evaluate((element) => document.activeElement === element), true);
  jobs[0].progress = 65; jobs[0].updated_at = new Date(Date.now() + 1000).toISOString();
  await page.waitForFunction(() => state.recentReviews.find((item) => item.job_id === 'sidebar-0').recognition_progress === 65);
  jobs[0].status = 'completed'; jobs[0].progress = 100; jobs[0].updated_at = new Date(Date.now() + 2000).toISOString();
  await page.waitForFunction(() => document.querySelector('#historyUnreadCount').textContent === '新完成 1');
  assert.equal(await page.evaluate(() => state.recognitionPollers['sidebar-0'] == null), true, 'Hidden sidebar still polls through completion');
  await toggle.press('Enter');
  await settled(page);
  assert.equal((await sidebar.boundingBox()).width, originalWidth);
  assert.equal(await sidebar.evaluate((element) => element.scrollTop), scroll);
  assert.equal(await page.locator('#historyUnreadCount').isVisible(), true);
  assert.deepEqual(await page.evaluate(() => [...historyDeletion.state.selected]), ['sidebar-1', 'sidebar-2']);
  assert.equal(await page.evaluate(() => sidebarFirstRow === document.querySelector('[data-history-job-id="sidebar-1"]')), true, 'No list teardown during collapse or progress updates');
  assert.equal(await page.evaluate(() => state.review === sidebarDraft && JSON.stringify(state.review) === sidebarDraftJson && state.reviewDraftFields.has('wire_diameter')), true);
  assert.equal(await page.evaluate(() => drawingUploads.pending[0].id), pendingId);
  assert.equal(await page.evaluate(() => sidebarSaveCalls), 0, 'Toggling never flushes even a failing save queue');
  assert.deepEqual(writes, [], 'Presentation-only changes never write parameters, annotations or orders');
  for (const width of [1440, 900, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await sidebar.evaluate((element) => { element.scrollTop = 0; });
    assert.equal(await page.locator('.history-sidebar-top').evaluate((element) => {
      const a = element.querySelector('#newReviewButton').getBoundingClientRect(), b = element.querySelector('#toggleHistorySidebar').getBoundingClientRect();
      return a.right <= b.left && Math.abs(a.top - b.top) < 1;
    }), true, 'New review and sidebar toggle fit on one row');
    const listScroll = await page.locator('#recentReviewList').evaluate((element) => { element.scrollLeft = 270; return element.scrollLeft; });
    const expandedSize = (await sidebar.boundingBox())[width <= 640 ? 'height' : 'width'];
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(output, `expanded-${width}.png`) });
    await sampleNextToggle(page);
    await toggle.click();
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(output, `sliding-${width}.png`), animations: 'allow' });
    await settled(page);
    await assertSliding(page, expandedSize, width <= 640);
    const box = await sidebar.boundingBox();
    assert.equal(width <= 640 ? box.height : box.width, 40);
    assert.equal(await toggle.isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(output, `collapsed-${width}.png`) });
    await toggle.press('Space');
    await settled(page);
    assert.equal(await page.locator('#recentReviewList').evaluate((element) => element.scrollLeft), listScroll);
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  const reversal = await page.evaluate(async () => {
    const button = document.getElementById('toggleHistorySidebar'), sidebar = document.getElementById('recentReviews');
    button.click();
    const obsolete = historySidebarMotion;
    for (let i = 0; i < 3; i++) await new Promise(requestAnimationFrame);
    const before = sidebar.getBoundingClientRect().width;
    button.click();
    const after = sidebar.getBoundingClientRect().width;
    obsolete.onEnd(new TransitionEvent('transitionend', { propertyName: 'grid-template-columns' }));
    return { before, after, running: Boolean(historySidebarMotion), collapsed: state.historySidebarCollapsed };
  });
  assert.ok(Math.abs(reversal.before - reversal.after) < 1, 'Reversal begins at the current on-screen position');
  assert.equal(reversal.running, true);
  assert.equal(reversal.collapsed, false);
  await settled(page);
  assert.equal(await page.locator('#historySidebarContent').evaluate((element) => element.inert || element.hidden), false);
  await page.evaluate(async () => {
    const button = document.getElementById('toggleHistorySidebar');
    button.click(); for (let i = 0; i < 2; i++) await new Promise(requestAnimationFrame);
    button.click(); await new Promise(requestAnimationFrame); button.click();
  });
  await settled(page);
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false', 'Rapid alternating clicks settle at the last choice');
  assert.equal(await page.locator('#historySidebarContent').isVisible(), false);
  await toggle.click();
  await page.setViewportSize({ width: 390, height: 844 });
  await settled(page);
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  assert.ok((await sidebar.boundingBox()).height > 40, 'Crossing to mobile settles the requested expanded layout');
  await toggle.click();
  await page.setViewportSize({ width: 900, height: 430 });
  await settled(page);
  assert.equal((await sidebar.boundingBox()).width, 40, 'Rotation/breakpoint changes keep the latest collapsed choice');
  await toggle.click(); await settled(page);
  await toggle.click();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await settled(page);
  assert.equal((await sidebar.boundingBox()).width, 40);
  await toggle.click();
  assert.equal(await page.evaluate(() => historySidebarMotion), null, 'Reduced motion uses immediate switching');
  assert.equal((await sidebar.boundingBox()).width, 216);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  assert.equal(await page.evaluate(() => state.review === sidebarDraft && JSON.stringify(state.review) === sidebarDraftJson), true);
  assert.deepEqual(await page.evaluate(() => [...historyDeletion.state.selected]), ['sidebar-1', 'sidebar-2']);
  assert.equal(await page.evaluate(() => drawingUploads.pending[0].id), pendingId);
  assert.equal(await page.evaluate(() => sidebarSaveCalls), 0);
  await page.evaluate(() => { flushReviewPersistence = sidebarOriginalFlush; state.reviewDraftFields.clear(); });
  await page.locator('#clearUploadsButton').click();
  await toggle.click();
  await page.reload(); await ready(page);
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false', 'Browser preference survives reload');
  assert.equal(await page.evaluate(() => historySidebarMotion), null, 'Reload restores the saved choice without a slide');
  assert.equal(await page.locator('#historyUnreadCount').textContent(), '新完成 1', 'Collapse does not acknowledge unread results');
  await toggle.click(); await page.reload(); await ready(page);
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  await context.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new Error('storage unavailable'); };
    Storage.prototype.setItem = () => { throw new Error('storage unavailable'); };
  });
  await page.reload(); await ready(page);
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  await toggle.click(); assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
  await settled(page);
  await toggle.click(); assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  await settled(page);
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  console.log('PASS: 220ms native slide with intermediate frames, fixed text layout, visible toggle, reversal/stale completion guards, resize/rotation/reduced-motion interruption, focus/scroll/selection/draft/upload preservation, progress/unread updates, reload without animation and storage fallback; zero API writes.');
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
