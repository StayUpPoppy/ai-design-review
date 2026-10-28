import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };
const cases = JSON.parse(execFileSync('.venv/Scripts/python.exe', ['scripts/test_solidworks_export.py', '--json'], { encoding: 'utf8', env, maxBuffer: 8 * 1024 * 1024 }));
const catalog = JSON.parse(fs.readFileSync('config/compression_material_catalog.json', 'utf8'));
const base = structuredClone(cases[0].review);
base.drawing_summary.drawing_name = '客户确认测试图纸'; base.drawing_summary.drawing_no = '00123-A';
base.spring_parameters.total_coils = { value: 10.5, unit: 'turns', source: ['human_edited'], need_human_review: false };
base.spring_parameters.active_coils = { value: 8.25, unit: 'turns', source: ['human_edited'], need_human_review: true };
base.spring_parameters.surface_roughness_ra = { value: null, unit: 'μm', source: [], need_human_review: true };
base.spring_parameters.outer_diameter = { value: 9, unit: 'mm', tolerance_upper: .1, tolerance_lower: 0, need_human_review: true };
base.spring_parameters.load_points = [{ load_point_id: 'zero', label: 'F1', height: 20, force: 0, height_unit: 'mm', force_unit: 'N', load_tolerance_percent: 10, need_human_review: true }];
base.technical_requirements = [{ requirement_id: 'heat', type: 'heat_treatment', content: '热处理：消除应力退火', need_human_review: false },
  { requirement_id: 'note', type: 'other', content: '其他要求：待客户确认 <script>window.reportInjected=true</script>', translation_status: 'translated', need_human_review: true }];
base.standardization_results = []; base.change_history = [];
const optionalAdvanced = ['controlled_diameter_field', 'body_length', 'end_coils', 'straightness', 'permanent_set_limit'];
const fixedAdvanced = ['support_coils', 'pitch', 'spring_rate', 'perpendicularity'];
const specializedAdvanced = ['diameter_accuracy_grade', 'free_length_accuracy_grade', 'load_accuracy_grade', 'stiffness_accuracy_grade'];
for (const field of optionalAdvanced) base.spring_parameters[field] = { value: '  ', source: ['qwen'], evidence: '有来源说明但未识别数值', default_source: 'company_default', need_human_review: true };
for (const field of specializedAdvanced) base.spring_parameters[field] = { value: '1级', source: ['human_confirmed'], need_human_review: false, confirmation_snapshot: { value: '1级' } };
const models = new Map(['a', 'b'].map(id => [id, { review: structuredClone(base), revision: 1 }]));
models.get('b').review.drawing_summary.drawing_name = '第二个订单';
const frontend = path.resolve('frontend'), out = path.resolve('outputs/confirmation-sheet-qa'); fs.mkdirSync(out, { recursive: true });
const logoPng = fs.readFileSync('frontend/assets/incospring-logo.png');
const server = http.createServer((req, res) => {
  const file = path.resolve(frontend, new URL(req.url, 'http://localhost').pathname.slice(1) || 'index.html');
  if (!file.startsWith(frontend + path.sep) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html'); res.end(fs.readFileSync(file));
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
let failSave = false, holdAssessment = false, failAssessment = false, releaseAssessment, writes = 0, remoteModels = 0;
let logoMode = 'fail', logoRequests = 0, releaseLogo;
const errors = [];
page.on('pageerror', e => { errors.push(e.stack); console.error(e.message); });
await page.route('**/assets/incospring-logo.png*', async route => {
  logoRequests++;
  const mode = logoMode;
  if (mode === 'fail') return route.fulfill({ status: 503, body: '模拟图片加载失败' });
  if (mode === 'hold') await new Promise(resolve => { releaseLogo = resolve; });
  return route.fulfill({ contentType: 'image/png', body: mode === 'corrupt' ? Buffer.concat([logoPng.subarray(0, 8), Buffer.from('bad image')]) : logoPng });
});
await page.route('**/api/**', async route => {
  const req = route.request(), api = new URL(req.url()).pathname;
  if (api === '/api/session') return route.fulfill({ json: { identity: { user_id: 'sheet-browser', username: 'test-user', real_name: '测试工程师' } } });
  if (api === '/api/material-catalog') return route.fulfill({ json: catalog });
  if (api === '/api/reviews') return route.fulfill({ json: { reviews: [...models].map(([id, m]) => ({ job_id: id, drawing_name: m.review.drawing_summary.drawing_name, revision: m.revision, recognition_status: 'completed' })) } });
  if (api === '/api/reviews/reasonableness') {
    if (holdAssessment) { holdAssessment = false; await new Promise(resolve => { releaseAssessment = resolve; }); }
    if (failAssessment) return route.fulfill({ status: 503, json: { detail: '模拟诊断不可用' } });
    const input = req.postDataJSON();
    const script = "import sys,json;sys.path.insert(0,'src');from ai_design_review.spring_feasibility import assess_parameter_reasonableness;b=json.load(sys.stdin);print(json.dumps({'parameter_reasonableness':assess_parameter_reasonableness(b['review'],based_on_revision=b.get('review_revision'))},ensure_ascii=False))";
    return route.fulfill({ body: execFileSync('.venv/Scripts/python.exe', ['-c', script], { input: JSON.stringify(input), encoding: 'utf8', env }), contentType: 'application/json' });
  }
  const match = api.match(/^\/api\/reviews\/(a|b)(?:\/(.*))?$/);
  if (match) {
    const [, id, action] = match, m = models.get(id);
    if (!action) {
      if (req.method() === 'PATCH') {
        writes++;
        if (failSave) return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
        const input = req.postDataJSON(); m.review = input.review; m.revision++;
        return route.fulfill({ json: { review_revision: m.revision, events: input.events } });
      }
      return route.fulfill({ json: { ...m.review, job_id: id, review_revision: m.revision } });
    }
    if (action === 'generation-jobs') return route.fulfill({ json: { generation_jobs: [] } });
    if (action === 'annotations') return route.fulfill({ json: { pages: [], annotations: [] } });
    if (action === 'changes') return route.fulfill({ json: { events: [] } });
  }
  if (/translat|standardize|generation-jobs$/.test(api) && req.method() === 'POST') remoteModels++;
  return route.fulfill({ json: { status: 'ok', recognition_queue_runtime: { status: 'available' } } });
});
const dialog = page.locator('.confirmation-sheet-preview'), frame = () => page.frameLocator('.confirmation-sheet-preview iframe');
async function saved() { await page.evaluate(() => flushReviewPersistence()); }
async function openReview(id) { await page.evaluate(async id => { await openPersistedReview(id); renderCompareOverlay(); }, id); await page.locator('[data-compare-tab="parameters"]').click(); await saved(); }
async function openSheet() { await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').click(); await dialog.waitFor(); await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled); }
async function snapshot() { return page.evaluate(() => JSON.stringify({ review: state.review, edit: state.reviewEditSerial, events: state.pendingReviewAuditEvents })); }
try {
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => state.identityReady && state.materialCatalog.items.length);
  await openReview('a');
  const logoError = 'Logo加载失败，请点击“刷新预览”重试。';
  await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').click();
  await dialog.getByText(logoError, { exact: true }).waitFor();
  assert.equal(await dialog.locator('[data-sheet-action="print"]').isDisabled(), true);
  logoMode = 'corrupt'; await dialog.locator('[data-sheet-action="refresh"]').click();
  await dialog.getByText(logoError, { exact: true }).waitFor();
  assert.equal(await dialog.locator('[data-sheet-action="print"]').isDisabled(), true, 'undecodable PNG never becomes printable');
  logoMode = 'hold'; await dialog.locator('[data-sheet-action="refresh"]').click();
  for (let i = 0; !releaseLogo && i < 200; i++) await page.waitForTimeout(10);
  assert.equal(typeof releaseLogo, 'function');
  assert.equal(await dialog.locator('[data-sheet-action="print"]').isDisabled(), true, 'pending image stays unprintable');
  await page.evaluate(async () => { await openPersistedReview('b'); });
  await dialog.waitFor({ state: 'detached' });
  await openReview('b');
  await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').click();
  logoMode = 'ok'; releaseLogo();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.match(await frame().locator('body').innerText(), /第二个订单/);
  assert.equal(await frame().locator('img[data-brand-logo]').evaluate(el => el.complete && el.naturalWidth > 0), true);
  assert.equal(logoRequests, 3, 'failed requests retry; a pending asset is shared safely across orders');
  await dialog.locator('[data-sheet-action="back"]').click();
  await openReview('a');
  await page.waitForTimeout(550); await saved();
  const before = await snapshot(), count = writes;
  const advancedPanel = page.locator('.compare-overlay .advanced-parameters');
  assert.equal(await advancedPanel.evaluate(el => el.open), false);
  await advancedPanel.locator('summary').click();
  for (const field of fixedAdvanced) assert.equal(await advancedPanel.locator(`[data-field="${field}"]`).count(), 1);
  for (const field of [...optionalAdvanced, ...specializedAdvanced]) assert.equal(await advancedPanel.locator(`[data-field="${field}"]`).count(), 0);
  await advancedPanel.screenshot({ path: path.join(out, 'advanced-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await advancedPanel.screenshot({ path: path.join(out, 'advanced-mobile.png') });
  assert.equal(await advancedPanel.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const planFields = await page.evaluate(() => { const plan = buildSafeConfirmationPlan(state.review); return [...plan.items, ...plan.skipped].map(item => item.field); });
  for (const field of [...optionalAdvanced, ...specializedAdvanced]) assert.equal(planFields.includes(field), false, `${field} excluded from visible bulk confirmation`);
  await advancedPanel.locator('summary').click(); await saved();
  assert.equal(writes, count, 'opening and closing advanced parameters never saves');
  assert.equal(await snapshot(), before, 'disclosure and filtering preserve data and confirmations');
  await openSheet();
  const brand = await frame().locator('.brand-header').evaluate(el => {
    const img = el.querySelector('img'), title = el.querySelector('h1');
    const rect = el.getBoundingClientRect(), text = title.getBoundingClientRect();
    return { width: parseFloat(getComputedStyle(img).width), height: parseFloat(getComputedStyle(img).height),
      naturalWidth: img.naturalWidth, naturalHeight: img.naturalHeight, centered: Math.abs((rect.left + rect.right - text.left - text.right) / 2) < 1 };
  });
  assert.ok(Math.abs(brand.width - 38 * 96 / 25.4) < .1);
  assert.ok(Math.abs(brand.width / brand.height - brand.naturalWidth / brand.naturalHeight) < .01, 'original aspect ratio');
  assert.equal(brand.centered, true, 'title stays centered on the sheet');
  await frame().getByText('弹簧参数确认单', { exact: true }).waitFor();
  const content = await frame().locator('body').innerText();
  assert.match(content, /00123-A/); assert.match(content, /测试工程师/); assert.match(content, /10\.5/); assert.match(content, /8\.25/);
  assert.match(content, /0 N/); assert.match(content, /±10%/); assert.match(content, /\+0.1 \/ 0/);
  assert.match(content, /待补充/); assert.match(content, /Ra 12.5 μm/); assert.match(content, /Ra 6.3 μm/);
  assert.doesNotMatch(content, /审图修订|已确认|本单不代表全部参数/);
  assert.equal(await frame().getByRole('columnheader', { name: '状态', exact: true }).count(), 0);
  assert.equal(await frame().locator('input').count(), 0, 'customer boxes are static empty squares');
  const printRows = await frame().locator('tbody > tr').count();
  assert.equal(await frame().locator('.paper-check').count(), printRows * 2);
  assert.equal(await frame().getByRole('heading', { name: '输入参数', exact: true }).count(), 1);
  assert.doesNotMatch(content, /基础参数|高级参数/);
  assert.equal(await dialog.locator('legend').filter({ hasText: /^输入参数$/ }).count(), 1);
  assert.equal(await dialog.locator('legend').filter({ hasText: /^(基础参数|高级参数)$/ }).count(), 0);
  assert.doesNotMatch(content, /直径精度等级|自由高度精度等级|载荷精度等级|刚度精度等级/);
  for (const field of optionalAdvanced) assert.equal(await dialog.locator(`input[data-sheet-id="param:${field}"]`).count(), 0);
  assert.match(content, /理论刚度/); assert.match(content, /单件重量/);
  assert.doesNotMatch(content, /名义压并高度|压并高度上限参考|应力采用高度/);
  assert.equal(await frame().getByRole('cell', { name: '压并高度', exact: true }).count(), 1);
  assert.match(await frame().getByRole('row').filter({ has: frame().getByRole('cell', { name: '压并高度', exact: true }) }).innerText(), /估算|无法计算/);
  for (const key of ['reference_solid_height_limit', 'solid_height_used']) assert.equal(await dialog.locator(`input[data-sheet-id="calculation:${key}"]`).count(), 0);
  assert.match(content, /工作应力（F1）/);
  const advanced = await page.evaluate(() => getParameterFieldGroups(state.review.spring_parameters, state.review).advanced);
  for (const field of advanced) assert.equal(await dialog.locator(`input[data-sheet-id="param:${field}"]`).isChecked(), true, `visible advanced ${field} selected`);
  const inputChoices = dialog.getByRole('group', { name: '输入参数', exact: true });
  const expectedRows = await page.evaluate(() => getParameterFields(state.review.spring_parameters, state.review).filter(field => COMPRESSION_CORE_PARAMETER_FIELDS.has(field)).map(field => `param:${field}`));
  const rowIds = [...expectedRows, ...advanced.map(field => `param:${field}`)];
  assert.deepEqual(await inputChoices.locator('input').evaluateAll(inputs => inputs.map(input => input.dataset.sheetId)), rowIds);
  assert.equal(new Set(rowIds).size, rowIds.length, 'merged input parameters have no duplicate rows');
  const inputRows = await frame().getByRole('heading', { name: '输入参数', exact: true }).locator('..').locator('tbody > tr').count();
  assert.equal(inputRows, rowIds.length, 'one continuous table contains both original groups');
  assert.equal(await frame().getByRole('cell', { name: '垂直度', exact: true }).count(), 1);
  const calculationChecks = await dialog.locator('input[data-sheet-id^="calculation:"]').count();
  assert.equal(calculationChecks, 10, 'nine customer-facing metrics and one work stress');
  await dialog.locator('input[data-sheet-id="calculation:theoretical_spring_rate"]').uncheck();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await frame().getByRole('cell', { name: '理论刚度', exact: true }).count(), 0);
  await dialog.locator('input[data-sheet-id="calculation:theoretical_spring_rate"]').check();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await frame().locator('script').count(), 0);
  assert.equal(await frame().locator('img').count(), 1, 'only the fixed branding image is permitted');
  assert.equal(await frame().locator('img').getAttribute('alt'), 'IncoSpring');
  assert.equal(await snapshot(), before, 'preview does not mutate review, confirmation or audit');
  assert.equal(writes, count, 'clean preview does not save');
  const choice = dialog.locator('input[data-sheet-id="param:total_coils"]');
  await choice.uncheck(); await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await frame().locator('td').filter({ hasText: /^总圈数$/ }).count(), 0);
  const advancedChoice = dialog.locator('input[data-sheet-id="param:perpendicularity"]');
  await advancedChoice.uncheck();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  await dialog.locator('[data-sheet-action="refresh"]').click();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await choice.isChecked(), false, 'refresh preserves a deselected original basic row');
  assert.equal(await advancedChoice.isChecked(), false, 'refresh preserves a deselected original advanced row');
  assert.equal(await frame().getByRole('cell', { name: '垂直度', exact: true }).count(), 0);
  await advancedChoice.check(); await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  await choice.check(); await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  await choice.uncheck(); await choice.check();
  await advancedChoice.uncheck(); await advancedChoice.check();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await frame().getByRole('cell', { name: '垂直度', exact: true }).count(), 1, 'rapid rerenders retain the latest selection');
  // Print and cancel are deliberately indistinguishable: both leave the preview reusable.
  await page.evaluate(() => { const win = document.querySelector('.confirmation-sheet-preview iframe').contentWindow; window.printCalls = 0; win.print = () => { window.printCalls++; win.dispatchEvent(new Event('afterprint')); }; });
  await dialog.locator('[data-sheet-action="print"]').click(); await dialog.locator('[data-sheet-action="print"]').click();
  assert.equal(await page.evaluate(() => window.printCalls), 2); assert.equal(writes, count);
  assert.equal(await dialog.locator('[data-sheet-action="print"]').evaluate(el => getComputedStyle(el).color), 'rgb(255, 255, 255)', 'hover keeps the print button text visible');
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(out, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  // Collapse options on mobile; users can expand them without losing choices.
  await dialog.locator('summary').click();
  await page.screenshot({ path: path.join(out, 'mobile.png') });
  assert.equal(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
  await dialog.locator('[data-sheet-action="back"]').click();
  assert.equal(await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').evaluate(el => document.activeElement === el), true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  // An actual unsaved input must be saved successfully before a snapshot exists.
  failSave = true;
  await advancedPanel.locator('summary').click();
  await advancedPanel.locator('[data-field="perpendicularity"] [data-role="value"]').fill('0.3');
  await page.locator('.compare-overlay [data-field="free_length"][data-kind="param"] [data-role="value"]').fill('26');
  await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').click();
  await dialog.getByText(/当前修改尚未保存/).waitFor();
  assert.equal(await dialog.locator('[data-sheet-action="print"]').isDisabled(), true);
  failSave = false; await dialog.locator('[data-sheet-action="refresh"]').click();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(models.get('a').review.spring_parameters.perpendicularity.value, .3, 'new advanced input survives save failure/retry');
  await page.evaluate(() => { state.review.spring_parameters.free_length.value = 27; state.reviewEditSerial++; });
  await dialog.getByText('参数已更新，请刷新预览。', { exact: true }).waitFor();
  assert.equal(await dialog.locator('[data-sheet-action="print"]').isDisabled(), true);
  await page.evaluate(() => renderCompareOverlay());
  await dialog.locator('[data-sheet-action="back"]').click();
  assert.equal(await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').evaluate(el => document.activeElement === el), true, 'focus survives an editor rerender');
  // Material properties are calculation inputs, even without a parameter edit.
  await openSheet();
  await page.evaluate(() => { state.materialCatalog = { ...state.materialCatalog, version: 'browser-updated-catalog' }; });
  await dialog.getByText('参数已更新，请刷新预览。', { exact: true }).waitFor();
  assert.equal(await dialog.locator('[data-sheet-action="print"]').isDisabled(), true);
  await dialog.locator('[data-sheet-action="refresh"]').click();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  await dialog.locator('[data-sheet-action="back"]').click();
  // A late assessment cannot open/repopulate a report for another order.
  await openReview('a');
  assert.equal(await page.locator('.compare-overlay [data-field="perpendicularity"] [data-role="value"]').inputValue(), '0.3', 'advanced input is restored on reopening');
  for (const field of optionalAdvanced) assert.equal(await advancedPanel.locator(`[data-field="${field}"]`).count(), 0);
  holdAssessment = true; await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').click();
  for (let i = 0; !releaseAssessment && i < 200; i++) await page.waitForTimeout(10);
  assert.equal(typeof releaseAssessment, 'function');
  await page.evaluate(async () => { await openPersistedReview('b'); });
  releaseAssessment(); await dialog.waitFor({ state: 'detached' });
  // Build a long local/spec report, still entirely read-only, and capture actual print pages.
  await page.evaluate(() => {
    state.lastJob = null; state.reviewNavigationSerial++;
    state.review.record_kind = 'variant'; state.review.multi_spec_origin = { code: 'FTA-28/103-274', order: 13 };
    state.review.technical_requirements.push({ requirement_id: 'long', type: 'other', content: '长技术要求：' + '本项需由客户确认，保留厚度≥15 μm和工序顺序。'.repeat(110), need_human_review: true });
    renderCompareOverlay();
  });
  await page.locator('[data-compare-tab="parameters"]').click(); await openSheet();
  assert.match(await frame().locator('body').innerText(), /本地数据/);
  assert.match(await frame().locator('body').innerText(), /FTA-28\/103-274/);
  assert.equal(await frame().getByRole('heading', { name: '输入参数', exact: true }).count(), 1);
  assert.doesNotMatch(await frame().locator('body').innerText(), /基础参数|高级参数/);
  const html = await page.locator('.confirmation-sheet-preview iframe').getAttribute('srcdoc');
  fs.writeFileSync(path.join(out, 'print.html'), html);
  const printPage = await browser.newPage(); await printPage.setContent(html);
  await printPage.evaluate(() => Promise.all([document.fonts.ready, ...[...document.images].map(img => img.decode())]));
  await printPage.pdf({ path: path.join(out, 'confirmation-sheet.pdf'), preferCSSPageSize: true, printBackground: true });
  await printPage.emulateMedia({ media: 'print' });
  assert.equal(await printPage.locator('.brand-header').evaluate(el => getComputedStyle(el).display), 'none', 'print uses repeating page-margin headers instead of a duplicate DOM header');
  await printPage.pdf({ path: path.join(out, 'confirmation-sheet-no-background.pdf'), preferCSSPageSize: true, printBackground: false });
  await printPage.close();
  const localSnapshot = await snapshot(), localWrites = writes;
  failAssessment = true; await dialog.locator('[data-sheet-action="refresh"]').click();
  await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled);
  assert.match(await frame().locator('body').innerText(), /本次未能更新合理性检查/);
  assert.equal(await snapshot(), localSnapshot); assert.equal(writes, localWrites);
  await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'detached' });
  // Child records share visibility; moving to the tolerance box must not remove
  // the row, while leaving a truly cleared optional row hides only that row.
  await page.evaluate(() => {
    Object.assign(state.review.spring_parameters, {
      body_length: { value: 10, unit: 'mm', source: ['human_edited'], need_human_review: true },
      controlled_diameter_field: { value: 'inner_diameter', source: ['qwen'], need_human_review: true },
      end_coils: { value: 0, unit: 'turns', need_human_review: true },
      straightness: { value: null, tolerance_upper: .1, unit: 'mm', need_human_review: true },
      permanent_set_limit: { value: 'invalid', unit: 'mm', derived_value_stale: true, need_human_review: true },
      legacy_value: { value: '旧参数', need_human_review: true },
      legacy_empty: { evidence: '只有旧说明' },
    });
    openCompareOverlay();
  });
  await page.locator('[data-compare-tab="parameters"]').click();
  if (!await advancedPanel.evaluate(el => el.open)) await advancedPanel.locator('summary').click();
  for (const field of [...optionalAdvanced, 'legacy_value']) assert.equal(await advancedPanel.locator(`[data-field="${field}"]`).count(), 1);
  assert.equal(await advancedPanel.locator('[data-field="legacy_empty"]').count(), 0);
  await openSheet();
  for (const field of optionalAdvanced) assert.equal(await dialog.locator(`input[data-sheet-id="param:${field}"]`).count(), 1);
  assert.match(await frame().locator('body').innerText(), /内径/);
  await dialog.locator('[data-sheet-action="back"]').click();
  const bodyRow = advancedPanel.locator('[data-field="body_length"]');
  await bodyRow.locator('[data-role="value"]').fill('');
  assert.equal(await bodyRow.count(), 1);
  assert.equal(await bodyRow.locator('[data-role="value"]').evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Tab');
  assert.equal(await bodyRow.count(), 1, 'moving inside the row does not hide it');
  await bodyRow.locator('[data-role="tolerance"]').fill('+0.2/0');
  await advancedPanel.locator('[data-field="perpendicularity"] [data-role="value"]').focus();
  assert.equal(await bodyRow.count(), 1, 'tolerance-only row stays visible');
  await bodyRow.locator('[data-role="tolerance"]').fill('');
  assert.equal(await bodyRow.count(), 1, 'editing an empty row keeps focus');
  const nextInput = advancedPanel.locator('[data-field="perpendicularity"] [data-role="value"]');
  await nextInput.focus();
  await bodyRow.waitFor({ state: 'detached' });
  assert.equal(await nextInput.evaluate(el => el === document.activeElement), true);
  assert.equal(await advancedPanel.evaluate(el => el.open), true);
  const hiddenState = await page.evaluate(() => JSON.stringify(state.review.spring_parameters.body_length));
  await openSheet();
  assert.equal(await dialog.locator('input[data-sheet-id="param:body_length"]').count(), 0);
  assert.equal(await page.evaluate(() => JSON.stringify(state.review.spring_parameters.body_length)), hiddenState);
  await dialog.locator('[data-sheet-action="back"]').click();
  await page.evaluate(() => renderCompareOverlay());
  assert.equal(await advancedPanel.locator('[data-field="body_length"]').count(), 0, 'cleared metadata cannot resurrect the row');
  await page.evaluate(() => { state.review.record_kind = 'source'; });
  await page.evaluate(() => confirmationSheetService().open());
  assert.equal(await dialog.count(), 0, 'source records must first open a child');
  assert.equal(remoteModels, 0, 'no model, standardization or SW calls'); assert.deepEqual(errors, []);
  assert.equal(logoRequests, 3, 'successful branding is reused across previews and orders');
  console.log(`Confirmation sheet browser tests passed; screenshots and A4 print PDF: ${out}`);
} finally { await browser.close(); server.close(); }
