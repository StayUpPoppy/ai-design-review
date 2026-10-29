// Offline A4 acceptance: complete report, a few questions, compact fit and long continuation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const context=vm.createContext({structuredClone});
for(const file of ['compression-design-checks.js','parameter-confirmation-sheet.js'])vm.runInContext(fs.readFileSync(`frontend/${file}`,'utf8'),context);
const api=context.ParameterConfirmationSheet,engine=context.CompressionDesignChecks;
const catalog=JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
const review=JSON.parse(fs.readFileSync('data/test/compression_design_checks.json','utf8')).base;
for(const [field,value]of Object.entries({standard_no:'GB/T 1239.2-2009',accuracy_grade:'2级',outer_diameter:20,inner_diameter:16,pitch:3.2,surface_roughness_ra:12.5,handedness:'右旋',perpendicularity:.2}))review.spring_parameters[field]={value};
for(const item of Object.values(review.spring_parameters))if(item&&!Array.isArray(item)){item.need_human_review=false;item.source=['human_edited'];}
review.spring_parameters.load_points=review.spring_parameters.load_points.slice(0,2).map(p=>({...p,need_human_review:false}));
const initial=engine.calculate(review.spring_parameters,review.spring_features,catalog);
review.spring_parameters.spring_rate.value=initial.metrics.theoretical_spring_rate.value;
for(const p of review.spring_parameters.load_points)p.force=initial.metrics.theoretical_spring_rate.value*(36-p.height);
const labels={material:'材料',standard_no:'标准号',accuracy_grade:'通用精度等级',wire_diameter:'线径',mean_diameter:'中径',outer_diameter:'外径',inner_diameter:'内径',free_length:'自由高度',active_coils:'有效圈数',total_coils:'总圈数',support_coils:'支承圈数（单端）',pitch:'节距',surface_roughness_ra:'表面粗糙度Ra',handedness:'旋向',end_type:'端部形式',end_grinding:'端面磨削',spring_rate:'当前刚度（参数值）',perpendicularity:'垂直度'};
const data={info:{drawingName:'客户弹簧参数核对样例',drawingNo:'00123-A',variant:'规格1',preparer:'测试工程师',date:'2026/10/28'},
  parameters:Object.entries(labels).map(([f,label])=>({id:`param:${f}`,field:f,label,value:review.spring_parameters[f].value,
    unit:['material','standard_no','accuracy_grade','handedness','end_type','end_grinding'].includes(f)?'':f.includes('coils')?'圈':f==='spring_rate'?'N/mm':f==='surface_roughness_ra'?'μm':'mm',state:'已确认',tolerance:f==='wire_diameter'?'±0.05':'—'})),
  calculations:api.calculationRows(engine.calculate(review.spring_parameters,review.spring_features,catalog),f=>labels[f]||f,{review,assessmentAvailable:true,parameterState:()=>({state:'已确认'}),loadState:()=>({state:'已确认'})}),
  loads:review.spring_parameters.load_points.map(p=>({id:`load:${p.label}`,field:`load_points.${p.label}`,label:p.label,height:`${p.height} mm`,force:`${Number(p.force.toFixed(4))} N`,tolerance:'±10%',state:'已确认'})),
  requirements:['热处理：消除应力退火。','表面处理：防锈处理，不得有油污及毛刺。','寿命要求：40000次循环内不得失效。','其他要求：未注尺寸以3D为准。'].map((content,i)=>({id:`technical:${i}`,field:`technical_requirements.${i}`,label:'技术要求',content,state:'已确认'}))};
assert.deepEqual(Array.from(data.calculations.filter(r=>r.assessment!=='confirmed'),r=>[r.label,r.reason]),[],'all actual inputs are reviewed');
const few=structuredClone(data);Object.assign(few.parameters.find(p=>p.field==='surface_roughness_ra'),{value:null,state:'待补充'});
Object.assign(few.parameters.find(p=>p.field==='perpendicularity'),{state:'待确认'});
few.suggestions=[{field:'surface_roughness_ra',value:'Ra 12.5 μm · 两端面',basis:'项目参考，非原图值'},{field:'surface_roughness_ra',value:'Ra 6.3 μm · 两端面',basis:'项目参考，非原图值'}];
const compact=structuredClone(few);
for(let i=0;i<9;i++)compact.requirements.push({id:`technical:extra-${i}`,field:`technical_requirements.extra-${i}`,label:'技术要求',content:`补充工艺${i+1}：端部不得存在裂纹，按规定顺序加工和检验。`,state:'已确认'});
const long=structuredClone(few);long.info.variant='FTA-28/103-274';
long.requirements.push({id:'technical:long',field:'technical_requirements.long',label:'技术要求',state:'待确认',content:'长条款开始：'+ '镀层厚度≥15 μm，先除氢后检验；不得漏镀，作用部位按原图执行。'.repeat(100)+'长条款结束-完整保留。'});
for(let i=0;i<18;i++)long.loads.push({id:`load:extra-${i}`,field:`load_points.extra-${i}`,label:`F${i+3}`,height:`${20+i} mm`,force:`${30+i} N`,state:i%2?'已确认':'待确认',tolerance:'+1 / -0.5 N'});
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
    assert.equal(await page.locator('table,input,.paper-check').count(),0);
    const ids=await page.locator('.rfi-code').allTextContents();assert.deepEqual(ids,ids.map((_,i)=>`RFI-${String(i+1).padStart(2,'0')}`));
    const labelsUsed=await page.locator('.assessment[data-state="rfi"]').allTextContents();assert.ok(labelsUsed.every(l=>ids.includes(l.replace(/[【】]/g,''))));
    if(name==='normal')assert.equal(ids.length,0);
    if(name==='few-rfi')assert.equal(ids.length,2);
    if(name==='compact')assert.equal(layout.compact,true);
    await page.pdf({path:path.join(out,`${name}.pdf`),preferCSSPageSize:true,printBackground:true});
    fs.writeFileSync(path.join(out,`${name}.html`),await page.content());
    records.push({name,...layout});
  }
  fs.writeFileSync(path.join(out,'layout.json'),JSON.stringify(records,null,2));
  console.log(JSON.stringify(records));
}finally{await browser.close();}
