import assert from "node:assert/strict";
import fs from "node:fs";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const cssSource = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");

assert.match(appSource, /generation-readiness/);
assert.match(appSource, /generation-jobs/);
assert.match(appSource, /window\.setInterval\(\(\) => \{ void poll\(\); \}, 2000\)/);
assert.match(appSource, /data-action="compare-generation"/);
assert.match(appSource, /data-action="approve-generation"/);
assert.match(appSource, /data-compare-mode="side-by-side"/);
assert.match(appSource, /data-compare-mode="overlay"/);
assert.match(appSource, /参数已过期/);
assert.match(appSource, /待真实 SolidWorks \/ ERP 接入/);
assert.match(appSource, /标准化为可选功能/);
assert.doesNotMatch(appSource, /等待生成标准化方案/);
assert.match(cssSource, /\.generation-compare-canvas\.overlay/);
assert.match(cssSource, /--generation-opacity/);

console.log("generation closed-loop UI test passed");
