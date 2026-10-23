import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };
const fixture = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_solidworks_export.py', '--json'], { encoding: 'utf8', env, maxBuffer: 4 * 1024 * 1024 }))[0].review;
function review(id) {
  const r = structuredClone(fixture); r.drawing_summary.drawing_no = `OLD-${id}`; r.drawing_summary.drawing_name = `测试图纸${id}`;
  r.spring_parameters = { ...r.spring_parameters, ...Object.fromEntries(Object.entries({ wire_diameter: 2, outer_diameter: 20, inner_diameter: 16, mean_diameter: 18 }).map(([f, value]) => [f, { value, unit: 'mm', source: ['qwen_vision', 'human_confirmed'], need_human_review: false, tolerance_upper: .1, tolerance_lower: -.1, evidence: '原图识别' }])) };
  r.manual_confirmations = {}; r.standardization_results = []; return r;
}
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const frontend = path.resolve('frontend'), output = path.resolve('outputs/diameter-drawing-no-qa'); fs.mkdirSync(output, { recursive: true });
const server = http.createServer((req, res) => {
  const file = path.resolve(frontend, new URL(req.url, 'http://localhost').pathname.slice(1) || 'index.html');
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); res.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const models = new Map(['a', 'b'].map((id) => [id, { review: review(id), revision: 1 }]));
let failSave = false, conflict = null, holdSave = false, releaseSave = null, reasonableness = 0;
const errors = []; page.on('pageerror', (e) => errors.push(e.stack));
await page.route('**/api/**', async (route) => {
  const request = route.request(), api = new URL(request.url()).pathname;
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'diameter-test', username: 'diameter-test' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') return route.fulfill({ json: { reviews: [...models].map(([id, m]) => ({ job_id: id, drawing_name: m.review.drawing_summary.drawing_name, drawing_no: m.review.drawing_summary.drawing_no, revision: m.revision, recognition_status: 'completed' })) } });
  const match = api.match(/^\/api\/reviews\/(a|b)(?:\/(.*))?$/);
  if (match) {
    const [, id, action] = match, model = models.get(id);
    if (!action) {
      if (request.method() === 'PATCH') {
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
    if (action === 'reasonableness') { reasonableness++; return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } }); }
  }
  return route.fulfill({ json: { status: 'ok', recognition_queue_runtime: { status: 'available' } } });
});
const root = page.locator('.compare-overlay');
const input = (field) => root.locator(`[data-kind="param"][data-field="${field}"] [data-role="value"]:visible`);
const drawing = () => root.locator('[data-role="drawing-no"]:visible');
async function open(id) { await page.evaluate(async (id) => { await openPersistedReview(id); renderCompareOverlay(); }, id); await root.waitFor(); await root.locator('[data-compare-tab="parameters"]').click(); }
async function saved() { assert.equal(await page.evaluate(() => flushReviewPersistence()), true); await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length); }
async function values(expected) { assert.deepEqual(await page.evaluate(() => ['outer_diameter', 'inner_diameter', 'mean_diameter'].map((f) => state.review.spring_parameters[f].value)), expected); }
try {
  await page.goto(process.env.DIAMETER_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.recentReviews.length === 2);
  await open('a');
  await input('outer_diameter').fill('24'); await values([24, 20, 22]);
  assert.equal(await input('outer_diameter').evaluate((el) => el === document.activeElement), true);
  assert.equal(await input('inner_diameter').inputValue(), '20');
  await input('outer_diameter').press('Tab'); await saved();
  assert.equal(models.get('a').review.diameter_linkage.driver_field, 'outer_diameter');
  assert.equal(models.get('a').review.diameter_linkage.original_parameters.outer_diameter.value, 20);
  assert.equal(models.get('a').review.spring_parameters.inner_diameter.tolerance_upper, .1);
  for (const f of ['outer_diameter', 'inner_diameter', 'mean_diameter']) assert.equal(models.get('a').review.spring_parameters[f].need_human_review, true);
  failSave = true; await input('mean_diameter').fill('24'); await input('mean_diameter').press('Tab');
  await page.waitForFunction(() => state.reviewPersistenceFailedFields.diameter_linkage);
  await values([26, 22, 24]); failSave = false;
  await root.locator('[data-kind="param"][data-field="mean_diameter"] [data-role="confirm"]:visible').click(); await saved();
  assert.equal(models.get('a').review.spring_parameters.mean_diameter.need_human_review, true, 'Retry saves the draft without confirming');
  await input('inner_diameter').fill('18'); await input('inner_diameter').press('Tab'); await saved(); await values([22, 18, 20]);
  await input('wire_diameter').fill('3'); await input('wire_diameter').press('Tab'); await saved(); await values([24, 18, 21]);
  await input('mean_diameter').fill('25'); await input('mean_diameter').press('Tab'); await saved(); await values([28, 22, 25]);
  await input('outer_diameter').fill('3'); await input('outer_diameter').press('Tab'); await saved();
  assert.equal(await page.evaluate(() => state.review.spring_parameters.inner_diameter.derived_value_stale), true);
  assert.equal(await input('inner_diameter').inputValue(), '22');
  await input('outer_diameter').fill('28'); await input('outer_diameter').press('Tab'); await saved(); await values([28, 22, 25]);
  // Diagnostics must neither replace nor unbind the focused number editor.
  const beforeRequests = reasonableness;
  await drawing().fill('  YD-001 23  ');
  await page.evaluate(() => syncParameterReasonablenessSurfaces());
  assert.equal(await drawing().evaluate((el) => el === document.activeElement), true);
  assert.equal(await drawing().inputValue(), '  YD-001 23  ');
  await drawing().press('Tab'); await saved();
  assert.equal(models.get('a').review.drawing_summary.drawing_no, 'YD-001 23');
  assert.equal(await page.evaluate(() => makeGenerationParameterPackage().solidworks_preview.titleBlockProperties['客户图号']), 'YD-001 23');
  await drawing().fill('00123'); await drawing().press('Tab'); await saved();
  await open('b'); await open('a'); assert.equal(await drawing().inputValue(), '00123'); await values([28, 22, 25]);
  await drawing().fill(''); await drawing().press('Tab'); await saved();
  assert.equal(await page.evaluate(() => '客户图号' in makeGenerationParameterPackage().solidworks_preview.titleBlockProperties), false);
  // Failed saves retain the input and expose its existing retry route.
  failSave = true; await drawing().fill('RETRY-001'); await drawing().press('Tab');
  await page.waitForFunction(() => state.reviewPersistenceFailedFields['drawing_summary.drawing_no']);
  assert.equal(await drawing().inputValue(), 'RETRY-001');
  failSave = false; await root.locator('[data-role="retry-drawing-no-save"]:visible').click(); await saved();
  // Unrelated concurrent edits merge without a dialog.
  conflict = (m) => { m.review.drawing_summary.drawing_name = '服务器新标题'; };
  await drawing().fill('MERGED-001'); await drawing().press('Tab'); await saved();
  assert.equal(models.get('a').review.drawing_summary.drawing_name, '服务器新标题');
  // Diameter conflicts present ONE decision for the whole set.
  conflict = (m) => { m.review.spring_parameters.wire_diameter.value = 4; };
  await input('inner_diameter').fill('26'); await input('inner_diameter').press('Tab');
  await page.getByRole('dialog').waitFor();
  assert.match(await page.getByRole('dialog').innerText(), /线径与三径联动/);
  await page.getByRole('button', { name: '保留我的值并保存' }).click(); await saved(); await values([32, 26, 29]);
  assert.equal(models.get('a').review.spring_parameters.wire_diameter.value, 3);
  conflict = (m) => { m.review.spring_parameters.wire_diameter.value = 6; };
  await input('mean_diameter').fill('33'); await input('mean_diameter').press('Tab');
  await page.getByRole('dialog').waitFor(); await page.getByRole('button', { name: '采用服务器值' }).click(); await saved();
  assert.equal(await input('wire_diameter').inputValue(), '6'); await values([38, 26, 32]);
  conflict = (m) => { m.review.drawing_summary.drawing_no = 'SERVER-001'; };
  await drawing().fill('LOCAL-001'); await drawing().press('Tab');
  await page.getByRole('dialog').waitFor(); await page.getByRole('button', { name: '采用服务器值' }).click(); await saved();
  assert.equal(await drawing().inputValue(), 'SERVER-001');
  await drawing().fill('LONG-001-前导零保留'); await drawing().press('Tab'); await saved();
  await drawing().scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(output, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 }); await drawing().scrollIntoViewIfNeeded();
  assert.equal(await drawing().isVisible(), true); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'mobile.png') });
  // A late PATCH receipt must not advance the revision of a different order.
  holdSave = true; await drawing().fill('LATE-A'); await drawing().press('Tab');
  while (!releaseSave) await new Promise((resolve) => setTimeout(resolve, 20));
  await page.evaluate((r) => { state.lastJob = { job_id: 'b', review_revision: 99 }; state.review = normalizeReview(r); }, models.get('b').review);
  releaseSave(); await page.waitForFunction(() => !state.reviewPersistenceSaving);
  assert.equal(await page.evaluate(() => state.lastJob.review_revision), 99);
  assert.equal(await page.evaluate(() => state.review.drawing_summary.drawing_no), 'OLD-b');
  assert.deepEqual(errors, []);
  console.log('Diameter/drawing number browser: live linkage, wire anchor, invalid recovery, focus, save/reopen/retry, atomic conflict, SW preview and responsive layout passed');
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
