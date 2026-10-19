import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const context = vm.createContext({ structuredClone });
vm.runInContext(fs.readFileSync("frontend/surface-roughness-reference.js", "utf8"), context);
const service = context.SurfaceRoughnessReference;
const missing = () => ({ value: null, unit: "μm", source: [], need_human_review: true, evidence: "", page: 1, position: null });
for (const value of [null, "", "  "]) assert.equal(service.eligible({ ...missing(), value }), true);
for (const value of [12.5, 6.3, 0, -1, false, "NaN", "abc", Infinity]) {
  const item = { ...missing(), value }, before = JSON.stringify(item);
  assert.equal(service.eligible(item), false);
  assert.equal(service.adopt(item), false);
  assert.equal(JSON.stringify(item), before, "Existing/invalid values are never replaced");
}
for (const extra of [{ unit: "mm" }, { roughness_conflict: true }, { derived_value_stale: true }, { formula_recommendation_stale: true }, { roughness_candidates: [{ value: 6.3 }] }]) {
  const item = { ...missing(), ...extra };
  assert.equal(service.adopt(item), false);
  assert.equal(item.value, null);
}
for (const value of [12.5, 6.3]) {
  const item = { ...missing(), confirmation_snapshot: { value } };
  assert.equal(service.adopt(item, value), true);
  assert.equal(item.value, value);
  assert.equal(item.need_human_review, true);
  assert.equal(item.confirmation_snapshot, undefined);
  assert.ok(service.summary(item).includes("人工采用项目参考"));
}
for (const value of [0, -1, 3.2, "6.3", NaN, Infinity]) assert.equal(service.adopt(missing(), value), false);
assert.equal(service.eligible({ ...missing(), source: ["human_edited"], roughness_candidates: [{ value: 6.3 }] }), false);
const evidenceFixtures = JSON.parse(fs.readFileSync("scripts/fixtures/roughness_evidence.json", "utf8"));
for (const row of evidenceFixtures) assert.equal(service.assessEvidence(row.value, row.text, Boolean(row.structured))[0], row.status, row.text);
const longEvidence = "Ra12.5或Ra6.3。我们再看，surface_roughness_ra应核对，need_human_review=true。";
const oldItem = { ...missing(), value: 6.3, source: ["qwen_vision"], evidence: longEvidence,
  roughness_candidates: [{ value: 12.5, location: "两端面", evidence: longEvidence, page: 1, source: "qwen_vision" }, { value: 6.3, evidence: longEvidence }] };
const beforeOld = JSON.stringify(oldItem);
assert.equal(service.candidateEvidence(oldItem.roughness_candidates[0])[0], "unverified");
assert.equal(service.evidenceEntries(oldItem).length, 1, "Repeated original evidence renders once");
assert.ok(service.summary(oldItem).includes("依据不足"));
assert.equal(JSON.stringify(oldItem), beforeOld, "Display fallback never rewrites an old value or its confirmation");
const original = missing();
original.confirmation_snapshot = { kind: "parameter", value: 12.5, tolerance_upper: null, tolerance_lower: null };
assert.equal(service.adopt(original), true);
assert.equal(original.value, 12.5);
assert.equal(original.surface_location, "两端面");
assert.equal(original.need_human_review, true);
assert.equal(original.confirmation_snapshot, undefined);
assert.equal(service.adopted(original), true);
assert.equal(original.evidence, "");
assert.equal(original.position, null);
assert.equal(service.adopt(original), false, "Repeated clicks do not apply twice");
original.need_human_review = false;
original.confirmation_snapshot = { kind: "parameter", value: 12.5 };
original.value = 6.3;
service.edited(original);
assert.equal(service.adopted(original), false);
assert.equal(original.confirmation_snapshot, undefined, "A later custom edit never inherits the reference confirmation");
original.value = "";
service.edited(original);
assert.equal(service.dismissed(original), true);
assert.equal(service.eligible(original), true);
const declined = missing();
assert.equal(service.dismiss(declined), true);
assert.equal(service.dismissed(structuredClone(declined)), true);
assert.equal(declined.need_human_review, true);
assert.equal(declined.value, null);
assert.equal(service.adopt(declined), true, "A user can reopen and adopt after declining");
assert.equal(declined.roughness_reference_dismissed, false);
assert.equal(service.dismissed({ ...missing(), source: ["manual"] }), true, "Old human-cleared fields start collapsed");
// Export parity includes every end condition and optional-reference stage.
const { execFileSync } = await import("node:child_process");
const rows = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe", ["scripts/test_surface_roughness_reference.py", "--json"], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
for (const name of ["compression-design-checks.js", "technical-requirement-equivalence.js", "solidworks-export.js"]) vm.runInContext(fs.readFileSync(`frontend/${name}`, "utf8"), context);
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
for (const row of rows) assert.deepEqual(JSON.parse(JSON.stringify(context.SolidWorksExport.buildPreview(structuredClone(row.package), row.review, catalog))), row.package.solidworks_preview, row.name);
console.log("PASS: optional Ra reference protects values/evidence, separates adoption from confirmation, remembers decline and custom edits");
