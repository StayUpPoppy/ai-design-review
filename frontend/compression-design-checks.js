/* Draft calculations mirror standardizers/design_checks.py; shared fixtures verify parity. */
(() => {
  const VERSION = "compression-design-v2";
  const PITCH_FIELDS = ["free_length", "wire_diameter", "active_coils", "total_coils", "support_coils", "end_type", "end_grinding", "pitch_type"];
  const SUPPORT_FIELDS = ["total_coils", "active_coils", "end_type"];
  const LENGTH_UNITS = { mm: 1, "毫米": 1, cm: 10, m: 1000, in: 25.4, inch: 25.4, "英寸": 25.4 };
  const FORCE_UNITS = { n: 1, "牛": 1, kn: 1000, kgf: 9.80665 };
  const raw = (item) => item && typeof item === "object" ? item.value : item;
  const empty = (value) => value == null || typeof value === "string" && !value.trim();
  const number = (value) => {
    if (!["number", "string"].includes(typeof value) || empty(value)) return null;
    if (typeof value === "string" && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  };
  const sources = (item) => (Array.isArray(item?.source) ? item.source : [item?.source]).filter(Boolean).map((v) => String(v).toLowerCase());
  const safe = (calculate) => number(calculate());
  const humanOverride = (item) => Boolean(item?.human_modified) || sources(item).some((s) => s.startsWith("human") && s !== "human_confirmed" || ["manual", "manual_input", "standardization_chat", "ai_chat"].includes(s));
  const sameInputs = (old, current) => old && Object.entries(current).every(([key, value]) => ["model_version", "model_id"].includes(key) || old[key] === value);
  function preserveCandidate(item, calculation) {
    const stale = calculation.value == null || !sameInputs(item.formula_calculation_inputs, calculation.inputs);
    item.derived_value_stale = stale;
    item.formula_recommendation_stale = stale;
    if (stale) { item.formula_recalculation_candidate = calculation; item.formula_calculation_reason = "计算依据已变化或无法验证，请应用新候选值后重新确认"; }
    else { delete item.formula_recalculation_candidate; delete item.formula_calculation_reason; }
  }
  function solidHeightKind(item) {
    if (!item || typeof item !== "object") return empty(item) ? "missing" : "unknown";
    if (humanOverride(item)) return "input_height";
    if (["reference_limit", "input_height", "nominal_estimate"].includes(item.value_kind)) return item.value_kind;
    if (item.formula_calculation_kind === "nominal_solid_height") return "nominal_estimate";
    if (/Hb.*dmax/i.test(item.formula || "") || /压并高度上限|Hb\s*[≤<]/.test(item.evidence || "")) return "reference_limit";
    if (item.formula_calculation_kind === "solid_height" || sources(item).some((s) => ["formula_calculation", "derived"].includes(s) || s.endsWith("formula_suggestion_applied"))) return "reference_limit";
    if (empty(item.value) && !item.derived_value_stale && !sources(item).some((s) => /^(human|manual)/.test(s))) return "missing";
    if (sources(item).some((s) => /^(qwen|human|manual|vision|drawing|ocr)/.test(s))) return "input_height";
    return empty(item.value) ? "missing" : "unknown";
  }
  function fresh(params, field, path = []) {
    if (path.includes(field)) return false;
    const item = params[field];
    if (!item || typeof item !== "object") return true;
    if (item.derived_value_stale || item.formula_recommendation_stale && !humanOverride(item)) return false;
    return !sources(item).some((s) => ["formula_calculation", "derived"].includes(s)) || humanOverride(item)
      || (item.source_fields || []).every((s) => {
        if (s === "pitch_type") return true;
        const parent = params[s];
        if (field !== "pitch" && (!(s in params) || empty(raw(parent)))) return false;
        if (field !== "pitch" && ["wire_diameter", "mean_diameter", "outer_diameter", "inner_diameter", "free_length", "active_coils", "total_coils", "support_coils"].includes(s)) {
          const value = number(raw(parent));
          if (value == null || value <= 0) return false;
          const unit = String(parent?.unit || (s.includes("coils") ? "turns" : "mm")).trim().toLowerCase();
          if (s.includes("coils") ? !["turns", "turn", "圈"].includes(unit) : !(unit in LENGTH_UNITS)) return false;
        }
        return fresh(params, s, [...path, field]);
      });
  }
  function input(params, field, notes, length = false) {
    const item = params[field];
    if (!fresh(params, field)) { notes[field] = `${field} 的推导值已失效或存在循环依赖`; return null; }
    let value = number(raw(item));
    if (value == null || value <= 0) {
      notes[field] = empty(raw(item)) ? `待补充 ${field}` : `${field} 必须为有限正数`; return null;
    }
    const unit = String(item?.unit || (length ? "mm" : "turns")).trim().toLowerCase();
    const factor = length ? LENGTH_UNITS[unit] : ["turns", "turn", "圈", ""].includes(unit) ? 1 : null;
    if (factor == null) { notes[field] = `${field} 不支持单位 ${unit}`; return null; }
    value *= factor;
    if (!Number.isFinite(value)) { notes[field] = `${field} 超出计算范围`; return null; }
    return value;
  }
  function endType(value) {
    const text = String(value || "");
    const key = text.toLowerCase().replaceAll("-", "_").replaceAll(" ", "");
    if (["not_tight", "nottight", "open", "open_end"].includes(key) || /不并紧|开口|开放|不闭口/.test(text)) return "两端不并紧";
    if (["tight", "closed", "closed_end", "closed_and_ground"].includes(key) || /两端并紧|双并紧|并紧|双闭口|闭口|闭合|压紧/.test(text)) return "两端并紧";
    return null;
  }
  function activeCalculation(params) {
    const notes = {}, total = input(params, "total_coils", notes), end = endType(raw(params.end_type)), grinding = endGrinding(raw(params.end_grinding));
    let support = input(params, "support_coils", notes), value = null, formula = "", reason = "", fields = ["total_coils", "end_type"];
    if (end === "两端不并紧") {
      fields.push("end_grinding");
      if (grinding && total != null) { value = total - (grinding === "两端磨削" ? 1 : 0); formula = grinding === "两端磨削" ? "total_coils - 1" : "total_coils"; }
      else reason = "需明确端面磨削方式与总圈数";
    } else if (end === "两端并紧") {
      fields.push("support_coils");
      if (support == null && empty(raw(params.support_coils)) && !humanOverride(params.support_coils) && fresh(params, "support_coils")) support = 1;
      if (total != null && support != null) { value = total - 2 * support; formula = "total_coils - 2 * support_coils"; }
      else reason = "支承圈数或总圈数无效";
    } else reason = "端部条件或圈数无效";
    if (value != null && (!Number.isFinite(value) || value <= 0)) { value = null; reason = "有效圈数必须为有限正数"; }
    const inputs = end === "两端不并紧" ? { total_coils: total, end_type: end, end_grinding: grinding } : { total_coils: total, end_type: end, support_coils: support };
    return { value, unit: "turns", formula, basis: end === "两端不并紧" ? grinding === "两端磨削" ? "两端不并紧、磨平：有效圈数 = 总圈数 - 1。" : "两端不并紧、不磨平：有效圈数 = 总圈数。" : `两端并紧：有效圈数 = 总圈数 - 2 × 单端支承圈数；当前单端支承圈数为 ${support} 圈。`, reason, source_fields: fields, inputs };
  }
  function applyActiveCoils(review) {
    const params = review.spring_parameters || {}, item = params.active_coils;
    if (humanOverride(item) || item && !sources(item).includes("company_active_coil_rule") && (item.need_human_review === false || !empty(raw(item)) && !sources(item).includes("solidworks_protocol_default"))) return;
    const calculation = activeCalculation(params);
    if (item?.need_human_review === false) {
      if (!item.formula_calculation_inputs && calculation.value != null && number(item.value) === calculation.value) item.formula_calculation_inputs = calculation.inputs;
      preserveCandidate(item, calculation); return;
    }
    if (calculation.value == null && !sources(item).includes("company_active_coil_rule")) return;
    const target = item && typeof item === "object" ? item : (params.active_coils = {});
    Object.assign(target, { value: calculation.value == null ? null : Number(calculation.value.toFixed(4)), unit: "turns", source: ["company_active_coil_rule"], need_human_review: true,
      derived_rule_id: "COMPANY-ACTIVE-COILS-END-CONDITION-V2", derived_formula: calculation.formula, evidence: calculation.basis, source_fields: calculation.source_fields,
      formula_calculation_inputs: calculation.inputs, derived_value_stale: calculation.value == null, formula_recommendation_stale: false });
    delete target.formula_recalculation_candidate;
  }
  function calculateReferenceHeight(params) {
    const notes = {}, total = input(params, "total_coils", notes), d = input(params, "wire_diameter", notes, true), grinding = endGrinding(raw(params.end_grinding));
    const missing = [total == null ? "total_coils" : null, d == null ? "wire_diameter" : null, !grinding ? "end_grinding" : null].filter(Boolean);
    if (missing.length) return { status: "missing_context", value: null, unit: "mm", formula: "", basis: "缺少总圈数、线径或端面磨削方式，无法计算压并高度参考值。", reason: "缺少压并高度公式输入：" + missing.join(", "), missing_fields: missing, source_fields: [], inputs: {} };
    const item = params.wire_diameter || {}, upperRaw = item.tolerance_upper, upper = number(upperRaw), factor = LENGTH_UNITS[String(item.unit || "mm").trim().toLowerCase()];
    if (!empty(upperRaw) && upper == null || item.tolerance_input_draft) return { status: "missing_context", value: null, unit: "mm", formula: "", basis: "线径上偏差无效，请核对。", reason: "线径上偏差无效，请核对", missing_fields: ["wire_diameter"], source_fields: [], inputs: {} };
    const wireUpper = upper == null ? null : upper * factor, maxWire = d + (wireUpper || 0);
    if (!Number.isFinite(maxWire) || maxWire <= 0) return { status: "missing_context", value: null, unit: "mm", formula: "", basis: "线径最大值必须为有限正数。", reason: "线径最大值必须为有限正数", missing_fields: ["wire_diameter"], source_fields: [], inputs: {} };
    const ground = grinding === "两端磨削", round = (v) => Number(v.toFixed(4));
    const value = safe(() => (ground ? total : total + 1.5) * maxWire);
    return { status: value == null ? "missing_context" : "calculated", value: value == null ? null : round(value), unit: "mm", formula: ground ? "Hb = n1 * dmax" : "Hb = (n1 + 1.5) * dmax",
      basis: `${ground ? "端面磨削约3/4圈适用：压并高度上限参考 Hb ≤ n1 * dmax。" : "两端不磨：压并高度上限参考 Hb ≤ (n1 + 1.5) * dmax。"} n1=${round(total)}, dmax=${round(maxWire)} mm。${wireUpper == null ? "缺少上偏差，按名义线径计算。" : ""}`,
      missing_fields: [], reason: "", source_fields: ["total_coils", "wire_diameter", "end_grinding"], inputs: { total_coils: round(total), wire_diameter_mm: round(d), wire_tolerance_upper_mm: round(wireUpper || 0), max_wire_diameter_mm: round(maxWire), end_mode: ground ? "ground" : "not_ground" } };
  }
  function applyReferenceHeight(review) {
    const params = review.spring_parameters || {}, old = params.solid_height, kind = solidHeightKind(old), calculation = calculateReferenceHeight(params);
    if (old && typeof old === "object") old.value_kind = kind;
    if (kind === "reference_limit" && old.need_human_review === false) { preserveCandidate(old, calculation); return; }
    if (["input_height", "unknown", "nominal_estimate"].includes(kind)) return;
    if (calculation.value == null && !old) return;
    const target = old && typeof old === "object" ? old : (params.solid_height = {});
    Object.assign(target, { value: calculation.value, unit: "mm", source: ["formula_calculation"], value_kind: "reference_limit", need_human_review: true,
      formula_calculation_kind: "solid_height", formula: calculation.formula, evidence: calculation.basis, source_fields: calculation.source_fields, formula_calculation_inputs: calculation.inputs,
      derived_value_stale: calculation.value == null, formula_recommendation_stale: false, formula_calculation_reason: calculation.reason, formula_calculation_status: calculation.status });
    delete target.formula_recalculation_candidate;
  }
  function endGrinding(value) {
    if ([1, "1", true].includes(value)) return "两端磨削";
    if ([0, "0", false].includes(value)) return "两端不磨削";
    const text = String(value || "");
    const key = text.toLowerCase().replaceAll("-", "_").replaceAll(" ", "");
    if (["not_ground", "notground", "unground", "no", "false"].includes(key) || /不磨|未磨/.test(text)) return "两端不磨削";
    if (["ground", "grounded", "yes", "true", "closed_and_ground"].includes(key) || /磨/.test(text)) return "两端磨削";
    return null;
  }
  function context(params, features = {}) {
    const notes = {}, c = { notes };
    ["wire_diameter", "mean_diameter", "outer_diameter", "inner_diameter", "free_length", "active_coils", "total_coils", "support_coils", "pitch"].forEach((f) => {
      c[f] = input(params, f, notes, !["active_coils", "total_coils", "support_coils"].includes(f));
    });
    if (c.mean_diameter == null && empty(raw(params.mean_diameter)) && fresh(params, "mean_diameter")) {
      const { wire_diameter: d, outer_diameter: outer, inner_diameter: inner } = c;
      const mean = outer != null && inner != null ? safe(() => outer / 2 + inner / 2) : outer != null && d != null ? safe(() => outer - d) : inner != null && d != null ? safe(() => inner + d) : null;
      if (mean != null && mean > 0) { c.mean_diameter = mean; delete notes.mean_diameter; }
    }
    c.end_type = endType(raw(params.end_type));
    c.end_grinding = endGrinding(raw(params.end_grinding));
    if (c.active_coils == null && empty(raw(params.active_coils)) && fresh(params, "active_coils")) {
      const active = !humanOverride(params.active_coils) ? activeCalculation(params).value : null;
      if (active != null && active > 0) { c.active_coils = active; delete notes.active_coils; }
    }
    c.incompatible = "";
    for (const [field, allowed] of Object.entries({ spring_family: ["helical"], spring_shape: ["cylindrical"], wire_section: ["round", "circular"], pitch_type: ["constant"] })) {
      const value = String(raw(features[field]) || "unknown").toLowerCase();
      if (![...allowed, "unknown", ""].includes(value)) { c.incompatible = `普通圆丝圆柱等节距模型不适用于 ${field}=${value}`; break; }
    }
    c.pitch_type = raw(features.pitch_type) || "unknown";
    return c;
  }
  function result(value, unit, formula, fields, c, options = {}) {
    let reason = options.reason || "";
    if (value != null && !Number.isFinite(value)) { value = null; reason = "数值超出计算范围"; }
    return { value, unit, formula, status: value != null ? options.estimated ? "estimated" : "calculated" : "missing_context",
      reason: reason || (value == null ? [...new Set(fields.filter((f) => c[f] == null).map((f) => c.notes[f] || `待补充 ${f}`))].join("；") || "计算输入失效或超出数值范围" : ""),
      basis: options.basis || "理论计算", source_fields: fields, inputs: Object.fromEntries(fields.map((f) => [f, c[f] ?? null])) };
  }
  function independentCoilSource(params, field, path = []) {
    if (path.includes(field)) return false;
    const item = params[field];
    if (!item || typeof item !== "object" || humanOverride(item)) return true;
    const origin = sources(item), parents = item.source_fields || [];
    if (origin.includes("company_active_coil_rule")) return false;
    if (origin.includes("solidworks_protocol_default") && item.need_human_review !== false) return false;
    if (origin.some((s) => ["formula_calculation", "derived", "parameter_change_proposal_derived"].includes(s)) && !parents.length) return false;
    return parents.every((s) => !["support_coils", "total_coils", "active_coils"].includes(s) && independentCoilSource(params, s, [...path, field]));
  }
  function calculateSupportCoils(params, review = {}) {
    const notes = {}, total = input(params, "total_coils", notes), active = input(params, "active_coils", notes);
    const end = endType(raw(params.end_type));
    let value = null, reason = "";
    if (asymmetricSupport(params, review)) reason = "原图明确两端支承结构不对称，不能按两端均分，请人工核对";
    else if (end !== "两端并紧") reason = "需明确两端并紧结构，才能由圈数推导单端支承圈数";
    else if (!["total_coils", "active_coils"].every((f) => independentCoilSource(params, f))) reason = "需要独立的总圈数和有效圈数；不能反推公司默认值或形成循环依赖";
    else if (total != null && active != null) {
      value = (total - active) / 2;
      if (value <= 0) { value = null; reason = "总圈数必须大于有效圈数，请核对圈数"; }
    }
    return result(value, "turns", "单端支承圈数 = (n1 - n) / 2", SUPPORT_FIELDS,
      { total_coils: total, active_coils: active, end_type: end, notes }, { reason, basis: "由独立总圈数和有效圈数推导；待人工确认" });
  }
  const SUPPORT_SNAPSHOT_KEYS = ["value", "unit", "need_human_review", "source", "evidence", "page", "position", "tolerance_upper", "tolerance_lower", "confirmation_snapshot"];
  const copy = (v) => JSON.parse(JSON.stringify(v));
  const supportSnapshot = (item, keys = SUPPORT_SNAPSHOT_KEYS) => Object.fromEntries(keys.filter((k) => k in item).map((k) => [k, copy(item[k])]));
  const recognizedSupport = (item) => sources(item).some((s) => /qwen|ocr|vision|drawing|werk24|pdf_text|cad|dxf|dwg|paddle|azure/.test(s));
  function supportOrigin(item) {
    const text = String(item?.evidence || "");
    if (/计算|推算|推导|相减|差值|默认|假设|derived|calculated|(?:总圈|total).*(?:有效|active).*[=＝]/i.test(text)) return "inferred";
    if (/(?:两端|双端|左右两端).{0,8}(?:合计|共|总)|总支承圈数|支承圈数合计|total\s+support/i.test(text)) return "drawing_total";
    if (/单端|每端|各端|两端各|每一端|per\s*end|each\s*end/i.test(text)
      && (/支承|支撑|support/i.test(text) || /(?:单端|每端|各端|两端各|每一端)\s*[:：]?\s*\d+(?:\.\d+)?\s*圈/.test(text))) return "drawing_single_end";
    return "unknown";
  }
  function asymmetricSupport(params, review = {}) {
    if (params.support_coils?.support_coils_symmetry === "asymmetric") return true;
    const texts = [params.support_coils?.evidence, params.end_type?.evidence, ...(review.technical_requirements || []).map((t) => t.content)].filter(Boolean).map(String);
    return texts.some((text) => {
      if (/两端.{0,12}(?:不对称|非对称|支承圈数不同)|左右端.{0,8}(?:不同|不等)|asymmetric\s+(?:end|support)/i.test(text)) return true;
      const m = text.match(/左端(?:支承)?(?:圈数)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*圈.{0,12}右端(?:支承)?(?:圈数)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*圈/);
      return Boolean(m && Number(m[1]) !== Number(m[2]));
    });
  }
  function prepareSupportCoils(review) {
    const item = review.spring_parameters?.support_coils;
    if (!item || typeof item !== "object") return;
    if (recognizedSupport(item) && !humanOverride(item) && !item.formula_calculation_kind) {
      item.support_coils_origin = supportOrigin(item);
      if (!item.support_coils_original && !empty(item.value)) item.support_coils_original = supportSnapshot(item);
      if (item.support_coils_origin !== "drawing_single_end" && item.need_human_review !== false) item.derived_value_stale = true;
    }
  }
  function applySupportCoils(review) {
    prepareSupportCoils(review);
    const params = review.spring_parameters || {}, old = params.support_coils;
    const item = old && typeof old === "object" ? old : { value: old };
    const formula = item.formula_calculation_kind === "support_coils", c = calculateSupportCoils(params, review);
    const origin = item.support_coils_origin || supportOrigin(item);
    const automatic = formula || recognizedSupport(item) && origin !== "drawing_single_end";
    const protectedValue = humanOverride(item) || origin === "drawing_single_end" || !automatic && !empty(item.value);
    const value = number(c.value), changedInputs = !sameInputs(item.formula_calculation_inputs || item.support_coils_input_baseline, c.inputs);
    const roots = [params.total_coils || {}, params.active_coils || {}];
    const waiting = roots.some((p) => humanOverride(p) && p.need_human_review !== false);
    const confirmed = roots.every((p) => p.need_human_review === false);
    const edited = roots.some(humanOverride) || item.support_coils_recompute_pending === true;
    item.support_coils_input_baseline ??= copy(c.inputs);
    delete item.support_coils_conflict; delete item.support_coils_waiting_confirmation; delete item.support_coils_notice;
    if (protectedValue) {
      if (formula) { delete item.derived_value_stale; delete item.formula_recommendation_stale; }
      if (value != null && number(item.value) != null && Math.abs(Number(item.value) - value) > 1e-9) {
        item.support_coils_conflict = "当前单端支承圈数与 (总圈数－有效圈数)/2 不一致，请核对原图或人工值";
        item.formula_recalculation_candidate = copy(c); item.support_coils_waiting_confirmation = waiting;
      } else { delete item.formula_recalculation_candidate; if (value == null) item.support_coils_notice = c.reason || "缺少有效计算依据"; }
      return;
    }
    if (waiting) {
      Object.assign(item, { derived_value_stale: true, formula_recommendation_stale: true, formula_recalculation_candidate: copy(c),
        support_coils_recompute_pending: true, support_coils_waiting_confirmation: true, formula_calculation_reason: "总圈数和有效圈数当前值均确认后，将自动重算单端支承圈数" });
      return;
    }
    if (item.need_human_review === false && (value == null || !changedInputs || !(confirmed && edited))) { preserveCandidate(item, c); return; }
    if (value == null) {
      if (automatic) Object.assign(item, { derived_value_stale: true, formula_recommendation_stale: true, formula_recalculation_candidate: copy(c), formula_calculation_reason: c.reason || "缺少有效计算依据" });
      else item.support_coils_notice = c.reason || "缺少有效计算依据";
      return;
    }
    const target = old && typeof old === "object" ? old : (params.support_coils = {});
    const before = supportSnapshot(target, [...SUPPORT_SNAPSHOT_KEYS, "formula_calculation_inputs"]);
    const changed = number(target.value) !== Number(value.toFixed(4)) || changedInputs || !formula;
    Object.assign(target, { field: "support_coils", value: Number(value.toFixed(4)), unit: "turns", source: ["formula_calculation"], need_human_review: true,
      confidence: 0.88, formula: c.formula, evidence: c.basis, source_fields: c.source_fields, formula_calculation_kind: "support_coils",
      formula_calculation_status: c.status, formula_calculation_inputs: copy(c.inputs), support_coils_input_baseline: copy(c.inputs), derived_value_stale: false, formula_recommendation_stale: false });
    if (changed) {
      const previous = review.manual_confirmations?.support_coils ?? null;
      delete review.manual_confirmations?.support_coils; delete target.confirmation_snapshot;
      target.support_coils_adjustment = { before, after: { value: target.value, unit: "turns", inputs: copy(c.inputs) }, previous_confirmation: copy(previous),
        reason: confirmed && edited ? "confirmed_coil_inputs_changed" : "support_coils_formula_reconciliation", audit_recorded: false };
    }
    ["formula_recalculation_candidate", "formula_calculation_reason", "support_coils_recompute_pending", "support_coils_waiting_confirmation"].forEach((k) => delete target[k]);
  }
  function geometry(c) {
    const options = c.end_grinding === "两端磨削" ? [[1.5, 1], [2, 1.5], [2.5, 2]] : c.end_grinding === "两端不磨削" ? [[2, 3], [2.5, 3.5]] : [];
    const a = c.support_coils == null ? null : options.find(([count]) => Math.abs(2 * c.support_coils - count) <= 1e-9)?.[1] ?? null;
    let reason = c.incompatible;
    const { end_type: end, end_grinding: grinding, total_coils: total, active_coils: n } = c;
    const model = end === "两端并紧" ? "book_table" : end === "两端不并紧" ? "open_end" : "unknown";
    if (!reason && (model === "unknown" || grinding == null)) reason = "需明确端部形式与端面磨削方式";
    if (!reason && model === "book_table") {
      if (a == null) reason = "需明确端面磨削方式与单端支承圈数，并符合图片公式分档";
      else if (n != null && total != null && Math.abs(total - n - 2 * c.support_coils) > 1e-4) reason = "总圈数、有效圈数与支承圈数不一致，请核对";
    }
    if (!reason && model === "open_end") {
      if (total == null || n == null) reason = (total == null ? c.notes.total_coils : c.notes.active_coils) || "缺少有效圈数或总圈数";
      else if (Math.abs(n - total + (grinding === "两端磨削" ? 1 : 0)) > 1e-4) reason = "有效圈数与不并紧端型关系不一致，请核对";
    }
    return { a, model_id: model, reason: reason || "",
      pitch_fields: model === "book_table" ? PITCH_FIELDS : ["free_length", "wire_diameter", "total_coils", "active_coils", "end_type", "end_grinding", "pitch_type"],
      solid_fields: model === "book_table" ? ["wire_diameter", "active_coils", "support_coils", "end_type", "end_grinding"] : ["wire_diameter", "total_coils", "active_coils", "end_type", "end_grinding"],
      pitch_formula: model === "book_table" ? "t = (H0 - a*d) / n" : grinding === "两端磨削" ? "t = H0 / n1" : "t = (H0 - d) / n1",
      solid_formula: model === "book_table" ? "Hb = d*(n+a)" : grinding === "两端磨削" ? "Hb = n1*d" : "Hb = (n1+1)*d" };
  }
  function calculatePitch(params, features = {}) {
    const c = context(params, features), g = geometry(c);
    let value = null, reason = g.reason;
    const { free_length: h, wire_diameter: d, active_coils: n, total_coils: total } = c;
    if (!reason && h != null && d != null) {
      if (g.model_id === "book_table" && n != null) value = safe(() => (h - g.a * d) / n);
      else if (g.model_id === "open_end" && total != null) value = safe(() => (h - (c.end_grinding === "两端磨削" ? 0 : d)) / total);
    }
    if (value != null) {
      if (!Number.isFinite(value) || value <= d) { value = null; reason = "推算节距必须大于线径，请核对自由高度、圈数与端部结构"; }
    }
    const valueResult = result(value, "mm", g.pitch_formula, g.pitch_fields, c, { reason });
    valueResult.inputs = { ...Object.fromEntries(g.pitch_fields.map((f) => [f, c[f] ?? null])), a: g.model_id === "book_table" ? g.a : null, model_version: VERSION };
    valueResult.model_id = g.model_id;
    valueResult.basis = g.model_id === "book_table" ? "书页公式补算；支承圈数按两端合计；待人工确认" : "不并紧补充公式；Victory Spring 表7.1；待人工确认";
    return valueResult;
  }
  function applyPitch(review) {
    const params = review.spring_parameters || {}, old = params.pitch;
    applySupportCoils(review);
    applyActiveCoils(review);
    applySupportCoils(review);
    applyNominalHeight(review);
    const item = old && typeof old === "object" ? old : { value: old };
    const formula = item.formula_calculation_kind === "pitch";
    const calculation = calculatePitch(params, review.spring_features || {});
    if (humanOverride(item)) {
      if (formula) { delete item.derived_value_stale; delete item.formula_recommendation_stale; }
      return;
    }
    if (formula && item.need_human_review === false) {
      preserveCandidate(item, calculation);
      return;
    }
    if (item.need_human_review === false || !formula && !empty(item.value)) return;
    if (calculation.value == null && !formula) return;
    const target = old && typeof old === "object" ? old : (params.pitch = {});
    const value = calculation.value == null ? null : Number(calculation.value.toFixed(4));
    Object.assign(target, { field: "pitch", value, unit: "mm", source: ["formula_calculation"], need_human_review: true,
      confidence: 0.88, formula: calculation.formula, evidence: calculation.basis, source_fields: [...calculation.source_fields],
      formula_calculation_kind: "pitch", formula_calculation_status: calculation.status,
      formula_calculation_inputs: calculation.inputs, formula_calculation_reason: calculation.reason,
      derived_value_stale: value == null, formula_recommendation_stale: false });
    delete target.formula_recalculation_candidate;
  }
  function calculateNominalHeight(params, features = {}) {
    const c = context(params, features), g = geometry(c), d = c.wire_diameter, n = c.active_coils, total = c.total_coils;
    let value = null;
    if (!g.reason && d != null) {
      if (g.model_id === "book_table" && n != null) value = safe(() => d * (n + g.a));
      else if (g.model_id === "open_end" && total != null) value = safe(() => d * (total + (c.end_grinding === "两端磨削" ? 0 : 1)));
    }
    const calculation = result(value, "mm", g.solid_formula, g.solid_fields, c, { reason: g.reason, estimated: true,
      basis: g.model_id === "book_table" ? "名义估算；书页公式" : "名义估算；不并紧补充公式；Victory Spring 表7.1" });
    calculation.inputs.a = g.model_id === "book_table" ? g.a : null;
    return Object.assign(calculation, { model_id: g.model_id, height_source: g.model_id === "book_table" ? "book_nominal" : "open_nominal" });
  }
  function applyNominalHeight(review) {
    const params = review.spring_parameters || {}, old = params.solid_height, kind = solidHeightKind(old);
    if (["input_height", "unknown"].includes(kind)) return;
    if (kind === "reference_limit" && old.formula_purpose_preserved) { applyReferenceHeight(review); return; }
    const calculation = calculateNominalHeight(params, review.spring_features || {});
    if (kind === "nominal_estimate" && old.need_human_review === false) { preserveCandidate(old, calculation); return; }
    const target = old && typeof old === "object" ? old : (params.solid_height = {});
    if (kind === "reference_limit") {
      const legacy = JSON.parse(JSON.stringify(target));
      if (review.manual_confirmations?.solid_height) {
        legacy.manual_confirmation = review.manual_confirmations.solid_height;
        delete review.manual_confirmations.solid_height;
      }
      Object.keys(target).forEach((key) => delete target[key]);
      target.legacy_reference_limit = legacy;
    }
    Object.assign(target, { field: "solid_height", value: calculation.value == null ? null : Number(calculation.value.toFixed(4)), unit: "mm",
      tolerance_upper: null, tolerance_lower: null, source: ["formula_calculation"], value_kind: "nominal_estimate", need_human_review: true,
      confidence: 0.88, formula: calculation.formula, evidence: calculation.basis, source_fields: calculation.source_fields,
      formula_calculation_kind: "nominal_solid_height", formula_calculation_status: calculation.value == null ? calculation.status : "calculated", formula_calculation_inputs: calculation.inputs,
      formula_calculation_reason: calculation.reason, derived_value_stale: calculation.value == null, formula_recommendation_stale: false });
    delete target.formula_recalculation_candidate;
  }
  const materialKey = (v) => String(v || "").normalize("NFKC").toLowerCase().replace(/[\s\-_]/g, "");
  function materialEntry(value, catalog) {
    const text = String(value ?? "").trim(), key = text.normalize("NFKC").toUpperCase().replace(/[^\p{L}\p{N}]/gu, "");
    if (!key || /^\d+$/.test(key) && !text.includes("#")) return null;
    const matches = (catalog?.items || []).filter((entry) => [entry.display_name, entry.standard_value, ...(entry.aliases || [])]
      .some((alias) => String(alias).normalize("NFKC").toUpperCase().replace(/[^\p{L}\p{N}]/gu, "") === key));
    return matches.length === 1 ? matches[0] : null;
  }
  function materialDisplayValue(value, catalog) {
    return materialEntry(value, catalog)?.display_name || String(value ?? "").trim();
  }
  function materialProfile(params, catalog) {
    const value = materialKey(raw(params.material));
    if (!value) return null;
    const matches = (catalog?.items || []).filter((p) => [p.display_name, p.standard_value, ...(p.aliases || [])].some((v) => materialKey(v) === value));
    return matches.length === 1 ? matches[0] : null;
  }
  const isSolidPoint = (point) => ["fb", "pb", "压并载荷", "压并负荷", "压并力"].includes(String(point.label || "").trim().toLowerCase().replace(/[ _]/g, ""));
  function calculate(params, features = {}, catalog = {}) {
    const c = context(params, features), profile = materialProfile(params, catalog);
    c.material = profile ? raw(params.material) : null;
    c.G = profile?.shear_modulus_mpa ?? null;
    c.rho = profile?.density_g_cm3 ?? null;
    c.notes.material = "请选择已配置的材料";
    const { wire_diameter: d, mean_diameter: mean, free_length: h, active_coils: n, total_coils: total, pitch } = c;
    const index = mean != null && d != null ? safe(() => mean / d) : null;
    const b = h != null && mean != null ? safe(() => h / mean) : null;
    const K = index != null && index > 1 ? safe(() => (4 * index - 1) / (4 * index - 4) + 0.615 / index) : null;
    let rate = c.G != null && d != null && mean != null && n != null ? c.G * d ** 4 / (8 * mean ** 3 * n) : null;
    if (rate != null && (!Number.isFinite(rate) || rate <= 0)) rate = null;
    const alpha = pitch != null && mean != null ? Math.atan2(pitch, Math.PI * mean) : null;
    const length = alpha != null && total != null ? safe(() => Math.PI * mean * total / Math.cos(alpha)) : null;
    const mass = d != null && length != null && c.rho != null ? safe(() => Math.PI * d ** 2 / 4 * length * c.rho * 1e-6) : null;
    const pc = calculatePitch(params, features), g = geometry(c), hbItem = params.solid_height;
    const nominalResult = calculateNominalHeight(params, features), nominal = nominalResult.value;
    const reference = calculateReferenceHeight(params), referenceResult = result(reference.value, "mm", reference.formula.replace(" = ", " ≤ "), reference.source_fields, c, { reason: reference.reason, basis: reference.basis });
    Object.assign(referenceResult, { inputs: reference.inputs, model_id: "gbt_1239_2_limit", height_source: "reference_limit" });
    const kind = solidHeightKind(hbItem);
    let hb = null, hbReason = "", heightSource = "unknown";
    if (["reference_limit", "missing"].includes(kind)) { hb = nominal; hbReason = nominalResult.reason; heightSource = nominalResult.height_source; }
    else if (kind === "nominal_estimate") {
      hb = input(params, "solid_height", c.notes, true);
      if (hb != null) hb = nominal;
      heightSource = nominalResult.height_source;
      if (hb == null) hbReason = c.notes.solid_height || nominalResult.reason || "名义压并高度无效，请核对";
    }
    else if (kind === "input_height") {
      hb = input(params, "solid_height", c.notes, true);
      heightSource = humanOverride(hbItem || {}) ? "manual" : "drawing";
      if (hb == null) hbReason = empty(raw(hbItem)) ? "人工主动清空压并高度，未自动替换" : c.notes.solid_height || "压并高度无效";
    } else hbReason = "压并高度用途无法确认，请核对来源";
    if (hb != null && h != null && (hb <= 0 || hb >= h)) { hb = null; hbReason = "估算压并高度必须满足 0 < Hb < H0，请核对"; }
    c.solid_height = hb;
    const heightBasis = { manual: "人工输入高度", drawing: "图纸标注高度", book_nominal: "书页名义高度", open_nominal: "不并紧名义高度", unknown: "高度来源待核对" }[heightSource];
    const metrics = {
      spring_index: result(index, "", "C = Dm / d", ["mean_diameter", "wire_diameter"], c),
      slenderness_ratio: result(b, "", "b = H0 / Dm", ["free_length", "mean_diameter"], c),
      curvature_factor: result(K, "", "K = (4C-1)/(4C-4) + 0.615/C", ["mean_diameter", "wire_diameter"], c, { reason: index != null && index <= 1 ? "旋绕比必须大于 1" : "" }),
      helix_angle: result(alpha != null ? alpha * 180 / Math.PI : null, "°", "α = atan(t / (π*Dm))", ["pitch", "mean_diameter"], c),
      wire_length: result(length, "mm", "L ≈ π*Dm*n1 / cos(α)", ["pitch", "mean_diameter", "total_coils"], c, { estimated: true, basis: "展开长度近似值" }),
      theoretical_spring_rate: result(rate, "N/mm", "P′ = G*d^4 / (8*Dm^3*n)", ["material", "wire_diameter", "mean_diameter", "active_coils"], c),
      unit_mass: result(mass, "kg", "Q ≈ π*d²*L*ρ/4 × 10⁻⁶", ["material", "wire_diameter", "mean_diameter", "total_coils", "pitch"], c, { estimated: true, basis: "单件重量估算" }),
      nominal_solid_height: nominalResult,
      reference_solid_height_limit: referenceResult,
      solid_height_used: result(hb, "mm", "用于 Pb = P′*(H0-Hb)", ["solid_height"], c, { reason: hbReason, estimated: heightSource.endsWith("nominal"), basis: heightBasis }),
    };
    Object.assign(metrics.solid_height_used, { height_source: heightSource, model_id: heightSource.endsWith("nominal") ? g.model_id : "input_height" });
    const points = params.load_points || [], solidPoints = points.filter(isSolidPoint);
    function stress(point, solid = false) {
      let force = null, estimated = false, reason = "";
      if (!empty(point.force)) {
        force = number(point.force);
        const unit = String(point.force_unit || "N").toLowerCase().trim(), factor = FORCE_UNITS[unit];
        if (force == null || force < 0) { force = null; reason = "力值必须为有限非负数"; }
        else if (factor == null) { force = null; reason = `不支持力值单位 ${unit}`; }
        else force *= factor;
      } else {
        estimated = true;
        const height = solid ? hb : input({ height: { value: point.height, unit: point.height_unit || "mm" } }, "height", c.notes, true);
        if (height == null) reason = solid ? hbReason || "缺少可用压并高度" : c.notes.height || "缺少有效高度";
        else if (h != null && (height > h || hb != null && height < hb || solid && height >= h)) reason = "高度超出有效压缩范围，请核对";
        else if (rate != null && h != null) force = rate * (h - height);
        else reason = "缺少理论刚度或自由高度，无法估算力值";
      }
      const value = force != null && mean != null && d != null && K != null ? safe(() => 8 * force * mean * K / (Math.PI * d ** 3)) : null;
      if (value == null && !reason) reason = metrics.curvature_factor.reason || "缺少中径、线径或可用曲度系数";
      const stressResult = { ...result(value, "MPa", "τ = 8*P*Dm*K / (π*d³)", ["mean_diameter", "wire_diameter", "load_points"], c,
        { reason, estimated, basis: estimated ? "估算载荷；P=P′*(H0-H)" : "已有载荷" }),
        force_n: Number.isFinite(force) ? force : null, load_point_id: point.load_point_id ?? null, label: point.label || "" };
      Object.assign(stressResult.inputs, { force_n: stressResult.force_n, curvature_factor: K, free_length_mm: h,
        theoretical_spring_rate: estimated ? rate : null, solid_height_mm: solid ? hb : null,
        test_height: point.height ?? null, test_height_unit: point.height_unit || "mm" });
      if (solid) {
        Object.assign(stressResult, { height_source: estimated ? heightSource : null, model_id: estimated ? heightSource.endsWith("nominal") ? g.model_id : "input_height" : "provided_load" });
        stressResult.inputs.solid_height_mm = estimated ? hb : null;
        stressResult.basis = estimated ? "估算压并载荷；" + heightBasis : "已有压并载荷";
      }
      return stressResult;
    }
    let solid;
    if (solidPoints.length > 1) {
      solid = result(null, "MPa", "τb = 8*Pb*Dm*K / (π*d³)", [], c, { reason: "存在多个压并载荷点，请核对" });
      solid.status = "ambiguous";
    } else { solid = stress(solidPoints[0] || {}, true); solid.formula = "τb = 8*Pb*Dm*K / (π*d³)"; }
    metrics.solid_stress = solid;
    if (solidPoints.length > 1 || solidPoints.length && !empty(solidPoints[0].force)) Object.assign(metrics.solid_height_used, { value: null, status: "not_required", reason: solidPoints.length === 1 ? "已有明确压并力值时不通过高度估算载荷" : "压并载荷点存在歧义" });
    const work = points.filter((p) => !isSolidPoint(p)).map((p) => stress(p));
    if (c.incompatible) [...Object.entries(metrics).filter(([key]) => !["spring_index", "slenderness_ratio"].includes(key)).map(([, v]) => v), ...work]
      .forEach((v) => Object.assign(v, { value: null, status: "not_applicable", reason: c.incompatible }));
    return { version: VERSION, material_catalog_version: catalog.version || "", material_properties: profile,
      metrics, work_stresses: work, pitch_calculation: pc };
  }
  function applyCandidate(item) {
    const c = item?.formula_recalculation_candidate;
    if (c?.value == null || !Number.isFinite(c.value) || c.value <= 0) return false;
    const company = sources(item).includes("company_active_coil_rule"), reference = solidHeightKind(item) === "reference_limit";
    Object.assign(item, { value: Number(c.value.toFixed(4)), unit: c.unit, formula: c.formula, evidence: c.basis, source_fields: c.source_fields,
      formula_calculation_inputs: c.inputs, source: company ? ["company_active_coil_rule"] : reference ? ["formula_calculation", "reference_limit_applied"] : ["formula_calculation"],
      need_human_review: true, derived_value_stale: false, formula_recommendation_stale: false, formula_calculation_status: c.status || "calculated" });
    if (reference) item.value_kind = "reference_limit";
    if (solidHeightKind(item) === "nominal_estimate") item.formula_calculation_status = "calculated";
    delete item.human_modified;
    delete item.formula_recalculation_candidate;
    delete item.formula_calculation_reason;
    return true;
  }
  globalThis.CompressionDesignChecks = { calculate, calculatePitch, calculateSupportCoils, applySupportCoils, prepareSupportCoils, supportOrigin, calculateReferenceHeight, calculateNominalHeight, activeCalculation, solidHeightKind, applyReferenceHeight, applyNominalHeight, applyCandidate, applyPitch, materialEntry, materialDisplayValue };
})();
