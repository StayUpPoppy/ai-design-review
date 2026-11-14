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
base.spring_parameters.support_coils = { value: 1.125, unit: 'turns', source: ['human_edited'], need_human_review: false };
base.spring_parameters.surface_roughness_ra = { value: null, unit: 'μm', source: [], need_human_review: true };
base.spring_parameters.outer_diameter = { value: 9, unit: 'mm', tolerance_upper: .1, tolerance_lower: 0, need_human_review: true };
base.spring_parameters.load_points = [{ load_point_id: 'zero', label: 'F1', height: 20, force: 0, height_unit: 'mm', force_unit: 'N',
  height_tolerance_upper: 2, height_tolerance_lower: -2, load_tolerance_percent: 10, need_human_review: true }];
const noteContent = '其他要求：待客户确认 <script>window.reportInjected=true</script>';
base.technical_requirements = [{ requirement_id: 'heat', type: 'heat_treatment', content: '热处理：消除应力退火', need_human_review: false },
  { requirement_id: 'note', type: 'other', content: noteContent, translation_status: 'translated',
    translation_output_snapshot: { content: noteContent, type: 'other' }, need_human_review: true }];
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
async function openSheet() {
  await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').click(); await dialog.waitFor();
  try { await page.waitForFunction(() => !document.querySelector('[data-sheet-action="print"]').disabled); }
  catch (error) {
    const diagnostic = await page.evaluate(() => ({ message:document.querySelector('.confirmation-sheet-message')?.textContent,
      job:state.lastJob?.job_id, navigation:state.reviewNavigationSerial, edit:state.reviewEditSerial }));
    throw new Error(`Report did not become ready: ${JSON.stringify(diagnostic)}`, {cause:error});
  }
}
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
  // Exercise the production projection with detached reviews, including legacy
  // defaults and conflicts. These builds never modify the open order.
  const healthy = await page.evaluate(async () => {
    const review=structuredClone(state.review), values={material:'SUS304',wire_diameter:2,outer_diameter:20,inner_diameter:16,mean_diameter:18,free_length:36,total_coils:12,active_coils:10,handedness:'右旋',end_type:'两端并紧',end_grinding:'两端磨削',support_coils:1};
    review.spring_parameters=Object.fromEntries(Object.entries(values).map(([field,value])=>[field,{value,source:['qwen_vision'],need_human_review:true,unit:field.includes('diameter')||field==='free_length'?'mm':field.includes('coils')?'turns':''}]));
    Object.assign(review.spring_parameters.mean_diameter,{source:['formula_calculation'],source_fields:['outer_diameter','wire_diameter'],default_source:'legacy-default'});
    review.spring_parameters.load_points=[{load_point_id:'production-f1',label:'F1',height:32,force:0,height_unit:'mm',force_unit:'N',source:['qwen_vision'],need_human_review:true}];
    review.technical_requirements=[{requirement_id:'original-tech',type:'other',content:'两端并紧并磨平，Ra12.5，不制扁。',need_human_review:true},
      {requirement_id:'surface-tech',type:'surface',content:'表面处理：表面处理\n镀锌五彩',need_human_review:true}];
    review.conflicts=[];review.parameter_reasonableness={issues:[]};review.parameter_reasonableness_stale=false;
    window.detachedSheetReview=review;
    return buildConfirmationSheetSnapshot({review,identity:state.identity,revision:1,jobId:'a'});
  });
  assert.equal(healthy.sections.find(section=>section.id==='parameters').rows.length,9);
  assert.equal(healthy.sections.find(section=>section.id==='issues').rows.length,0,'valid pending values and real derived values need no internal confirmation for this report');
  assert.match(healthy.sections.find(section=>section.id==='requirements').rows[0].content,/Ra12.5，不制扁/);
  assert.equal(healthy.sections.find(section=>section.id==='requirements').rows[1].content,'表面处理：镀锌五彩');
  assert.equal(healthy.sections.find(section=>section.id==='loads').rows[0].height,'32 mm');
  const tolerancedHeight=await page.evaluate(async()=>{
    const review=structuredClone(window.detachedSheetReview), point=review.spring_parameters.load_points[0];
    Object.assign(point,{height_unit:'cm',height:3.2,height_tolerance_upper:2,height_tolerance_lower:-2});
    const context={review,identity:state.identity,revision:1,jobId:'a'};
    const valid=await buildConfirmationSheetSnapshot(context);
    point.height_tolerance_input_draft='±5%';
    const invalid=await buildConfirmationSheetSnapshot(context);
    return {valid,invalid};
  });
  assert.equal(tolerancedHeight.valid.sections.find(section=>section.id==='loads').rows[0].height,'3.2 ±0.2 cm');
  const badHeightTolerance=tolerancedHeight.invalid.sections.find(section=>section.id==='issues').rows.flatMap(group=>group.items).find(row=>row.kind==='load');
  assert.ok(badHeightTolerance.messages.some(message=>message.includes('高度公差格式无效')));
  assert.doesNotMatch(badHeightTolerance.current,/±0.2/);
  const provisionalLoads=await page.evaluate(async()=>{
    const review=structuredClone(window.detachedSheetReview);
    const point=review.spring_parameters.load_points[0];
    Object.assign(point,{height:12.4,height_unit:"mm",force:83300,force_unit:"N",need_human_review:true,
      height_relation:{kind:"absolute_height",value:12.4,unit:"mm",verified:false,verification_method:"qwen_provisional",status:"model_pending"}});
    const context={review,identity:state.identity,revision:1,jobId:'a'};
    const draft=await buildConfirmationSheetSnapshot(context);
    point.need_human_review=false;
    const confirmed=await buildConfirmationSheetSnapshot(context);
    return {draft,confirmed};
  });
  assert.doesNotMatch(JSON.stringify(provisionalLoads.draft.sections),/83300/);
  assert.match(JSON.stringify(provisionalLoads.confirmed.sections),/83300/);
  const coilCheck=await page.evaluate(async()=>{
    const review=structuredClone(window.detachedSheetReview);
    review.spring_parameters.total_coils.value=6.5;
    review.spring_parameters.active_coils.value=8;
    const before=JSON.stringify(review),model=await buildConfirmationSheetSnapshot({review,identity:state.identity,revision:1,jobId:'a'});
    return {model,unchanged:JSON.stringify(review)===before};
  });
  const coilIssue=coilCheck.model.sections.find(section=>section.id==='issues').rows.find(group=>group.items.some(row=>row.field==='total_coils'));
  assert.ok(coilIssue.reasons.includes('有效圈数不能大于总圈数。'),'the production projection retains the reason instead of replacing it with the question');
  assert.ok(coilIssue.questions.includes('请确认总圈数与有效圈数的正确数值。'));
  assert.doesNotMatch(coilIssue.questions.join('；'),/补充端部形式/);
  assert.equal(coilCheck.unchanged,true);
  failAssessment=true;
  const legacyIssues=await page.evaluate(async()=>{
    const results=[];
    for(const content of [{message:'外径标注存在两个不同数值。'},{customer_question:'请明确外径采用的数值。'}]){
      const review=structuredClone(window.detachedSheetReview);
      review.parameter_reasonableness={issues:[{severity:'warning',category:'geometry',fields:['outer_diameter'],...content}]};
      results.push(await buildConfirmationSheetSnapshot({review,identity:state.identity,revision:1,jobId:'a'}));
    }
    return results.map(model=>model.sections.find(section=>section.id==='issues').rows[0]);
  });
  assert.deepEqual(legacyIssues[0].reasons,['外径标注存在两个不同数值。']);
  assert.deepEqual(legacyIssues[0].questions,['请确认外径的正确内容。']);
  assert.deepEqual(legacyIssues[1].reasons,[],'a question-only record never invents a reason');
  assert.deepEqual(legacyIssues[1].questions,['请明确外径采用的数值。']);
  const problematic = await page.evaluate(async () => {
    const review=structuredClone(window.detachedSheetReview),params=review.spring_parameters;
    params.wire_diameter.value=0;params.free_length.value=null;params.inner_diameter.value=null;
    params.mean_diameter={value:23,source:['solidworks_protocol_default'],default_source:'protocol',need_human_review:true};
    for(const field of ['surface_roughness_ra','end_type','end_grinding','flattening'])params[field]={value:'invalid',value_conflict:true,customer_question:'隐藏字段专属问题'};
    review.conflicts=[{field:'load_points.F1.force',values:[0,20],need_human_review:true}];
    review.parameter_reasonableness={issues:[{severity:'blocked',category:'geometry',fields:['end_type'],message:'隐藏字段诊断'},
      {severity:'needs_input',category:'missing_context',fields:['active_coils'],message:'缺少计算条件'},
      {severity:'warning',rule_id:'FORMULA-CHECK',fields:['total_coils'],message:'未采用公式建议'}]};
    const before=JSON.stringify(review),model=await buildConfirmationSheetSnapshot({review,identity:state.identity,revision:1,jobId:'a'});
    return {model,unchanged:JSON.stringify(review)===before};
  });
  const issueSources=problematic.model.sections.find(section=>section.id==='issues').rows.flatMap(group=>group.items);
  assert.deepEqual(issueSources.map(row=>row.field),['wire_diameter','free_length','load_points.F1']);
  assert.ok(issueSources.find(row=>row.field==='load_points.F1').messages.some(message=>message.includes('载荷标注不一致')));
  assert.ok(!problematic.model.sections.find(section=>section.id==='parameters').rows.some(row=>['inner_diameter','mean_diameter'].includes(row.field)),'blank optional and unadopted defaults do not become customer facts');
  assert.equal(problematic.unchanged,true);
  assert.match(problematic.model.notice,/本次未能更新合理性检查/);
  const defaultRisk = await page.evaluate(async () => {
    const review=structuredClone(window.detachedSheetReview);
    review.spring_parameters.wire_diameter={value:100,source:['system_default'],need_human_review:true};
    review.parameter_reasonableness={issues:[{severity:'blocked',category:'geometry',fields:['wire_diameter','outer_diameter'],message:'默认值造成的几何矛盾'}]};
    return buildConfirmationSheetSnapshot({review,identity:state.identity,revision:1,jobId:'a'});
  });
  assert.equal(defaultRisk.sections.find(section=>section.id==='issues').rows.length,1);
  assert.equal(defaultRisk.sections.find(section=>section.id==='issues').rows[0].items[0].field,'wire_diameter');
  assert.ok(defaultRisk.sections.find(section=>section.id==='parameters').rows.some(row=>row.field==='outer_diameter'));
  const invalidUnits = await page.evaluate(async () => {
    const review=structuredClone(window.detachedSheetReview);
    review.spring_parameters.mean_diameter.unit='pixels';
    review.spring_parameters.load_points[0].force_unit='unknown-force';
    return buildConfirmationSheetSnapshot({review,identity:state.identity,revision:1,jobId:'a'});
  });
  assert.deepEqual(invalidUnits.sections.find(section=>section.id==='issues').rows.flatMap(group=>group.items).map(row=>row.field),['mean_diameter','load_points.F1'],'invalid units remain customer issues even if diagnostics are unavailable');
  failAssessment=false;
  assert.equal(await snapshot(),before); assert.equal(writes,count);
  const advancedPanel = page.locator('.compare-overlay .advanced-parameters');
  assert.equal(await advancedPanel.evaluate(el => el.open), false);
  await advancedPanel.locator('summary').click();
  for (const field of fixedAdvanced) assert.equal(await advancedPanel.locator(`[data-field="${field}"]`).count(), 1);
  for (const field of [...optionalAdvanced, ...specializedAdvanced]) assert.equal(await advancedPanel.locator(`[data-field="${field}"]`).count(), 0);
  await advancedPanel.screenshot({ path: path.join(out, 'advanced-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => focusMissingStandardizationField('solid_height'));
  const mobileHeightRow = advancedPanel.locator('[data-kind="param"][data-field="solid_height"]');
  await page.waitForFunction(() => document.activeElement?.closest('[data-kind="param"][data-field="solid_height"]'));
  await mobileHeightRow.screenshot({ path: path.join(out, 'advanced-mobile.png') });
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
  assert.match(content,/00123-A/); assert.match(content,/测试工程师/); assert.match(content,/10\.5/); assert.match(content,/8\.25/);
  assert.match(content,/0 N/); assert.match(content,/±10%/); assert.match(content,/\+0.1 \/ 0/);
  assert.match(content,/高度 20 ±2 mm/,'a valid height tolerance stays with the height in an abnormal load row');
  assert.doesNotMatch(content,/审图修订|【确认】|【RFI|RFI-\d|设计校核结果|理论刚度|单件重量|表面粗糙度|名义压并高度/);
  assert.equal(await frame().locator('input,.paper-check,script').count(),0);
  assert.ok(await frame().locator('.parameter-report-table').count()===1);
  assert.equal(await frame().getByRole('columnheader',{name:'状态',exact:true}).count(),0);
  assert.equal(await frame().getByRole('heading',{name:'最终参数',exact:false}).count(),1);
  assert.equal(await frame().locator('.brand-header h1').evaluate(el=>getComputedStyle(el).fontSize),'18.6667px');
  for(const field of [...optionalAdvanced,...specializedAdvanced,...fixedAdvanced,'surface_roughness_ra','end_type','end_grinding','flattening','standard_no','accuracy_grade'])
    assert.equal(await dialog.locator(`input[data-sheet-id="param:${field}"]`).count(),0,`${field} cannot leak through report choices`);
  assert.equal(await dialog.locator('input[data-sheet-id^="calculation:"]').count(),0);
  assert.equal(await frame().locator('.parameter-report-table [data-report-row="param:active_coils"]').count(),1,`valid pending values are customer parameters, not automatic exceptions: ${content}`);
  assert.equal(await frame().locator('[data-report-row="technical:note"]').count(),1,'abnormal original requirement appears once');
  assert.equal(await frame().locator('.issue-reply').count()>0,true);
  const repliesFit=()=>frame().locator('.issue-reply').evaluateAll(rows=>rows.every(row=>{
    const line=row.querySelector('.issue-reply-line');
    return row.textContent==='客户回复：' && row.querySelectorAll('.issue-reply-line').length===1 && line.offsetWidth>100 && getComputedStyle(line).borderBottomStyle==='solid' && row.offsetHeight<=parseFloat(getComputedStyle(row).lineHeight)+2;
  }));
  assert.equal(await repliesFit(),true,'desktop: all issue types use one continuous reply line');
  assert.match(content,/F1 的试验高度不能大于自由长度/,'the customer sees the actual load error as well as the clarification request');
  assert.equal(await frame().locator('img').count(),1);
  assert.equal(await frame().locator('img').getAttribute('alt'),'IncoSpring');
  assert.equal(await snapshot(),before,'preview preserves the active review, confirmations and audit');
  assert.equal(writes,count,'clean preview never saves');
  const choice=dialog.locator('input[data-sheet-id="param:total_coils"]');
  await choice.uncheck(); await page.waitForFunction(()=>!document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await frame().locator('[data-report-row="param:total_coils"]').count(),0);
  await page.evaluate(()=>{state.review.spring_parameters.total_coils.value_conflict=true;state.reviewEditSerial++;});
  await dialog.locator('[data-sheet-action="refresh"]').click();
  await page.waitForFunction(()=>!document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await choice.isChecked(),false,'normal -> abnormal keeps the deselected source ID');
  assert.equal(await choice.locator('xpath=ancestor::fieldset').locator('legend').innerText(),'待客户澄清事项');
  assert.equal(await frame().locator('[data-report-row="param:total_coils"]').count(),0);
  await page.evaluate(()=>{delete state.review.spring_parameters.total_coils.value_conflict;state.reviewEditSerial++;});
  await dialog.locator('[data-sheet-action="refresh"]').click();
  await page.waitForFunction(()=>!document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await choice.isChecked(),false,'abnormal -> normal never silently reselects');
  await choice.check(); await choice.uncheck(); await choice.check();
  await page.waitForFunction(()=>!document.querySelector('[data-sheet-action="print"]').disabled);
  assert.equal(await frame().locator('[data-report-row="param:total_coils"]').count(),1);
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
  assert.equal(await repliesFit(),true,'narrow screen: reply lines stay on one line');
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
  assert.equal(await frame().getByRole('heading', { name: /最终参数/ }).count(), 1);
  assert.doesNotMatch(await frame().locator('body').innerText(), /基础参数|高级参数/);
  const html = await page.locator('.confirmation-sheet-preview iframe').evaluate(el=>el.contentDocument.documentElement.outerHTML);
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
  assert.match(await dialog.locator('.confirmation-sheet-message').innerText(), /本次未能更新合理性检查/);
  assert.doesNotMatch(await frame().locator('body').innerText(), /本次未能更新合理性检查/);
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
  for (const field of optionalAdvanced) assert.equal(await dialog.locator(`input[data-sheet-id="param:${field}"]`).count(), 0);
  assert.doesNotMatch(await frame().locator('body').innerText(), /受控直径/);
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
