import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const cases = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_solidworks_export.py', '--json'], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 }));
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const frontend = path.resolve('frontend'), output = path.resolve('outputs/generation-settings-qa');
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((request, response) => {
  const file = path.resolve(frontend, new URL(request.url, 'http://localhost').pathname.slice(1) || 'index.html');
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return response.writeHead(404).end();
  response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
  response.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], reviews = new Map(['a', 'b'].map((id) => [id, { review: structuredClone(cases[0].review), revision: 1, jobs: [] }]));
let failSave = false, conflictSave = false, holdCreate = false, releaseCreate = null, createCount = 0;
let holdPackage = false, releasePackage = null;
page.on('pageerror', (error) => errors.push(error.message));
page.on('dialog', (dialog) => dialog.accept());
await page.route('**/api/**', async (route) => {
  const request = route.request(), api = new URL(request.url()).pathname, method = request.method();
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'settings-user', username: 'account-name', real_name: '登录真实姓名' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') return route.fulfill({ json: { reviews: [...reviews].map(([id, model]) => ({ job_id: id, drawing_name: `图纸${id}`, revision: model.revision, recognition_status: 'completed' })) } });
  const match = api.match(/^\/api\/reviews\/(a|b)(?:\/(.*))?$/);
  if (match) {
    const [, id, action] = match, model = reviews.get(id);
    if (!action) {
      if (method === 'PATCH') {
        if (failSave) return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
        if (conflictSave) {
          conflictSave = false; model.revision++;
          model.review.generation_settings.username = '其他页面的姓名';
          return route.fulfill({ status: 409, json: { detail: '模拟版本冲突' } });
        }
        const input = request.postDataJSON();
        if (input.expected_revision !== model.revision) return route.fulfill({ status: 409, json: { detail: '模拟版本冲突' } });
        model.review = input.review; model.revision++;
        return route.fulfill({ json: { review_revision: model.revision, events: input.events } });
      }
      return route.fulfill({ json: { ...model.review, job_id: id, review_revision: model.revision } });
    }
    if (action === 'generation-readiness') return route.fulfill({ json: { review_revision: model.revision, generation_readiness: { status: 'ready', confirmed_core_count: 8, core_field_count: 8, warnings: [] } } });
    if (action === 'generation-package') {
      if (holdPackage) { holdPackage = false; await new Promise((resolve) => { releasePackage = resolve; }); }
      return route.fulfill({ json: { review_revision: model.revision,
        parameter_package: await page.evaluate((review) => makeGenerationParameterPackage(review), model.review) } });
    }
    if (action === 'generation-jobs') {
      if (method === 'POST') {
        createCount++;
        const settings = structuredClone(model.review.generation_settings);
        if (holdCreate) { holdCreate = false; await new Promise((resolve) => { releaseCreate = resolve; }); }
        const job = { generation_id: `task-${createCount}`, review_id: id, status: 'completed', progress: 100,
          review_revision: model.revision, generation_settings: settings, artifacts: [], preview_status: 'ready' };
        model.jobs.unshift(job);
        return route.fulfill({ status: 202, json: { generation_job: job } });
      }
      return route.fulfill({ json: { generation_jobs: model.jobs, generation_queue_available: true } });
    }
    if (action === 'annotations') return route.fulfill({ json: { pages: [], annotations: [] } });
    if (action === 'changes') return route.fulfill({ json: { events: [] } });
  }
  if (api.endsWith('/reasonableness')) return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
  return route.fulfill({ json: { status: 'ok', generation_runtime: { status: 'available' }, recognition_queue_runtime: { status: 'available' } } });
});
const root = page.locator('.compare-overlay'), username = () => root.locator('[data-generation-setting="username"]'), orientation = () => root.locator('[data-generation-setting="drawing_model"]');
const saved = () => page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length);
const waitRelease = () => new Promise((resolve, reject) => { const deadline = Date.now() + 10000;
  const check = () => releaseCreate ? resolve() : Date.now() > deadline ? reject(new Error('No mocked create request arrived')) : setTimeout(check, 10); check(); });
async function open(id) {
  await page.evaluate(async (id) => { await openPersistedReview(id); state.compareTab = 'generation'; renderCompareOverlay(); }, id);
  await username().waitFor();
}
try {
  await page.goto(process.env.GENERATION_SETTINGS_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.recentReviews.length === 2);
  await open('a');
  assert.equal(await username().inputValue(), '登录真实姓名');
  assert.equal(await orientation().inputValue(), 'X型');
  await orientation().selectOption('Y型');
  await username().fill('阿拉伯特'); await username().press('Tab'); await saved();
  assert.deepEqual(reviews.get('a').review.generation_settings, { drawing_model: 'Y型', username: '阿拉伯特' });
  const confirmations = await page.evaluate(() => JSON.stringify(state.review.manual_confirmations));
  await username().fill('正在输入的姓名');
  await username().evaluate((input) => input.setSelectionRange(2, 5));
  await page.evaluate(() => loadGenerationState('a'));
  assert.equal(await username().inputValue(), '正在输入的姓名');
  assert.equal(await username().evaluate((input) => document.activeElement === input && input.selectionStart === 2 && input.selectionEnd === 5), true, 'Polling preserves focus and caret');
  await username().press('Tab'); await saved();
  failSave = true;
  await username().fill('保存失败保留姓名'); await username().press('Tab');
  await page.waitForFunction(() => Object.keys(state.reviewPersistenceFailedFields).some((key) => key.startsWith('generation_settings.')));
  const beforeCreate = createCount;
  await page.evaluate(() => createGenerationJob());
  assert.equal(createCount, beforeCreate, 'Save failure sends no create request');
  assert.equal(await username().inputValue(), '保存失败保留姓名');
  failSave = false;
  await root.locator('[data-action="retry-generation-settings"]').click(); await saved();
  await username().fill('阿拉伯特'); await username().press('Tab'); await saved();
  holdCreate = true; releaseCreate = null;
  await root.locator('[data-action="create-generation-job"]').click();
  await waitRelease();
  assert.equal(await username().isDisabled(), true);
  releaseCreate();
  await page.waitForFunction(() => !state.generationBusy && state.generationJobs.length === 1);
  assert.ok((await root.locator('.generation-version-title').innerText()).includes('竖版 · 阿拉伯特'));
  const frozen = structuredClone(reviews.get('a').jobs[0]);
  await page.evaluate(() => { window.settingsDownloads = []; downloadJson = (value) => settingsDownloads.push(value); });
  await root.locator('[data-compare-panel="generation"] [data-action="export-generation-package"]').click();
  await page.waitForFunction(() => settingsDownloads.length === 1);
  const downloaded = await page.evaluate(() => settingsDownloads[0]);
  assert.equal(downloaded.solidworks_preview.DrawingModel, 'Y型'); assert.equal(downloaded.solidworks_preview.Username, '阿拉伯特');
  await page.evaluate(async () => {
    const action = { can_download: true, source_mode: 'server', review_revision: state.lastJob.review_revision, filename: 'settings.json' };
    state.review.standardization_chat = [{ generation_package_export: action }];
    await executeGenerationPackageExport(action, 0);
  });
  assert.equal(await page.evaluate(() => settingsDownloads.length), 2, 'Chat export uses the same saved settings');
  conflictSave = true;
  const derivedBefore = await page.evaluate(() => state.review.derived_parameters_stale);
  await username().fill('解决冲突后的姓名'); await username().press('Tab');
  await page.locator('.parameter-conflict-dialog').waitFor();
  await page.locator('.parameter-conflict-dialog [data-choice="local"]').click(); await saved();
  assert.equal(await username().inputValue(), '解决冲突后的姓名');
  assert.equal(reviews.get('a').review.generation_settings.username, '解决冲突后的姓名');
  assert.equal(await page.evaluate(() => state.review.derived_parameters_stale), derivedBefore, 'Presentation-only conflict merging does not invalidate formulas');
  await username().fill(''); await username().press('Tab'); await saved();
  await page.evaluate(() => createGenerationJob());
  assert.equal(createCount, beforeCreate + 1);
  assert.ok((await root.locator('.generation-settings-error').innerText()).includes('请填写'));
  assert.equal(await page.evaluate(() => exportCurrentGenerationPackage()), false);
  assert.equal(await page.evaluate(() => settingsDownloads.length), 2);
  await orientation().selectOption('X型'); await username().fill('新姓名'); await username().press('Tab'); await saved();
  assert.deepEqual(reviews.get('a').jobs[0], frozen, 'Editing never rewrites an existing job');
  assert.equal(await page.evaluate(() => JSON.stringify(state.review.manual_confirmations)), confirmations);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) await root.locator('.generation-settings').screenshot({ path: path.join(output, `settings-${width}.png`) });
    assert.equal(await root.locator('.generation-settings').evaluate((element) => element.scrollWidth > element.clientWidth), false);
  }
  await page.reload(); await page.waitForFunction(() => state.identityReady && state.recentReviews.length === 2); await open('a');
  assert.equal(await username().inputValue(), '新姓名'); assert.equal(await orientation().inputValue(), 'X型');
  holdCreate = true; releaseCreate = null;
  await root.locator('[data-action="create-generation-job"]').click(); await waitRelease();
  await page.evaluate(() => closeCompareOverlay()); await open('b');
  releaseCreate(); await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 100)));
  assert.equal(await page.evaluate(() => state.lastJob.job_id), 'b');
  assert.equal(await page.evaluate(() => state.generationJobs.length), 0, 'Late creation cannot replace the next order');
  assert.equal(await username().inputValue(), '登录真实姓名');
  holdPackage = true;
  await page.evaluate(() => { window.lateSettingsDownloads = []; downloadJson = (value) => lateSettingsDownloads.push(value); window.lateExport = exportCurrentGenerationPackage(); });
  await new Promise((resolve, reject) => { const deadline = Date.now() + 10000;
    const check = () => releasePackage ? resolve() : Date.now() > deadline ? reject(new Error('No package request')) : setTimeout(check, 10); check(); });
  await page.evaluate(() => closeCompareOverlay()); await open('a');
  releasePackage();
  assert.equal(await page.evaluate(() => lateExport), false);
  assert.equal(await page.evaluate(() => lateSettingsDownloads.length), 0, 'Late exports cannot download a different order under the current page');
  assert.deepEqual(errors, []);
  console.log('PASS: real-name defaults, native controls, save/reopen, failed-save guard/retry, polling focus, frozen versions, both exports, blank-name validation, desktop/mobile and late creation isolation; mock APIs only.');
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
