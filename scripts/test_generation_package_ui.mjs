import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const readinessStart = appSource.indexOf("function generationSourceParameter");
const readinessEnd = appSource.indexOf("function renderStandardizationHtml", readinessStart);
const packageStart = appSource.indexOf("function makeGenerationParameterPackage");
const packageEnd = appSource.indexOf("function downloadJson", packageStart);

assert.notEqual(readinessStart, -1, "generation readiness UI helpers must exist");
assert.notEqual(readinessEnd, -1, "generation readiness UI helper block must be complete");
assert.notEqual(packageStart, -1, "generation package helper must exist");
assert.notEqual(packageEnd, -1, "generation package helper block must be complete");

const context = {
  structuredClone,
  TECH_LABELS: { surface: "表面处理" },
  SPRING_TYPE_LABELS: { compression_spring: "压缩弹簧" },
  COMPRESSION_GENERATION_CORE_FIELDS: ["wire_diameter", "mean_diameter", "free_length", "total_coils", "active_coils", "handedness", "end_grinding", "end_coils_closed"],
  COMPRESSION_GENERATION_DEFAULTS: { wire_diameter: 3, mean_diameter: 23, free_length: 45, total_coils: 10, active_coils: 8, end_grinding: 1, end_coils_closed: 1 },
  COMPRESSION_GENERATION_UNITS: { wire_diameter: "mm", mean_diameter: "mm", free_length: "mm", total_coils: null, active_coils: null, handedness: null, end_grinding: null, end_coils_closed: null },
  COMPRESSION_GENERATION_LABELS: { wire_diameter: "线径", mean_diameter: "中径", free_length: "自由长度", total_coils: "总圈数", active_coils: "有效圈数", handedness: "旋向", end_grinding: "两端磨削", end_coils_closed: "端圈压并" },
  currentSpringType: (review) => review.drawing_summary?.spring_type || "unknown_spring",
  targetFieldLabel: (field) => ({ material: "材料", mean_diameter: "中径", active_coils: "有效圈数" }[field] || field),
};
vm.createContext(context);
vm.runInContext(appSource.slice(readinessStart, readinessEnd), context);
vm.runInContext(appSource.slice(packageStart, packageEnd), context);

const review = readyReview();
const readiness = context.assessGenerationReadiness(review);
assert.equal(readiness.status, "ready");
const packageData = context.makeGenerationParameterPackage(review);
assert.deepEqual(
  Object.keys(packageData.generation_parameters.spring_parameters),
  context.COMPRESSION_GENERATION_CORE_FIELDS,
);
assert.equal(packageData.generation_parameters.spring_parameters.mean_diameter.value, 18);
assert.equal(packageData.generation_parameters.spring_parameters.outer_diameter, undefined);
assert.equal(packageData.generation_parameters.spring_parameters.handedness.value, "right");
assert.equal(packageData.generation_parameters.spring_parameters.end_grinding.value, 1);
assert.equal(packageData.generation_parameters.spring_parameters.end_coils_closed.value, 1);
assert.equal(packageData.generation_parameters.spring_parameters.material, undefined);
assert.equal(packageData.generation_parameters.load_points, undefined);
assert.equal(packageData.generation_parameters.technical_requirements[0].content, "镀锌");

const directReview = structuredClone(review);
directReview.standard_selection = {
  selected_standard: null,
  status: "not_started",
  need_human_review: false,
  human_confirmed: false,
};
const directReadiness = context.assessGenerationReadiness(directReview);
assert.equal(directReadiness.status, "ready_with_warnings");
assert.equal(directReadiness.missing_fields.some((item) => item.field === "standard_no"), false);
assert.equal(directReadiness.pending_fields.some((item) => item.field === "standard_no"), false);
assert.equal(directReadiness.warnings.some((item) => item.field === "standard_no"), true);
const directPackage = context.makeGenerationParameterPackage(directReview);
assert.deepEqual(
  Object.keys(directPackage.generation_parameters.spring_parameters),
  Object.keys(packageData.generation_parameters.spring_parameters),
);
assert.equal(directPackage.standard_context.selected_standard, null);
assert.equal(directPackage.standard_context.human_confirmed, false);

const staleStandardization = structuredClone(review);
staleStandardization.derived_parameters_stale = true;
staleStandardization.standardization_results = [
  { target_field: "free_length", status: "stale", need_human_review: true, basis: "参数变化后建议已过期。" },
  { target_field: "surface", status: "suggested", need_human_review: false, basis: "标准化建议待处理。" },
];
const staleReadiness = context.assessGenerationReadiness(staleStandardization);
assert.equal(staleReadiness.status, "ready_with_warnings");
assert.equal(staleReadiness.pending_fields.length, 0);
assert.equal(staleReadiness.warnings.some((item) => item.field === "standardization"), true);
assert.equal(staleReadiness.warnings.some((item) => item.field === "surface"), true);

review.spring_parameters.active_coils.value = null;
assert.equal(context.assessGenerationReadiness(review).status, "needs_confirmation");
assert.equal(review.spring_parameters.active_coils.value, 8);
assert.equal(review.spring_parameters.active_coils.need_human_review, true);
const incompletePackage = context.makeGenerationParameterPackage(review);
assert.ok(incompletePackage);
assert.equal(incompletePackage.generation_parameters.spring_parameters.active_coils, undefined);
assert.equal(incompletePackage.standardization_trace, undefined);

console.log("generation package UI test passed");

function readyReview() {
  const param = (value, unit = null, extra = {}) => ({ value, unit, need_human_review: false, ...extra });
  return {
    drawing_summary: { spring_type: "compression_spring", drawing_no: "YD-001" },
    standard_selection: { selected_standard: "GB/T 1239.2-2009", human_confirmed: true },
    spring_parameters: {
      material: param("SUS304 raw", null, { standard_value: "SUS304" }),
      wire_diameter: param(2, "mm"),
      outer_diameter: param(20, "mm"),
      free_length: param(40, "mm"),
      total_coils: param(12, "turns"),
      active_coils: param(10, "turns"),
      handedness: param("右旋"),
      end_type: param("两端并紧"),
      end_grinding: param("两端磨平"),
      load_points: [{ label: "F1", height: 25, force: 100, need_human_review: false }],
    },
    technical_requirements: [{ type: "surface", content: "镀锌", standard_content: "公司内部镀锌", need_human_review: false }],
    derived_parameters: {},
    standardization_results: [],
  };
}
