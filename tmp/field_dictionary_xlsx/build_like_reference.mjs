import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const referencePath = "C:/Users/29580/Desktop/工作/pdf转erp/订单接口参数说明.xlsx";
const previewPath = "D:/YingKe/ai-design-review/tmp/field_dictionary_xlsx/order_interface_reference_preview.png";

const input = await FileBlob.load(referencePath);
const workbook = await SpreadsheetFile.importXlsx(input);
const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 6000,
  tableMaxRows: 18,
  tableMaxCols: 12,
  tableMaxCellChars: 120,
});
console.log(overview.ndjson);

const sheet = workbook.worksheets.getItemAt(0);
console.log(`SHEET=${sheet.name}`);
const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 1.4, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
console.log(`PREVIEW=${previewPath}`);

const outputDir = "D:/YingKe/ai-design-review/outputs/reference_style_field_dictionary_20260727";
const outputPath = `${outputDir}/compression_spring_generation_parameters_field_guide_reference_style.xlsx`;
const guideRows = [];
const yellowRows = [];
const indent = (level) => "\u00A0\u00A0\u00A0\u00A0".repeat(level);
const line = (code, description = "") => guideRows.push(["", code, description]);
const group = (code, description) => {
  line(code, description);
  yellowRows.push(guideRows.length);
};

line("{");
line(`${indent(1)}\"schema_version\": \"spring_generation_parameters/v1\",`, "JSON 结构版本，供程序按正确格式解析。");
line(`${indent(1)}\"package_type\": \"confirmed_compression_spring_generation_input\",`, "包的业务类型：已确认的压缩弹簧生图输入。");
line(`${indent(1)}\"generated_at\": \"2026-07-27T07:21:45.111Z\",`, "参数包生成时间。");
group(`${indent(1)}\"export_policy\": {`, "导出规则");
line(`${indent(2)}\"parameter_filter\": \"human_confirmed_only\",`, "导出筛选规则；仅导出人工确认的数据。");
line(`${indent(2)}\"readiness_is_advisory\": true`, "就绪检查只作提示；未齐套时仍允许导出。");
line(`${indent(1)}},`);
group(`${indent(1)}\"source\": {`, "图纸与弹簧来源信息");
line(`${indent(2)}\"drawing_no\": \"YD4765020175\",`, "图号。");
line(`${indent(2)}\"drawing_name\": \"UQD06外弹簧(钢珠型)\",`, "图纸/零件名称。");
line(`${indent(2)}\"spring_type\": \"compression_spring\",`, "程序使用的弹簧类型编码。");
line(`${indent(2)}\"spring_type_label\": \"压缩弹簧\"`, "给人看的弹簧类型名称。");
line(`${indent(1)}},`);
group(`${indent(1)}\"standard_context\": {`, "适用标准及确认状态");
line(`${indent(2)}\"selected_standard\": \"GB/T 1239.2-2009\",`, "当前采用的标准。");
line(`${indent(2)}\"selection_status\": \"applicable\",`, "标准适用状态。");
line(`${indent(2)}\"human_confirmed\": false`, "标准选择是否被显式人工确认。");
line(`${indent(1)}},`);
group(`${indent(1)}\"generation_parameters\": {`, "生图/制造的主参数");
group(`${indent(2)}\"spring_parameters\": {`, "弹簧主参数");
line(`${indent(3)}\"<每个参数记录>\": {`, "每个参数均使用同一记录结构。");
line(`${indent(4)}\"label\": \"线径\",`, "中文显示名称。");
line(`${indent(4)}\"value\": 1.5,`, "参数值。");
line(`${indent(4)}\"unit\": \"mm\",`, "单位，如 mm、N/mm、turns。");
line(`${indent(4)}\"tolerance_upper\": 0.05,`, "上公差。");
line(`${indent(4)}\"tolerance_lower\": -0.05,`, "下公差。");
line(`${indent(4)}\"confirmation_source\": \"human_confirmed\"`, "确认来源。");
line(`${indent(3)}},`);
group(`${indent(3)}\"<当前业务参数>\": {`, "当前包含的业务参数");
const parameters = [
  ["material", "SUS304", "材料，如 SUS304。"],
  ["standard_no", "GB/T 1239.2-2009", "产品适用标准号。"],
  ["accuracy_grade", "2级", "通用精度等级。"],
  ["wire_diameter", "1.5 mm", "线径。"],
  ["outer_diameter", "25 mm", "外径。"],
  ["inner_diameter", "22 mm", "内径。"],
  ["mean_diameter", "23.5 mm", "中径。"],
  ["free_length", "15 mm", "自由长度。"],
  ["solid_height", "6.2 mm", "压并高度。"],
  ["total_coils", "4 turns", "总圈数。"],
  ["active_coils", "3 turns", "有效圈数。"],
  ["handedness", "right", "旋向。"],
  ["end_type", "closed_and_ground", "端部形式。"],
  ["end_grinding", "两端磨平", "端面磨削要求。"],
  ["spring_rate", "1.154 N/mm", "刚度。"],
  ["perpendicularity", "0.75 mm", "垂直度要求。"],
  ["permanent_set_limit", "0.045 mm", "永久变形限值。"],
];
for (const [key, value, description] of parameters) {
  line(`${indent(4)}\"${key}\": \"${value}\",`, description);
}
line(`${indent(3)}},`);
line(`${indent(2)}},`);
group(`${indent(2)}\"load_points\": [`, "载荷点数组；当前是 F1、F2");
line(`${indent(3)}{`);
line(`${indent(4)}\"label\": \"F1\",`, "载荷点名称。");
line(`${indent(4)}\"height\": 11.414,`, "试验高度。");
line(`${indent(4)}\"height_unit\": \"mm\",`, "试验高度单位。");
line(`${indent(4)}\"force\": 11.9,`, "对应载荷。");
line(`${indent(4)}\"force_unit\": \"N\",`, "载荷单位。");
line(`${indent(4)}\"force_tolerance_percent\": 10,`, "图纸标注的载荷百分比公差。");
line(`${indent(4)}\"load_tolerance_upper\": 1.19,`, "换算后的载荷上偏差值。");
line(`${indent(4)}\"load_tolerance_lower\": -1.19,`, "换算后的载荷下偏差值。");
line(`${indent(4)}\"load_tolerance_percent\": 10,`, "当前采用的载荷百分比公差。");
line(`${indent(4)}\"deflection\": null,`, "压缩量；为空时可由自由长度减试验高度计算。");
line(`${indent(4)}\"deflection_unit\": \"mm\",`, "压缩量单位。");
line(`${indent(4)}\"test_height_type\": \"H1\",`, "试验高度代号。");
line(`${indent(4)}\"reference_only\": false,`, "是否只作参考、不作为强制验收点；F2 为 true。");
line(`${indent(4)}\"source\": [\"human_confirmed\", \"qwen_vision\"],`, "数据来源。");
line(`${indent(4)}\"evidence\": \"...\",`, "图纸中的原始证据文本。");
line(`${indent(4)}\"confidence\": 0.99,`, "识别/确认可信度。");
line(`${indent(4)}\"need_human_review\": false,`, "是否还需人工审核。");
line(`${indent(4)}\"page\": 1,`, "图纸页码。");
line(`${indent(4)}\"position\": null,`, "证据在图纸上的位置。");
line(`${indent(4)}\"suggested_region\": \"Qwen load point recognition\",`, "建议区域或识别来源说明。");
line(`${indent(4)}\"drawing_force_tolerance_percent\": 10,`, "原图载荷公差。");
line(`${indent(4)}\"tolerance_source\": \"standardization\",`, "公差来源。");
line(`${indent(4)}\"tolerance_basis\": \"表3-15...\"`, "公差采用的标准依据。");
line(`${indent(3)}},`);
line(`${indent(3)}{ \"label\": \"F2\", \"height\": 9.474, \"force\": 15.3, \"reference_only\": true }`);
line(`${indent(2)}],`);
group(`${indent(2)}\"torque_points\": [],`, "扭矩点数组；供扭转弹簧使用，本压缩弹簧为空");
group(`${indent(2)}\"technical_requirements\": [`, "技术要求数组");
line(`${indent(3)}{`);
line(`${indent(4)}\"type\": \"heat_treatment\",`, "要求类别，如 heat_treatment、surface、salt_spray、lifetime、environmental、other。");
line(`${indent(4)}\"content\": \"300°C+10°C/20min+1min\",`, "具体要求文字。");
line(`${indent(4)}\"confirmation_source\": \"human_confirmed\"`, "确认来源。");
line(`${indent(3)}}`);
line(`${indent(2)}]`);
line(`${indent(1)}},`);
group(`${indent(1)}\"derived_parameters\": {`, "从已确认主参数反算得到的辅助参数");
line(`${indent(2)}\"load_point_deflections\": [`, "每个载荷点的压缩量：自由长度减试验高度。");
line(`${indent(3)}{ \"label\": \"F1\", \"height\": 11.414, \"deflection\": 3.586, \"formula\": \"free_length - load_point.height\" }`);
line(`${indent(2)}],`);
line(`${indent(2)}\"mean_diameter\": { \"value\": 23.5, \"unit\": \"mm\", ... },`, "中径；可能来自图纸，也可能由内/外径和线径推导。");
line(`${indent(2)}\"spring_index\": { \"value\": 15.6667, ... },`, "旋绕比：中径 ÷ 线径。");
line(`${indent(2)}\"slenderness_ratio\": { \"value\": 0.6383, ... }`, "细长比：自由长度 ÷ 中径。");
line(`${indent(1)}}`);
line("}");

const outputWorkbook = Workbook.create();
const outputSheet = outputWorkbook.worksheets.add("字段说明");
const lastRow = guideRows.length;
outputSheet.getRange(`A1:C${lastRow}`).values = guideRows;
outputSheet.getRange(`B1:B${lastRow}`).format = {
  font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#77856E" },
  wrapText: true,
  verticalAlignment: "center",
};
outputSheet.getRange(`C1:C${lastRow}`).format = {
  font: { name: "Microsoft YaHei", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
for (const row of yellowRows) {
  outputSheet.getRange(`C${row}`).format = {
    fill: "#FFFF00",
    font: { name: "Microsoft YaHei", size: 10, bold: true },
    verticalAlignment: "center",
  };
}
outputSheet.getRange("A:A").format.columnWidth = 3;
outputSheet.getRange("B:B").format.columnWidth = 88;
outputSheet.getRange("C:C").format.columnWidth = 38;
outputSheet.getRange(`A1:C${lastRow}`).format.autofitRows();

await fs.mkdir(outputDir, { recursive: true });
const outputFile = await SpreadsheetFile.exportXlsx(outputWorkbook);
await outputFile.save(outputPath);
const outputCheck = await outputWorkbook.inspect({
  kind: "table",
  range: "字段说明!A1:C20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 3,
});
console.log(outputCheck.ndjson);
const outputErrors = await outputWorkbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(outputErrors.ndjson);
for (const [filename, range] of [
  ["reference_style_part1.png", "A1:C32"],
  ["reference_style_part2.png", "A33:C68"],
  ["reference_style_part3.png", `A69:C${lastRow}`],
]) {
  const outputPreview = await outputWorkbook.render({ sheetName: "字段说明", range, scale: 1.2, format: "png" });
  await fs.writeFile(`${outputDir}/${filename}`, new Uint8Array(await outputPreview.arrayBuffer()));
}
console.log(`OUTPUT=${outputPath}`);
