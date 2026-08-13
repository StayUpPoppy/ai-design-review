const state = {
  apiBaseUrl: normalizeBaseUrl(
    new URLSearchParams(window.location.search).get("api")
      || localStorage.getItem("aiDesignReviewApiBaseUrl")
      || defaultApiBaseUrl(),
  ),
  selectedFile: null,
  imageUrl: null,
  review: null,
  selectedBubbleId: null,
  lastJob: null,
  activeReviewMessageId: null,
  reviewContexts: {},
  compareOpen: false,
  compareTab: "workbench",
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
  automaticStandardizationTimer: null,
  accuracyGradeUpdate: {
    phase: "idle",
    grade: "",
    operation: "",
    timer: null,
  },
  pendingAccuracyGrade: "",
  reasonablenessRefreshTimer: null,
  reasonablenessRequestSerial: 0,
  reviewPersistenceTimer: null,
  reviewPersistenceSaving: false,
  reviewPersistencePromise: null,
  pendingReviewAuditEvents: [],
  recentReviews: [],
  recentReviewsLoading: false,
  recognitionPollers: {},
  recognitionMessageIds: {},
  generationReadiness: null,
  generationJobs: [],
  generationQueueAvailable: null,
  generationPollers: {},
  generationBusy: false,
  generationCompare: null,
  identity: null,
  identityReady: false,
  identityError: "",
};

window.addEventListener("beforeunload", (event) => {
  if (!hasPendingEditedReviewItems(state.review)) return;
  event.preventDefault();
  event.returnValue = "";
});

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
  support_coils: "支承圈数（单端）",
  handedness: "旋向",
  pitch: "节距",
  end_type: "端部形式",
  end_grinding: "端面磨削",
  end_coils_closed: "端圈压并",
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
  "active_coils",
  "solid_height",
  "handedness",
  "end_type",
  "end_grinding",
]);

const COMPRESSION_GENERATION_CORE_FIELDS = [
  "wire_diameter",
  "mean_diameter",
  "free_length",
  "total_coils",
  "active_coils",
  "handedness",
  "end_grinding",
  "end_coils_closed",
];

const COMPRESSION_GENERATION_DEFAULTS = {
  wire_diameter: 3,
  mean_diameter: 23,
  free_length: 45,
  total_coils: 10,
  active_coils: 8,
  end_grinding: 1,
  end_coils_closed: 1,
};

const COMPRESSION_GENERATION_UNITS = {
  wire_diameter: "mm",
  mean_diameter: "mm",
  free_length: "mm",
  total_coils: null,
  active_coils: null,
  handedness: null,
  end_grinding: null,
  end_coils_closed: null,
};

const COMPRESSION_GENERATION_LABELS = {
  wire_diameter: "线径",
  mean_diameter: "中径",
  free_length: "自由长度",
  total_coils: "总圈数",
  active_coils: "有效圈数",
  handedness: "旋向",
  end_grinding: "两端磨削",
  end_coils_closed: "端圈压并",
};

const SPECIALIZED_ACCURACY_PARAMETER_FIELDS = new Set([
  "diameter_accuracy_grade",
  "free_length_accuracy_grade",
  "load_accuracy_grade",
  "stiffness_accuracy_grade",
]);

const COMPRESSION_ACCURACY_GRADE_OPTIONS = ["1级", "2级", "3级"];
const COMPRESSION_END_GRINDING_OPTIONS = ["两端磨削", "两端不磨削"];
const COMPRESSION_END_TYPE_OPTIONS = ["两端并紧", "两端不并紧"];

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
      { key: "support_coils", label: "支承圈数（单端）", unit: "turns" },
      { key: "handedness", label: "旋向", required: true },
      { key: "pitch", label: "节距", unit: "mm" },
      { key: "end_type", label: "端部形式" },
      { key: "end_grinding", label: "端面磨削" },
      { key: "spring_rate", label: "刚度", unit: "N/mm" },
      { key: "perpendicularity", label: "垂直度", unit: "mm" },
      { key: "straightness", label: "直线度", unit: "mm" },
      { key: "permanent_set_limit", label: "永久变形限值", unit: "mm" },
    ],
    collections: [{ key: "load_points", label: "载荷测试点" }],
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
    collections: [{ key: "load_points", label: "载荷测试点" }],
  },
};

const conversation = document.getElementById("conversation");
const apiBaseInput = document.getElementById("apiBaseInput");
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
const newReviewButton = document.getElementById("newReviewButton");
const recentReviews = document.getElementById("recentReviews");
const recentReviewList = document.getElementById("recentReviewList");
const refreshRecentReviewsButton = document.getElementById("refreshRecentReviewsButton");
const identityProfile = document.getElementById("identityProfile");
const identityProfileName = document.getElementById("identityProfileName");
const identityProfileOrg = document.getElementById("identityProfileOrg");
const identityProfileSource = document.getElementById("identityProfileSource");
const compareOverlay = createCompareOverlay();

apiBaseInput.value = state.apiBaseUrl;

apiBaseInput.addEventListener("change", () => {
  state.apiBaseUrl = normalizeBaseUrl(apiBaseInput.value || state.apiBaseUrl);
  apiBaseInput.value = state.apiBaseUrl;
  localStorage.setItem("aiDesignReviewApiBaseUrl", state.apiBaseUrl);
});

chooseFileButton.addEventListener("click", () => drawingInput.click());
loadReviewJsonButton.addEventListener("click", () => reviewJsonInput.click());
submitButton.addEventListener("click", () => submitSelectedFile());
newReviewButton?.addEventListener("click", () => {
  void startNewReview();
});
useOcrInput.addEventListener("change", syncOcrProviderState);
useVlmInput?.addEventListener("change", syncVlmProviderState);
demoButton.addEventListener("click", loadDemoReview);
refreshRecentReviewsButton?.addEventListener("click", () => {
  void loadRecentReviews();
});
exportButton.addEventListener("click", () => {
  if (!state.review) return;
  downloadJson(makeExportReview(), "spring_review_confirmed.json");
});

syncOcrProviderState();
syncVlmProviderState();
void initializeIdentity();

async function initializeIdentity() {
  state.identityReady = false;
  state.identityError = "";
  refreshIdentityUi();
  setBusy(state.busy);
  try {
    const response = await apiFetch("/api/session");
    const payload = await response.json();
    if (!response.ok || !payload?.identity) {
      throw new Error(payload?.detail || "无法读取 ERP 登录身份");
    }
    state.identity = payload.identity;
    state.identityReady = true;
    refreshIdentityUi();
    setBusy(false);
    void loadRecentReviews();
  } catch (error) {
    state.identity = null;
    state.identityReady = false;
    state.identityError = error.message || "请从 ERP 登录后进入审图助手";
    refreshIdentityUi();
    setBusy(false);
  }
}

function refreshIdentityUi() {
  const identity = state.identity;
  const showIdentity = Boolean(identity?.identity_display_enabled);
  if (identityProfile) identityProfile.hidden = !showIdentity;
  if (showIdentity) {
    identityProfileName.textContent = identity.username || "-";
    identityProfileOrg.textContent = identity.org_name || "-";
    identityProfileSource.textContent = identity.is_mock ? "开发模拟" : "ERP 已同步";
  }
  if (!state.identityReady && state.identityError) {
    selectedFileName.textContent = "请从 ERP 登录后进入审图助手";
  }
}

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
  state.lastJob = null;
  resetGenerationState();
  state.compareTab = "workbench";
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
  if (!state.identityReady) return;
  if (!isSupportedDrawing(file)) {
    appendAssistantText("当前仅支持 PDF 或常见图片格式。");
    return;
  }
  state.selectedFile = file;
  selectedFileName.textContent = file.name;
  submitButton.disabled = state.busy;
}

async function submitSelectedFile() {
  if (!state.selectedFile || state.busy || !state.identityReady) return;
  if (useWerk24Input?.checked && !confirmWerk24Input?.checked) {
    appendAssistantText("调用 Werk24 前必须勾选“确认上传到 Werk24”。");
    return;
  }

  advancedOptions.open = false;
  setBusy(true);
  appendUserMessage(`上传图纸：${state.selectedFile.name}`);
  const providerLabel = ocrProviderInput.selectedOptions[0]?.textContent || "OCR";
  const activeEngineLabel = useQwenInput?.checked
    ? "Qwen3.7 视觉识别（必要时自动坐标复核）"
    : providerLabel;
  const thinkingId = appendAssistantText(`正在上传图纸，识别引擎：${activeEngineLabel}...`);

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

    const response = await apiFetch("/api/reviews", { method: "POST", body: form });
    const payload = await readUploadResponsePayload(response);
    if (!response.ok) throw new Error(payload.detail || "后端审查失败");

    state.lastJob = payload;
    state.selectedFile = null;
    drawingInput.value = "";
    selectedFileName.textContent = "图纸已加入识别队列";
    state.recognitionMessageIds[payload.job_id] = thinkingId;
    replaceMessage(thinkingId, recognitionProgressText({
      status: payload.recognition_status,
      stage: payload.recognition_stage,
      progress: payload.recognition_progress,
      queue_position: payload.queue_position,
    }));
    trackRecognitionJob(payload.job_id, thinkingId);
    void loadRecentReviews();
  } catch (error) {
    replaceMessage(thinkingId, error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

async function runStandardization(messageId = state.activeReviewMessageId, options = {}) {
  if (!state.review || state.busy) return false;
  clearTimeout(state.automaticStandardizationTimer);
  state.automaticStandardizationTimer = null;
  const accuracyGradeUpdate = options.accuracy_grade_update;
  const requestedAccuracyGrade = normalizeAccuracyGrade(options.pending_accuracy_grade);
  const feedbackOperation = options.workbench_feedback
    ? (requestedAccuracyGrade ? "accuracy" : "manual")
    : accuracyGradeUpdate?.grade ? "accuracy" : "";
  const feedbackGrade = requestedAccuracyGrade
    || normalizeAccuracyGrade(accuracyGradeUpdate?.grade)
    || normalizeAccuracyGrade(state.review?.spring_parameters?.accuracy_grade?.value);
  activateReviewContext(messageId);
  if (feedbackOperation) {
    setAccuracyGradeUpdate("loading", feedbackGrade, feedbackOperation);
  }
  await flushReviewPersistence();
  const requestReview = normalizeReview(structuredClone(state.review));
  const accuracyGradeCommit = requestedAccuracyGrade
    ? prepareAccuracyGradeCommit(requestReview, requestedAccuracyGrade)
    : null;
  const scrollState = captureReviewScrollState();
  setBusy(true);
  const endpoint = state.lastJob?.job_id
    ? `/api/reviews/${encodeURIComponent(state.lastJob.job_id)}/standardize`
    : "/api/reviews/standardize";
  const thinkingId = options.silent
    ? null
    : appendAssistantText(
      "正在根据当前确认/修改后的参数进行标准化...",
      false,
      { scroll: false },
    );
  try {
    const response = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review: requestReview,
        // Manual plan generation always enables the RAG/LLM fallback when local rules are pending.
        // The backend still skips it whenever deterministic local results already exist.
        use_llm_standardization: true,
        expected_revision: state.lastJob?.review_revision ?? undefined,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "标准化失败");

    if (thinkingId) removeMessage(thinkingId);
    if (payload.job_id) {
      state.lastJob = { ...(state.lastJob || {}), ...payload };
    }
    setReview(normalizeReview(payload.review), state.imageUrl, {
      preserveAccuracyGradeUpdate: true,
      preservePendingAccuracyGrade: true,
    });
    state.generationReadiness = null;
    if (state.lastJob?.job_id && typeof loadGenerationState === "function") {
      void loadGenerationState(state.lastJob.job_id, { silent: true });
    }
    state.review.standardization_apply_history = [];
    state.review.derived_parameters_stale = false;
    state.review.parameter_reasonableness_stale = false;
    if (accuracyGradeCommit) {
      state.pendingAccuracyGrade = "";
      syncBubbleValue("accuracy_grade", accuracyGradeCommit.grade);
      queueReviewAuditEvent({
        event_type: "accuracy_grade_selected",
        target_field: "accuracy_grade",
        before_state: accuracyGradeCommit.beforeState,
        after_state: parameterAuditState(state.review.spring_parameters?.accuracy_grade),
        metadata: { selection_method: "standardization_regeneration" },
      });
    }
    const context = getReviewContext(messageId);
    if (context) {
      context.review = state.review;
      context.imageUrl = state.imageUrl;
    }
    const warnings = payload.warnings?.length ? ` 警告：${payload.warnings.join("；")}` : "";
    const llmSummary = payload.llm_standardization?.result_count
      ? `，其中 LLM/RAG ${payload.llm_standardization.result_count} 项`
      : "";
    const completionPrefix = options.automatic ? "已按最新修改自动更新标准化方案" : "标准化完成";
    if (feedbackOperation) {
      setAccuracyGradeUpdate("success", feedbackGrade, feedbackOperation);
    }
    updateLatestReviewMessage(`${completionPrefix}：生成 ${state.review.standardization_results.length} 项建议${llmSummary}。${warnings}`);
    return true;
  } catch (error) {
    if (feedbackOperation) {
      setAccuracyGradeUpdate("error", feedbackGrade, feedbackOperation);
    }
    if (thinkingId) replaceMessage(thinkingId, error.message || String(error), true);
    else appendAssistantText(`自动更新标准化方案失败：${error.message || String(error)}`, true, { scroll: false });
    return false;
  } finally {
    setBusy(false);
    restoreReviewScrollState(scrollState);
  }
}

async function runStandardizationChat(message, messageId = state.activeReviewMessageId, useLlm = true, options = {}) {
  const text = String(message || "").trim();
  if (!state.review || !text || state.standardizationChatBusy) return;
  activateReviewContext(messageId);
  await flushReviewPersistence();
  const requestReview = normalizeReview(structuredClone(state.review));
  markSubmittedMissingChatActions(requestReview, options.submittedMissingActions);
  const pendingTurnId = appendPendingStandardizationChatTurn(text, messageId);
  state.standardizationChatBusy = true;
  refreshReviewSurfaces({ scrollChat: true });
  const endpoint = state.lastJob?.job_id
    ? `/api/reviews/${encodeURIComponent(state.lastJob.job_id)}/standardization-chat`
    : "/api/reviews/standardization-chat";
  let isTypingFinalReply = false;
  try {
    const response = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review: requestReview,
        message: text,
        use_llm: Boolean(useLlm),
        supplements: options.supplements || undefined,
        active_proposal_id: options.activeProposalId
          || state.review?.active_parameter_change_proposal_id
          || undefined,
        expected_revision: state.lastJob?.review_revision ?? undefined,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "标准化对话失败");

    if (payload.job_id) {
      state.lastJob = {
        ...(state.lastJob || {}),
        job_id: payload.job_id,
        review_revision: payload.review_revision ?? state.lastJob?.review_revision ?? null,
      };
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
    state.generationReadiness = null;
    if (state.lastJob?.job_id && typeof loadGenerationState === "function") {
      void loadGenerationState(state.lastJob.job_id, { silent: true });
    }
    const context = getReviewContext(messageId);
    if (context) {
      context.review = state.review;
      context.imageUrl = state.imageUrl;
    }
    refreshReviewSurfaces({ scrollChat: true });
    isTypingFinalReply = true;
    animateStandardizationChatReply(finalTurnIndex, finalAssistantText, messageId);
    if (finalTurn?.generation_package_export?.automatic_download) {
      void executeGenerationPackageExport(
        finalTurn.generation_package_export,
        finalTurnIndex,
        messageId,
        { automatic: true },
      );
    }
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

async function submitParameterChangeProposal(proposal, command, messageId = state.activeReviewMessageId) {
  if (!proposal?.proposal_id || !state.lastJob?.job_id || state.busy) return false;
  activateReviewContext(messageId);
  await flushReviewPersistence();
  setBusy(true);
  try {
    const response = await apiFetch(
      `/api/reviews/${encodeURIComponent(state.lastJob.job_id)}/parameter-change-proposals/${encodeURIComponent(proposal.proposal_id)}/${command}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version: Number(proposal.version),
          expected_review_revision: state.lastJob.review_revision,
        }),
      },
    );
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload?.detail;
      throw new Error(detail?.message || (typeof detail === "string" ? detail : "参数修改方案操作失败。"));
    }
    state.lastJob = {
      ...(state.lastJob || {}),
      job_id: payload.job_id || state.lastJob.job_id,
      review_revision: payload.review_revision ?? state.lastJob.review_revision,
    };
    setReview(normalizeReview(payload.review), state.imageUrl);
    state.generationReadiness = null;
    const context = getReviewContext(messageId);
    if (context) {
      context.review = state.review;
      context.imageUrl = state.imageUrl;
    }
    if (typeof loadGenerationState === "function") {
      void loadGenerationState(state.lastJob.job_id, { silent: true });
    }
    updateLatestReviewMessage(command === "apply"
      ? "已整体应用参数修改方案，关联参数、合理性和生图状态已经同步更新。"
      : "已放弃参数修改方案，正式参数没有变化。");
    return true;
  } catch (error) {
    updateLatestReviewMessage(error.message || String(error));
    return false;
  } finally {
    setBusy(false);
  }
}

function markSubmittedMissingChatActions(review, actionRefs) {
  if (!Array.isArray(actionRefs)) return;
  actionRefs.forEach((reference) => {
    const action = review.standardization_chat?.[reference.turnIndex]?.suggested_actions?.[reference.actionIndex];
    if (action?.type === "request_missing_field" && action.status === "need_input") {
      action.status = "submitted";
    }
  });
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
  const reviewScrollState = captureReviewScrollState();
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
  } else {
    restoreReviewScrollState(reviewScrollState);
  }
}

function restoreConversationScroll(scrollTop) {
  requestAnimationFrame(() => {
    conversation.scrollTop = scrollTop;
  });
}

function captureReviewScrollState() {
  return {
    windowX: window.scrollX,
    windowY: window.scrollY,
    conversationScrollTop: conversation.scrollTop,
    comparePanels: captureComparePanelScrollPositions(),
    chatLists: Array.from(document.querySelectorAll(".standardization-chat-list"), (list) => list.scrollTop),
  };
}

function restoreReviewScrollState(scrollState) {
  if (!scrollState) return;
  const restore = () => {
    window.scrollTo(scrollState.windowX || 0, scrollState.windowY || 0);
    conversation.scrollTop = scrollState.conversationScrollTop || 0;
    restoreComparePanelScrollPositions(scrollState.comparePanels, { immediate: true });
    document.querySelectorAll(".standardization-chat-list").forEach((list, index) => {
      const scrollTop = scrollState.chatLists?.[index];
      if (Number.isFinite(scrollTop)) list.scrollTop = scrollTop;
    });
  };
  requestAnimationFrame(() => {
    restore();
    requestAnimationFrame(restore);
  });
}

function parameterAuditState(param) {
  return {
    value: param?.value ?? null,
    unit: param?.unit ?? null,
    tolerance_upper: param?.tolerance_upper ?? null,
    tolerance_lower: param?.tolerance_lower ?? null,
    need_human_review: Boolean(param?.need_human_review),
    source: sourceValues(param?.source),
    default_source: param?.default_source ?? null,
    evidence: param?.evidence ?? "",
  };
}

function loadPointAuditState(point) {
  return {
    height: point?.height ?? null,
    force: point?.force ?? null,
    load_tolerance_upper: point?.load_tolerance_upper ?? null,
    load_tolerance_lower: point?.load_tolerance_lower ?? null,
    load_tolerance_percent: point?.load_tolerance_percent ?? null,
    need_human_review: Boolean(point?.need_human_review),
  };
}

function queueReviewAuditEvent(event) {
  if (!state.review || !event) return null;
  state.generationReadiness = null;
  const entry = {
    client_event_id: createAuditEventId(),
    event_type: event.event_type || "manual_review_updated",
    target_field: event.target_field || null,
    source: event.source || "manual",
    reason: event.reason || "人工在审查界面修改",
    before_state: event.before_state || null,
    after_state: event.after_state || null,
    metadata: event.metadata || {},
    created_at: new Date().toISOString(),
    sync_status: state.lastJob?.job_id ? "pending" : "local_only",
  };
  state.review.change_history ||= [];
  state.review.change_history.unshift(entry);
  if (state.lastJob?.job_id) {
    state.pendingReviewAuditEvents.push(entry);
    scheduleReviewPersistence();
  }
  refreshReviewChangeHistory();
  return entry;
}

function createAuditEventId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `audit_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function scheduleReviewPersistence() {
  clearTimeout(state.reviewPersistenceTimer);
  state.reviewPersistenceTimer = setTimeout(() => {
    persistReviewChanges();
  }, 450);
}

async function flushReviewPersistence(options = {}) {
  clearTimeout(state.reviewPersistenceTimer);
  if (state.reviewPersistenceSaving && state.reviewPersistencePromise) {
    await state.reviewPersistencePromise;
  }
  if (state.pendingReviewAuditEvents.length) {
    await persistReviewChanges(options);
  }
}

async function persistReviewChanges(options = {}) {
  if (state.reviewPersistenceSaving && state.reviewPersistencePromise) return state.reviewPersistencePromise;
  if (!state.lastJob?.job_id || !state.pendingReviewAuditEvents.length || !state.review) return false;
  const events = state.pendingReviewAuditEvents.splice(0);
  const reviewSnapshot = normalizeReview(structuredClone(state.review));
  state.reviewPersistenceSaving = true;
  state.reviewPersistencePromise = (async () => {
    try {
      const response = await apiFetch(`/api/reviews/${encodeURIComponent(state.lastJob.job_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review: reviewSnapshot,
          expected_revision: state.lastJob?.review_revision ?? undefined,
          events,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (response.status === 409 && Number.isFinite(Number(payload?.detail?.current_revision))) {
          state.lastJob.review_revision = Number(payload.detail.current_revision);
        }
        throw new Error(typeof payload.detail === "string" ? payload.detail : "审查数据保存失败");
      }
      if (payload.review_revision != null) state.lastJob.review_revision = payload.review_revision;
      const persistedIds = new Set((payload.events || []).map((item) => item.client_event_id).filter(Boolean));
      (state.review.change_history || []).forEach((entry) => {
        if (events.some((item) => item.client_event_id === entry.client_event_id)) {
          entry.sync_status = persistedIds.has(entry.client_event_id) ? "saved" : "saved_local";
        }
      });
      refreshReviewChangeHistory();
      if (state.generationJobs.length) void loadGenerationState(state.lastJob.job_id, { silent: true });
    } catch (error) {
      state.pendingReviewAuditEvents.unshift(...events);
      (state.review.change_history || []).forEach((entry) => {
        if (events.some((item) => item.client_event_id === entry.client_event_id)) entry.sync_status = "pending";
      });
      refreshReviewChangeHistory();
      if (options.throwOnError) throw error;
      return false;
    } finally {
      state.reviewPersistenceSaving = false;
      state.reviewPersistencePromise = null;
    }
  })();
  return state.reviewPersistencePromise;
}

function refreshReviewChangeHistory() {
  if (!state.review) return;
  document.querySelectorAll('[data-kind="review-change-history"]').forEach((node) => {
    const wasOpen = node.open;
    node.outerHTML = renderReviewChangeHistoryHtml(state.review, wasOpen);
  });
}

function scheduleParameterReasonablenessRefresh(messageId = state.activeReviewMessageId) {
  clearTimeout(state.reasonablenessRefreshTimer);
  state.reasonablenessRefreshTimer = setTimeout(() => {
    refreshParameterReasonableness(messageId);
  }, 180);
}

function clearAccuracyGradeUpdateTimer() {
  clearTimeout(state.accuracyGradeUpdate.timer);
  state.accuracyGradeUpdate.timer = null;
}

function resetAccuracyGradeUpdate() {
  clearAccuracyGradeUpdateTimer();
  state.accuracyGradeUpdate.phase = "idle";
  state.accuracyGradeUpdate.grade = "";
  state.accuracyGradeUpdate.operation = "";
  updateAccuracyGradeFeedbackUi();
}

function resetPendingAccuracyGrade() {
  state.pendingAccuracyGrade = "";
}

function pendingAccuracyGradeFor(param) {
  const pending = normalizeAccuracyGrade(state.pendingAccuracyGrade);
  const committed = normalizeAccuracyGrade(param?.value);
  return pending && pending !== committed ? pending : "";
}

function displayedAccuracyGrade(param) {
  return pendingAccuracyGradeFor(param) || normalizeAccuracyGrade(param?.value);
}

function accuracyGradeUpdateMessage(phase, grade, operation = "") {
  if (operation === "manual") {
    if (phase === "loading") return "正在生成标准化方案…";
    if (phase === "success") return "标准化方案已更新";
    if (phase === "error") return "方案生成失败，请重试";
  }
  if (phase === "pending") return `已选择 ${grade}，准备更新…`;
  if (phase === "loading") return `正在按 ${grade} 更新标准化方案…`;
  if (phase === "success") return `已按 ${grade} 更新成功`;
  if (phase === "error") return `按 ${grade} 自动更新失败，请点击更新方案重试`;
  if (phase === "ready") return `已选择 ${grade}，点击生成标准化方案`;
  return "";
}

function setAccuracyGradeUpdate(phase = "idle", grade = "", operation = "") {
  clearAccuracyGradeUpdateTimer();
  state.accuracyGradeUpdate.phase = phase;
  state.accuracyGradeUpdate.grade = grade;
  state.accuracyGradeUpdate.operation = operation;
  updateAccuracyGradeFeedbackUi();
}

function scheduleAutomaticStandardization(messageId = state.activeReviewMessageId, options = {}) {
  clearTimeout(state.automaticStandardizationTimer);
  state.automaticStandardizationTimer = null;
  const results = state.review?.standardization_results || [];
  const needsRefresh = state.review?.derived_parameters_stale
    || results.some((item) => item?.status === "stale");
  const isAccuracyGradeUpdate = options.source === "accuracy_grade";
  // Upload stays fast: only refresh after the user has already asked for a plan once.
  if (!state.review || (!options.force && (!results.length || !needsRefresh))) {
    if (isAccuracyGradeUpdate) setAccuracyGradeUpdate("ready", options.grade || "");
    return false;
  }
  if (state.busy) {
    if (isAccuracyGradeUpdate) setAccuracyGradeUpdate("pending", options.grade || "");
    state.automaticStandardizationTimer = setTimeout(() => {
      state.automaticStandardizationTimer = null;
      scheduleAutomaticStandardization(messageId, options);
    }, 180);
    return true;
  }
  if (isAccuracyGradeUpdate) setAccuracyGradeUpdate("pending", options.grade || "");
  state.automaticStandardizationTimer = setTimeout(() => {
    state.automaticStandardizationTimer = null;
    if (state.busy) {
      scheduleAutomaticStandardization(messageId, options);
      return;
    }
    runStandardization(messageId, {
      automatic: true,
      silent: true,
      accuracy_grade_update: isAccuracyGradeUpdate ? { grade: options.grade || "" } : null,
    });
  }, 900);
  return true;
}

async function refreshParameterReasonableness(messageId = state.activeReviewMessageId) {
  if (!state.review) return;
  const requestId = ++state.reasonablenessRequestSerial;
  const requestReview = normalizeReview(structuredClone(state.review));
  try {
    const response = await apiFetch("/api/reviews/reasonableness", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review: requestReview }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.parameter_reasonableness) return;
    if (requestId !== state.reasonablenessRequestSerial || !state.review) return;
    state.review.parameter_reasonableness = payload.parameter_reasonableness;
    state.review.parameter_reasonableness_stale = false;
    const context = getReviewContext(messageId);
    if (context) context.review = state.review;
    syncParameterReasonablenessSurfaces(messageId);
  } catch {
    // Keep the last diagnostic visible while the local API is unavailable.
  }
}

function syncParameterReasonablenessSurfaces(messageId = state.activeReviewMessageId) {
  if (!state.review) return;
  refreshDerivedStatus(state.review);
  document.querySelectorAll(".summary-strip").forEach((node) => {
    node.outerHTML = renderSummaryHtml(state.review);
  });
  document.querySelectorAll('[data-kind="parameter-reasonableness"]').forEach((node) => {
    const html = renderParameterReasonablenessHtml(state.review);
    if (html) node.outerHTML = html;
  });
  document.querySelectorAll('[data-kind="param"]').forEach((row) => {
    const severity = reasonablenessSeverityForField(state.review, row.dataset.field);
    ["blocked", "warning", "needs_input"].forEach((value) => row.classList.toggle(`parameter-risk-${value}`, severity === value));
    const param = state.review.spring_parameters?.[row.dataset.field];
    if (param) syncConfirmationControl(row, param, { kind: "parameter", field: row.dataset.field, review: state.review });
  });
  document.querySelectorAll('[data-kind="load_point"]').forEach((row) => {
    const point = state.review.spring_parameters?.load_points?.[Number(row.dataset.index)];
    const field = `load_points.${point?.label || `F${Number(row.dataset.index) + 1}`}`;
    const severity = reasonablenessSeverityForField(state.review, field);
    ["blocked", "warning", "needs_input"].forEach((value) => row.classList.toggle(`parameter-risk-${value}`, severity === value));
    if (point) syncConfirmationControl(row, point, { kind: "load_point", field, review: state.review });
  });
  bindReasonablenessIssueFocus(document, messageId);
}

function bindReasonablenessIssueFocus(root, messageId = state.activeReviewMessageId) {
  root.querySelectorAll('[data-role="focus-reasonableness-field"]').forEach((button) => {
    if (button.dataset.boundReasonablenessFocus) return;
    button.dataset.boundReasonablenessFocus = "true";
    button.addEventListener("click", () => {
      focusMissingStandardizationField(button.dataset.field || "", messageId);
    });
  });
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
  if (!state.identityReady) return;
  setBusy(true);
  appendUserMessage("加载样例审查结果");
  const thinkingId = appendAssistantText("正在加载样例...");
  try {
    const response = await apiFetch("/api/samples/mixed-review");
    if (!response.ok) throw new Error("样例审查 JSON 加载失败");
    const review = normalizeReview(await response.json());
    // A demo must never retain the ID of a previously opened real order.
    await flushReviewPersistence();
    state.lastJob = null;
    resetGenerationState();
    state.pendingReviewAuditEvents = [];
    removeMessage(thinkingId);
    state.compareTab = "workbench";
    setReview(review, apiUrl("/api/samples/spring-preview"));
    appendReviewMessage("样例已加载，请确认结构化尺寸数据。");
  } catch (error) {
    replaceMessage(thinkingId, error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

async function loadRecentReviews() {
  if (!state.identityReady || !recentReviews || !recentReviewList || state.recentReviewsLoading) return;
  state.recentReviewsLoading = true;
  if (refreshRecentReviewsButton) refreshRecentReviewsButton.disabled = true;
  try {
    const response = await apiFetch("/api/reviews?limit=20");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "无法读取已保存的审图记录");
    state.recentReviews = Array.isArray(payload.reviews) ? payload.reviews : [];
    renderRecentReviews();
    state.recentReviews
      .filter((item) => ["queued", "processing", "cancel_requested"].includes(item.recognition_status))
      .forEach((item) => trackRecognitionJob(item.job_id));
  } catch (error) {
    state.recentReviews = [];
    renderRecentReviews();
  } finally {
    state.recentReviewsLoading = false;
    if (refreshRecentReviewsButton) refreshRecentReviewsButton.disabled = false;
  }
}

function recognitionProgressText(recognition = {}) {
  const status = recognition.status || recognition.recognition_status || "queued";
  const progress = Number(recognition.progress ?? recognition.recognition_progress ?? 0);
  const queuePosition = recognition.queue_position;
  const stage = recognition.stage || recognition.recognition_stage || "queued";
  const stageLabels = {
    queued: "排队中",
    preparing: "准备文件",
    preparing_file: "准备文件",
    rendering_preview: "生成图纸预览",
    qwen_vision: "Qwen 视觉识别",
    dimension_ocr: "OCR 尺寸复核",
    ocr_review: "OCR 识别",
    ocr_fallback: "OCR 兜底识别",
    geometry_review: "几何复核",
    werk24: "Werk24 识别",
    building_review: "生成审图结果",
    saving_result: "保存审图结果",
    completed: "识别完成",
    failed: "识别失败",
    cancel_requested: "正在取消",
    cancelled: "已取消",
  };
  if (status === "queued") {
    return queuePosition ? `图纸已排队，当前第 ${queuePosition} 位。` : "图纸已排队，等待识别。";
  }
  if (status === "failed") return `图纸识别失败：${recognition.error_message || recognition.recognition_error || "请稍后重试。"}`;
  if (status === "cancel_requested" || status === "cancelled") return "图纸识别已取消。";
  if (status === "completed") return "图纸识别完成，正在打开审图结果。";
  return `正在${stageLabels[stage] || "识别图纸"}，${Math.max(0, Math.min(progress, 99))}%...`;
}

function recognitionStatusLabel(item = {}) {
  const status = item.recognition_status;
  if (!status) return "";
  if (status === "queued") return item.queue_position ? `排队中 · 第${item.queue_position}位` : "排队中";
  if (status === "processing") return `${Math.max(0, Number(item.recognition_progress || 0))}% · 识别中`;
  if (status === "completed") return "已完成";
  if (status === "failed") return "识别失败";
  if (status === "cancel_requested") return "取消中";
  if (status === "cancelled") return "已取消";
  return status;
}

function trackRecognitionJob(jobId, messageId = null) {
  if (!jobId || state.recognitionPollers[jobId]) return;
  if (messageId) state.recognitionMessageIds[jobId] = messageId;
  const poll = async () => {
    try {
      const response = await apiFetch(`/api/reviews/${encodeURIComponent(jobId)}/recognition-status`);
      const payload = await response.json();
      if (response.status === 404) {
        stopTrackingRecognitionJob(jobId);
        return;
      }
      if (!response.ok) throw new Error(payload.detail || "无法读取识别进度");
      const recognition = payload.recognition || {};
      mergeRecognitionStatus(jobId, recognition);
      const progressMessageId = state.recognitionMessageIds[jobId];
      if (progressMessageId) replaceMessage(progressMessageId, recognitionProgressText(recognition), recognition.status === "failed");
      if (["queued", "processing", "cancel_requested"].includes(recognition.status)) return;
      stopTrackingRecognitionJob(jobId);
      if (recognition.status === "completed" && state.lastJob?.job_id === jobId) {
        if (progressMessageId) removeMessage(progressMessageId);
        delete state.recognitionMessageIds[jobId];
        await openPersistedReview(jobId, { recognitionCompleted: true });
      }
    } catch (error) {
      const progressMessageId = state.recognitionMessageIds[jobId];
      if (progressMessageId) replaceMessage(progressMessageId, `识别进度读取失败：${error.message || String(error)}`, true);
      stopTrackingRecognitionJob(jobId);
    }
  };
  state.recognitionPollers[jobId] = window.setInterval(() => { void poll(); }, 2000);
  void poll();
}

function stopTrackingRecognitionJob(jobId) {
  const timer = state.recognitionPollers[jobId];
  if (timer) window.clearInterval(timer);
  delete state.recognitionPollers[jobId];
}

function mergeRecognitionStatus(jobId, recognition) {
  const index = state.recentReviews.findIndex((item) => item.job_id === jobId);
  if (index >= 0) {
    state.recentReviews[index] = {
      ...state.recentReviews[index],
      recognition_status: recognition.status,
      recognition_stage: recognition.stage,
      recognition_progress: recognition.progress,
      recognition_error: recognition.error_message,
      queue_position: recognition.queue_position,
      recognition_attempt_count: recognition.attempt_count,
      image_url: recognition.image_url || state.recentReviews[index].image_url || null,
      updated_at: recognition.updated_at || state.recentReviews[index].updated_at,
    };
  } else {
    state.recentReviews.unshift({
      job_id: jobId,
      drawing_name: recognition.drawing_name,
      recognition_status: recognition.status,
      recognition_stage: recognition.stage,
      recognition_progress: recognition.progress,
      recognition_error: recognition.error_message,
      queue_position: recognition.queue_position,
      recognition_attempt_count: recognition.attempt_count,
      image_url: recognition.image_url || null,
      updated_at: recognition.updated_at,
    });
  }
  renderRecentReviews();
}

function renderRecentReviews() {
  if (!recentReviews || !recentReviewList) return;
  const reviews = state.recentReviews || [];
  if (!reviews.length) {
    recentReviewList.innerHTML = '<p class="history-empty">暂无历史订单。上传并完成审图后，记录会自动保存在这里。</p>';
    return;
  }
  recentReviewList.innerHTML = reviews.map((item) => {
    const title = item.drawing_name || item.drawing_no || `审图 ${String(item.job_id || "").slice(0, 8)}`;
    const type = SPRING_TYPE_LABELS[item.spring_type] || item.spring_type || "未知类型";
    const status = recognitionStatusLabel(item) || recentReviewStatusLabel(item.overall_status);
    const revision = item.revision ? `版本 ${item.revision}` : "本地文件";
    const updatedAt = formatRecentReviewTime(item.updated_at);
    const details = [item.drawing_no, type, status, revision, updatedAt].filter(Boolean).join(" · ");
    const isActive = item.job_id === state.lastJob?.job_id;
    const canRetry = item.recognition_status === "failed";
    return `
      <article class="history-order-item${isActive ? " active" : ""}${canRetry ? " has-retry" : ""}">
        <button class="history-select-button" type="button" data-role="open-recent-review" data-job-id="${escapeHtml(item.job_id)}">
          <span class="history-order-copy">
            <strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
            <span>${escapeHtml(details)}</span>
          </span>
          <span class="history-order-arrow" aria-hidden="true">›</span>
        </button>
        ${canRetry ? `<button class="history-retry-button" type="button" data-role="retry-recognition" data-job-id="${escapeHtml(item.job_id)}" title="重新识别">重试</button>` : ""}
        <button class="history-delete-button" type="button" data-role="delete-recent-review" data-job-id="${escapeHtml(item.job_id)}" title="删除订单" aria-label="删除订单">
          <span class="history-delete-icon" aria-hidden="true"></span>
        </button>
      </article>
    `;
  }).join("");
  recentReviewList.querySelectorAll('[data-role="open-recent-review"]').forEach((button) => {
    button.addEventListener("click", () => {
      void openPersistedReview(button.dataset.jobId || "");
    });
  });
  recentReviewList.querySelectorAll('[data-role="delete-recent-review"]').forEach((button) => {
    button.addEventListener("click", () => {
      const item = state.recentReviews.find((review) => review.job_id === button.dataset.jobId);
      if (item) showDeleteReviewDialog(item);
    });
  });
  recentReviewList.querySelectorAll('[data-role="retry-recognition"]').forEach((button) => {
    button.addEventListener("click", () => {
      void retryRecognitionJob(button.dataset.jobId || "");
    });
  });
}

async function openPersistedReview(jobId, options = {}) {
  if (!jobId || state.busy) return;
  const item = state.recentReviews.find((review) => review.job_id === jobId);
  if (["queued", "processing", "cancel_requested"].includes(item?.recognition_status)) {
    const messageId = appendAssistantText(recognitionProgressText(item), false);
    trackRecognitionJob(jobId, messageId);
    return;
  }
  if (item?.recognition_status === "failed") {
    appendAssistantText(`该图纸识别失败：${item.recognition_error || "请点击历史订单右侧的重试。"}`, true);
    return;
  }
  if (item?.recognition_status === "cancelled") {
    appendAssistantText("该图纸识别已取消。", true);
    return;
  }
  setBusy(true);
  const thinkingId = appendAssistantText("正在恢复已保存的审图记录...");
  try {
    const response = await apiFetch(`/api/reviews/${encodeURIComponent(jobId)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "无法恢复该审图记录");
    removeMessage(thinkingId);
    state.lastJob = {
      job_id: jobId,
      review_revision: payload.review_revision ?? item?.revision ?? null,
      persistence: { mode: item?.revision ? "postgresql" : "json_fallback" },
    };
    state.compareTab = "workbench";
    setReview(normalizeReview(payload), toBackendAssetUrl(item?.image_url));
    await loadGenerationState(jobId, { render: false, silent: true });
    renderRecentReviews();
    if (!options.recognitionCompleted) appendUserMessage(`打开已保存审图：${item?.drawing_name || item?.drawing_no || jobId}`);
    appendReviewMessage("已恢复审图结果，可继续确认、标准化或与 AI 对话。");
    openCompareOverlay();
  } catch (error) {
    replaceMessage(thinkingId, error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

async function retryRecognitionJob(jobId) {
  if (!jobId || state.busy) return;
  const item = state.recentReviews.find((review) => review.job_id === jobId);
  try {
    const response = await apiFetch(`/api/reviews/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "重新识别失败");
    const recognition = payload.recognition || {};
    state.lastJob = { ...(state.lastJob || {}), job_id: jobId };
    const messageId = appendAssistantText(`正在重新识别：${item?.drawing_name || jobId}`);
    state.recognitionMessageIds[jobId] = messageId;
    mergeRecognitionStatus(jobId, recognition);
    trackRecognitionJob(jobId, messageId);
  } catch (error) {
    appendAssistantText(`无法重新识别：${error.message || String(error)}`, true);
  }
}

function showDeleteReviewDialog(item) {
  if (!item?.job_id || document.querySelector(".delete-review-dialog[open]")) return;
  const title = item.drawing_name || item.drawing_no || item.job_id;
  const dialog = document.createElement("dialog");
  dialog.className = "delete-review-dialog";
  dialog.innerHTML = `
    <div class="delete-review-dialog-content">
      <h2>删除历史订单？</h2>
      <p>“${escapeHtml(title)}”将从历史订单中移除。</p>
      <p class="delete-review-dialog-note">审图记录、修改留痕和本地识别产物会一并删除，删除后无法恢复。</p>
      <p class="delete-review-dialog-error" data-role="delete-review-error" hidden></p>
      <div class="delete-review-dialog-actions">
        <button type="button" data-role="cancel-delete-review">取消</button>
        <button class="delete-review-confirm-button" type="button" data-role="confirm-delete-review">删除</button>
      </div>
    </div>
  `;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.querySelector('[data-role="cancel-delete-review"]').addEventListener("click", () => dialog.close());
  dialog.querySelector('[data-role="confirm-delete-review"]').addEventListener("click", () => {
    void deletePersistedReview(item, dialog);
  });
  dialog.showModal();
}

async function deletePersistedReview(item, dialog) {
  if (!item?.job_id || state.busy) return;
  const confirmButton = dialog.querySelector('[data-role="confirm-delete-review"]');
  const cancelButton = dialog.querySelector('[data-role="cancel-delete-review"]');
  const errorNode = dialog.querySelector('[data-role="delete-review-error"]');
  confirmButton.disabled = true;
  cancelButton.disabled = true;
  setBusy(true);
  await flushReviewPersistence();
  try {
    const response = await apiFetch(`/api/reviews/${encodeURIComponent(item.job_id)}`, { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "删除历史订单失败");
    const title = item.drawing_name || item.drawing_no || item.job_id;
    const deletedCurrentReview = state.lastJob?.job_id === item.job_id;
    stopTrackingRecognitionJob(item.job_id);
    const progressMessageId = state.recognitionMessageIds[item.job_id];
    if (progressMessageId) removeMessage(progressMessageId);
    delete state.recognitionMessageIds[item.job_id];
    state.recentReviews = state.recentReviews.filter((review) => review.job_id !== item.job_id);
    if (deletedCurrentReview) resetDeletedReviewState();
    renderRecentReviews();
    dialog.close();
    appendAssistantText(`已删除历史订单：${title}`);
  } catch (error) {
    errorNode.hidden = false;
    errorNode.textContent = error.message || String(error);
    confirmButton.disabled = false;
    cancelButton.disabled = false;
  } finally {
    setBusy(false);
  }
}

function resetDeletedReviewState() {
  clearTimeout(state.reviewPersistenceTimer);
  resetAccuracyGradeUpdate();
  resetPendingAccuracyGrade();
  state.pendingReviewAuditEvents = [];
  if (state.compareOpen) closeCompareOverlay();
  const deletedReview = state.review;
  Object.entries(state.reviewContexts).forEach(([messageId, context]) => {
    if (context.review === deletedReview) {
      removeMessage(messageId);
      delete state.reviewContexts[messageId];
    }
  });
  state.review = null;
  state.imageUrl = null;
  state.lastJob = null;
  resetGenerationState();
  state.activeReviewMessageId = null;
  state.selectedBubbleId = null;
  exportButton.disabled = true;
}

async function startNewReview() {
  if (state.busy || !state.identityReady) return;
  setBusy(true);
  try {
    await flushReviewPersistence();
    clearTimeout(state.reviewPersistenceTimer);
    clearTimeout(state.reasonablenessRefreshTimer);
    clearTimeout(state.standardizationChatTypingTimer);
    clearTimeout(state.automaticStandardizationTimer);
    state.automaticStandardizationTimer = null;
    resetAccuracyGradeUpdate();
    resetPendingAccuracyGrade();
    state.reasonablenessRequestSerial += 1;
    state.pendingReviewAuditEvents = [];
    state.reviewContexts = {};
    state.compareTab = "workbench";
    state.review = null;
    state.imageUrl = null;
    state.lastJob = null;
    resetGenerationState();
    state.activeReviewMessageId = null;
    state.selectedBubbleId = null;
    state.selectedFile = null;
    drawingInput.value = "";
    reviewJsonInput.value = "";
    selectedFileName.textContent = "未选择文件";
    advancedOptions.open = false;
    if (state.compareOpen) closeCompareOverlay();
    exportButton.disabled = true;
    renderEmptyConversation();
    renderRecentReviews();
  } catch (error) {
    appendAssistantText(`无法保存当前审图记录：${error.message || String(error)}`, true);
  } finally {
    setBusy(false);
  }
}

function renderEmptyConversation() {
  conversation.replaceChildren();
  const message = createMessage("assistant");
  message.querySelector(".message-body").innerHTML = `
    <div class="message-meta">助手 · 图纸审查</div>
    <p>上传 PDF 或图片后，我会提取弹簧图纸里的结构化尺寸数据，并在这里等待你确认或修改。</p>
  `;
  conversation.appendChild(message);
  conversation.scrollTop = 0;
}

function recentReviewStatusLabel(status) {
  const labels = {
    pass: "通过",
    warning: "有风险",
    blocked: "需处理",
    need_review: "待确认",
    needs_input: "待补充",
  };
  return labels[status] || status || "待确认";
}

function formatRecentReviewTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
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
      <button type="button" data-action="fullscreen">进入审图工作台</button>
      <button type="button" data-action="export" ${review ? "" : "disabled"}>导出确认版</button>
    </div>
    ${renderStandardizationChatHtml(review)}
  `;
  body.querySelector('[data-action="fullscreen"]').addEventListener("click", () => {
    activateReviewContext(messageId);
    openCompareOverlay();
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
    <small title="${escapeHtml(referenceDetailLabel(item))}">${escapeHtml(referenceSummaryLabel(item))}</small>
  `).join("");
  const thresholdHtml = thresholdRows.map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  const auxiliaryHtml = auxiliaryEvidence.map((item) => `<small>${escapeHtml(item)}</small>`).join("");
  const conflictHtml = conflicts.map((item) => `<small>${escapeHtml(item)}</small>`).join("");
  return `
    <section class="review-block standard-selection-block">
      <details class="standard-selection-details">
        <summary>
          <span class="standard-selection-summary-title">
            <strong>标准选择判断</strong>
            <small>${escapeHtml(`推荐 ${selected} · 置信度 ${confidence}`)}</small>
          </span>
          <span class="standard-selection-summary-status">
            <span class="normalization-status ${escapeHtml(status)}">${escapeHtml(standardSelectionStatusLabel(status))}</span>
            <span class="standard-selection-disclosure" aria-hidden="true"></span>
          </span>
        </summary>
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
      </details>
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

function renderParameterReasonablenessHtml(review) {
  const assessment = review?.parameter_reasonableness || {};
  const status = assessment.status || "not_applicable";
  const issues = Array.isArray(assessment.issues) ? assessment.issues : [];
  const labels = {
    pass: "参数关系正常",
    warning: "存在风险提示",
    blocked: "存在不可用参数",
    needs_input: "需要补充信息",
    not_applicable: "暂不适用",
  };
  if (status === "not_applicable") return "";
  return `
    <section class="review-block parameter-reasonableness-block" data-kind="parameter-reasonableness">
      <div class="block-head">
        <h2>参数合理性</h2>
        <span class="parameter-reasonableness-status ${escapeHtml(status)}">${escapeHtml(labels[status] || "待核对")}</span>
      </div>
      <p class="parameter-reasonableness-summary">${escapeHtml(assessment.summary || "正在核对参数关系。")}</p>
      ${issues.length ? `
        <div class="parameter-reasonableness-list">
          ${issues.map((item, index) => {
            const fields = Array.isArray(item.fields) ? item.fields.filter(Boolean) : [];
            const target = fields[0] || "";
            return `
              <article class="parameter-reasonableness-item ${escapeHtml(item.severity || "warning")}">
                <div class="parameter-reasonableness-item-head">
                  <strong>${escapeHtml(reasonablenessSeverityLabel(item.severity))}</strong>
                  <small>${escapeHtml(item.rule_id || `RULE-${index + 1}`)}</small>
                </div>
                <p>${escapeHtml(item.message || "参数需要复核。")}</p>
                ${item.calculation ? `<small><b>计算：</b>${escapeHtml(item.calculation)}</small>` : ""}
                ${item.basis ? `<small><b>依据：</b>${escapeHtml(item.basis)}</small>` : ""}
                ${item.explanation ? `<small><b>说明：</b>${escapeHtml(item.explanation)}</small>` : ""}
                ${item.customer_question ? `<small><b>建议向客户确认：</b>${escapeHtml(item.customer_question)}</small>` : ""}
                ${target ? `<button type="button" class="secondary-action" data-role="focus-reasonableness-field" data-field="${escapeHtml(target)}">定位参数</button>` : ""}
              </article>
            `;
          }).join("")}
        </div>
      ` : `<div class="parameter-reasonableness-empty">未发现明显几何矛盾或当前标准适用范围风险，仍请确认识别值与使用工况。</div>`}
    </section>
  `;
}

function reasonablenessSeverityLabel(severity) {
  const labels = {
    blocked: "不可用",
    warning: "风险提示",
    needs_input: "待补充",
  };
  return labels[severity] || "待核对";
}

function reasonablenessSeverityForField(review, field) {
  const target = String(field || "");
  const ranks = { blocked: 3, warning: 2, needs_input: 1 };
  let result = "";
  for (const issue of review?.parameter_reasonableness?.issues || []) {
    const fields = Array.isArray(issue?.fields) ? issue.fields : [];
    const matches = fields.some((candidate) => {
      const value = String(candidate || "");
      return value === target || value.startsWith(`${target}.`) || target.startsWith(`${value}.`);
    });
    if (matches && (ranks[issue.severity] || 0) > (ranks[result] || 0)) result = issue.severity;
  }
  return result;
}

function renderParameterTableHtml(review) {
  const params = review.spring_parameters || {};
  const fieldGroups = getParameterFieldGroups(params, review);
  const confirmationPlan = buildSafeConfirmationPlan(review);
  const parameterRows = fieldGroups.core.map((field) => {
    const meta = getFieldMeta(field, review);
    return parameterRowHtml(field, params[field] || blankParam(meta.unit), meta);
  });
  const advancedRows = fieldGroups.advanced.map((field) => {
    const meta = getFieldMeta(field, review);
    return parameterRowHtml(field, params[field] || blankParam(meta.unit), meta);
  });
  const loadPointRows = (params.load_points || []).map((point, index) => loadPointRowHtml(point, index, review));
  const totalRows = parameterRows.length + loadPointRows.length;
  return `
    <section class="review-block">
      <div class="block-head">
        <h2>结构化尺寸数据</h2>
        <div class="parameter-bulk-actions">
          <span>${totalRows} 项</span>
          <button type="button" data-action="confirm-all-review-items" ${confirmationPlan.items.length ? "" : "disabled"}>全部确认可确认项${confirmationPlan.items.length ? ` · ${confirmationPlan.items.length}` : ""}</button>
        </div>
      </div>
      <div class="data-table">
        ${dataTableHeadHtml("参数", "数值", "公差")}
        ${parameterRows.join("")}
      </div>
      ${renderCompressionDesignCheckHtml(review)}
      ${loadPointRows.length ? `
        <div class="data-subsection">
          <div class="data-subsection-head">载荷测试点</div>
          <div class="data-table load-point-table">
            ${loadPointTableHeadHtml()}
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
      ${renderReviewChangeHistoryHtml(review)}
    </section>
  `;
}

function renderReviewChangeHistoryHtml(review, forceOpen = false) {
  const entries = Array.isArray(review?.change_history) ? review.change_history.slice(0, 20) : [];
  const rows = entries.length
    ? entries.map((entry) => `
      <li class="review-change-history-item">
        <div>
          <strong>${escapeHtml(auditTargetLabel(entry.target_field))}</strong>
          <span>${escapeHtml(auditEventLabel(entry.event_type))}</span>
        </div>
        <p>${escapeHtml(auditStateText(entry.before_state))} <b>→</b> ${escapeHtml(auditStateText(entry.after_state))}</p>
        <small>${escapeHtml(formatAuditTime(entry.created_at))}${entry.sync_status === "pending" ? " · 待保存" : ""}</small>
      </li>
    `).join("")
    : `<li class="review-change-history-empty">暂未产生人工修改记录。</li>`;
  return `
    <details class="review-change-history" data-kind="review-change-history"${forceOpen ? " open" : ""}>
      <summary>
        <span>修改记录</span>
        <small>${entries.length ? `最近 ${entries.length} 条` : "暂无"}</small>
      </summary>
      <ol>${rows}</ol>
    </details>
  `;
}

function auditTargetLabel(target) {
  const value = String(target || "");
  if (value.startsWith("load_points.")) return `载荷测试点 ${value.slice("load_points.".length)}`;
  return targetFieldLabel(value) || value || "审查数据";
}

function auditEventLabel(eventType) {
  const labels = {
    parameter_value_updated: "修改数值",
    parameter_tolerance_updated: "修改公差",
    parameter_confirmed: "确认参数",
    parameter_reopened: "重新编辑",
    recognized_value_confirmed: "确认识别值",
    modified_value_confirmed: "确认修改值",
    risk_value_confirmed: "确认风险值",
    load_point_value_updated: "修改载荷测试点",
    load_point_tolerance_updated: "修改载荷公差",
    load_point_confirmed: "确认载荷测试点",
    load_point_reopened: "重新编辑",
    standardization_suggestion_applied: "应用标准化建议",
    standardization_suggestions_applied: "批量应用标准化建议",
    standardization_application_reverted: "撤销标准化建议",
    standard_selection_confirmed: "确认适用标准",
    safe_fields_confirmed: "批量确认无风险项",
    all_fields_confirmed: "全部确认",
  };
  return labels[eventType] || "更新审查数据";
}

function auditStateText(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return "无";
  const parts = [];
  if (snapshot.value != null && snapshot.value !== "") parts.push(String(snapshot.value));
  if (snapshot.height != null && snapshot.height !== "") parts.push(`H=${snapshot.height}`);
  if (snapshot.force != null && snapshot.force !== "") parts.push(`F=${snapshot.force}`);
  const upper = snapshot.tolerance_upper ?? snapshot.load_tolerance_upper;
  const lower = snapshot.tolerance_lower ?? snapshot.load_tolerance_lower;
  const percent = snapshot.load_tolerance_percent;
  if (upper != null || lower != null) parts.push(`公差 ${upper ?? ""}/${lower ?? ""}`);
  if (percent != null && percent !== "") parts.push(`公差 ${percent}%`);
  if (!parts.length && snapshot.confirmed != null) parts.push(snapshot.confirmed ? "已确认" : "待确认");
  return parts.join("，") || "无";
}

function formatAuditTime(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "刚刚";
  return date.toLocaleString("zh-CN", { hour12: false });
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

function renderCompressionDesignCheckHtml(review) {
  if (!isCompressionSpringReview(review)) return "";
  const values = compressionDesignCheckValues(review.spring_parameters || {});
  return `
    <section class="compression-design-check" data-kind="compression-design-check">
      <div class="compression-design-check-head">
        <strong>设计校核值</strong>
        <small>自动计算</small>
      </div>
      <div class="compression-design-check-grid">
        ${compressionDesignCheckMetricHtml("旋绕比 C", "spring_index", values.spring_index, "C = D / d", values.spring_index_missing)}
        ${compressionDesignCheckMetricHtml("细长比 b", "slenderness_ratio", values.slenderness_ratio, "b = H0 / D", values.slenderness_ratio_missing)}
      </div>
    </section>
  `;
}

function compressionDesignCheckMetricHtml(label, metric, value, formula, missingFields) {
  const valueText = value == null ? "--" : formatCompactNumber(value);
  const missingText = value == null && missingFields.length
    ? `待补充：${missingFields.map((field) => targetFieldLabel(field)).join("、")}`
    : formula;
  return `
    <div class="compression-design-check-metric">
      <span>${escapeHtml(label)}</span>
      <strong data-role="design-check-value" data-metric="${escapeHtml(metric)}">${escapeHtml(valueText)}</strong>
      <small data-role="design-check-basis" data-metric="${escapeHtml(metric)}">${escapeHtml(missingText)}</small>
    </div>
  `;
}

function compressionDesignCheckValues(params, overrides = {}) {
  const valueFor = (field) => {
    const raw = Object.prototype.hasOwnProperty.call(overrides, field)
      ? overrides[field]
      : params[field]?.value;
    if (raw == null || String(raw).trim() === "") return null;
    const numeric = Number(raw);
    return Number.isFinite(numeric) ? numeric : null;
  };
  const wire = valueFor("wire_diameter");
  const outer = valueFor("outer_diameter");
  const inner = valueFor("inner_diameter");
  const recognizedMean = valueFor("mean_diameter");
  const freeLength = valueFor("free_length");
  const mean = recognizedMean ?? (wire != null && outer != null ? outer - wire : null) ?? (wire != null && inner != null ? inner + wire : null);
  const meanMissing = mean == null ? ["mean_diameter", "outer_diameter", "inner_diameter", "wire_diameter"] : [];
  const springIndex = mean != null && wire != null && wire !== 0 ? mean / wire : null;
  const slendernessRatio = mean != null && mean !== 0 && freeLength != null ? freeLength / mean : null;
  return {
    spring_index: springIndex,
    spring_index_missing: springIndex == null ? (wire == null || wire === 0 ? ["wire_diameter"] : meanMissing) : [],
    slenderness_ratio: slendernessRatio,
    slenderness_ratio_missing: slendernessRatio == null
      ? (freeLength == null ? ["free_length"] : meanMissing)
      : [],
  };
}

function designCheckInputOverrides(root) {
  const overrides = {};
  root.querySelectorAll('[data-kind="param"][data-field]').forEach((row) => {
    const input = row.querySelector('[data-role="value"]');
    if (input) overrides[row.dataset.field] = input.value;
  });
  return overrides;
}

function refreshCompressionDesignChecks(root, review) {
  const containers = root.querySelectorAll('[data-kind="compression-design-check"]');
  if (!containers.length) return;
  const values = compressionDesignCheckValues(review.spring_parameters || {}, designCheckInputOverrides(root));
  const metrics = {
    spring_index: { value: values.spring_index, formula: "C = D / d", missing: values.spring_index_missing },
    slenderness_ratio: { value: values.slenderness_ratio, formula: "b = H0 / D", missing: values.slenderness_ratio_missing },
  };
  containers.forEach((container) => {
    Object.entries(metrics).forEach(([metric, item]) => {
      const value = container.querySelector(`[data-role="design-check-value"][data-metric="${metric}"]`);
      const basis = container.querySelector(`[data-role="design-check-basis"][data-metric="${metric}"]`);
      if (value) value.textContent = item.value == null ? "--" : formatCompactNumber(item.value);
      if (basis) {
        basis.textContent = item.value == null && item.missing.length
          ? `待补充：${item.missing.map((field) => targetFieldLabel(field)).join("、")}`
          : item.formula;
      }
    });
  });
}

function loadPointTableHeadHtml() {
  return `
    <div class="data-table-head" aria-hidden="true">
      <span>&#36733;&#33655;&#28857;</span>
      <span>&#39640;&#24230;</span>
      <span>&#21147;&#20540;</span>
      <span>&#20844;&#24046;</span>
      <span>&#25805;&#20316;</span>
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
    core: fields.filter((field) => (
      COMPRESSION_CORE_PARAMETER_FIELDS.has(field)
      && (field !== "solid_height" || shouldShowSolidHeightCore(params[field]))
    )),
    advanced: fields.filter((field) => {
      if (COMPRESSION_CORE_PARAMETER_FIELDS.has(field)) return false;
      return shouldShowAdvancedParameter(field, params[field], review);
    }),
  };
}

function shouldShowSolidHeightCore(param) {
  return hasParameterContent(param);
}

function shouldShowAdvancedParameter(field, param, review) {
  if (SPECIALIZED_ACCURACY_PARAMETER_FIELDS.has(field)) {
    return hasExplicitSpecializedAccuracyContent(param);
  }
  return hasParameterContent(param) || hasStandardizationForField(field, review);
}

function hasExplicitSpecializedAccuracyContent(param) {
  if (!param || typeof param !== "object" || Array.isArray(param)) return false;
  const hasValue = param.value != null && param.value !== "";
  const hasTolerance = (param.tolerance_upper != null && param.tolerance_upper !== "")
    || (param.tolerance_lower != null && param.tolerance_lower !== "");
  if (!hasValue && !hasTolerance) return false;
  if (param.default_source === "company_default") return false;
  return true;
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
  let label = meta.label || FIELD_LABELS[field] || field;
  const requiredMark = meta.required ? " *" : "";
  const badges = [];
  const sources = sourceValues(param.source);
  if (param.default_source === "company_default" && field !== "accuracy_grade") {
    badges.push("公司默认 / 待确认");
  }
  if (field === "spring_rate") {
    if (sources.includes("formula_calculation")) {
      badges.push("公式计算 / 待确认");
    } else if (sources.some((source) => source.startsWith("human") || source === "manual")) {
      badges.push("人工填写");
    } else if (param.value != null && param.value !== "") {
      badges.push("图纸识别");
    }
  }
  if (field === "solid_height") {
    if (sources.includes("formula_calculation")) {
      label = `${label}（参考）`;
      badges.push("公式参考 / 待确认");
    } else if (sources.some((source) => source.startsWith("human") || source === "manual")) {
      badges.push("人工值");
    } else if (param.value != null && param.value !== "") {
      badges.push("图纸值");
    }
  }
  const reasonablenessSeverity = reasonablenessSeverityForField(state.review, field);
  if (reasonablenessSeverity) {
    badges.push(reasonablenessSeverityLabel(reasonablenessSeverity));
  }
  const accuracyGradeStatus = field === "accuracy_grade" ? accuracyGradeStatusLabel(param) : "";
  return `
    <div class="data-row${reasonablenessSeverity ? ` parameter-risk-${escapeHtml(reasonablenessSeverity)}` : ""}" data-kind="param" data-field="${escapeHtml(field)}">
      <div class="data-label">
        <strong title="${escapeHtml(label)}">${escapeHtml(label + requiredMark)}</strong>
        ${evidence ? `<small title="${escapeHtml(evidence)}">${escapeHtml(evidence)}</small>` : ""}
        ${badges.length || accuracyGradeStatus ? `<div class="parameter-badges">${accuracyGradeStatus ? `<span class="accuracy-grade-source ${accuracyGradeStatusClass(param)}" data-accuracy-grade-source>${escapeHtml(accuracyGradeStatus)}</span>` : ""}${badges.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
      </div>
      <label class="data-input-cell data-primary">
        <span class="sr-only">${escapeHtml(label)}数值</span>
        ${parameterValueControlHtml(field, param, label)}
      </label>
      <label class="data-input-cell data-secondary">
        <span class="sr-only">${escapeHtml(label)}公差</span>
        <input data-role="tolerance" aria-label="${escapeHtml(label)}公差" value="${escapeHtml(formatTolerance(param))}">
      </label>
      ${confirmationButtonHtml(param, { kind: "parameter", field, review: state.review })}
    </div>
  `;
}

function loadPointRowHtml(point, index, review = state.review) {
  const evidence = point.evidence || "";
  const label = point.label || `F${index + 1}`;
  const tolerance = loadPointToleranceDisplay(point, label, review);
  const reasonablenessSeverity = reasonablenessSeverityForField(review, `load_points.${label}`);
  return `
    <div class="data-row load-point${reasonablenessSeverity ? ` parameter-risk-${escapeHtml(reasonablenessSeverity)}` : ""}" data-kind="load_point" data-index="${index}">
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
      <label class="data-input-cell data-tertiary load-point-tolerance">
        <span class="sr-only">${escapeHtml(label)}&#20844;&#24046;</span>
        <input data-role="load-tolerance" aria-label="${escapeHtml(label)}&#20844;&#24046;" value="${escapeHtml(tolerance.value)}" placeholder="${escapeHtml(tolerance.placeholder)}" title="${escapeHtml(tolerance.title)}">
        ${tolerance.note ? `<small>${escapeHtml(tolerance.note)}</small>` : ""}
      </label>
      ${confirmationButtonHtml(point, { kind: "load_point", field: `load_points.${label}`, review })}
    </div>
  `;
}

function loadPointToleranceDisplay(point, label, review) {
  const suggestion = findLoadPointToleranceSuggestion(review, label);
  const suggested = suggestion ? formatLoadPointAbsoluteTolerance(
    suggestion.suggested_tolerance_upper,
    suggestion.suggested_tolerance_lower,
  ) : "";
  const absolute = formatLoadPointAbsoluteTolerance(
    point.load_tolerance_upper,
    point.load_tolerance_lower,
  );
  const drawingPercent = point.drawing_force_tolerance_percent ?? point.drawing_load_tolerance_percent;
  const standardizedPercent = point.load_tolerance_percent ?? point.force_tolerance_percent;
  if (point.tolerance_source === "standardization" && standardizedPercent != null && standardizedPercent !== "") {
    const drawingNote = drawingPercent != null && drawingPercent !== ""
      ? `\u56fe\u7eb8\u539f\u516c\u5dee \u00b1${formatCompactNumber(Math.abs(Number(drawingPercent)))}%`
      : "";
    return {
      value: `\u00b1${formatCompactNumber(Math.abs(Number(standardizedPercent)))}%`,
      placeholder: "",
      title: point.tolerance_basis || suggestion?.basis || "",
      note: [absolute ? `\u6807\u51c6\u5316\u503c ${absolute}` : "", drawingNote].filter(Boolean).join("\uff1b"),
    };
  }
  if (absolute) {
    return {
      value: absolute,
      placeholder: "",
      title: suggestion?.basis || "",
      note: suggested && suggested !== absolute ? `\u6807\u51c6\u5efa\u8bae ${suggested}` : "",
    };
  }

  const rawDrawingPercent = point.force_tolerance_percent ?? point.load_tolerance_percent;
  if (rawDrawingPercent != null && rawDrawingPercent !== "") {
    return {
      value: `\u00b1${formatCompactNumber(Math.abs(Number(rawDrawingPercent)))}%`,
      placeholder: "",
      title: suggestion?.basis || "",
      note: suggested ? `\u6807\u51c6\u5efa\u8bae ${suggested}` : "\u56fe\u7eb8\u516c\u5dee",
    };
  }

  if (!suggestion) {
    return { value: "", placeholder: "", title: "", note: "" };
  }
  return {
    value: "",
    placeholder: suggested ? `\u5efa\u8bae ${suggested}` : "",
    title: suggestion.basis || "",
    note: suggested ? "\u6807\u51c6\u5efa\u8bae" : "",
  };
}

function findLoadPointToleranceSuggestion(review, label) {
  const target = `load_points.${label}.force`;
  return (review?.standardization_results || []).find((item) => {
    if (String(item.target_field || "") !== target) return false;
    return item.suggested_tolerance_upper != null || item.suggested_tolerance_lower != null;
  }) || null;
}

function formatLoadPointAbsoluteTolerance(upper, lower) {
  if (upper == null && lower == null) return "";
  if (upper != null && lower != null && Number(upper) === Math.abs(Number(lower))) {
    return `\u00b1${formatCompactNumber(Math.abs(Number(upper)))}N`;
  }
  return `${upper ?? ""}/${lower ?? ""}N`;
}

function applyStandardizedLoadTolerance(point, upper, lower, options = {}) {
  if (!point || typeof point !== "object") return;
  if (point.drawing_force_tolerance_percent == null && point.force_tolerance_percent != null) {
    point.drawing_force_tolerance_percent = point.force_tolerance_percent;
  }
  if (point.drawing_load_tolerance_percent == null && point.load_tolerance_percent != null) {
    point.drawing_load_tolerance_percent = point.load_tolerance_percent;
  }
  point.load_tolerance_upper = upper ?? null;
  point.load_tolerance_lower = lower ?? null;
  const referenceTolerance = upper ?? (lower == null ? null : Math.abs(Number(lower)));
  if (point.force && referenceTolerance != null && !Number.isNaN(Number(referenceTolerance))) {
    const percent = Number(((Math.abs(Number(referenceTolerance)) / Math.abs(Number(point.force))) * 100).toFixed(3));
    point.force_tolerance_percent = percent;
    point.load_tolerance_percent = percent;
  }
  point.tolerance_source = "standardization";
  point.tolerance_basis = options.basis || point.tolerance_basis || "";
}

function confirmationItemWasEdited(item) {
  return Boolean(item?.need_human_review) && sourceValues(item?.source).includes("human_edited");
}

function hasPendingEditedReviewItems(review) {
  if (!review) return false;
  const parameters = review.spring_parameters || {};
  const parameterPending = Object.values(parameters).some((item) => {
    if (Array.isArray(item)) return item.some(confirmationItemWasEdited);
    return confirmationItemWasEdited(item);
  });
  return parameterPending || (review.technical_requirements || []).some(confirmationItemWasEdited);
}

function confirmationControlState(item, options = {}) {
  const kind = options.kind || "parameter";
  const field = options.field || "";
  const review = options.review || state.review;
  if (!item?.need_human_review) {
    return { state: "confirmed", label: "已确认", disabled: true, reason: "该项已经确认；修改内容后可重新确认。" };
  }

  let invalidReason = "";
  if (kind === "load_point") {
    if (!isFiniteReviewNumber(item?.height) || !isFiniteReviewNumber(item?.force)) {
      invalidReason = "高度和力值需要完整填写为有效数字";
    }
  } else if (kind === "technical") {
    if (!String(item?.content || "").trim()) invalidReason = "技术要求内容不能为空";
    else if (item?.type === "surface" && !["matched", "alias_matched", "llm_auto_matched", "human_confirmed"].includes(item?.normalization_status)) {
      invalidReason = "请先明确表面处理标准术语";
    }
  } else {
    invalidReason = bulkParameterInvalidReason(field, item);
    if (!invalidReason && item?.derived_value_stale) invalidReason = "关联参数已变化，等待重新计算";
  }

  const severity = kind === "technical" ? "" : reasonablenessSeverityForField(review, field);
  if (!invalidReason && ["blocked", "needs_input"].includes(severity)) {
    invalidReason = severity === "blocked" ? "存在阻断问题，请先修改参数" : "所需信息尚未填写完整";
  }
  if (!invalidReason && confirmationItemWasEdited(item) && review?.parameter_reasonableness_stale && kind !== "technical") {
    return { state: "validating", label: "校验中", disabled: true, reason: "正在重新检查参数合理性。" };
  }
  if (invalidReason) {
    return { state: "invalid", label: "无法确认", disabled: true, reason: invalidReason };
  }

  const modified = confirmationItemWasEdited(item);
  return {
    state: modified ? "modified" : (severity === "warning" ? "warning" : "pending"),
    label: modified ? "确认修改" : "确认",
    disabled: false,
    reason: severity === "warning" ? "当前值存在风险提示，确认后将记录人工接受。" : "",
  };
}

function confirmationButtonHtml(item, options = {}) {
  const control = confirmationControlState(item, options);
  const title = control.reason ? ` title="${escapeHtml(control.reason)}"` : "";
  return `<button class="confirm-button ${escapeHtml(control.state)}" type="button" data-role="confirm"${control.disabled ? " disabled" : ""}${title}>${escapeHtml(control.label)}</button>`;
}

function syncConfirmationControl(row, item, options = {}) {
  const button = row?.querySelector?.('[data-role="confirm"]');
  if (!button) return confirmationControlState(item, options);
  const control = confirmationControlState(item, options);
  button.classList.remove("confirmed", "pending", "modified", "warning", "validating", "invalid");
  button.classList.add(control.state);
  button.disabled = control.disabled;
  button.textContent = control.label;
  button.title = control.reason || "";
  row.dataset.confirmationState = control.state;
  return control;
}

function syncReviewConfirmationControls(root, review = state.review) {
  if (!root || !review) return;
  root.querySelectorAll('[data-kind="param"][data-field]').forEach((row) => {
    const field = row.dataset.field;
    const item = review.spring_parameters?.[field];
    if (item) syncConfirmationControl(row, item, { kind: "parameter", field, review });
  });
  root.querySelectorAll('[data-kind="load_point"][data-index]').forEach((row) => {
    const item = review.spring_parameters?.load_points?.[Number(row.dataset.index)];
    const field = `load_points.${item?.label || `F${Number(row.dataset.index) + 1}`}`;
    if (item) syncConfirmationControl(row, item, { kind: "load_point", field, review });
  });
  root.querySelectorAll('[data-kind="technical"][data-index]').forEach((row) => {
    const index = Number(row.dataset.index);
    const item = review.technical_requirements?.[index];
    if (item) syncConfirmationControl(row, item, { kind: "technical", field: `technical_requirements.${index + 1}`, review });
  });
}

function renderDerivedParametersHtml(review) {
  const derived = review.derived_parameters || {};
  const staleNotice = review.derived_parameters_stale
    ? `<div class="standardization-stale-notice">参数已修改，派生参数和标准化建议待重新计算。</div>`
    : "";
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
      <strong>${escapeHtml(item.label || "载荷测试点")}</strong>
      <span>${escapeHtml(formatStandardValue(item.deflection, item.deflection_unit))}</span>
      <small>${escapeHtml(item.formula || "")}</small>
    </div>
  `).join("");
  if (!rows && !loadRows) {
    return `
      <section class="review-block">
        <div class="block-head"><h2>派生参数</h2><span>0 项</span></div>
        ${staleNotice}
        <div class="empty-line">暂未生成中径、旋绕比、细长比或载荷变形量。</div>
      </section>
    `;
  }
  return `
    <section class="review-block">
      <div class="block-head"><h2>派生参数</h2><span>${review.derived_parameters_stale ? "待重新计算" : `${Object.keys(derived).length} 组`}</span></div>
      ${staleNotice}
      <div class="derived-list">${rows}${loadRows}</div>
    </section>
  `;
}

function renderGenerationReadinessHtml(review) {
  const serverState = review === state.review ? state.generationReadiness : null;
  const readiness = serverState?.generation_readiness || assessGenerationReadiness(review);
  const isPersistedReview = Boolean(state.lastJob?.job_id && review === state.review);
  const canGenerate = isPersistedReview && state.generationQueueAvailable === true && ["ready", "ready_with_warnings"].includes(readiness.status);
  const statusLabels = {
    ready: "可生成",
    ready_with_warnings: "可生成，有提示",
    needs_input: "待补充",
    needs_confirmation: "待确认",
    blocked: "存在不可用参数",
    not_applicable: "暂不适用",
  };
  return `
    <section class="review-block generation-readiness-block">
      <div class="block-head">
        <h2>生图参数包</h2>
        <span class="generation-readiness-status ${escapeHtml(readiness.status)}">${escapeHtml(statusLabels[readiness.status] || "待核对")}</span>
      </div>
      <p class="generation-readiness-summary">${escapeHtml(readiness.summary)}</p>
      <div class="generation-readiness-progress">已确认核心参数 ${readiness.confirmed_core_count}/${readiness.core_field_count}</div>
      ${renderGenerationReadinessIssues("需要补充", readiness.missing_fields, "missing")}
      ${renderGenerationReadinessIssues("需要确认", readiness.pending_fields, "pending")}
      ${renderGenerationReadinessIssues("参数不合理", readiness.blocking_reasonableness, "blocked")}
      ${renderGenerationReadinessIssues("风险提示", readiness.warnings, "warning")}
      <div class="generation-package-actions">
        <button type="button" data-action="export-generation-package">导出参数包</button>
        <button type="button" class="primary-action" data-action="create-generation-job" ${canGenerate && !state.generationBusy ? "" : "disabled"}>${state.generationBusy ? "正在创建…" : "生成图纸"}</button>
        <small>${isPersistedReview
          ? (state.generationQueueAvailable === false ? "就绪状态可查询；创建生图任务需要 PostgreSQL。" : "就绪状态由服务器重新计算；参数有提示时仍可确认后生成。")
          : "本地导入数据仅允许导出，保存为服务器审图单后才能生图。"}</small>
      </div>
      ${renderGenerationJobsHtml(review)}
    </section>
  `;
}

function renderGenerationJobsHtml(review) {
  if (review !== state.review || !state.lastJob?.job_id) return "";
  const jobs = Array.isArray(state.generationJobs) ? state.generationJobs : [];
  if (!jobs.length) {
    return '<div class="generation-empty">尚未生成版本。创建后会在这里显示 SolidWorks 模拟任务进度。</div>';
  }
  return `
    <section class="generation-version-section">
      <div class="generation-version-head">
        <strong>生图版本 · ${jobs.length}</strong>
        <span>旧版本保留，可随参数修订重新生成</span>
      </div>
      <div class="generation-version-list">
        ${jobs.map((job, index) => renderGenerationJobHtml(job, jobs.length - index)).join("")}
      </div>
      <div class="generation-erp-placeholder">
        <button type="button" disabled>传送至 ERP</button>
        <span>待真实 SolidWorks / ERP 接入</span>
      </div>
    </section>
  `;
}

function renderGenerationJobHtml(job, versionNumber) {
  const labels = {
    queued: "排队中",
    claimed: "已领取",
    generating_3d: "生成三维模型",
    generating_2d: "生成二维图",
    uploading: "上传产物",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  const png = (job.artifacts || []).find((item) => item.artifact_type === "png" || item.mime_type === "image/png");
  const pdf = (job.artifacts || []).find((item) => item.artifact_type === "pdf" || item.mime_type === "application/pdf");
  const isMock = (job.artifacts || []).some((item) => item.is_mock) || String(job.template_code || "").startsWith("mock");
  const terminal = ["completed", "failed", "cancelled"].includes(job.status);
  return `
    <article class="generation-version-card ${escapeHtml(job.status || "queued")}${job.is_final ? " final" : ""}${job.is_stale ? " stale" : ""}">
      <div class="generation-version-title">
        <div>
          <strong>版本 ${escapeHtml(String(versionNumber))}${job.is_final ? ` · ${isMock ? "模拟最终版本" : "最终版本"}` : ""}</strong>
          <small>审图修订 r${escapeHtml(String(job.review_revision ?? "-"))} · ${escapeHtml(job.template_code || "未匹配模板")} / ${escapeHtml(job.template_version || "-")}</small>
        </div>
        <span class="generation-job-status">${escapeHtml(labels[job.status] || job.status || "未知")}</span>
      </div>
      ${!terminal ? `<div class="generation-progress"><span style="width:${Math.min(Math.max(Number(job.progress) || 0, 0), 100)}%"></span></div>` : ""}
      <div class="generation-version-meta">
        <span>${escapeHtml(formatRecentReviewTime(job.completed_at || job.updated_at || job.created_at))}</span>
        ${isMock ? "<span>模拟产物</span>" : ""}
        ${job.parent_generation_id ? "<span>基于上一版本</span>" : ""}
        ${job.is_stale ? "<span class=\"generation-stale-label\">参数已过期</span>" : ""}
      </div>
      ${job.error_message ? `<p class="generation-error">${escapeHtml(job.error_code || "generation_failed")}：${escapeHtml(job.error_message)}</p>` : ""}
      <div class="generation-version-actions">
        ${png ? `<button type="button" data-action="compare-generation" data-generation-id="${escapeHtml(job.generation_id)}">对比图纸</button>` : ""}
        ${pdf ? `<a class="button-link" href="${escapeHtml(toBackendAssetUrl(pdf.url))}" target="_blank" rel="noopener">查看 PDF</a>` : ""}
        ${job.status === "failed" ? `<button type="button" data-action="retry-generation" data-generation-id="${escapeHtml(job.generation_id)}">原参数重试</button>` : ""}
        ${!terminal ? `<button type="button" class="secondary-action" data-action="cancel-generation" data-generation-id="${escapeHtml(job.generation_id)}">取消</button>` : ""}
        ${job.status === "completed" && !job.is_stale && !job.is_final ? `<button type="button" class="primary-action" data-action="approve-generation" data-generation-id="${escapeHtml(job.generation_id)}">设为最终版本</button>` : ""}
      </div>
    </article>
  `;
}

function renderGenerationReadinessIssues(title, issues, kind) {
  const items = Array.isArray(issues) ? issues : [];
  if (!items.length) return "";
  return `
    <section class="generation-readiness-issues ${escapeHtml(kind)}">
      <strong>${escapeHtml(title)} · ${items.length}</strong>
      <div>
        ${items.map((item) => `
          <div>
            <span><b>${escapeHtml(item.label || targetFieldLabel(item.field))}</b>${escapeHtml(item.reason || "")}</span>
            ${canFocusGenerationIssue(item.field) ? `<button type="button" class="secondary-action" data-role="focus-generation-field" data-field="${escapeHtml(item.field)}">去处理</button>` : ""}
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function canFocusGenerationIssue(field) {
  const target = String(field || "");
  return Boolean(target) && !target.startsWith("technical_requirements.");
}

function generationSourceParameter(parameters, field) {
  if (field === "mean_diameter") {
    const direct = rawGenerationParameter(parameters, "mean_diameter");
    if (direct) return direct;
    const wire = rawGenerationParameter(parameters, "wire_diameter");
    if (!wire || !Number.isFinite(Number(wire.value))) return null;
    for (const diameterField of ["outer_diameter", "inner_diameter"]) {
      const diameter = rawGenerationParameter(parameters, diameterField);
      if (!diameter || !Number.isFinite(Number(diameter.value))) continue;
      const value = diameterField === "outer_diameter"
        ? Number(diameter.value) - Number(wire.value)
        : Number(diameter.value) + Number(wire.value);
      return {
        value: Number(value.toFixed(3)),
        unit: "mm",
        source: ["derived", `${diameterField}_and_wire_diameter`],
        source_fields: [diameterField, "wire_diameter"],
        formula: diameterField === "outer_diameter"
          ? "outer_diameter - wire_diameter"
          : "inner_diameter + wire_diameter",
        need_human_review: Boolean(diameter.need_human_review || wire.need_human_review),
      };
    }
    return null;
  }
  if (field === "end_coils_closed") {
    const direct = parameters?.end_coils_closed;
    if (direct && typeof direct === "object" && direct.value != null && direct.value !== "") return direct;
    const legacy = parameters?.end_type;
    if (legacy && typeof legacy === "object" && legacy.value != null && legacy.value !== "") return legacy;
    return null;
  }
  return rawGenerationParameter(parameters, field);
}

function rawGenerationParameter(parameters, field) {
  const item = parameters?.[field];
  return item && typeof item === "object" && item.value != null && item.value !== "" ? item : null;
}

function generationContractValue(field, rawValue) {
  if (["wire_diameter", "mean_diameter", "free_length"].includes(field)) {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value <= 0) throw new Error(`${targetFieldLabel(field)}必须大于 0`);
    return Number(value.toFixed(3));
  }
  if (["total_coils", "active_coils"].includes(field)) {
    const value = Number(rawValue);
    if (!Number.isInteger(value) || value <= 0) throw new Error(`${targetFieldLabel(field)}必须是正整数`);
    return value;
  }
  const text = String(rawValue ?? "").trim();
  const normalized = text.toLowerCase().replaceAll("-", "_").replaceAll(" ", "");
  if (field === "handedness") {
    if (["right", "right_hand", "r", "右旋"].includes(normalized)) return "right";
    if (["left", "left_hand", "l", "左旋"].includes(normalized)) return "left";
    throw new Error("旋向只能是 right 或 left");
  }
  if (field === "end_grinding") {
    if (["1", "true", "ground", "grounded", "closed_and_ground"].includes(normalized)) return 1;
    if (["0", "false", "not_ground", "notground", "unground", "ungrounded"].includes(normalized)) return 0;
    if (text.includes("不磨") || text.includes("未磨")) return 0;
    if (text.includes("磨削") || text.includes("磨平")) return 1;
    throw new Error("两端磨削只能是 0 或 1");
  }
  if (field === "end_coils_closed") {
    if (["1", "true", "tight", "closed", "closed_end", "closed_and_ground", "closed_and_unground"].includes(normalized)) return 1;
    if (["0", "false", "not_tight", "nottight", "open", "open_end"].includes(normalized)) return 0;
    if (text.includes("不并紧") || text.includes("不压并") || text.includes("开口") || text.includes("开放")) return 0;
    if (text.includes("并紧") || text.includes("压并") || text.includes("闭口") || text.includes("闭合")) return 1;
    throw new Error("端圈压并只能是 0 或 1");
  }
  throw new Error(`不支持的生图字段：${field}`);
}

function generationContractState(parameters, field) {
  const item = generationSourceParameter(parameters, field);
  if (!item) return "missing";
  if (item.need_human_review) return "pending";
  try {
    generationContractValue(field, item.value);
    return "confirmed";
  } catch {
    return "invalid";
  }
}

function applyGenerationDefaults(review) {
  if (currentSpringType(review) !== "compression_spring") return [];
  review.spring_parameters ||= {};
  const applied = [];
  Object.entries(COMPRESSION_GENERATION_DEFAULTS).forEach(([field, value]) => {
    if (generationSourceParameter(review.spring_parameters, field)) return;
    const internalField = field === "end_coils_closed" ? "end_type" : field;
    const internalValue = field === "end_coils_closed"
      ? "两端并紧"
      : field === "end_grinding"
        ? "两端磨削"
        : value;
    review.spring_parameters[internalField] = {
      ...(review.spring_parameters[internalField] || {}),
      value: internalValue,
      unit: COMPRESSION_GENERATION_UNITS[field],
      source: ["solidworks_protocol_default"],
      default_source: "spring_generation_parameters/v1",
      need_human_review: true,
    };
    applied.push(field);
  });
  review.generation_defaulted_fields = Array.from(new Set([...(review.generation_defaulted_fields || []), ...applied]));
  return applied;
}

function assessGenerationReadiness(review) {
  if (currentSpringType(review) !== "compression_spring") {
    return {
      status: "not_applicable",
      summary: "当前仅对圆柱螺旋压缩弹簧生成参数包。",
      missing_fields: [],
      pending_fields: [],
      warnings: [],
      confirmed_core_count: 0,
      core_field_count: 0,
    };
  }
  applyGenerationDefaults(review);
  const parameters = review.spring_parameters || {};
  const reasonableness = review.parameter_reasonableness || {};
  const reasonablenessStale = Boolean(review.parameter_reasonableness_stale);
  const missing = [];
  const pending = [];
  const warnings = [];
  let confirmed = 0;
  const contractIssues = [];
  COMPRESSION_GENERATION_CORE_FIELDS.forEach((field) => {
    const state = generationContractState(parameters, field);
    if (state === "missing") missing.push(generationIssue(field, "缺少重新生图所需的核心参数。"));
    else if (state === "pending") pending.push(generationIssue(field, "参数已有值，但仍需人工确认。"));
    else if (state === "invalid") {
      try {
        generationContractValue(field, generationSourceParameter(parameters, field)?.value);
      } catch (error) {
        contractIssues.push(generationIssue(field, error.message || String(error)));
      }
    }
    else confirmed += 1;
  });
  if (generationContractState(parameters, "wire_diameter") === "confirmed" && generationContractState(parameters, "mean_diameter") === "confirmed") {
    const wire = generationContractValue("wire_diameter", generationSourceParameter(parameters, "wire_diameter").value);
    const mean = generationContractValue("mean_diameter", generationSourceParameter(parameters, "mean_diameter").value);
    if (mean <= wire) contractIssues.push(generationIssue("mean_diameter", "中径必须大于线径，确保计算内径大于零。"));
  }
  if (generationContractState(parameters, "total_coils") === "confirmed" && generationContractState(parameters, "active_coils") === "confirmed") {
    const total = generationContractValue("total_coils", generationSourceParameter(parameters, "total_coils").value);
    const active = generationContractValue("active_coils", generationSourceParameter(parameters, "active_coils").value);
    if (active > total) contractIssues.push(generationIssue("active_coils", "有效圈数不能大于总圈数。"));
  }
  const selection = review.standard_selection || {};
  if (!selection.selected_standard) {
    warnings.push(generationIssue("standard_no", "未执行或未完成标准化检查；本次可按当前人工确认参数直接生图。"));
  } else if (!selection.human_confirmed) {
    warnings.push(generationIssue("standard_no", "适用技术标准尚未人工确认；本次可按当前人工确认参数直接生图。"));
  }
  if (review.derived_parameters_stale) {
    warnings.push(generationIssue("standardization", "参数修改后标准化结果已过期；本次可按当前人工确认参数直接生图。", "标准化结果"));
  }
  for (const item of review.standardization_results || []) {
    if (!item || typeof item !== "object") continue;
    if (["stale", "need_context"].includes(item.status)) {
      warnings.push(generationIssue(item.target_field || "standardization", item.basis || "标准化结果仍需补充或重新计算；可按当前人工确认参数直接生图。"));
    } else if (item.status === "not_applicable") {
      warnings.push(generationIssue(item.target_field || "standardization", item.basis || "当前标准规则不适用，需作为特殊设计复核。"));
    } else if (["suggested", "llm_suggested", "rules_pending", "unmapped"].includes(item.status) || item.need_human_review) {
      warnings.push(generationIssue(item.target_field || "standardization", item.basis || "标准化建议尚未处理；未应用的建议不会进入生图参数包。"));
    }
  }
  if (reasonablenessStale) {
    warnings.push(generationIssue("reasonableness", "参数合理性结果待服务端重新计算；创建任务前服务端会使用当前参数重新核对。", "参数合理性"));
  }
  (review.technical_requirements || []).forEach((item, index) => {
    if (!item?.content || !item.need_human_review) return;
    const label = TECH_LABELS[item.type] || item.type || "技术要求";
    pending.push(generationIssue(`technical_requirements.${index + 1}`, `技术要求“${label}”尚未人工确认。`, label));
  });
  const status = (!reasonablenessStale && reasonableness.status === "blocked") || contractIssues.length
    ? "blocked"
    : missing.length ? "needs_input" : pending.length ? "needs_confirmation" : warnings.length ? "ready_with_warnings" : "ready";
  const summary = status === "blocked"
    ? (contractIssues[0]?.reason || reasonableness.summary || "存在无法直接采用的参数矛盾。")
    : status === "ready"
    ? "核心参数和技术要求均已确认，可生成参数包。"
    : status === "ready_with_warnings"
      ? "参数包可以生成，但存在需要在生图前知悉的风险提示。"
      : status === "needs_input"
        ? `还缺少 ${missing.length} 项生成必填信息。`
        : `核心尺寸已齐，但还有 ${pending.length} 项需要人工确认。`;
  return {
    status,
    summary,
    missing_fields: dedupeGenerationIssues(missing),
    pending_fields: dedupeGenerationIssues(pending),
    warnings: dedupeGenerationIssues(warnings),
    confirmed_core_count: confirmed,
    core_field_count: COMPRESSION_GENERATION_CORE_FIELDS.length,
    defaulted_fields: review.generation_defaulted_fields || [],
    parameter_reasonableness: reasonableness,
    blocking_reasonableness: contractIssues,
  };
}

function generationParameterState(param) {
  if (!param || typeof param !== "object" || param.value == null || param.value === "") return "missing";
  return param.need_human_review ? "pending" : "confirmed";
}

function generationIssue(field, reason, label = null) {
  return { field, label: label || targetFieldLabel(field), reason };
}

function dedupeGenerationIssues(issues) {
  const seen = new Set();
  return issues.filter((item) => {
    const key = `${item.field}:${item.reason}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderStandardizationHtml(review) {
  const results = Array.isArray(review.standardization_results) ? review.standardization_results : [];
  const batchPlan = standardizationBatchPlan(review);
  const canUndo = Boolean(lastStandardizationApplyHistory(review));
  const staleCount = results.filter((item) => item.status === "stale").length;
  if (!results.length) {
    const selection = review.standard_selection || {};
    const standard = selection.selected_standard || "未选择";
    const reason = selection.reason || "当前缺少可用于生成标准化建议的条件。";
    const statusText = selection.status === "rules_pending"
      ? "已完成标准选择，正在等待热卷规则或 RAG/LLM 待确认建议。"
      : selection.status === "not_applicable"
        ? "当前标准不适用于已接入的圆柱螺旋压缩弹簧规则。"
        : "尚未生成可应用的标准化建议。";
    return `
      <section class="review-block">
        <div class="block-head"><h2>标准化建议</h2><span>0 项</span></div>
        <div class="empty-line">
          <strong>${escapeHtml(statusText)}</strong>
          <span>适用标准：${escapeHtml(standard)}</span>
          <small>${escapeHtml(reason)}</small>
        </div>
      </section>
    `;
  }
  return `
    <section class="review-block">
      <div class="block-head"><h2>标准化建议</h2><span>${results.length} 项</span></div>
      <div class="standardization-toolbar">
        <span>${staleCount ? `参数已修改，${staleCount} 项建议已过期，请重新标准化` : (batchPlan.items.length ? `可一键应用 ${batchPlan.items.length} 项建议` : "暂无可批量应用的建议")}${batchPlan.conflicts.length ? `；${batchPlan.conflicts.length} 个字段存在多方案` : ""}</span>
        <div>
          <button type="button" data-action="apply-standardization-batch" ${batchPlan.items.length ? "" : "disabled"}>应用全部可用建议</button>
          <button type="button" class="secondary-action" data-action="undo-standardization-batch" ${canUndo ? "" : "disabled"}>撤销上次应用</button>
        </div>
      </div>
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
            <button type="button" data-role="confirm-standard" ${canConfirmStandardization(item) ? "" : "disabled"}>${item.status === "human_confirmed" ? "已应用" : "确认建议"}</button>
            ${renderStandardizationResultReferencesHtml(item)}
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function standardizationReferences(item) {
  const metadata = item?.metadata || {};
  const references = metadata.rag_references || metadata.standard_references || [];
  return Array.isArray(references) ? references.filter((reference) => reference && typeof reference === "object") : [];
}

function renderStandardizationResultReferencesHtml(item) {
  const references = standardizationReferences(item);
  if (!references.length) return "";
  return `
    <div class="standardization-result-references">
      ${references.map((reference) => `<small title="${escapeHtml(referenceDetailLabel(reference))}">${escapeHtml(referenceSummaryLabel(reference))}</small>`).join("")}
    </div>
  `;
}

function referenceSummaryLabel(reference) {
  const source = reference.source === "ragflow" ? "RAGFlow" : "本地知识兜底";
  const documentName = reference.document_name || reference.title || "标准资料";
  const tableNo = reference.table_no || reference.metadata?.table_no;
  const status = reference.status === "fallback" ? "已降级" : "";
  return [source, documentName, tableNo, status].filter(Boolean).join(" · ");
}

function referenceDetailLabel(reference) {
  const positions = Array.isArray(reference.positions) ? reference.positions : [];
  const firstPosition = Array.isArray(positions[0]) ? positions[0][0] : null;
  const score = reference.similarity ?? reference.score;
  const details = [
    reference.dataset_name ? `知识库：${reference.dataset_name}` : "",
    reference.document_name ? `文件：${reference.document_name}` : "",
    reference.standard_no ? `标准：${reference.standard_no}` : "",
    reference.chunk_id ? `分块：${reference.chunk_id}` : "",
    firstPosition != null ? `页码：${firstPosition}` : "",
    Number.isFinite(Number(score)) ? `相似度：${Math.round(Number(score) * 100)}%` : "",
    reference.retrieval_reason ? `状态：${reference.retrieval_reason}` : "",
  ];
  return details.filter(Boolean).join("；");
}

function standardizationBatchPlan(review) {
  const groups = new Map();
  (review?.standardization_results || []).forEach((item, index) => {
    if (!canConfirmStandardization(item)) return;
    const target = String(item.target_field || "").trim();
    if (!target) return;
    const group = groups.get(target) || [];
    group.push({ item, index });
    groups.set(target, group);
  });
  const items = [];
  const conflicts = [];
  groups.forEach((group, target) => {
    if (group.length === 1) {
      items.push(group[0]);
    } else {
      conflicts.push({ target, label: targetFieldLabel(target), count: group.length });
    }
  });
  return { items, conflicts };
}

function lastStandardizationApplyHistory(review) {
  const history = review?.standardization_apply_history || [];
  return history.length ? history[history.length - 1] : null;
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
      ${isGenerating ? "" : renderStandardizationChatReferencesHtml(turn)}
      ${isGenerating ? "" : renderStandardizationChatActionsHtml(turn, turnIndex)}
    </div>
  `;
  }).join("");
  const chatBusyAttr = state.standardizationChatBusy ? "disabled" : "";
  return `
    <section class="review-block standardization-chat-block">
      <div class="block-head"><h2>标准化对话</h2><span>${turns.length} 轮</span></div>
      <div class="standardization-chat-list">
        ${rows || `<div class="standardization-chat-empty">直接输入“请根据标准化手册推荐完整标准化方案”，或提出参数、公差调整需求；我会按当前参数自动准备标准化依据。</div>`}
      </div>
      <form class="standardization-chat-form" data-action="standardization-chat">
        <input data-role="standardization-chat-input" type="text" placeholder="直接要求按手册标准化，或修改参数...">
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
  if (turn.standardization_context?.status === "refreshed") {
    parts.push("已按当前参数更新标准化");
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

function renderStandardizationChatReferencesHtml(turn) {
  const references = Array.isArray(turn?.references) ? turn.references.filter((item) => item && typeof item === "object") : [];
  if (!references.length) return "";
  const sourceLabel = turn?.llm_chat?.status === "generated" ? "LLM/RAG 检索依据" : "标准依据";
  return `
    <details class="standardization-chat-references">
      <summary>${escapeHtml(`${sourceLabel} · ${references.length} 条`)}</summary>
      <ul>
        ${references.map((reference) => {
          const title = reference.title || reference.rule_topic || reference.table_no || reference.chunk_id || "标准资料";
          const parts = [reference.standard_no, reference.table_no, reference.rule_topic]
            .filter(Boolean)
            .map((item) => String(item));
          const detail = referenceDetailLabel(reference);
          const summary = referenceSummaryLabel(reference);
          return `<li title="${escapeHtml(detail)}"><strong>${escapeHtml(title)}</strong><span>${escapeHtml([summary, ...parts].filter(Boolean).join(" · "))}</span></li>`;
        }).join("")}
      </ul>
    </details>
  `;
}

function renderStandardizationChatActionsHtml(turn, turnIndex) {
  const actions = Array.isArray(turn.suggested_actions) ? turn.suggested_actions : [];
  if (turn?.generation_package_export) {
    return `
      <div class="standardization-chat-actions">
        ${renderGenerationPackageExportHtml(turn.generation_package_export, turnIndex)}
      </div>
    `;
  }
  if (turn?.accuracy_standardization?.status === "completed") {
    return `
      <div class="standardization-chat-actions">
        ${renderAccuracyStandardizationResultHtml(turn.accuracy_standardization, turn.standardization_batch, turnIndex)}
      </div>
    `;
  }
  if (turn?.standardization_batch) {
    return `
      <div class="standardization-chat-actions">
        ${renderChatStandardizationBatchHtml(turn.standardization_batch, turnIndex)}
      </div>
    `;
  }
  const proposal = currentParameterChangeProposal(turn);
  if (proposal) {
    return `
      <div class="standardization-chat-actions">
        ${renderStandardizationChatRollbackHtml(turn, turnIndex)}
        ${renderParameterChangeProposalHtml(proposal, turnIndex)}
      </div>
    `;
  }
  if (!actions.length) return "";
  const indexedActions = actions.map((action, actionIndex) => ({ action, actionIndex }));
  const supplementActions = indexedActions.filter(({ action }) => canBatchSupplementChatAction(action));
  const visibleActions = indexedActions.filter(({ action }) => action?.type !== "request_missing_field");
  return `
    <div class="standardization-chat-actions">
      ${renderStandardizationChatRollbackHtml(turn, turnIndex)}
      ${supplementActions.length ? renderStandardizationChatSupplementFormHtml(supplementActions, turnIndex) : ""}
      ${renderStandardizationChatBatchHtml(turn, turnIndex)}
      ${visibleActions.map(({ action, actionIndex }) => renderStandardizationChatActionHtml(action, turnIndex, actionIndex)).join("")}
    </div>
  `;
}

function generationPackageExportBaseline(review = state.review) {
  const parameters = review?.spring_parameters || {};
  return {
    spring_type: review?.drawing_summary?.spring_type ?? null,
    parameter_fields: COMPRESSION_GENERATION_CORE_FIELDS.map((field) => {
      const item = generationSourceParameter(parameters, field);
      return {
        field,
        value: item?.value ?? null,
        unit: item?.unit ?? null,
        tolerance_upper: item?.tolerance_upper ?? null,
        tolerance_lower: item?.tolerance_lower ?? null,
        need_human_review: Boolean(item?.need_human_review ?? true),
      };
    }),
    technical_requirements: (review?.technical_requirements || [])
      .filter((item) => item && typeof item === "object" && item.content)
      .map((item) => ({
        type: item.type ?? null,
        content: item.content ?? null,
        need_human_review: Boolean(item.need_human_review ?? true),
        confirmation_source: item.confirmation_source ?? null,
      })),
  };
}

function generationPackageExportDisplayStatus(action, review = state.review) {
  const clientStatus = String(action?.download_status || "");
  if (clientStatus === "stale") return "stale";
  if (action?.source_mode === "server") {
    const expected = Number(action?.review_revision);
    const current = Number(state.lastJob?.review_revision);
    if (Number.isFinite(expected) && Number.isFinite(current) && expected !== current) return "stale";
  }
  if (action?.baseline_state && review
    && JSON.stringify(action.baseline_state) !== JSON.stringify(generationPackageExportBaseline(review))) return "stale";
  return clientStatus || (action?.can_download ? "pending" : "blocked");
}

function generationPackageExportIssueField(issue) {
  if (issue?.field) return String(issue.field);
  if (Array.isArray(issue?.fields) && issue.fields.length) return String(issue.fields[0]);
  return "";
}

function generationPackageExportIssueText(issue) {
  if (typeof issue === "string") return issue;
  return String(issue?.reason || issue?.message || issue?.summary || "需要进一步处理");
}

function renderGenerationPackageExportIssuesHtml(title, items, kind, turnIndex) {
  const issues = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!issues.length) return "";
  return `
    <section class="generation-package-export-issues ${escapeHtml(kind)}">
      <strong>${escapeHtml(title)} · ${issues.length}</strong>
      <div>
        ${issues.map((issue) => {
          const field = generationPackageExportIssueField(issue);
          const label = typeof issue === "object" ? (issue.label || targetFieldLabel(field)) : "提示";
          return `
            <div>
              <span><b>${escapeHtml(label || "提示")}</b>${escapeHtml(generationPackageExportIssueText(issue))}</span>
              ${field ? `<button type="button" class="secondary-action" data-role="focus-generation-package-issue" data-turn-index="${turnIndex}" data-field="${escapeHtml(field)}">去处理</button>` : ""}
            </div>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

function renderGenerationPackageExportHtml(action, turnIndex) {
  const status = generationPackageExportDisplayStatus(action);
  const fields = Array.isArray(action?.parameter_fields) ? action.parameter_fields : [];
  const statusLabels = {
    pending: ["参数包可以导出", "等待浏览器开始下载"],
    downloading: ["正在导出参数包", "正在从可信来源读取最新JSON"],
    downloaded: ["参数包已导出", action?.downloaded_at ? `下载时间 ${new Date(action.downloaded_at).toLocaleString("zh-CN")}` : "可随时重新下载"],
    failed: ["自动下载未完成", action?.failure_reason || "请点击下方按钮重新下载"],
    stale: ["导出结果已过期", "参数或审图修订已经变化，请重新发送“导出参数包”"],
    blocked: ["暂时不能导出", "请先处理下列缺失、待确认或阻断问题"],
  };
  const [title, subtitle] = statusLabels[status] || statusLabels.blocked;
  const canDownload = Boolean(action?.can_download) && !["stale", "downloading"].includes(status);
  const buttonLabel = status === "downloaded" ? "重新下载" : status === "failed" ? "重新尝试" : "下载参数包";
  const sourceLabel = action?.source_mode === "server" ? "正式审图 · 服务端冻结参数包" : "本地JSON · 本地白名单导出";
  return `
    <section class="generation-package-export-card ${escapeHtml(status)}" data-kind="generation_package_export" data-turn-index="${turnIndex}">
      <div class="generation-package-export-head">
        <div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(subtitle)}</small></div>
        <span>${escapeHtml(action?.schema_version || "spring_generation_parameters/v1")}</span>
      </div>
      <p class="generation-package-export-source">${escapeHtml(sourceLabel)}</p>
      ${fields.length ? `
        <div class="generation-package-export-fields">
          ${fields.map((item) => `<span><b>${escapeHtml(FIELD_LABELS[item.field] || item.label || item.field || "参数")}</b>${escapeHtml(formatStandardValue(item.value, item.unit || ""))}</span>`).join("")}
        </div>
      ` : ""}
      ${renderGenerationPackageExportIssuesHtml("警告", action?.warnings, "warning", turnIndex)}
      ${renderGenerationPackageExportIssuesHtml("缺失项", action?.missing_fields, "missing", turnIndex)}
      ${renderGenerationPackageExportIssuesHtml("待确认项", action?.pending_fields, "pending", turnIndex)}
      ${renderGenerationPackageExportIssuesHtml("阻断问题", action?.blocking_reasonableness, "blocked", turnIndex)}
      <div class="generation-package-export-actions">
        <button type="button" data-role="download-generation-package" data-turn-index="${turnIndex}" ${canDownload ? "" : "disabled"}>${escapeHtml(buttonLabel)}</button>
        <small>仅下载JSON，不会创建生图任务。</small>
      </div>
    </section>
  `;
}

function updateGenerationPackageExportAction(turnIndex, patch, messageId = state.activeReviewMessageId) {
  const action = state.review?.standardization_chat?.[turnIndex]?.generation_package_export;
  if (!action) return null;
  Object.assign(action, patch);
  const context = getReviewContext(messageId);
  if (context) context.review = state.review;
  refreshReviewSurfaces({ scrollChat: true });
  return action;
}

async function executeGenerationPackageExport(action, turnIndex, messageId = state.activeReviewMessageId, options = {}) {
  if (!action || !state.review) return false;
  if (messageId) activateReviewContext(messageId, {
    preserveAccuracyGradeUpdate: true,
    preservePendingAccuracyGrade: true,
  });
  const liveAction = state.review?.standardization_chat?.[turnIndex]?.generation_package_export || action;
  if (!liveAction.can_download) return false;
  if (generationPackageExportDisplayStatus(liveAction) === "stale") {
    updateGenerationPackageExportAction(turnIndex, {
      download_status: "stale",
      failure_reason: "参数或审图修订已经变化，请重新发送导出指令。",
    }, messageId);
    return false;
  }
  updateGenerationPackageExportAction(turnIndex, { download_status: "downloading", failure_reason: "" }, messageId);
  try {
    let parameterPackage;
    if (liveAction.source_mode === "server") {
      if (!state.lastJob?.job_id) throw new Error("找不到正式审图任务，无法读取服务端参数包。");
      const response = await apiFetch(`/api/reviews/${encodeURIComponent(state.lastJob.job_id)}/generation-package`);
      const payload = await response.json();
      if (!response.ok) {
        const detail = payload?.detail;
        const error = new Error(
          detail?.message
          || detail?.summary
          || detail?.generation_readiness?.summary
          || (typeof detail === "string" ? detail : "服务端参数包读取失败。"),
        );
        if (response.status === 409) error.code = "generation_package_export_stale";
        throw error;
      }
      const expectedRevision = Number(liveAction.review_revision);
      const returnedRevision = Number(payload.review_revision);
      if (Number.isFinite(expectedRevision) && Number.isFinite(returnedRevision) && expectedRevision !== returnedRevision) {
        const error = new Error("审图修订已经变化，请重新发送导出指令。");
        error.code = "generation_package_export_stale";
        throw error;
      }
      parameterPackage = payload.parameter_package;
    } else {
      if (generationPackageExportDisplayStatus(liveAction) === "stale") {
        const error = new Error("本地参数已经变化，请重新发送导出指令。");
        error.code = "generation_package_export_stale";
        throw error;
      }
      const readiness = assessGenerationReadiness(state.review);
      if (!["ready", "ready_with_warnings"].includes(readiness.status)) {
        const error = new Error(readiness.summary || "当前参数暂时不能导出。");
        error.code = "generation_package_export_stale";
        throw error;
      }
      parameterPackage = makeGenerationParameterPackage(state.review);
    }
    if (!parameterPackage || typeof parameterPackage !== "object") throw new Error("参数包响应为空，未触发下载。");
    downloadJson(parameterPackage, liveAction.filename || "compression_spring_generation_parameters.json");
    updateGenerationPackageExportAction(turnIndex, {
      download_status: "downloaded",
      downloaded_at: new Date().toISOString(),
      failure_reason: "",
      automatic_download: false,
    }, messageId);
    return true;
  } catch (error) {
    const stale = error?.code === "generation_package_export_stale";
    updateGenerationPackageExportAction(turnIndex, {
      download_status: stale ? "stale" : "failed",
      failure_reason: error?.message || String(error),
      automatic_download: false,
    }, messageId);
    if (!options.automatic) updateLatestReviewMessage(error?.message || "参数包下载失败，请重试。");
    return false;
  }
}

function renderAccuracyStandardizationResultHtml(result, batch = null, turnIndex = -1) {
  const specializedLabels = {
    diameter_accuracy_grade: "直径精度等级",
    free_length_accuracy_grade: "自由高度精度等级",
    load_accuracy_grade: "载荷精度等级",
    stiffness_accuracy_grade: "刚度精度等级",
  };
  const retained = Object.entries(result?.specialized_grades_retained || {});
  const warnings = Array.isArray(result?.warnings) ? result.warnings.filter(Boolean) : [];
  const previous = result?.previous_grade || "未设置";
  const requested = result?.requested_grade || "-";
  const resultCount = Number(result?.standardization_result_count || 0);
  return `
    <section class="accuracy-standardization-result" data-kind="accuracy_standardization_result">
      <div class="accuracy-standardization-result-head">
        <div>
          <strong>精度标准化已完成</strong>
          <small>通用精度等级</small>
        </div>
        <span>${escapeHtml(previous)} → ${escapeHtml(requested)}</span>
      </div>
      <p>已按通用精度等级 ${escapeHtml(requested)} 重新生成 ${resultCount} 项标准化建议，建议尚未自动应用。</p>
      ${retained.length ? `
        <div class="accuracy-standardization-retained">
          <strong>以下专项精度保持不变并继续优先</strong>
          <ul>${retained.map(([field, grade]) => `<li><span>${escapeHtml(specializedLabels[field] || targetFieldLabel(field))}</span><b>${escapeHtml(grade)}</b></li>`).join("")}</ul>
        </div>
      ` : ""}
      ${warnings.length ? `<div class="accuracy-standardization-warnings"><strong>提示</strong><ul>${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : ""}
      ${batch ? renderChatStandardizationBatchHtml(batch, turnIndex) : `<small>请在标准化建议区域逐项核对，或使用现有批量应用操作。</small>`}
    </section>
  `;
}

function standardizationBatchDisplayStatus(batch, currentRevision = state.lastJob?.review_revision) {
  const status = String(batch?.status || "");
  if (status === "applied" || status === "no_changes" || status === "stale") return status;
  const hasBatchRevision = batch?.review_revision !== null && batch?.review_revision !== undefined && batch?.review_revision !== "";
  const hasActiveRevision = currentRevision !== null && currentRevision !== undefined && currentRevision !== "";
  const batchRevision = Number(batch?.review_revision);
  const activeRevision = Number(currentRevision);
  if (hasBatchRevision && hasActiveRevision && Number.isFinite(batchRevision) && Number.isFinite(activeRevision) && batchRevision !== activeRevision) {
    return "stale";
  }
  return status === "ready" ? "ready" : "no_changes";
}

function formatStandardizationBatchValue(snapshot, fallbackUnit = "") {
  const value = snapshot?.value;
  const unit = snapshot?.unit || fallbackUnit || "";
  const valueText = value == null || value === "" ? "未填写" : formatStandardValue(value, unit);
  const upper = snapshot?.tolerance_upper;
  const lower = snapshot?.tolerance_lower;
  const toleranceText = upper == null && lower == null
    ? ""
    : `，公差 ${formatTolerancePair({ upper, lower }, unit)}`;
  const confirmationText = snapshot?.confirmed ? "" : "（待确认）";
  return `${valueText}${toleranceText}${confirmationText}`;
}

function renderChatStandardizationBatchHtml(batch, turnIndex) {
  const status = standardizationBatchDisplayStatus(batch);
  const items = Array.isArray(batch?.items) ? batch.items.filter((item) => item?.can_apply !== false) : [];
  const skipped = Array.isArray(batch?.skipped_items) ? batch.skipped_items : [];
  const appliedCount = Number(batch?.applied_count || 0);
  const buttonLabel = status === "applied"
    ? `已应用 ${appliedCount || items.length} 项`
    : status === "stale"
      ? "结果已过期"
      : status === "no_changes"
        ? "无需应用"
        : `应用全部${items.length ? ` · ${items.length}` : ""}`;
  const disabled = status !== "ready" || !items.length;
  return `
    <section class="chat-standardization-batch ${escapeHtml(status)}" data-kind="chat_standardization_batch" data-turn-index="${turnIndex}" data-batch-id="${escapeHtml(batch?.batch_id || "")}">
      <div class="chat-standardization-batch-head">
        <div>
          <strong>本次标准化修改</strong>
          <small>${status === "stale" ? "正式参数或审图修订已经变化，请重新标准化" : (items.length ? `可应用 ${items.length} 项${skipped.length ? `，跳过 ${skipped.length} 项` : ""}` : "当前参数已经符合本次标准化结果")}</small>
        </div>
        <button type="button" data-role="apply-chat-standardization-batch" ${disabled ? "disabled" : ""}>${escapeHtml(buttonLabel)}</button>
      </div>
      ${items.length ? `
        <div class="chat-standardization-batch-list">
          ${items.map((item) => `
            <article class="chat-standardization-batch-item">
              <strong>${escapeHtml(item.label || targetFieldLabel(item.target_field))}</strong>
              <div><span>当前</span><b>${escapeHtml(formatStandardizationBatchValue(item.before, item.unit))}</b></div>
              <div><span>标准化后</span><b>${escapeHtml(formatStandardizationBatchValue(item.after, item.unit))}</b></div>
              ${item.basis ? `<details><summary>查看标准依据</summary><p>${escapeHtml(item.basis)}</p></details>` : ""}
            </article>
          `).join("")}
        </div>
      ` : ""}
      ${skipped.length ? `
        <details class="chat-standardization-batch-skipped">
          <summary>查看跳过的 ${skipped.length} 项</summary>
          <ul>${skipped.map((item) => `<li><strong>${escapeHtml(item.label || targetFieldLabel(item.target_field))}</strong><span>${escapeHtml(item.reason || "当前结果不能安全应用")}</span></li>`).join("")}</ul>
        </details>
      ` : ""}
    </section>
  `;
}

function currentParameterChangeProposal(turn) {
  const snapshot = turn?.change_proposal;
  if (!snapshot?.proposal_id) return null;
  const current = (state.review?.parameter_change_proposals || []).find((item) => {
    return String(item?.proposal_id || "") === String(snapshot.proposal_id);
  });
  if (!current) return snapshot;
  if (Number(current.version) === Number(snapshot.version)) return current;
  return {
    ...snapshot,
    status: "stale",
    summary: `此版本已由方案 V${current.version} 替代，仅保留用于查看历史。`,
  };
}

function renderParameterChangeProposalHtml(proposal, turnIndex) {
  const status = String(proposal?.status || "needs_input");
  const direct = Array.isArray(proposal?.direct_changes) ? proposal.direct_changes : [];
  const synchronized = Array.isArray(proposal?.synchronized_changes) ? proposal.synchronized_changes : [];
  const derived = Array.isArray(proposal?.derived_changes) ? proposal.derived_changes : [];
  const questions = Array.isArray(proposal?.clarifying_questions) ? proposal.clarifying_questions : [];
  const blocking = Array.isArray(proposal?.blocking_issues) ? proposal.blocking_issues : [];
  const introduced = Array.isArray(proposal?.risk_delta?.introduced) ? proposal.risk_delta.introduced : [];
  const recommendations = Array.isArray(proposal?.recommendations) ? proposal.recommendations : [];
  const constraints = Array.isArray(proposal?.constraints) ? proposal.constraints : [];
  const readiness = proposal?.generation_readiness || {};
  const canApply = ["ready", "warning"].includes(status) && Boolean(state.lastJob?.job_id);
  const canDiscard = !["applied", "discarded"].includes(status) && Boolean(state.lastJob?.job_id);
  const statusLabels = {
    needs_input: "需要补充",
    ready: "可以应用",
    warning: "有风险",
    blocked: "不可应用",
    stale: "方案已过期",
    applied: "已应用",
    discarded: "已放弃",
  };
  const applyLabel = status === "warning" ? "仍然应用方案" : (status === "applied" ? "方案已应用" : "应用整个方案");
  const readinessText = readiness.before_status || readiness.after_status
    ? `生图状态 ${generationReadinessStatusLabel(readiness.before_status)} → ${generationReadinessStatusLabel(readiness.after_status)}`
    : "";
  return `
    <section class="parameter-change-proposal ${escapeHtml(status)}" data-kind="parameter_change_proposal"
      data-turn-index="${turnIndex}" data-proposal-id="${escapeHtml(proposal.proposal_id || "")}" data-proposal-version="${escapeHtml(String(proposal.version || ""))}">
      <div class="parameter-change-proposal-head">
        <div>
          <strong>参数修改方案 V${escapeHtml(String(proposal.version || 1))}</strong>
          <small>${escapeHtml(statusLabels[status] || status)}</small>
        </div>
        ${readinessText ? `<span>${escapeHtml(readinessText)}</span>` : ""}
      </div>
      <p>${escapeHtml(proposal.summary || "方案计算完成。")}</p>
      ${renderParameterProposalMessages("用户约束", constraints.map((item) => item.description || `${FIELD_LABELS[item.target_field] || targetFieldLabel(item.target_field)}约束`))}
      ${renderParameterProposalChangeGroup("用户直接修改", direct)}
      ${renderParameterProposalChangeGroup("自动同步参数", synchronized)}
      ${renderParameterProposalChangeGroup("计算影响", derived)}
      ${renderParameterProposalMessages("需要补充", questions)}
      ${renderParameterProposalIssues("阻断问题", blocking)}
      ${renderParameterProposalIssues("风险提示", introduced)}
      ${renderParameterProposalRecommendations(recommendations)}
      ${proposal?.generation_readiness?.parameter_package_changed
        ? `<div class="parameter-change-proposal-effect">SolidWorks参数包将变化；已有生图版本不会覆盖，应用后需要创建新版本。</div>`
        : `<div class="parameter-change-proposal-effect">当前方案不会改变SolidWorks冻结建模参数。</div>`}
      ${!state.lastJob?.job_id ? `<small class="parameter-change-proposal-local">本地未持久化数据只能预览方案，不能整体应用。</small>` : ""}
      <div class="parameter-change-proposal-actions">
        <button type="button" data-role="apply-parameter-change-proposal" ${canApply ? "" : "disabled"}>${escapeHtml(applyLabel)}</button>
        <button type="button" class="secondary-action" data-role="discard-parameter-change-proposal" ${canDiscard ? "" : "disabled"}>放弃方案</button>
      </div>
      ${["needs_input", "ready", "warning", "blocked"].includes(status) ? `<small>可继续在下方对话中补充约束或调整目标值，正式参数在应用前不会变化。</small>` : ""}
    </section>
  `;
}

function renderParameterProposalChangeGroup(title, changes) {
  if (!Array.isArray(changes) || !changes.length) return "";
  return `
    <div class="parameter-change-proposal-group">
      <strong>${escapeHtml(title)}</strong>
      <ul>${changes.map((change) => `
        <li>
          <span>${escapeHtml(FIELD_LABELS[change.field] || change.label || targetFieldLabel(change.field))}</span>
          <small>${escapeHtml(`${formatParameterImpactValue(change.before, change.unit, change.change_type)} → ${formatParameterImpactValue(change.after, change.unit, change.change_type)}`)}</small>
        </li>
      `).join("")}</ul>
    </div>
  `;
}

function renderParameterProposalMessages(title, messages) {
  if (!Array.isArray(messages) || !messages.length) return "";
  return `<div class="parameter-change-proposal-notice"><strong>${escapeHtml(title)}</strong><ul>${messages.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
}

function renderParameterProposalIssues(title, issues) {
  return renderParameterProposalMessages(title, (issues || []).map((item) => item?.message || String(item || "")).filter(Boolean));
}

function renderParameterProposalRecommendations(items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `
    <div class="parameter-change-proposal-notice recommendation">
      <strong>尚未纳入方案的建议</strong>
      <ul>${items.map((item) => `<li>${escapeHtml(`${FIELD_LABELS[item.field] || item.label || targetFieldLabel(item.field)}：${item.reason || "需要继续确认"}`)}</li>`).join("")}</ul>
    </div>
  `;
}

function renderStandardizationChatRollbackHtml(turn, turnIndex) {
  const log = latestStandardizationChatApplication(turn);
  if (!log) return "";
  const count = Array.isArray(log.applied_patches) ? log.applied_patches.length : 1;
  const status = log.restandardization_status === "failed" ? "重新标准化未完成，可先撤销本次写回。" : "已写回参数并重新标准化，可撤销最近一次应用。";
  return `
    <div class="standardization-chat-rollback" data-kind="chat_action_rollback" data-turn-index="${turnIndex}" data-log-id="${escapeHtml(log.id)}">
      <small>${escapeHtml(`本轮已应用 ${count} 项建议。${status}`)}</small>
      <button type="button" class="secondary-action" data-role="undo-chat-turn-actions">撤销本次应用</button>
    </div>
  `;
}

function renderStandardizationChatActionHtml(action, turnIndex, actionIndex) {
  const target = String(action.target_field || "");
  const canApply = canApplyStandardizationChatAction(action);
  const impactStale = isParameterImpactPreviewStale(action.impact_preview);
  const status = action.status === "applied" ? "已应用" : (impactStale ? "预览已过期" : "待确认");
  const affected = Array.isArray(action.affected_fields) ? action.affected_fields : [];
  return `
    <div class="standardization-chat-action" data-kind="chat_action" data-turn-index="${turnIndex}" data-action-index="${actionIndex}">
      <div>
        <strong>${escapeHtml(action.target_label || targetFieldLabel(target) || "修改建议")}</strong>
        <span>${escapeHtml(formatStandardizationChatActionValue(action))}</span>
      </div>
      ${renderStandardizationChatActionPreviewHtml(action)}
      ${renderStandardizationChatImpactPreviewHtml(action.impact_preview, turnIndex)}
      ${action.impact_preview ? "" : renderStandardizationChatActionValidationHtml(action)}
      <div class="standardization-chat-action-notes">
        ${affected.length ? `<small>影响：${escapeHtml(affected.map((field) => targetFieldLabel(field)).join("、"))}</small>` : ""}
        ${action.reason ? `<small>${escapeHtml(action.reason)}</small>` : ""}
      </div>
      <button type="button" data-role="apply-chat-action" ${canApply ? "" : "disabled"}>${escapeHtml(status === "待确认" ? "应用建议" : status)}</button>
    </div>
  `;
}

function renderStandardizationChatActionValidationHtml(action) {
  const validation = action?.validation;
  if (!validation || validation.status === "not_applicable") return "";
  const statusLabels = {
    ready: "可应用",
    warning: "有风险",
    blocked: "不可应用",
  };
  const issues = Array.isArray(validation.issues) ? validation.issues.slice(0, 2) : [];
  const preview = renderStandardizationChatDerivedPreview(validation.derived_preview);
  return `
    <div class="standardization-chat-validation ${escapeHtml(validation.status || "warning")}">
      <strong>${escapeHtml(statusLabels[validation.status] || "待确认")}</strong>
      <small>${escapeHtml(validation.summary || "参数预检完成，请人工确认。")}</small>
      ${issues.length ? `<ul>${issues.map((item) => `<li>${escapeHtml(item.message || "")}</li>`).join("")}</ul>` : ""}
      ${preview ? `<span>${escapeHtml(preview)}</span>` : ""}
    </div>
  `;
}

function renderStandardizationChatDerivedPreview(preview) {
  if (!preview || typeof preview !== "object") return "";
  const fields = ["mean_diameter", "spring_index", "slenderness_ratio"];
  const values = fields.flatMap((field) => {
    const item = preview[field];
    if (!item || item.value == null) return [];
    return `${targetFieldLabel(field)} ${formatStandardValue(item.value, item.unit || "")}`;
  });
  return values.length ? `预计：${values.join(" · ")}` : "";
}

function buildParameterImpactBaselineState(review = state.review) {
  const summary = review?.drawing_summary || {};
  return {
    drawing_summary: { spring_type: summary.spring_type ?? null },
    spring_parameters: structuredClone(review?.spring_parameters || {}),
    technical_requirements: structuredClone(review?.technical_requirements || []),
    standard_selection: structuredClone(review?.standard_selection || {}),
    standardization_results: structuredClone(review?.standardization_results || []),
    derived_parameters_stale: Boolean(review?.derived_parameters_stale),
  };
}

function stableParameterImpactValue(value) {
  if (Array.isArray(value)) return value.map(stableParameterImpactValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, stableParameterImpactValue(value[key])]),
  );
}

function isParameterImpactPreviewStale(preview, review = state.review) {
  if (!preview?.baseline_state || !review) return false;
  return JSON.stringify(stableParameterImpactValue(preview.baseline_state))
    !== JSON.stringify(stableParameterImpactValue(buildParameterImpactBaselineState(review)));
}

function renderStandardizationChatImpactPreviewHtml(preview, turnIndex) {
  if (!preview || preview.status === "not_applicable") return "";
  const stale = isParameterImpactPreviewStale(preview);
  const statusLabels = { ready: "可应用", warning: "有风险", blocked: "不可应用" };
  const readiness = preview.generation_readiness || {};
  const risk = preview.risk_delta || {};
  const direct = Array.isArray(preview.direct_changes) ? preview.direct_changes : [];
  const derived = Array.isArray(preview.derived_changes) ? preview.derived_changes : [];
  const introduced = Array.isArray(risk.introduced) ? risk.introduced : [];
  const resolved = Array.isArray(risk.resolved) ? risk.resolved : [];
  const impactCount = Number(preview.impact_count) || direct.length + derived.length + introduced.length + resolved.length;
  const readinessText = readiness.before_status || readiness.after_status
    ? `生图状态 ${generationReadinessStatusLabel(readiness.before_status)} → ${generationReadinessStatusLabel(readiness.after_status)}`
    : "";
  return `
    <details class="standardization-chat-impact ${escapeHtml(preview.status || "ready")}${stale ? " stale" : ""}" ${stale ? "open" : ""}>
      <summary>
        <span>${escapeHtml(stale ? "影响预览已过期" : `预计影响 ${impactCount} 项 · ${statusLabels[preview.status] || "待确认"}`)}</span>
        ${readinessText ? `<small>${escapeHtml(readinessText)}</small>` : ""}
      </summary>
      <div class="standardization-chat-impact-body">
        <p>${escapeHtml(stale ? "当前参数或确认状态已经变化，请重新计算影响后再应用。" : (preview.summary || "影响计算完成。"))}</p>
        ${renderParameterImpactChangeSection("直接修改", direct)}
        ${renderParameterImpactChangeSection("计算影响", derived)}
        ${renderParameterImpactRiskSection("新增风险", introduced, "introduced")}
        ${renderParameterImpactRiskSection("已消除风险", resolved, "resolved")}
        ${renderParameterImpactWorkflowHtml(preview)}
        ${stale ? `<button type="button" class="secondary-action" data-role="recalculate-impact" data-turn-index="${turnIndex}">重新计算影响</button>` : ""}
      </div>
    </details>
  `;
}

function renderParameterImpactChangeSection(title, changes) {
  if (!Array.isArray(changes) || !changes.length) return "";
  return `
    <section>
      <strong>${escapeHtml(title)}</strong>
      <ul>${changes.map((change) => `
        <li>
          <span>${escapeHtml(FIELD_LABELS[change.field] || change.label || targetFieldLabel(change.field))}</span>
          <small>${escapeHtml(`${formatParameterImpactValue(change.before, change.unit, change.change_type)} → ${formatParameterImpactValue(change.after, change.unit, change.change_type)}`)}</small>
        </li>
      `).join("")}</ul>
    </section>
  `;
}

function formatParameterImpactValue(value, unit = "", changeType = "value") {
  if (changeType === "tolerance" || (value && typeof value === "object" && ("upper" in value || "lower" in value))) {
    return formatTolerancePair(value || {}, unit || "");
  }
  return formatStandardValue(value, unit || "");
}

function renderParameterImpactRiskSection(title, issues, kind) {
  if (!Array.isArray(issues) || !issues.length) return "";
  return `
    <section class="parameter-impact-risks ${escapeHtml(kind)}">
      <strong>${escapeHtml(title)}</strong>
      <ul>${issues.map((issue) => `<li><span>${escapeHtml(issue.message || issue.reason || "参数需复核")}</span></li>`).join("")}</ul>
    </section>
  `;
}

function renderParameterImpactWorkflowHtml(preview) {
  const readiness = preview.generation_readiness || {};
  const workflow = preview.workflow_effects || {};
  const frozenFields = Array.isArray(readiness.changed_frozen_fields)
    ? readiness.changed_frozen_fields.map((field) => targetFieldLabel(field))
    : [];
  const packageText = readiness.parameter_package_changed
    ? `SolidWorks 参数包将变化${frozenFields.length ? `：${frozenFields.join("、")}` : ""}`
    : "不会改变当前 SolidWorks 建模参数";
  const versionText = workflow.new_generation_required && state.generationJobs.length
    ? "旧生图版本不会被覆盖；应用后需创建新版本。"
    : (workflow.new_generation_required ? "后续创建生图任务时将使用新参数。" : "现有生图版本和参数包不受影响。");
  return `
    <section class="parameter-impact-workflow">
      <strong>生图和标准化流程影响</strong>
      <ul>
        <li><span>${escapeHtml(packageText)}</span></li>
        <li><span>${escapeHtml(versionText)}</span></li>
        ${workflow.standardization_recalculation_required ? "<li><span>应用后将自动重新标准化，旧标准化结果会先标记为过期。</span></li>" : ""}
      </ul>
    </section>
  `;
}

function generationReadinessStatusLabel(status) {
  return ({
    ready: "可生成",
    ready_with_warnings: "可生成（有提示）",
    needs_input: "待补充",
    needs_confirmation: "待确认",
    blocked: "存在不可用参数",
    not_applicable: "暂不适用",
  })[status] || status || "未知";
}

function canBatchSupplementChatAction(action) {
  const target = String(action?.target_field || "");
  return action?.type === "request_missing_field"
    && action?.status === "need_input"
    && Boolean(target)
    && target !== "standardization"
    && !target.startsWith("technical_requirements.");
}

function renderStandardizationChatSupplementFormHtml(items, turnIndex) {
  return `
    <form class="standardization-chat-supplement-form" data-kind="chat_supplement_form" data-turn-index="${turnIndex}">
      <div class="standardization-chat-supplement-head">
        <strong>补充本轮参数</strong>
        <small>可一次填写多项，提交后统一生成待确认建议。</small>
      </div>
      <div class="standardization-chat-supplement-fields">
        ${items.map(({ action, actionIndex }) => {
          const target = String(action?.target_field || "");
          const label = action?.target_label || targetFieldLabel(target) || "缺失字段";
          return `
            <label class="standardization-chat-supplement-field">
              <span>${escapeHtml(label)}</span>
              <input
                type="text"
                inputmode="${supplementInputMode(target)}"
                data-role="supplement-value"
                data-field="${escapeHtml(target)}"
                data-action-index="${actionIndex}"
                placeholder="${escapeHtml(supplementPlaceholder(target))}"
              >
              ${action?.reason ? `<small>${escapeHtml(action.reason)}</small>` : ""}
            </label>
          `;
        }).join("")}
      </div>
      <button type="submit">提交本轮补充</button>
    </form>
  `;
}

function supplementInputMode(target) {
  const numericFields = new Set([
    "wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length",
    "body_length", "solid_height", "total_coils", "active_coils", "end_coils", "support_coils",
    "pitch", "spring_rate", "perpendicularity", "straightness", "permanent_set_limit",
  ]);
  return numericFields.has(target) || target.startsWith("load_points.") ? "decimal" : "text";
}

function supplementPlaceholder(target) {
  if (target.endsWith("accuracy_grade")) return "例如：2级";
  if (target === "end_grinding") return "例如：两端磨平";
  if (target.startsWith("load_points.")) return "输入载荷值";
  return supplementInputMode(target) === "decimal" ? "输入数值" : "输入内容";
}

function renderStandardizationChatBatchHtml(turn, turnIndex) {
  const validation = validateStandardizationChatBatch(turn);
  if (validation.candidates.length < 2) return "";
  const proposalValidation = turn?.proposal_validation;
  const impactPreview = turn?.impact_preview;
  const label = validation.ok ? `应用本轮全部建议（${validation.candidates.length}）` : "本轮批量应用不可用";
  return `
    <div class="standardization-chat-batch" data-kind="chat_action_batch" data-turn-index="${turnIndex}">
      <div>
        <strong>本轮建议</strong>
        <small>${escapeHtml(validation.message || `可一次写回 ${validation.candidates.length} 条建议，写回后会重新标准化。`)}</small>
        ${renderStandardizationChatImpactPreviewHtml(impactPreview, turnIndex)}
        ${!impactPreview && proposalValidation && proposalValidation.status !== "not_applicable" ? `<small class="standardization-chat-batch-validation ${escapeHtml(proposalValidation.status || "warning")}">${escapeHtml(proposalValidation.summary || "")}</small>` : ""}
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
            ${confirmationButtonHtml(item, { kind: "technical", field: `technical_requirements.${index + 1}`, review })}
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
    stale: "已过期，需重算",
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
    completed: "已完成",
    execution_required: "待执行",
    invalid_grade: "精度等级无效",
    specialized_not_supported: "暂不支持专项精度",
    ready: "可以导出",
    blocked: "暂不能导出",
    explained: "已说明",
  };
  return labels[status] || status || "待确认";
}

function standardizationChatIntentLabel(type) {
  const labels = {
    explanation: "依据解释",
    parameter_change_request: "参数修改",
    multi_constraint_change_request: "多约束修改",
    full_standardization_plan: "完整标准化方案",
    accuracy_standardization_request: "按精度标准化",
    generation_package_export_request: "导出生图参数包",
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
  if (item?.status === "human_confirmed" || item?.status === "stale") return false;
  if (item?.metadata?.target_field_valid === false) return false;
  if (item?.metadata?.target_field_error) return false;
  return item?.status === "suggested" || item?.status === "llm_suggested" || item?.target_field === "standard_no";
}

function targetFieldLabel(targetField) {
  const text = String(targetField || "");
  const loadTarget = parseLoadPointTarget(text);
  if (loadTarget) return `载荷测试点 ${loadTarget.label} ${loadTarget.field === "height" ? "高度" : "力值"}`;
  return FIELD_LABELS[text] || text;
}

function parseLoadPointTarget(target) {
  const match = String(target || "").match(/^load_points\.([^.]+)\.(force|height)$/);
  return match ? { label: match[1], field: match[2] } : null;
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
  bindReasonablenessIssueFocus(root, messageId);

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
    const valueInput = row.querySelector('[data-role="value"]');
    let valueBeforeState = null;
    const applyValueDraft = (event) => {
      if (field === "accuracy_grade") return;
      activateReviewContext(messageId);
      valueBeforeState ||= parameterAuditState(param);
      rememberConfirmedSnapshot(param);
      param.value = parseValue(event.target.value, param.value);
      applyEditedConfirmationState(param, field);
      syncBubbleValue(field, param.value);
      syncConfirmationControl(row, param, { kind: "parameter", field, review });
      refreshCompressionDesignChecks(root, review);
      scheduleParameterReasonablenessRefresh(messageId);
    };
    valueInput.addEventListener("input", applyValueDraft);
    valueInput.addEventListener("change", (event) => {
      activateReviewContext(messageId);
      if (field === "accuracy_grade") {
        selectAccuracyGrade(root, review, event.target.value, messageId);
        return;
      }
      if (!valueBeforeState) applyValueDraft(event);
      const afterState = parameterAuditState(param);
      if (JSON.stringify(valueBeforeState) !== JSON.stringify(afterState)) {
        queueReviewAuditEvent({
          event_type: "parameter_value_updated",
          target_field: field,
          before_state: valueBeforeState,
          after_state: afterState,
        });
        scheduleParameterReasonablenessRefresh(messageId);
      }
      valueBeforeState = null;
    });
    const toleranceInput = row.querySelector('[data-role="tolerance"]');
    let toleranceBeforeState = null;
    const applyToleranceDraft = (event) => {
      activateReviewContext(messageId);
      toleranceBeforeState ||= parameterAuditState(param);
      rememberConfirmedSnapshot(param);
      applyTolerance(param, event.target.value);
      applyEditedConfirmationState(param, field);
      syncConfirmationControl(row, param, { kind: "parameter", field, review });
      scheduleParameterReasonablenessRefresh(messageId);
    };
    toleranceInput.addEventListener("input", applyToleranceDraft);
    toleranceInput.addEventListener("change", (event) => {
      if (!toleranceBeforeState) applyToleranceDraft(event);
      const afterState = parameterAuditState(param);
      if (JSON.stringify(toleranceBeforeState) !== JSON.stringify(afterState)) {
        queueReviewAuditEvent({
          event_type: "parameter_tolerance_updated",
          target_field: field,
          before_state: toleranceBeforeState,
          after_state: afterState,
        });
        scheduleParameterReasonablenessRefresh(messageId);
      }
      toleranceBeforeState = null;
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      activateReviewContext(messageId);
      const control = confirmationControlState(param, { kind: "parameter", field, review });
      if (control.disabled) return;
      const beforeState = parameterAuditState(param);
      const eventType = confirmationAuditEventType(param, field, review);
      confirmParam(param, field);
      queueReviewAuditEvent({
        event_type: eventType,
        target_field: field,
        before_state: beforeState,
        after_state: parameterAuditState(param),
        metadata: eventType === "risk_value_confirmed" ? { accepted_warning: true } : {},
      });
      syncConfirmationControl(row, param, { kind: "parameter", field, review });
      if (field === "accuracy_grade") syncAccuracyGradeControls(root, param);
      scheduleParameterReasonablenessRefresh(messageId);
    });
  });

  root.querySelectorAll('[data-action="select-workbench-accuracy-grade"]').forEach((select) => {
    select.addEventListener("change", (event) => {
      activateReviewContext(messageId);
      selectAccuracyGrade(root, review, event.target.value, messageId);
    });
  });

  root.querySelectorAll('[data-kind="load_point"]').forEach((row) => {
    const point = review.spring_parameters.load_points[Number(row.dataset.index)];
    const pointField = `load_points.${point?.label || `F${Number(row.dataset.index) + 1}`}`;
    const confirmationField = `load_points_${row.dataset.index}`;
    const bindLoadPointDraft = (input, applyValue, eventType) => {
      let beforeState = null;
      const applyDraft = (event) => {
        activateReviewContext(messageId);
        beforeState ||= loadPointAuditState(point);
        rememberConfirmedSnapshot(point);
        applyValue(event);
        applyEditedConfirmationState(point, pointField, { confirmationField });
        syncConfirmationControl(row, point, { kind: "load_point", field: pointField, review });
        scheduleParameterReasonablenessRefresh(messageId);
      };
      input.addEventListener("input", applyDraft);
      input.addEventListener("change", (event) => {
        if (!beforeState) applyDraft(event);
        const afterState = loadPointAuditState(point);
        if (JSON.stringify(beforeState) !== JSON.stringify(afterState)) {
          queueReviewAuditEvent({ event_type: eventType, target_field: pointField, before_state: beforeState, after_state: afterState });
          scheduleParameterReasonablenessRefresh(messageId);
        }
        beforeState = null;
      });
    };
    bindLoadPointDraft(row.querySelector('[data-role="height"]'), (event) => {
      point.height = parseValue(event.target.value, point.height);
    }, "load_point_value_updated");
    bindLoadPointDraft(row.querySelector('[data-role="force"]'), (event) => {
      point.force = parseValue(event.target.value, point.force);
    }, "load_point_value_updated");
    bindLoadPointDraft(row.querySelector('[data-role="load-tolerance"]'), (event) => {
      applyLoadPointTolerance(point, event.target.value);
    }, "load_point_tolerance_updated");
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      activateReviewContext(messageId);
      const control = confirmationControlState(point, { kind: "load_point", field: pointField, review });
      if (control.disabled) return;
      const beforeState = loadPointAuditState(point);
      const eventType = confirmationAuditEventType(point, pointField, review);
      confirmParam(point, confirmationField);
      queueReviewAuditEvent({
        event_type: eventType,
        target_field: pointField,
        before_state: beforeState,
        after_state: loadPointAuditState(point),
        metadata: eventType === "risk_value_confirmed" ? { accepted_warning: true } : {},
      });
      syncConfirmationControl(row, point, { kind: "load_point", field: pointField, review });
      scheduleParameterReasonablenessRefresh(messageId);
    });
  });

  root.querySelector('[data-action="run-workbench-standardization"]')?.addEventListener("click", () => {
    activateReviewContext(messageId);
    runStandardization(messageId, {
      workbench_feedback: true,
      pending_accuracy_grade: pendingAccuracyGradeFor(state.review?.spring_parameters?.accuracy_grade),
    });
  });

  root.querySelector('[data-action="apply-workbench-standardization"]')?.addEventListener("click", () => {
    applyAvailableStandardizationSuggestions(messageId);
  });

  root.querySelector('[data-action="confirm-all-review-items"]')?.addEventListener("click", async () => {
    activateReviewContext(messageId);
    const plan = buildSafeConfirmationPlan(state.review);
    if (!plan.items.length) {
      updateLatestReviewMessage("没有可批量确认的无风险项目，请继续逐项处理默认值或风险项。");
      return;
    }
    const confirmed = confirmSafeRecognizedFields(plan);
    syncReviewConfirmationControls(root, state.review);
    const bulkButton = root.querySelector('[data-action="confirm-all-review-items"]');
    const remainingPlan = buildSafeConfirmationPlan(state.review);
    if (bulkButton) {
      bulkButton.disabled = !remainingPlan.items.length;
      bulkButton.textContent = `全部确认可确认项${remainingPlan.items.length ? ` · ${remainingPlan.items.length}` : ""}`;
    }
    queueReviewAuditEvent({
      event_type: "safe_fields_confirmed",
      source: "manual_batch_confirmation",
      after_state: {
        confirmed_count: confirmed.count,
        group_counts: confirmed.group_counts,
      },
      metadata: {
        fields: confirmed.fields,
        labels: confirmed.labels,
        group_counts: confirmed.group_counts,
        skipped: confirmed.skipped.map((item) => ({
          field: item.field,
          label: item.label,
          reason: item.reason,
        })),
      },
    });
    scheduleParameterReasonablenessRefresh(messageId);
    updateLatestReviewMessage(`已确认 ${confirmed.count} 项无风险内容，跳过 ${confirmed.skipped.length} 项默认值、风险项或不完整内容。`);
    await flushReviewPersistence();
    if (state.lastJob?.job_id) await loadGenerationState(state.lastJob.job_id, { silent: true });
  });

  root.querySelectorAll('[data-action="focus-workbench-field"]').forEach((button) => {
    button.addEventListener("click", () => {
      activateReviewContext(messageId);
      focusMissingStandardizationField(button.dataset.field || "", messageId);
    });
  });

  root.querySelectorAll('[data-action="show-workbench-tab"]').forEach((button) => {
    button.addEventListener("click", () => {
      const compareRoot = root.closest?.("#compareOverlay") || (root.id === "compareOverlay" ? root : null);
      if (compareRoot) setCompareTab(compareRoot, button.dataset.targetTab);
    });
  });

  root.querySelectorAll('[data-action="workbench-ai"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = form.querySelector('[data-role="workbench-ai-input"]');
      const text = input?.value?.trim() || "";
      if (!text) return;
      input.value = "";
      const compareRoot = root.closest?.("#compareOverlay") || (root.id === "compareOverlay" ? root : null);
      if (compareRoot) setCompareTab(compareRoot, "assistant");
      runStandardizationChat(text, messageId, true);
    });
  });

  root.querySelectorAll('[data-kind="standardization"]').forEach((row) => {
    const item = review.standardization_results[Number(row.dataset.index)];
    row.querySelector('[data-role="confirm-standard"]')?.addEventListener("click", () => {
      activateReviewContext(messageId);
      const beforeState = { status: item.status, suggested_value: item.suggested_value ?? null };
      const applied = applyStandardizationResults([item], { mode: "single" });
      if (applied.count) {
        queueReviewAuditEvent({
          event_type: "standardization_suggestion_applied",
          target_field: item.target_field,
          source: "standardization",
          before_state: beforeState,
          after_state: { status: item.status, applied_count: applied.count },
        });
        scheduleParameterReasonablenessRefresh(messageId);
      }
      updateLatestReviewMessage(applied.count ? "已应用标准化建议，请继续核对导出数据。" : "该建议当前无法应用，请重新标准化后再试。");
    });
  });

  root.querySelector('[data-action="apply-standardization-batch"]')?.addEventListener("click", () => {
    applyAvailableStandardizationSuggestions(messageId);
  });

  root.querySelector('[data-action="undo-standardization-batch"]')?.addEventListener("click", () => {
    activateReviewContext(messageId);
    const reverted = undoLastStandardizationApplication();
    if (reverted) {
      queueReviewAuditEvent({
        event_type: "standardization_application_reverted",
        source: "standardization",
        after_state: { reverted_count: reverted.applied_count },
      });
      scheduleParameterReasonablenessRefresh(messageId);
    }
    updateLatestReviewMessage(reverted ? `已撤销上次应用的 ${reverted.applied_count} 项标准化建议。` : "没有可撤销的标准化应用记录。");
  });

  root.querySelector('[data-action="export-generation-package"]')?.addEventListener("click", () => {
    activateReviewContext(messageId);
    const packageData = makeGenerationParameterPackage(state.review);
    downloadJson(packageData, "compression_spring_generation_parameters.json");
    updateLatestReviewMessage("已导出当前已确认的生图参数包；待确认或空缺字段未包含。");
  });

  root.querySelector('[data-action="create-generation-job"]')?.addEventListener("click", () => {
    activateReviewContext(messageId);
    void createGenerationJob();
  });

  root.querySelectorAll('[data-action="compare-generation"]').forEach((button) => {
    button.addEventListener("click", () => openGenerationCompare(button.dataset.generationId || ""));
  });

  root.querySelectorAll('[data-action="retry-generation"]').forEach((button) => {
    button.addEventListener("click", () => void retryGenerationJob(button.dataset.generationId || ""));
  });

  root.querySelectorAll('[data-action="cancel-generation"]').forEach((button) => {
    button.addEventListener("click", () => void cancelGenerationJob(button.dataset.generationId || ""));
  });

  root.querySelectorAll('[data-action="approve-generation"]').forEach((button) => {
    button.addEventListener("click", () => void approveGenerationJob(button.dataset.generationId || ""));
  });

  root.querySelector('[data-action="confirm-standard-selection"]')?.addEventListener("click", () => {
    activateReviewContext(messageId);
    const beforeState = structuredClone(state.review.standard_selection || {});
    confirmStandardSelection();
    queueReviewAuditEvent({
      event_type: "standard_selection_confirmed",
      target_field: "standard_no",
      before_state: beforeState,
      after_state: structuredClone(state.review.standard_selection || {}),
    });
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

  root.querySelectorAll('[data-kind="chat_supplement_form"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (state.standardizationChatBusy) return;
      activateReviewContext(messageId);
      const turnIndex = Number(form.dataset.turnIndex);
      const turn = review.standardization_chat?.[turnIndex];
      const supplements = {};
      const submittedMissingActions = [];
      const messageParts = [];
      form.querySelectorAll('[data-role="supplement-value"]').forEach((input) => {
        const value = input.value.trim();
        const target = String(input.dataset.field || "");
        if (!value || !target) return;
        const actionIndex = Number(input.dataset.actionIndex);
        const action = turn?.suggested_actions?.[actionIndex];
        supplements[target] = value;
        submittedMissingActions.push({ turnIndex, actionIndex });
        messageParts.push(`${action?.target_label || targetFieldLabel(target)}=${value}`);
      });
      if (!Object.keys(supplements).length) {
        updateLatestReviewMessage("请至少填写一项需要补充的参数。");
        return;
      }
      runStandardizationChat(`补充参数：${messageParts.join("；")}`, messageId, false, {
        supplements,
        submittedMissingActions,
      });
    });
  });

  root.querySelectorAll('[data-role="focus-generation-field"]').forEach((button) => {
    button.addEventListener("click", () => {
      activateReviewContext(messageId);
      focusMissingStandardizationField(button.dataset.field || "", messageId);
    });
  });

  root.querySelectorAll('[data-kind="generation_package_export"]').forEach((row) => {
    const turnIndex = Number(row.dataset.turnIndex);
    row.querySelector('[data-role="download-generation-package"]')?.addEventListener("click", () => {
      activateReviewContext(messageId);
      const action = state.review?.standardization_chat?.[turnIndex]?.generation_package_export;
      void executeGenerationPackageExport(action, turnIndex, messageId);
    });
    row.querySelectorAll('[data-role="focus-generation-package-issue"]').forEach((button) => {
      button.addEventListener("click", () => {
        activateReviewContext(messageId);
        focusMissingStandardizationField(button.dataset.field || "", messageId);
      });
    });
  });

  root.querySelectorAll('[data-role="recalculate-impact"]').forEach((button) => {
    button.addEventListener("click", () => {
      if (state.standardizationChatBusy || state.busy) return;
      activateReviewContext(messageId);
      const turn = review.standardization_chat?.[Number(button.dataset.turnIndex)];
      const originalRequest = String(turn?.user || "").trim();
      if (!originalRequest) {
        updateLatestReviewMessage("找不到原修改要求，请重新输入参数修改内容。");
        return;
      }
      runStandardizationChat(originalRequest, messageId, true);
    });
  });

  root.querySelectorAll('[data-kind="parameter_change_proposal"]').forEach((row) => {
    const proposalId = String(row.dataset.proposalId || "");
    const proposal = (state.review?.parameter_change_proposals || []).find((item) => {
      return String(item?.proposal_id || "") === proposalId;
    }) || review.standardization_chat?.[Number(row.dataset.turnIndex)]?.change_proposal;
    row.querySelector('[data-role="apply-parameter-change-proposal"]')?.addEventListener("click", () => {
      void submitParameterChangeProposal(proposal, "apply", messageId);
    });
    row.querySelector('[data-role="discard-parameter-change-proposal"]')?.addEventListener("click", () => {
      void submitParameterChangeProposal(proposal, "discard", messageId);
    });
  });

  root.querySelectorAll('[data-kind="chat_standardization_batch"]').forEach((row) => {
    row.querySelector('[data-role="apply-chat-standardization-batch"]')?.addEventListener("click", () => {
      const turn = review.standardization_chat?.[Number(row.dataset.turnIndex)];
      const batch = turn?.standardization_batch;
      void applyChatStandardizationBatch(batch, messageId);
    });
  });

  root.querySelectorAll('[data-kind="chat_action"]').forEach((row) => {
    row.querySelector('[data-role="apply-chat-action"]')?.addEventListener("click", async () => {
      if (state.busy) return;
      activateReviewContext(messageId);
      const turn = review.standardization_chat?.[Number(row.dataset.turnIndex)];
      const action = turn?.suggested_actions?.[Number(row.dataset.actionIndex)];
      const applied = applyStandardizationChatActions([action], turn, { batch: false, turnIndex: Number(row.dataset.turnIndex) });
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
      const applied = applyStandardizationChatActions(validation.candidates, turn, { batch: true, turnIndex: Number(row.dataset.turnIndex) });
      if (!applied.ok) {
        updateLatestReviewMessage(applied.message || "本轮建议暂时不能批量应用。");
        return;
      }
      updateLatestReviewMessage(`已应用 ${applied.patches.length} 条对话修改建议，正在重新标准化...`);
      const standardized = await runStandardization(messageId);
      markStandardizationChatActionLogRestandardized(applied.log_id, standardized);
    });
  });

  root.querySelectorAll('[data-kind="chat_action_rollback"]').forEach((row) => {
    row.querySelector('[data-role="undo-chat-turn-actions"]')?.addEventListener("click", async () => {
      if (state.busy) return;
      activateReviewContext(messageId);
      const reverted = undoStandardizationChatApplication(row.dataset.logId || "");
      if (!reverted.ok) {
        updateLatestReviewMessage(reverted.message || "暂时无法撤销这次对话应用。");
        return;
      }
      updateLatestReviewMessage("已撤销本次对话应用，正在按撤销后的参数重新标准化...");
      const standardized = await runStandardization(messageId);
      markStandardizationChatApplicationRollbackRestandardized(reverted.log_id, standardized);
    });
  });

  root.querySelectorAll('[data-kind="technical"]').forEach((row) => {
    const item = review.technical_requirements[Number(row.dataset.index)];
    const technicalField = `technical_requirements.${Number(row.dataset.index) + 1}`;
    const confirmationField = `technical_${row.dataset.index}`;
    const contentInput = row.querySelector('[data-role="content"]');
    let contentBeforeState = null;
    const applyTechnicalDraft = (event) => {
      activateReviewContext(messageId);
      contentBeforeState ||= { content: item.content || "", need_human_review: Boolean(item.need_human_review) };
      rememberConfirmedSnapshot(item);
      item.content = event.target.value.trim();
      if (item.type === "surface") {
        item.raw_content ||= item.evidence || item.content;
        item.standard_content = item.content;
        item.normalization_status = "human_confirmed";
        item.normalization_source = "human";
        item.normalization_confidence = 1;
        item.normalization_reason = "人工修改标准术语";
      }
      applyEditedConfirmationState(item, technicalField, {
        confirmationField,
        skipParameterReasonableness: true,
        skipStandardizationInvalidation: true,
        skipDependentInvalidation: true,
      });
      syncConfirmationControl(row, item, { kind: "technical", field: technicalField, review });
    };
    contentInput.addEventListener("input", applyTechnicalDraft);
    contentInput.addEventListener("change", (event) => {
      if (!contentBeforeState) applyTechnicalDraft(event);
      const afterState = { content: item.content || "", need_human_review: Boolean(item.need_human_review) };
      if (JSON.stringify(contentBeforeState) !== JSON.stringify(afterState)) {
        queueReviewAuditEvent({
          event_type: "technical_requirement_updated",
          target_field: technicalField,
          before_state: contentBeforeState,
          after_state: afterState,
        });
      }
      contentBeforeState = null;
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="standard-candidate"]')?.addEventListener("change", (event) => {
      const value = event.target.value.trim();
      if (!value) return;
      activateReviewContext(messageId);
      const beforeState = { content: item.content || "", need_human_review: Boolean(item.need_human_review) };
      rememberConfirmedSnapshot(item);
      item.raw_content ||= item.evidence || item.content;
      item.content = value;
      item.standard_content = value;
      item.normalization_status = "human_confirmed";
      item.normalization_source = "human";
      item.normalization_confidence = 1;
      item.normalization_reason = "人工选择候选标准术语";
      contentInput.value = value;
      applyEditedConfirmationState(item, technicalField, {
        confirmationField,
        skipParameterReasonableness: true,
        skipStandardizationInvalidation: true,
        skipDependentInvalidation: true,
      });
      queueReviewAuditEvent({
        event_type: "technical_requirement_updated",
        target_field: technicalField,
        before_state: beforeState,
        after_state: { content: item.content || "", need_human_review: Boolean(item.need_human_review) },
      });
      syncConfirmationControl(row, item, { kind: "technical", field: technicalField, review });
      updateLatestReviewMessage();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      activateReviewContext(messageId);
      const control = confirmationControlState(item, { kind: "technical", field: technicalField, review });
      if (control.disabled) return;
      const beforeState = { content: item.content || "", need_human_review: Boolean(item.need_human_review) };
      const eventType = confirmationItemWasEdited(item) ? "modified_value_confirmed" : "recognized_value_confirmed";
      if (item.type === "surface" && item.content) {
        item.standard_content ||= item.content;
        item.raw_content ||= item.evidence || item.content;
        item.normalization_status = "human_confirmed";
        item.normalization_source = "human";
        item.normalization_confidence = 1;
        item.normalization_reason = "人工确认当前表面处理术语";
      }
      confirmParam(item, confirmationField);
      queueReviewAuditEvent({
        event_type: eventType,
        target_field: technicalField,
        before_state: beforeState,
        after_state: { content: item.content || "", need_human_review: Boolean(item.need_human_review) },
      });
      syncConfirmationControl(row, item, { kind: "technical", field: technicalField, review });
      updateLatestReviewMessage();
    });
  });
}

function applyStandardizationResult(item) {
  if (!item) return false;
  if (item.metadata?.target_field_valid === false) return false;
  if (item.metadata?.target_field_error) return false;
  state.review.standardization_results ||= [];
  state.review.spring_parameters ||= {};
  const target = String(item.target_field || "");
  const loadMatch = target.match(/^load_points\.([^.]+)\.force$/);
  if (loadMatch) {
    const label = loadMatch[1];
    const point = (state.review.spring_parameters.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    if (!point) return false;
    applyStandardizedLoadTolerance(
      point,
      item.suggested_tolerance_upper,
      item.suggested_tolerance_lower,
      { basis: item.basis || "" },
    );
    confirmParam(point, `standardization_${target}`);
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
    target_field: target,
  };
  return true;
}

function applyStandardizationResults(items, options = {}) {
  const candidates = (Array.isArray(items) ? items : [items]).filter((item) => canConfirmStandardization(item));
  if (!candidates.length) return { count: 0, history_id: null };
  const before = {
    spring_parameters: structuredClone(state.review.spring_parameters || {}),
    standardization_results: structuredClone(state.review.standardization_results || []),
    manual_confirmations: structuredClone(state.review.manual_confirmations || {}),
  };
  const appliedItems = candidates.filter((item) => applyStandardizationResult(item));
  if (!appliedItems.length) return { count: 0, history_id: null };
  state.review.standardization_apply_history ||= [];
  const historyId = `standardization_apply_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  state.review.standardization_apply_history.push({
    id: historyId,
    mode: options.mode || "single",
    batch_id: options.batch_id || null,
    applied_at: new Date().toISOString(),
    applied_count: appliedItems.length,
    targets: appliedItems.map((item) => String(item.target_field || "")),
    before,
  });
  state.review.parameter_reasonableness_stale = true;
  return { count: appliedItems.length, history_id: historyId };
}

function undoLastStandardizationApplication() {
  const history = state.review?.standardization_apply_history || [];
  const last = history.pop();
  if (!last?.before) return null;
  state.review.spring_parameters = structuredClone(last.before.spring_parameters || {});
  state.review.standardization_results = structuredClone(last.before.standardization_results || []);
  state.review.manual_confirmations = structuredClone(last.before.manual_confirmations || {});
  state.review.parameter_reasonableness_stale = true;
  state.review.confirmation_history ||= [];
  state.review.confirmation_history.push({
    event: "standardization_application_reverted",
    history_id: last.id,
    reverted_at: new Date().toISOString(),
    applied_count: last.applied_count,
    targets: last.targets,
  });
  if (last.batch_id) {
    markStandardizationBatchState(last.batch_id, { status: "stale", applied_count: 0, applied_at: null });
  }
  return last;
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
  const invalid = candidates.filter((action) => !canApplyStandardizationChatAction(action, {
    ignoreImpactFreshness: true,
    ignoreImpactAssessment: true,
  }));
  const duplicateTargets = duplicateStandardizationChatTargets(candidates);
  const proposalValidation = turn?.proposal_validation;
  const impactPreview = turn?.impact_preview;
  if (candidates.length < 2) {
    return {
      ok: false,
      candidates,
      message: candidates.length ? "本轮只有一条待应用建议，请逐条应用。" : "本轮没有可应用的修改建议。",
    };
  }
  if (impactPreview && isParameterImpactPreviewStale(impactPreview)) {
    return {
      ok: false,
      candidates,
      message: "本轮影响预览已过期，请重新计算后再应用。",
    };
  }
  if (invalid.length) {
    return {
      ok: false,
      candidates,
      message: "本轮存在缺少目标字段、建议值或载荷测试点的建议，需要逐条处理。",
    };
  }
  if (duplicateTargets.length) {
    return {
      ok: false,
      candidates,
      message: `同一字段存在多条同类建议：${duplicateTargets.join("、")}，请逐条确认。`,
    };
  }
  if (impactPreview?.status === "blocked") {
    return {
      ok: false,
      candidates,
      message: impactPreview.summary || "本轮参数组合会产生阻断问题，不能批量应用。",
    };
  }
  if (proposalValidation?.status === "blocked") {
    return {
      ok: false,
      candidates,
      message: proposalValidation.summary || "本轮参数组合不符合可行性校验，不能批量应用。",
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

function canApplyStandardizationChatAction(action, options = {}) {
  if (!action || action.status === "applied") return false;
  if (!isApplicableStandardizationChatActionType(action.type)) return false;
  if (!options.ignoreImpactAssessment && action.impact_preview?.status === "blocked") return false;
  if (!options.ignoreImpactFreshness && isParameterImpactPreviewStale(action.impact_preview)) return false;
  if (!options.ignoreImpactAssessment && action.validation?.status === "blocked") return false;
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
  const loadTarget = parseLoadPointTarget(target);
  if (!loadTarget) return true;
  return (state.review?.spring_parameters?.load_points || []).some((candidate) => {
    return String(candidate.label || "") === loadTarget.label;
  });
}

function applyStandardizationChatActions(actions, turn, options = {}) {
  const list = (Array.isArray(actions) ? actions : [actions]).filter(Boolean);
  if (!list.length) {
    return { ok: false, message: "没有可应用的标准化对话建议。" };
  }
  const batchApplication = list.length > 1;
  const invalid = list.filter((action) => !canApplyStandardizationChatAction(action, {
    ignoreImpactFreshness: batchApplication,
    ignoreImpactAssessment: batchApplication,
  }));
  if (invalid.length) {
    return { ok: false, message: "存在缺少目标字段、建议值或载荷测试点的建议，暂时无法应用。" };
  }
  const duplicateTargets = duplicateStandardizationChatTargets(list);
  if (duplicateTargets.length) {
    return {
      ok: false,
      message: `同一字段存在多条同类建议：${duplicateTargets.join("、")}，请逐条确认。`,
    };
  }

  const now = new Date().toISOString();
  const rollback = captureStandardizationChatRollback(list, turn, options);
  const patches = [];
  for (const action of list) {
    const applied = applyStandardizationChatAction(action, turn, {
      now,
      ignoreImpactFreshness: batchApplication,
      ignoreImpactAssessment: batchApplication,
    });
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
    rollback,
  });
  state.review.parameter_reasonableness_stale = true;
  return { ok: true, patches, log_id: logId };
}

function applyStandardizationChatAction(action, turn, options = {}) {
  if (!canApplyStandardizationChatAction(action, {
    ignoreImpactFreshness: Boolean(options.ignoreImpactFreshness),
    ignoreImpactAssessment: Boolean(options.ignoreImpactAssessment),
  })) {
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

  const loadTarget = parseLoadPointTarget(target);
  if (loadTarget) {
    const { label, field } = loadTarget;
    const point = (state.review.spring_parameters.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    if (!point) {
      action.apply_error = `未找到载荷测试点 ${label}`;
      return { ok: false, message: `未找到载荷测试点 ${label}，请先在载荷测试点表中补充。` };
    }
    const unitKey = field === "height" ? "height_unit" : "force_unit";
    unit = unit || point[unitKey] || (field === "height" ? "mm" : "N");
    point[field] = value;
    if (unit) point[unitKey] = unit;
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
      action.apply_error = `未找到载荷测试点 ${label}`;
      return { ok: false, message: `未找到载荷测试点 ${label}，请先在载荷测试点表中补充。` };
    }
    applyStandardizedLoadTolerance(point, tolerance.upper, tolerance.lower, { basis: action.reason || "" });
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

function captureStandardizationChatRollback(actions, turn, options = {}) {
  const parameters = state.review?.spring_parameters || {};
  const confirmations = state.review?.manual_confirmations || {};
  const fieldStates = actions.map((action) => {
    const target = String(action?.target_field || "");
    const loadTarget = parseLoadPointTarget(target);
    const confirmationKey = action?.type === "propose_tolerance_patch"
      ? `standardization_chat_${target}_tolerance`
      : `standardization_chat_${target}`;
    const confirmation = Object.prototype.hasOwnProperty.call(confirmations, confirmationKey)
      ? { exists: true, value: structuredClone(confirmations[confirmationKey]) }
      : { exists: false, value: null };
    if (loadTarget) {
      const { label } = loadTarget;
      const index = (parameters.load_points || []).findIndex((point) => String(point?.label || "") === label);
      return {
        target,
        kind: "load_point",
        index,
        label,
        value: index >= 0 ? structuredClone(parameters.load_points[index]) : null,
        confirmation_key: confirmationKey,
        confirmation,
      };
    }
    return {
      target,
      kind: "parameter",
      exists: Object.prototype.hasOwnProperty.call(parameters, target),
      value: Object.prototype.hasOwnProperty.call(parameters, target) ? structuredClone(parameters[target]) : null,
      confirmation_key: confirmationKey,
      confirmation,
    };
  });
  const actionStates = actions.map((action) => ({
    index: Array.isArray(turn?.suggested_actions) ? turn.suggested_actions.indexOf(action) : -1,
    value: structuredClone(action),
  }));
  return {
    turn_created_at: turn?.created_at || null,
    turn_index: Number.isInteger(options.turnIndex) ? options.turnIndex : null,
    field_states: fieldStates,
    action_states: actionStates,
  };
}

function recordStandardizationChatActionLog({ turn, patches, batch, appliedAt, rollback }) {
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
    rollback: rollback || null,
    turn_created_at: rollback?.turn_created_at || turn?.created_at || null,
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

function latestStandardizationChatApplication(turn) {
  const turnCreatedAt = turn?.created_at || null;
  return [...(state.review?.agent_actions || [])].reverse().find((item) => {
    return item?.source === "standardization_chat"
      && item?.turn_created_at === turnCreatedAt
      && item?.rollback
      && !item?.reverted;
  }) || null;
}

function undoStandardizationChatApplication(logId) {
  const log = (state.review?.agent_actions || []).find((item) => item?.id === logId);
  if (!log?.rollback || log.reverted) {
    return { ok: false, message: "没有可撤销的对话应用记录。" };
  }
  const conflict = standardizationChatRollbackConflict(log);
  if (conflict) {
    return { ok: false, message: `${targetFieldLabel(conflict)} 已被后续修改，不能覆盖较新的参数。` };
  }
  const parameters = state.review.spring_parameters ||= {};
  const confirmations = state.review.manual_confirmations ||= {};
  if (log.rollback.full_state) {
    const snapshot = log.rollback.full_state;
    state.review.spring_parameters = structuredClone(snapshot.spring_parameters || {});
    state.review.manual_confirmations = structuredClone(snapshot.manual_confirmations || {});
    state.review.derived_parameters = structuredClone(snapshot.derived_parameters || {});
    state.review.parameter_reasonableness = structuredClone(snapshot.parameter_reasonableness || {});
    state.review.standard_selection = structuredClone(snapshot.standard_selection || {});
    state.review.standardization_results = structuredClone(snapshot.standardization_results || []);
    const proposal = (state.review.parameter_change_proposals || []).find((item) => {
      return String(item?.proposal_id || "") === String(log.rollback.proposal_id || "");
    });
    if (proposal) {
      proposal.status = proposal.blocking_issues?.length ? "blocked" : (proposal.clarifying_questions?.length ? "needs_input" : "ready");
      delete proposal.applied_at;
      proposal.summary = "已撤销方案应用，可继续调整后再次应用。";
      state.review.active_parameter_change_proposal_id = proposal.proposal_id;
    }
  }
  for (const snapshot of log.rollback.field_states || []) {
    if (snapshot.kind === "load_point") {
      const points = parameters.load_points ||= [];
      if (snapshot.index >= 0) {
        points[snapshot.index] = structuredClone(snapshot.value);
      }
    } else if (snapshot.exists) {
      parameters[snapshot.target] = structuredClone(snapshot.value);
      syncBubbleValue(snapshot.target, parameters[snapshot.target]?.value);
    } else {
      delete parameters[snapshot.target];
      syncBubbleValue(snapshot.target, undefined);
    }
    if (snapshot.confirmation?.exists) {
      confirmations[snapshot.confirmation_key] = structuredClone(snapshot.confirmation.value);
    } else {
      delete confirmations[snapshot.confirmation_key];
    }
  }
  const turn = findStandardizationChatTurn(log.rollback);
  if (turn) {
    for (const actionState of log.rollback.action_states || []) {
      if (actionState.index >= 0) {
        turn.suggested_actions[actionState.index] = structuredClone(actionState.value);
      }
    }
  }
  log.reverted = true;
  log.reverted_at = new Date().toISOString();
  log.rollback_restandardization_status = "pending";
  return { ok: true, log_id: log.id };
}

function standardizationChatRollbackConflict(log) {
  for (const patch of log.applied_patches || []) {
    const target = String(patch?.target_field || "");
    if (patch?.action_type === "propose_tolerance_patch") {
      const current = currentActionTargetTolerance(target);
      if (!standardizationChatValuesEqual(current.upper, patch.suggested_tolerance_upper)
        || !standardizationChatValuesEqual(current.lower, patch.suggested_tolerance_lower)) {
        return target;
      }
      continue;
    }
    if (!standardizationChatValuesEqual(currentActionTargetValue(target), patch.proposed_value)) {
      return target;
    }
  }
  return "";
}

function standardizationChatValuesEqual(left, right) {
  if (left == null && right == null) return true;
  const numericLeft = Number(left);
  const numericRight = Number(right);
  if (Number.isFinite(numericLeft) && Number.isFinite(numericRight)) {
    return Math.abs(numericLeft - numericRight) < 1e-9;
  }
  return String(left ?? "") === String(right ?? "");
}

function findStandardizationChatTurn(rollback) {
  const turns = state.review?.standardization_chat || [];
  if (rollback?.turn_created_at) {
    const matched = turns.find((turn) => turn?.created_at === rollback.turn_created_at);
    if (matched) return matched;
  }
  const index = Number(rollback?.turn_index);
  return Number.isInteger(index) && index >= 0 ? turns[index] : null;
}

function markStandardizationChatApplicationRollbackRestandardized(logId, completed) {
  const log = (state.review?.agent_actions || []).find((item) => item?.id === logId);
  if (log) {
    log.rollback_restandardization_status = completed ? "completed" : "failed";
    log.rollback_restandardized_at = new Date().toISOString();
  }
  const context = getReviewContext(state.activeReviewMessageId);
  if (context) {
    context.review = state.review;
    context.imageUrl = state.imageUrl;
  }
}

function currentActionTargetValue(target) {
  const loadTarget = parseLoadPointTarget(target);
  if (loadTarget) {
    const { label, field } = loadTarget;
    const point = (state.review.spring_parameters?.load_points || []).find((candidate) => {
      return String(candidate.label || "") === label;
    });
    return point?.[field];
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
  const reviewScrollState = captureReviewScrollState();
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
  restoreReviewScrollState(reviewScrollState);
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

function focusMissingStandardizationField(field, messageId = state.activeReviewMessageId) {
  const target = String(field || "").trim();
  if (!target || !state.review) return;
  if (messageId) activateReviewContext(messageId);
  if (target === "standardization" || target === "standard_no") {
    state.compareTab = "standards";
    if (!state.compareOpen) openCompareOverlay(messageId);
    else renderCompareOverlay();
    return;
  }
  state.compareTab = "parameters";
  if (!state.compareOpen) {
    openCompareOverlay(messageId);
  } else {
    renderCompareOverlay();
  }
  requestAnimationFrame(() => {
    const technicalMatch = target.match(/^technical_requirements\.(\d+)$/);
    if (technicalMatch) {
      const technicalIndex = Math.max(Number(technicalMatch[1]) - 1, 0);
      const technicalRow = compareOverlay.querySelector(`[data-kind="technical"][data-index="${technicalIndex}"]`);
      if (technicalRow) {
        technicalRow.scrollIntoView({ behavior: "smooth", block: "center" });
        const input = technicalRow.querySelector('[data-role="content"]');
        input?.focus({ preventScroll: true });
        input?.select();
      }
      return;
    }
    const loadTarget = parseLoadPointTarget(target);
    if (loadTarget) {
      const pointIndex = (state.review.spring_parameters?.load_points || []).findIndex((point) => String(point?.label || "") === loadTarget.label);
      const loadRow = compareOverlay.querySelector(`[data-kind="load_point"][data-index="${pointIndex}"]`);
      if (loadRow) {
        loadRow.scrollIntoView({ behavior: "smooth", block: "center" });
        const input = loadRow.querySelector(`[data-role="${loadTarget.field}"]`);
        input?.focus({ preventScroll: true });
        input?.select();
      }
      return;
    }
    const row = Array.from(compareOverlay.querySelectorAll('[data-kind="param"]'))
      .find((item) => item.dataset.field === target);
    if (!row) return;
    const advanced = row.closest("details");
    if (advanced) advanced.open = true;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    const input = row.querySelector('[data-role="value"]');
    input?.focus({ preventScroll: true });
    input?.select();
  });
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
  const scrollState = captureCompareOverlayScrollState();
  refreshDerivedStatus(state.review);
  const activeTab = validCompareTab(state.compareTab);
  compareOverlay.innerHTML = `
    <div class="compare-shell">
      <header class="compare-head">
        <div>
          <h2>审图工作台</h2>
          <p>左侧查看原图，右侧按待处理事项完成核对、标准化与导出。</p>
        </div>
        <div class="compare-actions">
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
  bindCompareTabs(compareOverlay);
  bindReviewEditors(compareOverlay);
  initializeCompareViewer();
  restoreCompareOverlayScrollState(scrollState);
}

function captureCompareOverlayScrollState() {
  return {
    panels: captureComparePanelScrollPositions(),
    chatLists: Array.from(compareOverlay.querySelectorAll(".standardization-chat-list"), (list) => list.scrollTop),
  };
}

function restoreCompareOverlayScrollState(scrollState) {
  if (!scrollState) return;
  const restore = () => {
    restoreComparePanelScrollPositions(scrollState.panels, { immediate: true });
    compareOverlay.querySelectorAll(".standardization-chat-list").forEach((list, index) => {
      const scrollTop = scrollState.chatLists?.[index];
      if (Number.isFinite(scrollTop)) list.scrollTop = scrollTop;
    });
  };
  restore();
  requestAnimationFrame(() => {
    restore();
    requestAnimationFrame(restore);
  });
}

function captureComparePanelScrollPositions() {
  const positions = {};
  compareOverlay.querySelectorAll("[data-compare-panel]").forEach((panel) => {
    positions[panel.dataset.comparePanel] = panel.scrollTop;
  });
  return positions;
}

function restoreComparePanelScrollPositions(positions, options = {}) {
  const restore = () => {
    compareOverlay.querySelectorAll("[data-compare-panel]").forEach((panel) => {
      const scrollTop = positions[panel.dataset.comparePanel];
      if (Number.isFinite(scrollTop)) panel.scrollTop = scrollTop;
    });
  };
  if (options.immediate) restore();
  else requestAnimationFrame(restore);
}

function buildSafeConfirmationPlan(review) {
  const parameters = review?.spring_parameters || {};
  const fieldGroups = getParameterFieldGroups(parameters, review);
  const coreFields = new Set(fieldGroups.core);
  const advancedFields = new Set(fieldGroups.advanced);
  const items = [];
  const skipped = [];
  const skip = (group, field, label, reason) => skipped.push({ group, field, label, reason });

  getParameterFields(parameters, review).forEach((field) => {
    const param = parameters[field];
    if (!param?.need_human_review) return;
    const group = coreFields.has(field) ? "core" : (advancedFields.has(field) ? "advanced" : "advanced");
    const label = targetFieldLabel(field);
    const sources = sourceValues(param.source);
    const hasSystemDefault = Boolean(param.default_source) || sources.some((source) => source.includes("default"));
    const isFormulaValue = sources.includes("formula_calculation");

    if (field === "standard_no") {
      skip(group, field, label, "适用标准不在批量确认范围内");
      return;
    }
    const invalidReason = bulkParameterInvalidReason(field, param);
    if (invalidReason) {
      skip(group, field, label, invalidReason);
      return;
    }
    if (hasSystemDefault) {
      skip(group, field, label, "默认候选值需要单独确认");
      return;
    }
    const severity = reasonablenessSeverityForField(review, field);
    if (severity) {
      skip(group, field, label, `存在${reasonablenessSeverityLabel(severity)}，需要单独处理`);
      return;
    }
    if (isFormulaValue && !formulaConfirmationSourcesReady(parameters, param, review)) {
      skip(group, field, label, "公式来源字段尚未全部确认");
      return;
    }
    items.push({ kind: "parameter", group, field, param, label });
  });

  (parameters.load_points || []).forEach((point, index) => {
    if (!point?.need_human_review) return;
    const pointLabel = point.label || `F${index + 1}`;
    const field = `load_points.${pointLabel}`;
    const label = `载荷测试点 ${pointLabel}`;
    if (!isFiniteReviewNumber(point.height) || !isFiniteReviewNumber(point.force)) {
      skip("load_point", field, label, "高度和力值需要完整填写为有效数字");
      return;
    }
    const sources = sourceValues(point.source);
    if (point.default_source || sources.some((source) => source.includes("default"))) {
      skip("load_point", field, label, "默认候选值需要单独确认");
      return;
    }
    const severity = reasonablenessSeverityForField(review, field);
    if (severity) {
      skip("load_point", field, label, `存在${reasonablenessSeverityLabel(severity)}，需要单独处理`);
      return;
    }
    items.push({ kind: "load_point", group: "load_point", field, index, point, label });
  });

  (review?.technical_requirements || []).forEach((item, index) => {
    if (!item?.need_human_review) return;
    const field = `technical_requirements.${index + 1}`;
    const label = TECH_LABELS[item.type] || item.type || "技术要求";
    if (!String(item.content || "").trim()) {
      skip("technical", field, label, "技术要求内容为空");
      return;
    }
    if (item.type === "surface" && !["matched", "alias_matched", "llm_auto_matched", "human_confirmed"].includes(item.normalization_status)) {
      skip("technical", field, label, "表面处理术语尚未明确匹配");
      return;
    }
    items.push({ kind: "technical", group: "technical", field, index, item, label });
  });

  return { items, skipped, group_counts: safeConfirmationGroupCounts(items) };
}

function safeConfirmableReviewItems(review) {
  return buildSafeConfirmationPlan(review).items;
}

function bulkParameterInvalidReason(field, param) {
  if (param?.value == null || param.value === "") return "参数值缺失";
  try {
    if (COMPRESSION_GENERATION_CORE_FIELDS.includes(field)) generationContractValue(field, param.value);
    else if (field === "end_type") generationContractValue("end_coils_closed", param.value);
    else if (supplementInputMode(field) === "decimal" && !isFiniteReviewNumber(param.value)) return "参数值不是有效数字";
  } catch (error) {
    return error.message || String(error);
  }
  return "";
}

function isFiniteReviewNumber(value) {
  return value != null && value !== "" && Number.isFinite(Number(value));
}

function formulaConfirmationSourcesReady(parameters, param, review) {
  const sourceFields = Array.isArray(param?.source_fields) ? param.source_fields.filter(Boolean) : [];
  if (!sourceFields.length) return false;
  return sourceFields.every((field) => {
    const source = parameters?.[field];
    return source && typeof source === "object"
      && source.value != null && source.value !== ""
      && !source.need_human_review
      && !reasonablenessSeverityForField(review, field);
  });
}

function safeConfirmationGroupCounts(items) {
  const counts = { core: 0, advanced: 0, load_point: 0, technical: 0 };
  items.forEach((item) => { counts[item.group] = (counts[item.group] || 0) + 1; });
  return counts;
}

function confirmSafeRecognizedFields(plan = null) {
  if (!state.review) return { count: 0, labels: [], fields: [], group_counts: safeConfirmationGroupCounts([]), skipped: [] };
  const confirmationPlan = plan || buildSafeConfirmationPlan(state.review);
  confirmationPlan.items.forEach((item) => {
    if (item.kind === "parameter") confirmParam(item.param, item.field);
    else if (item.kind === "load_point") confirmParam(item.point, `load_points_${item.index}`);
    else if (item.kind === "technical") confirmParam(item.item, `technical_${item.index}`);
  });
  return {
    count: confirmationPlan.items.length,
    labels: confirmationPlan.items.map((item) => item.label),
    fields: confirmationPlan.items.map((item) => item.field),
    group_counts: confirmationPlan.group_counts,
    skipped: confirmationPlan.skipped,
  };
}

function applyAvailableStandardizationSuggestions(messageId = state.activeReviewMessageId) {
  activateReviewContext(messageId);
  const plan = standardizationBatchPlan(state.review);
  const applied = applyStandardizationResults(plan.items.map(({ item }) => item), { mode: "batch" });
  if (applied.count) {
    queueReviewAuditEvent({
      event_type: "standardization_suggestions_applied",
      source: "standardization",
      after_state: { applied_count: applied.count },
      metadata: { targets: plan.items.map(({ item }) => item.target_field).filter(Boolean) },
    });
    scheduleParameterReasonablenessRefresh(messageId);
  }
  updateLatestReviewMessage(applied.count ? `已应用 ${applied.count} 项标准化建议，可继续修改或导出。` : "暂无可批量应用的标准化建议。");
  return applied;
}

function currentStandardizationBatchTargetValue(target) {
  const loadTarget = parseLoadPointTarget(target);
  if (loadTarget) {
    const point = (state.review?.spring_parameters?.load_points || []).find((item) => String(item?.label || "") === loadTarget.label);
    return {
      exists: Boolean(point),
      value: point?.force ?? null,
      tolerance_upper: point?.load_tolerance_upper ?? null,
      tolerance_lower: point?.load_tolerance_lower ?? null,
      unit: point?.force_unit || "N",
      confirmed: point ? !Boolean(point.need_human_review) : false,
    };
  }
  const param = state.review?.spring_parameters?.[target];
  return {
    exists: Boolean(param && typeof param === "object"),
    value: param?.value ?? null,
    tolerance_upper: param?.tolerance_upper ?? null,
    tolerance_lower: param?.tolerance_lower ?? null,
    unit: param?.unit || "",
    confirmed: param ? !Boolean(param.need_human_review) : false,
  };
}

function standardizationBatchValuesEqual(left, right) {
  return ["exists", "value", "tolerance_upper", "tolerance_lower", "unit", "confirmed"]
    .every((key) => JSON.stringify(left?.[key] ?? null) === JSON.stringify(right?.[key] ?? null));
}

function standardizationBatchResultMatches(item, result) {
  if (!item || !result) return false;
  if (!["suggested", "llm_suggested"].includes(String(result.status || ""))) return false;
  if (String(result.target_field || "") !== String(item.target_field || "")) return false;
  if (String(result.rule_id || "") !== String(item.rule_id || "")) return false;
  const before = currentStandardizationBatchTargetValue(item.target_field);
  if (!standardizationBatchValuesEqual(before, item.before)) return false;
  const hasTolerance = result.suggested_tolerance_upper != null || result.suggested_tolerance_lower != null;
  const after = {
    exists: true,
    value: result.suggested_value != null ? result.suggested_value : before.value,
    tolerance_upper: hasTolerance ? (result.suggested_tolerance_upper ?? null) : before.tolerance_upper,
    tolerance_lower: hasTolerance ? (result.suggested_tolerance_lower ?? null) : before.tolerance_lower,
    unit: result.unit || before.unit || "",
    confirmed: true,
  };
  return standardizationBatchValuesEqual(after, item.after);
}

function markStandardizationBatchState(batchId, patch) {
  let changed = false;
  (state.review?.standardization_chat || []).forEach((turn) => {
    if (String(turn?.standardization_batch?.batch_id || "") !== String(batchId || "")) return;
    Object.assign(turn.standardization_batch, patch);
    changed = true;
  });
  return changed;
}

function removeQueuedReviewAuditEvent(clientEventId) {
  if (!clientEventId) return;
  state.pendingReviewAuditEvents = state.pendingReviewAuditEvents.filter((item) => item.client_event_id !== clientEventId);
  if (state.review?.change_history) {
    state.review.change_history = state.review.change_history.filter((item) => item.client_event_id !== clientEventId);
  }
}

async function applyChatStandardizationBatch(batch, messageId = state.activeReviewMessageId) {
  if (!batch || state.busy || state.standardizationChatBusy) return false;
  activateReviewContext(messageId);
  setBusy(true);
  let beforeReview = null;
  let auditEntry = null;
  try {
    await flushReviewPersistence({ throwOnError: true });
    if (standardizationBatchDisplayStatus(batch) !== "ready") {
      markStandardizationBatchState(batch.batch_id, { status: "stale" });
      updateLatestReviewMessage("这份标准化结果已经过期，请重新执行标准化后再应用。");
      return false;
    }
    beforeReview = structuredClone(state.review);
    const batchPlan = standardizationBatchPlan(state.review);
    const safeIndexes = new Set(batchPlan.items.map(({ index }) => Number(index)));
    const selected = [];
    for (const expected of batch.items || []) {
      const index = Number(expected.result_index);
      const result = state.review.standardization_results?.[index];
      if (!safeIndexes.has(index) || !standardizationBatchResultMatches(expected, result)) {
        markStandardizationBatchState(batch.batch_id, { status: "stale" });
        updateLatestReviewMessage("参数或标准化建议已经变化，这份结果不能继续应用，请重新标准化。");
        return false;
      }
      selected.push(result);
    }
    const applied = applyStandardizationResults(selected, { mode: "chat_batch", batch_id: batch.batch_id });
    if (!applied.count || applied.count !== selected.length) {
      state.review = beforeReview;
      updateLatestReviewMessage("没有可安全写入的标准化内容，请重新标准化后再试。");
      return false;
    }
    const appliedAt = new Date().toISOString();
    markStandardizationBatchState(batch.batch_id, {
      status: "applied",
      applied_count: applied.count,
      applied_at: appliedAt,
    });
    auditEntry = queueReviewAuditEvent({
      event_type: "standardization_suggestions_applied",
      source: "ai_chat",
      reason: "用户在AI对话中一键应用标准化结果",
      after_state: { applied_count: applied.count },
      metadata: {
        batch_id: batch.batch_id,
        targets: selected.map((item) => item.target_field).filter(Boolean),
        skipped_count: Number(batch.skipped_count || 0),
      },
    });
    await flushReviewPersistence({ throwOnError: true });
    state.generationReadiness = null;
    await refreshParameterReasonableness(messageId);
    if (state.lastJob?.job_id && typeof loadGenerationState === "function") {
      await loadGenerationState(state.lastJob.job_id, { silent: true });
    }
    updateLatestReviewMessage(`已应用 ${applied.count} 项标准化修改，参数栏位和生图就绪状态已更新。`);
    return true;
  } catch (error) {
    removeQueuedReviewAuditEvent(auditEntry?.client_event_id);
    if (beforeReview) {
      setReview(normalizeReview(beforeReview), state.imageUrl);
      markStandardizationBatchState(batch.batch_id, { status: "stale" });
    }
    updateLatestReviewMessage(error.message || "应用失败，参数没有被部分覆盖，请刷新后重试。");
    return false;
  } finally {
    setBusy(false);
  }
}

function normalizeAccuracyGrade(value) {
  const match = String(value ?? "").match(/([123])\s*级?/);
  return match ? `${match[1]}级` : "";
}

function accuracyGradeStatusLabel(param) {
  const sources = sourceValues(param?.source);
  if (param?.default_source === "company_default") return "公司默认 / 待确认";
  if (sources.includes("human_selected")) return "人工选择 / 已确认";
  if (sources.includes("human_confirmed")) return "人工确认";
  return param?.need_human_review ? "图纸识别 / 待确认" : "图纸识别";
}

function accuracyGradeStatusClass(param) {
  return param?.default_source === "company_default" ? "is-default" : "is-confirmed";
}

function accuracyGradeFeedbackIsVisible() {
  return state.accuracyGradeUpdate.phase !== "idle";
}

function renderAccuracyGradeFeedbackHtml(param) {
  const feedback = state.accuracyGradeUpdate;
  const visible = accuracyGradeFeedbackIsVisible();
  const message = accuracyGradeUpdateMessage(feedback.phase, feedback.grade, feedback.operation);
  return `
    <span class="workbench-accuracy-status">
      <small class="${accuracyGradeStatusClass(param)}" data-accuracy-grade-source${visible ? " hidden" : ""}>${escapeHtml(accuracyGradeStatusLabel(param))}</small>
      <small class="workbench-accuracy-update ${escapeHtml(feedback.phase)}" data-accuracy-grade-update-status role="status" aria-live="polite"${visible ? "" : " hidden"}>${escapeHtml(message)}</small>
    </span>
  `;
}

function accuracyGradeOptionsHtml(param) {
  const selected = displayedAccuracyGrade(param);
  const placeholder = selected ? "" : '<option value="" selected disabled>请选择</option>';
  return `${placeholder}${COMPRESSION_ACCURACY_GRADE_OPTIONS.map((grade) => `
    <option value="${grade}"${grade === selected ? " selected" : ""}>${grade}</option>
  `).join("")}`;
}

function parameterValueControlHtml(field, param, label) {
  if (field === "accuracy_grade") {
    return `
      <select data-role="value" data-accuracy-grade-selector aria-label="${escapeHtml(label)}">
        ${accuracyGradeOptionsHtml(param)}
      </select>
    `;
  }
  const endOptions = field === "end_grinding"
    ? COMPRESSION_END_GRINDING_OPTIONS
    : field === "end_type" ? COMPRESSION_END_TYPE_OPTIONS : null;
  if (endOptions) {
    return `
      <select data-role="value" aria-label="${escapeHtml(label)}">
        ${endConditionOptionsHtml(endOptions, param)}
      </select>
    `;
  }
  return `
    <input data-role="value" aria-label="${escapeHtml(label)}数值" value="${escapeHtml(formatFieldInput(param))}">
  `;
}

function endConditionOptionsHtml(options, param) {
  const selected = String(param?.value || "").trim();
  const placeholder = selected ? "" : '<option value="" selected>未识别</option>';
  return `${placeholder}${options.map((option) => `
    <option value="${escapeHtml(option)}"${option === selected ? " selected" : ""}>${escapeHtml(option)}</option>
  `).join("")}`;
}

function renderWorkbenchAccuracyGradeSelectorHtml(review) {
  const param = review?.spring_parameters?.accuracy_grade;
  if (!param || !isCompressionSpringReview(review)) return "";
  return `
    <label class="workbench-accuracy-grade">
      <span>通用精度等级</span>
      <select data-action="select-workbench-accuracy-grade" data-accuracy-grade-selector aria-label="通用精度等级">
        ${accuracyGradeOptionsHtml(param)}
      </select>
      ${renderAccuracyGradeFeedbackHtml(param)}
    </label>
  `;
}

function prepareAccuracyGradeCommit(review, grade) {
  const normalized = normalizeAccuracyGrade(grade);
  const param = review?.spring_parameters?.accuracy_grade;
  if (!normalized || !param || normalized === normalizeAccuracyGrade(param.value)) return null;
  const beforeState = parameterAuditState(param);
  revokeManualConfirmations("accuracy_grade", "accuracy_grade_selected", review);
  param.value = normalized;
  param.need_human_review = false;
  param.confidence = 0.99;
  param.source = ["human_selected"];
  param.evidence = `人工选择通用精度等级：${normalized}。`;
  delete param.default_source;
  delete param.default_reason;
  review.manual_confirmations ||= {};
  review.manual_confirmations.accuracy_grade = {
    confirmed: true,
    value: normalized,
    confirmed_at: new Date().toISOString(),
    confirmation_source: "accuracy_grade_selector",
  };
  return { grade: normalized, beforeState };
}

function syncAccuracyGradeControls(root, param) {
  const scope = root?.closest?.("#compareOverlay") || root || document;
  const value = displayedAccuracyGrade(param);
  scope.querySelectorAll("[data-accuracy-grade-selector]").forEach((select) => {
    select.value = value;
  });
  scope.querySelectorAll("[data-accuracy-grade-source]").forEach((element) => {
    element.textContent = accuracyGradeStatusLabel(param);
    element.classList.toggle("is-default", param?.default_source === "company_default");
    element.classList.toggle("is-confirmed", param?.default_source !== "company_default");
  });
  scope.querySelectorAll('[data-kind="param"][data-field="accuracy_grade"]').forEach((row) => {
    syncConfirmationControl(row, param, { kind: "parameter", field: "accuracy_grade", review: state.review });
  });
  updateAccuracyGradeFeedbackUi(scope);
}

function updateAccuracyGradeFeedbackUi(root = document) {
  const scope = root?.closest?.("#compareOverlay") || root || document;
  const feedback = state.accuracyGradeUpdate;
  const visible = accuracyGradeFeedbackIsVisible();
  const message = accuracyGradeUpdateMessage(feedback.phase, feedback.grade, feedback.operation);
  scope.querySelectorAll(".workbench-accuracy-status [data-accuracy-grade-source]").forEach((element) => {
    element.hidden = visible;
  });
  scope.querySelectorAll(".workbench-accuracy-status [data-accuracy-grade-update-status]").forEach((element) => {
    element.hidden = !visible;
    element.textContent = message;
    element.classList.remove("pending", "loading", "success", "error", "ready");
    if (visible) element.classList.add(feedback.phase);
  });
  scope.querySelectorAll("[data-accuracy-grade-selector]").forEach((select) => {
    select.disabled = feedback.phase === "loading";
    select.setAttribute("aria-busy", feedback.phase === "loading" ? "true" : "false");
  });
  scope.querySelectorAll('[data-action="run-workbench-standardization"]').forEach((button) => {
    button.disabled = feedback.phase === "loading";
    button.setAttribute("aria-busy", feedback.phase === "loading" ? "true" : "false");
  });
}

function selectAccuracyGrade(root, review, grade, messageId) {
  const param = review?.spring_parameters?.accuracy_grade;
  if (!param) return false;
  const selected = normalizeAccuracyGrade(grade);
  if (!selected) return false;
  const committed = normalizeAccuracyGrade(param.value);
  state.pendingAccuracyGrade = selected === committed ? "" : selected;
  setAccuracyGradeUpdate(
    state.pendingAccuracyGrade ? "ready" : "idle",
    state.pendingAccuracyGrade,
    state.pendingAccuracyGrade ? "accuracy" : "",
  );
  syncAccuracyGradeControls(root, param);
  refreshReviewSurfaces();
  return true;
}

function renderReviewWorkbenchHtml(review) {
  const reasonableness = review.parameter_reasonableness || {};
  const issues = Array.isArray(reasonableness.issues) ? reasonableness.issues : [];
  const blockedIssues = issues.filter((item) => item?.severity === "blocked");
  const warningIssues = issues.filter((item) => item?.severity === "warning");
  const inputIssues = issues.filter((item) => item?.severity === "needs_input");
  const standardizationResults = review.standardization_results || [];
  const staleCount = standardizationResults.filter((item) => item?.status === "stale").length;
  const batchPlan = standardizationBatchPlan(review);
  const safeItems = safeConfirmableReviewItems(review);
  const readiness = assessGenerationReadiness(review);
  const pendingAccuracyGrade = pendingAccuracyGradeFor(review.spring_parameters?.accuracy_grade);
  const hasPendingAccuracyGrade = Boolean(pendingAccuracyGrade);
  const needsStandardization = !standardizationResults.length || staleCount > 0;
  const shouldGenerateStandardization = needsStandardization || hasPendingAccuracyGrade;
  const standardizationLabel = hasPendingAccuracyGrade
    ? "重新生成标准化方案"
    : !standardizationResults.length
    ? "生成标准化方案"
    : "更新标准化方案";
  const handlingItems = [
    ...blockedIssues,
    ...inputIssues,
    ...warningIssues,
  ];
  const coveredFields = [
    ...handlingItems.flatMap((item) => Array.isArray(item?.fields) ? item.fields : []),
    ...safeItems.map((item) => item.field),
  ];
  const generationTasks = [...(readiness.missing_fields || []), ...(readiness.pending_fields || [])]
    .filter((item) => !coveredFields.some((field) => workbenchFieldsOverlap(field, item?.field)));
  const actionableCount = handlingItems.length + safeItems.length + generationTasks.length;
  return `
    <section class="review-workbench" data-kind="review-workbench">
      <section class="workbench-overview">
        <div>
          <span>当前审图</span>
          <strong>${escapeHtml(workbenchStatusLabel(review, readiness))}</strong>
          <small>${escapeHtml(workbenchStatusDescription(review, readiness, { blocked: blockedIssues.length, input: inputIssues.length, warning: warningIssues.length }))}</small>
        </div>
        <div class="workbench-overview-counts">
          <span>待处理 <b>${actionableCount}</b></span>
          <span>风险 <b>${blockedIssues.length + warningIssues.length}</b></span>
          <span>已确认 <b>${readiness.confirmed_core_count}/${readiness.core_field_count}</b></span>
        </div>
      </section>

      <section class="workbench-steps" aria-label="审图步骤">
        <article class="workbench-step ${blockedIssues.length || inputIssues.length ? "needs-attention" : ""}">
          <div class="workbench-step-index">1</div>
          <div>
            <strong>核对识别结果</strong>
            <small>${safeItems.length ? `${safeItems.length} 项无风险识别值可批量确认` : "识别值已完成初步核对"}</small>
          </div>
          <div class="workbench-step-actions">
            <button type="button" class="secondary-action" data-action="show-workbench-tab" data-target-tab="parameters">${safeItems.length ? "去参数页批量确认" : "查看参数"}</button>
          </div>
        </article>
        <article class="workbench-step ${needsStandardization || hasPendingAccuracyGrade ? "needs-attention" : ""}">
          <div class="workbench-step-index">2</div>
          <div>
            <strong>生成并应用标准化方案</strong>
            <small>${hasPendingAccuracyGrade ? `已选择 ${pendingAccuracyGrade}，点击重新生成标准化方案后才会写入` : (needsStandardization ? (!standardizationResults.length ? "尚未生成标准化建议" : `${staleCount} 项建议需要按最新参数更新`) : (batchPlan.items.length ? `${batchPlan.items.length} 项建议可一键应用` : "标准化建议已同步"))}</small>
            ${renderWorkbenchAccuracyGradeSelectorHtml(review)}
          </div>
          <div class="workbench-step-actions">
            ${shouldGenerateStandardization
              ? `<button type="button" data-action="run-workbench-standardization">${escapeHtml(standardizationLabel)}</button>`
              : batchPlan.items.length
                ? `<button type="button" data-action="apply-workbench-standardization">应用 ${batchPlan.items.length} 项建议</button>`
                : ""}
            <button type="button" class="secondary-action" data-action="show-workbench-tab" data-target-tab="standards">查看方案</button>
          </div>
        </article>
        <article class="workbench-step">
          <div class="workbench-step-index">3</div>
          <div>
            <strong>导出生图参数包</strong>
            <small>${escapeHtml(readiness.summary)}</small>
          </div>
          <div class="workbench-step-actions">
            <button type="button" data-action="export-generation-package">导出参数包</button>
          </div>
        </article>
      </section>

      ${handlingItems.length || generationTasks.length ? `
        <section class="workbench-task-list">
          <div class="block-head"><h2>优先处理</h2><span>${handlingItems.length + generationTasks.length} 项</span></div>
          ${handlingItems.slice(0, 4).map((item) => renderWorkbenchIssueHtml(item)).join("")}
          ${generationTasks.slice(0, 3).map((item) => renderWorkbenchGenerationTaskHtml(item)).join("")}
        </section>
      ` : `
        <section class="workbench-clear-state">
          <strong>当前没有需要优先处理的参数问题</strong>
          <span>仍可查看参数详情，或直接导出当前已确认的参数包。</span>
        </section>
      `}

      <form class="workbench-ai-form" data-action="workbench-ai">
        <input data-role="workbench-ai-input" type="text" placeholder="直接提问或修改参数，例如：按一级精度重新出方案">
        <button type="submit">交给 AI</button>
      </form>
    </section>
  `;
}

function workbenchFieldsOverlap(left, right) {
  const first = String(left || "");
  const second = String(right || "");
  return Boolean(first && second && (first === second || first.startsWith(`${second}.`) || second.startsWith(`${first}.`)));
}

function workbenchStatusLabel(review, readiness) {
  if (readiness.status === "blocked") return "存在需要先核对的参数";
  if (readiness.status === "ready" || readiness.status === "ready_with_warnings") return "可以导出生图参数包";
  return "继续处理待确认项目";
}

function workbenchStatusDescription(review, readiness, counts) {
  if (counts.blocked) return `${counts.blocked} 项几何或载荷关系需要先人工核对。`;
  if (counts.input) return `${counts.input} 项信息待补充，补齐后可继续标准化。`;
  if (counts.warning) return `${counts.warning} 项风险提示不阻断流程，但建议向客户确认。`;
  if (!review?.standardization_results?.length) return "标准化为可选功能；确认建模参数和技术要求后可直接生图。";
  return readiness.summary;
}

function renderWorkbenchIssueHtml(item) {
  const field = Array.isArray(item?.fields) ? item.fields[0] : "";
  const severity = item?.severity || "warning";
  return `
    <article class="workbench-task ${escapeHtml(severity)}">
      <div>
        <strong>${escapeHtml(reasonablenessSeverityLabel(severity))}</strong>
        <span>${escapeHtml(item?.message || item?.explanation || "请核对当前参数。")}</span>
        ${item?.customer_question ? `<small>建议：${escapeHtml(item.customer_question)}</small>` : ""}
      </div>
      ${field ? `<button type="button" class="secondary-action" data-action="focus-workbench-field" data-field="${escapeHtml(field)}">去处理</button>` : ""}
    </article>
  `;
}

function renderWorkbenchGenerationTaskHtml(item) {
  return `
    <article class="workbench-task pending">
      <div>
        <strong>${escapeHtml(item?.label || targetFieldLabel(item?.field))}</strong>
        <span>${escapeHtml(item?.reason || "需要补充或确认。")}</span>
      </div>
      ${canFocusGenerationIssue(item?.field) ? `<button type="button" class="secondary-action" data-action="focus-workbench-field" data-field="${escapeHtml(item.field)}">去处理</button>` : ""}
    </article>
  `;
}

function renderCompareDataPanelHtml(review, activeTab) {
  const panels = {
    workbench: renderReviewWorkbenchHtml(review),
    parameters: `
      ${renderTypeSelectorHtml(review)}
      ${renderSummaryHtml(review)}
      ${renderParameterReasonablenessHtml(review)}
      ${renderParameterTableHtml(review)}
      ${renderRequirementsHtml(review)}
    `,
    standards: `
      ${renderStandardSelectionHtml(review)}
      ${renderStandardizationHtml(review)}
      ${renderDerivedParametersHtml(review)}
    `,
    generation: `
      ${renderGenerationReadinessHtml(review)}
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
    ["workbench", "待处理"],
    ["parameters", "参数"],
    ["standards", "标准化"],
    ["generation", "生图参数包"],
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
      setCompareTab(root, button.dataset.compareTab);
    });
  });
}

function setCompareTab(root, requestedTab) {
  const tab = validCompareTab(requestedTab);
  state.compareTab = tab;
  root.querySelectorAll("[data-compare-tab]").forEach((item) => {
    item.classList.toggle("active", item.dataset.compareTab === tab);
  });
  const title = root.querySelector(".compare-data-top strong");
  const description = root.querySelector(".compare-data-top small");
  if (title) title.textContent = compareTabTitle(tab);
  if (description) description.textContent = compareTabDescription(tab);
  root.querySelectorAll("[data-compare-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.comparePanel === tab);
  });
}

function validCompareTab(tab) {
  return ["workbench", "parameters", "standards", "generation", "assistant"].includes(tab) ? tab : "workbench";
}

function compareTabTitle(tab) {
  const titles = {
    workbench: "待处理",
    parameters: "参数确认",
    standards: "标准化",
    generation: "生图参数包",
    assistant: "AI 对话",
  };
  return titles[tab] || titles.parameters;
}

function compareTabDescription(tab) {
  const descriptions = {
    workbench: "按优先级完成核对、标准化与导出",
    parameters: "核对识别尺寸和技术要求",
    standards: "查看标准选择、建议和派生参数",
    generation: "检查重新生图需要的已确认参数",
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

function activateReviewContext(messageId = state.activeReviewMessageId, options = {}) {
  const context = getReviewContext(messageId);
  if (!context) return null;
  const isCurrentReview = state.review === context.review;
  state.activeReviewMessageId = messageId;
  setReview(context.review, context.imageUrl, {
    preserveAccuracyGradeUpdate: options.preserveAccuracyGradeUpdate ?? isCurrentReview,
    preservePendingAccuracyGrade: options.preservePendingAccuracyGrade ?? isCurrentReview,
  });
  return context;
}

function setReview(review, imageUrl, options = {}) {
  if (!options.preserveAccuracyGradeUpdate) resetAccuracyGradeUpdate();
  if (!options.preservePendingAccuracyGrade) resetPendingAccuracyGrade();
  applyGenerationDefaults(review);
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

function appendAssistantText(text, isError = false, options = {}) {
  const message = createMessage("assistant");
  message.classList.toggle("error", isError);
  message.querySelector(".message-body").innerHTML = `
    <div class="message-meta">助手 · 引导</div>
    <p>${escapeHtml(text)}</p>
  `;
  conversation.appendChild(message);
  if (options.scroll !== false) scrollToBottom();
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
  const disabled = busy || !state.identityReady;
  submitButton.disabled = disabled || !state.selectedFile;
  chooseFileButton.disabled = disabled;
  demoButton.disabled = disabled;
  if (newReviewButton) newReviewButton.disabled = disabled;
  submitButton.classList.toggle("busy", busy);
  submitButton.textContent = busy ? "审查中..." : "↑";
  submitButton.setAttribute("aria-label", busy ? "正在审查" : "开始审查");
}

function apiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${state.apiBaseUrl}${normalizedPath}`;
}

function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), { ...options, credentials: "include" });
}

async function loadGenerationState(reviewId = state.lastJob?.job_id, options = {}) {
  if (!reviewId) {
    resetGenerationState();
    return;
  }
  state.generationQueueAvailable = null;
  try {
    const [readinessResponse, jobsResponse] = await Promise.all([
      apiFetch(`/api/reviews/${encodeURIComponent(reviewId)}/generation-readiness`),
      apiFetch(`/api/reviews/${encodeURIComponent(reviewId)}/generation-jobs`),
    ]);
    const readinessPayload = await readinessResponse.json();
    const jobsPayload = await jobsResponse.json();
    if (!readinessResponse.ok) throw new Error(generationApiError(readinessPayload, "无法读取服务端生图就绪状态"));
    if (state.lastJob?.job_id !== reviewId) return;
    state.generationReadiness = readinessPayload;
    if (jobsResponse.ok) {
      state.generationQueueAvailable = true;
      state.generationJobs = jobsPayload.generation_jobs || [];
    } else if (jobsResponse.status === 503 && jobsPayload?.detail?.code === "generation_queue_not_configured") {
      state.generationQueueAvailable = false;
      state.generationJobs = [];
    } else {
      throw new Error(generationApiError(jobsPayload, "无法读取生图版本"));
    }
    state.generationJobs.forEach((job) => {
      if (!["completed", "failed", "cancelled"].includes(job.status)) trackGenerationJob(job.generation_id);
    });
    if (options.render !== false) refreshReviewSurfaces();
  } catch (error) {
    if (options.silent !== true) appendAssistantText(`生图服务暂不可用：${error.message || String(error)}`, true, { scroll: false });
  }
}

async function reloadGenerationReadiness(reviewId = state.lastJob?.job_id) {
  if (!reviewId) return null;
  const response = await apiFetch(`/api/reviews/${encodeURIComponent(reviewId)}/generation-readiness`);
  const payload = await response.json();
  if (!response.ok) throw new Error(generationApiError(payload, "无法读取服务端生图就绪状态"));
  if (state.lastJob?.job_id === reviewId) state.generationReadiness = payload;
  return payload;
}

async function createGenerationJob() {
  const reviewId = state.lastJob?.job_id;
  if (!reviewId || state.generationBusy) return;
  state.generationBusy = true;
  refreshReviewSurfaces();
  try {
    await flushReviewPersistence();
    if (state.pendingReviewAuditEvents.length || state.reviewPersistenceSaving) {
      throw new Error("当前参数尚未成功保存到服务器，请检查网络后重试");
    }
    const readinessPayload = await reloadGenerationReadiness(reviewId);
    const readiness = readinessPayload?.generation_readiness || {};
    if (!["ready", "ready_with_warnings"].includes(readiness.status)) {
      throw new Error(readiness.summary || "当前参数尚未达到生图条件");
    }
    if (readiness.status === "ready_with_warnings") {
      const warningText = (readiness.warnings || []).map((item) => item.reason).filter(Boolean).join("\n");
      if (!window.confirm(`当前参数可以生图。标准化为可选功能，未应用的标准化建议不会进入参数包；任务将按当前已确认参数生成。\n\n风险提示：\n${warningText || readiness.summary}\n\n是否继续生成？`)) return;
    }
    const parent = state.generationJobs.find((job) => job.status === "completed") || state.generationJobs[0];
    const response = await apiFetch(`/api/reviews/${encodeURIComponent(reviewId)}/generation-jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_review_revision: Number(readinessPayload.review_revision),
        idempotency_key: createGenerationIdempotencyKey(reviewId, readinessPayload.review_revision),
        parent_generation_id: parent?.generation_id || null,
        requested_artifact_types: ["pdf"],
        mock_scenario: "success",
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(generationApiError(payload, "创建生图任务失败"));
    const job = payload.generation_job;
    state.generationJobs = [job, ...state.generationJobs.filter((item) => item.generation_id !== job.generation_id)];
    trackGenerationJob(job.generation_id);
    appendAssistantText("已创建生图任务，SolidWorks Worker 将按正式协议领取并生成 PDF；服务器会自动生成对比预览。", false, { scroll: false });
  } catch (error) {
    appendAssistantText(`无法生成图纸：${error.message || String(error)}`, true, { scroll: false });
  } finally {
    state.generationBusy = false;
    refreshReviewSurfaces();
  }
}

function trackGenerationJob(generationId) {
  if (!generationId || state.generationPollers[generationId]) return;
  const poll = async () => {
    try {
      const response = await apiFetch(`/api/generation-jobs/${encodeURIComponent(generationId)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(generationApiError(payload, "读取生图进度失败"));
      const job = payload.generation_job;
      const index = state.generationJobs.findIndex((item) => item.generation_id === generationId);
      if (index >= 0) state.generationJobs.splice(index, 1, job);
      else state.generationJobs.unshift(job);
      if (["completed", "failed", "cancelled"].includes(job.status)) {
        stopTrackingGenerationJob(generationId);
        await loadGenerationState(job.review_id, { silent: true });
      } else {
        refreshReviewSurfaces();
      }
    } catch {
      // A transient network failure should not discard a running job; the next poll retries it.
    }
  };
  state.generationPollers[generationId] = window.setInterval(() => { void poll(); }, 2000);
  void poll();
}

function stopTrackingGenerationJob(generationId) {
  const timer = state.generationPollers[generationId];
  if (timer) window.clearInterval(timer);
  delete state.generationPollers[generationId];
}

async function retryGenerationJob(generationId) {
  await generationJobAction(generationId, "retry", "已按原参数创建重试任务。", true);
}

async function cancelGenerationJob(generationId) {
  await generationJobAction(generationId, "cancel", "已请求取消生图任务。", false);
}

async function approveGenerationJob(generationId) {
  await generationJobAction(generationId, "approve", "当前版本已设为模拟最终版本；ERP 传送将在真实接口接入后开放。", false);
}

async function generationJobAction(generationId, action, successMessage, shouldTrack) {
  if (!generationId || state.generationBusy) return;
  state.generationBusy = true;
  try {
    const response = await apiFetch(`/api/generation-jobs/${encodeURIComponent(generationId)}/${action}`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(generationApiError(payload, `生图任务${action}失败`));
    const job = payload.generation_job;
    state.generationJobs = [job, ...state.generationJobs.filter((item) => item.generation_id !== job.generation_id)];
    if (shouldTrack) trackGenerationJob(job.generation_id);
    await loadGenerationState(job.review_id || state.lastJob?.job_id, { silent: true });
    appendAssistantText(successMessage, false, { scroll: false });
  } catch (error) {
    appendAssistantText(`操作失败：${error.message || String(error)}`, true, { scroll: false });
  } finally {
    state.generationBusy = false;
    refreshReviewSurfaces();
  }
}

function createGenerationIdempotencyKey(reviewId, revision) {
  const unique = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${reviewId}-r${revision}-${unique}`;
}

function generationApiError(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  const labels = {
    generation_not_ready: "当前审图参数尚未达到生图条件",
    review_revision_conflict: "审图参数已更新，请刷新后重新生图",
    template_not_found: "没有匹配到可用生图模板",
    template_selection_required: "存在多个同优先级模板，需要人工选择",
    generation_queue_not_configured: "生图队列需要 PostgreSQL",
    generation_conflict: "生图任务状态冲突，请刷新后重试",
  };
  return labels[detail?.code] || detail?.code || fallback;
}

function resetGenerationState() {
  Object.keys(state.generationPollers).forEach(stopTrackingGenerationJob);
  state.generationReadiness = null;
  state.generationJobs = [];
  state.generationQueueAvailable = null;
  state.generationBusy = false;
  document.querySelector(".generation-compare-dialog[open]")?.close();
}

function openGenerationCompare(generationId) {
  const job = state.generationJobs.find((item) => item.generation_id === generationId);
  const artifact = (job?.artifacts || []).find((item) => item.artifact_type === "png" || item.mime_type === "image/png");
  if (!job || !artifact) return;
  document.querySelector(".generation-compare-dialog")?.remove();
  const dialog = document.createElement("dialog");
  dialog.className = "generation-compare-dialog";
  const originalUrl = state.imageUrl ? toBackendAssetUrl(state.imageUrl) : "";
  const generatedUrl = toBackendAssetUrl(artifact.url);
  dialog.innerHTML = `
    <div class="generation-compare-shell">
      <header>
        <div><strong>原图与生成图对比</strong><small>审图修订 r${escapeHtml(String(job.review_revision))} · ${escapeHtml(job.template_code || "")}</small></div>
        <button type="button" data-role="close-generation-compare" aria-label="关闭">×</button>
      </header>
      <div class="generation-compare-toolbar">
        <div role="group" aria-label="对比模式">
          <button type="button" class="active" data-compare-mode="side-by-side">左右对比</button>
          <button type="button" data-compare-mode="original">仅原图</button>
          <button type="button" data-compare-mode="generated">仅生成图</button>
          <button type="button" data-compare-mode="overlay">透明叠加</button>
        </div>
        <label>缩放 <input type="range" min="50" max="200" value="100" data-role="generation-zoom"><span data-role="generation-zoom-label">100%</span></label>
        <label class="generation-opacity-control" hidden>生成图透明度 <input type="range" min="10" max="100" value="55" data-role="generation-opacity"></label>
      </div>
      <div class="generation-compare-canvas side-by-side" data-role="generation-compare-canvas">
        <figure class="generation-original"><figcaption>用户原图</figcaption>${originalUrl ? `<div><img src="${escapeHtml(originalUrl)}" alt="用户上传的原始图纸"></div>` : "<p>原图预览不可用</p>"}</figure>
        <figure class="generation-output"><figcaption>生成二维图（模拟）</figcaption><div><img src="${escapeHtml(generatedUrl)}" alt="模拟 SolidWorks 生成图"></div></figure>
      </div>
    </div>
  `;
  document.body.appendChild(dialog);
  const canvas = dialog.querySelector('[data-role="generation-compare-canvas"]');
  const opacityControl = dialog.querySelector(".generation-opacity-control");
  dialog.querySelector('[data-role="close-generation-compare"]').addEventListener("click", () => dialog.close());
  dialog.querySelectorAll("[data-compare-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      dialog.querySelectorAll("[data-compare-mode]").forEach((item) => item.classList.toggle("active", item === button));
      canvas.className = `generation-compare-canvas ${button.dataset.compareMode}`;
      opacityControl.hidden = button.dataset.compareMode !== "overlay";
    });
  });
  dialog.querySelector('[data-role="generation-zoom"]').addEventListener("input", (event) => {
    const scale = Number(event.target.value) / 100;
    canvas.style.setProperty("--generation-zoom", String(scale));
    dialog.querySelector('[data-role="generation-zoom-label"]').textContent = `${event.target.value}%`;
  });
  dialog.querySelector('[data-role="generation-opacity"]').addEventListener("input", (event) => {
    canvas.style.setProperty("--generation-opacity", String(Number(event.target.value) / 100));
  });
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.showModal();
}

async function readUploadResponsePayload(response) {
  const body = await response.text();
  try {
    return body ? JSON.parse(body) : {};
  } catch {
    if (response.status === 413) {
      return { detail: "上传文件超过网关允许的大小，请压缩 PDF 后重试或联系管理员调整上传限制。" };
    }
    if ([502, 503, 504].includes(response.status)) {
      return { detail: "上传识别请求等待后端服务超时。请稍后重试；若持续出现，请联系管理员检查网关/API 代理超时配置。" };
    }
    return { detail: `上传服务返回了非 JSON 响应（HTTP ${response.status || "未知"}）。请联系管理员检查 API 代理配置。` };
  }
}

function toBackendAssetUrl(path) {
  if (!path) return null;
  if (/^https?:\/\//i.test(path) || path.startsWith("blob:")) return path;
  return apiUrl(path);
}

function normalizeBaseUrl(url) {
  return String(url || "http://127.0.0.1:8770").trim().replace(/\/+$/, "");
}

function defaultApiBaseUrl() {
  const protocol = window.location.protocol;
  const host = window.location.hostname;
  const port = window.location.port;
  if (!protocol.startsWith("http") || !host) return "http://127.0.0.1:8770";
  if (["127.0.0.1", "localhost"].includes(host) && port === "5173") {
    return `${protocol}//${host}:8770`;
  }
  return window.location.origin;
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
  cloned.parameter_reasonableness ||= {
    status: "not_applicable",
    summary: "当前尚未生成参数合理性诊断。",
    issues: [],
  };
  cloned.parameter_reasonableness_stale ??= false;
  cloned.derived_parameters_stale ??= false;
  cloned.standardization_results ||= [];
  cloned.standardization_apply_history ||= [];
  cloned.confirmation_history ||= [];
  cloned.standardization_chat ||= [];
  cloned.parameter_change_proposals ||= [];
  cloned.active_parameter_change_proposal_id ??= null;
  cloned.agent_actions ||= [];
  cloned.change_history ||= [];
  cloned.technical_requirements ||= [];
  cloned.review_results ||= [];
  cloned.balloons ||= [];
  cloned.manual_confirmations ||= {};
  applyGenerationDefaults(cloned);
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
  const reasonablenessBlocked = review.parameter_reasonableness?.status === "blocked";
  review.human_review_required = hasHumanReview(review) || reasonablenessBlocked;
  review.erp_ready = !hasBlockingRule && !reasonablenessBlocked && !review.human_review_required && requiredMissing.length === 0;
  if (reasonablenessBlocked) {
    review.erp_block_reason = review.parameter_reasonableness?.summary || "存在不可用参数。";
  }
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
  const acceptsDefaultAccuracy = field === "accuracy_grade" && param?.default_source === "company_default";
  param.need_human_review = false;
  param.confidence = Math.max(Number(param.confidence) || 0, 0.99);
  param.source = Array.from(new Set(["human_confirmed", ...sourceValues(param.source)]));
  delete param.derived_value_stale;
  if (acceptsDefaultAccuracy) {
    param.source = ["human_confirmed"];
    param.evidence = `人工确认通用精度等级：${normalizeAccuracyGrade(param.value) || param.value}。`;
    delete param.default_source;
    delete param.default_reason;
    invalidateStandardizationResults("accuracy_grade");
    scheduleAutomaticStandardization();
  }
  state.review.manual_confirmations[field] = {
    confirmed: true,
    value: param.value ?? param.content ?? null,
    confirmed_at: new Date().toISOString(),
  };
  param.confirmation_snapshot = confirmationSnapshotFor(param);
}

function confirmationSnapshotFor(item) {
  if (!item || typeof item !== "object") return null;
  if (Object.prototype.hasOwnProperty.call(item, "height") || Object.prototype.hasOwnProperty.call(item, "force")) {
    return {
      kind: "load_point",
      height: item.height ?? null,
      force: item.force ?? null,
      load_tolerance_upper: item.load_tolerance_upper ?? null,
      load_tolerance_lower: item.load_tolerance_lower ?? null,
      load_tolerance_percent: item.load_tolerance_percent ?? null,
    };
  }
  if (Object.prototype.hasOwnProperty.call(item, "content")) {
    return { kind: "technical", content: String(item.content || "").trim() };
  }
  return {
    kind: "parameter",
    value: item.value ?? null,
    tolerance_upper: item.tolerance_upper ?? null,
    tolerance_lower: item.tolerance_lower ?? null,
  };
}

function rememberConfirmedSnapshot(item) {
  if (!item || item.need_human_review || item.confirmation_snapshot) return;
  item.confirmation_snapshot = confirmationSnapshotFor(item);
}

function confirmationSnapshotMatches(item) {
  if (!item?.confirmation_snapshot) return false;
  return JSON.stringify(item.confirmation_snapshot) === JSON.stringify(confirmationSnapshotFor(item));
}

function restoreSnapshotConfirmation(item, confirmationField) {
  item.need_human_review = false;
  item.source = sourceValues(item.source).filter((source) => source !== "human_edited");
  delete item.derived_value_stale;
  state.review.manual_confirmations ||= {};
  state.review.manual_confirmations[confirmationField] = {
    confirmed: true,
    value: item.value ?? item.content ?? null,
    confirmed_at: new Date().toISOString(),
    confirmation_source: "restored_confirmed_value",
  };
}

function applyEditedConfirmationState(item, field, options = {}) {
  const confirmationField = options.confirmationField || field;
  if (confirmationSnapshotMatches(item)) {
    restoreSnapshotConfirmation(item, confirmationField);
    return "restored";
  }
  markParamEdited(item, field, options);
  return "modified";
}

function confirmationAuditEventType(item, field, review = state.review) {
  if (reasonablenessSeverityForField(review, field) === "warning") return "risk_value_confirmed";
  return confirmationItemWasEdited(item) ? "modified_value_confirmed" : "recognized_value_confirmed";
}

function markDependentFormulaParametersPending(field) {
  const parameters = state.review?.spring_parameters || {};
  Object.entries(parameters).forEach(([targetField, target]) => {
    if (targetField === field || !target || typeof target !== "object" || Array.isArray(target)) return;
    const sourceFields = Array.isArray(target.source_fields) ? target.source_fields : [];
    const isCalculated = sourceValues(target.source).some((source) => source === "formula_calculation" || source === "derived");
    if (!isCalculated || !sourceFields.includes(field)) return;
    rememberConfirmedSnapshot(target);
    const recalculated = recalculateKnownDependentParameter(targetField, target, parameters);
    if (recalculated && confirmationSnapshotMatches(target)) {
      restoreSnapshotConfirmation(target, targetField);
      return;
    }
    target.need_human_review = true;
    target.source = Array.from(new Set(["derived_recalculation", ...sourceValues(target.source)]));
    target.derived_value_stale = !recalculated;
    revokeManualConfirmations(targetField, "source_parameter_edited");
  });
}

function recalculateKnownDependentParameter(field, target, parameters) {
  const wire = Number(parameters.wire_diameter?.value);
  const mean = Number(parameters.mean_diameter?.value);
  const outer = Number(parameters.outer_diameter?.value);
  const inner = Number(parameters.inner_diameter?.value);
  let value = null;
  if (field === "mean_diameter" && Number.isFinite(wire)) {
    if (target.source_fields?.includes("outer_diameter") && Number.isFinite(outer)) value = outer - wire;
    else if (target.source_fields?.includes("inner_diameter") && Number.isFinite(inner)) value = inner + wire;
  } else if (field === "outer_diameter" && Number.isFinite(wire) && Number.isFinite(mean)) {
    value = mean + wire;
  } else if (field === "inner_diameter" && Number.isFinite(wire) && Number.isFinite(mean)) {
    value = mean - wire;
  }
  if (!Number.isFinite(value)) return false;
  target.value = Number(value.toFixed(3));
  return true;
}

function markParamEdited(param, field = "", options = {}) {
  param.need_human_review = true;
  param.source = Array.from(new Set(["human_edited", ...sourceValues(param.source)]));
  if (!options.skipParameterReasonableness) state.review.parameter_reasonableness_stale = true;
  if (!field) {
    scheduleAutomaticStandardization();
    return;
  }
  if (options.confirmationField) {
    revokeManualConfirmations(options.confirmationField, "value_edited");
  }
  revokeManualConfirmations(field, "value_edited");
  if (!options.skipStandardizationInvalidation) invalidateStandardizationResults(field);
  if (!options.skipDependentInvalidation && !field.startsWith("load_points.") && !field.startsWith("technical_requirements.")) {
    markDependentFormulaParametersPending(field);
  }
  scheduleAutomaticStandardization(undefined, {
    force: ["total_coils", "end_type", "support_coils"].includes(field),
  });
}

function sourceValues(source) {
  if (Array.isArray(source)) return source;
  return source ? [source] : [];
}

function revokeManualConfirmations(field, reason, review = state.review) {
  if (!review || !field) return false;
  const confirmations = review.manual_confirmations ||= {};
  let revoked = false;
  Object.entries(confirmations).forEach(([key, entry]) => {
    if (!entry?.confirmed || !confirmationMatchesField(key, entry, field)) return;
    review.confirmation_history ||= [];
    review.confirmation_history.push({
      event: "confirmation_reopened",
      field,
      confirmation_key: key,
      reason,
      reopened_at: new Date().toISOString(),
      previous_confirmation: structuredClone(entry),
    });
    confirmations[key] = {
      ...entry,
      confirmed: false,
      revoked_at: new Date().toISOString(),
      revoke_reason: reason,
    };
    revoked = true;
  });
  return revoked;
}

function confirmationMatchesField(key, entry, field) {
  const target = String(entry?.target_field || "");
  if (key === field || target === field || target.startsWith(`${field}.`)) return true;
  if (key.endsWith(`_${field}`)) return true;
  return field.startsWith("load_points.") && key.includes(field);
}

function invalidateStandardizationResults(field) {
  const activeStatuses = new Set(["suggested", "llm_suggested", "human_confirmed"]);
  let invalidated = 0;
  (state.review.standardization_results || []).forEach((item) => {
    if (!activeStatuses.has(item.status)) return;
    item.metadata ||= {};
    item.metadata.stale_by_field = field;
    item.metadata.stale_at = new Date().toISOString();
    item.status = "stale";
    item.need_human_review = true;
    invalidated += 1;
  });
  if (!invalidated) return 0;
  state.review.standardization_apply_history = [];
  state.review.derived_parameters_stale = true;
  if (["wire_diameter", "standard_no"].includes(field)) {
    state.review.standard_selection ||= {};
    state.review.standard_selection.need_human_review = true;
    state.review.standard_selection.human_confirmed = false;
  }
  return invalidated;
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

function makeGenerationParameterPackage(review = state.review) {
  const confirmedParameters = {};
  COMPRESSION_GENERATION_CORE_FIELDS.forEach((field) => {
    const param = generationSourceParameter(review.spring_parameters || {}, field);
    if (!param || generationContractState(review.spring_parameters || {}, field) !== "confirmed") return;
    const value = generationContractValue(field, param.value);
    confirmedParameters[field] = {
      label: COMPRESSION_GENERATION_LABELS[field],
      value,
      unit: COMPRESSION_GENERATION_UNITS[field],
      tolerance_upper: param.tolerance_upper ?? null,
      tolerance_lower: param.tolerance_lower ?? null,
      confirmation_source: "human_confirmed",
    };
  });
  const requirements = (review.technical_requirements || [])
    .filter((item) => item?.content && !item.need_human_review)
    .map((item) => ({
      type: item.type,
      content: item.content,
      confirmation_source: "human_confirmed",
    }));
  const summary = review.drawing_summary || {};
  const selection = review.standard_selection || {};
  return {
    schema_version: "spring_generation_parameters/v1",
    package_type: "confirmed_compression_spring_generation_input",
    generated_at: new Date().toISOString(),
    export_policy: {
      parameter_filter: "frozen_compression_inputs_v1_human_confirmed_only",
      readiness_is_advisory: true,
    },
    source: {
      drawing_no: summary.drawing_no || null,
      drawing_name: summary.drawing_name || null,
      spring_type: currentSpringType(review),
      spring_type_label: summary.spring_type_label || SPRING_TYPE_LABELS[currentSpringType(review)] || null,
    },
    standard_context: {
      selected_standard: selection.selected_standard || null,
      selection_status: selection.status || null,
      human_confirmed: Boolean(selection.human_confirmed),
    },
    generation_parameters: {
      spring_parameters: confirmedParameters,
      technical_requirements: requirements,
    },
    derived_parameters: generationDerivedParameters(review),
  };
}

function generationDerivedParameters(review) {
  const derived = structuredClone(review.derived_parameters || {});
  ["mean_diameter", "spring_index", "slenderness_ratio"].forEach((field) => delete derived[field]);
  const params = review.spring_parameters || {};
  const confirmedNumber = (field) => {
    if (generationParameterState(params[field]) !== "confirmed") return null;
    const value = Number(params[field]?.value);
    return Number.isFinite(value) ? value : null;
  };
  const wire = confirmedNumber("wire_diameter");
  const outer = confirmedNumber("outer_diameter");
  const inner = confirmedNumber("inner_diameter");
  const recognizedMean = confirmedNumber("mean_diameter");
  const freeLength = confirmedNumber("free_length");
  let mean = recognizedMean;
  let meanFormula = recognizedMean != null ? "drawing_or_manual_mean_diameter" : "";
  let meanSources = recognizedMean != null ? ["mean_diameter"] : [];
  if (mean == null && wire != null && outer != null) {
    mean = outer - wire;
    meanFormula = "outer_diameter - wire_diameter";
    meanSources = ["outer_diameter", "wire_diameter"];
  } else if (mean == null && wire != null && inner != null) {
    mean = inner + wire;
    meanFormula = "inner_diameter + wire_diameter";
    meanSources = ["inner_diameter", "wire_diameter"];
  }
  if (mean != null) {
    derived.mean_diameter = generationDerivedParameter("mean_diameter", mean, "mm", meanFormula, meanSources);
  }
  if (mean != null && wire != null && wire !== 0) {
    derived.spring_index = generationDerivedParameter(
      "spring_index",
      mean / wire,
      null,
      "mean_diameter / wire_diameter",
      ["mean_diameter", "wire_diameter"],
    );
  }
  if (mean != null && mean !== 0 && freeLength != null) {
    derived.slenderness_ratio = generationDerivedParameter(
      "slenderness_ratio",
      freeLength / mean,
      null,
      "free_length / mean_diameter",
      ["free_length", "mean_diameter"],
    );
  }
  return derived;
}

function generationDerivedParameter(field, value, unit, formula, sourceFields) {
  const rounded = Number(Number(value).toFixed(4));
  return {
    field,
    value: rounded,
    unit,
    source: ["derived", "generation_export"],
    formula,
    source_fields: sourceFields,
    confidence: 0.99,
    need_human_review: false,
  };
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

function applyLoadPointTolerance(point, value) {
  const text = value.trim().replace(/^\u5efa\u8bae\s*/, "").replace(/N$/i, "");
  if (!text) {
    point.load_tolerance_upper = null;
    point.load_tolerance_lower = null;
    point.load_tolerance_percent = null;
    point.force_tolerance_percent = null;
    point.tolerance_source = "human";
    point.tolerance_basis = "";
    return;
  }
  if (text.endsWith("%")) {
    const percent = Number(text.replace(/^\u00b1/, "").slice(0, -1));
    if (!Number.isNaN(percent)) {
      point.force_tolerance_percent = Math.abs(percent);
      point.load_tolerance_percent = Math.abs(percent);
      point.load_tolerance_upper = null;
      point.load_tolerance_lower = null;
      point.tolerance_source = "human";
      point.tolerance_basis = "";
    }
    return;
  }
  const parsed = { tolerance_upper: null, tolerance_lower: null };
  applyTolerance(parsed, text.replace(/^\u00b1/, "\u00b1"));
  point.load_tolerance_upper = parsed.tolerance_upper;
  point.load_tolerance_lower = parsed.tolerance_lower;
  if (point.force && parsed.tolerance_upper != null) {
    point.load_tolerance_percent = Number(
      ((Math.abs(Number(parsed.tolerance_upper)) / Math.abs(Number(point.force))) * 100).toFixed(3),
    );
  }
  point.tolerance_source = "human";
  point.tolerance_basis = "";
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
