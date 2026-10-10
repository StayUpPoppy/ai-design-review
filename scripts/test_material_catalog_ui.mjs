import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

// Deliberately independent expected values: catches accidental source-table drift.
const materials = [
  ["SWPB", "SWP-B", 78000, ["SWPB", "SWP-B"]],
  ["SWPA 琴钢丝", "SWP-A", 78000, ["SWPA", "SWP-A"]],
  ["SWC 硬钢线", "SWC", 78000, ["SWC", "SW-C"]],
  ["SUS304 不锈钢", "SUS304", 71500, ["SUS304"]],
  ["SUS316 不锈钢", "SUS316", 71500, ["SUS316"]],
  ["SUS631 不锈钢", "SUS631", 73500, ["SUS631"]],
  ["65Mn 弹簧钢", "65Mn", 78000, ["65Mn"]],
  ["60Si2Mn 硅锰钢", "60Si2Mn", 78000, ["60Si2Mn"]],
  ["50CrVA 铬钒钢", "50CrVA", 78000, ["50CrVA"]],
  ["Inconel X750 镍基合金钢", "Inconel X750", 79000, ["INCONEL X750", "INCONEL X-750", "INCONEL 750", "lnconelX750镍基合金钢"]],
  ["70碳素钢", "70#", 79000, ["70#", "70碳素钢"]],
  ["55CrSi合金钢", "55CrSi", 79000, ["55CrSi"]],
  ["17-4PH不锈钢", "17-4PH", 76000, ["17-4PH"]],
  ["17-7PH不锈钢", "17-7PH", 75500, ["17-7PH"]],
  ["Inconel 718 镍基合金钢", "Inconel 718", 77200, ["INCONEL 718", "lnconel718镍基合金钢"]],
];

export const catalogFixture = {
  version: "company-materials/test-v1", source: "公司材料表固定参考值（模拟数据）",
  items: materials.map(([display_name, standard_value, shear_modulus_mpa, aliases], index) => ({ id: String(index + 1), display_name, standard_value, shear_modulus_mpa, aliases })),
};

export const confirmedParam = (value, unit = null, extra = {}) => ({ value, unit, source: ["human_confirmed"], need_human_review: false, ...extra });

export function materialReviewFixture(material = {}) {
  return {
    drawing_summary: { spring_type: "compression_spring", spring_type_label: "压缩弹簧", drawing_name: "材料下拉回归（模拟测试数据）", drawing_no: "DEMO-MATERIAL" },
    spring_parameters: {
      material: confirmedParam("SUS304 不锈钢", null, { raw_value: "SUS304", standard_value: "SUS304", material_id: "4", material_catalog_version: catalogFixture.version, material_selection_source: "drawing", material_match_status: "matched", ...material }),
      standard_no: confirmedParam("GB/T 1239.2-2009"), accuracy_grade: confirmedParam("2级"),
      wire_diameter: confirmedParam(2, "mm"), outer_diameter: confirmedParam(20, "mm"), inner_diameter: confirmedParam(16, "mm"), mean_diameter: confirmedParam(18, "mm"),
      free_length: confirmedParam(40, "mm"), solid_height: confirmedParam(24, "mm"),
      total_coils: confirmedParam(12, "turns"), active_coils: confirmedParam(10, "turns"), surface_roughness_ra: confirmedParam(12.5, "μm"),
      handedness: confirmedParam("right"), end_type: confirmedParam("两端并紧"), end_grinding: confirmedParam("两端磨削"),
      pitch: confirmedParam(3.6, "mm"), support_coils: confirmedParam(1, "turns"), spring_rate: confirmedParam(8.8, "N/mm"), load_points: [],
    },
    technical_requirements: [], standardization_results: [], derived_parameters: {},
    manual_confirmations: { material: { confirmation_state: "human_confirmed", value: material.value ?? "SUS304 不锈钢" } },
    change_history: [], parameter_reasonableness: { status: "ok", issues: [], suggestions: [] },
    balloons: [{ field: "material", number: 1, value: material.value ?? "SUS304 不锈钢" }],
  };
}

function materialFunctionBlocks(source) {
  // Production declarations are top-level; nested braces are indented. Do not
  // evaluate app startup/DOM listeners in this isolated read-only VM.
  return [...source.matchAll(/^(?:async )?function ([A-Za-z_$][\w$]*)\([^]*?^\}/gm)]
    .filter((match) => /material/i.test(match[1]) || match[1] === "parameterRowHtml").map((match) => match[0]).join("\n");
}

export async function runMaterialUiTests() {
  const source = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
  const context = {
    state: { review: materialReviewFixture(), apiBaseUrl: "", materialCatalog: { ...structuredClone(catalogFixture), status: "ready", error: "", apiBaseUrl: "" } },
    currentSpringType: (review) => review?.drawing_summary?.spring_type || "compression_spring",
    sourceValues: (value) => Array.isArray(value) ? value : [value].filter(Boolean),
    escapeHtml: (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;"),
    structuredClone, Set, Map, console,
    document: { querySelectorAll: () => [] },
    materialCatalogRequestSerial: 0, materialCatalogPromise: null,
    FIELD_LABELS: {}, pendingDefaultCandidateNotice: () => "", reasonablenessSeverityForField: () => "",
    accuracyGradeStatusLabel: () => "", parameterUnitLabel: (field, name) => ({ name, unit: "", text: name }),
    parameterUnitLabelHtml: (label) => label.name, parameterValueControlHtml: () => "<input>",
    formatTolerance: () => "", confirmationButtonHtml: () => "<button>确认</button>",
  };
  vm.createContext(context);
  const functions = materialFunctionBlocks(source);
  assert.match(functions, /function applyMaterialSelection\(/, "Material selection helper must exist");
  vm.runInContext(functions, context);
  const original = { value: "SUS304 不锈钢", standard_value: "SUS304", raw_value: "SUS304 ГОСТ 5632-72", material_id: "4", material_catalog_version: catalogFixture.version, source: ["qwen_vision"], need_human_review: false };
  const selected = structuredClone(original);
  assert.equal(context.applyMaterialSelection(selected, "SUS316 不锈钢"), true);
  assert.equal(selected.value, "SUS316 不锈钢");
  assert.equal(selected.standard_value, "SUS316");
  assert.equal(String(selected.material_id), "5");
  assert.equal(selected.material_catalog_version, catalogFixture.version);
  assert.equal(selected.raw_value, original.raw_value, "Choice must retain original drawing material");
  assert.equal(selected.material_selection_source, "manual");
  const beforeInvalid = JSON.stringify(selected);
  assert.equal(context.applyMaterialSelection(selected, "SUS316L"), false, "UI helper must reject arbitrary new material strings");
  assert.equal(JSON.stringify(selected), beforeInvalid);
  assert.equal(context.applyMaterialSelection(selected, ""), true);
  assert.ok(selected.value == null || selected.value === "");
  assert.ok(selected.standard_value == null || selected.standard_value === "");
  assert.ok(selected.material_id == null || selected.material_id === "");
  assert.equal(selected.raw_value, original.raw_value);
  const legacyWithoutOriginal = { value: "旧人工材料", source: ["human_edited"], need_human_review: false };
  assert.equal(context.applyMaterialSelection(legacyWithoutOriginal, "SUS304 不锈钢"), true);
  assert.ok(!Object.hasOwn(legacyWithoutOriginal, "raw_value"), "Missing drawing evidence must not be invented from historical manual values");
  const legacy = { value: "ХН70МВТЮБ ГОСТ 5632-72", standard_value: "ХН70МВТЮБ", raw_value: "ХН70МВТЮБ ГОСТ 5632-72", need_human_review: false };
  const frozen = JSON.stringify(legacy);
  assert.equal(context.applyMaterialSelection(legacy, "ХН70МВТЮБ ГОСТ 5632-72"), false);
  assert.equal(JSON.stringify(legacy), frozen, "Compatibility value is not a new catalog option");
  const htmlBefore = JSON.stringify(context.state.review);
  const html = context.materialOptionsHtml(legacy);
  assert.equal((html.match(/<option /g) || []).length, 17);
  assert.match(html, /selected disabled>原有材料/);
  const noteHtml = context.materialSelectionNotesHtml({ ...legacy, raw_value: '<script>ХН70МВТЮБ</script>',
    material_selection_source: "drawing_substitute", material_substitution_evidence: { evidence: '允许换用 <script>INCONEL750</script>' } });
  assert.ok(!noteHtml.includes("<script>"));
  assert.ok(noteHtml.includes("&lt;script&gt;"));
  assert.ok(noteHtml.includes("查看替代依据") && !noteHtml.includes("<details open"));
  for (const need_human_review of [true, false]) {
    const compactParam = { ...original, material_selection_source: "manual", need_human_review };
    const compactBefore = JSON.stringify(compactParam);
    const compactHtml = context.materialSelectionNotesHtml(compactParam);
    assert.match(compactHtml, /class="material-selection-notes" hidden><\/div>/);
    assert.doesNotMatch(compactHtml, /当前材料：|原图材料：|公司材料表固定参考值/);
    assert.equal(JSON.stringify(compactParam), compactBefore, "Compact display must not remove raw material or selection metadata");
  }
  const emptyNotes = context.materialSelectionNotesHtml({ value: "", raw_value: "SUS304" });
  assert.match(emptyNotes, /原图材料未匹配公司材料目录，请选择/);
  assert.doesNotMatch(emptyNotes, /class="material-selection-notes" hidden/);
  assert.match(context.materialSelectionNotesHtml({ value: "", material_match_status: "conflict" }), /识别到多个材料候选/);
  const refreshedNotes = { innerHTML: "", hidden: false };
  const refreshRow = { querySelector: (selector) => selector === ".material-selection-notes" ? refreshedNotes : null };
  context.refreshMaterialSelectionRow(refreshRow, original);
  assert.equal(refreshedNotes.hidden, true);
  context.refreshMaterialSelectionRow(refreshRow, { value: "", raw_value: "SUS304" });
  assert.equal(refreshedNotes.hidden, false);
  context.state.materialCatalog.status = "error";
  context.state.materialCatalog.error = "模拟请求失败";
  context.refreshMaterialSelectionRow(refreshRow, original);
  assert.equal(refreshedNotes.hidden, false);
  assert.match(refreshedNotes.innerHTML, /重试加载材料/);
  context.state.materialCatalog.status = "ready";
  context.state.materialCatalog.error = "";
  context.refreshMaterialSelectionRow(refreshRow, original);
  assert.equal(refreshedNotes.hidden, true);
  assert.equal(JSON.stringify(context.state.review), htmlBefore);
  const oldRate = { value: 2.4348, need_human_review: true, source: ["formula_calculation"],
    formula_recommendation_stale: true, formula_material_catalog_stale: true,
    formula_calculation_reason: "公司材料表 G 已更新，请核对 <新刚度>。" };
  const oldRateBefore = JSON.stringify(oldRate);
  const oldRateHtml = context.parameterRowHtml("spring_rate", oldRate, { label: "刚度" });
  assert.match(oldRateHtml, /公式参考待更新/);
  assert.match(oldRateHtml, /parameter-formula-reference-note/);
  assert.ok(oldRateHtml.includes("&lt;新刚度&gt;"));
  assert.equal(JSON.stringify(oldRate), oldRateBefore, "Formula warnings must not alter historical values or confirmation");
  const confirmedRateHtml = context.parameterRowHtml("spring_rate", { value: 2.45, need_human_review: false, source: ["formula_calculation"] }, { label: "刚度" });
  assert.match(confirmedRateHtml, /公式计算已确认/);

  const requests = [];
  context.apiFetch = () => new Promise((resolve) => requests.push(resolve));
  context.state.apiBaseUrl = "https://first.test";
  const first = context.ensureMaterialCatalog({ force: true });
  assert.equal(context.state.materialCatalog.status, "loading");
  context.state.apiBaseUrl = "https://second.test";
  const second = context.ensureMaterialCatalog({ force: true });
  requests[1]({ ok: true, json: async () => ({ ...structuredClone(catalogFixture), version: "second-version" }) });
  assert.equal(await second, true);
  requests[0]({ ok: true, json: async () => ({ ...structuredClone(catalogFixture), version: "obsolete-version" }) });
  assert.equal(await first, false);
  assert.equal(context.state.materialCatalog.version, "second-version", "Old endpoint response cannot overwrite current directory");
  assert.equal(context.state.materialCatalog.apiBaseUrl, "https://second.test");
  assert.equal(JSON.stringify(context.state.review), htmlBefore, "Directory async responses cannot change review values");
  const failed = context.ensureMaterialCatalog({ force: true });
  requests[2]({ ok: false, json: async () => ({ detail: "模拟连接失败" }) });
  assert.equal(await failed, false);
  assert.equal(context.state.materialCatalog.status, "error");
  assert.equal(await context.ensureMaterialCatalog(), false);
  assert.equal(requests.length, 3, "Failed directory does not retry repeatedly without explicit force");
  const retry = context.ensureMaterialCatalog({ force: true });
  requests[3]({ ok: true, json: async () => structuredClone(catalogFixture) });
  assert.equal(await retry, true);
  assert.equal(context.state.materialCatalog.status, "ready");
  assert.equal(JSON.stringify(context.state.review), htmlBefore);
  console.log("PASS: material identity/raw preservation, legacy/escaping, async endpoint protection and explicit failure retry");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await runMaterialUiTests();
