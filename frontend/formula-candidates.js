/* Candidate projection mirrors formula_candidates.py; shared fixtures verify parity. */
(() => {
  const fields = ["pitch", "active_coils", "solid_height"];
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const sources = (item) => (Array.isArray(item?.source) ? item.source : [item?.source]).filter(Boolean).map((v) => String(v).toLowerCase());
  const manual = (item) => item?.human_modified || sources(item).some((s) => s.startsWith("human") && s !== "human_confirmed" || ["manual", "manual_input", "standardization_chat", "ai_chat"].includes(s));
  const stable = (v) => Array.isArray(v) ? `[${v.map(stable).join(",")}]` : v && typeof v === "object"
    ? `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${stable(v[k])}`).join(",")}}` : JSON.stringify(v ?? null);
  function token(v) {
    let hash = 2166136261;
    for (const byte of new TextEncoder().encode(stable(v))) hash = Math.imul(hash ^ byte, 16777619) >>> 0;
    return `fnv1a32:${hash.toString(16).padStart(8, "0")}`;
  }
  function dependencyValue(v) {
    if (Array.isArray(v)) return v.map(dependencyValue);
    if (!v || typeof v !== "object") return v ?? null;
    return Object.fromEntries(["value", "tolerance_upper", "tolerance_lower"].filter((k) => k in v).map((k) => [k, dependencyValue(v[k])]));
  }
  function calculation(review, field) {
    const api = globalThis.CompressionDesignChecks, p = review.spring_parameters || {}, kind = api.solidHeightKind(p.solid_height);
    const c = field === "pitch" ? api.calculatePitch(p, review.spring_features || {}) : field === "active_coils" ? api.activeCalculation(p)
      : kind === "reference_limit" ? api.calculateReferenceHeight(p) : api.calculateNominalHeight(p, review.spring_features || {});
    return { value: Number.isFinite(c.value) ? Number(c.value.toFixed(4)) : null, unit: c.unit, formula: c.formula || "",
      inputs: c.inputs || {}, source_fields: c.source_fields || [], basis: c.basis || "", purpose: field === "solid_height" ? kind : field,
      status: field === "solid_height" && kind === "nominal_estimate" ? "estimated" : "calculated" };
  }
  const identity = (c) => Object.fromEntries(["value", "unit", "formula", "inputs", "purpose"].map((k) => [k, c[k]]));
  const sameInputs = (old, current) => old && Object.entries(current).every(([k, v]) => ["model_version", "model_id"].includes(k) || (old[k] ?? null) === v);
  function build(review, revision = null) {
    if (review?.drawing_summary?.spring_type !== "compression_spring") return [];
    const p = review.spring_parameters || {}, result = [];
    for (const field of fields) {
      const item = p[field];
      if (!item || manual(item)) continue;
      const c = calculation(review, field), kind = c.purpose;
      const owned = field === "active_coils" ? sources(item).includes("company_active_coil_rule") : field === "pitch" ? item.formula_calculation_kind === "pitch" : ["nominal_estimate", "reference_limit"].includes(kind);
      if (!owned || !(item.need_human_review === false || item.formula_recalculation_candidate || item.derived_value_stale || item.formula_recommendation_stale)
        || c.value == null || c.value <= 0 || sameInputs(item.formula_calculation_inputs, c.inputs)) continue;
      const snapshot = Object.fromEntries([...new Set(c.source_fields)].sort().map((f) => [f, dependencyValue(p[f])]));
      result.push({ suggestion_id: `formula_candidate:${field}:${token(identity(c))}`, suggestion_kind: "formula_candidate", formula_candidate: c,
        source: "formula", target_field: field, current_value: item.value ?? null, current_tolerance_upper: item.tolerance_upper ?? null,
        current_tolerance_lower: item.tolerance_lower ?? null, suggested_value: c.value, suggested_tolerance_upper: null, suggested_tolerance_lower: null,
        unit: c.unit, application_mode: "value", rule_id: `FORMULA-CANDIDATE-${field}-${kind}`, basis: c.basis, source_fields: c.source_fields,
        dependency_snapshot: snapshot, dependency_token: token(snapshot), based_on_revision: revision, status: "available",
        standardization_result_index: null, standardization_result_indexes: [] });
    }
    return result;
  }
  const isCandidate = (item) => item?.suggestion_kind === "formula_candidate";
  function fresh(review, item) {
    if (!fields.includes(item?.target_field)) return false;
    const current = calculation(review, item.target_field);
    return current.value != null && current.value > 0 && stable(identity(current)) === stable(identity(item.formula_candidate || {}));
  }
  function merge(review, suggestions, revision = null) {
    const candidates = build(review, revision), ordinary = [];
    for (const item of suggestions || []) {
      if (isCandidate(item)) {
        const target = review.spring_parameters?.[item.target_field];
        if (item.status === "applied" && target?.last_applied_suggestion_id === item.suggestion_id
          && !manual(target) && target.value === item.suggested_value && fresh(review, item)) ordinary.push(item);
        continue;
      }
      const duplicate = candidates.find((c) => c.target_field === item.target_field && c.application_mode === item.application_mode
        && c.suggested_value === item.suggested_value && item.suggested_tolerance_upper == null && item.suggested_tolerance_lower == null
        && (c.target_field !== "solid_height" || (item.metadata?.value_kind || (item.rule_id === "FORMULA-SOLID-HEIGHT" ? "reference_limit" : "nominal_estimate")) === c.formula_candidate.purpose));
      if (duplicate && item.status !== "stale") {
        duplicate.supporting_sources = [...new Set([...(duplicate.supporting_sources || ["formula"]), item.source, ...(item.supporting_sources || [])])];
        duplicate.standardization_result_indexes.push(...(item.standardization_result_indexes || []));
      } else ordinary.push(item);
    }
    const result = [...candidates, ...ordinary];
    const groups = new Map();
    for (const item of result) if (["available", "conflict"].includes(item.status) && item.application_mode !== "none") {
      const group = groups.get(item.target_field) || []; group.push(item); groups.set(item.target_field, group);
    }
    for (const group of groups.values()) if (group.length > 1) group.forEach((i) => { i.status = "conflict"; });
    return result;
  }
  function apply(review, item) {
    if (!isCandidate(item) || !fresh(review, item)) return false;
    const param = review.spring_parameters?.[item.target_field];
    if (!param) return false;
    const c = clone(item.formula_candidate);
    param.formula_recalculation_candidate = c;
    if (!CompressionDesignChecks.applyCandidate(param)) return false;
    if (item.target_field === "solid_height") {
      param.value_kind = c.purpose;
      param.formula_purpose_preserved = true;
      param.formula_calculation_kind = c.purpose === "nominal_estimate" ? "nominal_solid_height" : "solid_height";
    }
    delete param.confirmation_snapshot;
    delete review.manual_confirmations?.[item.target_field];
    param.last_applied_suggestion_id = item.suggestion_id;
    param.last_applied_suggestion = { source: "formula_candidate", rule_id: item.rule_id, basis: item.basis, applied_at: new Date().toISOString() };
    return true;
  }
  globalThis.FormulaCandidates = { build, merge, fresh, apply, calculation, isCandidate };
})();
