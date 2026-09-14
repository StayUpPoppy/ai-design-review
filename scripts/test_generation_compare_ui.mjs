import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const start = source.indexOf("function openGenerationCompare(");
const end = source.indexOf("\nasync function readUploadResponsePayload", start);
assert.ok(start >= 0 && end > start, "generation comparison function is present");

function element() {
  const listeners = new Map();
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    value: "",
    checked: false,
    textContent: "",
    className: "",
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      toggle: (name, force) => {
        if (force ?? !classes.has(name)) classes.add(name);
        else classes.delete(name);
      },
      contains: (name) => classes.has(name),
    },
    addEventListener(type, listener) {
      const current = listeners.get(type) || [];
      current.push(listener);
      listeners.set(type, current);
    },
    dispatch(type, event = {}) {
      for (const listener of listeners.get(type) || []) listener({ target: this, ...event });
    },
  };
}

const originalFigure = element();
const generatedFigure = element();
const originalViewport = element();
const generatedViewport = element();
const originalImage = element();
const generatedImage = element();
for (const [viewport, image, figure, key, left] of [
  [originalViewport, originalImage, originalFigure, "original", 0],
  [generatedViewport, generatedImage, generatedFigure, "generated", 500],
]) {
  viewport.dataset.pane = key;
  viewport.querySelector = () => image;
  viewport.closest = () => figure;
  viewport.getBoundingClientRect = () => ({ left, top: 0, width: 500, height: 500 });
  viewport.setPointerCapture = () => {};
  viewport.hasPointerCapture = () => false;
  image.complete = true;
  image.naturalWidth = 1000;
  image.naturalHeight = 1000;
}

const canvas = element();
const zoomLabel = element();
const zoomOut = element();
const zoomIn = element();
const resetView = element();
const paneSelect = element();
const originalOption = element();
const generatedOption = element();
paneSelect.querySelector = (selector) => selector.includes('"original"') ? originalOption : generatedOption;
const linkToggle = element();
const close = element();
const modeButtons = ["side-by-side", "original", "generated"].map((mode) => {
  const button = element();
  button.dataset.compareMode = mode;
  return button;
});
const nodes = new Map([
  ['[data-role="generation-compare-canvas"]', canvas],
  ['[data-role="generation-zoom-label"]', zoomLabel],
  ['[data-role="generation-zoom-out"]', zoomOut],
  ['[data-role="generation-zoom-in"]', zoomIn],
  ['[data-role="generation-reset-view"]', resetView],
  ['[data-role="generation-active-pane"]', paneSelect],
  ['[data-role="generation-link-views"]', linkToggle],
  ['[data-role="close-generation-compare"]', close],
]);
const dialog = element();
dialog.querySelector = (selector) => nodes.get(selector);
dialog.querySelectorAll = (selector) => selector === '[data-role="generation-compare-viewport"]'
  ? [originalViewport, generatedViewport]
  : selector === "[data-compare-mode]" ? modeButtons : [];
dialog.showModal = () => {};
dialog.remove = () => {};

let nextFrame = 0;
const frames = new Map();
const context = {
  state: {
    generationJobs: [{
      generation_id: "1000000001",
      review_revision: 1,
      template_code: "test",
      artifacts: [{ artifact_type: "png", url: "/generated.png" }],
    }],
    imageUrl: "/original.png",
  },
  document: {
    querySelector: () => null,
    createElement: () => dialog,
    body: { appendChild: () => {} },
  },
  toBackendAssetUrl: (url) => url,
  escapeHtml: (value) => String(value),
  requestAnimationFrame: (callback) => {
    const id = ++nextFrame;
    frames.set(id, callback);
    return id;
  },
  cancelAnimationFrame: (id) => frames.delete(id),
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.openGenerationCompare("1000000001");

function flushFrames() {
  for (let pass = 0; pass < 10 && frames.size; pass += 1) {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback());
  }
  assert.equal(frames.size, 0, "render queue settles");
}

function scale(image) {
  return Number(image.style.transform.match(/scale\(([^)]+)\)/)?.[1]);
}

flushFrames();
assert.equal(linkToggle.checked, false);
assert.equal(paneSelect.value, "original");
assert.equal(scale(originalImage), scale(generatedImage));

originalViewport.dispatch("wheel", {
  deltaY: -100,
  clientX: 250,
  clientY: 250,
  preventDefault() {},
});
flushFrames();
assert.ok(scale(originalImage) > scale(generatedImage), "wheel zoom changes only the hovered pane");
const generatedBeforeDrag = generatedImage.style.transform;
const originalBeforeDrag = originalImage.style.transform;
originalViewport.dispatch("pointerdown", {
  pointerType: "mouse", button: 0, pointerId: 1, clientX: 250, clientY: 250, preventDefault() {},
});
originalViewport.dispatch("pointermove", { pointerId: 1, clientX: 200, clientY: 250 });
flushFrames();
assert.notEqual(originalImage.style.transform, originalBeforeDrag, "drag moves the selected pane");
assert.equal(generatedImage.style.transform, generatedBeforeDrag, "drag does not move the other pane");
originalViewport.dispatch("pointerup", { pointerId: 1 });

paneSelect.value = "generated";
paneSelect.dispatch("change");
const originalBeforeToolbar = scale(originalImage);
zoomIn.dispatch("click");
flushFrames();
assert.equal(scale(originalImage), originalBeforeToolbar, "toolbar zoom honors the selected pane");
assert.ok(scale(generatedImage) > originalBeforeToolbar);

linkToggle.checked = true;
linkToggle.dispatch("change");
flushFrames();
assert.equal(scale(originalImage), scale(generatedImage), "linking aligns both panes to the active one");
generatedViewport.dispatch("wheel", {
  deltaY: -100, clientX: 750, clientY: 250, preventDefault() {},
});
flushFrames();
assert.equal(scale(originalImage), scale(generatedImage), "linked wheel zoom changes both panes");
assert.equal(resetView.textContent, "重置两侧");

linkToggle.checked = false;
linkToggle.dispatch("change");
flushFrames();
const originalBeforeUnlinkedWheel = scale(originalImage);
generatedViewport.dispatch("wheel", {
  deltaY: -100, clientX: 750, clientY: 250, preventDefault() {},
});
flushFrames();
assert.equal(scale(originalImage), originalBeforeUnlinkedWheel, "unlink restores independent zoom");
resetView.dispatch("click");
flushFrames();
assert.equal(scale(originalImage), originalBeforeUnlinkedWheel, "reset affects only the active pane");
assert.equal(resetView.textContent, "重置当前");

modeButtons[1].dispatch("click");
flushFrames();
assert.equal(paneSelect.value, "original");
assert.equal(scale(originalImage), originalBeforeUnlinkedWheel, "mode switch preserves each pane's view");
modeButtons[0].dispatch("click");
flushFrames();
assert.equal(generatedOption.disabled, false);

console.log("generation comparison independent and linked interaction test passed");
