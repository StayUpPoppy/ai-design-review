import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixture = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_company_surface_mapping.py', '--json'], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }));
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const id = (name) => fixture.catalog.items.find((v) => v.name === name).id;
const frontend = path.resolve('frontend'), output = path.resolve('outputs/company-surface-qa'); fs.mkdirSync(output, { recursive: true });
const drawing = 'C:/Users/29580/Desktop/微信图片_20261023104312_5_187.jpg';
const server = http.createServer((req, res) => {
  const file = path.resolve(frontend, new URL(req.url, 'http://localhost').pathname.slice(1) || 'index.html');
  if (req.url === '/surface-drawing.jpg' && fs.existsSync(drawing)) { res.setHeader('Content-Type', 'image/jpeg'); return res.end(fs.readFileSync(drawing)); }
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); res.end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const imageUrl = `http://127.0.0.1:${server.address().port}/surface-drawing.jpg`;
const browser = await chromium.launch({ headless: true, channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const models = new Map(['a', 'b'].map((job) => [job, { review: structuredClone(fixture.source_review), revision: 1 }]));
let failCatalog = true, failSave = false, conflict = null, holdSave = false, releaseSave = null;
const requests = [], errors = []; page.on('pageerror', (e) => errors.push(e.stack));
await page.route('**/api/**', async (route) => {
  const request = route.request(), api = new URL(request.url()).pathname; requests.push(api);
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'company-surface-test', username: 'company-surface-test' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/surface-treatment-catalog') return route.fulfill(failCatalog ? { status: 503, json: { detail: 'offline' } } : { json: fixture.catalog });
  if (api === '/api/reviews') return route.fulfill({ json: { reviews: [...models].map(([job, m]) => ({ job_id: job, drawing_name: `公司表面处理测试${job}`, revision: m.revision, recognition_status: 'completed', image_url: imageUrl })) } });
  const match = api.match(/^\/api\/reviews\/([^/]+)(?:\/(.+))?$/);
  if (match) {
    const [, job, action] = match, model = models.get(job);
    if (!model) return route.fulfill({ status: 404, json: { detail: 'unknown mock order' } });
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
      return route.fulfill({ json: { ...model.review, job_id: job, review_revision: model.revision } });
    }
    if (action === 'generation-jobs') return route.fulfill({ json: { generation_jobs: [] } });
    if (action === 'annotations') return route.fulfill({ json: { pages: [], annotations: [] } });
    if (action === 'changes') return route.fulfill({ json: { events: [] } });
    if (action === 'reasonableness') return route.fulfill({ json: { parameter_reasonableness: { status: 'ok', issues: [], suggestions: [] } } });
  }
  return route.fulfill({ json: { status: 'ok', recognition_queue_runtime: { status: 'available' } } });
});
const root = page.locator('.compare-overlay');
const row = () => root.locator('.requirement-row[data-requirement-id="surface-one"]');
const body = () => row().locator('[data-role="content"]');
const select = () => row().locator('[data-role="surface-company-select"]').first();
const confirm = () => row().locator('[data-role="confirm"]');
async function open(job) { await page.evaluate(async (job) => { await openPersistedReview(job); renderCompareOverlay(); }, job); await root.waitFor(); await root.locator('[data-compare-tab="parameters"]').click(); await row().waitFor(); }
async function saved() { assert.equal(await page.evaluate(() => Promise.race([flushReviewPersistence(), new Promise((_, reject) => setTimeout(() => reject(new Error(JSON.stringify({ saving: state.reviewPersistenceSaving, pending: state.pendingReviewAuditEvents, failed: state.reviewPersistenceFailedFields, conflicts: state.reviewPersistenceConflictFields }))), 15000))])), true); await page.waitForFunction(() => !state.reviewPersistenceSaving && !state.pendingReviewAuditEvents.length); }
async function edit(text) { await body().fill(text); await body().press('Tab'); await saved(); }
const surfaces = () => page.evaluate(() => state.review.technical_requirements.filter((v) => v.surface_mapping));
try {
  await page.goto(process.env.COMPANY_FRONTEND_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.recentReviews.length === 2); await open('a');
  await page.waitForFunction(() => state.surfaceCatalog.status === 'error'); assert.equal(await select().isDisabled(), true);
  failCatalog = false; await row().locator('[data-role="surface-catalog-retry"]').click(); await page.waitForFunction(() => state.surfaceCatalog.status === 'ready');
  console.log('PASS catalog retry');
  assert.equal(models.get('a').revision, 1, 'Opening an old order must not save the read projection');
  assert.equal((await surfaces())[0].surface_mapping.source_requirement_ids, undefined);
  assert.equal(await select().inputValue(), id('电镀-镀彩锌')); assert.equal(await select().locator('option').count(), 50);
  assert.equal(await row().locator('[data-role="technical-group-status"]').innerText(), '待确认');
  assert.equal((await surfaces()).length, 2); assert.match(await body().inputValue(), /15 μm/);
  assert.equal(await root.locator('[data-role="surface-company-add"], [data-role="surface-company-clear"]').count(), 0);
  assert.equal(await row().locator('[data-role="surface-company-select"]').count(), 1);
  assert.equal(await root.locator('.requirement-row[data-requirement-id="surface-ocr"]').count(), 0);
  assert.match(await row().locator('[data-role="technical-group-sources"] summary').innerText(), /3 条原始记录/);
  assert.equal(await page.evaluate(() => state.review.technical_requirements.find((v) => v.requirement_id === 'surface-ocr').need_human_review), true);
  await row().locator('[data-role="surface-company-search"]').fill('彩锌');
  assert.equal(await select().locator('option').evaluateAll((options) => options.filter((o) => o.value && !o.hidden).length), 1);
  await row().locator('[data-role="surface-company-search"]').fill('');
  await select().focus(); await select().selectOption(id('电镀-镀白锌')); await saved();
  assert.match(await body().inputValue(), /电镀-镀白锌/); assert.match(await body().inputValue(), /除氢/);
  assert.equal(await select().evaluate((el) => document.activeElement === el), true);
  assert.equal((await surfaces()).every((v) => v.need_human_review && v.surface_mapping.catalog_ids[0] === id('电镀-镀白锌')), true);
  await edit('表面处理：' + fixture.chinese); assert.equal(await select().inputValue(), id('电镀-镀彩锌'));
  console.log('PASS linked edits');
  const sources = row().locator('[data-role="technical-group-sources"]'); await sources.locator('summary').click();
  await body().focus(); await page.evaluate(() => syncParameterReasonablenessSurfaces());
  assert.equal(await body().evaluate((el) => el === document.activeElement), true); assert.equal(await sources.evaluate((el) => el.open), true);
  await edit('表面处理：镀锌，镀层厚度≥15 μm，并进行除氢处理。');
  assert.equal(await confirm().isDisabled(), true); assert.match(await row().locator('[data-role="technical-group-reason"]').innerText(), /公司类型与正文不一致/);
  await root.locator('[data-action="confirm-all-review-items"]').click(); await saved();
  assert.equal((await surfaces()).every((v) => v.need_human_review), true);
  assert.equal(await page.evaluate(() => state.review.technical_requirements.filter((v) => !v.surface_mapping && v.requirement_id !== 'surface-ocr').every((v) => v.need_human_review === false)), true);
  const beforeClear = await body().inputValue(); await select().selectOption(''); await saved();
  assert.equal(await body().inputValue(), beforeClear); assert.equal(await select().inputValue(), ''); assert.equal(await confirm().isEnabled(), true);
  await edit('表面处理：' + fixture.chinese); assert.equal(await select().inputValue(), '', 'Explicit none must remain empty');
  await confirm().click(); await saved();
  assert.equal((await surfaces()).every((v) => v.need_human_review === false && v.surface_mapping.selection_mode === 'none'), true);
  console.log('PASS conflicts, bulk and explicit none');
  await select().selectOption(id('电镀-镀彩锌')); await saved();
  assert.equal((await surfaces()).every((v) => v.need_human_review), true);
  failSave = true; await body().fill('表面处理：' + fixture.chinese + ' 保持清洁。'); await body().press('Tab');
  await page.waitForFunction(() => state.reviewPersistenceFailedFields['technical_requirements.surface-one']);
  assert.match(await body().inputValue(), /保持清洁/); failSave = false; await confirm().click(); await saved();
  await confirm().click(); await saved();
  let outgoing = await page.evaluate(() => makeGenerationParameterPackage());
  const text = outgoing.solidworks_preview.extraProperties['技术要求'];
  assert.equal(text.includes('Fe/Ep'), false); assert.equal(text.split('保持清洁').length - 1, 1); assert.match(text, /消除应力退火/); assert.match(text, /保持6h/); assert.match(text, /268mm/);
  assert.equal(outgoing.generation_parameters.technical_requirements.filter((v) => v.surface_mapping).length, 2);
  console.log('PASS save retry and Chinese output');
  await row().locator('[data-role="delete-technical-requirement"]').click(); await saved();
  assert.equal((await surfaces()).length, 0);
  assert.equal(await page.evaluate(() => state.review.technical_requirements.some((v) => v.requirement_id === 'surface-ocr')), false);
  await root.locator('[data-action="undo-technical-requirement-delete"]').click(); await saved(); await row().waitFor(); assert.equal((await surfaces()).length, 2);
  await open('b'); await open('a'); assert.equal(await select().inputValue(), id('电镀-镀彩锌')); assert.match(await body().inputValue(), /保持清洁/);
  console.log('PASS delete undo and reopen');
  // A conflict that changes only the company choice still requires a decision.
  conflict = (m) => { for (const v of m.review.technical_requirements.filter((v) => v.surface_mapping)) v.surface_mapping.selection_mode = 'none'; };
  await body().fill('表面处理：' + fixture.chinese + ' 人工确认工艺。'); await body().press('Tab');
  await page.getByRole('dialog').waitFor();
  // Each preserved source has its own CAS decision under the existing save flow.
  for (let i = 0; i < 2; i++) await page.getByRole('button', { name: '保留我的值并保存' }).click();
  await saved(); console.log('PASS grouped source conflict choices');
  assert.match(await body().inputValue(), /人工确认工艺/);
  await confirm().click(); await saved();
  // Historical multiple IDs remain intact on render, then become one on edit.
  await page.evaluate((ids) => { for (const v of state.review.technical_requirements.filter((v) => v.surface_mapping)) v.surface_mapping.catalog_ids = ids; updateLatestReviewMessage(); }, [id('电镀-镀彩锌'), id('上油')]);
  assert.equal(await row().locator('[data-role="surface-company-select"]').count(), 1);
  assert.equal((await surfaces())[0].surface_mapping.catalog_ids.length, 2);
  await edit('表面处理：清洗后上油，保持清洁。');
  assert.equal(await select().inputValue(), id('清洗'));
  assert.equal((await surfaces()).every((v) => v.surface_mapping.catalog_ids.length === 1), true);
  await select().selectOption(id('发黑')); await saved(); assert.match(await body().inputValue(), /发黑后上油/);
  await edit('表面处理：' + fixture.chinese + ' 人工确认工艺。'); await confirm().click(); await saved();
  await row().scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(output, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 1600 }); await row().scrollIntoViewIfNeeded();
  assert.equal(await select().isVisible(), true); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'mobile.png') });
  // Clearing the body keeps the source evidence and excludes the row from SW.
  await edit(''); assert.equal(await confirm().isDisabled(), true);
  assert.equal((await page.evaluate(() => makeGenerationParameterPackage())).generation_parameters.technical_requirements.some((v) => v.surface_mapping), false);
  assert.equal((await surfaces())[0].original_content, fixture.source_review.technical_requirements[0].original_content);
  assert.equal(await root.locator('.requirement-row[data-requirement-id="surface-ocr"]').count(), 0);
  holdSave = true; await body().fill('表面处理：' + fixture.chinese); await body().press('Tab');
  const deadline = Date.now() + 30000;
  while (!releaseSave && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(typeof releaseSave, 'function', 'Late-response mock must receive the pending save');
  await page.evaluate((r) => { state.lastJob = { job_id: 'b', review_revision: 99 }; state.review = normalizeReview(r); }, models.get('b').review);
  releaseSave(); await page.waitForFunction(() => !state.reviewPersistenceSaving);
  assert.equal(await page.evaluate(() => state.lastJob.review_revision), 99);
  assert.equal(await page.evaluate(() => state.review.technical_requirements[0].content), fixture.chinese);
  assert.equal(requests.some((v) => /translate|recognition.*retry/.test(v)), false, 'No model calls from local editing');
  assert.deepEqual(errors, []);
  console.log('Company surface browser: catalog retry/search, linked grouped edits, conflicts, explicit none, single/bulk confirmation, save/retry/CAS, delete/undo, reopen, Chinese SW text, focus and responsive layout passed');
} catch (error) { console.error(error); throw error; }
finally { releaseSave?.(); await browser.close(); server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); }
