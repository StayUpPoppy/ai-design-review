import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");
function block(start, end) {
  const first = source.indexOf(start), last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `Missing function block: ${start}`);
  return source.slice(first, last);
}
const context = {
  state: { review: { spring_parameters: {}, technical_requirements: [] }, loadPointUndo: null },
  FIELD_LABELS: {},
  sourceValues: (value) => Array.isArray(value) ? value : [value].filter(Boolean),
  pendingDefaultCandidateNotice: () => "",
  reasonablenessSeverityForField: () => "",
  accuracyGradeStatusLabel: () => "",
  surfaceRoughnessCandidatesHtml: () => "",
  formatFieldInput: (param) => param.value ?? "",
  formatTolerance: (param) => param.tolerance_upper == null ? "" : `±${param.tolerance_upper}`,
  confirmationButtonHtml: (param) => `<button class="confirm-button${param.need_human_review ? "" : " confirmed"}">${param.need_human_review ? "确认" : "已确认"}</button>`,
  loadPointToleranceDisplay: (point) => ({ value: point.display_tolerance || "", placeholder: "", title: point.tolerance_basis || "", note: "" }),
  ensureLoadPointIds: () => {},
  isValidLoadPoint: () => true,
  loadPointTableHeadHtml: () => "",
  escapeHtml: (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;"),
};
vm.createContext(context);
vm.runInContext(block("function parameterDisplayUnit", "function surfaceRoughnessCandidatesHtml"), context);
vm.runInContext(block("function parameterValueControlHtml", "function normalizeHandednessValue"), context);
vm.runInContext(block("function loadPointRowHtml", "function loadPointToleranceDisplay"), context);

const fixtures = [
  ["wire_diameter", "线径", { value: 1.8, unit: "mm" }, { unit: "mm", required: true }, "线径（mm）"],
  ["outer_diameter", "外径", { value: 27, unit: "mm", need_human_review: false }, {}, "外径（mm）"],
  ["free_length", "自由长度", { value: null }, { unit: "mm" }, "自由长度（mm）"],
  ["total_coils", "总圈数", { value: 10, unit: "turns" }, {}, "总圈数（圈）"],
  ["active_coils", "有效圈数（圈）", { value: 8, unit: "turns" }, {}, "有效圈数（圈）"],
  ["support_coils", "支承圈数（单端）", { value: 1, unit: "turns" }, {}, "支承圈数（单端）（圈）"],
  ["surface_roughness_ra", "表面粗糙度 Ra（μm）", { value: 12.5, unit: "μm" }, { unit: "μm" }, "表面粗糙度 Ra（μm）"],
  ["surface_roughness_ra", "表面粗糙度 Ra (µm)", { value: 12.5, unit: "µm" }, { unit: "μm" }, "表面粗糙度 Ra（μm）"],
  ["spring_rate", "刚度", { value: 1.8331, unit: "N/mm", tolerance_upper: .1833 }, {}, "刚度（N/mm）"],
  ["pitch", "节距", { value: 2.5, unit: " " }, { unit: "mm" }, "节距（mm）"],
  ["custom", "自定义参数", { value: 0 }, {}, "自定义参数"],
  ["wire_diameter", "线径（mm）", { value: .18, unit: "cm" }, { unit: "mm" }, "线径（cm）"],
];
for (const [field, label, param, meta, expected] of fixtures) {
  param.need_human_review ??= true;
  const before = JSON.stringify({ param, meta });
  const display = context.parameterUnitLabel(field, label, param, meta);
  assert.equal(display.text, expected);
  const html = context.parameterRowHtml(field, param, { ...meta, label });
  assert.ok(html.includes(`title="${expected}"`), expected);
  assert.ok(html.includes(`aria-label="${expected}数值"`), expected);
  assert.ok(html.includes(`aria-label="${expected}公差"`), expected);
  assert.ok(html.includes(`value="${param.value ?? ""}"`));
  assert.equal(JSON.stringify({ param, meta }), before, "Unit labels must not mutate values, units or confirmation flags");
  if (meta.required) assert.match(html, /<\/span> \*<\/strong>/);
  if (field === "surface_roughness_ra") assert.equal((html.match(/class="parameter-label-unit"/g) || []).length, 1);
}
for (const field of ["material", "standard_no", "accuracy_grade", "diameter_accuracy_grade", "free_length_accuracy_grade", "load_accuracy_grade", "stiffness_accuracy_grade", "handedness", "end_type", "end_grinding", "end_coils_closed", "hook_type", "controlled_diameter_field"]) {
  assert.equal(context.parameterUnitLabel(field, "非数值选项", { unit: "mm" }, {}).text, "非数值选项");
}
const solid = { value: 20, unit: "mm", need_human_review: true, source: ["formula_calculation"] };
const solidHtml = context.parameterRowHtml("solid_height", solid, { label: "压并高度", unit: "mm" });
assert.match(solidHtml, /title="压并高度（参考）（mm）"/);
assert.match(solidHtml, /公式参考 \/ 待确认/);
const escaped = context.parameterUnitLabelHtml(context.parameterUnitLabel("custom", '<script>"', { unit: '<img src=x>' }, {}));
assert.ok(!escaped.includes("<script>") && !escaped.includes("<img src=x>"));
assert.ok(escaped.includes("&lt;script&gt;"));

for (const point of [
  { load_point_id: "one", label: "F1", height: 18, force: 16, display_tolerance: "±0.8", need_human_review: false },
  { load_point_id: "two", label: "F2", height: 1.8, force: 3, height_unit: "cm", force_unit: "kN", display_tolerance: "±10%", tolerance_basis: "图纸依据", need_human_review: true },
]) {
  const before = JSON.stringify(point);
  const html = context.loadPointRowHtml(point, 0);
  const heightUnit = point.height_unit || "mm", forceUnit = point.force_unit || "N";
  assert.ok(html.includes(`高度<span class="parameter-label-unit">（${heightUnit}）</span>`));
  assert.ok(html.includes(`力值<span class="parameter-label-unit">（${forceUnit}）</span>`));
  assert.match(html, new RegExp(`<strong title="${point.label}">${point.label}</strong>`));
  assert.ok(html.includes(`aria-label="${point.label}高度（${heightUnit}）"`));
  assert.ok(html.includes(`aria-label="${point.label}力值（${forceUnit}）"`));
  assert.ok(html.includes(`value="${point.display_tolerance}"`));
  assert.ok(html.includes(`绝对公差单位与力值一致（${forceUnit}）`));
  assert.equal(JSON.stringify(point), before);
}
const section = context.renderLoadPointSectionHtml(context.state.review, []);
assert.ok(section.includes('高度<span class="parameter-label-unit">（mm）</span>'));
assert.ok(section.includes('力值<span class="parameter-label-unit">（N）</span>'));
assert.ok(section.includes("绝对公差单位与力值一致；百分比公差使用 %。"));
assert.match(styles, /\.data-row\[data-kind="param"\] \.data-label strong\s*\{[^}]*white-space: normal;/);
assert.match(styles, /\.parameter-label-unit\s*\{[^}]*white-space: nowrap;/);
console.log("PASS: parameter/load-point units, qualifiers, accessible labels, escaping and read-only rendering");
