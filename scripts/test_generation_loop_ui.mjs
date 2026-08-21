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
assert.match(appSource, /data-compare-mode="original"/);
assert.match(appSource, /data-compare-mode="generated"/);
assert.match(appSource, /data-role="generation-zoom-out"/);
assert.match(appSource, /data-role="generation-zoom-in"/);
assert.match(appSource, /data-role="generation-reset-view"/);
assert.match(appSource, /data-role="generation-compare-viewport"/);
assert.match(appSource, /addEventListener\("wheel"/);
assert.match(appSource, /addEventListener\("pointerdown"/);
assert.match(appSource, /addEventListener\("pointermove"/);
assert.match(appSource, /new ResizeObserver\(scheduleRender\)/);
assert.match(appSource, /const minZoom = 0\.25/);
assert.match(appSource, /const maxZoom = 5/);
assert.doesNotMatch(appSource, /data-compare-mode="overlay"/);
assert.doesNotMatch(appSource, /generation-opacity/);
assert.match(appSource, /参数已过期/);
assert.match(appSource, /待真实 SolidWorks \/ ERP 接入/);
assert.match(appSource, /标准化为可选功能/);
assert.doesNotMatch(appSource, /等待生成标准化方案/);
assert.match(cssSource, /\.generation-compare-viewport/);
assert.match(cssSource, /\.generation-compare-viewport\.dragging/);
assert.doesNotMatch(cssSource, /\.generation-compare-canvas\.overlay/);
assert.doesNotMatch(cssSource, /--generation-opacity/);

console.log("generation closed-loop UI test passed");
