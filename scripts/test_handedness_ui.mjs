import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const optionStart = appSource.indexOf("const HANDEDNESS_OPTIONS");
const optionEnd = appSource.indexOf("const STANDARDIZATION_PARAMETER_ASSOCIATIONS", optionStart);
const contractStart = appSource.indexOf("function generationContractValue");
const contractEnd = appSource.indexOf("function generationContractState", contractStart);
const controlStart = appSource.indexOf("function parameterValueControlHtml");
const controlEnd = appSource.indexOf("function renderWorkbenchAccuracyGradeSelectorHtml", controlStart);

assert.notEqual(optionStart, -1, "handedness options must exist");
assert.notEqual(optionEnd, -1, "handedness options block must be complete");
assert.notEqual(contractStart, -1, "generation handedness conversion must exist");
assert.notEqual(contractEnd, -1, "generation handedness conversion block must be complete");
assert.notEqual(controlStart, -1, "parameter value control must exist");
assert.notEqual(controlEnd, -1, "parameter value control block must be complete");

const context = {
  COMPRESSION_ACCURACY_GRADE_OPTIONS: ["1级", "2级", "3级"],
  COMPRESSION_END_GRINDING_OPTIONS: ["两端磨削", "两端不磨削"],
  COMPRESSION_END_TYPE_OPTIONS: ["两端并紧", "两端不并紧"],
  displayedAccuracyGrade: () => "2级",
  escapeHtml: (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;"),
  formatFieldInput: (param) => param?.value ?? "",
  targetFieldLabel: (field) => field,
};
vm.createContext(context);
vm.runInContext(appSource.slice(optionStart, optionEnd), context);
vm.runInContext(appSource.slice(controlStart, controlEnd), context);
vm.runInContext(appSource.slice(contractStart, contractEnd), context);

const rightHtml = context.parameterValueControlHtml("handedness", { value: "right" }, "旋向");
assert.match(rightHtml, /<select[^>]+data-role="value"/);
assert.match(rightHtml, /<option value="right" selected>右旋<\/option>/);
assert.match(rightHtml, /<option value="left">左旋<\/option>/);
assert.doesNotMatch(rightHtml, />right<\/option>|>left<\/option>/);

const legacyChineseHtml = context.parameterValueControlHtml("handedness", { value: "左旋" }, "旋向");
assert.match(legacyChineseHtml, /<option value="left" selected>左旋<\/option>/);
assert.equal(context.generationContractValue("handedness", "左旋"), "left");
assert.equal(context.generationContractValue("handedness", "右旋"), "right");
assert.equal(context.generationContractValue("handedness", "left"), "left");
assert.equal(context.generationContractValue("handedness", "right"), "right");
assert.equal(context.handednessDisplayLabel("left"), "左旋");
assert.equal(context.handednessDisplayLabel("right"), "右旋");

const invalidHtml = context.parameterValueControlHtml("handedness", { value: "clockwise" }, "旋向");
assert.match(invalidHtml, /无法识别：clockwise/);
assert.match(invalidHtml, /value="" selected disabled/);

console.log("旋向 UI 测试通过：中文下拉显示、历史值兼容与 left\/right 参数包映射正确。");
