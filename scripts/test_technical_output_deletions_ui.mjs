import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
const cases = JSON.parse(execFileSync(process.env.DESIGN_TEST_PYTHON || ".venv/Scripts/python.exe",
  ["scripts/test_technical_output_deletions.py", "--json"], { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 }));
const catalog = JSON.parse(fs.readFileSync("config/compression_material_catalog.json", "utf8"));
const context = vm.createContext({ structuredClone });
for (const file of ["compression-design-checks", "technical-requirement-equivalence", "solidworks-export"])
  vm.runInContext(fs.readFileSync(`frontend/${file}.js`, "utf8"), context);
for (const row of cases) {
  const before = structuredClone(row.review);
  const projection = JSON.parse(JSON.stringify(context.SolidWorksExport.technicalProjection(row.package, row.review, catalog)));
  assert.deepEqual(projection, row.projection, row.name);
  assert.deepEqual(row.review, before, "Projection never changes the review");
  const review = structuredClone(row.review);
  context.SolidWorksExport.refreshDeletions(review);
  assert.ok((review.technical_output_deletions || []).every(item => item.source_key.startsWith("legacy:")
    || JSON.stringify(item.basis) === JSON.stringify(context.SolidWorksExport.outputBasis(review, item.source_key, item.fields, item.load_point_ids, "", item.basis.scope))));
}
console.log(`PASS ${cases.length} shared technical deletion projections, exact frontend/backend provenance and read-only parity`);
