import assert from "node:assert/strict";
import fs from "node:fs";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const coreFields = appSource.slice(
  appSource.indexOf("const COMPRESSION_CORE_PARAMETER_FIELDS"),
  appSource.indexOf("const COMPRESSION_GENERATION_CORE_FIELDS"),
);

assert.match(coreFields, /"solid_height"/);
assert.match(appSource, /function shouldShowSolidHeightCore\(param\)/);
assert.match(appSource, /field !== "solid_height" \|\| shouldShowSolidHeightCore\(params\[field\]\)/);
assert.match(appSource, /field === "solid_height"/);
assert.match(appSource, /公式参考 \/ 待确认/);
assert.match(appSource, /人工值/);
assert.match(appSource, /图纸值/);

console.log("compression solid height UI test passed");
