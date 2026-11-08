/* Shared state for the execution-standard controls and versioned suggestions. */
(() => {
  const VERSION = "spring-standardization/v2";
  const COLD = "GB/T 1239.2-2009", HOT = "GB/T 23934-2015";
  const OPTIONS = [{ value: COLD, label: `冷卷 · ${COLD}` }, { value: HOT, label: `热卷 · ${HOT}` }];
  const FIELDS = ["material", "wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "total_coils", "active_coils", "support_coils", "end_type", "end_grinding", "pitch", "spring_rate", "controlled_diameter_field", "accuracy_grade", "diameter_accuracy_grade", "free_length_accuracy_grade", "load_accuracy_grade", "stiffness_accuracy_grade"];
  const manual = (selection) => ["human_selected", "manual"].includes(selection?.selection_source);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  function resolve(review) {
    const parameters = review.spring_parameters || {}, current = review.standard_selection || {};
    if (manual(current)) return current;
    if (current.selected_standard && !current.selection_source) return current;
    let selected = current.selected_standard || review.accuracy_inference?.standard_no || null;
    let source = current.selection_source || "missing";
    const drawing = String(parameters.standard_no?.value || "").replace(/\s/g, "");
    if (/^GB\/?T1239\.2(?:[-—－]2009)?$/i.test(drawing)) { selected = COLD; source = "drawing_standard_no"; }
    else if (/^GB\/?T23934(?:[-—－](?:2014|2015))?$/i.test(drawing)) { selected = HOT; source = "drawing_standard_no"; }
    else if (!drawing || /4357|5311|1222|18983/.test(drawing)) {
      const wire = parameters.wire_diameter || {};
      const factor = { mm: 1, cm: 10, m: 1000, in: 25.4, inch: 25.4, 毫米: 1 }[String(wire.unit || "mm").toLowerCase()];
      const value = Number(wire.value) * factor;
      if (Number.isFinite(value) && value > 0) { selected = value < 8 ? COLD : HOT; source = "wire_diameter_threshold"; }
    }
    const metadata = { ...(current.metadata || {}) };
    metadata.drawing_standard ??= clone(parameters.standard_no || {});
    review.standard_selection = { ...current, selected_standard: selected, selection_source: source, metadata };
    return review.standard_selection;
  }
  function select(review, selected) {
    if (![COLD, HOT].includes(selected)) return false;
    const previous = resolve(review);
    review.standard_selection = { ...previous, selected_standard: selected, selection_source: "human_selected", human_confirmed: true,
      need_human_review: false, rules_available: true, status: "applicable", confirmed_at: new Date().toISOString(), reason: "按用户选择的执行标准计算。" };
    const accuracy = review.spring_parameters.accuracy_grade ||= { value: null, need_human_review: true };
    if (selected === COLD && /^T\s*级?$/i.test(accuracy.value || "")) {
      Object.assign(accuracy, { value: null, source: ["human_selected"], requires_selection: true, need_human_review: true });
      review.accuracy_inference ||= {};
      review.accuracy_inference.selection_mode = "manual";
      delete (review.manual_confirmations || {}).accuracy_grade;
    }
    return true;
  }
  function inputs(review) {
    const parameters = review.spring_parameters || {}, values = {};
    for (const field of FIELDS) {
      const item = parameters[field] || {};
      values[field] = { value: item.value ?? null, unit: item.unit ?? null, stale: Boolean(item.derived_value_stale) };
    }
    values.wire_diameter.tolerance_upper = parameters.wire_diameter?.tolerance_upper ?? null;
    values.load_points = (parameters.load_points || []).map(point => Object.fromEntries(["load_point_id", "label", "force", "force_unit", "height", "height_unit"].map(key => [key, point[key] ?? null])));
    const source = parameters.accuracy_grade?.source || [];
    return { version: VERSION, standard: review.standard_selection?.selected_standard ?? null,
      manual_grade: (Array.isArray(source) ? source : [source]).some(s => ["human_selected", "manual"].includes(s)), parameters: values };
  }
  const fingerprint = (review) => AccuracyInference.fingerprint(inputs(review));
  function fresh(review) {
    const context = review.standardization_context || {};
    return context.version === VERSION && context.input_fingerprint === fingerprint(review);
  }
  function invalidate(review, force = false) {
    const results = review.standardization_results || [];
    if (!results.length || !force && fresh(review)) return false;
    results.forEach(item => Object.assign(item, { status: "stale", need_human_review: true }));
    for (const turn of review.standardization_chat || []) if (turn.standardization_batch) turn.standardization_batch.status = "stale";
    review.derived_parameters_stale = true;
    return true;
  }
  const fieldLabels = { material: "材料", wire_diameter: "线径", outer_diameter: "外径", inner_diameter: "内径", mean_diameter: "中径",
    free_length: "自由高度", total_coils: "总圈数", active_coils: "有效圈数", support_coils: "支承圈数", spring_rate: "刚度",
    accuracy_grade: "精度等级", diameter_accuracy_grade: "直径精度等级", free_length_accuracy_grade: "自由高度精度等级",
    load_accuracy_grade: "载荷精度等级", stiffness_accuracy_grade: "刚度精度等级", pitch: "节距", end_type: "端部形式", end_grinding: "端面磨削",
    standard_no: "执行标准", perpendicularity: "垂直度", straightness: "直线度" };
  function fieldLabel(field) {
    const load = String(field).match(/^load_points\.(.+)\.force$/);
    return fieldLabels[field] || (load ? `${load[1]} 力值` : String(field));
  }
  const unique = values => [...new Set((values || []).filter(Boolean).map(String))];
  function affectedTargets(item, review) {
    return item.target_field === "load_points"
      ? (review.spring_parameters?.load_points || []).map((point, index) => `load_points.${point.label || `F${index + 1}`}.force`)
      : item.target_field ? [item.target_field] : [];
  }
  function rootMissingFields(item, review, rateCalculation) {
    const missing = unique(item.metadata?.missing_fields);
    if (Array.isArray(item.metadata?.root_missing_fields)) return unique(item.metadata.root_missing_fields);
    let rateMissing;
    if (rateCalculation) rateMissing = rateCalculation.missing_fields || Object.keys(rateCalculation.inputs || {}).filter(field => rateCalculation.inputs[field] == null);
    else rateMissing = review.spring_parameters?.spring_rate?.formula_calculation_missing_fields || [];
    return unique(missing.flatMap(field => field === "spring_rate" && rateMissing.length ? rateMissing : [field]));
  }
  function hasValue(review, field) {
    const load = String(field).match(/^load_points\.(.+)\.force$/);
    const value = load ? review.spring_parameters?.load_points?.find(point => point.label === load[1])?.force : review.spring_parameters?.[field]?.value;
    return value != null && String(value).trim() !== "";
  }
  function navigationLabel(review, field) {
    return fieldLabels[field] || /^load_points\.(.+)\.force$/.test(field) ? `${hasValue(review, field) ? "核对" : "补充"}${fieldLabel(field)}` : "定位参数";
  }
  function describeDiagnostic(group, review) {
    const roots = group.root_missing_fields, targets = group.affected_fields;
    const loadLabels = targets.map(target => target.match(/^load_points\.(.+)\.force$/)?.[1]).filter(Boolean);
    const affected = loadLabels.length === targets.length ? `${loadLabels.join("、")} 的力值公差` : `${targets.map(fieldLabel).join("、")}的标准公差`;
    const names = roots.map(fieldLabel).join("、"), viaRate = group.missing_fields.includes("spring_rate") && !roots.includes("spring_rate");
    let message, calculation, resolution;
    if (roots.length) {
      const prefix = roots.some(field => hasValue(review, field)) ? `需补充或核对${names}` : `缺少${names}`;
      message = `${prefix}，${viaRate ? "无法计算刚度，因此" : ""}${affected}尚未生成。`;
      calculation = viaRate ? `刚度计算需要${names}；载荷公差计算依赖刚度。` : `公差计算需要有效的${names}。`;
      const operation = roots.some(field => hasValue(review, field)) ? "补充或核对" : "补充";
      resolution = `${operation}${names}后重新标准化${viaRate ? "，也可直接填写刚度或手填力值公差。" : group.missing_fields.includes("spring_rate") ? "，或手填力值公差。" : "，或手填公差。"}`;
      if (roots.includes("material") && hasValue(review, "material")) calculation += "当前材料未匹配可用剪切模量，请核对材料。";
    } else {
      message = group.basis || "当前规则无法计算，请核对输入或手填公差。";
      calculation = "当前规则未形成唯一可应用值。";
      resolution = "请按上述规则说明核对参数，或手填公差。";
    }
    const basis = roots.length && /缺少有效计算依据|缺少有效载荷、精度等级或有效圈数/.test(group.basis) ? "" : group.basis;
    return { ...group, basis, category: "standardization", fields: roots.length ? roots : targets, message, calculation,
      explanation: "补齐后重新生成建议；当前公差保持不变。", customer_question: resolution, resolution, via_spring_rate: viaRate };
  }
  function diagnosticGroups(review, rateCalculation = null) {
    if (!fresh(review)) return [];
    const results = review.standardization_results || [], groups = new Map(), validTargets = new Set();
    for (const item of results) if (["suggested", "llm_suggested", "human_confirmed"].includes(item.status)
      && [item.suggested_value, item.suggested_tolerance_upper, item.suggested_tolerance_lower].some(value => value != null)) {
      affectedTargets(item, review).forEach(target => validTargets.add(target));
    }
    for (const [index, item] of results.entries()) {
      if (["suggested", "llm_suggested", "human_confirmed", "stale"].includes(item.status) || item.target_field === "standard_no"
        || item.metadata?.value_kind === "reference_limit" || item.rule_id === "GBT1239.2-SOLID") continue;
      const targets = affectedTargets(item, review).filter(target => !validTargets.has(target));
      if (!targets.length) continue;
      const missing = unique(item.metadata?.missing_fields), roots = rootMissingFields(item, review, rateCalculation);
      const basis = String(item.basis || ""), rule = String(item.rule_id || `STANDARDIZATION-DIAGNOSTIC-${index + 1}`);
      const severity = ["need_context", "rules_pending", "unmapped"].includes(item.status) ? "needs_input" : "warning";
      const kind = targets.every(target => /^load_points\.(.+)\.force$/.test(target)) ? "load" : targets;
      const key = JSON.stringify([rule, severity, kind, [...roots].sort(), missing.includes("spring_rate"), roots.length ? "" : basis]);
      if (!groups.has(key)) groups.set(key, { rule_id: rule, severity, missing_fields: missing, root_missing_fields: roots, affected_fields: [], basis });
      groups.get(key).affected_fields = unique([...groups.get(key).affected_fields, ...targets]);
    }
    return [...groups.values()].map(group => describeDiagnostic(group, review));
  }
  function report(review, rateCalculation = null) {
    const results = review?.standardization_results || [], grouped = new Map();
    const stale = results.length > 0 && (!fresh(review) || results.some(item => item.status === "stale"));
    for (const item of results) {
      if (!item?.target_field || item.target_field === "standard_no" || item.metadata?.value_kind === "reference_limit" || item.rule_id === "GBT1239.2-SOLID") continue;
      const targets = affectedTargets(item, review);
      for (const target of targets) {
        if (!grouped.has(target)) grouped.set(target, []);
        grouped.get(target).push(item);
      }
    }
    let generated = 0;
    const diagnostics = [], issues = stale ? [] : diagnosticGroups(review, rateCalculation);
    for (const [target, items] of grouped) {
      const valid = items.some(item => ["suggested", "llm_suggested", "human_confirmed"].includes(item.status)
        && [item.suggested_value, item.suggested_tolerance_upper, item.suggested_tolerance_lower].some(value => value != null));
      if (!stale && valid) { generated++; continue; }
      const item = items.find(item => item.metadata?.missing_fields?.length) || items[0];
      const missing = item.metadata?.missing_fields || [];
      const issue = issues.find(issue => issue.affected_fields.includes(target));
      const individual = issue && describeDiagnostic({ ...issue, affected_fields: [target] }, review);
      const reason = stale ? "标准化结果待更新，请重新标准化。" : individual ? `${individual.message}${individual.resolution}` : item.basis || "当前规则无法计算，请手填公差。";
      diagnostics.push({ target_field: target, label: fieldLabel(target), reason, stale, missing_fields: missing, root_missing_fields: issue?.root_missing_fields || [], fields: issue?.fields || [] });
    }
    return { generated, failed: stale ? 0 : diagnostics.length, diagnostics, issues, stale,
      message: stale ? "待重新标准化" : `已生成 ${generated} 项，${diagnostics.length} 项未能生成` };
  }
  globalThis.ExecutionStandards = { VERSION, COLD, HOT, OPTIONS, resolve, select, inputs, fingerprint, fresh, invalidate, manual, report, diagnosticGroups, navigationLabel };
})();
