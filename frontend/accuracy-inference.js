/* Independent-input accuracy inference. Rules mirror the versioned backend
 * rule table; the shared test checks equality and Python/browser decisions. */
(() => {
  const VERSION = "compression-accuracy/v1";
  const RULES = {"standard_no":"GB/T 1239.2-2009","label":"冷卷圆柱螺旋弹簧技术条件 第2部分：压缩弹簧","spring_type":"compression_spring","spring_family":"cold_coiled_cylindrical_compression","accuracy_grades":["1","2","3"],"diameter_tolerance":[{"spring_index_min":3,"spring_index_max":8,"include_min":true,"include_max":true,"grades":{"1":{"factor":0.01,"minimum":0.15},"2":{"factor":0.015,"minimum":0.2},"3":{"factor":0.025,"minimum":0.4}}},{"spring_index_min":8,"spring_index_max":15,"include_min":false,"include_max":true,"grades":{"1":{"factor":0.015,"minimum":0.2},"2":{"factor":0.02,"minimum":0.3},"3":{"factor":0.03,"minimum":0.5}}},{"spring_index_min":15,"spring_index_max":22,"include_min":false,"include_max":true,"grades":{"1":{"factor":0.02,"minimum":0.3},"2":{"factor":0.03,"minimum":0.5},"3":{"factor":0.04,"minimum":0.7}}}],"free_length_tolerance":[{"spring_index_min":3,"spring_index_max":8,"include_min":true,"include_max":true,"grades":{"1":{"factor":0.01,"minimum":0.2},"2":{"factor":0.02,"minimum":0.5},"3":{"factor":0.03,"minimum":0.7}}},{"spring_index_min":8,"spring_index_max":15,"include_min":false,"include_max":true,"grades":{"1":{"factor":0.015,"minimum":0.5},"2":{"factor":0.03,"minimum":0.7},"3":{"factor":0.04,"minimum":0.8}}},{"spring_index_min":15,"spring_index_max":22,"include_min":false,"include_max":true,"grades":{"1":{"factor":0.02,"minimum":0.6},"2":{"factor":0.04,"minimum":0.8},"3":{"factor":0.06,"minimum":1.0}}}],"total_coils_tolerance":[{"max":10,"tolerance":0.25},{"min":10,"max":20,"tolerance":0.5},{"min":20,"max":50,"tolerance":1.0}],"perpendicularity":{"1":{"factor":0.02,"angle_degree":1.15},"2":{"factor":0.05,"angle_degree":2.9},"3":{"factor":0.08,"angle_degree":4.6}},"load_tolerance":{"3_to_10":{"1":0.05,"2":0.1,"3":0.15},"gt_10":{"1":0.04,"2":0.08,"3":0.12}},"stiffness_tolerance":{"3_to_10":{"1":0.05,"2":0.1,"3":0.15},"gt_10":{"1":0.04,"2":0.08,"3":0.12}},"solid_height":{"ground":{"formula":"total_coils * max_wire_diameter","end_grinding_aliases":["磨","磨削","磨平","端面磨削","两端磨平","并紧磨平"]},"not_ground":{"formula":"(total_coils + 1.5) * max_wire_diameter","end_grinding_aliases":["不磨","未磨","两端不磨","不磨削"]}},"permanent_set":{"max_free_length_ratio":0.003}};
  const FIELDS = ["wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "active_coils", "total_coils", "support_coils", "end_type", "end_grinding", "spring_rate", "controlled_diameter_field", "diameter_accuracy_grade", "free_length_accuracy_grade", "load_accuracy_grade", "stiffness_accuracy_grade"];
  const SPECIFIC = { diameter: "diameter_accuracy_grade", free_length: "free_length_accuracy_grade", load: "load_accuracy_grade", stiffness: "stiffness_accuracy_grade" };
  const LENGTH = { mm: 1, cm: 10, m: 1000, in: 25.4, inch: 25.4, 毫米: 1 }, FORCE = { n: 1, kn: 1000, kgf: 9.80665 };
  const GENERATED = new Set(["standardization", "system_generated", "human_suggestion_applied"]);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const num = (v) => v == null || typeof v === "boolean" || typeof v === "string" && !v.trim() || !Number.isFinite(Number(v)) ? null : Number(v);
  const grade = (v) => String(v ?? "").match(/^\s*([123])\s*[级級]?\s*$/)?.[1] ? `${String(v).match(/[123]/)[0]}级` : null;
  const sources = (p) => Array.isArray(p.source) ? p.source : p.source ? [p.source] : [];
  // Match Python round(): exact binary halfway values use ties-to-even.
  const round = (v, digits = 4) => {
    const scale = 10 ** digits, scaled = v * scale;
    if (Number.isSafeInteger(Math.floor(scaled)) && Number.isInteger(v * 2 ** (digits + 1)) && !Number.isInteger(v * 2 ** digits)) {
      const floor = Math.floor(scaled);
      return (floor % 2 === 0 ? floor : floor + 1) / scale;
    }
    return Number(v.toFixed(digits));
  };
  function item(p = {}, load = false) {
    const formula = sources(p).some((s) => ["formula_calculation", "company_active_coil_rule"].includes(s));
    return { value: p[load ? "force" : "value"] ?? null, unit: p[load ? "force_unit" : "unit"] || (load ? "N" : ""),
      upper: p[load ? "load_tolerance_upper" : "tolerance_upper"] ?? null, lower: p[load ? "load_tolerance_lower" : "tolerance_lower"] ?? null,
      percent: load ? p.force_tolerance_percent ?? p.load_tolerance_percent ?? null : null,
      invalid: Boolean(p.tolerance_input_draft || p.derived_value_stale), system_value: p.accuracy_value_source === "system" || formula && p.accuracy_value_source !== "human",
      system_tolerance: GENERATED.has(p.tolerance_source) || formula && p.tolerance_source !== "human" };
  }
  function capture(review) {
    const p = review.spring_parameters || {}, result = Object.fromEntries(FIELDS.map((f) => [f, item(p[f])]));
    (p.load_points || []).forEach((point, i) => { result[`load:${point.load_point_id || point.label || i}`] = item(point, true); });
    return result;
  }
  function stable(v) {
    if (typeof v === "number") {
      const buffer = new ArrayBuffer(8); new DataView(buffer).setFloat64(0, v || 0);
      return { $number: [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("") };
    }
    return Array.isArray(v) ? v.map(stable) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, stable(v[k])])) : v;
  }
  function fingerprint(value) {
    const raw = JSON.stringify(stable(value)); let hash = 2166136261;
    for (let i = 0; i < raw.length; i++) hash = Math.imul(hash ^ raw.charCodeAt(i), 16777619) >>> 0;
    return hash.toString(16).padStart(8, "0");
  }
  function scaled(p = {}, kind = "length") {
    const unit = String(p.unit || (kind === "load" ? "N" : kind === "stiffness" ? "N/mm" : kind === "coils" ? "turns" : "mm")).trim().toLowerCase();
    const factor = kind === "load" ? FORCE[unit] : kind === "stiffness" ? { "n/mm": 1, "n/cm": .1, "kn/m": 1, "n/m": .001 }[unit] : kind === "coils" && ["turns", "turn", "圈"].includes(unit) ? 1 : LENGTH[unit];
    const value = num(p.value);
    return p.invalid || factor == null || value == null || value <= 0 ? [null, null] : [value * factor, factor];
  }
  function analyze(snapshot, standard = null, geometryDriver = null) {
    const supported = /^GB\s*\/?\s*T\s*1239\.2(?:-2009)?$/i.test(standard || "");
    const value = (f, kind = "length") => scaled(snapshot[f], kind)[0];
    const wire = value("wire_diameter"); let mean = snapshot.mean_diameter?.system_value ? null : value("mean_diameter");
    if (mean == null && wire != null) { const outer = value("outer_diameter"), inner = value("inner_diameter"); mean = outer != null ? outer - wire : inner != null ? inner + wire : null; }
    let geometry = null;
    if (["outer_diameter", "inner_diameter", "mean_diameter"].includes(geometryDriver)) {
      const anchor = value(geometryDriver);
      mean = anchor == null || wire == null ? null : geometryDriver === "outer_diameter" ? anchor - wire : geometryDriver === "inner_diameter" ? anchor + wire : anchor;
      geometry = { mean_diameter: mean, outer_diameter: mean == null ? null : mean + wire, inner_diameter: mean == null ? null : mean - wire };
    }
    const springIndex = mean != null && mean > 0 && wire ? round(mean / wire) : null;
    let active = value("active_coils", "coils");
    if (snapshot.active_coils?.system_value) {
      const inputs = Object.fromEntries(Object.entries(snapshot).filter(([f]) => !f.startsWith("load:")).map(([f, p]) => [f, { value: p.value, unit: p.unit || null, derived_value_stale: p.invalid }]));
      delete inputs.active_coils;
      active = typeof CompressionDesignChecks !== "undefined" ? num(CompressionDesignChecks.activeCalculation(inputs).value) : null;
    }
    const controlled = snapshot.controlled_diameter_field?.value;
    const diameters = ["outer_diameter", "inner_diameter"].includes(controlled) ? [controlled] : ["outer_diameter", "inner_diameter"];
    const targets = [...diameters.map((f) => [f, "diameter"]), ["free_length", "free_length"], ["spring_rate", "stiffness"], ...Object.keys(snapshot).filter((f) => f.startsWith("load:")).map((f) => [f, "load"])];
    const results = [];
    for (const [field, kind] of targets) {
      const p = snapshot[field] || {}, percent = num(p.percent), explicit = grade(snapshot[SPECIFIC[kind]]?.value);
      let upper = num(p.upper), lower = num(p.lower);
      if (upper == null && lower == null && percent == null && !explicit && (p.value == null || p.value === "")) continue;
      let [nominal, factor] = scaled(p, kind === "load" ? "load" : kind === "stiffness" ? "stiffness" : "length");
      if (kind === "diameter" && geometry) { factor = LENGTH[String(p.unit || "mm").trim().toLowerCase()]; nominal = factor == null ? null : geometry[field]; }
      const r = { field, kind, grade: null, status: "missing_context", limits: {}, stricter_than_first: false };
      if (!supported) r.status = "not_applicable";
      else if (explicit) Object.assign(r, { grade: explicit, status: "drawing_grade" });
      else if (p.system_tolerance) r.status = "generated_tolerance";
      else if (upper == null && lower == null && percent == null) r.status = "missing_tolerance";
      else if (nominal != null) {
        if (kind === "load" && upper == null && lower == null && percent != null && percent >= 0) { upper = nominal * percent / 100; lower = -upper; }
        else { upper = upper == null ? null : upper * factor; lower = lower == null ? null : lower * factor; }
        if (upper != null && lower != null && lower <= upper) {
          for (const g of ["1", "2", "3"]) {
            let limit = null;
            if (["diameter", "free_length"].includes(kind)) {
              const band = springIndex == null ? null : RULES[`${kind}_tolerance`].find((b) => (b.include_min ? springIndex >= b.spring_index_min : springIndex > b.spring_index_min) && (b.include_max ? springIndex <= b.spring_index_max : springIndex < b.spring_index_max));
              if (band) limit = round(Math.max(band.grades[g].factor * nominal, band.grades[g].minimum));
            } else {
              const table = RULES[kind === "load" ? "load_tolerance" : "stiffness_tolerance"], ratio = active != null && active >= 3 && active <= 10 ? table["3_to_10"][g] : active != null && active > 10 ? table.gt_10[g] : null;
              if (ratio != null) limit = round(nominal * ratio);
            }
            if (limit != null) {
              r.limits[`${g}级`] = limit;
              if (r.grade == null && round(upper - limit, 9) <= 0 && round(lower + limit, 9) >= 0) Object.assign(r, { grade: `${g}级`, status: "matched" });
            }
          }
          if (Object.keys(r.limits).length && !r.grade) r.status = "outside_grades";
          r.stricter_than_first = Boolean(r.grade === "1级" && r.limits["1级"] != null && upper < r.limits["1级"] && lower > -r.limits["1级"]);
        } else r.status = "invalid_tolerance";
      }
      results.push(r);
    }
    const grades = results.map((r) => r.grade).filter(Boolean).sort();
    return { results, inferred_grade: grades[0] || null, complete: Boolean(results.length) && results.every((r) => r.grade), standard_no: standard };
  }
  function refresh(review, options = {}) {
    const { initialize = false } = options;
    let standard = options.standard;
    if (review.drawing_summary?.spring_type !== "compression_spring") return false;
    const params = review.spring_parameters ||= {}, current = capture(review), accuracy = params.accuracy_grade ||= { value: null, need_human_review: true };
    let meta = review.accuracy_inference;
    if (!meta || typeof meta !== "object") {
      const explicit = grade(accuracy.value) && accuracy.default_source !== "company_default" && !sources(accuracy).includes("company_default");
      meta = review.accuracy_inference = { selection_mode: initialize ? explicit ? "drawing" : "auto" : "legacy", input_snapshot: clone(current), observed_inputs: clone(current) };
    }
    if (meta.selection_mode === "auto" && sources(accuracy).includes("human_selected")) meta.selection_mode = "manual";
    const observed = meta.observed_inputs ||= {}, snapshot = meta.input_snapshot ||= {};
    Object.keys(snapshot).filter((f) => !(f in current)).forEach((f) => { delete snapshot[f]; });
    for (const [field, p] of Object.entries(current)) {
      if (JSON.stringify(p) === JSON.stringify(observed[field])) continue;
      const saved = snapshot[field] ||= clone(p);
      if (!p.system_value) for (const k of ["value", "unit", "invalid", "system_value"]) saved[k] = p[k];
      if (!p.system_tolerance) for (const k of ["upper", "lower", "percent", "invalid", "system_tolerance"]) saved[k] = p[k];
    }
    meta.observed_inputs = clone(current);
    const selection = review.standard_selection || {};
    if (selection.selected_standard) meta.standard_selection_source = selection.selection_source || "selected";
    if (!Object.hasOwn(options, "standard")) {
      standard = selection.selected_standard || meta.standard_no || params.standard_no?.value || null;
      if (meta.standard_selection_source === "wire_diameter_threshold" && !params.standard_no?.value) {
        const wireMm = scaled(snapshot.wire_diameter)[0];
        standard = wireMm == null ? null : wireMm < 8 ? "GB/T 1239.2-2009" : "GB/T 23934-2015";
      }
    }
    const previousInferred = meta.inferred_grade;
    const geometryDriver = review.diameter_linkage?.driver_field;
    const analysis = analyze(snapshot, standard, geometryDriver), fingerprintInput = { snapshot, standard, version: VERSION };
    if (geometryDriver) fingerprintInput.geometry_driver = geometryDriver;
    Object.assign(meta, analysis, { rules_version: VERSION, calculation_fingerprint: fingerprint(fingerprintInput) });
    if (meta.selection_mode !== "auto") return false;
    const selected = analysis.inferred_grade || "2级", changed = grade(accuracy.value) !== selected || Boolean(previousInferred && !analysis.inferred_grade);
    if (changed) {
      for (const [key, entry] of Object.entries(review.manual_confirmations ||= {})) if (key === "accuracy_grade" || entry.target_field === "accuracy_grade") Object.assign(entry, { confirmed: false, revoke_reason: "accuracy_inference_changed" });
      delete accuracy.confirmation_snapshot; accuracy.need_human_review = true;
      (review.standardization_results || []).forEach((r) => { const deps = r.metadata?.source_fields; if (!deps?.length || deps.includes("accuracy_grade")) Object.assign(r, { status: "stale", need_human_review: true }); });
    }
    accuracy.value = selected;
    if (analysis.inferred_grade) {
      accuracy.source = [...new Set([...sources(accuracy).filter((s) => s !== "company_default"), "tolerance_inference"])];
      accuracy.evidence = "根据独立公差按等级限值反推，整体报价取最严格等级。";
      delete accuracy.default_source; delete accuracy.default_reason;
    } else if (accuracy.need_human_review !== false) {
      Object.assign(accuracy, { default_source: "company_default", default_reason: "无可用独立公差反推，按公司默认二级精度生成标准化建议。", evidence: "无可用独立公差反推，按公司默认二级精度生成标准化建议。" });
      accuracy.source = [...new Set([...sources(accuracy).filter((s) => s !== "tolerance_inference"), "company_default"])];
    }
    return changed;
  }
  function manual(review) { refresh(review); if (review.accuracy_inference) review.accuracy_inference.selection_mode = "manual"; }
  function markInput(review, target, { generated = false, tolerance = false } = {}) {
    const params = review.spring_parameters || {}, match = String(target).match(/^load_points\.([^.]+)\.(force|height)$/);
    const p = match ? (params.load_points || []).find((p) => String(p.label) === match[1]) : params[target];
    if (!p) return;
    p[tolerance ? "tolerance_source" : "accuracy_value_source"] = generated ? tolerance ? "system_generated" : "system" : "human";
    if (generated && !tolerance) p.tolerance_source = "system_generated";
    return refresh(review);
  }
  globalThis.AccuracyInference = { VERSION, RULES, FIELDS, capture, analyze, refresh, manual, markInput };
})();
