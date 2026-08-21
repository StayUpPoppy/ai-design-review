import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = appSource.indexOf("function generationPackageExportBaseline");
const end = appSource.indexOf("function renderAccuracyStandardizationResultHtml", start);
assert.notEqual(start, -1, "generation package chat helpers must exist");
assert.notEqual(end, -1, "generation package chat helper block must be complete");
assert.match(
  appSource,
  /finalTurn\?\.generation_package_export\?\.automatic_download[\s\S]*executeGenerationPackageExport/,
  "new export turns must trigger an immediate browser download",
);

const downloads = [];
let refreshCount = 0;
const review = readyReview();
const state = {
  review,
  lastJob: { job_id: "review-1", review_revision: 5 },
  activeReviewMessageId: "message-1",
  pendingReviewAuditEvents: [],
  reviewPersistenceSaving: false,
};
const context = {
  console,
  structuredClone,
  state,
  COMPRESSION_GENERATION_CORE_FIELDS: [
    "wire_diameter", "mean_diameter", "free_length", "total_coils",
    "active_coils", "handedness", "end_grinding", "end_coils_closed",
  ],
  FIELD_LABELS: {
    wire_diameter: "线径", mean_diameter: "中径", free_length: "自由长度",
    total_coils: "总圈数", active_coils: "有效圈数", handedness: "旋向",
    end_grinding: "两端磨削", end_coils_closed: "端圈压并", standard_no: "标准号",
  },
  currentSpringType: (value) => value?.drawing_summary?.spring_type || "unknown_spring",
  generationSourceParameter: (parameters, field) => parameters?.[field] || null,
  targetFieldLabel: (field) => context.FIELD_LABELS[field] || field,
  formatStandardValue: (value, unit = "") => value == null || value === "" ? "-" : `${value}${unit}`,
  escapeHtml: (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;"),
  getReviewContext: () => ({ review: state.review }),
  refreshReviewSurfaces: () => { refreshCount += 1; },
  activateReviewContext: () => state.review,
  flushReviewPersistence: async () => true,
  apiFetch: async () => ({
    ok: true,
    json: async () => ({
      review_revision: 5,
      parameter_package: { schema_version: "spring_generation_parameters/v1", trusted: true },
    }),
  }),
  assessGenerationReadiness: () => ({ status: "ready", summary: "可以导出" }),
  makeGenerationParameterPackage: () => ({ schema_version: "spring_generation_parameters/v1", local: true }),
  downloadJson: (data, filename) => downloads.push({ data, filename }),
  updateLatestReviewMessage: () => {},
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

const baseline = context.generationPackageExportBaseline(review);
const serverAction = makeAction({ baseline_state: baseline });
review.standardization_chat = [{ generation_package_export: serverAction }];

const html = context.renderGenerationPackageExportHtml(serverAction, 0);
assert.match(html, /参数包可以导出/);
assert.match(html, /线径/);
assert.match(html, /中径/);
assert.match(html, /未执行标准化检查/);
assert.match(html, /去处理/);
assert.doesNotMatch(html, />mean_diameter</);
assert.match(html, /仅下载JSON，不会创建生图任务/);

assert.equal(await context.executeGenerationPackageExport(serverAction, 0, "message-1"), true);
assert.equal(downloads.length, 1);
assert.deepEqual(downloads[0].data, { schema_version: "spring_generation_parameters/v1", trusted: true });
assert.equal(downloads[0].filename, "compression_spring_generation_parameters.json");
assert.equal(serverAction.download_status, "downloaded");
assert.equal(serverAction.automatic_download, false);
assert.ok(refreshCount >= 2);
assert.match(context.renderGenerationPackageExportHtml(serverAction, 0), /重新下载/);

review.spring_parameters.free_length.value = 46;
assert.equal(context.generationPackageExportDisplayStatus(serverAction), "stale");
review.spring_parameters.free_length.value = 45;
state.lastJob.review_revision = 6;
assert.equal(context.generationPackageExportDisplayStatus(serverAction), "stale");
assert.match(context.renderGenerationPackageExportHtml(serverAction, 0), /导出结果已过期/);

const localAction = makeAction({
  source_mode: "local",
  review_revision: null,
  baseline_state: context.generationPackageExportBaseline(review),
});
review.standardization_chat = [{ generation_package_export: localAction }];
state.lastJob = null;
assert.equal(await context.executeGenerationPackageExport(localAction, 0, "message-1"), true);
assert.deepEqual(downloads[1].data, { schema_version: "spring_generation_parameters/v1", local: true });

review.spring_parameters.mean_diameter.value = 24;
assert.equal(context.generationPackageExportDisplayStatus(localAction), "stale");

review.spring_parameters.mean_diameter.value = 23;
state.lastJob = { job_id: "review-1", review_revision: 5 };
const conflictAction = makeAction({ baseline_state: context.generationPackageExportBaseline(review) });
review.standardization_chat = [{ generation_package_export: conflictAction }];
context.apiFetch = async () => ({
  ok: false,
  status: 409,
  json: async () => ({ detail: { generation_readiness: { summary: "参数已变化" } } }),
});
assert.equal(await context.executeGenerationPackageExport(conflictAction, 0, "message-1"), false);
assert.equal(conflictAction.download_status, "stale");
assert.match(conflictAction.failure_reason, /参数已变化/);

console.log("generation package chat UI test passed");

function makeAction(overrides = {}) {
  return {
    status: "ready_with_warnings",
    source_mode: "server",
    filename: "compression_spring_generation_parameters.json",
    schema_version: "spring_generation_parameters/v1",
    review_revision: 5,
    can_download: true,
    automatic_download: true,
    action_type: "download_generation_package",
    parameter_fields: [
      { field: "wire_diameter", label: "线径", value: 3, unit: "mm" },
      { field: "mean_diameter", label: "mean_diameter", value: 23, unit: "mm" },
    ],
    missing_fields: [],
    pending_fields: [],
    blocking_reasonableness: [],
    warnings: [{ field: "standard_no", label: "适用标准", reason: "未执行标准化检查。" }],
    download_status: "pending",
    downloaded_at: null,
    failure_reason: "",
    ...overrides,
  };
}

function readyReview() {
  const confirmed = (value, unit = null) => ({ value, unit, need_human_review: false });
  return {
    drawing_summary: { spring_type: "compression_spring" },
    spring_parameters: {
      wire_diameter: confirmed(3, "mm"),
      mean_diameter: confirmed(23, "mm"),
      free_length: confirmed(45, "mm"),
      total_coils: confirmed(10),
      active_coils: confirmed(8),
      handedness: confirmed("right"),
      end_grinding: confirmed(1),
      end_coils_closed: confirmed(1),
    },
    technical_requirements: [{ type: "process", content: "两端磨平", need_human_review: false }],
    standardization_chat: [],
  };
}
