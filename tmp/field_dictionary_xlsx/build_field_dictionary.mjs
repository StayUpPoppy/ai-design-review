import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "D:/YingKe/ai-design-review/outputs/field_dictionary_20260727";
const outputPath = `${outputDir}/compression_spring_generation_parameters_field_dictionary.xlsx`;

const topLevel = [
  ["schema_version", "文本", "spring_generation_parameters/v1", "参数包结构版本，供下游程序选择正确的解析规则。", "系统兼容", "是"],
  ["package_type", "文本", "confirmed_compression_spring_generation_input", "参数包业务类型，说明这是已确认的压缩弹簧生图输入。", "路由/校验", "是"],
  ["generated_at", "ISO 8601 时间", "导出于 2026-07-27T07:21:45.111Z", "参数包导出时间，用于追溯与版本管理。", "追溯", "否"],
  ["export_policy", "对象", "2 个子字段", "导出筛选与就绪规则。", "下游校验", "建议"],
  ["source", "对象", "4 个子字段", "图纸、零件和弹簧类型来源信息。", "标题栏/订单关联", "建议"],
  ["standard_context", "对象", "3 个子字段", "适用标准与标准确认状态。", "标准标注/合规", "建议"],
  ["generation_parameters", "对象", "4 个子字段", "真正用于生图或制造的业务输入。", "生图主输入", "是"],
  ["derived_parameters", "对象", "4 个子字段", "由已确认主参数反算得到的辅助数据。", "校验/辅助标注", "可选"],
];

const parameterRows = [
  ["材料与标准", "material", "材料", "SUS304", "弹簧材料。"],
  ["材料与标准", "standard_no", "标准号", "GB/T 1239.2-2009", "产品采用的技术标准。"],
  ["材料与标准", "accuracy_grade", "通用精度等级", "2级", "尺寸与性能公差的适用精度等级。"],
  ["几何尺寸", "wire_diameter", "线径", "1.5 mm", "弹簧丝直径。"],
  ["几何尺寸", "outer_diameter", "外径", "25 mm", "弹簧外径。"],
  ["几何尺寸", "inner_diameter", "内径", "22 mm", "弹簧内径。"],
  ["几何尺寸", "mean_diameter", "中径", "23.5 mm", "弹簧平均直径，常用于刚度与旋绕比计算。"],
  ["几何尺寸", "free_length", "自由长度", "15 mm", "未受力状态下的轴向长度。"],
  ["几何尺寸", "solid_height", "压并高度", "6.2 mm", "弹簧完全压并时的高度。"],
  ["圈数与端部", "total_coils", "总圈数", "4 turns", "弹簧全部圈数。"],
  ["圈数与端部", "active_coils", "有效圈数", "3 turns", "参与弹性变形的有效圈数。"],
  ["圈数与端部", "handedness", "旋向", "right", "绕制方向。"],
  ["圈数与端部", "end_type", "端部形式", "closed_and_ground", "端圈闭合、磨平等结构形式。"],
  ["圈数与端部", "end_grinding", "端面磨削", "两端磨平", "端面加工要求。"],
  ["性能与限值", "spring_rate", "刚度", "1.154 N/mm", "单位压缩量对应的载荷变化。"],
  ["性能与限值", "perpendicularity", "垂直度", "0.75 mm", "端面或轴线的垂直度限值。"],
  ["性能与限值", "permanent_set_limit", "永久变形限值", "0.045 mm", "规定工况后的最大永久变形。"],
];

const detailRows = [
  ["元数据", "schema_version", "schema_version", "文本", "spring_generation_parameters/v1", "参数包结构版本。", "系统兼容", "是"],
  ["元数据", "package_type", "package_type", "文本", "confirmed_compression_spring_generation_input", "参数包业务类型。", "下游路由", "是"],
  ["元数据", "generated_at", "generated_at", "时间文本", "导出于 2026-07-27T07:21:45.111Z", "生成时间。", "追溯", "否"],
  ["导出规则", "export_policy.parameter_filter", "parameter_filter", "文本", "human_confirmed_only", "仅将人工确认的字段放入正式参数区。", "避免使用未确认识别值", "建议"],
  ["导出规则", "export_policy.readiness_is_advisory", "readiness_is_advisory", "布尔", "true", "就绪检查仅作提示，未齐套也可下载。", "下游应自行决定是否拒收", "建议"],
  ["来源信息", "source.drawing_no", "drawing_no", "文本", "YD4765020175", "图号。", "标题栏/订单关联", "建议"],
  ["来源信息", "source.drawing_name", "drawing_name", "文本", "UQD06外弹簧(钢珠型)", "图纸或零件名称。", "标题栏", "建议"],
  ["来源信息", "source.spring_type", "spring_type", "文本", "compression_spring", "机器可读的弹簧类型。", "选择生图模板", "是"],
  ["来源信息", "source.spring_type_label", "spring_type_label", "文本", "压缩弹簧", "人类可读的弹簧类型。", "标题/显示", "否"],
  ["标准上下文", "standard_context.selected_standard", "selected_standard", "文本", "GB/T 1239.2-2009", "选用的技术标准。", "标准标注/合规", "建议"],
  ["标准上下文", "standard_context.selection_status", "selection_status", "文本", "applicable", "标准适用状态。", "下游合规判断", "建议"],
  ["标准上下文", "standard_context.human_confirmed", "human_confirmed", "布尔", "false", "标准选择是否经过显式人工确认。", "下游审核", "建议"],
  ["生图参数", "generation_parameters.spring_parameters", "spring_parameters", "对象", "17 个参数", "压缩弹簧的材料、几何、端部、性能主参数集合。", "绘图/制造主输入", "是"],
  ["生图参数", "generation_parameters.load_points", "load_points", "数组", "F1、F2", "指定高度下的载荷验收点。", "性能标注/验收", "建议"],
  ["生图参数", "generation_parameters.torque_points", "torque_points", "数组", "[]", "扭转弹簧的扭矩点；本压缩弹簧为空。", "扭簧专用", "否"],
  ["生图参数", "generation_parameters.technical_requirements", "technical_requirements", "数组", "6 条", "热处理、表面、盐雾、寿命、环保等要求。", "技术要求区", "建议"],
  ["参数记录通用结构", "generation_parameters.spring_parameters.<参数>.label", "label", "文本", "线径", "参数中文显示名称。", "显示/标注", "否"],
  ["参数记录通用结构", "generation_parameters.spring_parameters.<参数>.value", "value", "数值或文本", "1.5", "参数的正式确认值。", "绘图/制造", "是"],
  ["参数记录通用结构", "generation_parameters.spring_parameters.<参数>.unit", "unit", "文本或空", "mm", "参数单位。", "单位换算/标注", "是"],
  ["参数记录通用结构", "generation_parameters.spring_parameters.<参数>.tolerance_upper", "tolerance_upper", "数值或空", "0.05", "参数上公差。", "尺寸标注", "建议"],
  ["参数记录通用结构", "generation_parameters.spring_parameters.<参数>.tolerance_lower", "tolerance_lower", "数值或空", "-0.05", "参数下公差。", "尺寸标注", "建议"],
  ["参数记录通用结构", "generation_parameters.spring_parameters.<参数>.confirmation_source", "confirmation_source", "文本", "human_confirmed", "参数确认来源。", "审计/安全校验", "建议"],
  ...parameterRows.map(([group, key, label, example, meaning]) => ["主参数：" + group, `generation_parameters.spring_parameters.${key}`, key, "参数记录", example, meaning, "生图主输入", "是"]),
  ["载荷点", "generation_parameters.load_points[].label", "label", "文本", "F1", "载荷点标识。", "载荷标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].height", "height", "数值", "11.414", "试验或工作高度。", "性能标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].height_unit", "height_unit", "文本", "mm", "高度单位。", "单位标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].force", "force", "数值", "11.9", "指定高度对应的载荷。", "性能标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].force_unit", "force_unit", "文本", "N", "载荷单位。", "单位标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].force_tolerance_percent", "force_tolerance_percent", "数值", "10", "图纸标注的载荷百分比公差。", "性能标注", "可选"],
  ["载荷点", "generation_parameters.load_points[].deflection", "deflection", "数值或空", "null", "压缩量；未给出时可由自由长度减高度计算。", "辅助计算", "可选"],
  ["载荷点", "generation_parameters.load_points[].deflection_unit", "deflection_unit", "文本", "mm", "压缩量单位。", "辅助计算", "可选"],
  ["载荷点", "generation_parameters.load_points[].load_tolerance_upper", "load_tolerance_upper", "数值", "1.19", "标准化后的载荷上偏差。", "性能标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].load_tolerance_lower", "load_tolerance_lower", "数值", "-1.19", "标准化后的载荷下偏差。", "性能标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].load_tolerance_percent", "load_tolerance_percent", "数值", "10", "当前采用的载荷百分比公差。", "性能标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].test_height_type", "test_height_type", "文本", "H1", "试验高度代号。", "性能标注", "建议"],
  ["载荷点", "generation_parameters.load_points[].reference_only", "reference_only", "布尔", "false", "是否仅作参考、非强制验收点。", "决定是否画为控制点", "建议"],
  ["载荷点留痕", "generation_parameters.load_points[].source", "source", "数组", "[human_confirmed, qwen_vision]", "载荷点数据来源。", "追溯", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].evidence", "evidence", "文本", "图纸技术要求原文", "从图纸提取的证据文本。", "追溯", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].confidence", "confidence", "数值", "0.99", "识别或确认置信度。", "审核", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].need_human_review", "need_human_review", "布尔", "false", "是否仍需要人工复核。", "下游安全校验", "建议"],
  ["载荷点留痕", "generation_parameters.load_points[].page", "page", "整数", "1", "证据所在图纸页码。", "追溯", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].position", "position", "对象或空", "null", "证据在图纸上的坐标。", "追溯", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].suggested_region", "suggested_region", "文本", "Qwen load point recognition", "识别建议区域或来源说明。", "追溯", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].drawing_force_tolerance_percent", "drawing_force_tolerance_percent", "数值", "10", "原图载荷百分比公差。", "追溯/对比", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].tolerance_source", "tolerance_source", "文本", "standardization", "载荷公差的来源。", "追溯", "否"],
  ["载荷点留痕", "generation_parameters.load_points[].tolerance_basis", "tolerance_basis", "文本", "表3-15…", "载荷公差的标准依据。", "追溯", "否"],
  ["技术要求", "generation_parameters.technical_requirements[].type", "type", "枚举文本", "heat_treatment", "要求类别：热处理、表面、盐雾、寿命、环保或其他。", "选择图纸区域/模板", "建议"],
  ["技术要求", "generation_parameters.technical_requirements[].content", "content", "文本", "720h无红锈", "具体技术要求内容。", "技术要求区", "建议"],
  ["技术要求", "generation_parameters.technical_requirements[].confirmation_source", "confirmation_source", "文本", "human_confirmed", "技术要求确认来源。", "追溯", "否"],
  ["派生参数", "derived_parameters.load_point_deflections", "load_point_deflections", "数组", "2 项", "各载荷点的压缩量计算结果。", "辅助标注/校验", "可选"],
  ["派生参数", "derived_parameters.load_point_deflections[].label", "label", "文本", "F1", "对应的载荷点标识。", "辅助标注", "可选"],
  ["派生参数", "derived_parameters.load_point_deflections[].height", "height", "数值", "11.414", "载荷点高度。", "辅助计算", "可选"],
  ["派生参数", "derived_parameters.load_point_deflections[].height_unit", "height_unit", "文本", "mm", "高度单位。", "辅助计算", "可选"],
  ["派生参数", "derived_parameters.load_point_deflections[].deflection", "deflection", "数值", "3.586", "自由长度减载荷点高度所得压缩量。", "辅助标注/校验", "可选"],
  ["派生参数", "derived_parameters.load_point_deflections[].deflection_unit", "deflection_unit", "文本", "mm", "压缩量单位。", "辅助计算", "可选"],
  ["派生参数", "derived_parameters.load_point_deflections[].formula", "formula", "文本", "free_length - load_point.height", "派生计算公式。", "追溯", "否"],
  ["派生参数", "derived_parameters.load_point_deflections[].source_fields", "source_fields", "数组", "[free_length, load_points]", "计算使用的源字段。", "追溯", "否"],
  ["派生参数", "derived_parameters.mean_diameter", "mean_diameter", "派生记录", "23.5 mm", "中径的派生或确认记录。", "辅助校验", "可选"],
  ["派生参数", "derived_parameters.spring_index", "spring_index", "派生记录", "15.6667", "旋绕比：中径 ÷ 线径。", "设计校验", "可选"],
  ["派生参数", "derived_parameters.slenderness_ratio", "slenderness_ratio", "派生记录", "0.6383", "细长比：自由长度 ÷ 中径。", "设计校验", "可选"],
  ["派生记录通用结构", "derived_parameters.<参数>.field", "field", "文本", "spring_index", "派生参数名称。", "辅助识别", "否"],
  ["派生记录通用结构", "derived_parameters.<参数>.value", "value", "数值", "15.6667", "派生计算值。", "辅助校验", "可选"],
  ["派生记录通用结构", "derived_parameters.<参数>.unit", "unit", "文本或空", "mm", "派生值单位。", "单位标注", "可选"],
  ["派生记录通用结构", "derived_parameters.<参数>.source", "source", "数组", "[derived, generation_export]", "派生数据来源标识。", "追溯", "否"],
  ["派生记录通用结构", "derived_parameters.<参数>.formula", "formula", "文本", "mean_diameter / wire_diameter", "计算公式。", "追溯", "否"],
  ["派生记录通用结构", "derived_parameters.<参数>.source_fields", "source_fields", "数组", "[mean_diameter, wire_diameter]", "参与计算的源字段。", "追溯", "否"],
  ["派生记录通用结构", "derived_parameters.<参数>.confidence", "confidence", "数值", "0.99", "派生值可信度。", "审核", "否"],
  ["派生记录通用结构", "derived_parameters.<参数>.need_human_review", "need_human_review", "布尔", "false", "派生值是否仍需人工复核。", "审核", "建议"],
];

const coreInput = [
  ["材料", "SUS304", "", "材料与标准"],
  ["标准号", "GB/T 1239.2-2009", "", "材料与标准"],
  ["精度等级", "2级", "", "材料与标准"],
  ["线径", 1.5, "mm", "几何尺寸"],
  ["外径", 25, "mm", "几何尺寸"],
  ["内径", 22, "mm", "几何尺寸"],
  ["中径", 23.5, "mm", "几何尺寸"],
  ["自由长度", 15, "mm", "几何尺寸"],
  ["压并高度", 6.2, "mm", "几何尺寸"],
  ["总圈数", 4, "turns", "圈数与端部"],
  ["有效圈数", 3, "turns", "圈数与端部"],
  ["旋向", "right", "", "圈数与端部"],
  ["端部形式", "closed_and_ground", "", "圈数与端部"],
  ["端面磨削", "两端磨平", "", "圈数与端部"],
  ["刚度", 1.154, "N/mm", "性能与限值"],
  ["垂直度", 0.75, "mm", "性能与限值"],
  ["永久变形限值", 0.045, "mm", "性能与限值"],
];

const workbook = Workbook.create();
const overview = workbook.worksheets.add("字段总览");
const dictionary = workbook.worksheets.add("字段说明");
const input = workbook.worksheets.add("生图输入摘要");

const navy = "#1F4E78";
const blue = "#D9EAF7";
const teal = "#0F766E";
const lightTeal = "#E8F5F1";
const gray = "#F4F6F8";
const border = "#D5DCE4";

function title(sheet, text, endColumn) {
  sheet.mergeCells(`A1:${endColumn}1`);
  sheet.getRange("A1").values = [[text]];
  sheet.getRange("A1").format = {
    fill: navy,
    font: { bold: true, color: "#FFFFFF", size: 16 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange("A1").format.rowHeight = 28;
}

function styleHeader(range, fill = navy) {
  range.format = {
    fill,
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: border },
  };
}

function styleBody(range) {
  range.format = {
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: border },
  };
}

title(overview, "压缩弹簧生成参数包：字段总览", "F");
overview.getRange("A3:F3").values = [["顶层字段", "数据类型", "当前示例", "功能", "下游用途", "是否建议生图端读取"]];
overview.getRange(`A4:F${3 + topLevel.length}`).values = topLevel;
styleHeader(overview.getRange("A3:F3"));
styleBody(overview.getRange(`A4:F${3 + topLevel.length}`));
overview.getRange("A13:F13").merge();
overview.getRange("A13").values = [["使用说明：生图端优先读取 generation_parameters；source 与 standard_context 用于标题栏、类型路由和标准标注；derived_parameters 仅作辅助校验或自动补标。"]];
overview.getRange("A13").format = { fill: lightTeal, font: { color: teal, italic: true }, wrapText: true, verticalAlignment: "center" };
overview.getRange("A13").format.rowHeight = 34;
overview.getRange("A3:F11").format.autofitColumns();
overview.getRange("A:A").format.columnWidth = 25;
overview.getRange("B:B").format.columnWidth = 17;
overview.getRange("C:C").format.columnWidth = 38;
overview.getRange("D:D").format.columnWidth = 32;
overview.getRange("E:E").format.columnWidth = 24;
overview.getRange("F:F").format.columnWidth = 18;
overview.getRange(`A4:F${3 + topLevel.length}`).format.autofitRows();
overview.freezePanes.freezeRows(3);
overview.showGridLines = false;
overview.tables.add(`A3:F${3 + topLevel.length}`, true, "TopLevelFields");

title(dictionary, "字段说明（compression_spring_generation_parameters (9).json）", "H");
dictionary.getRange("A3:H3").values = [["大类", "字段路径", "字段", "数据类型", "当前示例", "字段含义", "生图端用途", "是否必读"]];
dictionary.getRange(`A4:H${3 + detailRows.length}`).values = detailRows;
styleHeader(dictionary.getRange("A3:H3"));
styleBody(dictionary.getRange(`A4:H${3 + detailRows.length}`));
dictionary.getRange(`A4:A${3 + detailRows.length}`).format.fill = gray;
dictionary.getRange(`H4:H${3 + detailRows.length}`).conditionalFormats.add("containsText", { text: "是", format: { fill: "#DFF2E5", font: { bold: true, color: "#166534" } } });
dictionary.getRange(`H4:H${3 + detailRows.length}`).conditionalFormats.add("containsText", { text: "建议", format: { fill: "#FFF5D6", font: { color: "#8A5A00" } } });
dictionary.getRange("A3:H3").format.rowHeight = 26;
dictionary.getRange("A:A").format.columnWidth = 20;
dictionary.getRange("B:B").format.columnWidth = 52;
dictionary.getRange("C:C").format.columnWidth = 27;
dictionary.getRange("D:D").format.columnWidth = 16;
dictionary.getRange("E:E").format.columnWidth = 34;
dictionary.getRange("F:F").format.columnWidth = 44;
dictionary.getRange("G:G").format.columnWidth = 26;
dictionary.getRange("H:H").format.columnWidth = 13;
dictionary.getRange(`A4:H${3 + detailRows.length}`).format.autofitRows();
dictionary.freezePanes.freezeRows(3);
dictionary.freezePanes.freezeColumns(2);
dictionary.showGridLines = false;
dictionary.tables.add(`A3:H${3 + detailRows.length}`, true, "FieldDictionary");

title(input, "生图输入摘要（已确认参数）", "E");
input.getRange("A3:E3").values = [["字段", "当前值", "单位", "分组", "生图用途"]];
const coreRows = coreInput.map(([field, value, unit, group]) => [field, value, unit, group, group === "性能与限值" ? "性能/验收标注" : "几何或标题栏输入"]);
input.getRange(`A4:E${3 + coreRows.length}`).values = coreRows;
styleHeader(input.getRange("A3:E3"), teal);
styleBody(input.getRange(`A4:E${3 + coreRows.length}`));
input.getRange(`A4:A${3 + coreRows.length}`).format.fill = lightTeal;
const loadStart = 22;
input.getRange(`A${loadStart}:E${loadStart}`).merge();
input.getRange(`A${loadStart}`).values = [["载荷点"]];
input.getRange(`A${loadStart}`).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "left" };
input.getRange(`A${loadStart + 1}:E${loadStart + 1}`).values = [["载荷点", "试验高度", "载荷", "是否仅参考", "用途"]];
input.getRange(`A${loadStart + 2}:E${loadStart + 3}`).values = [
  ["F1", "11.414 mm", "11.9 N ±10%", "否", "控制/验收载荷点"],
  ["F2", "9.474 mm", "15.3 N ±10%", "是", "参考载荷点"],
];
styleHeader(input.getRange(`A${loadStart + 1}:E${loadStart + 1}`), teal);
styleBody(input.getRange(`A${loadStart + 2}:E${loadStart + 3}`));
const techStart = 27;
input.getRange(`A${techStart}:E${techStart}`).merge();
input.getRange(`A${techStart}`).values = [["技术要求"]];
input.getRange(`A${techStart}`).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "left" };
input.getRange(`A${techStart + 1}:C${techStart + 1}`).values = [["类别", "内容", "用途"]];
input.getRange(`A${techStart + 2}:C${techStart + 7}`).values = [
  ["热处理", "300°C+10°C/20min+1min", "技术要求区"],
  ["表面", "产品不可有油污、研磨粉尘，表面毛刺小于线径的10%", "技术要求区"],
  ["盐雾", "720h无红锈", "技术要求区"],
  ["寿命", "L1-L2-L1一秒钟一次,4万次内不可失效,力衰保证10%之内", "技术要求区"],
  ["环保", "禁用物质符合GB/T 30512-2014《汽车禁用物质要求》", "技术要求区"],
  ["其他", "未注尺寸以3D为准", "技术要求区"],
];
styleHeader(input.getRange(`A${techStart + 1}:C${techStart + 1}`), teal);
styleBody(input.getRange(`A${techStart + 2}:C${techStart + 7}`));
input.getRange("A:A").format.columnWidth = 20;
input.getRange("B:B").format.columnWidth = 54;
input.getRange("C:C").format.columnWidth = 25;
input.getRange("D:D").format.columnWidth = 20;
input.getRange("E:E").format.columnWidth = 28;
input.freezePanes.freezeRows(3);
input.showGridLines = false;
input.tables.add(`A3:E${3 + coreRows.length}`, true, "CoreDrawingInputs");

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const inspection = await workbook.inspect({
  kind: "table",
  range: "字段说明!A1:H15",
  include: "values,formulas",
  tableMaxRows: 15,
  tableMaxCols: 8,
});
console.log(inspection.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);
const previews = [
  ["字段总览", "A1:F13", "overview_preview.png"],
  ["字段说明", "A1:H28", "field_dictionary_preview.png"],
  ["生图输入摘要", "A1:E34", "drawing_input_preview.png"],
];
for (const [sheetName, range, filename] of previews) {
  const preview = await workbook.render({ sheetName, range, scale: 1.3, format: "png" });
  await fs.writeFile(`${outputDir}/${filename}`, new Uint8Array(await preview.arrayBuffer()));
}
console.log(`OUTPUT=${outputPath}`);
