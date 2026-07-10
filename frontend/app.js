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
  compareTab: "parameters",
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
  standardizationChatBusy: false,
  standardizationChatTypingTimer: null,
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
  standard_no: "标准号",
  spring_family: "弹簧族",
  spring_shape: "结构形状",
  manufacturing_method: "成形方式",
  wire_section: "线材截面",
  pitch_type: "节距类型",
  accuracy_grade: "通用精度等级",
  diameter_accuracy_grade: "直径精度等级",
  free_length_accuracy_grade: "自由高度精度等级",
  load_accuracy_grade: "载荷精度等级",
  stiffness_accuracy_grade: "刚度精度等级",
  wire_diameter: "线径",
  outer_diameter: "外径",
  inner_diameter: "内径",
  mean_diameter: "中径",
  controlled_diameter_field: "受控直径",
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
  end_grinding: "端面磨削",
  spring_rate: "刚度",
  perpendicularity: "垂直度",
  straightness: "直线度",
  permanent_set_limit: "永久变形限值",
  spring_index: "旋绕比",
  slenderness_ratio: "细长比",
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

const PARAMETER_COLLECTION_FIELDS = new Set(["load_points", "torque_points"]);

const COMPRESSION_CORE_PARAMETER_FIELDS = new Set([
  "material",
  "standard_no",
  "accuracy_grade",
  "wire_diameter",
  "outer_diameter",
  "inner_diameter",
  "mean_diameter",
  "free_length",
  "total_coils",
  "handedness",
  "end_grinding",
]);

const STANDARDIZATION_PARAMETER_ASSOCIATIONS = {
  load_points: new Set(["active_coils", "load_accuracy_grade"]),
  spring_rate: new Set(["active_coils", "stiffness_accuracy_grade"]),
};

const LOCAL_SPRING_TEMPLATES = {
  compression_spring: {
    spring_type: "compression_spring",
    label: "压缩弹簧",
    fields: [
      { key: "material", label: "材料", required: true },
      { key: "standard_no", label: "标准号" },
      { key: "accuracy_grade", label: "通用精度等级" },
      { key: "diameter_accuracy_grade", label: "直径精度等级" },
      { key: "free_length_accuracy_grade", label: "自由高度精度等级" },
      { key: "load_accuracy_grade", label: "载荷精度等级" },
      { key: "stiffness_accuracy_grade", label: "刚度精度等级" },
      { key: "wire_diameter", label: "线径", unit: "mm", required: true },
      { key: "outer_diameter", label: "外径", unit: "mm", required: true },
      { key: "inner_diameter", label: "内径", unit: "mm" },
      { key: "mean_diameter", label: "中径", unit: "mm" },
      { key: "controlled_diameter_field", label: "受控直径" },
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
      { key: "end_grinding", label: "端面磨削" },
      { key: "spring_rate", label: "刚度", unit: "N/mm" },
      { key: "perpendicularity", label: "垂直度", unit: "mm" },
      { key: "straightness", label: "直线度", unit: "mm" },
      { key: "permanent_set_limit", label: "永久变形限值", unit: "mm" },
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
const useVlmInput = document.getElementById("useVlmInput");
const useLlmStandardizationInput = document.getElementById("useLlmStandardizationInput");
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
    form.append("use_geometry", "false");
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

async function runStandardization(messageId = state.activeReviewMessageId) {
  if (!state.review || state.busy) return false;
  activateReviewContext(messageId);
  setBusy(true);
  const endpoint = state.lastJob?.job_id
    ? `/api/reviews/${encodeURIComponent(state.lastJob.job_id)}/standardize`
    : "/api/reviews/standardize";
  const thinkingId = appendAssistantText("正在根据当前确认/修改后的参数进行标准化...");
  try {
    const response = await fetch(apiUrl(endpoint), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review: state.review,
        use_llm_standardization: useLlmStandardizationInput?.checked ? true : false,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "标准化失败");

    removeMessage(thinkingId);
    if (payload.job_id) {
      state.lastJob = { ...(state.lastJob || {}), ...payload };
    }
    setReview(normalizeReview(payload.review), state.imageUrl);
    const context = getReviewContext(messageId);
    if (context) {
      context.review = state.review;
      context.imageUrl = state.imageUrl;
    }
    const warnings = payload.warnings?.length ? ` 警告：${payload.warnings.join("；")}` : "";
    const llmSummary = payload.llm_standardization?.result_count
      ? `，其中 LLM/RAG ${payload.llm_standardization.result_count} 项`
      : "";
    updateLatestReviewMessage(`标准化完成：生成 ${state.review.standardization_results.length} 项建议${llmSummary}。${warnings}`);
    return true;
  } catch (error) {
    replaceMessage(thinkingId, error.message || String(error), true);
    return false;
  } finally {
    setBusy(false);
  }
}

async function runStandardizationChat(message, messageId = state.activeReviewMessageId, useLlm = true) {
  const text = String(message || "").trim();
  if (!state.review || !text || state.standardizationChatBusy) return;
  activateReviewContext(messageId);
  const requestReview = normalizeReview(structuredClone(state.review));
  const pendingTurnId = appendPendingStandardizationChatTurn(text, messageId);
  state.standardizationChatBusy = true;
  refreshReviewSurfaces({ scrollChat: true });
  const endpoint = state.lastJob?.job_id
    ? `/api/reviews/${encodeURIComponent(state.lastJob.job_id)}/standardization-chat`
    : "/api/reviews/standardization-chat";
  let isTypingFinalReply = false;
  try {
    const response = await fetch(apiUrl(endpoint), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review: requestReview,
        message: text,
        use_llm: Boolean(useLlm),
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "标准化对话失败");

    if (payload.job_id) {
      state.lastJob = { ...(state.lastJob || {}), job_id: payload.job_id };
    }
    const normalized = normalizeReview(payload.review);
    const finalTurnIndex = Math.max((normalized.standardization_chat || []).length - 1, 0);
    const finalTurn = normalized.standardization_chat?.[finalTurnIndex];
    const finalAssistantText = finalTurn?.assistant || "";
    if (finalTurn) {
      finalTurn.assistant = "";
      finalTurn.typing = true;
      finalTurn._client_id = pendingTurnId;
    }
    setReview(normalized, state.imageUrl);
    const context = getReviewContext(messageId);
    if (context) {
      context.review = state.review;
      context.imageUrl = state.imageUrl;
    }
    refreshReviewSurfaces({ scrollChat: true });
    isTypingFinalReply = true;
    animateStandardizationChatReply(finalTurnIndex, finalAssistantText, messageId);
  } catch (error) {
    replacePendingStandardizationChatTurn(pendingTurnId, `标准化对话失败：${error.message || String(error)}`, true);
    refreshReviewSurfaces({ scrollChat: true });
  } finally {
    if (!isTypingFinalReply) {
      state.standardizationChatBusy = false;
      refreshReviewSurfaces({ scrollChat: true });
    }
  }
}

function appendPendingStandardizationChatTurn(text, messageId = state.activeReviewMessageId) {
  const clientId = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  state.review.standardization_chat ||= [];
  state.review.standardization_chat.push({
    _client_id: clientId,
    created_at: new Date().toISOString(),
    user: text,
    assistant: "正在生成回复",
    pending: true,
    suggested_actions: [],
  });
  const context = getReviewContext(messageId);
  if (context) {
    context.review = state.review;
    context.imageUrl = state.imageUrl;
  }
  return clientId;
}

function replacePendingStandardizationChatTurn(clientId, assistantText, isError = false) {
  const turns = state.review?.standardization_chat || [];
  const turn = turns.find((item) => item?._client_id === clientId);
  if (!turn) return;
  turn.assistant = assistantText;
  turn.pending = false;
  turn.typing = false;
  turn.error = Boolean(isError);
}

function refreshReviewSurfaces(options = {}) {
  if (!state.review) return;
  refreshDerivedStatus(state.review);
  exportButton.disabled = false;
  const context = getReviewContext(state.activeReviewMessageId);
  if (context) {
    context.review = state.review;
    context.imageUrl = state.imageUrl;
  }
  const activeMessage = conversation.querySelector(`[data-message-id="${state.activeReviewMessageId}"]`);
  const body = activeMessage?.querySelector(".message-body");
  if (body) {
    renderReviewBody(body, context?.title || "已更新结构化尺寸数据，请继续确认。", context || activeReviewContext(), state.activeReviewMessageId);
  }
  if (state.compareOpen) {
    renderCompareOverlay();
  }
  if (options.scrollChat) {
    requestAnimationFrame(scrollStandardizationChatToBottom);
  }
}

function animateStandardizationChatReply(turnIndex, finalText, messageId = state.activeReviewMessageId) {
  clearTimeout(state.standardizationChatTypingTimer);
  const fullText = String(finalText || "");
  const turns = state.review?.standardization_chat || [];
  const turn = turns[turnIndex];
  if (!turn) return;
  let offset = 0;
  const step = fullText.length > 180 ? 3 : 1;

  function renderTick() {
    const visible = fullText.slice(0, offset);
    document.querySelectorAll(`[data-chat-turn-index="${turnIndex}"] [data-role="chat-assistant-text"]`).forEach((node) => {
      node.textContent = visible || "正在生成回复";
    });
    scrollStandardizationChatToBottom();
  }

  function finish() {
    turn.assistant = fullText;
    turn.typing = false;
    turn.pending = false;
    state.standardizationChatBusy = false;
    const context = getReviewContext(messageId);
    if (context) {
      context.review = state.review;
      context.imageUrl = state.imageUrl;
    }
    refreshReviewSurfaces({ scrollChat: true });
    updateLatestReviewMessage("标准化对话已回复，请继续确认或修改参数。");
  }

  renderTick();
  const tick = () => {
    offset = Math.min(fullText.length, offset + step);
    renderTick();
    if (offset >= fullText.length) {
      state.standardizationChatTypingTimer = null;
      finish();
      return;
    }
    state.standardizationChatTypingTimer = setTimeout(tick, 24);
  };
  state.standardizationChatTypingTimer = setTimeout(tick, 120);
}

function scrollStandardizationChatToBottom() {
  document.querySelectorAll(".standardization-chat-list").forEach((list) => {
    list.scrollTop = list.scrollHeight;
  });
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
    const llmStandardizationStatus = payload.llm_standardization_runtime?.status || "unknown";
    const standardizationChatStatus = payload.standardization_chat_runtime?.status || "unknown";
    const vlmStatus = payload.vlm_runtime?.status || "unknown";
    setBackendStatus(
      `后端正常 · Qwen ${qwenModel} ${qwenStatus} · OCR ${defaultProvider} · 百度 ${baiduStatus} · 百度VL ${baiduVlStatus} · RapidOCR ${rapidStatus} · 标准化LLM ${llmStandardizationStatus} · 对话LLM ${standardizationChatStatus} · VLM ${vlmStatus}`,
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
      <button type="button" data-action="standardize">${standardizeButtonLabel(review)}</button>
      <button type="button" data-action="confirm-all">全部确认</button>
      <button type="button" data-action="export" ${review ? "" : "disabled"}>导出确认版</button>
    </div>
    ${renderStandardizationChatHtml(review)}
  `;
  body.querySelector('[data-action="fullscreen"]').addEventListener("click", () => {
    activateReviewContext(messageId);
    openCompareOverlay();
  });
  body.querySelector('[data-action="standardize"]').addEventListener("click", () => {
    runStandardization(messageId);
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

function standardizeButtonLabel(review) {
  return (review?.standardization_results || []).length ? "重新标准化" : "标准化";
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

function renderStandardSelectionHtml(review) {
  const selection = review.standard_selection || {};
  const features = review.spring_features || {};
  const status = selection.status || "need_review";
  const selected = selection.selected_standard || "未选择";
  const confidence = selection.confidence != null ? `${Math.round(Number(selection.confidence || 0) * 100)}%` : "-";
  const evidence = Array.isArray(selection.evidence) ? selection.evidence : [];
  const references = Array.isArray(selection.references) ? selection.references : [];
  const candidateStandards = Array.isArray(selection.candidate_standards) ? selection.candidate_standards : [];
  const metadata = selection.metadata || {};
  const auxiliaryEvidence = Array.isArray(metadata.auxiliary_evidence) ? metadata.auxiliary_evidence : [];
  const conflicts = Array.isArray(metadata.conflicts) ? metadata.conflicts : [];
  const thresholdRows = [];
  if (metadata.wire_diameter_mm != null && metadata.wire_diameter_threshold_mm != null) {
    thresholdRows.push(`线径 d=${formatCompactNumber(metadata.wire_diameter_mm)}mm / 阈值 ${formatCompactNumber(metadata.wire_diameter_threshold_mm)}mm`);
  }
  const featureRows = ["spring_family", "spring_shape", "manufacturing_method", "wire_section", "pitch_type"].map((field) => {
    const item = features[field] || {};
    return `
      <div class="standard-feature">
        <span>${escapeHtml(FIELD_LABELS[field] || field)}</span>
        <strong>${escapeHtml(featureValueLabel(field, item.value))}</strong>
      </div>
    `;
  }).join("");
  const candidateRows = candidateStandards.map((item) => `
    <span>${escapeHtml(item.standard_no || "")}${item.rules_available ? "" : " · 规则待接入"}</span>
  `).join("");
  const referenceRows = references.map((item) => `
    <small>${escapeHtml(item.standard_no || "")} · ${escapeHtml(item.source || "RAG")} · ${escapeHtml(item.status || "")}</small>
  `).join("");
  const thresholdHtml = thresholdRows.map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  const auxiliaryHtml = auxiliaryEvidence.map((item) => `<small>${escapeHtml(item)}</small>`).join("");
  const conflictHtml = conflicts.map((item) => `<small>${escapeHtml(item)}</small>`).join("");
  return `
    <section class="review-block standard-selection-block">
      <div class="block-head">
        <h2>标准选择判断</h2>
        <span class="normalization-status ${escapeHtml(status)}">${escapeHtml(standardSelectionStatusLabel(status))}</span>
      </div>
      <div class="standard-selection-card">
        <div class="standard-selection-main">
          <div>
            <span>推荐标准</span>
            <strong>${escapeHtml(selected)}</strong>
            ${selection.standard_label ? `<small>${escapeHtml(selection.standard_label)}</small>` : ""}
          </div>
          <div>
            <span>置信度</span>
            <strong>${escapeHtml(confidence)}</strong>
            <small>${escapeHtml(selectionSourceLabel(selection.selection_source))}</small>
          </div>
          <button type="button" data-action="confirm-standard-selection" ${selection.need_human_review ? "" : "disabled"}>
            ${selection.need_human_review ? "确认判断" : "已确认"}
          </button>
        </div>
        <div class="standard-features">${featureRows}</div>
        ${selection.reason ? `<p>${escapeHtml(selection.reason)}</p>` : ""}
        ${thresholdHtml ? `<div class="standard-selection-metadata">${thresholdHtml}</div>` : ""}
        ${evidence.length ? `<div class="standard-selection-evidence">${evidence.map((item) => `<small>${escapeHtml(item)}</small>`).join("")}</div>` : ""}
        ${auxiliaryHtml ? `<div class="standard-selection-auxiliary">${auxiliaryHtml}</div>` : ""}
        ${conflictHtml ? `<div class="standard-selection-conflicts">${conflictHtml}</div>` : ""}
        ${candidateRows ? `<div class="standard-selection-candidates">${candidateRows}</div>` : ""}
        ${referenceRows ? `<div class="standard-selection-references">${referenceRows}</div>` : ""}
      </div>
    </section>
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
  const fieldGroups = getParameterFieldGroups(params, review);
  const parameterRows = fieldGroups.core.map((field) => {
    const meta = getFieldMeta(field, review);
    return parameterRowHtml(field, params[field] || blankParam(meta.unit), meta);
  });
  const advancedRows = fieldGroups.advanced.map((field) => {
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
      ${advancedRows.length ? `
        <details class="advanced-parameters">
          <summary>
            <span>高级参数</span>
            <small>${advancedRows.length} 项有识别值或标准化建议</small>
          </summary>
          <div class="data-table advanced-data-table">
            ${dataTableHeadHtml("参数", "数值", "公差")}
            ${advancedRows.join("")}
          </div>
        </details>
      ` : ""}
    </section>
  `;
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
    return !PARAMETER_COLLECTION_FIELDS.has(field) && value && typeof value === "object" && !Array.isArray(value);
  });
  return Array.from(new Set([...templateFields, ...returnedFields]));
}

function getParameterFieldGroups(params, review) {
  const fields = getParameterFields(params, review);
  if (!isCompressionSpringReview(review)) {
    return { core: fields, advanced: [] };
  }
  return {
    core: fields.filter((field) => COMPRESSION_CORE_PARAMETER_FIELDS.has(field)),
    advanced: fields.filter((field) => {
      if (COMPRESSION_CORE_PARAMETER_FIELDS.has(field)) return false;
      return shouldShowAdvancedParameter(field, params[field], review);
    }),
  };
}

function shouldShowAdvancedParameter(field, param, review) {
  return hasParameterContent(param) || hasStandardizationForField(field, review);
}

function hasParameterContent(param) {
  if (!param || typeof param !== "object" || Array.isArray(param)) return false;
  if (param.value != null && param.value !== "") return true;
  if (param.tolerance_upper != null && param.tolerance_upper !== "") return true;
  if (param.tolerance_lower != null && param.tolerance_lower !== "") return true;
  if (param.default_source) return true;
  if (param.evidence || param.suggested_region) return true;
  const sources = Array.isArray(param.source) ? param.source : [param.source].filter(Boolean);
  if (sources.some((item) => ["human_edited", "human_confirmed"].includes(item))) return true;
  return false;
}

function hasStandardizationForField(field, review) {
  return (review.standardization_results || []).some((item) => {
    const target = String(item.target_field || "");
    const targetRoot = target.split(".")[0];
    return target === field
      || target.startsWith(`${field}.`)
      || Boolean(STANDARDIZATION_PARAMETER_ASSOCIATIONS[targetRoot]?.has(field));
  });
}

function isCompressionSpringReview(review) {
  if (currentSpringType(review) === "compression_spring") return true;
  const templateLabel = String(review?.spring_template?.label || "");
  return templateLabel.includes("压缩") || normalizeSpringTypeValue(review?.spring_template?.spring_type) === "compression_spring";
}

function parameterRowHtml(field, param, meta = getFieldMeta(field, state.review)) {
  const evidence = param.evidence || param.suggested_region || "";
  const label = meta.label || FIELD_LABELS[field] || field;
  const requiredMark = meta.required ? " *" : "";
  const badges = [];
  if (param.default_source === "company_default") {
    badges.push("公司默认 / 待确认");
  }
  return `
    <div class="data-row" data-kind="param" data-field="${escapeHtml(field)}">
      <div class="data-label">
        <strong title="${escapeHtml(label)}">${escapeHtml(label + requiredMark)}</strong>
        ${evidence ? `<small title="${escapeHtml(evidence)}">${escapeHtml(evidence)}</small>` : ""}
        ${badges.length ? `<div class="parameter-badges">${badges.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
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

function renderDerivedParametersHtml(review) {
  const derived = review.derived_parameters || {};
  const rows = Object.entries(derived)
    .filter(([, value]) => value && typeof value === "object" && !Array.isArray(value))
    .map(([field, item]) => `
      <div class="derived-row">
        <strong>${escapeHtml(FIELD_LABELS[field] || item.field || field)}</strong>
        <span>${escapeHtml(formatStandardValue(item.value, item.unit))}</span>
        <small>${escapeHtml(item.formula || "")}</small>
      </div>
    `).join("");
  const loadDeflections = Array.isArray(derived.load_point_deflections) ? derived.load_point_deflections : [];
  const loadRows = loadDeflections.map((item) => `
    <div class="derived-row">
      <strong>${escapeHtml(item.label || "载荷点")}</strong>
      <span>${escapeHtml(formatStandardValue(item.deflection, item.deflection_unit))}</span>
      <small>${escapeHtml(item.formula || "")}</small>
    </div>
  `).join("");
  if (!rows && !loadRows) {
    return `
      <section class="review-block">
        <div class="block-head"><h2>派生参数</h2><span>0 项</span></div>
        <div class="empty-line">暂未生成中径、旋绕比、细长比或载荷变形量。</div>
      </section>
    `;
  }
  return `
    <section class="review-block">
      <div class="block-head"><h2>派生参数</h2><span>${Object.keys(derived).length} 组</span></div>
      <div class="derived-list">${rows}${loadRows}</div>
    </section>
  `;
}

function renderStandardizationHtml(review) {
  const results = Array.isArray(review.standardization_results) ? review.standardization_results : [];
  if (!results.length) {
    return `
      <section class="review-block">
        <div class="block-head"><h2>标准化建议</h2><span>0 项</span></div>
        <div class="empty-line">请先确认或修改识别参数，再点击“标准化”生成建议。</div>
      </section>
    `;
  }
  return `
    <section class="review-block">
      <div class="block-head"><h2>标准化建议</h2><span>${results.length} 项</span></div>
      <div class="standardization-list">
        ${results.map((item, index) => `
          <div class="standardization-row" data-kind="standardization" data-index="${index}">
            <div>
              <strong>${escapeHtml(targetFieldLabel(item.target_field))}</strong>
              <span class="normalization-status ${escapeHtml(item.status || "need_context")}">${escapeHtml(standardizationStatusLabel(item.status))}</span>
            </div>
            <div>
              <span>${escapeHtml(formatStandardizationSuggestion(item))}</span>
              <small>${escapeHtml(item.standard_no || "")}</small>
            </div>
            <p>${escapeHtml(item.basis || "")}</p>
            <button type="button" data-role="confirm-standard" ${canConfirmStandardization(item) ? "" : "disabled"}>确认建议</button>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderStandardizationChatHtml(review) {
  const turns = Array.isArray(review.standardization_chat) ? review.standardization_chat : [];
  const rows = turns.map((turn, turnIndex) => {
    const isGenerating = Boolean(turn.pending || turn.typing);
    const assistantText = turn.assistant || (isGenerating ? "正在生成回复" : "");
    return `
    <div class="standardization-chat-turn${turn.error ? " error" : ""}${isGenerating ? " generating" : ""}" data-chat-turn-index="${turnIndex}">
      <div class="chat-line user-line">
        <strong>你</strong>
        <span>${escapeHtml(turn.user || "")}</span>
      </div>
      <div class="chat-line assistant-line">
        <strong>助手</strong>
        <span data-role="chat-assistant-text">${escapeHtml(assistantText)}</span>
      </div>
      ${isGenerating ? "" : renderStandardizationChatIntentMetaHtml(turn)}
      ${isGenerating ? "" : renderStandardizationChatConstraintsHtml(turn)}
      ${isGenerating ? "" : renderStandardizationChatActionsHtml(turn, turnIndex)}
    </div>
  `;
  }).join("");
  const chatBusyAttr = state.standardizationChatBusy ? "disabled" : "";
  return `
    <section class="review-block standardization-chat-block">
      <div class="block-head"><h2>标准化对话</h2><span>${turns.length} 轮</span></div>
      <div class="standardization-chat-list">
        ${rows || `<div class="standardization-chat-empty">你好，可以问我标准化依据、参数调整建议，或输入“请根据标准化手册推荐完整标准化方案”。</div>`}
      </div>
      <form class="standardization-chat-form" data-action="standardization-chat">
        <input data-role="standardization-chat-input" type="text" placeholder="发消息，询问标准化依据或修改参数...">
        <button type="submit" ${chatBusyAttr}>${state.standardizationChatBusy ? "生成中" : "发送"}</button>
      </form>
    </section>
  `;
}

function renderStandardizationChatIntentMetaHtml(turn) {
  const parts = [];
  if (turn.intent?.target_label) {
    parts.push(`意图：${turn.intent.target_label}`);
  } else if (turn.intent?.type) {
    parts.push(`意图：${standardizationChatIntentLabel(turn.intent.type)}`);
  }
  if (turn.intent?.status) {
    parts.push(standardizationChatStatusLabel(turn.intent.status));
  }
  if (turn.llm_chat?.status === "generated") {
    parts.push("LLM/RAG");
  } else if (turn.llm_chat?.status === "failed") {
    parts.push("LLM降级");
  }
  return parts.length ? `<small>${escapeHtml(parts.join(" · "))}</small>` : "";
}

function renderStandardizationChatConstraintsHtml(turn) {
  const constraints = standardizationChatConstraints(turn);
  if (!constraints.length) return "";
  return `
    <div class="standardization-chat-constraints">
      <strong>约束</strong>
      <div>${constraints.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
    </div>
  `;
}

function renderStandardizationChatActionsHtml(turn, turnIndex) {
  const actions = Array.isArray(turn.suggested_actions) ? turn.suggested_actions : [];
  if (!actions.length) return "";
  return `
    <div class="standardization-chat-actions">
      ${renderStandardizationChatBatchHtml(turn, turnIndex)}
      ${actions.map((action, actionIndex) => renderStandardizationChatActionHtml(action, turnIndex, actionIndex)).join("")}
    </div>
  `;
}

function renderStandardizationChatActionHtml(action, turnIndex, actionIndex) {
  const target = String(action.target_field || "");
  const canApply = canApplyStandardizationChatAction(action);
  const status = action.status === "applied" ? "已应用" : "待确认";
  const affected = Array.isArray(action.affected_fields) ? action.affected_fields : [];
  return `
    <div class="standardization-chat-action" data-kind="chat_action" data-turn-index="${turnIndex}" data-action-index="${actionIndex}">
      <div>
        <strong>${escapeHtml(action.target_label || targetFieldLabel(target) || "修改建议")}</strong>
        <span>${escapeHtml(formatStandardizationChatActionValue(action))}</span>
      </div>
      ${renderStandardizationChatActionPreviewHtml(action)}
      <div class="standardization-chat-action-notes">
        ${affected.length ? `<small>影响：${escapeHtml(affected.map((field) => targetFieldLabel(field)).join("、"))}</small>` : ""}
        ${action.reason ? `<small>${escapeHtml(action.reason)}</small>` : ""}
      </div>
      <button type="button" data-role="apply-chat-action" ${canApply ? "" : "disabled"}>${escapeHtml(status === "已应用" ? status : "应用建议")}</button>
    </div>
  `;
}

function renderStandardizationChatBatchHtml(turn, turnIndex) {
  const validation = validateStandardizationChatBatch(turn);
  if (validation.candidates.length < 2) return "";
  const label = validation.ok ? `应用本轮全部建议（${validation.candidates.length}）` : "本轮批量应用不可用";
  return `
    <div class="standardization-chat-batch" data-kind="chat_action_batch" data-turn-index="${turnIndex}">
      <div>
        <strong>本轮建议</strong>
        <small>${escapeHtml(validation.message || `可一次写回 ${validation.candidates.length} 条建议，写回后会重新标准化。`)}</small>
      </div>
      <button type="button" data-role="apply-chat-turn-actions" ${validation.ok ? "" : "disabled"}>${escapeHtml(label)}</button>
    </div>
  `;
}

function renderStandardizationChatActionPreviewHtml(action) {
  if (!action?.target_field || !hasStandardizationChatActionValue(action)) return "";
  const target = String(action.target_field);
  const unit = action.unit || "";
  const previous = action.type === "propose_tolerance_patch"
    ? (action.status === "applied" && action.previous_tolerance ? action.previous_tolerance : currentActionTargetTolerance(target))
    : (action.status === "applied" && action.previous_value !== undefined ? action.previous_value : currentActionTargetValue(target));
  const proposed = action.type === "propose_tolerance_patch"
    ? normalizeActionTolerance(action, previous)
    : normalizeActionValue(action.proposed_value, previous);
  return `
    <div class="standardization-chat-preview">
      <small>当前</small>
      <span>${escapeHtml(action.type === "propose_tolerance_patch" ? formatTolerancePair(previous, unit) : formatStandardValue(previous, unit))}</span>
      <small>建议</small>
      <span>${escapeHtml(action.type === "propose_tolerance_patch" ? formatTolerancePair(proposed, unit) : formatStandardValue(proposed, unit))}</span>
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
            ${renderSurfaceNormalizationHtml(item)}
            <button type="button" data-role="confirm">${item.need_human_review ? "确认" : "已确认"}</button>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderSurfaceNormalizationHtml(item) {
  if (item.type !== "surface") return "";
  const status = item.normalization_status || "unmatched";
  const raw = item.raw_content || item.evidence || "";
  const reason = item.normalization_reason || "";
  const candidates = Array.isArray(item.standard_candidates) ? item.standard_candidates : [];
  const lockedStatuses = new Set(["matched", "alias_matched", "llm_auto_matched", "human_confirmed"]);
  const candidateOptions = candidates
    .filter((candidate) => candidate?.term)
    .map((candidate) => `
      <option value="${escapeHtml(candidate.term)}">${escapeHtml(candidate.term)}${candidate.score ? ` · ${Math.round(Number(candidate.score) * 100)}%` : ""}</option>
    `).join("");
  return `
    <div class="requirement-meta">
      <span class="normalization-status ${escapeHtml(status)}">${escapeHtml(surfaceStatusLabel(status))}</span>
      ${raw ? `<small>图纸原文：${escapeHtml(raw)}</small>` : ""}
      ${reason ? `<small>说明：${escapeHtml(reason)}</small>` : ""}
      ${candidateOptions && !lockedStatuses.has(status) ? `
        <label class="candidate-select">候选标准术语
          <select data-role="standard-candidate">
            <option value="">选择标准术语</option>
            ${candidateOptions}
          </select>
        </label>
      ` : ""}
    </div>
  `;
}

function surfaceStatusLabel(status) {
  const labels = {
    matched: "已标准化",
    alias_matched: "按别名标准化",
    llm_auto_matched: "AI自动标准化",
    human_confirmed: "人工确认",
    suggested: "候选待确认",
    unmatched: "未标准化，保持原文",
  };
  return labels[status] || "待确认";
}

function standardizationStatusLabel(status) {
  const labels = {
    suggested: "可确认建议",
    llm_suggested: "LLM建议",
    need_context: "需补充条件",
    not_applicable: "不适用",
    rules_pending: "规则待接入",
    unmapped: "未映射",
    human_confirmed: "人工确认",
  };
  return labels[status] || "待确认";
}

function standardizationChatStatusLabel(status) {
  const labels = {
    answered: "已解释",
    need_context: "需补充条件",
    need_clarification: "需追问",
    proposal_ready: "已形成修改建议",
    manual_apply_required: "需手动应用",
  };
  return labels[status] || status || "待确认";
}

function standardizationChatIntentLabel(type) {
  const labels = {
    explanation: "依据解释",
    parameter_change_request: "参数修改",
    multi_constraint_change_request: "多约束修改",
    full_standardization_plan: "完整标准化方案",
    confirmation: "确认应用",
    unknown: "待澄清",
  };
  return labels[type] || type || "待识别";
}

function standardSelectionStatusLabel(status) {
  const labels = {
    not_started: "待标准化",
    applicable: "可适用",
    need_review: "需人工确认",
    not_applicable: "不适用",
    rules_pending: "规则待接入",
  };
  return labels[status] || "待确认";
}

function selectionSourceLabel(source) {
  const labels = {
    not_started: "等待标准化",
    drawing_standard_no: "图纸标准号",
    wire_diameter_threshold: "线径阈值",
    recognized_feature: "识别特征",
    llm_inference: "LLM判断",
    insufficient_context: "信息不足",
    spring_type: "弹簧类型",
  };
  return labels[source] || source || "";
}

function featureValueLabel(field, value) {
  const text = String(value ?? "unknown");
  const labels = {
    spring_family: {
      helical: "螺旋",
      disc: "碟形",
      wave: "波形",
      rubber: "橡胶",
      gas: "气弹簧",
      unknown: "未知",
    },
    spring_shape: {
      cylindrical: "圆柱",
      conical: "圆锥",
      barrel: "鼓形",
      hourglass: "腰鼓",
      unknown: "未知",
    },
    manufacturing_method: {
      cold_coiled: "冷卷",
      hot_coiled: "热卷",
      unknown: "未知",
    },
    wire_section: {
      round: "圆截面",
      rectangular: "矩形截面",
      square: "方形截面",
      unknown: "未知",
    },
    pitch_type: {
      constant: "等节距",
      variable: "变节距",
      unknown: "未知",
    },
  };
  return labels[field]?.[text] || text;
}

function canConfirmStandardization(item) {
  if (item?.metadata?.target_field_valid === false) return false;
  if (item?.metadata?.target_field_error) return false;
  return item?.status === "suggested" || item?.status === "llm_suggested" || item?.target_field === "standard_no";
}

function targetFieldLabel(targetField) {
  const text = String(targetField || "");
  const loadMatch = text.match(/^load_points\.([^.]+)\.force$/);
  if (loadMatch) return `载荷点 ${loadMatch[1]}`;
  return FIELD_LABELS[text] || text;
}

function formatStandardValue(value, unit = "") {
  if (value == null || value === "") return "-";
  return `${value}${unit || ""}`;
}

function formatStandardizationSuggestion(item) {
  const value = formatStandardValue(item.suggested_value, item.unit);
  const upper = item.suggested_tolerance_upper;
  const lower = item.suggested_tolerance_lower;
  if (upper == null && lower == null) return value;
  if (Number(upper) === Math.abs(Number(lower))) {
    return `${value} ±${formatCompactNumber(Math.abs(Number(upper)))}`;
  }
  return `${value} ${upper ?? ""}/${lower ?? ""}`;
}

function formatCompactNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "");
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(4)));
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

  root.querySelectorAll('[data-kind="standardization"]').forEach((row) => {
    const item = review.standardization_results[Number(row.dataset.index)];
    row.querySelector('[data-role="confirm-standard"]')?.addEventListener("click", () => {
      activateReviewContext(messageId);
      applyStandardizationResult(item);
      updateLatestReviewMessage("已确认标准化建议，请继续核对导出数据。");
    });
  });

  root.querySelector('[data-action="confirm-standard-selection"]')?.addEventListener("click", () => {
    activateReviewContext(messageId);
    confirmStandardSelection();
    updateLatestReviewMessage("已确认标准选择判断，请继续核对尺寸和标准化建议。");
  });

  root.querySelectorAll('[data-action="standardization-chat"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      activateReviewContext(messageId);
      const input = form.querySelector('[data-role="standardization-chat-input"]');
      const text = input?.value?.trim() || "";
      if (!text) return;
      input.value = "";
      runStandardizationChat(text, messageId, true);
    });
  });

  root.querySelectorAll('[data-kind="chat_action"]').forEach((row) => {
    row.querySelector('[data-role="apply-chat-action"]')?.addEventListener("click", async () => {
      if (state.busy) return;
      activateReviewContext(messageId);
      const turn = review.standardization_chat?.[Number(row.dataset.turnIndex)];
      const action = turn?.suggested_actions?.[Number(row.dataset.actionIndex)];
      const applied = applyStandardizationChatActions([action], turn, { batch: false });
      if (!applied.ok) {
        updateLatestReviewMessage(applied.message || "暂时无法应用这条标准化对话建议。");
        return;
      }
      updateLatestReviewMessage("已应用对话修改建议，正在重新标准化...");
      const standardized = await runStandardization(messageId);
      markStandardizationChatActionLogRestandardized(applied.log_id, standardized);
    });
  });

  root.querySelectorAll('[data-kind="chat_action_batch"]').forEach((row) => {
    row.querySelector('[data-role="apply-chat-turn-actions"]')?.addEventListener("click", async () => {
      if (state.busy) return;
      activateReviewContext(messageId);
      const turn = review.standardization_chat?.[Number(row.dataset.turnIndex)];
      const validation = validateStandardizationChatBatch(turn);
      if (!validation.ok) {
        updateLatestReviewMessage(validation.message || "本轮建议暂时不能批量应用。");
        return;
      }
      const applied = applyStandardizationChatActions(validation.candidates, turn, { batch: true });
      if (!applied.ok) {
        updateLatestReviewMessage(applied.message || "本轮建议暂时不能批量应用。");
        return;
      }
      updateLatestReviewMessage(`已应用 ${applied.patches.length} 条对话修改建议，正在重新标准化...`);
      const standardized = await runStandardization(messageId);
      markStandardizationChatActionLogRestandardized(applied.log_id, standardized);
    });
  });

  root.querySelectorAll('[data-kind="technical"]').forEach((row) => {
    const item = review.technical_requirements[Number(row.dataset.index)];
    const contentInput = row.querySelector('[data-role="content"]');
    contentInput.addEventListener("change", (event) => {
      activateReviewContext(messageId);
      item.content = event.target.value.trim();
      if (item.type === "surface") {
        item.raw_content ||= item.evidence || item.content;
        item.standard_content = item.content;
        item.normalization_status = "human_confirmed";
        item.normalization_source = "human";
        item.normalization_confidence = 1;
        item.normalization_reason = "人工修改标准术语";
      }
      confirmParam(item, `technical_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="standard-candidate"]')?.addEventListener("change", (event) => {
      const value = event.target.value.trim();
      if (!value) return;
      activateReviewContext(messageId);
      item.raw_content ||= item.evidence || item.content;
      item.content = value;
      item.standard_content = value;
      item.normalization_status = "human_confirmed";
      item.normalization_source = "human";
      item.normalization_confidence = 1;
      item.normalization_reason = "人工选择候选标准术语";
      contentInput.value = value;
      confirmParam(item, `technical_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      activateReviewContext(messageId);
      if (item.type === "surface" && item.content) {
        item.standard_content ||= item.content;
        item.raw_content ||= item.evidence || item.content;
        item.normalization_status = "human_confirmed";
        item.normalization_source = "human";
        item.normalization_confidence = 1;
        item.normalization_reason = "人工确认当前表面处理术语";
      }
      confirmParam(item, `technical_${row.dataset.index}`);
      updateLatestReviewMessage();
    });
  });
}

function applyStandardizationResult(item) {
  if (!item) return;
  if (item.metadata?.target_field_valid === false) return;
  if (item.metadata?.target_field_error) return;
  state.review.standardization_results ||= [];
  state.review.spring_parameters ||= {};
  const target = String(item.target_field || "");
  const loadMatch = target.match(/^load_points\.([^.]+)\.force$/);
  if (loadMatch) {
    const label = loadMatch[1];
    const point = (state.review.spring_parameters.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    if (point) {
      point.load_tolerance_upper = item.suggested_tolerance_upper;
      point.load_tolerance_lower = item.suggested_tolerance_lower;
      if (point.force && item.suggested_tolerance_upper != null) {
        point.load_tolerance_percent = Number(((Number(item.suggested_tolerance_upper) / Number(point.force)) * 100).toFixed(3));
      }
      confirmParam(point, `standardization_${target}`);
    }
  } else if (target) {
    const meta = getFieldMeta(target, state.review);
    const param = state.review.spring_parameters[target] || blankParam(meta.unit);
    if (item.suggested_value != null) {
      param.value = item.suggested_value;
    }
    if (item.suggested_tolerance_upper != null || item.suggested_tolerance_lower != null) {
      param.tolerance_upper = item.suggested_tolerance_upper;
      param.tolerance_lower = item.suggested_tolerance_lower;
    }
    if (!param.unit && item.unit) {
      param.unit = item.unit;
    }
    state.review.spring_parameters[target] = param;
    confirmParam(param, `standardization_${target}`);
    syncBubbleValue(target, param.value);
  }
  item.status = "human_confirmed";
  item.need_human_review = false;
  state.review.manual_confirmations[`standardization_${target}`] = {
    confirmed: true,
    value: item.suggested_value ?? null,
    confirmed_at: new Date().toISOString(),
    rule_id: item.rule_id,
  };
}

function standardizationChatConstraints(turn) {
  const constraints = Array.isArray(turn?.intent?.constraints) ? turn.intent.constraints : [];
  return constraints.map((item) => String(item || "").trim()).filter(Boolean);
}

function standardizationChatPatchCandidates(turn) {
  const actions = Array.isArray(turn?.suggested_actions) ? turn.suggested_actions : [];
  return actions.filter((action) => isApplicableStandardizationChatActionType(action?.type) && action.status !== "applied");
}

function validateStandardizationChatBatch(turn) {
  const candidates = standardizationChatPatchCandidates(turn);
  const invalid = candidates.filter((action) => !canApplyStandardizationChatAction(action));
  const duplicateTargets = duplicateStandardizationChatTargets(candidates);
  if (candidates.length < 2) {
    return {
      ok: false,
      candidates,
      message: candidates.length ? "本轮只有一条待应用建议，请逐条应用。" : "本轮没有可应用的修改建议。",
    };
  }
  if (invalid.length) {
    return {
      ok: false,
      candidates,
      message: "本轮存在缺少目标字段、建议值或载荷点的建议，需要逐条处理。",
    };
  }
  if (duplicateTargets.length) {
    return {
      ok: false,
      candidates,
      message: `同一字段存在多条同类建议：${duplicateTargets.join("、")}，请逐条确认。`,
    };
  }
  return {
    ok: true,
    candidates,
    message: `可一次写回 ${candidates.length} 条建议，写回后会重新标准化。`,
  };
}

function duplicateStandardizationChatTargets(actions) {
  const counts = new Map();
  const labels = new Map();
  for (const action of actions) {
    const target = String(action?.target_field || "");
    if (!target) continue;
    const key = `${action?.type || "unknown"}:${target}`;
    counts.set(key, (counts.get(key) || 0) + 1);
    labels.set(key, `${targetFieldLabel(target)} / ${standardizationChatActionTypeLabel(action?.type)}`);
  }
  return Array.from(counts.entries())
    .filter(([, count]) => count > 1)
    .map(([key]) => labels.get(key) || key);
}

function canApplyStandardizationChatAction(action) {
  if (!action || action.status === "applied") return false;
  if (!isApplicableStandardizationChatActionType(action.type)) return false;
  if (action.metadata?.action_type_valid === false) return false;
  if (action.metadata?.target_field_valid === false) return false;
  if (!action.target_field) return false;
  if (!standardizationChatTargetExists(action.target_field)) return false;
  return hasStandardizationChatActionValue(action);
}

function isApplicableStandardizationChatActionType(type) {
  return type === "propose_parameter_patch" || type === "propose_tolerance_patch";
}

function standardizationChatActionTypeLabel(type) {
  const labels = {
    propose_parameter_patch: "参数",
    propose_tolerance_patch: "公差",
  };
  return labels[type] || "建议";
}

function hasStandardizationChatActionValue(action) {
  if (!action) return false;
  if (action.type === "propose_tolerance_patch") {
    return action.suggested_tolerance_upper !== undefined
      || action.suggested_tolerance_lower !== undefined
      || action.tolerance_upper !== undefined
      || action.tolerance_lower !== undefined;
  }
  return action.proposed_value !== undefined && action.proposed_value !== null && action.proposed_value !== "";
}

function formatStandardizationChatActionValue(action) {
  if (action?.type === "propose_tolerance_patch") {
    return formatTolerancePair(normalizeActionTolerance(action, {}), action.unit || "");
  }
  return formatStandardValue(action?.proposed_value, action?.unit || "");
}

function formatTolerancePair(tolerance, unit = "") {
  const upper = tolerance?.upper;
  const lower = tolerance?.lower;
  if (upper == null && lower == null) return "-";
  const suffix = unit || "";
  if (upper != null && lower != null && Number(upper) === Math.abs(Number(lower))) {
    return `±${formatCompactNumber(Math.abs(Number(upper)))}${suffix}`;
  }
  const upperText = upper == null ? "" : `+${formatCompactNumber(upper)}${suffix}`;
  const lowerText = lower == null ? "" : `${formatCompactNumber(lower)}${suffix}`;
  return `${upperText}/${lowerText}`;
}

function standardizationChatTargetExists(target) {
  const loadMatch = String(target || "").match(/^load_points\.([^.]+)\.force$/);
  if (!loadMatch) return true;
  const label = loadMatch[1];
  return (state.review?.spring_parameters?.load_points || []).some((candidate) => {
    return String(candidate.label || "") === label;
  });
}

function applyStandardizationChatActions(actions, turn, options = {}) {
  const list = (Array.isArray(actions) ? actions : [actions]).filter(Boolean);
  if (!list.length) {
    return { ok: false, message: "没有可应用的标准化对话建议。" };
  }
  const invalid = list.filter((action) => !canApplyStandardizationChatAction(action));
  if (invalid.length) {
    return { ok: false, message: "存在缺少目标字段、建议值或载荷点的建议，暂时无法应用。" };
  }
  const duplicateTargets = duplicateStandardizationChatTargets(list);
  if (duplicateTargets.length) {
    return {
      ok: false,
      message: `同一字段存在多条同类建议：${duplicateTargets.join("、")}，请逐条确认。`,
    };
  }

  const now = new Date().toISOString();
  const patches = [];
  for (const action of list) {
    const applied = applyStandardizationChatAction(action, turn, { now });
    if (!applied.ok) {
      return applied;
    }
    patches.push(applied.patch);
  }

  const logId = recordStandardizationChatActionLog({
    turn,
    patches,
    batch: Boolean(options.batch) || patches.length > 1,
    appliedAt: now,
  });
  return { ok: true, patches, log_id: logId };
}

function applyStandardizationChatAction(action, turn, options = {}) {
  if (!canApplyStandardizationChatAction(action)) {
    return { ok: false, message: "这条建议缺少可应用的目标字段或建议值。" };
  }
  if (action.type === "propose_tolerance_patch") {
    return applyStandardizationChatToleranceAction(action, turn, options);
  }
  state.review.spring_parameters ||= {};
  state.review.manual_confirmations ||= {};
  const target = String(action.target_field || "");
  const previous = currentActionTargetValue(target);
  const value = normalizeActionValue(action.proposed_value, previous);
  const now = options.now || new Date().toISOString();
  let unit = action.unit || "";

  const loadMatch = target.match(/^load_points\.([^.]+)\.force$/);
  if (loadMatch) {
    const label = loadMatch[1];
    const point = (state.review.spring_parameters.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    if (!point) {
      action.apply_error = `未找到载荷点 ${label}`;
      return { ok: false, message: `未找到载荷点 ${label}，请先在载荷点表中补充。` };
    }
    unit = unit || point.force_unit || "";
    point.force = value;
    if (unit) point.force_unit = unit;
    point.need_human_review = false;
    point.confidence = Math.max(Number(point.confidence) || 0, 0.99);
    point.source = Array.from(new Set(["standardization_chat", "human_confirmed", ...(point.source || [])]));
    state.review.manual_confirmations[`standardization_chat_${target}`] = {
      confirmed: true,
      value,
      previous_value: previous ?? null,
      confirmed_at: now,
      user_message: turn?.user || "",
      action_type: action.type,
    };
  } else {
    const meta = getFieldMeta(target, state.review);
    const param = state.review.spring_parameters[target] || blankParam(meta.unit);
    unit = unit || param.unit || meta.unit || "";
    param.value = value;
    param.unit = unit || null;
    param.need_human_review = false;
    param.confidence = Math.max(Number(param.confidence) || 0, 0.99);
    param.source = Array.from(new Set(["standardization_chat", "human_confirmed", ...(param.source || [])]));
    param.evidence = action.reason || turn?.user || param.evidence || "标准化对话应用建议";
    state.review.spring_parameters[target] = param;
    syncBubbleValue(target, value);
    state.review.manual_confirmations[`standardization_chat_${target}`] = {
      confirmed: true,
      value,
      previous_value: previous ?? null,
      confirmed_at: now,
      user_message: turn?.user || "",
      action_type: action.type,
    };
  }

  action.status = "applied";
  action.applied_at = now;
  action.applied_value = value;
  action.previous_value = previous ?? null;
  action.apply_policy = "manual_confirmed";
  return {
    ok: true,
    patch: {
      target_field: target,
      target_label: action.target_label || targetFieldLabel(target),
      previous_value: previous ?? null,
      proposed_value: value,
      unit: unit || null,
      action_type: action.type,
      reason: action.reason || "",
      affected_fields: Array.isArray(action.affected_fields) ? action.affected_fields : [],
    },
  };
}

function applyStandardizationChatToleranceAction(action, turn, options = {}) {
  state.review.spring_parameters ||= {};
  state.review.manual_confirmations ||= {};
  const target = String(action.target_field || "");
  const previous = currentActionTargetTolerance(target);
  const tolerance = normalizeActionTolerance(action, previous);
  const now = options.now || new Date().toISOString();
  const unit = action.unit || "";

  const loadMatch = target.match(/^load_points\.([^.]+)\.force$/);
  if (loadMatch) {
    const label = loadMatch[1];
    const point = (state.review.spring_parameters.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    if (!point) {
      action.apply_error = `未找到载荷点 ${label}`;
      return { ok: false, message: `未找到载荷点 ${label}，请先在载荷点表中补充。` };
    }
    point.load_tolerance_upper = tolerance.upper;
    point.load_tolerance_lower = tolerance.lower;
    point.need_human_review = false;
    point.confidence = Math.max(Number(point.confidence) || 0, 0.99);
    point.source = Array.from(new Set(["standardization_chat", "human_confirmed", ...(point.source || [])]));
  } else {
    const meta = getFieldMeta(target, state.review);
    const param = state.review.spring_parameters[target] || blankParam(meta.unit);
    param.tolerance_upper = tolerance.upper;
    param.tolerance_lower = tolerance.lower;
    if (!param.unit && unit) param.unit = unit;
    param.need_human_review = false;
    param.confidence = Math.max(Number(param.confidence) || 0, 0.99);
    param.source = Array.from(new Set(["standardization_chat", "human_confirmed", ...(param.source || [])]));
    param.evidence = action.reason || turn?.user || param.evidence || "标准化对话应用公差建议";
    state.review.spring_parameters[target] = param;
  }

  state.review.manual_confirmations[`standardization_chat_${target}_tolerance`] = {
    confirmed: true,
    previous_tolerance: previous,
    tolerance,
    confirmed_at: now,
    user_message: turn?.user || "",
    action_type: action.type,
  };

  action.status = "applied";
  action.applied_at = now;
  action.previous_tolerance = previous;
  action.applied_tolerance = tolerance;
  action.apply_policy = "manual_confirmed";
  return {
    ok: true,
    patch: {
      target_field: target,
      target_label: action.target_label || targetFieldLabel(target),
      previous_tolerance_upper: previous.upper ?? null,
      previous_tolerance_lower: previous.lower ?? null,
      suggested_tolerance_upper: tolerance.upper ?? null,
      suggested_tolerance_lower: tolerance.lower ?? null,
      unit: unit || null,
      action_type: action.type,
      reason: action.reason || "",
      affected_fields: Array.isArray(action.affected_fields) ? action.affected_fields : [],
    },
  };
}

function recordStandardizationChatActionLog({ turn, patches, batch, appliedAt }) {
  state.review.agent_actions ||= [];
  const logId = `standardization_chat_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  state.review.agent_actions.push({
    id: logId,
    source: "standardization_chat",
    action_type: batch ? "batch_apply_standardization_patches" : (patches[0]?.action_type || "apply_standardization_patch"),
    user_message: turn?.user || "",
    assistant_message: turn?.assistant || "",
    constraints: standardizationChatConstraints(turn),
    applied_at: appliedAt || new Date().toISOString(),
    applied_patches: patches,
    restandardized: false,
    restandardization_status: "pending",
  });
  return logId;
}

function markStandardizationChatActionLogRestandardized(logId, completed) {
  if (!logId || !state.review) return;
  const log = (state.review.agent_actions || []).find((item) => item.id === logId);
  if (log) {
    log.restandardized = Boolean(completed);
    log.restandardization_status = completed ? "completed" : "failed";
    log.restandardized_at = new Date().toISOString();
  }
  const context = getReviewContext(state.activeReviewMessageId);
  if (context) {
    context.review = state.review;
    context.imageUrl = state.imageUrl;
  }
}

function currentActionTargetValue(target) {
  const loadMatch = String(target || "").match(/^load_points\.([^.]+)\.force$/);
  if (loadMatch) {
    const label = loadMatch[1];
    const point = (state.review.spring_parameters?.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    return point?.force;
  }
  const param = state.review.spring_parameters?.[target];
  return param && typeof param === "object" ? param.value : undefined;
}

function currentActionTargetTolerance(target) {
  const loadMatch = String(target || "").match(/^load_points\.([^.]+)\.force$/);
  if (loadMatch) {
    const label = loadMatch[1];
    const point = (state.review.spring_parameters?.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    return {
      upper: point?.load_tolerance_upper ?? null,
      lower: point?.load_tolerance_lower ?? null,
    };
  }
  const param = state.review.spring_parameters?.[target];
  return {
    upper: param && typeof param === "object" ? (param.tolerance_upper ?? null) : null,
    lower: param && typeof param === "object" ? (param.tolerance_lower ?? null) : null,
  };
}

function normalizeActionValue(value, previous) {
  if (typeof value === "number") return value;
  if (typeof value === "string") return parseValue(value, previous);
  return value;
}

function normalizeActionTolerance(action, previous = {}) {
  const upper = action.suggested_tolerance_upper ?? action.tolerance_upper ?? previous.upper ?? null;
  const lower = action.suggested_tolerance_lower ?? action.tolerance_lower ?? previous.lower ?? null;
  return {
    upper: typeof upper === "string" ? parseValue(upper, previous.upper) : upper,
    lower: typeof lower === "string" ? parseValue(lower, previous.lower) : lower,
  };
}

function confirmStandardSelection() {
  const selection = state.review.standard_selection;
  if (!selection) return;
  selection.need_human_review = false;
  selection.human_confirmed = true;
  selection.confirmed_at = new Date().toISOString();
  state.review.manual_confirmations.standard_selection = {
    confirmed: true,
    value: selection.selected_standard || null,
    confirmed_at: selection.confirmed_at,
  };
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
  const activeTab = validCompareTab(state.compareTab);
  compareOverlay.innerHTML = `
    <div class="compare-shell">
      <header class="compare-head">
        <div>
          <h2>图纸核对</h2>
          <p>左侧查看原图，右侧确认参数、标准化建议和 AI 对话。</p>
        </div>
        <div class="compare-actions">
          <button type="button" data-action="standardize">${standardizeButtonLabel(state.review)}</button>
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
        ${renderCompareDataPanelHtml(state.review, activeTab)}
      </div>
    </div>
  `;
  compareOverlay.querySelector('[data-action="close"]').addEventListener("click", closeCompareOverlay);
  compareOverlay.querySelector('[data-action="export"]').addEventListener("click", () => {
    downloadJson(makeExportReview(), "spring_review_confirmed.json");
  });
  compareOverlay.querySelector('[data-action="standardize"]').addEventListener("click", () => {
    runStandardization();
  });
  compareOverlay.querySelector('[data-action="confirm-all"]').addEventListener("click", () => {
    confirmAllFields();
    acknowledgeScannedInput();
    updateLatestReviewMessage("已全部确认，当前审查状态已刷新。");
  });
  bindCompareTabs(compareOverlay);
  bindReviewEditors(compareOverlay);
  initializeCompareViewer();
}

function renderCompareDataPanelHtml(review, activeTab) {
  const panels = {
    parameters: `
      ${renderTypeSelectorHtml(review)}
      ${renderSummaryHtml(review)}
      ${renderParameterTableHtml(review)}
      ${renderRequirementsHtml(review)}
    `,
    standards: `
      ${renderStandardSelectionHtml(review)}
      ${renderStandardizationHtml(review)}
      ${renderDerivedParametersHtml(review)}
    `,
    assistant: `
      ${renderStandardizationChatHtml(review)}
    `,
  };
  return `
    <section class="compare-data-panel">
      <div class="compare-data-top">
        <div>
          <strong>${escapeHtml(compareTabTitle(activeTab))}</strong>
          <small>${escapeHtml(compareTabDescription(activeTab))}</small>
        </div>
        ${renderCompareTabsHtml(activeTab)}
      </div>
      <div class="compare-tab-panels">
        ${Object.entries(panels).map(([tab, html]) => `
          <div class="compare-tab-panel${tab === activeTab ? " active" : ""}" data-compare-panel="${escapeHtml(tab)}">
            ${html}
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderCompareTabsHtml(activeTab) {
  const tabs = [
    ["parameters", "参数"],
    ["standards", "标准化"],
    ["assistant", "AI 对话"],
  ];
  return `
    <nav class="compare-tabs" aria-label="右侧数据视图">
      ${tabs.map(([tab, label]) => `
        <button type="button" class="${tab === activeTab ? "active" : ""}" data-compare-tab="${escapeHtml(tab)}">${escapeHtml(label)}</button>
      `).join("")}
    </nav>
  `;
}

function bindCompareTabs(root) {
  root.querySelectorAll("[data-compare-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = validCompareTab(button.dataset.compareTab);
      state.compareTab = tab;
      root.querySelectorAll("[data-compare-tab]").forEach((item) => {
        item.classList.toggle("active", item.dataset.compareTab === tab);
      });
      root.querySelector(".compare-data-top strong").textContent = compareTabTitle(tab);
      root.querySelector(".compare-data-top small").textContent = compareTabDescription(tab);
      root.querySelectorAll("[data-compare-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.comparePanel === tab);
      });
    });
  });
}

function validCompareTab(tab) {
  return ["parameters", "standards", "assistant"].includes(tab) ? tab : "parameters";
}

function compareTabTitle(tab) {
  const titles = {
    parameters: "参数确认",
    standards: "标准化",
    assistant: "AI 对话",
  };
  return titles[tab] || titles.parameters;
}

function compareTabDescription(tab) {
  const descriptions = {
    parameters: "核对识别尺寸和技术要求",
    standards: "查看标准选择、建议和派生参数",
    assistant: "按当前图纸上下文提问或应用建议",
  };
  return descriptions[tab] || descriptions.parameters;
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
  return `审查完成：${businessCount} 个结构化候选，来源 ${sources}。${warnings}`;
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
  cloned.drawing_summary.spring_type = normalizeSpringTypeValue(cloned.drawing_summary.spring_type || "compression_spring");
  cloned.spring_template ||= getLocalTemplate(cloned.drawing_summary.spring_type);
  cloned.spring_parameters ||= {};
  cloned.spring_parameters.load_points ||= [];
  cloned.spring_features ||= {};
  cloned.standard_selection ||= {
    selected_standard: null,
    candidate_standards: [],
    status: "need_review",
    confidence: 0,
    selection_source: "missing",
    reason: "",
    evidence: [],
    need_human_review: false,
    references: [],
  };
  cloned.derived_parameters ||= {};
  cloned.standardization_results ||= [];
  cloned.standardization_chat ||= [];
  cloned.agent_actions ||= [];
  cloned.technical_requirements ||= [];
  cloned.review_results ||= [];
  cloned.balloons ||= [];
  cloned.manual_confirmations ||= {};
  return cloned;
}

function currentSpringType(review) {
  const candidates = [
    review?.drawing_summary?.spring_type,
    review?.spring_template?.spring_type,
    review?.spring_type_detection?.spring_type,
    review?.spring_template?.label,
    review?.drawing_summary?.spring_type_label,
  ];
  for (const candidate of candidates) {
    const normalized = normalizeSpringTypeValue(candidate);
    if (normalized && normalized !== "unknown_spring") return normalized;
  }
  return "unknown_spring";
}

function normalizeSpringTypeValue(value) {
  const raw = String(value || "").trim();
  if (!raw) return "unknown_spring";
  if (LOCAL_SPRING_TEMPLATES[raw]) return raw;
  const labelMatch = Object.entries(SPRING_TYPE_LABELS).find(([, label]) => label === raw);
  if (labelMatch) return labelMatch[0];
  if (raw.includes("压缩")) return "compression_spring";
  if (raw.includes("拉伸")) return "extension_spring";
  if (raw.includes("扭转")) return "torsion_spring";
  return raw;
}

function getLocalTemplate(type) {
  return structuredClone(LOCAL_SPRING_TEMPLATES[type] || LOCAL_SPRING_TEMPLATES.unknown_spring);
}

function getSpringTemplate(review) {
  const currentType = currentSpringType(review);
  const backendTemplate = review?.spring_template;
  if (normalizeSpringTypeValue(backendTemplate?.spring_type) === currentType && Array.isArray(backendTemplate.fields)) {
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
  const standardizationNeedsReview = (review.standardization_results || []).some((item) => item.need_human_review);
  const standardSelectionNeedsReview = Boolean(review.standard_selection?.need_human_review);
  return fieldNeedsReview || techNeedsReview || standardizationNeedsReview || standardSelectionNeedsReview;
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
  (state.review.standardization_results || []).forEach((item) => {
    if (canConfirmStandardization(item)) {
      applyStandardizationResult(item);
    }
  });
  if (state.review.standard_selection?.need_human_review) {
    confirmStandardSelection();
  }
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
    window.scrollTo(0, 0);
    conversation.scrollTop = conversation.scrollHeight;
  });
}

function scrollMessageIntoView(message) {
  requestAnimationFrame(() => {
    window.scrollTo(0, 0);
    const top = Math.max(0, message.offsetTop - conversation.offsetTop - 12);
    conversation.scrollTo({ top, behavior: "smooth" });
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
