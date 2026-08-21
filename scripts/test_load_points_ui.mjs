import assert from "node:assert/strict";
import fs from "node:fs";

const app = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");

for (const marker of [
  "function renderLoadPointSectionHtml",
  "data-action=\"show-load-point-create\"",
  "data-kind=\"load_point_create\"",
  "data-role=\"delete-load-point\"",
  "data-action=\"undo-load-point-delete\"",
  "event_type: \"load_point_added\"",
  "event_type: \"load_point_deleted\"",
  "event_type: \"load_point_restored\"",
  "function ensureLoadPointIds",
  "generation_parameters: {\n      spring_parameters: confirmedParameters,\n      load_points: loadPoints",
]) {
  assert.ok(app.includes(marker), `missing load-point UI behavior: ${marker}`);
}

assert.match(app, /load_point_id: createLoadPointId\(review\)/);
assert.match(app, /if \(!isValidLoadPoint\(point\) \|\| point\.need_human_review !== false\) return false;/);
assert.match(app, /载荷测试点变更/);
assert.match(styles, /\.load-point-create/);
assert.match(styles, /\.load-point-actions/);
assert.match(styles, /\.load-point-undo/);

console.log("load point UI source tests passed");
