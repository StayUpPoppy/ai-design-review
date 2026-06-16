const state = {
  apiBaseUrl: normalizeBaseUrl(
    new URLSearchParams(window.location.search).get("api")
      || localStorage.getItem("aiDesignReviewApiBaseUrl")
      || "http://127.0.0.1:8770",
  ),
  selectedFile: null,
  imageUrl: null,
  review: null,
  selectedBubbleId: null,
  lastJob: null,
  activeReviewMessageId: null,
  compareOpen: false,
  compareView: {
    initialized: false,
    scale: 1,
    x: 0,
    y: 0,
    dragging: false,
    startClientX: 0,
    startClientY: 0,
    startX: 0,
    startY: 0,
  },
  busy: false,
};

const REQUIRED_FIELDS = [
  "material",
  "wire_diameter",
  "outer_diameter",
  "free_length",
  "total_coils",
  "handedness",
];

const FIELD_LABELS = {
  drawing_no: "图号",
  drawing_name: "图纸名称",
  version: "版本",
  material: "材料",
  wire_diameter: "线径",
  outer_diameter: "外径",
  free_length: "自由长度",
  total_coils: "总圈数",
  active_coils: "有效圈数",
  handedness: "旋向",
  pitch: "节距",
  end_type: "端部形式",
};

const TECH_LABELS = {
  heat_treatment: "热处理",
  surface: "表面要求",
  salt_spray: "盐雾",
  lifetime: "寿命",
  environmental: "环保",
  process: "工艺",
  other: "其他",
};

const conversation = document.getElementById("conversation");
const backendStatus = document.getElementById("backendStatus");
const apiBaseInput = document.getElementById("apiBaseInput");
const checkApiButton = document.getElementById("checkApiButton");
const demoButton = document.getElementById("demoButton");
const exportButton = document.getElementById("exportButton");
const drawingInput = document.getElementById("drawingInput");
const reviewJsonInput = document.getElementById("reviewJsonInput");
const chooseFileButton = document.getElementById("chooseFileButton");
const loadReviewJsonButton = document.getElementById("loadReviewJsonButton");
const submitButton = document.getElementById("submitButton");
const selectedFileName = document.getElementById("selectedFileName");
const dropZone = document.getElementById("dropZone");
const usePaddleOcrInput = document.getElementById("usePaddleOcrInput");
const useWerk24Input = document.getElementById("useWerk24Input");
const confirmWerk24Input = document.getElementById("confirmWerk24Input");
const useCachedWerk24Input = document.getElementById("useCachedWerk24Input");
const useSampleOcrInput = document.getElementById("useSampleOcrInput");
const compareOverlay = createCompareOverlay();

apiBaseInput.value = state.apiBaseUrl;

apiBaseInput.addEventListener("change", () => {
  state.apiBaseUrl = normalizeBaseUrl(apiBaseInput.value || state.apiBaseUrl);
  apiBaseInput.value = state.apiBaseUrl;
  localStorage.setItem("aiDesignReviewApiBaseUrl", state.apiBaseUrl);
  setBackendStatus(`后端地址已切换为 ${state.apiBaseUrl}`);
});

checkApiButton.addEventListener("click", checkApiHealth);
chooseFileButton.addEventListener("click", () => drawingInput.click());
loadReviewJsonButton.addEventListener("click", () => reviewJsonInput.click());
submitButton.addEventListener("click", () => submitSelectedFile());
demoButton.addEventListener("click", loadDemoReview);
exportButton.addEventListener("click", () => {
  if (!state.review) return;
  downloadJson(makeExportReview(), "spring_review_confirmed.json");
});

drawingInput.addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) selectDrawingFile(file);
});

reviewJsonInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  const review = normalizeReview(JSON.parse(await file.text()));
  setReview(review, null);
  appendUserMessage(`导入审查 JSON：${file.name}`);
  appendReviewMessage("已加载审查结果，请确认结构化尺寸数据。");
});

["dragenter", "dragover"].forEach((eventName) => {
  window.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  window.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (eventName === "drop") return;
    dropZone.classList.remove("dragging");
  });
});

window.addEventListener("drop", (event) => {
  dropZone.classList.remove("dragging");
  const file = Array.from(event.dataTransfer?.files || []).find(isSupportedDrawing);
  if (!file) {
    appendAssistantText("暂未找到可上传的 PDF 或图片文件。");
    return;
  }
  selectDrawingFile(file);
  submitSelectedFile();
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.compareOpen) {
    closeCompareOverlay();
  }
});

function selectDrawingFile(file) {
  if (!isSupportedDrawing(file)) {
    appendAssistantText("当前仅支持 PDF 或常见图片格式。");
    return;
  }
  state.selectedFile = file;
  selectedFileName.textContent = file.name;
  submitButton.disabled = state.busy;
}

async function submitSelectedFile() {
  if (!state.selectedFile || state.busy) return;
  if (useWerk24Input.checked && !confirmWerk24Input.checked) {
    appendAssistantText("调用 Werk24 前必须勾选“确认上传到 Werk24”。");
    return;
  }

  setBusy(true);
  appendUserMessage(`上传图纸：${state.selectedFile.name}`);
  const thinkingId = appendAssistantText("正在识别图纸，PaddleOCR 可能需要几十秒...");

  try {
    const form = new FormData();
    form.append("drawing", state.selectedFile);
    form.append("use_paddleocr", usePaddleOcrInput.checked ? "true" : "false");
    form.append("use_werk24", useWerk24Input.checked ? "true" : "false");
    form.append("confirm_upload_to_werk24", confirmWerk24Input.checked ? "true" : "false");
    form.append("use_cached_werk24", useCachedWerk24Input.checked ? "true" : "false");
    form.append("use_sample_ocr", useSampleOcrInput.checked ? "true" : "false");

    const response = await fetch(apiUrl("/api/reviews"), { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "后端审查失败");

    removeMessage(thinkingId);
    state.lastJob = payload;
    setReview(normalizeReview(payload.review), toBackendAssetUrl(payload.image_url));
    appendReviewMessage(makeCompletionText(payload));
  } catch (error) {
    replaceMessage(thinkingId, error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

async function loadDemoReview() {
  setBusy(true);
  appendUserMessage("加载样例审查结果");
  const thinkingId = appendAssistantText("正在加载样例...");
  try {
    const response = await fetch(apiUrl("/outputs/mixed_review.json"));
    if (!response.ok) throw new Error("样例审查 JSON 加载失败");
    const review = normalizeReview(await response.json());
    removeMessage(thinkingId);
    setReview(review, apiUrl("/tmp_pdf_pages/spring_example_rotated.png"));
    appendReviewMessage("样例已加载，请确认结构化尺寸数据。");
  } catch (error) {
    replaceMessage(thinkingId, error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

async function checkApiHealth() {
  setBackendStatus("正在检查后端...");
  try {
    const response = await fetch(apiUrl("/api/health"));
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "后端健康检查失败");
    const paddleStatus = payload.paddleocr_runtime?.status || "unknown";
    const werk24Status = payload.werk24_license?.status || "unknown";
    setBackendStatus(`后端正常 · PaddleOCR ${paddleStatus} · Werk24 ${werk24Status}`);
  } catch (error) {
    setBackendStatus(`后端不可用：${error.message || String(error)}`, true);
  }
}

function appendReviewMessage(title) {
  const message = createMessage("assistant");
  const body = message.querySelector(".message-body");
  renderReviewBody(body, title);
  conversation.appendChild(message);
  state.activeReviewMessageId = message.dataset.messageId;
  scrollMessageIntoView(message);
}

function renderReviewBody(body, title) {
  const review = state.review;
  refreshDerivedStatus(review);
  body.innerHTML = `
    <div class="message-meta">助手 · 结构化审查</div>
    <p>${escapeHtml(title)}</p>
    ${renderSummaryHtml(review)}
    ${renderPreviewHtml()}
    ${renderParameterTableHtml(review)}
    ${renderRequirementsHtml(review)}
    <div class="review-actions">
      <button type="button" data-action="fullscreen">全屏对比</button>
      <button type="button" data-action="confirm-all">全部确认</button>
      <button type="button" data-action="export" ${review ? "" : "disabled"}>导出确认版</button>
    </div>
  `;
  body.querySelector('[data-action="fullscreen"]').addEventListener("click", openCompareOverlay);
  body.querySelector('[data-action="confirm-all"]').addEventListener("click", () => {
    confirmAllFields();
    acknowledgeScannedInput();
    updateLatestReviewMessage("已全部确认，当前审查状态已刷新。");
  });
  body.querySelector('[data-action="export"]').addEventListener("click", () => {
    downloadJson(makeExportReview(), "spring_review_confirmed.json");
  });
  bindReviewEditors(body);
}

function renderSummaryHtml(review) {
  const info = review.drawing_summary || {};
  const missing = review.missing_fields || [];
  return `
    <section class="summary-strip">
      ${metricHtml("图纸", info.drawing_name || "-")}
      ${metricHtml("图号", info.drawing_no || "-")}
      ${metricHtml("状态", info.overall_status || "-")}
      ${metricHtml("ERP", review.erp_ready ? "允许" : "阻断")}
      ${metricHtml("缺失字段", missing.length ? missing.map((field) => FIELD_LABELS[field] || field).join("、") : "无")}
    </section>
  `;
}

function metricHtml(label, value) {
  return `
    <div class="metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function renderPreviewHtml() {
  if (!state.imageUrl) return "";
  return `
    <details class="drawing-preview" open>
      <summary>图纸预览</summary>
      ${renderDrawingCanvasHtml("preview-canvas")}
    </details>
  `;
}

function renderDrawingCanvasHtml(className) {
  if (!state.imageUrl) {
    return `<div class="${escapeHtml(className)} empty-line">未加载图纸预览</div>`;
  }
  return `
    <div class="${escapeHtml(className)}">
      <img src="${escapeHtml(state.imageUrl)}" alt="drawing">
    </div>
  `;
}

function renderParameterTableHtml(review) {
  const params = review.spring_parameters || {};
  const rows = [
    ...getParameterFields(params).map((field) => parameterRowHtml(field, params[field] || blankParam())),
    ...(params.load_points || []).map((point, index) => loadPointRowHtml(point, index)),
  ];
  return `
    <section class="review-block">
      <div class="block-head">
        <h2>结构化尺寸数据</h2>
        <span>${rows.length} 项</span>
      </div>
      <div class="data-table">${rows.join("")}</div>
    </section>
  `;
}

function getParameterFields(params) {
  const returnedFields = Object.keys(params).filter((field) => {
    const value = params[field];
    return field !== "load_points" && value && typeof value === "object" && !Array.isArray(value);
  });
  return Array.from(new Set([...REQUIRED_FIELDS, ...returnedFields]));
}

function parameterRowHtml(field, param) {
  const confidence = Math.round((Number(param.confidence) || 0) * 100);
  return `
    <div class="data-row" data-kind="param" data-field="${escapeHtml(field)}">
      <div>
        <strong>${escapeHtml(FIELD_LABELS[field] || field)}</strong>
        <span>${escapeHtml((param.source || []).join(" / ") || "-")} · ${confidence}%</span>
      </div>
      <label>
        数值
        <input data-role="value" value="${escapeHtml(formatFieldInput(param))}">
      </label>
      <label>
        公差
        <input data-role="tolerance" value="${escapeHtml(formatTolerance(param))}">
      </label>
      <button type="button" data-role="confirm">${param.need_human_review ? "确认" : "已确认"}</button>
      <p>${escapeHtml(param.evidence || param.suggested_region || "")}</p>
    </div>
  `;
}

function loadPointRowHtml(point, index) {
  const confidence = Math.round((Number(point.confidence) || 0) * 100);
  return `
    <div class="data-row load-point" data-kind="load_point" data-index="${index}">
      <div>
        <strong>${escapeHtml(point.label || `F${index + 1}`)}</strong>
        <span>${escapeHtml((point.source || []).join(" / ") || "-")} · ${confidence}%</span>
      </div>
      <label>
        高度 mm
        <input data-role="height" value="${escapeHtml(point.height ?? "")}">
      </label>
      <label>
        力值 N
        <input data-role="force" value="${escapeHtml(point.force ?? "")}">
      </label>
      <button type="button" data-role="confirm">${point.need_human_review ? "确认" : "已确认"}</button>
      <p>${escapeHtml(point.evidence || "")}</p>
    </div>
  `;
}

function renderRequirementsHtml(review) {
  const requirements = review.technical_requirements || [];
  if (!requirements.length) {
    return `
      <section class="review-block">
        <div class="block-head"><h2>技术要求</h2><span>0 项</span></div>
        <div class="empty-line">未识别技术要求</div>
      </section>
    `;
  }
  return `
    <section class="review-block">
      <div class="block-head"><h2>技术要求</h2><span>${requirements.length} 项</span></div>
      <div class="requirement-list">
        ${requirements.map((item, index) => `
          <div class="requirement-row" data-kind="technical" data-index="${index}">
            <label>${escapeHtml(TECH_LABELS[item.type] || item.type || "技术要求")}
              <textarea data-role="content">${escapeHtml(item.content || "")}</textarea>
            </label>
            <button type="button" data-role="confirm">${item.need_human_review ? "确认" : "已确认"}</button>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function bindReviewEditors(root) {
  root.querySelectorAll('[data-kind="param"]').forEach((row) => {
    const field = row.dataset.field;
    const param = state.review.spring_parameters[field] || blankParam();
    state.review.spring_parameters[field] = param;
    row.querySelector('[data-role="value"]').addEventListener("change", (event) => {
      param.value = parseValue(event.target.value, param.value);
      markParamEdited(param);
      syncBubbleValue(field, param.value);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="tolerance"]').addEventListener("change", (event) => {
      applyTolerance(param, event.target.value);
      markParamEdited(param);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      confirmParam(param, field);
      updateLatestReviewMessage();
    });
  });

  root.querySelectorAll('[data-kind="load_point"]').forEach((row) => {
    const point = state.review.spring_parameters.load_points[Number(row.dataset.index)];
    row.querySelector('[data-role="height"]').addEventListener("change", (event) => {
      point.height = parseValue(event.target.value, point.height);
      markParamEdited(point);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="force"]').addEventListener("change", (event) => {
      point.force = parseValue(event.target.value, point.force);
      markParamEdited(point);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      confirmParam(point, `load_point_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
  });

  root.querySelectorAll('[data-kind="technical"]').forEach((row) => {
    const item = state.review.technical_requirements[Number(row.dataset.index)];
    row.querySelector('[data-role="content"]').addEventListener("change", (event) => {
      item.content = event.target.value.trim();
      confirmParam(item, `technical_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      confirmParam(item, `technical_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
  });
}

function updateLatestReviewMessage(title = "已更新结构化尺寸数据，请继续确认。") {
  refreshDerivedStatus(state.review);
  exportButton.disabled = false;
  const activeMessage = conversation.querySelector(`[data-message-id="${state.activeReviewMessageId}"]`);
  const body = activeMessage?.querySelector(".message-body");
  if (!body) {
    appendReviewMessage(title);
    return;
  }
  renderReviewBody(body, title);
  if (state.compareOpen) {
    renderCompareOverlay();
  }
}

function openCompareOverlay() {
  if (!state.review) return;
  state.compareOpen = true;
  state.compareView.initialized = false;
  document.body.classList.add("compare-open");
  compareOverlay.hidden = false;
  renderCompareOverlay();
}

function closeCompareOverlay() {
  state.compareOpen = false;
  document.body.classList.remove("compare-open");
  compareOverlay.hidden = true;
}

function createCompareOverlay() {
  const overlay = document.createElement("section");
  overlay.id = "compareOverlay";
  overlay.className = "compare-overlay";
  overlay.hidden = true;
  overlay.setAttribute("aria-label", "全屏图纸数据对比");
  document.body.appendChild(overlay);
  return overlay;
}

function renderCompareOverlay() {
  if (!state.review) return;
  refreshDerivedStatus(state.review);
  compareOverlay.innerHTML = `
    <div class="compare-shell">
      <header class="compare-head">
        <div>
          <h2>图纸与结构化数据对比</h2>
          <p>左侧查看原始图纸，右侧逐项确认或修改尺寸数据。</p>
        </div>
        <div class="compare-actions">
          <button type="button" data-action="confirm-all">全部确认</button>
          <button type="button" data-action="export">导出确认版</button>
          <button type="button" data-action="close">缩小</button>
        </div>
      </header>
      <div class="compare-layout">
        <section class="compare-drawing-panel">
          <div class="compare-panel-head">
            <strong>图纸预览</strong>
            <span>滚轮缩放，按住拖动</span>
          </div>
          ${renderCompareViewerHtml()}
        </section>
        <section class="compare-data-panel">
          ${renderSummaryHtml(state.review)}
          ${renderParameterTableHtml(state.review)}
          ${renderRequirementsHtml(state.review)}
        </section>
      </div>
    </div>
  `;
  compareOverlay.querySelector('[data-action="close"]').addEventListener("click", closeCompareOverlay);
  compareOverlay.querySelector('[data-action="export"]').addEventListener("click", () => {
    downloadJson(makeExportReview(), "spring_review_confirmed.json");
  });
  compareOverlay.querySelector('[data-action="confirm-all"]').addEventListener("click", () => {
    confirmAllFields();
    acknowledgeScannedInput();
    updateLatestReviewMessage("已全部确认，当前审查状态已刷新。");
  });
  bindReviewEditors(compareOverlay);
  initializeCompareViewer();
}

function renderCompareViewerHtml() {
  if (!state.imageUrl) {
    return `<div class="compare-viewer empty-line">未加载图纸预览</div>`;
  }
  return `
    <div class="compare-viewer">
      <div class="compare-tools">
        <button type="button" data-view-action="fit">适应窗口</button>
        <button type="button" data-view-action="zoom-out">缩小</button>
        <span id="compareZoomLabel">100%</span>
        <button type="button" data-view-action="zoom-in">放大</button>
        <button type="button" data-view-action="actual">100%</button>
      </div>
      <div id="compareViewport" class="compare-viewport">
        <img id="compareImage" class="compare-image" src="${escapeHtml(state.imageUrl)}" alt="drawing">
      </div>
    </div>
  `;
}

function initializeCompareViewer() {
  const viewport = compareOverlay.querySelector("#compareViewport");
  const image = compareOverlay.querySelector("#compareImage");
  if (!viewport || !image) return;

  const setup = () => {
    if (!image.naturalWidth || !image.naturalHeight) return;
    if (!state.compareView.initialized) {
      fitCompareImage();
    } else {
      applyCompareTransform();
    }
  };

  if (image.complete) {
    setup();
  } else {
    image.addEventListener("load", setup, { once: true });
  }

  compareOverlay.querySelector('[data-view-action="fit"]').addEventListener("click", fitCompareImage);
  compareOverlay.querySelector('[data-view-action="actual"]').addEventListener("click", () => {
    setCompareScale(1);
  });
  compareOverlay.querySelector('[data-view-action="zoom-in"]').addEventListener("click", () => {
    zoomCompareImage(1.2);
  });
  compareOverlay.querySelector('[data-view-action="zoom-out"]').addEventListener("click", () => {
    zoomCompareImage(1 / 1.2);
  });

  viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomCompareImage(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
  }, { passive: false });

  viewport.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    state.compareView.dragging = true;
    state.compareView.startClientX = event.clientX;
    state.compareView.startClientY = event.clientY;
    state.compareView.startX = state.compareView.x;
    state.compareView.startY = state.compareView.y;
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("dragging");
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!state.compareView.dragging) return;
    state.compareView.x = state.compareView.startX + event.clientX - state.compareView.startClientX;
    state.compareView.y = state.compareView.startY + event.clientY - state.compareView.startClientY;
    applyCompareTransform();
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((eventName) => {
    viewport.addEventListener(eventName, () => {
      state.compareView.dragging = false;
      viewport.classList.remove("dragging");
    });
  });
}

function fitCompareImage() {
  const viewport = compareOverlay.querySelector("#compareViewport");
  const image = compareOverlay.querySelector("#compareImage");
  if (!viewport || !image || !image.naturalWidth || !image.naturalHeight) return;
  const padding = 28;
  const viewportWidth = Math.max(1, viewport.clientWidth - padding * 2);
  const viewportHeight = Math.max(1, viewport.clientHeight - padding * 2);
  const scale = clamp(Math.min(
    viewportWidth / image.naturalWidth,
    viewportHeight / image.naturalHeight,
  ), 0.03, 4);
  state.compareView.scale = scale;
  state.compareView.x = (viewport.clientWidth - image.naturalWidth * scale) / 2;
  state.compareView.y = (viewport.clientHeight - image.naturalHeight * scale) / 2;
  state.compareView.initialized = true;
  applyCompareTransform();
}

function setCompareScale(scale) {
  const viewport = compareOverlay.querySelector("#compareViewport");
  if (!viewport) return;
  const rect = viewport.getBoundingClientRect();
  zoomCompareImage(scale / state.compareView.scale, rect.left + rect.width / 2, rect.top + rect.height / 2);
}

function zoomCompareImage(multiplier, clientX, clientY) {
  const viewport = compareOverlay.querySelector("#compareViewport");
  if (!viewport) return;
  const currentScale = state.compareView.scale;
  const nextScale = clamp(currentScale * multiplier, 0.05, 8);
  const rect = viewport.getBoundingClientRect();
  const originX = (clientX ?? rect.left + rect.width / 2) - rect.left;
  const originY = (clientY ?? rect.top + rect.height / 2) - rect.top;
  const imageX = (originX - state.compareView.x) / currentScale;
  const imageY = (originY - state.compareView.y) / currentScale;
  state.compareView.scale = nextScale;
  state.compareView.x = originX - imageX * nextScale;
  state.compareView.y = originY - imageY * nextScale;
  state.compareView.initialized = true;
  applyCompareTransform();
}

function applyCompareTransform() {
  const image = compareOverlay.querySelector("#compareImage");
  const label = compareOverlay.querySelector("#compareZoomLabel");
  if (!image) return;
  image.style.transform = `translate(${state.compareView.x}px, ${state.compareView.y}px) scale(${state.compareView.scale})`;
  if (label) {
    label.textContent = `${Math.round(state.compareView.scale * 100)}%`;
  }
}

function setReview(review, imageUrl) {
  state.review = review;
  state.imageUrl = imageUrl;
  exportButton.disabled = false;
}

function makeCompletionText(payload) {
  const warnings = payload.warnings?.length ? `警告：${payload.warnings.join("；")}` : "";
  const sources = payload.candidate_sources?.join(" / ") || "无";
  return `审查完成：${payload.candidate_count} 个候选，来源 ${sources}。${warnings}`;
}

function appendUserMessage(text) {
  const message = createMessage("user");
  message.querySelector(".message-body").innerHTML = `
    <div class="message-meta">用户 · 图纸上传</div>
    <p>${escapeHtml(text)}</p>
  `;
  conversation.appendChild(message);
  scrollToBottom();
}

function appendAssistantText(text, isError = false) {
  const message = createMessage("assistant");
  message.classList.toggle("error", isError);
  message.querySelector(".message-body").innerHTML = `
    <div class="message-meta">助手 · 引导</div>
    <p>${escapeHtml(text)}</p>
  `;
  conversation.appendChild(message);
  scrollToBottom();
  return message.dataset.messageId;
}

function replaceMessage(messageId, text, isError = false) {
  const message = conversation.querySelector(`[data-message-id="${messageId}"]`);
  if (!message) return;
  message.classList.toggle("error", isError);
  message.querySelector(".message-body").innerHTML = `
    <div class="message-meta">助手 · 引导</div>
    <p>${escapeHtml(text)}</p>
  `;
}

function removeMessage(messageId) {
  conversation.querySelector(`[data-message-id="${messageId}"]`)?.remove();
}

function createMessage(role) {
  const message = document.createElement("article");
  message.className = `message ${role}`;
  message.dataset.messageId = createMessageId();
  message.innerHTML = `
    <div class="avatar">${role === "user" ? "我" : "AI"}</div>
    <div class="message-body"></div>
  `;
  return message;
}

function createMessageId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function setBusy(busy) {
  state.busy = busy;
  submitButton.disabled = busy || !state.selectedFile;
  chooseFileButton.disabled = busy;
  demoButton.disabled = busy;
  submitButton.textContent = busy ? "审查中..." : "开始审查";
}

function setBackendStatus(text, isError = false) {
  backendStatus.textContent = text;
  backendStatus.classList.toggle("error", isError);
}

function apiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${state.apiBaseUrl}${normalizedPath}`;
}

function toBackendAssetUrl(path) {
  if (!path) return null;
  if (/^https?:\/\//i.test(path) || path.startsWith("blob:")) return path;
  return apiUrl(path);
}

function normalizeBaseUrl(url) {
  return String(url || "http://127.0.0.1:8770").trim().replace(/\/+$/, "");
}

function normalizeReview(review) {
  const cloned = structuredClone(review);
  cloned.drawing_summary ||= {};
  cloned.spring_parameters ||= {};
  cloned.spring_parameters.load_points ||= [];
  cloned.technical_requirements ||= [];
  cloned.review_results ||= [];
  cloned.balloons ||= [];
  cloned.manual_confirmations ||= {};
  return cloned;
}

function refreshDerivedStatus(review) {
  const requiredMissing = REQUIRED_FIELDS.filter((field) => {
    const value = review.spring_parameters?.[field]?.value;
    return value == null || value === "";
  });
  review.missing_fields = requiredMissing;
  const hasBlockingRule = (review.review_results || []).some((rule) => {
    return ["fail", "missing", "need_review"].includes(rule.status);
  });
  review.human_review_required = hasHumanReview(review);
  review.erp_ready = !hasBlockingRule && !review.human_review_required && requiredMissing.length === 0;
  review.erp_block_reason = review.erp_ready ? "" : review.erp_block_reason || "存在待确认字段或阻断规则。";
  review.drawing_summary.overall_status = review.erp_ready
    ? ((review.review_results || []).some((rule) => rule.status === "warning") ? "warning" : "pass")
    : "need_review";
}

function hasHumanReview(review) {
  const params = review.spring_parameters || {};
  const fieldNeedsReview = Object.values(params).some((param) => {
    if (Array.isArray(param)) return param.some((item) => item.need_human_review);
    return param && typeof param === "object" && param.need_human_review;
  });
  const techNeedsReview = (review.technical_requirements || []).some((item) => item.need_human_review);
  return fieldNeedsReview || techNeedsReview;
}

function confirmAllFields() {
  const params = state.review.spring_parameters || {};
  Object.entries(params).forEach(([field, param]) => {
    if (Array.isArray(param)) {
      param.forEach((item, index) => confirmParam(item, `${field}_${index}`));
    } else if (param && typeof param === "object") {
      confirmParam(param, field);
    }
  });
  (state.review.technical_requirements || []).forEach((item, index) => {
    confirmParam(item, `technical_${index}`);
  });
}

function acknowledgeScannedInput() {
  const rule = state.review.review_results.find((item) => item.rule_id === "DOC-001");
  if (rule) {
    rule.status = "pass";
    rule.message = "工程师已确认扫描图纸，允许进入后续 ERP 前置流程。";
    rule.severity = "low";
  }
  state.review.human_review_required = false;
  state.review.erp_block_reason = "";
}

function confirmParam(param, field) {
  param.need_human_review = false;
  param.confidence = Math.max(Number(param.confidence) || 0, 0.99);
  param.source = Array.from(new Set(["human_confirmed", ...(param.source || [])]));
  state.review.manual_confirmations[field] = {
    confirmed: true,
    value: param.value ?? param.content ?? null,
    confirmed_at: new Date().toISOString(),
  };
}

function markParamEdited(param) {
  param.need_human_review = true;
  param.source = Array.from(new Set(["human_edited", ...(param.source || [])]));
}

function syncBubbleValue(field, value) {
  const bubble = (state.review.balloons || []).find((item) => item.field === field);
  if (bubble) bubble.value = String(value ?? "");
}

function makeExportReview() {
  const exported = structuredClone(state.review);
  exported.exported_at = new Date().toISOString();
  exported.export_type = "human_confirmed_review";
  refreshDerivedStatus(exported);
  return exported;
}

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function blankParam() {
  return {
    value: "",
    source: [],
    evidence: "",
    confidence: 0,
    need_human_review: true,
  };
}

function formatFieldInput(param) {
  return param.value ?? "";
}

function formatTolerance(param) {
  const upper = param.tolerance_upper;
  const lower = param.tolerance_lower;
  if (upper == null && lower == null) return "";
  if (Number(upper) === Math.abs(Number(lower))) return `±${Math.abs(Number(upper))}`;
  return `${upper ?? ""}/${lower ?? ""}`;
}

function applyTolerance(param, value) {
  const text = value.trim();
  if (!text) {
    param.tolerance_upper = null;
    param.tolerance_lower = null;
    return;
  }
  if (text.startsWith("±")) {
    const number = Number(text.slice(1));
    if (!Number.isNaN(number)) {
      param.tolerance_upper = number;
      param.tolerance_lower = -number;
    }
    return;
  }
  if (text.includes("/")) {
    const [upper, lower] = text.split("/").map((part) => Number(part.trim()));
    param.tolerance_upper = Number.isNaN(upper) ? null : upper;
    param.tolerance_lower = Number.isNaN(lower) ? null : lower;
  }
}

function parseValue(text, previous) {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  if (typeof previous === "number" || /^-?\d+(\.\d+)?$/.test(trimmed)) {
    const number = Number(trimmed);
    return Number.isNaN(number) ? trimmed : number;
  }
  return trimmed;
}

function isSupportedDrawing(file) {
  if (!file) return false;
  const name = file.name.toLowerCase();
  return file.type === "application/pdf"
    || file.type.startsWith("image/")
    || [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"].some((suffix) => name.endsWith(suffix));
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    conversation.scrollTop = conversation.scrollHeight;
  });
}

function scrollMessageIntoView(message) {
  requestAnimationFrame(() => {
    message.scrollIntoView({ block: "start", behavior: "smooth" });
  });
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

checkApiHealth();
