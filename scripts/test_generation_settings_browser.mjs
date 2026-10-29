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
let holdPackage = false, releasePackage = null, failPackage = false, packageCount = 0;
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
      packageCount++;
      if (failPackage === 'network') return route.abort('failed');
      if (failPackage) return route.fulfill({status:503,json:{detail:'模拟导出失败'}});
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
  const createButton=()=>root.locator('[data-action="create-generation-job"]');
  const initialRequests={packages:packageCount,creates:createCount};
  await root.locator('[data-compare-tab="workbench"]').click();
  assert.equal(await root.locator('[data-action="export-generation-package"]').count(),0);
  const go=root.locator('[data-target-tab="generation"]');
  assert.equal(await go.innerText(),'去生图');
  await go.click();
  assert.equal(await root.locator('[data-compare-tab="generation"]').evaluate(el=>document.activeElement===el),true);
  assert.deepEqual({packages:packageCount,creates:createCount},initialRequests,'navigation sends no package/create requests');
  for(const status of ['ready','ready_with_warnings','needs_input','needs_confirmation','blocked','not_applicable']) {
    await page.evaluate(status=>{state.generationReadiness={generation_readiness:{status}};syncGenerationSettingsControls();},status);
    assert.equal(await createButton().isDisabled(),!['ready','ready_with_warnings'].includes(status),status);
  }
  await page.evaluate(()=>{state.generationReadiness={generation_readiness:{status:'ready'}};state.generationQueueAvailable=false;syncGenerationSettingsControls();});
  assert.equal(await createButton().isDisabled(),true,'unavailable service');
  await page.evaluate(()=>{state.generationQueueAvailable=true;window.originalJob=state.lastJob;state.lastJob=null;syncGenerationSettingsControls();});
  assert.equal(await createButton().isDisabled(),true,'local imports cannot create tasks');
  await page.evaluate(()=>{state.lastJob=originalJob;syncGenerationSettingsControls();});

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
  const beforeFailedExport=packageCount;
  await page.evaluate(async()=>{const action={can_download:true,source_mode:'server',review_revision:state.lastJob.review_revision};state.review.standardization_chat=[{generation_package_export:action}];await executeGenerationPackageExport(action,0);});
  assert.equal(packageCount,beforeFailedExport,'failed save sends no package request');
  assert.equal(await page.evaluate(()=>state.generationBusy),false);
  assert.equal(await createButton().innerText(),'生成图纸');

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
  assert.equal(await root.locator('[data-action="export-generation-package"]').count(), 0);
  await page.evaluate(() => exportCurrentGenerationPackage());
  await page.waitForFunction(() => settingsDownloads.length === 1);
  const downloaded = await page.evaluate(() => settingsDownloads[0]);
  assert.equal(downloaded.solidworks_preview.DrawingModel, 'Y型'); assert.equal(downloaded.solidworks_preview.Username, '阿拉伯特');
  await page.evaluate(async () => {
    const action = { can_download: true, source_mode: 'server', review_revision: state.lastJob.review_revision, filename: 'settings.json' };
    state.review.standardization_chat = [{ generation_package_export: action }];
    await executeGenerationPackageExport(action, 0);
  });
  assert.equal(await page.evaluate(() => settingsDownloads.length), 2, 'Chat export uses the same saved settings');
  assert.equal(await createButton().isEnabled(),true,'chat export restores create button');
  for(const failure of [true,'network']) {
    failPackage=failure;
    await page.evaluate(async()=>{const action={can_download:true,source_mode:'server',review_revision:state.lastJob.review_revision};state.review.standardization_chat=[{generation_package_export:action}];refreshReviewSurfaces();await executeGenerationPackageExport(action,0);});
    assert.equal(await createButton().isEnabled(),true,'request failure restores create button');
    assert.equal(await createButton().innerText(),'生成图纸');
  }
  failPackage=false;
  holdPackage=true;releasePackage=null;
  await page.evaluate(()=>{
    const action={can_download:true,source_mode:'server',review_revision:state.lastJob.review_revision};
    state.review.standardization_chat=[{generation_package_export:action}];refreshReviewSurfaces();
    window.sameGenerationInput=document.querySelector('#compareOverlay [data-generation-setting="username"]');
    window.slowChatExport=executeGenerationPackageExport(action,0);
  });
  await page.waitForFunction(()=>state.generationBusy);
  for(let n=0;!releasePackage&&n<300;n++)await page.waitForTimeout(10);
  assert.equal(typeof releasePackage,'function');
  assert.equal(await createButton().isDisabled(),true);assert.equal(await createButton().innerText(),'处理中…');
  const duringExportCreateCount=createCount;
  await page.evaluate(()=>createGenerationJob());assert.equal(createCount,duringExportCreateCount,'no overlapping create');
  await page.evaluate(()=>{state.generationReadiness={generation_readiness:{status:'blocked'}};});
  releasePackage();assert.equal(await page.evaluate(()=>slowChatExport),true);
  assert.equal(await createButton().isDisabled(),true,'do not force enable when readiness changed');
  assert.equal(await page.evaluate(()=>sameGenerationInput===document.querySelector('#compareOverlay [data-generation-setting="username"]')),true,'status changes preserve input nodes');
  await page.evaluate(()=>{state.generationReadiness={generation_readiness:{status:'ready'}};syncGenerationSettingsControls();});
  assert.equal(await createButton().isEnabled(),true);

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
  assert.equal(await page.evaluate(() => settingsDownloads.length), 3);
  await orientation().selectOption('X型'); await username().fill('新姓名'); await username().press('Tab'); await saved();
  assert.deepEqual(reviews.get('a').jobs[0], frozen, 'Editing never rewrites an existing job');
  assert.equal(await page.evaluate(() => JSON.stringify(state.review.manual_confirmations)), confirmations);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await createButton().scrollIntoViewIfNeeded();
    if (!process.env.SKIP_UI_QA_SCREENSHOTS) {
      if(width===390)await page.screenshot({path:path.join(output,`settings-${width}.png`)});
      else await root.locator('.generation-readiness-block').screenshot({path:path.join(output,`settings-${width}.png`)});
    }
    const layout=await root.locator('.generation-package-actions').evaluate(el=>{const b=el.querySelector('button').getBoundingClientRect(),r=el.getBoundingClientRect();return {width:b.width,available:r.width,right:b.right,edge:r.right};});
    if(width===390)assert.ok(Math.abs(layout.width-layout.available)<2,'narrow primary button fills row');
    else assert.ok(Math.abs(layout.right-layout.edge)<2,'desktop primary button right aligned');
    await root.locator('[data-compare-tab="workbench"]').click();
    await root.locator('[data-target-tab="generation"]').scrollIntoViewIfNeeded();
    if(!process.env.SKIP_UI_QA_SCREENSHOTS)await root.locator('[data-target-tab="generation"]').locator('xpath=ancestor::article').screenshot({path:path.join(output,`workbench-${width}.png`)});
    await root.locator('[data-target-tab="generation"]').click();
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
  holdCreate=true;releaseCreate=null;
  await createButton().click();await waitRelease();
  releasePackage();
  assert.equal(await page.evaluate(() => lateExport), false);
  assert.equal(await page.evaluate(() => lateSettingsDownloads.length), 0, 'Late exports cannot download a different order under the current page');
  assert.equal(await page.evaluate(()=>state.generationBusy),true,'old export cannot unlock the new creation');
  assert.equal(await createButton().isDisabled(),true);
  releaseCreate();await page.waitForFunction(()=>!state.generationBusy);

  assert.deepEqual(errors, []);
  console.log('PASS: real-name defaults, native controls, save/reopen, failed-save guard/retry, polling focus, frozen versions, navigation/readiness, retained exports, save/network failure recovery, desktop/mobile and late-operation isolation; mock APIs only.');
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
