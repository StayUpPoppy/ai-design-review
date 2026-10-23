/* Explicit-edit diameter linkage; kept in step with diameter_linkage.py. */
(() => {
  const VERSION = "compression-diameters/v1";
  const DIAMETERS = ["outer_diameter", "inner_diameter", "mean_diameter"];
  const GROUP = ["wire_diameter", ...DIAMETERS];
  const UNITS = { mm: 1, 毫米: 1, cm: 10, m: 1000, in: 25.4, inch: 25.4, 英寸: 25.4 };
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const num = (v) => typeof v === "boolean" || v == null || typeof v === "string" && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(v.trim()) || !Number.isFinite(Number(v)) ? null : Number(v);
  const factor = (p) => UNITS[String(p.unit || "mm").trim().toLowerCase()];
  const round = (v, digits) => {
    const scale = 10 ** digits, scaled = v * scale;
    if (Number.isSafeInteger(Math.floor(scaled)) && Number.isInteger(v * 2 ** (digits + 1)) && !Number.isInteger(v * 2 ** digits)) {
      const floor = Math.floor(scaled); return (floor % 2 === 0 ? floor : floor + 1) / scale;
    }
    return Number(v.toFixed(digits));
  };
  function supported(review) {
    if (review.drawing_summary?.spring_type !== "compression_spring") return false;
    return [["spring_shape", ["cylindrical", "cylinder", "圆柱"]], ["wire_section", ["round", "circular", "圆形", "圆截面"]]].every(([f, allowed]) => {
      const p = review.spring_features?.[f], v = p && typeof p === "object" ? p.value : p;
      return !v || ["unknown", "unknown_shape", "unknown_section", ...allowed].includes(v);
    });
  }
  function groupState(review) {
    return { parameters: Object.fromEntries(GROUP.map((f) => [f, clone(review.spring_parameters?.[f] ?? null)])), linkage: clone(review.diameter_linkage ?? null),
      manual_confirmations: Object.fromEntries(Object.entries(review.manual_confirmations || {}).filter(([k, v]) => GROUP.some((f) => k === f || k.endsWith(`_${f}`) || v?.target_field === f)).map(([k, v]) => [k, clone(v)])) };
  }
  function calculate(parameters, driver) {
    const wire = parameters.wire_diameter || {}, base = parameters[driver] || {};
    const inputs = Object.fromEntries(["wire_diameter", driver].map((f) => [f, { value: parameters[f]?.value ?? null, unit: parameters[f]?.unit || "mm" }]));
    let d = num(wire.value), value = num(base.value), df = factor(wire), vf = factor(base), reason = "";
    if (d == null || d <= 0 || df == null || wire.derived_value_stale) reason = "三径联动需要有效线径，请先核对线径。";
    else if (value == null || value <= 0 || vf == null) reason = "请输入有效的直径正数。";
    else if (DIAMETERS.some((f) => factor(parameters[f] || {}) == null)) reason = "三径单位无法换算，请核对单位。";
    else {
      d *= df; value *= vf;
      const mean = driver === "outer_diameter" ? value - d : driver === "inner_diameter" ? value + d : value;
      const values = { outer_diameter: mean + d, inner_diameter: mean - d, mean_diameter: mean };
      if (Object.entries(values).some(([f, v]) => num(v) == null || v <= 0 || round(v / factor(parameters[f] || {}), factor(parameters[f] || {}) === 1 ? 4 : 8) <= 0)) reason = "直径关系无效，需满足中径大于线径、内径大于0。";
      else return { inputs, values_mm: values, status: "calculated", reason: "" };
    }
    return { inputs, values_mm: {}, status: "invalid", reason };
  }
  function apply(review, editedField = null) {
    const previous = review.diameter_linkage || {}, driver = DIAMETERS.includes(editedField) ? editedField : previous.driver_field;
    if (!supported(review) || !DIAMETERS.includes(driver)) return { changed_fields: [], before: groupState(review) };
    const parameters = review.spring_parameters ||= {}, before = groupState(review), c = calculate(parameters, driver);
    const changedInput = previous.driver_field !== driver || !same(previous.inputs, c.inputs) || previous.status !== c.status;
    review.diameter_linkage = { version: VERSION, driver_field: driver, inputs: c.inputs, status: c.status, reason: c.reason, original_parameters: previous.original_parameters || clone(before.parameters) };
    const wire = parameters.wire_diameter || {}, wireSources = Array.isArray(wire.source) ? wire.source : [wire.source];
    if (wireSources.some((s) => ["formula_calculation", "derived"].includes(s))) {
      wire.source = [editedField === "wire_diameter" ? "human_edited" : "diameter_linkage_fixed_input"];
      wire.accuracy_value_source = editedField === "wire_diameter" ? "human" : "system";
      for (const k of ["source_fields", "formula", "formula_calculation_kind", "formula_calculation_inputs"]) delete wire[k];
    }
    const changed = [];
    for (const field of DIAMETERS) {
      const item = parameters[field] ||= { value: null, unit: "mm" }, old = clone(item);
      item.diameter_linkage_managed = true;
      if (c.status === "calculated") {
        if (field !== driver) {
          let f = factor(item); if (f == null) { item.unit = "mm"; f = 1; }
          item.value = round(c.values_mm[field] / f, f === 1 ? 4 : 8);
          item.source = ["formula_calculation", "diameter_linkage"];
          item.source_fields = [driver, "wire_diameter"];
          item.formula = {
            outer_diameter: { mean_diameter: "Dm = Do - d", inner_diameter: "Di = Do - 2d" },
            inner_diameter: { mean_diameter: "Dm = Di + d", outer_diameter: "Do = Di + 2d" },
            mean_diameter: { outer_diameter: "Do = Dm + d", inner_diameter: "Di = Dm - d" },
          }[driver][field];
          item.evidence = `联动计算：${item.formula}。`;
          item.formula_calculation_kind = "diameter_linkage"; item.formula_calculation_inputs = clone(c.inputs);
          item.accuracy_value_source = "system";
        } else if (DIAMETERS.includes(editedField)) {
          item.source = ["human_edited", "diameter_linkage_driver"]; item.accuracy_value_source = "human";
          item.evidence = "人工修改直径，按当前线径联动。";
          for (const k of ["source_fields", "formula", "formula_calculation_kind", "formula_calculation_inputs"]) delete item[k];
        }
        for (const k of ["diameter_linkage_error", "formula_recommendation_stale", "formula_recalculation_candidate"]) delete item[k];
        item.derived_value_stale = false;
      } else { item.derived_value_stale = true; item.diameter_linkage_error = c.reason; }
      if (changedInput || old.value !== item.value || Boolean(old.derived_value_stale) !== Boolean(item.derived_value_stale)) {
        item.need_human_review = true; delete item.confirmation_snapshot;
        for (const [key, entry] of Object.entries(review.manual_confirmations || {})) {
          if (entry && (key === field || key.endsWith(`_${field}`) || entry.target_field === field)) { entry.confirmed = false; entry.revoked_reason = "diameter_linkage_changed"; }
        }
        changed.push(field);
      }
    }
    if (changed.length) {
      review.derived_parameters_stale = true; review.parameter_reasonableness_stale = true;
      for (const row of review.standardization_results || []) if (["suggested", "llm_suggested", "human_confirmed"].includes(row.status)) { row.status = "stale"; row.need_human_review = true; }
    }
    return { changed_fields: changed, before };
  }
  globalThis.DiameterLinkage = { VERSION, DIAMETERS, GROUP, supported, groupState, calculate, apply };
})();
