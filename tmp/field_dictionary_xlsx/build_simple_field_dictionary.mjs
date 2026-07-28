import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "D:/YingKe/ai-design-review/outputs/simple_field_dictionary_20260727";
const outputPath = `${outputDir}/compression_spring_generation_parameters_field_guide.xlsx`;

const rows = [];
const sectionRows = [];
const headerRows = [];
const section = (name, description = "") => {
  rows.push([name, description]);
  sectionRows.push(rows.length);
};
const header = () => {
  rows.push(["字段", "含义"]);
  headerRows.push(rows.length);
};
const item = (field, meaning) => rows.push([field, meaning]);

header();
item("schema_version", "JSON 结构版本，供程序按正确格式解析。");
item("package_type", "包的业务类型：已确认的压缩弹簧生图输入。");
item("generated_at", "参数包生成时间。");
item("export_policy", "导出规则。");
item("source", "图纸与弹簧来源信息。");
item("standard_context", "适用标准及确认状态。");
item("generation_parameters", "生图/制造的主参数。");
item("derived_parameters", "从主参数计算出的辅助参数。");

section("export_policy");
header();
item("parameter_filter", "导出筛选规则；human_confirmed_only 表示仅导出人工确认的数据。");
item("readiness_is_advisory", "就绪检查是否只作提示；true 表示即使未齐套，系统也允许导出。");

section("source");
header();
item("drawing_no", "图号。");
item("drawing_name", "图纸/零件名称。");
item("spring_type", "程序使用的弹簧类型编码，如 compression_spring。");
item("spring_type_label", "给人看的弹簧类型名称，如“压缩弹簧”。");

section("standard_context");
header();
item("selected_standard", "当前采用的标准，如 GB/T 1239.2-2009。");
item("selection_status", "标准适用状态，如 applicable。");
item("human_confirmed", "标准选择是否被显式人工确认。");

section("generation_parameters", "这是最核心的大类，包含四部分。");
section("spring_parameters", "它是“参数名 → 参数记录”的集合。每个参数记录的通用字段如下。");
header();
item("label", "中文显示名称。");
item("value", "参数值。");
item("unit", "单位，如 mm、N/mm、turns。");
item("tolerance_upper", "上公差。");
item("tolerance_lower", "下公差。");
item("confirmation_source", "确认来源；当前是 human_confirmed。");

section("spring_parameters 当前包含的业务参数");
header();
item("material", "材料，如 SUS304。");
item("standard_no", "产品适用标准号。");
item("accuracy_grade", "通用精度等级。");
item("wire_diameter", "线径。");
item("outer_diameter", "外径。");
item("inner_diameter", "内径。");
item("mean_diameter", "中径。");
item("free_length", "自由长度。");
item("solid_height", "压并高度。");
item("total_coils", "总圈数。");
item("active_coils", "有效圈数。");
item("handedness", "旋向。");
item("end_type", "端部形式。");
item("end_grinding", "端面磨削要求。");
item("spring_rate", "刚度，单位通常是 N/mm。");
item("perpendicularity", "垂直度要求。");
item("permanent_set_limit", "永久变形限值。");

section("load_points", "载荷点数组；当前是 F1、F2。每个载荷点的字段含义如下。");
header();
item("label", "载荷点名称，如 F1、F2。");
item("height / height_unit", "试验高度及单位。");
item("force / force_unit", "对应载荷及单位。");
item("force_tolerance_percent", "图纸标注的载荷百分比公差。");
item("load_tolerance_upper / load_tolerance_lower", "换算后的载荷上下偏差值。");
item("load_tolerance_percent", "当前实际采用的载荷百分比公差。");
item("deflection / deflection_unit", "压缩量及单位；为空时可由自由长度减试验高度计算。");
item("test_height_type", "试验高度代号，如 H1、H2。");
item("reference_only", "是否只作参考、不作为强制验收点。当前 F2 为 true。");
item("source", "数据来源，如人工确认、视觉识别。");
item("evidence", "图纸中的原始证据文本。");
item("confidence", "识别/确认可信度。");
item("need_human_review", "是否还需人工审核。");
item("page / position / suggested_region", "图纸页码、位置、建议区域，用于定位证据。");
item("drawing_force_tolerance_percent", "原图载荷公差。");
item("tolerance_source", "公差来源，如标准化计算。");
item("tolerance_basis", "公差采用的标准依据。");

section("torque_points", "扭矩点数组，给扭转弹簧使用。当前压缩弹簧为空数组。");
section("technical_requirements", "技术要求数组。每条只有三项。");
header();
item("type", "要求类别，如 heat_treatment、surface、salt_spray、lifetime、environmental、other。");
item("content", "具体要求文字。");
item("confirmation_source", "确认来源。");

section("derived_parameters", "这是程序从已确认主参数反算出来的数据，不是人工录入源数据。");
header();
item("load_point_deflections", "每个载荷点的压缩量：自由长度减试验高度。记录中包含 F1/F2 名称、高度、压缩量、公式及源字段。");
item("mean_diameter", "中径；可能来自图纸，也可能由内/外径和线径推导。");
item("spring_index", "旋绕比：中径 ÷ 线径。");
item("slenderness_ratio", "细长比：自由长度 ÷ 中径。");

section("派生记录通用字段", "后三类派生记录的通用字段如下。");
header();
item("field", "派生参数名。");
item("value / unit", "计算值与单位。");
item("source", "标识这是导出阶段计算的派生数据。");
item("formula", "计算公式。");
item("source_fields", "参与计算的原始字段。");
item("confidence", "推导可信度。");
item("need_human_review", "是否还需复核。");

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("字段说明");
const lastRow = rows.length;
sheet.getRange(`A1:B${lastRow}`).values = rows;
sheet.getRange(`A1:B${lastRow}`).format = {
  font: { name: "Microsoft YaHei", size: 10 },
  wrapText: true,
  verticalAlignment: "top",
};

for (const row of sectionRows) {
  const range = sheet.getRange(`A${row}:B${row}`);
  range.format = {
    font: { name: "Microsoft YaHei", size: 10, bold: true },
    verticalAlignment: "center",
    borders: { bottom: { style: "thin", color: "#808080" } },
  };
  range.format.rowHeight = 20;
}

for (const row of headerRows) {
  const range = sheet.getRange(`A${row}:B${row}`);
  range.format = {
    font: { name: "Microsoft YaHei", size: 10, bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { bottom: { style: "thin", color: "#808080" } },
  };
  range.format.rowHeight = 20;
}

sheet.getRange("A:A").format.columnWidth = 44;
sheet.getRange("B:B").format.columnWidth = 92;
sheet.getRange(`A1:B${lastRow}`).format.autofitRows();
sheet.freezePanes.freezeRows(1);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const inspection = await workbook.inspect({
  kind: "table",
  range: "字段说明!A1:B24",
  include: "values,formulas",
  tableMaxRows: 24,
  tableMaxCols: 2,
});
console.log(inspection.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const ranges = [
  ["simple_field_guide_part1.png", "A1:B34"],
  ["simple_field_guide_part2.png", "A34:B71"],
  ["simple_field_guide_part3.png", `A72:B${lastRow}`],
];
for (const [filename, range] of ranges) {
  const preview = await workbook.render({ sheetName: "字段说明", range, scale: 1.2, format: "png" });
  await fs.writeFile(`${outputDir}/${filename}`, new Uint8Array(await preview.arrayBuffer()));
}
console.log(`OUTPUT=${outputPath}`);
