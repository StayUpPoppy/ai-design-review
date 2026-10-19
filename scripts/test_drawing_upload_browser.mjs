import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const frontend = path.resolve('frontend'), output = path.resolve('outputs/batch-upload-qa');
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'drawing-upload-'));
const folder = path.join(temporary, 'orders');
fs.mkdirSync(path.join(folder, 'nested'), { recursive: true });
for (const [name, body] of [['a.pdf', '%PDF-test'], ['nested/a.pdf', '%PDF-other'], ['nested/readme.txt', 'not a drawing'], ['empty.jpg', '']]) {
  fs.writeFileSync(path.join(folder, name), body);
}
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
const input = (name) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-local-test') });
async function scenario(width = 1440) {
  const page = await browser.newPage({ viewport: { width, height: 1000 } });
  const model = { page, jobs: new Map(), uploads: [], retries: [], errors: [], writes: [], getReviews: [], offline: new Set(),
    failures: new Map(), truncate: false, serial: 0, active: 0, peak: 0, uploadGate: null, reviewGate: null, listQueries: [] };
  let time = Date.now();
  model.update = (id, values) => Object.assign(model.jobs.get(id), values, { updated_at: new Date(++time).toISOString() });
  page.on('pageerror', (error) => model.errors.push(error.message));
  await page.route('**/api/**', async (route) => {
    const request = route.request(), url = new URL(request.url()), api = url.pathname, method = request.method();
    if (method !== 'GET') model.writes.push([method, api]);
    if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'local-test', username: '离线批量验收' } } });
    if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
    if (api === '/api/reviews' && method === 'POST') {
      const text = request.postDataBuffer().toString('utf8');
      const name = text.match(/name="drawing"; filename="([^"]+)"/)[1];
      model.uploads.push({ name, text }); model.peak = Math.max(model.peak, ++model.active);
      try {
        if (model.uploadGate) await model.uploadGate.promise;
        const fail = model.failures.get(name);
        if (fail === 'network') return route.abort('connectionfailed');
        if (fail) return route.fulfill({ status: fail, json: { detail: `模拟上传错误 ${fail}` } });
        const id = `upload-${++model.serial}`;
        model.jobs.set(id, { job_id: id, drawing_name: name, status: 'queued', stage: 'queued', progress: 0, attempt_count: 0, updated_at: new Date(++time).toISOString() });
        return route.fulfill({ status: 202, json: { job_id: id, recognition_status: 'queued', recognition_progress: 0 } });
      } finally { model.active--; }
    }
    if (api === '/api/reviews') {
      model.listQueries.push(url.searchParams.get('limit'));
      let jobs = [...model.jobs.values()].reverse();
      if (model.truncate) jobs = jobs.slice(0, 20);
      return route.fulfill({ json: { reviews: jobs.map((job) => ({ ...job, recognition_status: job.status,
        recognition_progress: job.progress, recognition_attempt_count: job.attempt_count, recognition_error: job.error_message })) } });
    }
    const match = api.match(/^\/api\/reviews\/([^/]+)(?:\/(recognition-status|retry))?$/);
    if (match) {
      const [, id, action] = match;
      if (action === 'recognition-status') return route.fulfill(model.offline.has(id)
        ? { status: 503, json: { detail: '模拟进度刷新失败' } } : { json: { job_id: id, recognition: model.jobs.get(id) } });
      if (action === 'retry') {
        model.retries.push(id); model.update(id, { status: 'queued', progress: 0, error_message: '' });
        return route.fulfill({ status: 202, json: { job_id: id, recognition: model.jobs.get(id) } });
      }
      if (method === 'DELETE') { model.jobs.delete(id); return route.fulfill({ json: { deleted: true } }); }
      if (method === 'PATCH') return route.fulfill({ json: { job_id: id, review_revision: 2 } });
      model.getReviews.push(id);
      if (model.reviewGate) await model.reviewGate.promise;
      return route.fulfill({ json: { job_id: id, review_revision: 1,
        drawing_summary: { drawing_name: '本地模拟图纸', spring_type: 'compression_spring' }, spring_parameters: {},
        technical_requirements: [], manual_confirmations: {}, change_history: [] } });
    }
    if (api.endsWith('/generation-jobs')) return route.fulfill({ json: { generation_jobs: [], generation_queue_available: false } });
    if (api.endsWith('/annotations')) return route.fulfill({ json: { pages: [], annotations: [], warnings: [] } });
    if (api.endsWith('/reasonableness')) return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
    if (api.endsWith('/changes')) return route.fulfill({ json: { events: [] } });
    return route.fulfill({ json: { status: 'ok', generation_runtime: { status: 'not_configured' }, recognition_queue_runtime: { status: 'not_configured' } } });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && !state.recentReviewsLoading);
  return model;
}
const collected = async (page, count) => page.waitForFunction((count) => !drawingUploads.scanning
  && drawingUploads.entries.length === count && document.querySelectorAll('.upload-file').length === count, count);
const clear = async (page) => { await page.locator('#clearUploadsButton').click(); await page.waitForFunction(() => drawingUploads.unsubmitted.length === 0 && !drawingUploads.scanning); };
const expand = async (page, id) => {
  const section = page.locator(`#${id}`);
  if (!await section.evaluate((element) => element.open)) await section.locator('summary').click();
};
const rowFor = (page, name) => page.locator('.upload-file').filter({ has: page.locator('.upload-file-name', { hasText: name }) });
try {
  const model = await scenario(), { page } = model;
  await page.locator('#drawingInput').setInputFiles([input('first.pdf'), input('second.pdf')]); await collected(page, 2);
  assert.equal(model.uploads.length, 0, 'Selection must never submit automatically');
  assert.equal(await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented;
  }), true, 'Unsubmitted files participate in the existing leave-page protection');
  await page.evaluate(() => { window.originalUploadFlush = flushReviewPersistence; flushReviewPersistence = async () => false; });
  await page.locator('#submitButton').click();
  await page.waitForFunction(() => !uploadPreparing);
  assert.equal(model.uploads.length, 0, 'Failed review persistence blocks all uploads');
  assert.equal(await page.evaluate(() => drawingUploads.pending.length), 2, 'Failed save preserves local files');
  await page.evaluate(() => { flushReviewPersistence = originalUploadFlush; });
  await page.locator('.upload-file').first().getByRole('button', { name: '移除', exact: true }).click(); await collected(page, 1); await clear(page);
  assert.equal(await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented;
  }), false, 'Clearing unsent files releases the leave-page guard');
  await page.locator('#drawingFolderInput').setInputFiles(folder); await collected(page, 4);
  assert.equal(await page.locator('.upload-file[data-status="pending"]').count(), 2);
  assert.ok((await page.locator('#uploadQueueList').innerText()).includes('orders/nested/a.pdf'));
  await page.locator('#drawingFolderInput').setInputFiles(folder); await collected(page, 4); await clear(page);
  await page.evaluate(() => {
    const transfer = new DataTransfer(); transfer.items.add(new File(['pdf'], 'drag-one.pdf')); transfer.items.add(new File(['pdf'], 'drag-two.pdf'));
    window.dispatchEvent(new DragEvent('drop', { dataTransfer: transfer, cancelable: true }));
  });
  await collected(page, 2); assert.equal(model.uploads.length, 0); await clear(page);
  assert.equal(await page.evaluate(() => {
    const transfer = new DataTransfer(); transfer.setData('text/plain', 'keep text drag');
    const event = new DragEvent('drop', { dataTransfer: transfer, cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented;
  }), false, 'Do not intercept text dragging');
  await page.evaluate(() => {
    const f = (name) => ({ name, isFile: true, file: (resolve) => resolve(new File(['pdf'], name)) });
    const dir = (name, pages) => ({ name, isDirectory: true, createReader: () => { let n = 0; return { readEntries: (resolve) => resolve(pages[n++] || []) }; } });
    const roots = [dir('folder', [[f('a.pdf')], [dir('nested', [[f('b.pdf')]])]]), dir('other', [[f('a.pdf')]]), f('loose.pdf'), dir('empty', [])];
    const transfer = new DataTransfer();
    Object.defineProperty(transfer, 'types', { value: ['Files'] });
    Object.defineProperty(transfer, 'items', { value: roots.map((entry) => ({ kind: 'file', webkitGetAsEntry: () => entry })) });
    window.dispatchEvent(new DragEvent('drop', { dataTransfer: transfer, cancelable: true }));
  });
  await collected(page, 5); assert.equal(await page.locator('.upload-file[data-status="pending"]').count(), 4);
  assert.ok((await page.locator('#uploadQueueList').innerText()).includes('folder/nested/b.pdf')); await clear(page);
  await page.evaluate(() => {
    drawingUploads.collectDrop([{ entry: { name: 'slow.pdf', isFile: true, file: (resolve) => {
      window.resolveOldScan = () => resolve(new File(['pdf'], 'slow.pdf'));
    } } }]);
  });
  await page.waitForFunction(() => !document.getElementById('uploadScanStatus').hidden);
  assert.equal(await page.locator('#submitButton').isDisabled(), true);
  await clear(page); await page.locator('#drawingInput').setInputFiles([input('new.pdf')]);
  await page.evaluate(() => resolveOldScan()); await collected(page, 1);
  assert.equal(await page.locator('.upload-file-name').textContent(), 'new.pdf'); await clear(page);

  // Fifty jobs: stop after the first request, edit a different review, resume frozen options.
  await page.evaluate(() => {
    window.reviewBeforeUploads = state.review = { marker: 'before-upload', spring_parameters: {}, technical_requirements: [] };
    state.lastJob = { job_id: 'existing-order' };
  });
  model.uploadGate = deferred();
  await page.locator('#drawingInput').setInputFiles(Array.from({ length: 50 }, (_, i) => input(`batch-${i}.pdf`)));
  await collected(page, 50);
  await page.evaluate(() => {
    window.beforeBatchFlush = flushReviewPersistence;
    flushReviewPersistence = () => new Promise((resolve) => { window.releaseBatchFlush = () => resolve(true); });
  });
  await page.locator('#submitButton').click();
  await page.waitForFunction(() => uploadPreparing && !drawingUploads.running);
  await page.evaluate(() => {
    useQwenInput.checked = false;
    flushReviewPersistence = beforeBatchFlush; releaseBatchFlush();
  });
  await page.waitForFunction(() => drawingUploads.running);
  assert.equal(model.uploads.length, 1);
  await page.evaluate(() => { state.review.marker = 'edited-during-upload'; state.reviewEditSerial++; });
  await page.locator('#pauseUploadButton').click(); model.uploadGate.resolve(); model.uploadGate = null;
  await page.waitForFunction(() => !drawingUploads.running && drawingUploads.entries.filter((item) => item.jobId).length === 1);
  assert.equal(model.uploads.length, 1); assert.equal(await page.locator('#submitButton').textContent(), '继续上传');
  await page.evaluate(() => { useQwenInput.checked = false; });
  await page.locator('#submitButton').click();
  await page.waitForFunction(() => !drawingUploads.running && drawingUploads.entries.filter((item) => item.jobId).length === 50);
  assert.equal(model.peak, 1); assert.equal(model.uploads.length, 50);
  assert.ok(model.uploads.every((upload) => /name="use_qwen"\r\n\r\ntrue/.test(upload.text)), 'Click freezes settings even during persistence, and resume retains them');
  assert.ok(model.uploads.every((upload) => !upload.text.includes('webkitRelativePath') && !upload.text.includes(temporary)));
  assert.equal(await page.evaluate(() => state.review === reviewBeforeUploads && state.review.marker === 'edited-during-upload' && state.lastJob.job_id === 'existing-order'), true);
  assert.equal(model.writes.some(([method]) => method === 'PATCH'), false, 'Background upload never rewrites the review');
  const ids = [...model.jobs.keys()], first = ids[0], failed = ids[1], completed = ids[2];
  model.update(first, { status: 'processing', progress: 62, attempt_count: 1 });
  model.update(failed, { status: 'failed', error_message: '模拟OCR失败' });
  model.update(completed, { status: 'completed', progress: 100 });
  await page.waitForFunction((id) => drawingUploads.entries.find((entry) => entry.jobId === id)?.progress === 62, first);
  assert.equal(await page.locator('#uploadProgressSection').evaluate((element) => element.open), false, 'Recognition progress defaults collapsed');
  assert.equal(await page.locator('#submitButton').isVisible(), false, 'No empty start button after upload');
  assert.equal(await page.locator('#uploadUnsentHint').isVisible(), false);
  assert.equal(await rowFor(page, 'batch-0.pdf').locator('.upload-file-state').textContent(), '识别中 62%');
  assert.equal(await page.locator(`[data-history-job-id="${first}"] [data-role="recognition-percentage"]`).textContent(), '62%');
  await page.waitForFunction((id) => state.recentReviews.find((item) => item.job_id === id)?.recognition_status === 'failed', failed);
  assert.equal(await rowFor(page, 'batch-1.pdf').count(), 0, 'Recognition failures move to history');
  await page.locator(`[data-history-job-id="${failed}"]`).getByRole('button', { name: '重试', exact: true }).click();
  await page.waitForFunction((id) => drawingUploads.entries.find((entry) => entry.jobId === id)?.status === 'queued', failed);
  assert.deepEqual(model.retries, [failed]); assert.equal(model.uploads.length, 50);
  assert.equal(await page.evaluate(() => state.lastJob.job_id), 'existing-order', 'Recognition retry must not select a batch order');
  model.truncate = true; await page.locator('#refreshRecentReviewsButton').click();
  await page.waitForFunction(() => !state.recentReviewsLoading);
  assert.equal(await page.evaluate(() => [...drawingUploads.trackedJobs.keys()].every((id) => state.recentReviews.some((review) => review.job_id === id))), true, 'Active jobs survive a truncated list independently of UI cleanup');
  model.update(first, { status: 'processing', progress: 77 });
  await page.waitForFunction((id) => drawingUploads.entries.find((entry) => entry.jobId === id)?.progress === 77, first);
  assert.ok(model.listQueries.every((limit) => limit === '100'));
  model.offline.add(first);
  await page.waitForFunction((id) => Boolean(drawingUploads.entries.find((entry) => entry.jobId === id)?.syncError), first);
  model.offline.delete(first); await expand(page, 'uploadProgressSection');
  await rowFor(page, 'batch-0.pdf').getByRole('button', { name: '刷新进度', exact: true }).click();
  await page.waitForFunction((id) => !drawingUploads.entries.find((entry) => entry.jobId === id)?.syncError, first);
  // The worker increments a retried job's attempt counter when claiming it.
  for (const id of ids) model.update(id, { status: 'completed', progress: 100,
    attempt_count: model.jobs.get(id).attempt_count + (id === failed ? 1 : 0) });
  await page.waitForFunction(() => drawingUploads.entries.length === 0 && drawingUploads.completion?.completed === 50);
  assert.equal(await page.locator('.upload-file').count(), 0, 'Completed details do not accumulate');
  assert.equal(await page.locator('#uploadCompletionText').textContent(), '本批50份 · 全部完成');
  assert.equal(await page.locator('#uploadViewHistory').count(), 0, 'Completion has no history jump button');
  const unreadBeforeClear = await page.locator('.history-unread-dot:not([hidden])').count();
  const visibleCompletions = await page.evaluate(() => state.recentReviews.filter((item) => item.recognition_status === 'completed').length);
  assert.equal(unreadBeforeClear, visibleCompletions, 'Each locatable unopened completion has a dot; a prior completed row outside the truncated list is not counted');
  await page.locator('#clearUploadCompletion').click();
  await page.waitForFunction(() => document.getElementById('uploadQueue').hidden);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'chooseFileButton', 'Clearing the completion notice restores keyboard focus');
  assert.equal(await page.locator('.history-unread-dot:not([hidden])').count(), unreadBeforeClear, 'Completion cleanup does not acknowledge recognition results');
  assert.equal(model.getReviews.length, 0, 'Batch completion never auto opens');
  assert.equal(await page.evaluate(() => Object.keys(state.recognitionPollers).length), 0);

  model.failures.set('too-large.pdf', 413);
  await page.locator('#drawingInput').setInputFiles([input('too-large.pdf')]); await page.locator('#submitButton').click();
  await page.waitForFunction(() => drawingUploads.entries.some((item) => item.status === 'upload_failed'));
  assert.equal(await page.locator('#uploadProblemsSection').evaluate((element) => element.open), false, 'Problems do not force themselves open');
  await expand(page, 'uploadProblemsSection');
  model.failures.delete('too-large.pdf'); await rowFor(page, 'too-large.pdf').getByRole('button', { name: '重试上传', exact: true }).click();
  await page.waitForFunction(() => drawingUploads.entries.find((item) => item.name === 'too-large.pdf').jobId);
  model.failures.set('auth.pdf', 401);
  await page.locator('#drawingInput').setInputFiles([input('auth.pdf'), input('after-auth.pdf')]); await page.locator('#submitButton').click();
  await page.waitForFunction(() => !drawingUploads.running && drawingUploads.entries.some((item) => item.name === 'auth.pdf' && item.status === 'upload_failed'));
  assert.equal(model.uploads.some((item) => item.name === 'after-auth.pdf'), false); await clear(page);
  model.failures.set('unknown.pdf', 'network');
  await page.locator('#drawingInput').setInputFiles([input('unknown.pdf')]); await page.locator('#submitButton').click();
  await page.waitForFunction(() => drawingUploads.entries.some((item) => item.status === 'unknown'));
  await expand(page, 'uploadProblemsSection');
  const countBefore = model.uploads.length;
  assert.equal(await rowFor(page, 'unknown.pdf').getByRole('button', { name: '核对后重试上传', exact: true }).count(), 0);
  await rowFor(page, 'unknown.pdf').getByRole('button', { name: '核对历史订单', exact: true }).click();
  await rowFor(page, 'unknown.pdf').getByRole('button', { name: '核对后重试上传', exact: true }).waitFor();
  assert.equal(model.uploads.length, countBefore, 'Checking uncertain outcomes does not reupload'); await clear(page);
  await page.locator('#drawingInput').setInputFiles(Array.from({ length: 51 }, (_, i) => input(`limit-${i}.pdf`)));
  await page.waitForFunction(() => drawingUploads.tooMany && !drawingUploads.scanning);
  assert.equal(await page.locator('#submitButton').isDisabled(), true); await page.evaluate(() => submitSelectedFile());
  assert.equal(model.uploads.length, countBefore); await clear(page);
  assert.deepEqual(model.errors, []); await page.close();

  // Single-file auto open, and protection both before and during a late review response.
  for (const guard of ['none', 'edited-before-completion', 'edited-during-fetch', 'new-review']) {
    const single = await scenario(), { page } = single;
    await page.locator('#drawingInput').setInputFiles([input('single.pdf')]); await page.locator('#submitButton').click();
    await page.waitForFunction(() => drawingUploads.entries[0]?.jobId);
    const id = [...single.jobs.keys()][0];
    if (guard === 'edited-before-completion') await page.evaluate(() => { state.review = { marker: 'keep' }; state.reviewEditSerial++; });
    if (guard === 'new-review') await page.locator('#newReviewButton').click();
    if (guard === 'edited-during-fetch') single.reviewGate = deferred();
    single.update(id, { status: 'completed', progress: 100 });
    await page.waitForFunction(() => drawingUploads.entries.length === 0 && drawingUploads.completion?.completed === 1);
    if (guard === 'none') await page.waitForFunction((id) => state.lastJob?.job_id === id && !state.busy, id);
    else if (guard === 'edited-during-fetch') {
      await page.waitForFunction(() => state.busy);
      await page.evaluate(() => { state.review = { marker: 'keep' }; state.reviewEditSerial++; });
      single.reviewGate.resolve(); await page.waitForFunction(() => !state.busy);
      assert.equal(await page.evaluate(() => state.review.marker), 'keep');
    } else {
      await page.waitForFunction(() => Object.keys(state.recognitionPollers).length === 0);
      assert.equal(single.getReviews.length, 0);
    }
    assert.equal(await page.locator(`[data-history-job-id="${id}"] .history-unread-dot`).isVisible(), guard !== 'none', 'Only a successful automatic view acknowledges the result');
    assert.deepEqual(single.errors, [], guard); await page.close();
  }

  // Multiple live batches, manual disclosure state and cleanup never share counters.
  const rollover = await scenario();
  {
    const { page } = rollover;
    await page.locator('#drawingInput').setInputFiles([input('older-a.pdf'), input('older-b.pdf')]);
    await page.evaluate(() => { window.oldBatchFiles = drawingUploads.entries.map((item) => item.file); });
    await page.locator('#submitButton').click();
    await page.waitForFunction(() => drawingUploads.trackedJobs.size === 2 && !drawingUploads.running);
    const oldIds = [...rollover.jobs.keys()];
    await expand(page, 'uploadProgressSection');
    await page.locator('#drawingInput').setInputFiles([input('current-a.pdf'), input('current-b.pdf')]);
    await page.waitForFunction(() => drawingUploads.pending.length === 2 && !drawingUploads.scanning);
    assert.equal(await page.locator('#uploadProgressSection').evaluate((element) => element.open), true, 'Adding files only expands the pending area');
    await page.locator('#uploadPendingSection summary').click();
    rollover.update(oldIds[0], { status: 'processing', progress: 42 });
    await page.waitForFunction((id) => drawingUploads.trackedJobs.get(id)?.progress === 42, oldIds[0]);
    assert.equal(await page.locator('#uploadPendingSection').evaluate((element) => element.open), false, 'Progress cannot reset manual collapse');
    assert.equal(await page.locator('#uploadProgressSection').evaluate((element) => element.open), true, 'Progress cannot reset manual expansion');
    await expand(page, 'uploadPendingSection'); await page.locator('#submitButton').click();
    await page.waitForFunction(() => drawingUploads.trackedJobs.size === 4 && !drawingUploads.running);
    const currentIds = [...rollover.jobs.keys()].slice(2);
    rollover.update(oldIds[0], { status: 'completed', progress: 100 }); rollover.update(oldIds[1], { status: 'failed', error_message: '旧批次失败' });
    await page.waitForFunction(() => drawingUploads.entries.length === 2);
    assert.equal(await page.locator('#uploadCompletion').isVisible(), false, 'Previous batches cannot complete the current batch');
    assert.equal(await rowFor(page, 'older-a.pdf').count(), 0);
    assert.equal(await rowFor(page, 'older-b.pdf').count(), 0);
    assert.equal(await page.locator(`[data-history-job-id="${oldIds[1]}"]`).getByRole('button', { name: '重试', exact: true }).count(), 1);
    rollover.update(currentIds[0], { status: 'completed', progress: 100 }); rollover.update(currentIds[1], { status: 'failed', error_message: '本批次失败' });
    await page.waitForFunction(() => drawingUploads.entries.length === 0 && drawingUploads.completion?.total === 2);
    assert.equal(await page.locator('#uploadCompletionText').textContent(), '本批2份 · 完成1份 · 失败1份');
    await page.evaluate(() => drawingUploads.collectFiles(oldBatchFiles));
    assert.equal(await page.evaluate(() => drawingUploads.pending.length), 0, 'Cleanup preserves page dedup fingerprints');
    await page.locator('#clearUploadCompletion').click();
    await page.waitForFunction(() => document.getElementById('uploadQueue').hidden);
    await page.locator('#drawingInput').setInputFiles([input('future-a.pdf')]);
    assert.equal(await page.locator('#uploadCompletion').isVisible(), false);
    assert.equal(await page.locator('#uploadPendingSection').evaluate((element) => element.open), true);
    assert.deepEqual(rollover.errors, []); await page.close();
  }

  // One batched visual inspection across the supported viewport classes; no paid API calls.
  for (const [name, width] of [['desktop', 1440], ['narrow', 900], ['mobile', 430]]) {
    const layout = await scenario(width), { page } = layout;
    await page.locator('#drawingFolderInput').setInputFiles(folder); await collected(page, 4);
    await page.locator('#submitButton').focus();
    assert.equal(await page.locator('#drawingFolderInput').getAttribute('webkitdirectory'), '');
    assert.equal(await page.locator('#drawingInput').getAttribute('multiple'), '');
    assert.equal(await page.locator('#dropZone').evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return rect.left >= 0 && rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1
        && [...element.querySelectorAll('button:not([hidden])')].every((button) => {
          const b = button.getBoundingClientRect(); return !b.width || (b.left >= rect.left && b.right <= rect.right + 1);
        });
    }), true, `${name}: upload controls fit`);
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(output, `${name}-pending.png`) });
    await clear(page);
    await page.locator('#drawingInput').setInputFiles(Array.from({ length: 4 }, (_, index) => input(`completed-${index}.pdf`)));
    await page.locator('#submitButton').click();
    await page.waitForFunction(() => drawingUploads.trackedJobs.size === 4 && !drawingUploads.running);
    for (const id of layout.jobs.keys()) layout.update(id, { status: 'completed', progress: 100 });
    await page.waitForFunction(() => drawingUploads.completion?.completed === 4 && drawingUploads.entries.length === 0);
    assert.equal(await page.locator('#dropZone').evaluate((element) => element.getBoundingClientRect().height < 260), true, `${name}: completion is compact`);
    assert.equal(await page.locator('#submitButton').isVisible(), false);
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await page.screenshot({ path: path.join(output, `${name}.png`) });
    assert.deepEqual(layout.errors, []); await page.close();
  }
  console.log('PASS: four upload entries, directory pagination, 50-file queue, pause/retry/auth/network, shared history, editing/late-response protection and responsive layouts.');
} finally {
  await browser.close(); await new Promise((resolve) => server.close(resolve));
  const resolvedTemporary = path.resolve(temporary);
  assert.ok(resolvedTemporary.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolvedTemporary).startsWith('drawing-upload-'));
  fs.rmSync(resolvedTemporary, { recursive: true, force: true });
}
