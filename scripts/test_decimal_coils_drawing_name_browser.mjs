import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixture = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_solidworks_export.py', '--json'], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, maxBuffer: 4 * 1024 * 1024 }))[0].review;
function review(id) {
  const r = structuredClone(fixture); r.drawing_summary.drawing_no = `OLD-${id}`; r.drawing_summary.drawing_name = `测试图纸${id}`;
  r.spring_parameters = { ...r.spring_parameters, ...Object.fromEntries(Object.entries({ wire_diameter: 2, outer_diameter: 20, inner_diameter: 16, mean_diameter: 18, free_length: 50, total_coils: 10, active_coils: 8 }).map(([f, value]) => [f, { value, source: ['qwen_vision', 'human_confirmed'], need_human_review: false }])) };
  r.manual_confirmations = {}; r.standardization_results = []; return r;
}
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const frontend = path.resolve('frontend'), output = path.resolve('outputs/decimal-coils-drawing-name-qa'); fs.mkdirSync(output, { recursive: true });
const server = http.createServer((req, res) => {
  const file = path.resolve(frontend, new URL(req.url, 'http://localhost').pathname.slice(1) || 'index.html');
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); res.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const models = new Map(['a', 'b'].map((id) => [id, { review: review(id), revision: 1 }]));
let failSave = false, conflict = null, holdSave = false, releaseSave = null, holdList = false, releaseList = null, patchCount = 0;
const errors = []; page.on('pageerror', (e) => errors.push(e.stack));
await page.route('**/api/**', async (route) => {
  const request = route.request(), api = new URL(request.url()).pathname;
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'decimal-test', username: 'decimal-test' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') {
    const rows = [...models].map(([id, m]) => ({ job_id: id, drawing_name: m.review.drawing_summary.drawing_name, drawing_no: m.review.drawing_summary.drawing_no, revision: m.revision, recognition_status: 'completed' }));
    if (holdList) { holdList = false; await new Promise((resolve) => { releaseList = resolve; }); }
    return route.fulfill({ json: { reviews: rows } });
  }
  const match = api.match(/^\/api\/reviews\/([^/]+)(?:\/(.+))?$/);
  if (match) {
    const [, id, action] = match, model = models.get(id);
    if (!model) return route.fulfill({ status: 404, json: { detail: `Unknown mock order: ${id}` } });
    if (!action) {
      if (request.method() === 'PATCH') {
        patchCount++;
        if (holdSave) { holdSave = false; await new Promise((resolve) => { releaseSave = resolve; }); }
        if (failSave) return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
        if (conflict) { conflict(model); conflict = null; model.revision++; return route.fulfill({ status: 409, json: { detail: '模拟冲突' } }); }
        const input = request.postDataJSON();
        if (input.expected_revision !== model.revision) return route.fulfill({ status: 409, json: { detail: '修订冲突' } });
        model.review = input.review; model.revision++;
        return route.fulfill({ json: { review_revision: model.revision, events: input.events } });
      }
      return route.fulfill({ json: { ...model.review, job_id: id, review_revision: model.revision } });
    }
    if (action === 'generation-jobs') return route.fulfill({ json: { generation_jobs: [] } });
    if (action === 'annotations') return route.fulfill({ json: { pages: [], annotations: [] } });
    if (action === 'changes') return route.fulfill({ json: { events: [] } });
    if (action === 'reasonableness') return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
  }
  return route.fulfill({ json: { status: 'ok', recognition_queue_runtime: { status: 'available' } } });
});
const root = page.locator('.compare-overlay');
const input = (field) => root.locator(`[data-kind="param"][data-field="${field}"] [data-role="value"]:visible`);
const name = () => root.locator('[data-role="drawing-name"]:visible');
async function open(id) { await page.evaluate(async (id) => { await openPersistedReview(id); renderCompareOverlay(); }, id); await root.waitFor(); await root.locator('[data-compare-tab="parameters"]').click(); }
async function saved() { assert.equal(await page.evaluate(() => flushReviewPersistence()), true); await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length); }
async function editName(value) { await name().fill(value); await name().press('Tab'); await saved(); }
const title = () => page.evaluate(() => state.recentReviews.find((r) => r.job_id === 'a').drawing_name);
try {
  await page.goto(process.env.DECIMAL_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.recentReviews.length === 2); await open('a');
  for (const [field, value] of [['total_coils', '10.5'], ['active_coils', '8.25']]) {
    await input(field).fill(value); await input(field).press('Tab'); await saved();
    const confirm = root.locator(`[data-kind="param"][data-field="${field}"] [data-role="confirm"]:visible`);
    assert.equal(await confirm.isEnabled(), true); await confirm.click(); await saved();
    assert.equal(models.get('a').review.spring_parameters[field].need_human_review, false);
  }
  let exported = await page.evaluate(() => makeGenerationParameterPackage());
  assert.equal(exported.solidworks_preview.modelParameters['圈数'], 10.5);
  assert.equal(exported.solidworks_preview.modelParameters['有效圈数n'], 8.25);
  // Bulk confirmation and JSON round-trip preserve every supplied digit too.
  for (const [field, value] of [['total_coils', '10.5123456789'], ['active_coils', '8.25123456789']]) {
    await input(field).fill(value); await input(field).press('Tab'); await saved();
  }
  await root.locator('[data-action="confirm-all-review-items"]').click(); await saved();
  exported = await page.evaluate(() => makeGenerationParameterPackage());
  assert.equal(exported.solidworks_preview.modelParameters['圈数'], 10.5123456789);
  assert.equal(exported.solidworks_preview.modelParameters['有效圈数n'], 8.25123456789);
  for (const invalid of ['', '0', '-1', 'abc', 'Infinity']) {
    assert.equal(await page.evaluate((v) => Boolean(parameterConfirmationInvalidReason('total_coils', { value: v })), invalid), true);
  }
  assert.equal(await page.evaluate(() => { const r = structuredClone(state.review); r.spring_parameters.active_coils.value = 11; r.spring_parameters.active_coils.need_human_review = false; return assessGenerationReadiness(r).status; }), 'blocked');
  const beforeParameters = await page.evaluate(() => JSON.stringify(state.review.spring_parameters));
  await name().fill('  客户 图纸-001  '); await page.evaluate(() => syncParameterReasonablenessSurfaces());
  assert.equal(await name().evaluate((el) => el === document.activeElement), true);
  assert.equal(await name().inputValue(), '  客户 图纸-001  '); await name().press('Tab'); await saved();
  assert.equal(await title(), '客户 图纸-001');
  assert.equal(await page.evaluate(() => JSON.stringify(state.review.spring_parameters)), beforeParameters);
  assert.equal(await page.evaluate(() => makeGenerationParameterPackage().source.drawing_name), '客户 图纸-001');
  await open('b'); await open('a'); assert.equal(await name().inputValue(), '客户 图纸-001');
  assert.equal(await input('total_coils').inputValue(), '10.5123456789');
  await editName(''); assert.equal(await title(), '');
  assert.equal(await page.evaluate(() => makeGenerationParameterPackage().source.drawing_name), null);
  assert.equal(await page.locator('[data-history-job-id="a"] strong').innerText(), 'OLD-a');
  await editName('图'.repeat(512));
  const beforeInvalid = patchCount;
  await name().fill('图'.repeat(513)); await name().press('Tab');
  assert.match(await root.locator('[data-role="drawing-name-save-status"]:visible').innerText(), /最长512/);
  assert.equal(await page.evaluate(() => flushReviewPersistence()), false); assert.equal(patchCount, beforeInvalid);
  await editName('😀'.repeat(512)); assert.equal(Array.from(models.get('a').review.drawing_summary.drawing_name).length, 512);
  failSave = true; await name().fill('保存失败保留'); await name().press('Tab');
  await page.waitForFunction(() => state.reviewPersistenceFailedFields['drawing_summary.drawing_name']);
  assert.equal(await name().inputValue(), '保存失败保留'); failSave = false;
  await root.locator('[data-role="retry-drawing-name-save"]:visible').click(); await saved();
  conflict = (m) => { m.review.drawing_summary.drawing_name = '另一位用户修改'; };
  await name().fill('本地名称'); await name().press('Tab');
  await page.getByRole('dialog').waitFor(); assert.match(await page.getByRole('dialog').innerText(), /图纸名称/);
  await page.getByRole('button', { name: '保留我的值并保存' }).click(); await saved(); assert.equal(await title(), '本地名称');
  conflict = (m) => { m.review.drawing_summary.drawing_name = '采用服务器名称'; };
  await name().fill('放弃的名称'); await name().press('Tab');
  await page.getByRole('dialog').waitFor(); await page.getByRole('button', { name: '采用服务器值' }).click(); await saved();
  assert.equal(await name().inputValue(), '采用服务器名称'); assert.equal(await title(), '采用服务器名称');
  // List launched before commit, and old progress, cannot restore the old name.
  holdList = true; await page.evaluate(() => { void loadRecentReviews(); });
  while (!releaseList) await new Promise((resolve) => setTimeout(resolve, 10));
  await editName('列表晚到保护'); releaseList(); await page.waitForFunction(() => !state.recentReviewsLoading);
  assert.equal(await title(), '列表晚到保护');
  await page.evaluate(() => mergeRecognitionStatus('a', { status: 'completed', drawing_name: '旧上传文件名' }));
  assert.equal(await title(), '列表晚到保护');
  await page.evaluate(() => loadRecentReviews());
  await page.evaluate(() => mergeRecognitionStatus('a', { status: 'completed', drawing_name: '旧上传文件名' }));
  assert.equal(await title(), '列表晚到保护');
  await editName('压缩弹簧 客户版 001-A'); await name().scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(output, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 }); await name().scrollIntoViewIfNeeded();
  assert.equal(await name().isVisible(), true); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'mobile.png') });
  holdSave = true; await name().fill('订单A晚到保存'); await name().press('Tab');
  while (!releaseSave) await new Promise((resolve) => setTimeout(resolve, 10));
  await page.evaluate((r) => { state.lastJob = { job_id: 'b', review_revision: 99 }; state.review = normalizeReview(r); }, models.get('b').review);
  releaseSave(); await page.waitForFunction(() => !state.reviewPersistenceSaving);
  assert.equal(await page.evaluate(() => state.lastJob.review_revision), 99);
  assert.equal(await page.evaluate(() => state.review.drawing_summary.drawing_name), '测试图纸b');
  assert.deepEqual(errors, []);
  console.log('Decimal coils/name browser: individual/bulk confirmation, full precision, invalid input, save/reopen/retry, conflict, stale list/progress, focus and responsive layout passed');
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
