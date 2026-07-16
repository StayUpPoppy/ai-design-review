import assert from "node:assert/strict";
import fs from "node:fs";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");

assert.match(appSource, /field === "spring_rate"/);
assert.match(appSource, /formula_calculation/);
assert.match(appSource, /公式计算 \/ 待确认/);
assert.doesNotMatch(
  appSource.slice(appSource.indexOf("const COMPRESSION_CORE_PARAMETER_FIELDS"), appSource.indexOf("const COMPRESSION_GENERATION_CORE_FIELDS")),
  /"spring_rate"/,
);

console.log("compression stiffness UI test passed");
