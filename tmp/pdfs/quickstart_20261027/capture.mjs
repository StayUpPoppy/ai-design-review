import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('C:/Users/29580/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.resolve('tmp/pdfs/quickstart_20261027/assets');fs.mkdirSync(out,{recursive:true});
const drawing=`<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="720" viewBox="0 0 1000 720"><rect width="1000" height="720" fill="white"/><g fill="none" stroke="#263244" stroke-width="2"><rect x="30" y="30" width="940" height="660"/><path d="M210 330 L230 330 Q245 230 260 330 Q275 430 290 330 Q305 230 320 330 Q335 430 350 330 Q365 230 380 330 Q395 430 410 330 Q425 230 440 330 Q455 430 470 330 Q485 230 500 330 Q515 430 530 330 Q545 230 560 330 Q575 430 590 330 Q605 230 620 330 Q635 430 650 330 Q665 230 680 330 L700 330"/><path d="M230 215 V190 H680 V215 M715 260 H750 V400 H715 M230 450 H680"/><path d="M235 190 l15 -5 v10 z M675 190 l-15 -5 v10 z M750 265 l-5 15 h10 z M750 395 l-5 -15 h10 z" fill="#263244"/><rect x="600" y="570" width="370" height="120"/><path d="M600 610 H970 M600 650 H970 M740 570 V690"/></g><g font-family="Microsoft YaHei,Arial" fill="#263244"><text x="400" y="170" font-size="23">自由高度 25</text><text x="770" y="340" font-size="23">外径 9</text><text x="90" y="490" font-size="21">技术要求</text><text x="90" y="525" font-size="19">1. 材料：SUS304，线径 1。</text><text x="90" y="560" font-size="19">2. 总圈数10；有效圈数8。</text><text x="90" y="595" font-size="19">3. 两端并紧磨平，右旋。</text><text x="90" y="630" font-size="19">4. 消除应力退火。</text><text x="620" y="597" font-size="18">图纸名称</text><text x="760" y="597" font-size="18">示例压缩弹簧</text><text x="620" y="638" font-size="18">图号</text><text x="760" y="638" font-size="18">DEMO-001</text><text x="620" y="677" font-size="18">演示图纸</text><text x="760" y="677" font-size="17">仅用于操作说明</text></g></svg>`;
const treatment=JSON.parse(fs.readFileSync('config/compression_material_catalog.json','utf8'));
const p=(value,unit='')=>({value,unit,need_human_review:false,human_modified:true,source:['human_edited'],confidence:1,evidence:'示例参数，仅演示界面操作'});
const review={drawing_summary:{spring_type:'compression_spring',drawing_name:'示例压缩弹簧',drawing_no:'DEMO-001'},spring_parameters:{
 material:p('SUS304'),standard_no:p('GB/T 1239.2-2009'),accuracy_grade:p('2级'),wire_diameter:p(1,'mm'),outer_diameter:p(9,'mm'),inner_diameter:p(7,'mm'),mean_diameter:p(8,'mm'),free_length:p(25,'mm'),solid_height:p(9,'mm'),total_coils:p(10,'turns'),active_coils:p(8,'turns'),support_coils:{...p(1,'turns'),evidence:'每端支承圈数：1圈',support_coils_origin:'drawing_single_end'},pitch:p(3,'mm'),surface_roughness_ra:{value:null,unit:'μm',need_human_review:true},handedness:p('right'),end_type:p('两端并紧'),end_grinding:p('两端磨削'),load_points:[]},
 spring_features:{spring_shape:{value:'cylindrical'},wire_section:{value:'round'},pitch_type:{value:'constant'}},
 technical_requirements:[{requirement_id:'heat',type:'heat_treatment',content:'热处理：消除应力退火。',need_human_review:true},{requirement_id:'surface',type:'surface',content:'表面处理：防锈处理。',normalization_status:'human_confirmed',need_human_review:true}],
 parameter_reasonableness:{status:'pass',issues:[],suggestions:[]},standardization_results:[],manual_confirmations:{},change_history:[],generation_settings:{drawing_model:'X型',username:'张工'}};
let revision=1;
const frontend=path.resolve('frontend');
const server=http.createServer((req,res)=>{const url=new URL(req.url,'http://localhost');if(url.pathname==='/manual-drawing.svg'){res.setHeader('Content-Type','image/svg+xml');return res.end(drawing);}const file=path.resolve(frontend,url.pathname.slice(1)||'index.html');if(!file.startsWith(frontend+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':'text/html');res.end(fs.readFileSync(file));});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1.5});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const req=route.request(),u=new URL(req.url()),api=u.pathname;
 if(api==='/api/session')return route.fulfill({json:{identity:{user_id:'guide-demo',username:'zhanggong',real_name:'张工'}}});
 if(api==='/api/material-catalog')return route.fulfill({json:treatment});
 if(api==='/api/surface-treatment-catalog')return route.fulfill({json:{version:'demo',items:[]}});
 if(api==='/api/reviews')return route.fulfill({json:{reviews:[{job_id:'guide-demo',drawing_name:'示例压缩弹簧',drawing_no:'DEMO-001',revision,recognition_status:'completed',image_url:'/manual-drawing.svg'}]}});
 if(api==='/api/reviews/reasonableness')return route.fulfill({json:{parameter_reasonableness:{status:'pass',issues:[],suggestions:[]}}});
 if(api==='/api/reviews/guide-demo'){
   if(req.method()==='PATCH'){revision++;return route.fulfill({json:{review_revision:revision,events:req.postDataJSON().events}});}
   return route.fulfill({json:{...review,job_id:'guide-demo',review_revision:revision,image_url:'/manual-drawing.svg'}});
 }
 if(api.endsWith('/generation-jobs'))return route.fulfill({json:{generation_jobs:[],generation_queue_available:true}});
 if(api.endsWith('/annotations'))return route.fulfill({json:{pages:[],annotations:[]}});
 if(api.endsWith('/changes'))return route.fulfill({json:{events:[]}});
 return route.fulfill({json:{status:'ok',generation_runtime:{status:'available'},recognition_queue_runtime:{status:'available'}}});
});
async function shot(name,locator){await page.waitForTimeout(120);await (locator||page).screenshot({path:path.join(out,name+'.png')});}
try{
 await page.goto(`http://127.0.0.1:${server.address().port}`);await page.waitForFunction(()=>state.identityReady&&state.materialCatalog.items.length);
 await page.locator('#drawingInput').setInputFiles({name:'示例压缩弹簧.png',mimeType:'image/png',buffer:Buffer.from('manual demonstration file - never uploaded')});
 await page.waitForFunction(()=>!document.querySelector('#submitButton').disabled);
 await shot('upload');
 await shot('upload-zone',page.locator('#dropZone'));
 await page.evaluate(async()=>{await openPersistedReview('guide-demo');state.imageUrl='/manual-drawing.svg';state.compareTab='parameters';renderCompareOverlay();});
 await page.waitForFunction(()=>document.querySelector('.compare-overlay')&&!document.querySelector('.compare-overlay').hidden);
 await shot('workbench');
 await page.evaluate(()=>{state.review.spring_parameters.wire_diameter.need_human_review=true;state.review.spring_parameters.free_length.need_human_review=true;state.review.spring_parameters.total_coils.need_human_review=true;state.review.spring_parameters.active_coils.need_human_review=true;renderCompareOverlay();});
 await shot('parameters',page.locator('.compare-tab-panel[data-compare-panel="parameters"]'));
 await shot('parameter-table',page.locator('.compare-tab-panel[data-compare-panel="parameters"] .data-table').first());
 const cropBottom=await page.locator('.compare-tab-panel[data-compare-panel="parameters"] .data-table').first().evaluate(table=>{const box=table.getBoundingClientRect(),last=table.querySelector('[data-field="total_coils"]').getBoundingClientRect();return (last.bottom-box.top)/box.height;});
 fs.writeFileSync(path.join(out,'crop.json'),JSON.stringify({parameterBottom:cropBottom}));
 // Detail of real controls, at a readable scale for the printed guide.
 const parameterPanel=page.locator('.compare-tab-panel[data-compare-panel="parameters"]');
 await parameterPanel.locator('[data-field="surface_roughness_ra"]').scrollIntoViewIfNeeded();
 await shot('roughness',parameterPanel.locator('[data-field="surface_roughness_ra"]'));
 await parameterPanel.locator('[data-kind="technical"]').first().scrollIntoViewIfNeeded();
 await shot('technical',parameterPanel.locator('[data-kind="technical"]').first());
 await page.evaluate(()=>{state.compareTab='generation';state.generationQueueAvailable=true;for(const item of state.review.technical_requirements)item.need_human_review=false;state.generationReadiness={generation_readiness:{status:'ready',summary:'核心参数和技术要求已确认，可生成图纸。',confirmed_core_count:8,core_field_count:8,warnings:[],missing_fields:[],pending_fields:[]}};renderCompareOverlay();});
 await shot('generation',page.locator('.compare-tab-panel[data-compare-panel="generation"]'));
 await page.evaluate(()=>{state.generationJobs=[{generation_id:'1000000001',review_revision:1,template_code:'solidworks_compression_v2',template_version:'1',status:'completed',progress:100,preview_status:'ready',status_message:'示例界面：二维图已生成',generation_settings:{drawing_model:'X型',username:'张工'},created_at:'2026-10-27T02:00:00Z',artifacts:[{artifact_id:'demo-pdf',artifact_type:'pdf',mime_type:'application/pdf',filename:'示例压缩弹簧.pdf',url:'/guide-demo.pdf'}]}];renderCompareOverlay();});
 await shot('result',page.locator('.generation-version-card'));
 await page.evaluate(()=>{state.compareTab='parameters';renderCompareOverlay();});
 await page.locator('.compare-overlay [data-action="preview-confirmation-sheet"]').click();await page.waitForFunction(()=>!document.querySelector('[data-sheet-action="print"]').disabled);
 await shot('sheet',page.locator('.confirmation-sheet-preview'));
 await page.keyboard.press('Escape');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log('Saved manual screenshots:',out);
}finally{await browser.close();server.close();}
