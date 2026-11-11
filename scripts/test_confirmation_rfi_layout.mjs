// Offline A4 acceptance: normal values, merged customer issues, compact and continued pages.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const context=vm.createContext({structuredClone});
vm.runInContext(fs.readFileSync('frontend/parameter-confirmation-sheet.js','utf8'),context);
const api=context.ParameterConfirmationSheet;
const labels={material:'材料',wire_diameter:'线径',outer_diameter:'外径',inner_diameter:'内径',mean_diameter:'中径',free_length:'自由长度',total_coils:'总圈数',active_coils:'有效圈数',handedness:'旋向'};
const values={material:'SUS304',wire_diameter:2,outer_diameter:20,inner_diameter:16,mean_diameter:18,free_length:36,total_coils:12,active_coils:10,handedness:'右旋'};
const data={info:{drawingName:'压缩弹簧',drawingNo:'00123-A',variant:'规格1',preparer:'测试工程师',date:'2026/11/10'},
 parameters:Object.entries(values).map(([field,value])=>({id:`param:${field}`,field,label:labels[field],value,unit:field.includes('diameter')||field==='free_length'?'mm':field.includes('coils')?'圈':'',state:'待确认',tolerance:field==='wire_diameter'?'±0.05':'—'})),
 loads:[{id:'load:one',field:'load_points.F1',label:'F1',height:'32 ±2 mm',force:'10 N',tolerance:'±10%'},{id:'load:two',field:'load_points.F2',label:'F2',height:'28 mm',force:'20 N',tolerance:'±10%'}],
 requirements:['热处理：消除应力退火。','表面处理：防锈处理，不得有油污及毛刺。','寿命要求：40000次循环内不得失效。','其他要求：两端并紧并磨平，Ra12.5，不制扁。'].map((content,i)=>({id:`technical:${i}`,field:`technical_requirements.${i}`,number:i+1,label:'技术要求',content,state:'待确认'}))};
const few=structuredClone(data);
few.parameters.find(row=>row.field==='wire_diameter').value=null;
few.parameters.find(row=>row.field==='total_coils').value=6.5;
few.parameters.find(row=>row.field==='active_coils').value=8;
few.issues=[{rule_id:'SPRING-GEO-COIL-COUNT',severity:'blocked',category:'geometry',fields:['total_coils','active_coils'],message:'有效圈数不能大于总圈数。',customer_question:'请确认总圈数与有效圈数的正确数值。'}];
few.loads[1].customer_issues=['该测试点有两组力值，请确认采用值及公差。'];
few.requirements[1].customer_issues=['处理方式未明确，请提供具体工艺。'];
const compact=structuredClone(few);
for(let i=0;i<16;i++)compact.requirements.push({id:`technical:extra-${i}`,field:`technical_requirements.extra-${i}`,number:i+5,label:'技术要求',content:`补充工艺${i+1}：端部不得存在裂纹，按规定顺序加工和检验。`});
const long=structuredClone(few);long.info.variant='FTA-28/103-274';
long.requirements.push({id:'technical:long',field:'technical_requirements.long',number:5,label:'技术要求',customer_issues:['该条款的适用部位待客户明确。'],content:'长条款开始：'+ '镀层厚度≥15 μm，先除氢后检验；不得漏镀，作用部位按原图执行。'.repeat(100)+'长条款结束-完整保留。'});
for(let i=0;i<18;i++)long.loads.push({id:`load:extra-${i}`,field:`load_points.extra-${i}`,label:`F${i+3}`,height:`${20+i} mm`,force:`${30+i} N`,tolerance:'+1 / -0.5 N'});
const logoData=`data:image/png;base64,${fs.readFileSync('frontend/assets/incospring-logo.png').toString('base64')}`;
const out=path.resolve('outputs/confirmation-rfi-qa');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,channel:'msedge'}),records=[];
try{
 const page=await browser.newPage({viewport:{width:900,height:1200}});
 for(const[name,input]of [['normal',data],['few-rfi',few],['compact',compact],['long',long]]){
  const before=JSON.stringify(input),model=api.buildModel(input);assert.equal(JSON.stringify(input),before);
  await page.setContent(api.documentHtml(model,undefined,{logoData}));
  await page.evaluate(()=>Promise.all([document.fonts.ready,...[...document.images].map(i=>i.decode())]));
  await page.addScriptTag({content:fs.readFileSync('frontend/parameter-confirmation-sheet.js','utf8')});
  const layout=await page.evaluate(()=>{const original=document.querySelector('.report-content').offsetHeight;return {...ParameterConfirmationSheet.fitDocument(document),original,height:document.querySelector('.report-content').offsetHeight};});
  assert.equal(await page.locator('.brand-header h1').evaluate(el=>getComputedStyle(el).fontSize),'18.6667px');
  assert.equal(await page.locator('input,.paper-check').count(),0);
  const ids=await page.locator('[data-report-row]').evaluateAll(rows=>rows.map(row=>row.dataset.reportRow));
  assert.equal(new Set(ids).size,ids.length,'each selected project is printed once');
  assert.equal(await page.locator('.parameter-report-table').count(),1);
  assert.equal(await page.locator('.load-report-table').count(),1);
  assert.equal(await page.locator('[data-report-row="load:one"] td').nth(1).textContent(),'32 ±2 mm');
  if(name==='normal')assert.equal(await page.locator('[data-report-row="load:two"] td').nth(1).textContent(),'28 mm');
  assert.equal(await page.locator('.issue-reply').count(),name==='normal'?0:name==='long'?5:4);
  assert.match(await page.locator('body').innerText(),/两端并紧并磨平，Ra12.5，不制扁/,'original technical text stays complete');
  assert.doesNotMatch(await page.locator('body').innerText(),/RFI-|【确认】|紧凑异常示例|设计校核结果/);
  if(name!=='normal'){
   assert.equal(await page.locator('.parameter-report-table [data-report-row="param:wire_diameter"]').count(),0);
   assert.equal(await page.locator('[data-report-row="param:total_coils"]').count(),1);
   assert.equal(await page.locator('.parameter-report-table [data-report-row="param:active_coils"]').count(),0);
   assert.equal((await page.locator('body').innerText()).split('有效圈数不能大于总圈数').length-1,1);
   assert.match(await page.locator('body').innerText(),/总圈数：6.5 圈；有效圈数：8 圈/);
   assert.equal(await page.locator('[data-report-row="technical:1"]').count(),1);
   assert.equal(await page.locator('.issue-reply').evaluateAll(rows=>rows.every(row=>{
    const line=row.querySelector('.issue-reply-line'),style=getComputedStyle(row);
    return row.textContent==='客户回复：' && row.querySelectorAll('.issue-reply-line').length===1 && getComputedStyle(line).borderBottomStyle==='solid' && line.offsetWidth>100 && row.offsetHeight<=parseFloat(style.lineHeight)+2;
   })),true,'all reply lines are uniform, continuous and stay on one line');
  }
  if(name==='compact')assert.equal(layout.compact,true,JSON.stringify(layout));
  await page.pdf({path:path.join(out,`${name}.pdf`),preferCSSPageSize:true,printBackground:true});
  await page.screenshot({path:path.join(out,`${name}-screen.png`),fullPage:true});
  fs.writeFileSync(path.join(out,`${name}.html`),await page.content());
  records.push({name,...layout});
 }
 fs.writeFileSync(path.join(out,'layout.json'),JSON.stringify(records,null,2));
 console.log(JSON.stringify(records));
}finally{await browser.close();}
