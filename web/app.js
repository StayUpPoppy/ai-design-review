const state = {
  imageUrl: null,
  imageSize: null,
  review: null,
  selectedBubbleId: null,
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

const imageInput = document.getElementById("imageInput");
const jsonInput = document.getElementById("jsonInput");
const demoButton = document.getElementById("demoButton");
const exportButton = document.getElementById("exportButton");
const confirmAllButton = document.getElementById("confirmAllButton");
const backendDrawingInput = document.getElementById("backendDrawingInput");
const backendOcrInput = document.getElementById("backendOcrInput");
const backendCandidateInput = document.getElementById("backendCandidateInput");
const useSampleOcrInput = document.getElementById("useSampleOcrInput");
const useCachedWerk24Input = document.getElementById("useCachedWerk24Input");
const usePaddleOcrInput = document.getElementById("usePaddleOcrInput");
const useWerk24Input = document.getElementById("useWerk24Input");
const confirmWerk24Input = document.getElementById("confirmWerk24Input");
const processButton = document.getElementById("processButton");
const backendStatus = document.getElementById("backendStatus");
const canvas = document.getElementById("canvas");
const summary = document.getElementById("summary");
const statusList = document.getElementById("statusList");
const fieldEditor = document.getElementById("fieldEditor");
const requirementEditor = document.getElementById("requirementEditor");
const bubbleList = document.getElementById("bubbleList");
const ruleList = document.getElementById("ruleList");

imageInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (state.imageUrl?.startsWith("blob:")) URL.revokeObjectURL(state.imageUrl);
  state.imageUrl = URL.createObjectURL(file);
  render();
});

jsonInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  state.review = normalizeReview(JSON.parse(await file.text()));
  render();
});

demoButton.addEventListener("click", async () => {
  try {
    const reviewResponse = await fetch("/outputs/mixed_review.json");
    if (!reviewResponse.ok) throw new Error("样例审查 JSON 加载失败");
    state.review = normalizeReview(await reviewResponse.json());
    state.imageUrl = "/tmp_pdf_pages/spring_example_rotated.png";
    setBackendStatus("样例已加载。");
    render();
  } catch (error) {
    setBackendStatus(error.message || String(error), true);
  }
});

confirmAllButton.addEventListener("click", () => {
  if (!state.review) return;
  confirmAllFields();
  acknowledgeScannedInput();
  render();
});

exportButton.addEventListener("click", () => {
  if (!state.review) return;
  const exported = makeExportReview();
  downloadJson(exported, "spring_review_confirmed.json");
});

processButton.addEventListener("click", async () => {
  const drawing = backendDrawingInput.files?.[0];
  if (!drawing) {
    setBackendStatus("请选择 PDF 或图片图纸。", true);
    return;
  }
  if (useWerk24Input.checked && !confirmWerk24Input.checked) {
    setBackendStatus("调用 Werk24 前必须勾选“确认上传到 Werk24”。", true);
    return;
  }

  const form = new FormData();
  form.append("drawing", drawing);
  const candidateJson = backendCandidateInput.files?.[0];
  if (candidateJson) form.append("candidate_json", candidateJson);
  const ocrJson = backendOcrInput.files?.[0];
  if (ocrJson) form.append("ocr_json", ocrJson);
  form.append("use_werk24", useWerk24Input.checked ? "true" : "false");
  form.append("confirm_upload_to_werk24", confirmWerk24Input.checked ? "true" : "false");
  form.append("use_cached_werk24", useCachedWerk24Input.checked ? "true" : "false");
  form.append("use_paddleocr", usePaddleOcrInput.checked ? "true" : "false");
  form.append("use_sample_ocr", useSampleOcrInput.checked ? "true" : "false");

  processButton.disabled = true;
  setBackendStatus("后端审查中...");
  try {
    const response = await fetch("/api/reviews", {
      method: "POST",
      body: form,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "后端审查失败");
    }
    state.review = normalizeReview(payload.review);
    state.imageUrl = payload.image_url;
    state.selectedBubbleId = null;
    const warnings = payload.warnings?.length ? `；警告：${payload.warnings.join("；")}` : "";
    setBackendStatus(`审查完成：${payload.candidate_count} 个候选，来源 ${payload.candidate_sources.join(" / ") || "无"}${warnings}`);
    render();
  } catch (error) {
    setBackendStatus(error.message || String(error), true);
  } finally {
    processButton.disabled = false;
  }
});

function normalizeReview(review) {
  const cloned = structuredClone(review);
  cloned.spring_parameters ||= {};
  cloned.technical_requirements ||= [];
  cloned.review_results ||= [];
  cloned.balloons ||= [];
  cloned.manual_confirmations ||= {};
  return cloned;
}

function render() {
  renderCanvas();
  renderPanel();
  exportButton.disabled = !state.review;
  confirmAllButton.disabled = !state.review;
}

function renderCanvas() {
  canvas.innerHTML = "";

  if (!state.imageUrl) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "未加载图纸";
    canvas.appendChild(empty);
    return;
  }

  const img = document.createElement("img");
  img.src = state.imageUrl;
  img.alt = "drawing";
  img.onload = () => {
    state.imageSize = { width: img.naturalWidth, height: img.naturalHeight };
    placeBubbles();
  };
  canvas.appendChild(img);
}

function placeBubbles() {
  const bubbles = state.review?.balloons || [];
  bubbles.forEach((bubble, index) => {
    const node = document.createElement("button");
    node.className = `bubble ${bubble.status || "need_review"}`;
    node.classList.toggle("selected", bubble.bubble_id === state.selectedBubbleId);
    node.textContent = bubble.bubble_id;
    node.title = `${bubble.label}: ${bubble.value}\n${bubble.message || ""}`;

    const pos = getBubblePosition(bubble, index);
    node.style.left = `${pos.x}px`;
    node.style.top = `${pos.y}px`;
    node.addEventListener("click", () => {
      state.selectedBubbleId = bubble.bubble_id;
      renderPanel();
      renderCanvas();
    });
    canvas.appendChild(node);
  });
}

function getBubblePosition(bubble, index) {
  const image = state.imageSize || { width: 1200, height: 800 };
  const position = bubble.position || {};

  if (position.coordinate_type === "normalized" && position.x != null && position.y != null) {
    return {
      x: position.x * image.width,
      y: position.y * image.height,
    };
  }

  if (position.coordinate_type === "pixel" && position.x != null && position.y != null) {
    return {
      x: position.x,
      y: position.y,
    };
  }

  const columns = 3;
  const col = index % columns;
  const row = Math.floor(index / columns);
  return {
    x: Math.max(24, image.width - 210 + col * 52),
    y: 28 + row * 52,
  };
}

function renderPanel() {
  const review = state.review;
  if (!review) {
    summary.textContent = "等待加载审查结果。";
    statusList.innerHTML = "";
    fieldEditor.innerHTML = emptyText("未加载参数");
    requirementEditor.innerHTML = emptyText("未加载技术要求");
    bubbleList.innerHTML = "";
    ruleList.innerHTML = "";
    return;
  }

  refreshDerivedStatus(review);
  const info = review.drawing_summary || {};
  summary.textContent = info.summary || "";

  statusList.innerHTML = "";
  addStatus("图纸", info.drawing_name || "-");
  addStatus("图号", info.drawing_no || "-");
  addStatus("版本", info.version || "-");
  addStatus("状态", info.overall_status || "-");
  addStatus("ERP", review.erp_ready ? "允许" : "阻断");

  renderFields(review);
  renderRequirements(review);
  renderBubbles(review);
  renderRules(review);
}

function renderFields(review) {
  fieldEditor.innerHTML = "";
  const params = review.spring_parameters || {};

  REQUIRED_FIELDS.forEach((field) => {
    fieldEditor.appendChild(fieldRow(field, params[field] || blankParam()));
  });

  (params.load_points || []).forEach((point, index) => {
    fieldEditor.appendChild(loadPointRow(point, index));
  });
}

function fieldRow(field, param) {
  const row = document.createElement("div");
  row.className = "field-row";
  row.dataset.field = field;
  const confidence = Math.round((Number(param.confidence) || 0) * 100);
  row.innerHTML = `
    <div class="field-main">
      <label>${escapeHtml(FIELD_LABELS[field] || field)}
        <input value="${escapeHtml(formatFieldInput(param))}" data-role="value">
      </label>
      <label>公差
        <input value="${escapeHtml(formatTolerance(param))}" data-role="tolerance">
      </label>
    </div>
    <div class="field-meta">
      <span>${escapeHtml((param.source || []).join(" / ") || "-")}</span>
      <span>${confidence}%</span>
      <button type="button" data-role="confirm">${param.need_human_review ? "确认" : "已确认"}</button>
    </div>
    <p>${escapeHtml(param.evidence || param.suggested_region || "")}</p>
  `;

  row.querySelector('[data-role="value"]').addEventListener("change", (event) => {
    param.value = parseValue(event.target.value, param.value);
    markParamEdited(param);
    syncBubbleValue(field, param.value);
    renderPanel();
  });
  row.querySelector('[data-role="tolerance"]').addEventListener("change", (event) => {
    applyTolerance(param, event.target.value);
    markParamEdited(param);
    renderPanel();
  });
  row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
    confirmParam(param, field);
    renderPanel();
  });
  return row;
}

function loadPointRow(point, index) {
  const row = document.createElement("div");
  row.className = "field-row";
  row.dataset.field = `load_point_${index}`;
  row.innerHTML = `
    <div class="field-main three">
      <label>载荷点
        <input value="${escapeHtml(point.label || `F${index + 1}`)}" data-role="label">
      </label>
      <label>高度 mm
        <input value="${escapeHtml(point.height ?? "")}" data-role="height">
      </label>
      <label>力值 N
        <input value="${escapeHtml(point.force ?? "")}" data-role="force">
      </label>
    </div>
    <div class="field-meta">
      <span>${escapeHtml((point.source || []).join(" / ") || "-")}</span>
      <span>${Math.round((Number(point.confidence) || 0) * 100)}%</span>
      <button type="button" data-role="confirm">${point.need_human_review ? "确认" : "已确认"}</button>
    </div>
    <p>${escapeHtml(point.evidence || "")}</p>
  `;

  row.querySelector('[data-role="label"]').addEventListener("change", (event) => {
    point.label = event.target.value.trim();
    markParamEdited(point);
    renderPanel();
  });
  row.querySelector('[data-role="height"]').addEventListener("change", (event) => {
    point.height = parseValue(event.target.value, point.height);
    markParamEdited(point);
    renderPanel();
  });
  row.querySelector('[data-role="force"]').addEventListener("change", (event) => {
    point.force = parseValue(event.target.value, point.force);
    markParamEdited(point);
    renderPanel();
  });
  row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
    confirmParam(point, `load_point_${index}`);
    renderPanel();
  });
  return row;
}

function renderRequirements(review) {
  requirementEditor.innerHTML = "";
  if (!review.technical_requirements?.length) {
    requirementEditor.innerHTML = emptyText("未识别技术要求");
    return;
  }

  review.technical_requirements.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "requirement-row";
    row.innerHTML = `
      <label>${escapeHtml(TECH_LABELS[item.type] || item.type || "技术要求")}
        <textarea data-role="content">${escapeHtml(item.content || "")}</textarea>
      </label>
      <div class="field-meta">
        <span>${escapeHtml((item.source || []).join(" / ") || "-")}</span>
        <span>${Math.round((Number(item.confidence) || 0) * 100)}%</span>
        <button type="button" data-role="confirm">${item.need_human_review ? "确认" : "已确认"}</button>
      </div>
    `;
    row.querySelector('[data-role="content"]').addEventListener("change", (event) => {
      item.content = event.target.value.trim();
      confirmParam(item, `technical_${index}`);
      renderPanel();
    });
    row.querySelector('[data-role="confirm"]').addEventListener("click", () => {
      confirmParam(item, `technical_${index}`);
      renderPanel();
    });
    requirementEditor.appendChild(row);
  });
}

function renderBubbles(review) {
  bubbleList.innerHTML = "";
  (review.balloons || []).forEach((bubble) => {
    const item = compactItem(
      `${bubble.bubble_id} ${bubble.label}`,
      bubble.value,
      bubble.evidence || bubble.suggested_region,
      bubble.status,
    );
    item.classList.toggle("selected", bubble.bubble_id === state.selectedBubbleId);
    item.addEventListener("click", () => {
      state.selectedBubbleId = bubble.bubble_id;
      render();
    });
    bubbleList.appendChild(item);
  });
}

function renderRules(review) {
  ruleList.innerHTML = "";
  (review.review_results || []).forEach((rule) => {
    ruleList.appendChild(compactItem(
      `${rule.rule_id} ${rule.rule_name}`,
      rule.message,
      `严重级别：${rule.severity}`,
      rule.status,
    ));
  });
}

function addStatus(label, value) {
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = label;
  dd.textContent = value;
  statusList.append(dt, dd);
}

function compactItem(title, value, detail, status) {
  const item = document.createElement("div");
  item.className = "item";
  item.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(value || "")}</span>
    <p>${escapeHtml(detail || "")}</p>
    <em class="tag ${escapeHtml(status || "need_review")}">${escapeHtml(status || "need_review")}</em>
  `;
  return item;
}

function refreshDerivedStatus(review) {
  const requiredMissing = REQUIRED_FIELDS.filter((field) => {
    const value = review.spring_parameters?.[field]?.value;
    return value == null || value === "";
  });
  review.missing_fields = requiredMissing;
  const hasBlockingRule = review.review_results.some((rule) => {
    return ["fail", "missing", "need_review"].includes(rule.status);
  });
  review.human_review_required = hasHumanReview(review);
  review.erp_ready = !hasBlockingRule && !review.human_review_required && requiredMissing.length === 0;
  review.erp_block_reason = review.erp_ready ? "" : review.erp_block_reason || "存在待确认字段或阻断规则。";

  if (review.drawing_summary) {
    review.drawing_summary.overall_status = review.erp_ready
      ? (review.review_results.some((rule) => rule.status === "warning") ? "warning" : "pass")
      : "need_review";
    review.drawing_summary.summary = review.erp_ready
      ? "工程师已确认，审查结果可进入 ERP 前置流程。"
      : "当前审查状态为 need_review，存在需要人工确认的字段，暂不允许自动进入 ERP。";
  }
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

function setBackendStatus(text, isError = false) {
  backendStatus.textContent = text;
  backendStatus.classList.toggle("error", isError);
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

function emptyText(text) {
  return `<div class="empty small">${escapeHtml(text)}</div>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

render();
