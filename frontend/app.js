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
  reviewContexts: {},
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
  inner_diameter: "内径",
  mean_diameter: "中径",
  free_length: "自由长度",
  body_length: "弹体长度",
  solid_height: "压并高度",
  total_coils: "总圈数",
  active_coils: "有效圈数",
  end_coils: "端圈数",
  support_coils: "支承圈数",
  handedness: "旋向",
  pitch: "节距",
  end_type: "端部形式",
  coil_body_length: "卷绕体长度",
  arm_length: "臂长",
  short_arm_length: "短臂长",
  long_arm_length: "长臂长",
  leg1_length: "第一臂长度",
  leg2_length: "第二臂长度",
  free_angle: "自由角",
  working_angle: "工作角",
  leg1_angle: "第一臂角度",
  leg2_angle: "第二臂角度",
  bend_radius: "折弯半径",
  leg_end_type: "臂端形式",
  mandrel_diameter: "芯轴直径",
  torque: "扭矩",
  hook_type: "钩型",
  hook_outer_diameter: "钩环外径",
  hook_inner_diameter: "钩环内径",
  hook_gap: "钩口间隙",
  hook1_type: "左端钩型",
  hook2_type: "右端钩型",
  hook1_length: "左端钩长度",
  hook2_length: "右端钩长度",
  hook1_outer_diameter: "左钩外径",
  hook2_outer_diameter: "右钩外径",
  hook1_inner_diameter: "左钩内径",
  hook2_inner_diameter: "右钩内径",
  hook1_opening: "左钩开口",
  hook2_opening: "右钩开口",
  hook_orientation: "钩环方向",
  center_to_center_length: "中心距",
  initial_tension: "初拉力",
  ring_type: "类型",
  thickness: "厚度",
  free_diameter: "自由状态直径",
  opening_width: "开口宽度",
  gap_width: "缺口宽度",
  notch_depth: "缺口深度",
  groove_diameter: "槽径",
  groove_width: "槽宽",
  lug_hole_diameter: "耳孔直径",
  lug_center_distance: "耳孔中心距",
  opening_angle: "开口角度",
  section_width: "剖面宽度",
  section_height: "剖面高度",
  chamfer: "倒角",
  corner_radius: "圆角R",
};

const TECH_LABELS = {
  heat_treatment: "热处理",
  surface: "表面处理",
  salt_spray: "盐雾",
  lifetime: "寿命",
  environmental: "环保",
  hardness: "硬度",
  process: "工艺",
  other: "其他",
};

const VLM_AVAILABLE = false;

const SPRING_TYPE_LABELS = {
  compression_spring: "压缩弹簧",
  torsion_spring: "扭转弹簧",
  extension_spring: "拉伸弹簧",
  retaining_ring: "卡簧/挡圈",
  unknown_spring: "未知弹簧",
};

const LOCAL_SPRING_TEMPLATES = {
  compression_spring: {
    spring_type: "compression_spring",
    label: "压缩弹簧",
    fields: [
      { key: "material", label: "材料", required: true },
      { key: "wire_diameter", label: "线径", unit: "mm", required: true },
      { key: "outer_diameter", label: "外径", unit: "mm", required: true },
      { key: "inner_diameter", label: "内径", unit: "mm" },
      { key: "mean_diameter", label: "中径", unit: "mm" },
      { key: "free_length", label: "自由长度", unit: "mm", required: true },
      { key: "body_length", label: "弹体长度", unit: "mm" },
      { key: "solid_height", label: "压并高度", unit: "mm" },
      { key: "total_coils", label: "总圈数", unit: "turns", required: true },
      { key: "active_coils", label: "有效圈数", unit: "turns" },
      { key: "end_coils", label: "端圈数", unit: "turns" },
      { key: "support_coils", label: "支承圈数", unit: "turns" },
      { key: "handedness", label: "旋向", required: true },
      { key: "pitch", label: "节距", unit: "mm" },
      { key: "end_type", label: "端部形式" },
    ],
    collections: [{ key: "load_points", label: "载荷点" }],
  },
  torsion_spring: {
    spring_type: "torsion_spring",
    label: "扭转弹簧",
    fields: [
      { key: "material", label: "材料", required: true },
      { key: "wire_diameter", label: "线径", unit: "mm", required: true },
      { key: "outer_diameter", label: "外径", unit: "mm" },
      { key: "inner_diameter", label: "内径", unit: "mm" },
      { key: "mean_diameter", label: "中径", unit: "mm", required: true },
      { key: "total_coils", label: "总圈数", unit: "turns", required: true },
      { key: "active_coils", label: "有效圈数", unit: "turns" },
      { key: "handedness", label: "旋向", required: true },
      { key: "coil_body_length", label: "卷绕体长度", unit: "mm" },
      { key: "arm_length", label: "臂长", unit: "mm" },
      { key: "short_arm_length", label: "短臂长", unit: "mm" },
      { key: "long_arm_length", label: "长臂长", unit: "mm" },
      { key: "leg1_length", label: "第一臂长度", unit: "mm" },
      { key: "leg2_length", label: "第二臂长度", unit: "mm" },
      { key: "free_angle", label: "自由角", unit: "deg" },
      { key: "working_angle", label: "工作角", unit: "deg" },
      { key: "leg1_angle", label: "第一臂角度", unit: "deg" },
      { key: "leg2_angle", label: "第二臂角度", unit: "deg" },
      { key: "bend_radius", label: "折弯半径", unit: "mm" },
      { key: "leg_end_type", label: "臂端形式" },
      { key: "mandrel_diameter", label: "芯轴直径", unit: "mm" },
      { key: "torque", label: "扭矩", unit: "Nmm" },
    ],
    collections: [{ key: "torque_points", label: "扭矩点" }],
  },
  extension_spring: {
    spring_type: "extension_spring",
    label: "拉伸弹簧",
    fields: [
      { key: "material", label: "材料", required: true },
      { key: "wire_diameter", label: "线径", unit: "mm", required: true },
      { key: "outer_diameter", label: "外径", unit: "mm" },
      { key: "inner_diameter", label: "内径", unit: "mm" },
      { key: "mean_diameter", label: "中径", unit: "mm", required: true },
      { key: "free_length", label: "自由长度", unit: "mm", required: true },
      { key: "body_length", label: "弹体长度", unit: "mm" },
      { key: "total_coils", label: "总圈数", unit: "turns", required: true },
      { key: "active_coils", label: "有效圈数", unit: "turns" },
      { key: "hook_type", label: "钩型" },
      { key: "hook_outer_diameter", label: "钩环外径", unit: "mm" },
      { key: "hook_inner_diameter", label: "钩环内径", unit: "mm" },
      { key: "hook_gap", label: "钩口间隙", unit: "mm" },
      { key: "hook1_type", label: "左端钩型" },
      { key: "hook2_type", label: "右端钩型" },
      { key: "hook1_length", label: "左端钩长度", unit: "mm" },
      { key: "hook2_length", label: "右端钩长度", unit: "mm" },
      { key: "hook1_outer_diameter", label: "左钩外径", unit: "mm" },
      { key: "hook2_outer_diameter", label: "右钩外径", unit: "mm" },
      { key: "hook1_inner_diameter", label: "左钩内径", unit: "mm" },
      { key: "hook2_inner_diameter", label: "右钩内径", unit: "mm" },
      { key: "hook1_opening", label: "左钩开口", unit: "mm" },
      { key: "hook2_opening", label: "右钩开口", unit: "mm" },
      { key: "hook_orientation", label: "钩环方向" },
      { key: "center_to_center_length", label: "中心距", unit: "mm" },
      { key: "initial_tension", label: "初拉力", unit: "N" },
    ],
    collections: [{ key: "load_points", label: "拉力点" }],
  },
  retaining_ring: {
    spring_type: "retaining_ring",
    label: "卡簧/挡圈",
    fields: [
      { key: "material", label: "材料", required: true },
      { key: "ring_type", label: "类型" },
      { key: "wire_diameter", label: "线径", unit: "mm" },
      { key: "thickness", label: "厚度", unit: "mm" },
      { key: "outer_diameter", label: "外径", unit: "mm" },
      { key: "inner_diameter", label: "内径", unit: "mm", required: true },
      { key: "free_diameter", label: "自由状态直径", unit: "mm" },
      { key: "opening_width", label: "开口宽度", unit: "mm" },
      { key: "gap_width", label: "缺口宽度", unit: "mm" },
      { key: "notch_depth", label: "缺口深度", unit: "mm" },
      { key: "groove_diameter", label: "槽径", unit: "mm" },
      { key: "groove_width", label: "槽宽", unit: "mm" },
      { key: "lug_hole_diameter", label: "耳孔直径", unit: "mm" },
      { key: "lug_center_distance", label: "耳孔中心距", unit: "mm" },
      { key: "opening_angle", label: "开口角度", unit: "deg" },
      { key: "section_width", label: "剖面宽度", unit: "mm" },
      { key: "section_height", label: "剖面高度", unit: "mm" },
      { key: "chamfer", label: "倒角" },
      { key: "corner_radius", label: "圆角R", unit: "mm" },
    ],
    collections: [],
  },
  unknown_spring: {
    spring_type: "unknown_spring",
    label: "未知弹簧",
    fields: [
      { key: "material", label: "材料" },
      { key: "wire_diameter", label: "线径", unit: "mm" },
      { key: "outer_diameter", label: "外径", unit: "mm" },
      { key: "inner_diameter", label: "内径", unit: "mm" },
      { key: "mean_diameter", label: "中径", unit: "mm" },
      { key: "free_length", label: "自由长度", unit: "mm" },
      { key: "body_length", label: "弹体长度", unit: "mm" },
      { key: "total_coils", label: "总圈数", unit: "turns" },
      { key: "handedness", label: "旋向" },
      { key: "pitch", label: "节距", unit: "mm" },
      { key: "arm_length", label: "臂长", unit: "mm" },
      { key: "working_angle", label: "工作角", unit: "deg" },
      { key: "hook_type", label: "钩型" },
      { key: "opening_width", label: "开口宽度", unit: "mm" },
      { key: "thickness", label: "厚度", unit: "mm" },
    ],
    collections: [{ key: "load_points", label: "载荷点" }],
  },
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
const advancedOptions = document.getElementById("advancedOptions");
const useOcrInput = document.getElementById("useOcrInput");
const useQwenInput = document.getElementById("useQwenInput");
const ocrProviderInput = document.getElementById("ocrProviderInput");
const useGeometryInput = document.getElementById("useGeometryInput");
const useVlmInput = document.getElementById("useVlmInput");
const visionProviderInput = document.getElementById("visionProviderInput");
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
useOcrInput.addEventListener("change", syncOcrProviderState);
useVlmInput?.addEventListener("change", syncVlmProviderState);
demoButton.addEventListener("click", loadDemoReview);
exportButton.addEventListener("click", () => {
  if (!state.review) return;
  downloadJson(makeExportReview(), "spring_review_confirmed.json");
});

syncOcrProviderState();
syncVlmProviderState();

function syncOcrProviderState() {
  ocrProviderInput.disabled = !useOcrInput.checked;
}

function syncVlmProviderState() {
  if (!visionProviderInput || !useVlmInput) return;
  if (!VLM_AVAILABLE) {
    useVlmInput.checked = false;
    useVlmInput.disabled = true;
    visionProviderInput.value = "none";
    visionProviderInput.disabled = true;
    return;
  }
  useVlmInput.disabled = false;
  visionProviderInput.disabled = !useVlmInput.checked;
}

drawingInput.addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) selectDrawingFile(file);
});

reviewJsonInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  advancedOptions.open = false;
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
  } else if (event.key === "Escape" && advancedOptions.open) {
    advancedOptions.open = false;
  }
});

window.addEventListener("click", (event) => {
  if (advancedOptions.open && !advancedOptions.contains(event.target)) {
    advancedOptions.open = false;
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
  if (useWerk24Input?.checked && !confirmWerk24Input?.checked) {
    appendAssistantText("调用 Werk24 前必须勾选“确认上传到 Werk24”。");
    return;
  }

  advancedOptions.open = false;
  setBusy(true);
  appendUserMessage(`上传图纸：${state.selectedFile.name}`);
  const providerLabel = ocrProviderInput.selectedOptions[0]?.textContent || "OCR";
  const activeEngineLabel = useQwenInput?.checked ? "Qwen3.7 视觉识别" : providerLabel;
  const thinkingId = appendAssistantText(`正在识别图纸，当前引擎：${activeEngineLabel}...`);

  try {
    const form = new FormData();
    form.append("drawing", state.selectedFile);
    form.append("use_qwen", useQwenInput?.checked ? "true" : "false");
    form.append("use_ocr", useOcrInput.checked ? "true" : "false");
    if (useOcrInput.checked) form.append("ocr_provider", ocrProviderInput.value);
    form.append("use_geometry", useGeometryInput?.checked ? "true" : "false");
    form.append("use_vlm", useVlmInput?.checked ? "true" : "false");
    form.append("vision_provider", visionProviderInput?.value || "none");
    form.append("use_werk24", useWerk24Input?.checked ? "true" : "false");
    form.append("confirm_upload_to_werk24", confirmWerk24Input?.checked ? "true" : "false");
    form.append("use_cached_werk24", useCachedWerk24Input?.checked ? "true" : "false");
    form.append("use_sample_ocr", useSampleOcrInput.checked ? "true" : "false");

    const response = await fetch(apiUrl("/api/reviews"), { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "后端审查失败");

    removeMessage(thinkingId);
    state.lastJob = payload;
    setReview(normalizeReview(payload.review), toBackendAssetUrl(payload.image_url));
    appendReviewMessage(makeCompletionText(payload));
    openCompareOverlay();
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
    const qwenStatus = payload.qwen_runtime?.status || "unknown";
    const qwenModel = payload.qwen_runtime?.model || "qwen3.7-plus";
    const ocrRuntime = payload.ocr_runtime || {};
    const defaultProvider = ocrRuntime.default_provider || "unknown";
    const baiduStatus = ocrRuntime.baidu_ocr?.status || "unknown";
    const baiduVlStatus = ocrRuntime.baidu_paddleocr_vl?.status || "unknown";
    const rapidStatus = ocrRuntime.rapidocr?.status || "unknown";
    const geometryStatus = payload.geometry_runtime?.status || "unknown";
    const vlmStatus = payload.vlm_runtime?.status || "unknown";
    setBackendStatus(
      `后端正常 · Qwen ${qwenModel} ${qwenStatus} · OCR ${defaultProvider} · 百度 ${baiduStatus} · 百度VL ${baiduVlStatus} · RapidOCR ${rapidStatus} · 几何 ${geometryStatus} · VLM ${vlmStatus}`,
    );
  } catch (error) {
    setBackendStatus(`后端不可用：${error.message || String(error)}`, true);
  }
}

function appendReviewMessage(title) {
  const message = createMessage("assistant");
  const body = message.querySelector(".message-body");
  const messageId = message.dataset.messageId;
  const context = registerReviewContext(messageId, state.review, state.imageUrl, title);
  renderReviewBody(body, title, context, messageId);
  conversation.appendChild(message);
  state.activeReviewMessageId = messageId;
  scrollMessageIntoView(message);
}

function renderReviewBody(body, title, context = activeReviewContext(), messageId = state.activeReviewMessageId) {
  const review = context?.review || state.review;
  if (!review) return;
  const imageUrl = context?.imageUrl ?? state.imageUrl;
  refreshDerivedStatus(review);
  body.dataset.reviewMessageId = messageId || "";
  body.innerHTML = `
    <div class="message-meta">助手 · 结构化审查</div>
    <p>${escapeHtml(title)}</p>
    ${renderTypeSelectorHtml(review)}
    ${renderSummaryHtml(review)}
    ${renderPreviewHtml(imageUrl)}
    <div class="review-actions">
      <button type="button" data-action="fullscreen">全屏对比</button>
      <button type="button" data-action="confirm-all">全部确认</button>
      <button type="button" data-action="export" ${review ? "" : "disabled"}>导出确认版</button>
    </div>
  `;
  body.querySelector('[data-action="fullscreen"]').addEventListener("click", () => {
    activateReviewContext(messageId);
    openCompareOverlay();
  });
  body.querySelector('[data-action="confirm-all"]').addEventListener("click", () => {
    activateReviewContext(messageId);
    confirmAllFields();
    acknowledgeScannedInput();
    updateLatestReviewMessage("已全部确认，当前审查状态已刷新。");
  });
  body.querySelector('[data-action="export"]').addEventListener("click", () => {
    activateReviewContext(messageId);
    downloadJson(makeExportReview(), "spring_review_confirmed.json");
  });
  bindReviewEditors(body, messageId);
}

function renderTypeSelectorHtml(review) {
  const detection = review.spring_type_detection || {};
  const type = currentSpringType(review);
  const label = SPRING_TYPE_LABELS[type] || type || "未知弹簧";
  const confidence = Number(detection.confidence ?? review.drawing_summary?.spring_type_confidence ?? 0);
  const confidenceText = confidence ? `${Math.round(confidence * 100)}%` : "待确认";
  const needReview = detection.need_human_review || type === "unknown_spring";
  return `
    <section class="spring-type-panel">
      <div>
        <span>识别类型</span>
        <strong>${escapeHtml(label)}</strong>
        <small>${needReview ? "需要人工确认" : "自动识别"} · 置信度 ${escapeHtml(confidenceText)}</small>
      </div>
      <label>
        <span class="sr-only">切换弹簧类型模板</span>
        <select data-action="spring-type">
          ${Object.entries(SPRING_TYPE_LABELS).map(([value, optionLabel]) => `
            <option value="${escapeHtml(value)}" ${value === type ? "selected" : ""}>${escapeHtml(optionLabel)}</option>
          `).join("")}
        </select>
      </label>
    </section>
  `;
}

function renderSummaryHtml(review) {
  const info = review.drawing_summary || {};
  const missing = review.missing_fields || [];
  const springType = currentSpringType(review);
  return `
    <section class="summary-strip">
      ${metricHtml("类型", SPRING_TYPE_LABELS[springType] || springType || "-")}
      ${metricHtml("图纸", info.drawing_name || "-")}
      ${metricHtml("图号", info.drawing_no || "-")}
      ${metricHtml("状态", info.overall_status || "-")}
      ${metricHtml("ERP", review.erp_ready ? "允许" : "阻断")}
      ${metricHtml("缺失字段", missing.length ? missing.map((field) => getFieldMeta(field, review).label || field).join("、") : "无")}
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

function renderPreviewHtml(imageUrl = state.imageUrl) {
  if (!imageUrl) return "";
  return `
    <details class="drawing-preview" open>
      <summary>图纸预览</summary>
      ${renderDrawingCanvasHtml("preview-canvas", imageUrl)}
    </details>
  `;
}

function renderDrawingCanvasHtml(className, imageUrl = state.imageUrl) {
  if (!imageUrl) {
    return `<div class="${escapeHtml(className)} empty-line">未加载图纸预览</div>`;
  }
  return `
    <div class="${escapeHtml(className)}">
      <img src="${escapeHtml(imageUrl)}" alt="drawing">
    </div>
  `;
}

function renderParameterTableHtml(review) {
  const params = review.spring_parameters || {};
  const parameterRows = getParameterFields(params, review).map((field) => {
    const meta = getFieldMeta(field, review);
    return parameterRowHtml(field, params[field] || blankParam(meta.unit), meta);
  });
  const loadPointRows = (params.load_points || []).map((point, index) => loadPointRowHtml(point, index));
  const totalRows = parameterRows.length + loadPointRows.length;
  return `
    <section class="review-block">
      <div class="block-head">
        <h2>结构化尺寸数据</h2>
        <span>${totalRows} 项</span>
      </div>
      <div class="data-table">
        ${dataTableHeadHtml("参数", "数值", "公差")}
        ${parameterRows.join("")}
      </div>
      ${loadPointRows.length ? `
        <div class="data-subsection">
          <div class="data-subsection-head">载荷点</div>
          <div class="data-table">
            ${dataTableHeadHtml("载荷点", "高度", "力值")}
            ${loadPointRows.join("")}
          </div>
        </div>
      ` : ""}
    </section>
  `;
}

function renderGeometryEvidenceHtml(review) {
  const items = Array.isArray(review.dimension_evidence) ? review.dimension_evidence : [];
  if (!items.length) {
    return `
      <section class="review-block geometry-evidence-block">
        <div class="block-head"><h2>几何证据</h2><span>0 项</span></div>
        <div class="empty-line">未生成线段、箭头、圆弧或标题栏证据。</div>
      </section>
    `;
  }
  const counts = items.reduce((acc, item) => {
    const kind = item.kind || "unknown";
    acc[kind] = (acc[kind] || 0) + 1;
    return acc;
  }, {});
  const chips = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([kind, count]) => `<span>${escapeHtml(geometryKindLabel(kind))} ${count}</span>`)
    .join("");
  const rows = items.slice(0, 12).map((item) => `
    <div class="evidence-row">
      <strong>${escapeHtml(geometryKindLabel(item.kind || "unknown"))}</strong>
      <span>${escapeHtml(formatEvidencePosition(item))}</span>
      <small>${Math.round(Number(item.confidence || 0) * 100)}%</small>
    </div>
  `).join("");
  return `
    <section class="review-block geometry-evidence-block">
      <div class="block-head"><h2>几何证据</h2><span>${items.length} 项</span></div>
      <div class="evidence-chip-list">${chips}</div>
      <div class="evidence-list">${rows}</div>
    </section>
  `;
}

function geometryKindLabel(kind) {
  const labels = {
    arrowhead_candidate: "箭头候选",
    circle_candidate: "圆/弧候选",
    contour: "轮廓",
    drawing_content_bbox: "图纸内容区",
    horizontal_line_candidate: "水平线",
    vertical_line_candidate: "垂直线",
    raster_line: "线段",
    title_block_candidate: "标题栏",
    vector_line: "PDF 矢量线",
    vector_rect: "PDF 矢量框",
    vector_text: "PDF 文本",
  };
  return labels[kind] || kind;
}

function formatEvidencePosition(item) {
  const pos = item.position || {};
  const page = item.page ? `P${item.page}` : "P?";
  const x = Number(pos.x);
  const y = Number(pos.y);
  const w = Number(pos.width);
  const h = Number(pos.height);
  if (![x, y, w, h].every(Number.isFinite)) {
    return item.suggested_region || page;
  }
  return `${page} · x${Math.round(x)} y${Math.round(y)} · ${Math.round(w)}×${Math.round(h)}`;
}

function dataTableHeadHtml(nameLabel, primaryLabel, secondaryLabel) {
  return `
    <div class="data-table-head" aria-hidden="true">
      <span>${escapeHtml(nameLabel)}</span>
      <span>${escapeHtml(primaryLabel)}</span>
      <span>${escapeHtml(secondaryLabel)}</span>
      <span>操作</span>
    </div>
  `;
}

function getParameterFields(params, review) {
  const templateFields = getSpringTemplate(review).fields.map((field) => field.key);
  const returnedFields = Object.keys(params).filter((field) => {
    const value = params[field];
    return !["load_points", "torque_points"].includes(field) && value && typeof value === "object" && !Array.isArray(value);
  });
  return Array.from(new Set([...templateFields, ...returnedFields]));
}

function parameterRowHtml(field, param, meta = getFieldMeta(field, state.review)) {
  const evidence = param.evidence || param.suggested_region || "";
  const label = meta.label || FIELD_LABELS[field] || field;
  const requiredMark = meta.required ? " *" : "";
  return `
    <div class="data-row" data-kind="param" data-field="${escapeHtml(field)}">
      <div class="data-label">
        <strong title="${escapeHtml(label)}">${escapeHtml(label + requiredMark)}</strong>
        ${evidence ? `<small title="${escapeHtml(evidence)}">${escapeHtml(evidence)}</small>` : ""}
      </div>
      <label class="data-input-cell data-primary">
        <span class="sr-only">${escapeHtml(label)}数值</span>
        <input data-role="value" aria-label="${escapeHtml(label)}数值" value="${escapeHtml(formatFieldInput(param))}">
      </label>
      <label class="data-input-cell data-secondary">
        <span class="sr-only">${escapeHtml(label)}公差</span>
        <input data-role="tolerance" aria-label="${escapeHtml(label)}公差" value="${escapeHtml(formatTolerance(param))}">
      </label>
      <button class="confirm-button${param.need_human_review ? "" : " confirmed"}" type="button" data-role="confirm">${param.need_human_review ? "确认" : "已确认"}</button>
    </div>
  `;
}

function loadPointRowHtml(point, index) {
  const evidence = point.evidence || "";
  const label = point.label || `F${index + 1}`;
  return `
    <div class="data-row load-point" data-kind="load_point" data-index="${index}">
      <div class="data-label">
        <strong title="${escapeHtml(label)}">${escapeHtml(label)}</strong>
        ${evidence ? `<small title="${escapeHtml(evidence)}">${escapeHtml(evidence)}</small>` : ""}
      </div>
      <label class="data-input-cell data-primary">
        <span class="sr-only">${escapeHtml(label)}高度 mm</span>
        <input data-role="height" aria-label="${escapeHtml(label)}高度 mm" value="${escapeHtml(point.height ?? "")}">
      </label>
      <label class="data-input-cell data-secondary">
        <span class="sr-only">${escapeHtml(label)}力值 N</span>
        <input data-role="force" aria-label="${escapeHtml(label)}力值 N" value="${escapeHtml(point.force ?? "")}">
      </label>
      <button class="confirm-button${point.need_human_review ? "" : " confirmed"}" type="button" data-role="confirm">${point.need_human_review ? "确认" : "已确认"}</button>
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

function bindReviewEditors(root, messageId = state.activeReviewMessageId) {
  const context = getReviewContext(messageId) || activeReviewContext();
  const review = context?.review || state.review;
  if (!review) return;

  root.querySelectorAll('[data-action="spring-type"]').forEach((select) => {
    select.addEventListener("change", (event) => {
      activateReviewContext(messageId);
      switchSpringType(event.target.value);
    });
  });

  root.querySelectorAll('[data-kind="param"]').forEach((row) => {
    const field = row.dataset.field;
    const fieldMeta = getFieldMeta(field, review);
    const param = review.spring_parameters[field] || blankParam(fieldMeta.unit);
    review.spring_parameters[field] = param;
    row.querySelector('[data-role="value"]').addEventListener("change", (event) => {
      activateReviewContext(messageId);
      param.value = parseValue(event.target.value, param.value);
      markParamEdited(param);
      syncBubbleValue(field, param.value);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="tolerance"]').addEventListener("change", (event) => {
      activateReviewContext(messageId);
      applyTolerance(param, event.target.value);
      markParamEdited(param);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      activateReviewContext(messageId);
      confirmParam(param, field);
      updateLatestReviewMessage();
    });
  });

  root.querySelectorAll('[data-kind="load_point"]').forEach((row) => {
    const point = review.spring_parameters.load_points[Number(row.dataset.index)];
    row.querySelector('[data-role="height"]').addEventListener("change", (event) => {
      activateReviewContext(messageId);
      point.height = parseValue(event.target.value, point.height);
      markParamEdited(point);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="force"]').addEventListener("change", (event) => {
      activateReviewContext(messageId);
      point.force = parseValue(event.target.value, point.force);
      markParamEdited(point);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      activateReviewContext(messageId);
      confirmParam(point, `load_point_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
  });

  root.querySelectorAll('[data-kind="technical"]').forEach((row) => {
    const item = review.technical_requirements[Number(row.dataset.index)];
    row.querySelector('[data-role="content"]').addEventListener("change", (event) => {
      activateReviewContext(messageId);
      item.content = event.target.value.trim();
      confirmParam(item, `technical_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      activateReviewContext(messageId);
      confirmParam(item, `technical_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
  });
}

function switchSpringType(type) {
  const template = getLocalTemplate(type);
  state.review.drawing_summary ||= {};
  state.review.drawing_summary.spring_type = template.spring_type;
  state.review.drawing_summary.spring_type_label = template.label;
  state.review.drawing_summary.spring_type_confidence = 1;
  state.review.spring_type_detection = {
    spring_type: template.spring_type,
    label: template.label,
    confidence: 1,
    need_human_review: false,
    source: "manual",
  };
  state.review.spring_template = structuredClone(template);
  state.review.spring_parameters ||= {};
  for (const field of template.fields || []) {
    state.review.spring_parameters[field.key] ||= blankParam(field.unit);
    if (!state.review.spring_parameters[field.key].unit && field.unit) {
      state.review.spring_parameters[field.key].unit = field.unit;
    }
  }
  for (const collection of template.collections || []) {
    state.review.spring_parameters[collection.key] ||= [];
  }
  updateLatestReviewMessage("已切换弹簧模板，请继续确认结构化尺寸数据。");
}

function updateLatestReviewMessage(title = "已更新结构化尺寸数据，请继续确认。") {
  refreshDerivedStatus(state.review);
  exportButton.disabled = false;
  const context = getReviewContext(state.activeReviewMessageId);
  if (context) {
    context.review = state.review;
    context.imageUrl = state.imageUrl;
    context.title = title;
  }
  const activeMessage = conversation.querySelector(`[data-message-id="${state.activeReviewMessageId}"]`);
  const body = activeMessage?.querySelector(".message-body");
  if (!body) {
    appendReviewMessage(title);
    return;
  }
  renderReviewBody(body, title, context || activeReviewContext(), state.activeReviewMessageId);
  if (state.compareOpen) {
    renderCompareOverlay();
  }
}

function openCompareOverlay(messageId = state.activeReviewMessageId) {
  if (messageId) activateReviewContext(messageId);
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
          ${renderTypeSelectorHtml(state.review)}
          ${renderSummaryHtml(state.review)}
          ${renderParameterTableHtml(state.review)}
          ${renderGeometryEvidenceHtml(state.review)}
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

function registerReviewContext(messageId, review, imageUrl, title = "") {
  const context = {
    review,
    imageUrl,
    title,
  };
  state.reviewContexts[messageId] = context;
  return context;
}

function getReviewContext(messageId = state.activeReviewMessageId) {
  return messageId ? state.reviewContexts[messageId] : null;
}

function activeReviewContext() {
  return getReviewContext() || {
    review: state.review,
    imageUrl: state.imageUrl,
    title: "",
  };
}

function activateReviewContext(messageId = state.activeReviewMessageId) {
  const context = getReviewContext(messageId);
  if (!context) return null;
  state.activeReviewMessageId = messageId;
  setReview(context.review, context.imageUrl);
  return context;
}

function setReview(review, imageUrl) {
  state.review = review;
  state.imageUrl = imageUrl;
  exportButton.disabled = false;
}

function makeCompletionText(payload) {
  const warnings = payload.warnings?.length ? `警告：${payload.warnings.join("；")}` : "";
  const sources = payload.candidate_sources?.join(" / ") || "无";
  const businessCount = payload.business_candidate_count ?? payload.candidate_count ?? 0;
  const evidenceCount = payload.geometry_evidence_count ?? 0;
  return `审查完成：${businessCount} 个结构化候选，${evidenceCount} 项几何证据，来源 ${sources}。${warnings}`;
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
  submitButton.classList.toggle("busy", busy);
  submitButton.textContent = busy ? "审查中..." : "↑";
  submitButton.setAttribute("aria-label", busy ? "正在审查" : "开始审查");
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
  cloned.drawing_summary.spring_type ||= "compression_spring";
  cloned.spring_template ||= getLocalTemplate(cloned.drawing_summary.spring_type);
  cloned.spring_parameters ||= {};
  cloned.spring_parameters.load_points ||= [];
  cloned.technical_requirements ||= [];
  cloned.dimension_evidence ||= [];
  cloned.review_results ||= [];
  cloned.balloons ||= [];
  cloned.manual_confirmations ||= {};
  return cloned;
}

function currentSpringType(review) {
  return review?.drawing_summary?.spring_type
    || review?.spring_template?.spring_type
    || review?.spring_type_detection?.spring_type
    || "unknown_spring";
}

function getLocalTemplate(type) {
  return structuredClone(LOCAL_SPRING_TEMPLATES[type] || LOCAL_SPRING_TEMPLATES.unknown_spring);
}

function getSpringTemplate(review) {
  const currentType = currentSpringType(review);
  const backendTemplate = review?.spring_template;
  if (backendTemplate?.spring_type === currentType && Array.isArray(backendTemplate.fields)) {
    return backendTemplate;
  }
  return getLocalTemplate(currentType);
}

function getFieldMeta(field, review) {
  return getSpringTemplate(review).fields.find((item) => item.key === field) || {
    key: field,
    label: FIELD_LABELS[field] || field,
  };
}

function requiredFieldsForReview(review) {
  return getSpringTemplate(review).fields.filter((field) => field.required).map((field) => field.key);
}

function refreshDerivedStatus(review) {
  const requiredMissing = requiredFieldsForReview(review).filter((field) => {
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

function blankParam(unit = null) {
  return {
    value: "",
    unit,
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
