import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const readinessStart = appSource.indexOf("function assessGenerationReadiness");
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
  COMPRESSION_GENERATION_CORE_FIELDS: ["material", "wire_diameter", "free_length", "total_coils", "active_coils", "handedness", "end_grinding"],
  CONTROLLED_DIAMETER_FIELDS: ["outer_diameter", "inner_diameter", "mean_diameter"],
  currentSpringType: (review) => review.drawing_summary?.spring_type || "unknown_spring",
  targetFieldLabel: (field) => ({ material: "材料", outer_diameter: "外径" }[field] || field),
};
vm.createContext(context);
vm.runInContext(appSource.slice(readinessStart, readinessEnd), context);
vm.runInContext(appSource.slice(packageStart, packageEnd), context);

const review = readyReview();
const readiness = context.assessGenerationReadiness(review);
assert.equal(readiness.status, "ready");
const packageData = context.makeGenerationParameterPackage(review);
assert.equal(packageData.generation_parameters.spring_parameters.material.value, "SUS304");
assert.equal(packageData.generation_parameters.spring_parameters.outer_diameter.value, 20);
assert.equal(packageData.generation_parameters.technical_requirements[0].content, "公司内部镀锌");

review.spring_parameters.active_coils.value = null;
assert.equal(context.assessGenerationReadiness(review).status, "needs_input");
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
      end_grinding: param("两端磨平"),
      load_points: [{ label: "F1", height: 25, force: 100, need_human_review: false }],
    },
    technical_requirements: [{ type: "surface", content: "镀锌", standard_content: "公司内部镀锌", need_human_review: false }],
    derived_parameters: {},
    standardization_results: [],
  };
}
