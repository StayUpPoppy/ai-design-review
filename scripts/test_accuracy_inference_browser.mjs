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
let holdSave = false, releaseSave = null, failStandard = false;
page.on('pageerror', (error) => { errors.push(error.stack); console.error('Browser error:', error.message); });
await page.route('**/api/**', async (route) => {
  const request = route.request(), api = new URL(request.url()).pathname, method = request.method();
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'accuracy-browser', username: 'accuracy-browser' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') return route.fulfill({ json: { reviews: [...models].map(([id, m]) => ({ job_id: id, drawing_name: `测试图纸${id}`, revision: m.revision, recognition_status: 'completed' })) } });
  const match = api.match(/^\/api\/reviews\/(a|b|hot|cold-load|hot-load|multi-load|material-load|direct-load|manual-load|root-load)(?:\/(.*))?$/);
  if (match) {
    const [, id, action] = match, model = models.get(id);
    if (!action) {
      if (method === 'PATCH') {
        if (holdSave) { holdSave = false; await new Promise(resolve => { releaseSave = resolve; }); }
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
      if (failStandard) return route.fulfill({ status: 503, json: { detail: '模拟标准化失败' } });
      if (holdStandard) { holdStandard = false; await new Promise((resolve) => { releaseStandard = resolve; }); }
      const python = "import sys,json;sys.path.insert(0,'src');from ai_design_review import standard_selector;standard_selector.standard_references=lambda *a,**k:[];from ai_design_review.workflow import apply_standardization_to_review;r=json.load(sys.stdin);apply_standardization_to_review(r);print(json.dumps(r,ensure_ascii=False))";
      model.review = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['-c', python], { input: JSON.stringify(input.review), encoding: 'utf8', env })); model.revision++;
      return route.fulfill({ json: { job_id: id, review: model.review, review_revision: model.revision, warnings: [] } });
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
async function saved() { await page.evaluate(() => flushReviewPersistence({throwOnError:true})); try { await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length); } catch(error) { console.error('Persistence state', await page.evaluate(() => ({pending:state.pendingReviewAuditEvents,failed:state.reviewPersistenceFailedFields,saving:state.reviewPersistenceSaving,standardizing:state.standardizationInFlight,revision:state.lastJob?.review_revision}))); throw error; } }
const tolerance = () => root.locator('[data-kind="param"][data-field="free_length"] [data-role="tolerance"]:visible');
try {
  await page.goto(process.env.ACCURACY_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.recentReviews.length === 2);
  await open('a'); await tab('parameters');
  assert.equal(await root.locator('[data-kind="param"][data-field="accuracy_grade"]').count(), 0);
  assert.equal(await root.locator('[data-kind="execution-standard"]').count(), 0);
  assert.equal(await page.evaluate(() => buildSafeConfirmationPlan(state.review).items.some(item => ['standard_no','accuracy_grade'].includes(item.field))), false);
  assert.equal(await page.evaluate(() => {
    const panel = document.querySelector('[data-compare-panel="parameters"]');
    return Boolean(panel.querySelector('[data-kind="standardization-settings"]').compareDocumentPosition(panel.querySelector('[data-kind="parameter-reasonableness"]')) & Node.DOCUMENT_POSITION_FOLLOWING);
  }), true, 'Settings appear before reasonableness');
  assert.equal(await page.evaluate(() => state.review.spring_parameters.accuracy_grade.value), '1级');
  await tolerance().fill('±0.6');
  assert.equal(await tolerance().evaluate((input) => document.activeElement === input), true, 'Inference keeps the input focused');
  await tolerance().press('Tab'); await saved();
  assert.equal(models.get('a').review.spring_parameters.accuracy_grade.value, '2级');
  await tab('workbench'); await grade().selectOption('3级');
  assert.equal(await root.locator('.workbench-standardization-step [data-execution-standard-selector]').count(), 1);
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
  // Both entrypoints persist the same execution standard before regeneration.
  const standard = () => root.locator('[data-execution-standard-selector]:visible').first();
  await standard().selectOption('GB/T 23934-2015'); await saved();
  await grade().selectOption('T级'); await saved();
  assert.equal(models.get('b').review.standard_selection.selected_standard, 'GB/T 23934-2015');
  assert.equal(models.get('b').review.accuracy_inference.selection_mode, 'manual');
  const originalTolerance = models.get('b').review.spring_parameters.free_length.tolerance_upper;
  await tab('parameters');
  assert.equal(await standard().inputValue(), 'GB/T 23934-2015');
  assert.equal(await grade().inputValue(), 'T级');
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight);
  assert.equal(await page.evaluate(() => ExecutionStandards.fresh(state.review)), true);
  assert.equal(models.get('b').review.spring_parameters.free_length.tolerance_upper, originalTolerance);
  await standard().selectOption('GB/T 1239.2-2009'); await saved();
  assert.equal(await grade().inputValue(), '');
  assert.equal(await root.locator('[data-action="run-workbench-standardization"]:visible').isDisabled(), true);
  assert.equal(await page.evaluate(() => standardizationBatchPlan(state.review).items.length), 0);
  await grade().selectOption('2级'); await saved();
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight);
  const independentBeforeBatch = await page.evaluate(() => structuredClone(state.review.accuracy_inference.input_snapshot));
  const applied = await page.evaluate(() => applyAvailableStandardizationSuggestions());
  assert.ok(applied.count > 0, 'An explicit batch includes existing manual tolerances'); await saved();
  assert.equal(models.get('b').review.spring_parameters.free_length.tolerance_upper, .8);
  assert.deepEqual(await page.evaluate(() => state.review.accuracy_inference.input_snapshot), independentBeforeBatch);
  assert.equal(await page.evaluate(() => Boolean(undoLastStandardizationApplication())), true);
  assert.equal(await page.evaluate(() => state.review.spring_parameters.free_length.tolerance_upper), originalTolerance);
  await open('b'); await tab('workbench');
  assert.equal(await standard().inputValue(), 'GB/T 1239.2-2009');
  assert.equal(await grade().inputValue(), '2级');
  failSave = true; await standard().selectOption('GB/T 23934-2015');
  await page.waitForFunction(() => Boolean(state.reviewPersistenceFailedFields.standard_selection));
  assert.equal(await root.locator('[data-action="run-workbench-standardization"]:visible').isDisabled(), true);
  failSave = false; await root.locator('[data-action="retry-standardization-save"]:visible').click(); await saved();
  assert.equal(models.get('b').review.standard_selection.selected_standard, 'GB/T 23934-2015');
  await page.screenshot({ path: path.join(output, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 }); await grade().scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(output, 'mobile.png') });
  assert.equal(await grade().isVisible(), true);
  for (const [name, viewport] of [['desktop', {width:1440,height:1000}], ['mobile', {width:390,height:844}]]) {
    await page.setViewportSize(viewport);
    for (const panel of ['workbench', 'parameters']) {
      await tab(panel); await standard().scrollIntoViewIfNeeded();
      assert.equal(await standard().isVisible(), true);
      assert.equal(await grade().isVisible(), true);
      assert.equal(await standard().evaluate(element => element.getBoundingClientRect().right <= window.innerWidth), true, `${name} ${panel} standard fits`);
      await page.screenshot({ path: path.join(output, `${name}-${panel}.png`) });
    }
  }
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
  // Real hot rule output and native T selector, with current manual-mode rules.
  const hot = review(), fixture = fixtures.find(f => f.name === 'hot row13 strictest T').expected;
  hot.spring_parameters = { ...hot.spring_parameters, ...fixture.spring_parameters, load_points: [] };
  hot.standard_selection = fixture.standard_selection; hot.accuracy_inference = fixture.accuracy_inference;
  hot.standardization_results = [];
  models.set('hot', { review: hot, revision: 1 });
  await open('hot'); await tab('workbench');
  assert.equal(await grade().inputValue(), 'T级');
  assert.deepEqual(await grade().locator('option').evaluateAll(xs => xs.filter(x => x.value).map(x => x.value)), ['T级', '1级', '2级', '3级']);
  await grade().selectOption('2级');
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight && state.review.accuracy_inference.selection_mode === 'manual');
  await page.evaluate(() => {
    const items = state.review.standardization_results.filter(r => ['inner_diameter','free_length'].includes(r.target_field));
    const before = Object.fromEntries(items.map(r => [r.target_field, parameterAuditState(state.review.spring_parameters[r.target_field])]));
    applyStandardizationResults(items);
    for (const item of items) queueReviewAuditEvent({ event_type: 'parameter_tolerance_updated', target_field: item.target_field,
      before_state: before[item.target_field], after_state: parameterAuditState(state.review.spring_parameters[item.target_field]) });
  }); await saved();
  assert.equal(models.get('hot').review.spring_parameters.inner_diameter.tolerance_upper, 2);
  assert.equal(models.get('hot').review.spring_parameters.free_length.tolerance_upper, 5.48);
  assert.equal(models.get('hot').review.accuracy_inference.inferred_grade, 'T级');
  await open('a'); await open('hot'); await tab('parameters');
  assert.equal(await grade().inputValue(), '2级');
  await page.screenshot({ path: path.join(output, 'hot-manual-grade.png') });
  // Load diagnostics remain separate from applicable suggestions and preserve tolerances.
  const coldLoad = review();
  Object.assign(coldLoad.spring_parameters, {
    wire_diameter: { value: 3, unit: 'mm' }, outer_diameter: { value: 30, unit: 'mm' }, mean_diameter: { value: 27, unit: 'mm' },
    free_length: { value: 50, unit: 'mm' }, total_coils: { value: null, source: ['human_input'] },
    active_coils: { value: null, unit: 'turns', source: ['human_input'] }, spring_rate: { value: null },
    accuracy_grade: { value: '2级', source: ['human_selected'] },
    load_points: [{ label: 'F1', force: 100, height: 40, force_tolerance_percent: 10 }, { label: 'F2', force: 200, height: 30, load_tolerance_upper: 4, load_tolerance_lower: -2 }],
  });
  coldLoad.standard_selection = { selected_standard: 'GB/T 1239.2-2009', selection_source: 'human_selected' };
  coldLoad.accuracy_inference.selection_mode = 'manual';
  models.set('cold-load', { review: coldLoad, revision: 1 });
  await open('cold-load'); await tab('parameters');
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight);
  assert.equal(await root.locator('[data-standardization-diagnostic]:visible').count(), 2);
  assert.match(await root.locator('[data-standardization-diagnostic]:visible').first().textContent(), /有效圈数.*F1/);
  assert.match(await root.locator('[data-standardization-control-status]:visible').textContent(), /已生成 \d+ 项，\d+ 项未能生成/);
  assert.ok(await page.evaluate(() => standardizationReport(state.review).failed >= 2));
  assert.equal(await root.locator('[data-kind="load_point"] [data-role="load-tolerance"]:visible').first().inputValue(), '±10%');
  assert.equal(await page.evaluate(() => reasonablenessSuggestionBatchPlan(state.review).items.some(item => item.target_field?.startsWith('load_points'))), false);
  const active = root.locator('[data-kind="param"][data-field="active_coils"] [data-role="value"]:visible');
  await active.fill('8'); await active.press('Tab'); await saved();
  assert.match(await root.locator('[data-standardization-diagnostic]:visible').first().textContent(), /待更新/);
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight);
  assert.equal(await root.locator('[data-standardization-diagnostic]:visible').count(), 0);
  assert.equal(await root.locator('[data-kind="load_point"] [data-role="load-tolerance"]:visible').first().inputValue(), '±10%');
  await active.fill('2'); await active.press('Tab'); await saved();
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight);
  assert.match(await root.locator('[data-standardization-diagnostic]:visible').first().textContent(), /查表范围.*手填公差/);
  // Saving and calculation both show the spinner, with a single request.
  holdSave = true; holdStandard = true; releaseStandard = null;
  const beforeSlowRun = standards;
  await grade().selectOption('3级');
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => state.standardizationInFlight);
  assert.equal(await root.locator('[data-action="run-workbench-standardization"][aria-busy="true"] .standardization-spinner').count(), 2);
  assert.equal(await grade().isDisabled(), true);
  assert.equal(await root.locator('[data-execution-standard-selector]:visible').isDisabled(), true);
  assert.equal(standards, beforeSlowRun, 'No calculation before the pending save finishes');
  for (let i = 0; !releaseSave && i < 200; i++) await new Promise(resolve => setTimeout(resolve, 10));
  releaseSave();
  for (let i = 0; !releaseStandard && i < 200; i++) await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(standards, beforeSlowRun + 1);
  await tab('workbench');
  assert.equal(await root.locator('[data-action="run-workbench-standardization"]:visible .standardization-spinner').count(), 1);
  releaseStandard();
  await page.waitForFunction(() => !state.standardizationInFlight);
  assert.equal(await root.locator('.standardization-spinner').count(), 0);
  failStandard = true;
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight && state.standardizationError?.kind === 'calculation');
  assert.match(await root.locator('[data-standardization-control-status]:visible').textContent(), /标准化失败.*重试/);
  assert.equal(await root.locator('[data-action="run-workbench-standardization"]:visible').isEnabled(), true);
  failStandard = false;
  await tab('parameters'); failSave = true;
  await active.fill('8'); await active.press('Tab');
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight && state.standardizationError?.kind === 'save');
  assert.equal(await grade().inputValue(), '3级');
  assert.equal(await root.locator('[data-action="retry-standardization-save"]:visible').count(), 1);
  failSave = false;
  await root.locator('[data-action="retry-standardization-save"]:visible').click(); await saved();
  await page.waitForFunction(() => state.standardizationError == null);
  assert.equal(await root.locator('[data-action="run-workbench-standardization"]:visible').isEnabled(), true);
  const hotLoad = structuredClone(coldLoad);
  hotLoad.standard_selection.selected_standard = 'GB/T 23934-2015';
  hotLoad.spring_parameters.material = { value: 'SUS304' };
  hotLoad.spring_parameters.accuracy_grade = { value: '2级', source: ['tolerance_inference'] };
  hotLoad.accuracy_inference.selection_mode = 'auto';
  models.set('hot-load', { review: hotLoad, revision: 1 });
  await open('hot-load'); await tab('parameters');
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight);
  assert.match(await root.locator('[data-standardization-diagnostic]:visible').first().textContent(), /缺少有效圈数.*无法计算刚度.*F1/);
  assert.equal(await page.evaluate(() => state.review.accuracy_inference.selection_mode), 'auto');
  assert.equal(await page.evaluate(() => state.review.spring_parameters.accuracy_grade.source.includes('human_selected')), false);
  const loadIssue = () => root.locator('[data-standardization-issue]:visible').filter({ hasText: 'GBT23934-LOAD' });
  assert.equal(await loadIssue().count(), 1, 'F1 and F2 share one actionable explanation');
  assert.match(await loadIssue().textContent(), /F1、F2.*处理方式.*补充有效圈数/s);
  assert.doesNotMatch(await loadIssue().textContent(), /建议向客户确认|缺少有效计算依据/);
  assert.match(await root.locator('.parameter-reasonableness-summary:visible').textContent(), /有效圈数/);
  await loadIssue().getByRole('button', { name: '补充有效圈数', exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.closest('[data-kind="param"]')?.dataset.field === 'active_coils');
  assert.equal(await active.evaluate(input => input.closest('[data-kind="param"]').classList.contains('review-target-highlight')), true);
  // Historical records with only the generic stiffness issue resolve current roots too.
  await page.evaluate(() => {
    state.review.standardization_results.forEach(item => { if (item.metadata) delete item.metadata.root_missing_fields; });
    state.review.parameter_reasonableness.issues = [{ category: 'standardization', severity: 'needs_input', fields: ['spring_rate'], message: '缺少有效计算依据' }];
    renderCompareOverlay();
  });
  assert.equal(await loadIssue().getByRole('button', { name: '补充有效圈数', exact: true }).count(), 1);
  await active.fill('8'); await active.press('Tab'); await saved();
  assert.equal(await loadIssue().count(), 0, 'Input edits immediately remove obsolete root-cause cards');
  assert.match(await root.locator('[data-standardization-control-status]:visible').textContent(), /待重新标准化/);
  await root.locator('[data-action="run-workbench-standardization"]:visible').click();
  await page.waitForFunction(() => !state.standardizationInFlight);
  assert.equal(await loadIssue().count(), 0);
  assert.equal(await root.locator('[data-standardization-diagnostic]:visible').count(), 0);
  assert.equal(await root.locator('[data-kind="load_point"] [data-role="load-tolerance"]:visible').first().inputValue(), '±10%');

  async function openLoadCase(id, value) {
    models.set(id, { review: value, revision: 1 });
    await open(id); await tab('parameters');
    await root.locator('[data-action="run-workbench-standardization"]:visible').click();
    await page.waitForFunction(() => !state.standardizationInFlight);
  }
  const multiLoad = structuredClone(hotLoad);
  multiLoad.spring_parameters.material = { value: null, source: ['human_input'] };
  multiLoad.spring_parameters.mean_diameter = { value: 'invalid', unit: 'mm', source: ['human_input'] };
  multiLoad.spring_parameters.outer_diameter = { value: null, unit: 'mm', source: ['human_input'] };
  multiLoad.spring_parameters.inner_diameter = { value: null, unit: 'mm', source: ['human_input'] };
  await openLoadCase('multi-load', multiLoad);
  const missingButtons = await loadIssue().locator('[data-role="focus-reasonableness-field"]').evaluateAll(buttons => buttons.map(button => button.dataset.field));
  assert.deepEqual(new Set(missingButtons), new Set(['mean_diameter', 'active_coils', 'material']));
  const materialLoad = structuredClone(hotLoad);
  materialLoad.spring_parameters.active_coils = { value: 8, unit: 'turns', source: ['human_input'] };
  materialLoad.spring_parameters.material = { value: 'UNKNOWN', source: ['human_input'] };
  await openLoadCase('material-load', materialLoad);
  await loadIssue().getByRole('button', { name: '核对材料', exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.closest('[data-kind="param"]')?.dataset.field === 'material');
  const directLoad = structuredClone(hotLoad);
  directLoad.spring_parameters.active_coils = { value: 8, unit: 'turns', source: ['human_input'] };
  directLoad.spring_parameters.spring_rate = { value: null, unit: 'N/mm', source: ['human_input'] };
  await openLoadCase('direct-load', directLoad);
  await loadIssue().getByRole('button', { name: '补充刚度', exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.closest('[data-kind="param"]')?.dataset.field === 'spring_rate');
  assert.equal(await root.locator('[data-kind="param"][data-field="spring_rate"]').evaluate(row => row.closest('details')?.open), true);
  const manualLoad = structuredClone(hotLoad);
  manualLoad.spring_parameters.spring_rate = { value: 10, unit: 'N/mm', source: ['human_input'] };
  await openLoadCase('manual-load', manualLoad);
  assert.equal(await loadIssue().count(), 0, 'A manual stiffness does not require active coils');
  await openLoadCase('root-load', structuredClone(hotLoad));
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    await page.setViewportSize(viewport);
    for (const panel of ['workbench', 'parameters']) {
      await tab(panel);
      await root.locator(panel === 'workbench' ? '.workbench-standardization-step:visible' : '[data-kind="standardization-settings"]:visible').scrollIntoViewIfNeeded();
      assert.equal(await root.locator('[data-execution-standard-selector]:visible').evaluate(element => element.getBoundingClientRect().right <= window.innerWidth), true);
      assert.equal(await root.locator(`[data-compare-panel="${panel}"]`).evaluate(element => element.scrollWidth <= element.clientWidth + 1), true);
      if (panel === 'workbench') assert.equal(await root.locator('.workbench-standardization-content').evaluate(element => {
        const heading = element.querySelector('.standardization-settings-heading').getBoundingClientRect();
        const controls = element.querySelector('.execution-standard-toolbar').getBoundingClientRect();
        return controls.top >= heading.bottom - 1 && controls.left >= element.getBoundingClientRect().left - 1;
      }), true, 'Selectors stay below the heading at both widths');
      if (panel === 'workbench') {
        const actions = await root.locator('.workbench-standardization-content > .workbench-step-actions').evaluate(element => [...element.querySelectorAll('button:not([hidden])')].map(button => {
          const style = getComputedStyle(button);
          return { text: button.textContent.trim(), height: button.getBoundingClientRect().height, font: style.fontSize, padding: style.padding, secondary: button.classList.contains('secondary-action') };
        }));
        assert.equal(actions[0].text, '重新标准化');
        assert.ok(actions[1].text.startsWith('查看并处理建议'));
        assert.equal(actions[2].text, '查看依据');
        assert.equal(new Set(actions.map(action => `${action.height}/${action.font}/${action.padding}`)).size, 1);
        assert.ok(actions.every(action => action.secondary));
        assert.equal(await root.locator('.workbench-standardization-content > .standardization-settings-heading button').count(), 0);
      } else {
        assert.equal(await root.locator('[data-kind="standardization-settings"] .standardization-settings-heading [data-action="run-workbench-standardization"]').count(), 1);
        await loadIssue().scrollIntoViewIfNeeded();
      }
      await page.screenshot({ path: path.join(output, `${name}-${panel}-root-diagnostics.png`) });
    }
  }
  assert.deepEqual(errors, []);
  console.log('Accuracy browser: dual standard selectors, immediate saves, T-grade switching, batch replacement/undo, manual inference, failure/retry, conflicts, late responses and desktop/mobile passed');
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
