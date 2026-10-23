import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };
const cases = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_solidworks_export.py', '--json'], { encoding: 'utf8', env, maxBuffer: 4 * 1024 * 1024 }));
const fixtures = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_accuracy_inference.py', '--json'], { encoding: 'utf8', env }));
function review() {
  const r = structuredClone(cases[0].review), f = fixtures[0].expected;
  r.spring_parameters = { ...r.spring_parameters, ...f.spring_parameters, load_points: [] };
  for (const k of ['diameter_accuracy_grade', 'free_length_accuracy_grade', 'load_accuracy_grade', 'stiffness_accuracy_grade']) r.spring_parameters[k] = { value: null };
  r.accuracy_inference = structuredClone(f.accuracy_inference); r.standard_selection = { ...r.standard_selection, ...f.standard_selection };
  r.spring_parameters.total_coils.value = 10;
  r.standardization_results = []; r.manual_confirmations = {}; return r;
}
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const frontend = path.resolve('frontend'), output = path.resolve('outputs/accuracy-inference-qa'); fs.mkdirSync(output, { recursive: true });
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, 'http://localhost').pathname.slice(1) || 'index.html');
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, channel: 'msedge' }), page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const models = new Map(['a', 'b'].map((id) => [id, { review: review(), revision: 1 }])), errors = [];
let failSave = false, conflictSave = false, standards = 0, holdStandard = false, releaseStandard = null;
page.on('pageerror', (error) => { errors.push(error.stack); console.error('Browser error:', error.message); });
await page.route('**/api/**', async (route) => {
  const request = route.request(), api = new URL(request.url()).pathname, method = request.method();
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'accuracy-browser', username: 'accuracy-browser' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') return route.fulfill({ json: { reviews: [...models].map(([id, m]) => ({ job_id: id, drawing_name: `测试图纸${id}`, revision: m.revision, recognition_status: 'completed' })) } });
  const match = api.match(/^\/api\/reviews\/(a|b)(?:\/(.*))?$/);
  if (match) {
    const [, id, action] = match, model = models.get(id);
    if (!action) {
      if (method === 'PATCH') {
        if (failSave) return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
        if (conflictSave) { conflictSave = false; model.revision++; model.review.drawing_summary.drawing_name = '服务器修改标题'; return route.fulfill({ status: 409, json: { detail: '模拟修订冲突' } }); }
        const input = request.postDataJSON();
        if (input.expected_revision !== model.revision) return route.fulfill({ status: 409, json: { detail: '模拟修订冲突' } });
        model.review = input.review; model.revision++;
        return route.fulfill({ json: { review_revision: model.revision, events: input.events } });
      }
      return route.fulfill({ json: { ...model.review, job_id: id, review_revision: model.revision } });
    }
    if (action === 'standardize') {
      standards++; const input = request.postDataJSON();
      if (holdStandard) { holdStandard = false; await new Promise((resolve) => { releaseStandard = resolve; }); }
      const python = "import sys,json;sys.path.insert(0,'src');from ai_design_review import standard_selector;standard_selector.standard_references=lambda *a,**k:[];from ai_design_review.workflow import apply_standardization_to_review;r=json.load(sys.stdin);apply_standardization_to_review(r);print(json.dumps(r,ensure_ascii=False))";
      model.review = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['-c', python], { input: JSON.stringify(input.review), encoding: 'utf8', env })); model.revision++;
      return route.fulfill({ json: { review: model.review, review_revision: model.revision, warnings: [] } });
    }
    if (action === 'generation-jobs') return route.fulfill({ json: { generation_jobs: [] } });
    if (action === 'annotations') return route.fulfill({ json: { pages: [], annotations: [] } });
    if (action === 'changes') return route.fulfill({ json: { events: [] } });
  }
  if (api.endsWith('/reasonableness')) return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
  return route.fulfill({ json: { status: 'ok', recognition_queue_runtime: { status: 'available' } } });
});
const root = page.locator('.compare-overlay'), grade = () => root.locator('[data-accuracy-grade-selector]:visible').first();
async function tab(name) { await root.locator(`[data-compare-tab="${name}"]`).click(); }
async function open(id) { await page.evaluate(async (id) => { await openPersistedReview(id); renderCompareOverlay(); }, id); await root.waitFor(); }
async function saved() { await page.evaluate(() => flushReviewPersistence()); await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length); }
const tolerance = () => root.locator('[data-kind="param"][data-field="free_length"] [data-role="tolerance"]:visible');
try {
  await page.goto(process.env.ACCURACY_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.recentReviews.length === 2);
  await open('a'); await tab('parameters');
  assert.equal(await page.evaluate(() => state.review.spring_parameters.accuracy_grade.value), '1级');
  await tolerance().fill('±0.6');
  assert.equal(await tolerance().evaluate((input) => document.activeElement === input), true, 'Inference keeps the input focused');
  await tolerance().press('Tab'); await saved();
  assert.equal(models.get('a').review.spring_parameters.accuracy_grade.value, '2级');
  await tab('workbench'); await grade().selectOption('3级');
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight && state.review.accuracy_inference.selection_mode === 'manual');
  assert.equal(await grade().inputValue(), '3级'); assert.equal(standards, 1);
  await tab('standards');
  const index = await page.evaluate(() => state.review.standardization_results.findIndex((r) => r.target_field === 'free_length'));
  await page.evaluate((index) => {
    const item = state.review.standardization_results[index];
    const before = parameterAuditState(state.review.spring_parameters.free_length);
    applyStandardizationResults([item]);
    queueReviewAuditEvent({ event_type: "parameter_tolerance_updated", target_field: "free_length", before_state: before, after_state: parameterAuditState(state.review.spring_parameters.free_length) });
  }, index); await saved();
  assert.equal(models.get('a').review.spring_parameters.free_length.tolerance_upper, 1.2);
  assert.equal(models.get('a').review.accuracy_inference.input_snapshot.free_length.upper, .6);
  await open('b'); await open('a'); await tab('workbench'); assert.equal(await grade().inputValue(), '3级');
  await tab('parameters'); failSave = true;
  await tolerance().fill('±0.1'); await tolerance().press('Tab');
  await page.waitForFunction(() => Object.keys(state.reviewPersistenceFailedFields).length > 0);
  assert.equal(await page.evaluate(() => state.review.accuracy_inference.inferred_grade), '1级');
  assert.equal(await page.evaluate(() => state.review.spring_parameters.accuracy_grade.value), '3级');
  failSave = false; await saved();
  await open('b'); await tab('parameters'); conflictSave = true;
  await tolerance().fill('±0.6'); await tolerance().press('Tab'); await saved();
  assert.equal(models.get('b').review.spring_parameters.accuracy_grade.value, '2级');
  assert.equal(models.get('b').review.accuracy_inference.input_snapshot.free_length.upper, .6);
  assert.equal(models.get('b').review.drawing_summary.drawing_name, '服务器修改标题');
  await tab('workbench'); assert.equal(await grade().inputValue(), '2级');
  assert.equal(await root.getByText(/人工采用.*反推参考/).count(), 0);
  await page.screenshot({ path: path.join(output, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 }); await grade().scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(output, 'mobile.png') });
  assert.equal(await grade().isVisible(), true);
  // A response for the previous order must not replace another order, even
  // when no new parameter edit increments the edit serial.
  holdStandard = true;
  await page.evaluate(() => { window.accuracyLateRequest = runStandardization(state.activeReviewMessageId, { silent: true }); });
  for (let i = 0; !releaseStandard && i < 200; i++) await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(typeof releaseStandard, 'function');
  await page.evaluate((r) => { state.lastJob = { job_id: 'a', review_revision: r.revision }; state.reviewNavigationSerial++;
    setReview(normalizeReview(r.review), null); }, models.get('a'));
  releaseStandard();
  assert.equal(await page.evaluate(() => window.accuracyLateRequest), false);
  assert.equal(await page.evaluate(() => state.lastJob.job_id), 'a');
  assert.equal(await page.evaluate(() => state.review.accuracy_inference.selection_mode), 'manual');
  assert.equal(await page.evaluate(() => state.review.spring_parameters.accuracy_grade.value), '3级');
  assert.deepEqual(errors, []);
  console.log('Accuracy inference browser: native inputs, manual selection, applying real rule output, no loop, reopen, failure/retry, conflict merge, focus and mobile passed');
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
