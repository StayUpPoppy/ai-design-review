import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const cssSource = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");
const start = appSource.indexOf("function renderParameterReasonablenessHtml");
const end = appSource.indexOf("function renderParameterTableHtml", start);

assert.notEqual(start, -1, "reasonableness renderer must exist");
assert.notEqual(end, -1, "reasonableness renderer block must be complete");

const context = {
  escapeHtml: (value) => String(value ?? ""),
};
vm.createContext(context);
vm.runInContext(appSource.slice(start, end), context);

const blocked = context.renderParameterReasonablenessHtml({
  parameter_reasonableness: {
    status: "blocked",
    summary: "外径与线径存在矛盾。",
    issues: [{
      severity: "blocked",
      rule_id: "SPRING-GEO-OUTER-INNER",
      fields: ["outer_diameter", "wire_diameter"],
      message: "外径必须大于两倍线径。",
      calculation: "Di=Do-2d=-1 mm",
      basis: "圆丝圆柱螺旋弹簧几何关系。",
      explanation: "当前截面几何不成立。",
      customer_question: "请客户确认外径或线径。",
    }],
  },
});

assert.match(blocked, /参数合理性/);
assert.match(blocked, /不可用/);
assert.match(blocked, /SPRING-GEO-OUTER-INNER/);
assert.match(blocked, /建议向客户确认/);
assert.match(blocked, /data-role="focus-reasonableness-field"/);
assert.match(cssSource, /\.parameter-reasonableness-item\.blocked/);
assert.match(cssSource, /\.data-row\.parameter-risk-warning/);

const pass = context.renderParameterReasonablenessHtml({
  parameter_reasonableness: { status: "pass", summary: "通过", issues: [] },
});
assert.match(pass, /参数关系正常/);
assert.match(pass, /未发现明显几何矛盾/);

console.log("parameter reasonableness UI test passed");
