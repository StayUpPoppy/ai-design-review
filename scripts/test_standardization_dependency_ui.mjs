import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
function extract(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `Cannot extract ${start}`);
  return source.slice(first, last);
}

const context = {
  state: {
    review: {
      standard_selection: { human_confirmed: true },
      standardization_apply_history: [],
      standardization_results: [
        { status: "suggested", target_field: "free_length", metadata: { source_fields: ["free_length", "wire_diameter"] } },
        { status: "suggested", target_field: "total_coils", metadata: { source_fields: ["total_coils"] } },
        { status: "suggested", target_field: "legacy_rule", metadata: {} },
      ],
      parameter_reasonableness: { suggestions: [] },
    },
  },
};
vm.createContext(context);
vm.runInContext(extract("function invalidateReasonablenessSuggestions", "function sourceValues"), context);
vm.runInContext(extract("function invalidateStandardizationResults", "function syncBubbleValue"), context);

assert.equal(context.invalidateStandardizationResults("material"), 1, "unknown rules remain conservative");
assert.equal(context.state.review.standardization_results[0].status, "suggested");
assert.equal(context.state.review.standardization_results[1].status, "suggested");
assert.equal(context.state.review.standardization_results[2].status, "stale");

assert.equal(context.invalidateStandardizationResults("free_length"), 1);
assert.equal(context.state.review.standardization_results[0].status, "stale");
assert.equal(context.state.review.standardization_results[1].status, "suggested");

console.log("standardization dependency UI tests passed");
