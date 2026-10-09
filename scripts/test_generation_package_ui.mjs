import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { translationTestHelpers } from "./translation_ui_test_support.mjs";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const readinessStart = appSource.indexOf("function generationSourceParameter");
const readinessEnd = appSource.indexOf("function renderStandardizationHtml", readinessStart);
const packageStart = appSource.indexOf("function makeGenerationParameterPackage");
const packageEnd = appSource.indexOf("function downloadJson", packageStart);
const handednessStart = appSource.indexOf("function normalizeHandednessValue");
const handednessEnd = appSource.indexOf("function handednessOptionsHtml", handednessStart);

assert.notEqual(readinessStart, -1, "generation readiness UI helpers must exist");
assert.notEqual(readinessEnd, -1, "generation readiness UI helper block must be complete");
assert.notEqual(packageStart, -1, "generation package helper must exist");
assert.notEqual(packageEnd, -1, "generation package helper block must be complete");
assert.notEqual(handednessStart, -1, "handedness normalizer must exist");
assert.notEqual(handednessEnd, -1, "handedness normalizer block must be complete");

const context = {
  structuredClone,
  TECH_LABELS: { surface: "表面处理" },
  GENERATION_TECHNICAL_REQUIREMENT_LABELS: {
    surface: "表面处理",
    surface_roughness: "表面粗糙度",
    hardness: "硬度要求",
    heat_treatment: "热处理",
    salt_spray: "盐雾试验",
    environmental: "环保要求",
    lifetime: "寿命要求",
    process: "工艺要求",
    other: "其他要求",
  },
  SPRING_TYPE_LABELS: { compression_spring: "压缩弹簧" },
  COMPRESSION_GENERATION_CORE_FIELDS: ["wire_diameter", "mean_diameter", "free_length", "total_coils", "active_coils", "handedness", "end_grinding", "end_coils_closed"],
  COMPRESSION_GENERATION_EXPORT_FIELDS: ["material", "wire_diameter", "mean_diameter", "free_length", "total_coils", "active_coils", "handedness", "end_grinding", "end_coils_closed"],
  COMPRESSION_GENERATION_DEFAULTS: { wire_diameter: 3, mean_diameter: 23, free_length: 45, total_coils: 10, active_coils: 8, end_grinding: 1, end_coils_closed: 1 },
  COMPRESSION_GENERATION_UNITS: { material: null, wire_diameter: "mm", mean_diameter: "mm", free_length: "mm", total_coils: null, active_coils: null, handedness: null, end_grinding: null, end_coils_closed: null },
  COMPRESSION_GENERATION_LABELS: { material: "材料", wire_diameter: "线径", mean_diameter: "中径", free_length: "自由长度", total_coils: "总圈数", active_coils: "有效圈数", handedness: "旋向", end_grinding: "两端磨削", end_coils_closed: "端圈压并" },
  HANDEDNESS_OPTIONS: [{ value: "left", label: "左旋" }, { value: "right", label: "右旋" }],
  currentSpringType: (review) => review.drawing_summary?.spring_type || "unknown_spring",
  normalizeTechnicalRequirementType: (value) => String(value || "other").trim() || "other",
  normalizeLoadPointLabel: (value) => String(value || "").trim().replace(/\s+/g, " "),
  canonicalLoadPointLabel: (value) => String(value || "").trim().replace(/\s+/g, " ").toLocaleLowerCase(),
  ensureLoadPointIds: (review) => review,
  loadPointField: (point, index = -1) => `load_points.${String(point?.label || index + 1).trim() || index + 1}`,
  isValidLoadPoint: (point) => {
    const height = Number(point?.height);
    const force = Number(point?.force);
    return Boolean(String(point?.label || "").trim()) && Number.isFinite(height) && Number.isFinite(force) && height > 0 && force >= 0;
  },
  targetFieldLabel: (field) => ({ material: "材料", mean_diameter: "中径", active_coils: "有效圈数" }[field] || field),
  formatCompactNumber: (value) => Number.isInteger(Number(value)) ? String(Number(value)) : String(Number(Number(value).toFixed(4))),
};
vm.createContext(context);
translationTestHelpers(context);
const duplicateStart = appSource.indexOf("function technicalRequirementsAreDuplicates");
vm.runInContext(appSource.slice(duplicateStart, appSource.indexOf("function isDuplicateTechnicalRequirement", duplicateStart)), context);
vm.runInContext(appSource.slice(handednessStart, handednessEnd), context);
vm.runInContext(appSource.slice(readinessStart, readinessEnd), context);
vm.runInContext(appSource.slice(packageStart, packageEnd), context);

const review = readyReview();
const readiness = context.assessGenerationReadiness(review);
assert.equal(readiness.status, "ready");
const packageData = context.makeGenerationParameterPackage(review);
assert.deepEqual(
  Object.keys(packageData.generation_parameters.spring_parameters),
  context.COMPRESSION_GENERATION_EXPORT_FIELDS,
);
assert.equal(packageData.generation_parameters.spring_parameters.mean_diameter.value, 18);
assert.equal(packageData.generation_parameters.spring_parameters.outer_diameter, undefined);
assert.equal(packageData.generation_parameters.spring_parameters.handedness.value, "right");
assert.equal(packageData.generation_parameters.spring_parameters.end_grinding.value, 1);
assert.equal(packageData.generation_parameters.spring_parameters.end_coils_closed.value, 1);
assert.equal(packageData.solidworks_preview.modelParameters["有效圈数n"], 10);
assert.equal(packageData.solidworks_preview.modelParameters["是否磨平"], 1);
assert.equal(packageData.solidworks_preview.modelParameters["工作高度H1"], 25);
assert.equal(packageData.solidworks_preview.modelParameters["工作高度H2"], null);
assert.equal(packageData.solidworks_preview.TaskId, undefined);
assert.equal(packageData.generation_parameters.spring_parameters.material.value, "SUS304 raw");
assert.equal(JSON.stringify(packageData.generation_parameters.load_points), JSON.stringify([{
  label: "F1",
  height: { value: 25, unit: "mm" },
  force: { value: 100, unit: "N", tolerance_upper: null, tolerance_lower: null },
  confirmation_source: "human_confirmed",
}]));
assert.equal(packageData.generation_parameters.technical_requirements[0].content, "镀锌");
assert.equal(packageData.generation_parameters.technical_requirements[0].requirement_id, undefined);
assert.equal(packageData.generation_parameters.technical_requirements_text, "1.表面处理：镀锌");

const pendingRequirementReview = structuredClone(review);
pendingRequirementReview.technical_requirements[0].requirement_id = "techreq-confirmed";
pendingRequirementReview.technical_requirements.push({
  requirement_id: "techreq-pending",
  type: "other",
  content: "待确认内容不会进入参数包。",
  need_human_review: true,
});
const filteredPackage = context.makeGenerationParameterPackage(pendingRequirementReview);
assert.equal(filteredPackage.generation_parameters.technical_requirements.length, 1);
assert.deepEqual(
  Object.keys(filteredPackage.generation_parameters.technical_requirements[0]),
  ["type", "content", "confirmation_source"],
);
assert.equal(filteredPackage.generation_parameters.technical_requirements_text, "1.表面处理：镀锌");

const formattedRequirementsReview = structuredClone(review);
formattedRequirementsReview.technical_requirements = [
  { type: "surface", content: "表面处理：表面镀锌。", need_human_review: false },
  { type: "salt_spray", content: "盐雾试验: 96小时。", need_human_review: false },
  { type: "process", content: "去除毛刺。\n不得有锐边。", need_human_review: false },
];
assert.equal(
  context.makeGenerationParameterPackage(formattedRequirementsReview).generation_parameters.technical_requirements_text,
  "1.表面处理：表面镀锌。\n2.盐雾试验：96小时。\n3.工艺要求：去除毛刺。；不得有锐边。",
);

const noRequirementsReview = structuredClone(review);
noRequirementsReview.technical_requirements = [];
assert.equal(context.makeGenerationParameterPackage(noRequirementsReview).generation_parameters.technical_requirements_text, "");
const originalNumberReview = structuredClone(review);
originalNumberReview.technical_requirements = [{ type: "other", content: "9.未注尺寸以3D为准", original_number: "9", need_human_review: false }];
assert.equal(context.makeGenerationParameterPackage(originalNumberReview).generation_parameters.technical_requirements_text, "1.其他要求：未注尺寸以3D为准");
delete originalNumberReview.technical_requirements[0].original_number;
assert.equal(context.makeGenerationParameterPackage(originalNumberReview).generation_parameters.technical_requirements_text, "1.其他要求：未注尺寸以3D为准");
originalNumberReview.technical_requirements[0].content = "12.5 mm";
originalNumberReview.technical_requirements[0].original_number = "12";
assert.equal(context.makeGenerationParameterPackage(originalNumberReview).generation_parameters.technical_requirements_text, "1.其他要求：12.5 mm");

const engineeringNoteReview = structuredClone(review);
const engineeringNote = { requirement_id: "3d-note", type: "other", content: "未注尺寸以3D为准", need_human_review: false };
engineeringNoteReview.technical_requirements = [engineeringNote];
assert.match(context.makeGenerationParameterPackage(engineeringNoteReview).generation_parameters.technical_requirements_text, /未注尺寸以3D为准/);
Object.assign(engineeringNote, { need_human_review: true, translation_status: "not_required" });
assert.equal(context.makeGenerationParameterPackage(engineeringNoteReview).generation_parameters.technical_requirements_text, "");
Object.assign(engineeringNote, { need_human_review: false, translation_status: "failed", translation_error: "翻译改变了数值或公差",
  translation_input_snapshot: { content: engineeringNote.content, type: "other" } });
assert.equal(context.makeGenerationParameterPackage(engineeringNoteReview).generation_parameters.technical_requirements_text, "");

const pendingRoughnessReview = structuredClone(review);
pendingRoughnessReview.spring_parameters.surface_roughness_ra = {
  value: 12.5,
  unit: "μm",
  surface_location: "两端面",
  need_human_review: true,
};
assert.equal(
  context.makeGenerationParameterPackage(pendingRoughnessReview).generation_parameters.technical_requirements_text,
  "1.表面处理：镀锌",
);
const confirmedRoughnessReview = structuredClone(pendingRoughnessReview);
confirmedRoughnessReview.spring_parameters.surface_roughness_ra.need_human_review = false;
const roughnessPackage = context.makeGenerationParameterPackage(confirmedRoughnessReview);
assert.equal(roughnessPackage.generation_parameters.technical_requirements_text, "1.两端面粗糙度 Ra 12.5μm\n2.表面处理：镀锌");
assert.equal(roughnessPackage.generation_parameters.technical_requirements[0].type, "surface_roughness");
assert.equal(roughnessPackage.generation_parameters.spring_parameters.surface_roughness_ra, undefined);

assert.match(appSource, /active_coils[^]*surface_roughness_ra[^]*end_coils/);
assert.match(appSource, /data-role="roughness-candidate"/);

const pendingLoadPointReview = structuredClone(review);
pendingLoadPointReview.spring_parameters.load_points.push({ label: "F2", height: 30, force: 150, need_human_review: true });
const pendingLoadReadiness = context.assessGenerationReadiness(pendingLoadPointReview);
assert.equal(pendingLoadReadiness.status, "needs_confirmation");
assert.ok(pendingLoadReadiness.pending_fields.some((item) => item.field === "load_points.F2"));
const filteredLoadPackage = context.makeGenerationParameterPackage(pendingLoadPointReview);
assert.equal(filteredLoadPackage.generation_parameters.load_points.length, 1);

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

const ungroundReview = structuredClone(review);
ungroundReview.spring_parameters.end_grinding.value = "两端不磨削";
const ungroundPackage = context.makeGenerationParameterPackage(ungroundReview);
assert.equal(ungroundPackage.generation_parameters.spring_parameters.end_grinding.value, 0);
assert.equal(ungroundPackage.solidworks_preview.modelParameters["是否磨平"], 0);

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
assert.equal(incompletePackage.solidworks_preview.modelParameters["有效圈数n"], null);
assert.equal(incompletePackage.standardization_trace, undefined);

const warningFixtures = JSON.parse(fs.readFileSync(new URL("./fixtures/technical_translation_warning_pairs.json", import.meta.url), "utf8"));
const warningReview = readyReview();
warningReview.technical_requirements = warningFixtures.map((fixture) => ({ ...fixture, need_human_review: false, translation_status: "translated",
  translation_warnings: [{ category: fixture.expected_category, original: fixture.original_content, translated: fixture.content }],
  translation_warning_snapshot: { content: fixture.content, type: fixture.type } }));
const warningText = context.makeGenerationParameterPackage(warningReview).generation_parameters.technical_requirements_text;
assert.ok(warningText.includes("STsKBA") && warningText.includes("B-1-1.5"));
assert.ok(warningText.startsWith("1.") && warningText.includes("\n2.") && !warningText.startsWith("技术要求\n"));
warningReview.technical_requirements[0].need_human_review = true;
assert.ok(!context.makeGenerationParameterPackage(warningReview).generation_parameters.technical_requirements_text.includes("STsKBA"));
warningReview.technical_requirements[0].need_human_review = false;
const downloads = [];
const action = { source_mode: "local", can_download: true };
warningReview.standardization_chat = [{ generation_package_export: action }];
Object.assign(context, { state: { review: warningReview, lastJob: null, pendingReviewAuditEvents: [], reviewPersistenceSaving: false },
  flushReviewPersistence: async () => true, generationPackageExportDisplayStatus: () => "ready",
  updateGenerationPackageExportAction: (_index, patch) => Object.assign(action, patch),
  updateLatestReviewMessage() {}, downloadJson: (data) => downloads.push(data) });
const exportStart = appSource.indexOf("async function executeGenerationPackageExport");
vm.runInContext(appSource.slice(exportStart, appSource.indexOf("function renderAccuracyStandardizationResultHtml", exportStart)), context);
assert.equal(await context.exportCurrentGenerationPackage(), true);
assert.equal(await context.executeGenerationPackageExport(action, 0), true, action.failure_reason);
assert.equal(downloads.length, 2);
for (const downloaded of downloads) assert.equal(downloaded.generation_parameters.technical_requirements_text, warningText);
context.state.pendingReviewAuditEvents.push({ target_field: "technical_requirements.warning" });
context.flushReviewPersistence = async () => false;
assert.equal(await context.exportCurrentGenerationPackage(), false);
assert.equal(await context.executeGenerationPackageExport(action, 0), false);
assert.equal(downloads.length, 2, "neither export entry downloads unpersisted translation confirmations");
assert.equal(warningReview.technical_requirements[0].translation_warnings.length, 1, "failed saves preserve the local warning result");

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
