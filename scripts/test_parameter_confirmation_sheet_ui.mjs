import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context=vm.createContext({structuredClone});
vm.runInContext(fs.readFileSync('frontend/parameter-confirmation-sheet.js','utf8'),context);
const api=context.ParameterConfirmationSheet;
const logoData=`data:image/png;base64,${fs.readFileSync('frontend/assets/incospring-logo.png').toString('base64')}`;
const values={material:'55CrSi',wire_diameter:1.6,outer_diameter:13,inner_diameter:9.8,mean_diameter:11.4,free_length:28,total_coils:7.5,active_coils:5.5,handedness:'右旋'};
const labels={material:'材料',wire_diameter:'线径',outer_diameter:'外径',inner_diameter:'内径',mean_diameter:'中径',free_length:'自由长度',total_coils:'总圈数',active_coils:'有效圈数',handedness:'旋向'};
const fixture=()=>({info:{drawingName:'压缩弹簧',drawingNo:'000123-A',date:'2026/11/10',local:true},
 parameters:Object.entries(values).map(([field,value])=>({id:`param:${field}`,field,label:labels[field],value,unit:field.includes('diameter')||field==='free_length'?'mm':field.includes('coils')?'圈':'',state:'待确认',tolerance:field==='wire_diameter'?'±0.05':'—'})),
 loads:[{id:'load:f1',field:'load_points.F1',label:'F1',height:'20 mm',force:'0 N',tolerance:'±10%',state:'待确认'}],
 requirements:[{id:'technical:one',field:'technical_requirements.one',label:'工艺要求',number:3,content:'两端并紧并磨平；Ra12.5；不制扁；附加条件完整保留。',state:'待确认'}]});
const render=(model,selected)=>api.documentHtml(model,selected,{logoData});
const data=fixture(),before=JSON.stringify(data),model=api.buildModel(data),html=render(model);
assert.equal(JSON.stringify(data),before);
assert.deepEqual(Array.from(model.sections,s=>s.id),['parameters','loads','requirements','issues']);
assert.equal(model.sections[0].rows.length,9);
assert.equal(model.sections[3].rows.length,0,'internal pending confirmation is not a customer question');
assert.match(html,/14pt/);assert.match(html,/9.5pt/);assert.match(html,/9pt/);
assert.match(html,/最终参数/);assert.match(html,/0 N/);assert.match(html,/±10%/);assert.match(html,/000123-A/);
assert.match(html,/3\. 两端并紧并磨平；Ra12.5；不制扁；附加条件完整保留/);
assert.doesNotMatch(html,/RFI-|【确认】|【RFI|设计校核|待客户澄清事项|紧凑异常示例/);
assert.equal((html.match(/<table/g)||[]).length,2);
assert.equal((html.match(/<img\b/g)||[]).length,1);
assert.equal(api.tolerance({tolerance_upper:.1,tolerance_lower:-.1}),'±0.1');
assert.equal(api.tolerance({tolerance_upper:1,tolerance_lower:0}),'+1 / 0');
assert.equal(api.tolerance({tolerance_input_draft:'±abc'}),'±abc');
assert.equal(api.tolerance({force_tolerance_percent:0},true),'±0%');
assert.equal(api.tolerance({load_tolerance_upper:1,load_tolerance_lower:-.5,load_tolerance_percent:10},true),'+1 / -0.5');
assert.throws(()=>api.documentHtml(model,undefined,{logoData:'https://example.com/logo.png'}),/Logo/);
const omitted=fixture();
for(const field of ['surface_roughness_ra','end_type','end_grinding','flattening','pitch','solid_height','spring_rate','standard_no']){
 omitted.parameters.push({id:`param:${field}`,field,label:`隐藏-${field}`,value:0,customer_issues:['隐藏项冲突']});
}
omitted.advanced=[{id:'param:legacy',field:'legacy',value:3}];
omitted.calculations=[{id:'calculation:stress',value:999}];
omitted.suggestions=[{field:'wire_diameter',value:88}];
omitted.issues=[{fields:['end_type'],severity:'blocked',category:'geometry',message:'隐藏字段专属异常'},
 {fields:['active_coils'],severity:'needs_input',category:'missing_context',message:'缺少公式条件'},
 {fields:['wire_diameter'],severity:'warning',rule_id:'FORMULA-CHECK',category:'geometry',message:'内部公式差异'},
 {fields:['total_coils'],severity:'warning',category:'standard_scope',message:'未采用的标准化范围'}];
omitted.notice='内部检查暂不可用';
const projected=api.buildModel(omitted),projectedHtml=render(projected);
assert.equal(projected.sections[3].rows.length,0);
assert.doesNotMatch(projectedHtml,/隐藏-|隐藏字段|缺少公式|内部公式|标准化范围|内部检查暂不可用|calculation:/);
assert.equal(projected.notice,'内部检查暂不可用');
const missing=fixture();missing.parameters.find(p=>p.field==='wire_diameter').value=null;
missing.parameters.find(p=>p.field==='mean_diameter').value=null;
const missingModel=api.buildModel(missing),issue=missingModel.sections[3].rows[0];
assert.equal(issue.id,'param:wire_diameter');assert.equal(issue.items[0].ref,'参数2');
assert.ok(!api.selectionRows(missingModel).some(row=>row.field==='mean_diameter'));
assert.equal((render(missingModel).match(/data-report-row="param:wire_diameter"/g)||[]).length,1);
assert.ok(!missingModel.sections[0].rows.some(p=>p.field==='wire_diameter'));
const explicitOptional=fixture();explicitOptional.parameters.find(p=>p.field==='mean_diameter').value=null;
explicitOptional.issues=[{severity:'warning',category:'geometry',fields:['mean_diameter'],message:'图纸中径归属冲突，请明确采用的尺寸。'}];
assert.equal(api.buildModel(explicitOptional).sections[3].rows[0].items[0].field,'mean_diameter','an existing real issue is retained even for a blank optional field');
const selected=new Set(api.selectionRows(model).map(row=>row.id));selected.delete('param:wire_diameter');
assert.doesNotMatch(render(missingModel,selected),/data-report-row="param:wire_diameter"/,'choice identity is unchanged when moving to issues');
const grouped=fixture();grouped.parameters[1].customer_issues=['线径需核对','线径需核对'];
grouped.issues=[{fields:['wire_diameter','outer_diameter'],severity:'warning',category:'geometry',message:'线径与外径不一致'},
 {fields:['outer_diameter','inner_diameter'],severity:'warning',category:'geometry',message:'外径与内径不一致'}];
const groupModel=api.buildModel(grouped),groups=groupModel.sections[3].rows;
assert.equal(groups.length,1);assert.equal(groups[0].items.length,3);
assert.equal(new Set(api.selectionRows(groupModel).map(row=>row.id)).size,api.selectionRows(groupModel).length);
assert.deepEqual(Array.from(groups[0].messages),['线径需核对','线径与外径不一致','外径与内径不一致']);
assert.equal((render(groupModel).match(/class="issue-reply"/g)||[]).length,1);
const coils=fixture();
coils.parameters.find(row=>row.field==='total_coils').value=6.5;
coils.parameters.find(row=>row.field==='active_coils').value=8;
coils.issues=[{rule_id:'SPRING-GEO-COIL-COUNT',severity:'blocked',category:'geometry',fields:['total_coils','active_coils'],message:'有效圈数不能大于总圈数。',customer_question:'请确认总圈数与有效圈数的正确数值。'},
 {severity:'warning',category:'geometry',fields:['active_coils','total_coils'],message:' 有效圈数不能大于总圈数 ',customer_question:'请确认总圈数与有效圈数的正确数值'}];
const coilsModel=api.buildModel(coils),coilsHtml=render(coilsModel),coilsIssue=coilsModel.sections[3].rows[0];
assert.deepEqual(Array.from(coilsIssue.reasons),['有效圈数不能大于总圈数。']);
assert.deepEqual(Array.from(coilsIssue.questions),['请确认总圈数与有效圈数的正确数值。']);
assert.equal(coilsIssue.items.length,2);
assert.equal((coilsHtml.match(/有效圈数不能大于总圈数/g)||[]).length,1);
assert.equal((coilsHtml.match(/请确认总圈数与有效圈数的正确数值/g)||[]).length,1);
assert.match(coilsHtml,/当前：总圈数：6.5 圈；有效圈数：8 圈/);
assert.doesNotMatch(coilsHtml,/SPRING-GEO-COIL-COUNT|补充端部形式/);
for(const field of ['total_coils','active_coils'])assert.ok(!coilsModel.sections[0].rows.some(row=>row.field===field));
const partlySelected=new Set(api.selectionRows(coilsModel).map(row=>row.id));partlySelected.delete('param:total_coils');
assert.doesNotMatch(render(coilsModel,partlySelected),/总圈数：6.5 圈/);
assert.match(render(coilsModel,partlySelected),/有效圈数不能大于总圈数/);
for(const [description,source,expectedReasons]of [
 ['reason only',{message:'两个直径标注不一致。'},['两个直径标注不一致。']],
 ['question only',{customer_question:'请明确这两个直径的尺寸归属。'},[]],
 ['same text in both',{message:'请核对尺寸归属。',customer_question:' 请核对尺寸归属 '},['请核对尺寸归属。']],
]){
 const input=fixture();input.issues=[{severity:'warning',category:'geometry',fields:['outer_diameter','inner_diameter'],...source}];
 const result=api.buildModel(input),group=result.sections[3].rows[0];
 assert.deepEqual(Array.from(group.reasons),expectedReasons,description);
 assert.equal(group.questions.length,1,description);
 assert.equal(group.messages.length,description==='reason only'?2:1,description);
 if(description==='reason only')assert.equal(group.questions[0],'请确认外径、内径的正确内容。');
}
const replyKinds=fixture();
for(const row of [replyKinds.parameters[0],replyKinds.parameters[1],replyKinds.parameters[8],replyKinds.loads[0],replyKinds.requirements[0]])row.customer_issues=['标注存在冲突，请明确采用内容。'];
const replyHtml=render(api.buildModel(replyKinds));
assert.equal((replyHtml.match(/class="issue-reply"/g)||[]).length,5);
assert.equal((replyHtml.match(/<span class="issue-reply-label">客户回复：<\/span><span class="issue-reply-line" aria-hidden="true"><\/span>/g)||[]).length,5);
assert.doesNotMatch(replyHtml,/确认值：_|测试高度：_|力值：_|公差：_|客户回复：_/);
const provisional=fixture();Object.assign(provisional.parameters[1],{value:3,provisional_default:true});
const provisionalModel=api.buildModel(provisional);
assert.equal(provisionalModel.sections[3].rows[0].items[0].current,'原图未明确');
const issueHtml=render(provisionalModel).split('待客户澄清事项')[1];assert.doesNotMatch(issueHtml,/3 mm/);
const escaped=fixture();escaped.info.drawingName='<script>alert(1)</script>';
escaped.requirements[0].content='<img src=x onerror=alert(1)>';
assert.match(render(api.buildModel(escaped)),/&lt;script&gt;/);
assert.doesNotMatch(render(api.buildModel(escaped)),/<script>|<img src=x/);
const long=fixture();long.requirements[0].customer_issues=['具体工艺未注明'];
long.requirements[0].content='长条款开始：'+ '镀层厚度≥15μm，先除氢后检验；不得漏镀。'.repeat(100)+'长条款结束-完整保留。';
const longHtml=render(api.buildModel(long));assert.match(longHtml,/长条款结束-完整保留/);assert.match(longHtml,/long-item/);
assert.equal((longHtml.match(/长条款开始/g)||[]).length,1,'abnormal full text prints only once');
assert.doesNotMatch(render(model,new Set()),/<table|data-report-row/);
console.log('PASS customer confirmation model: nine-field policy, pending normal values, omitted diagnostics, stable choices, merged exceptions, full clauses, original references and escaped read-only HTML');
