/* SolidWorks projection; shared fixtures verify parity with solidworks.py. */
(() => {
  const calculatedProperties = { "P'": "theoretical_spring_rate", C: "spring_index", "τ_b": "solid_stress" };
  const lengthUnits = { mm: 1, "毫米": 1, cm: 10, m: 1000, in: 25.4, inch: 25.4, "英寸": 25.4 };
  const forceUnits = { n: 1, "牛": 1, kn: 1000, kgf: 9.80665 };
  const number = (v) => ["number", "string"].includes(typeof v) && String(v).trim() && Number.isFinite(Number(v)) ? Number(v) : null;
  const rounded = (v, digits = 4) => Number(Number(v).toFixed(digits));
  const textNumber = (v) => String(rounded(v));
  const parameterValue = (item, preservePrecision = false) => number(item?.value) != null ? (preservePrecision ? Number(item.value) : rounded(item.value, 3)) : typeof item?.value === "string" ? item.value.trim() || null : null;
  const handedness = (value) => ["right", "right_hand", "r", "右旋"].includes(String(value).toLowerCase()) ? "右旋" : ["left", "left_hand", "l", "左旋"].includes(String(value).toLowerCase()) ? "左旋" : null;
  const solidLabel = (label) => ["fb", "pb", "压并载荷", "压并负荷", "压并力"].includes(String(label || "").replace(/[\s_]/g, "").toLowerCase());
  const sources = (item) => (Array.isArray(item?.source) ? item.source : [item?.source]).filter(Boolean).map((s) => String(s).toLowerCase());
  const humanOverride = (item) => item?.human_modified || sources(item).some((s) => s.startsWith("human") && s !== "human_confirmed" || ["manual", "manual_input", "standardization_chat", "ai_chat"].includes(s));
  function current(parameters, field, path = []) {
    if (path.includes(field)) return false;
    const item = parameters[field];
    if (!item || typeof item !== "object") return true;
    if (item.derived_value_stale || item.formula_recommendation_stale && !humanOverride(item)) return false;
    if (humanOverride(item) || !sources(item).some((s) => ["formula_calculation", "derived"].includes(s))) return true;
    return (item.source_fields || []).every((parent) => parameters[parent]?.value != null && parameters[parent]?.value !== "" && current(parameters, parent, [...path, field]));
  }
  const roughnessUnit = (value) => String(value || "μm").trim().toLowerCase().replace(/µ/g, "μ").replace(/um/g, "μm");
  const roughnessLocation = (value) => {
    const text = String(value || "").replace(/\s+/g, "");
    return ({ "两端": "两端面", "外圆表面": "外圆", "内圆表面": "内圆" })[text] ?? text;
  };
  const positiveRoughness = (value) => {
    if (!["number", "string"].includes(typeof value)) return null;
    const text = String(value).trim().replace(/,/g, ".");
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) return null;
    const result = number(text);
    return result != null && result > 0 ? result : null;
  };
  function standaloneRoughness(item) {
    let [body] = TechnicalRequirementEquivalence.body(TechnicalRequirementEquivalence.outputContent(item));
    const suffix = body.match(/\(作用范围:\s*([^()]+)\)$/), locations = [item.application_scope, suffix?.[1]];
    if (suffix) body = body.slice(0, suffix.index).trim();
    const match = body.match(/^(?:(两端面?|[左右]端面|端面|外圆(?:表面)?|内圆(?:表面)?|弹簧表面|全表面|整体)\s*)?(?:(?:表面)?粗糙度(?:要求)?\s*[:=]?\s*(?:Ra\s*[:=]?\s*)?|Ra\s*[:=]?\s*)(\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*(μm|um)?$/i);
    let value, unit;
    if (match) {
      value = positiveRoughness(match[2]); unit = roughnessUnit(match[3]); locations.push(match[1]);
    } else if (["surface_roughness", "roughness", "surface_finish", "表面粗糙度"].includes(String(item.type || "").toLowerCase())) {
      value = positiveRoughness(body); unit = "μm";
    } else return null;
    if (value == null || unit !== "μm") return null;
    const scopes = [...new Set(locations.filter((location) => String(location || "").trim()).map(roughnessLocation))];
    return scopes.length > 1 ? null : { value, unit, location: scopes[0] || "" };
  }
  function roughnessParameter(item) {
    const value = positiveRoughness(item?.value);
    return value != null && roughnessUnit(item?.unit) === "μm" ? { value, unit: "μm", location: roughnessLocation(item?.surface_location) } : null;
  }
  const canPromoteRoughness = (item) => (item?.value == null || item.value === "") && !humanOverride(item);
  function currentRoughness(review) {
    const parameters = review.spring_parameters || {}, item = parameters.surface_roughness_ra;
    if (!item || item.roughness_conflict || item.formula_recommendation_stale || !current(parameters, "surface_roughness_ra")) return null;
    return roughnessParameter(item);
  }
  function confirmedRoughness(review) {
    return review.spring_parameters?.surface_roughness_ra?.need_human_review === false ? currentRoughness(review) : null;
  }
  function roughnessMatches(item, roughness) {
    const parsed = standaloneRoughness(item);
    return roughness != null && parsed != null && parsed.value === roughness.value && parsed.unit === roughness.unit && parsed.location === roughness.location;
  }
  function confirmedSolidHeight(review) {
    const parameters = review.spring_parameters || {}, item = parameters.solid_height;
    if (!item || item.need_human_review !== false || !current(parameters, "solid_height") || item.formula_recommendation_stale) return null;
    const kind = globalThis.CompressionDesignChecks?.solidHeightKind(item);
    if (!["input_height", "nominal_estimate"].includes(kind)) return null;
    const value = number(item.value), factor = lengthUnits[String(item.unit || "mm").trim().toLowerCase()];
    const result = value != null && factor != null ? value * factor : null;
    const free = parameters.free_length || {}, freeValue = number(free.value), freeFactor = lengthUnits[String(free.unit || "mm").trim().toLowerCase()];
    if (result != null && freeValue != null && freeFactor != null && result >= freeValue * freeFactor) return null;
    return result != null && Number.isFinite(result) && result > 0 ? result : null;
  }
  function forceText(point) {
    const force = point.force || {};
    const text = `${textNumber(force.value)} N`, percent = number(force.tolerance_percent);
    const upper = number(force.tolerance_upper), lower = number(force.tolerance_lower);
    if (percent != null) return `${text}（允差 ±${textNumber(Math.abs(percent))}%）`;
    if (upper == null && lower == null) return text;
    if (upper != null && lower != null && upper >= 0 && Math.abs(upper + lower) <= 1e-9) return `${text}（允差 ±${textNumber(upper)} N）`;
    const signed = (v) => `${v > 0 ? "+" : ""}${textNumber(v)}`;
    return `${text}（允差 ${[upper, lower].filter((v) => v != null).map(signed).join("/")} N）`;
  }
  function endConditionValue(field, value) {
    // Mirror generation_contract normalization, including legacy Chinese values.
    if (typeof value === "boolean") return Number(value);
    if (typeof value === "number" && [0, 1].includes(value)) return value;
    const text = String(value ?? "").trim(), key = text.toLowerCase().replace(/-/g, "_").replace(/ /g, "");
    if (["0", "1"].includes(text)) return Number(text);
    if (field === "end_grinding") {
      if (["not_ground", "notground", "unground", "no", "false"].includes(key) || /不磨|未磨/.test(text)) return 0;
      if (["ground", "grounded", "yes", "true", "closed_and_ground"].includes(key) || /磨/.test(text)) return 1;
    } else {
      if (["closed_and_ground", "closed_and_unground", "closed_ground"].includes(key)) return 1;
      if (["not_tight", "nottight", "open", "open_end"].includes(key) || /不并紧|开口|开放|不闭口/.test(text)) return 0;
      if (["tight", "closed", "closed_end"].includes(key) || /两端并紧|双并紧|并紧|双闭口|闭口|闭合|压紧/.test(text)) return 1;
    }
    return null;
  }
  function confirmedEndNote(exported, review) {
    const parameters = review.spring_parameters || {}, values = [];
    for (const field of ["end_coils_closed", "end_grinding"]) {
      let sourceField = field;
      if (field === "end_coils_closed" && (!parameters[field] || parameters[field].value == null || parameters[field].value === "")) sourceField = "end_type";
      const item = parameters[sourceField], output = exported[field];
      if (!item || item.need_human_review !== false || item.formula_recommendation_stale || !current(parameters, sourceField) || !output) return null;
      const value = endConditionValue(field, item.value);
      if (value == null || value !== endConditionValue(field, output.value)) return null;
      values.push(value);
    }
    return {
      "1,1": "两端并紧磨平，每端磨270°。", "1,0": "两端并紧，不磨平。",
      "0,1": "两端不并紧，端面磨平。", "0,0": "两端不并紧，不磨平。",
    }[values.join(",")];
  }
  function content(item) {
    const value = TechnicalRequirementEquivalence.outputContent(item);
    return value.replace(/(?:\s*(?:\r\n?|\n)\s*)+/g, "；").replace(/[\t ]+/g, " ").trim();
  }
  const roughnessLine = (value) => value.replace(/粗糙度\s*[:：]?\s*Ra\s*/, "表面粗糙度：Ra ").replace("表面表面粗糙度", "表面粗糙度").replace(/(?<=\d)\s*[μµ]m/g, " μm").replace(/[。.]+$/, "") + "。";
  function sentenceKey(value, catalog, scope) {
    let [key, kind] = TechnicalRequirementEquivalence.body(value);
    const material = key.match(/^(?:材质|材料)\s*[:：]?\s*(.+?)\s*[。.]*$/);
    if (material) key = `材料：${CompressionDesignChecks.materialDisplayValue(material[1], catalog)}`;
    key = key.replace(/^(?:材质|材料)/, "材料").replace(/^(?:旋向|绕制方向)/, "绕制方向").replace(/^(?:有效圈数n?|工作圈数)/, "工作圈数").replace(/表面粗糙度/g, "粗糙度").replace(/^(材料|绕制方向|工作圈数)\s*:\s*/, "$1");
    return JSON.stringify(TechnicalRequirementEquivalence.key({ type: [null, "other", "process"].includes(kind) ? "other" : kind, content: key, application_scope: scope }));
  }
  function technicalText(packageData, review, catalog = {}) {
    const generation = packageData.generation_parameters || {}, parameters = generation.spring_parameters || {};
    const lines = [], remaining = [], material = parameterValue(parameters.material), direction = handedness(parameterValue(parameters.handedness));
    const roughness = confirmedRoughness(review);
    const keys = new Set();
    const append = (line, scope) => {
      if (roughnessMatches({ content: line, application_scope: scope }, roughness)) return;
      const key = sentenceKey(line, catalog, scope);
      if (line && !keys.has(key)) { keys.add(key); lines.push(line); }
    };
    const endNote = confirmedEndNote(parameters, review);
    if (endNote) append(endNote);
    if (material != null) append(`材料：${CompressionDesignChecks.materialDisplayValue(material, catalog)}。`);
    if (direction) append(`绕制方向：${direction}。`);
    const requirements = generation.technical_requirements || [];
    for (const item of requirements) {
      if (!item || typeof item !== "object") continue;
      const body = content(item);
      if (["surface_roughness", "roughness"].includes(item.type) && body) append(roughnessLine(TechnicalRequirementEquivalence.format(item)), item.application_scope);
      else remaining.push(item);
    }
    const hb = confirmedSolidHeight(review), points = (generation.load_points || []).filter((p) => p && typeof p === "object");
    const solid = points.filter((p) => solidLabel(p.label)), fb = solid.length === 1 ? number(solid[0].force?.value) : null;
    const fbHeight = solid.length === 1 ? number(solid[0].height?.value) : null, fbText = fb != null && fb >= 0 ? forceText(solid[0]) : null;
    if (hb != null && fbText != null && fbHeight != null && Math.abs(hb - fbHeight) <= 1e-9) append(`当弹簧压并至高度 Hb = ${textNumber(hb)} mm 时，对应压并载荷 Fb = ${fbText}。`);
    else {
      if (hb != null) append(`压并高度：Hb = ${textNumber(hb)} mm。`);
      if (fbText != null) append(`压并载荷：Fb = ${fbText}${hb != null && fbHeight != null ? `（载荷测试高度 ${textNumber(fbHeight)} mm）` : ""}。`);
    }
    for (const point of points) {
      if (solidLabel(point.label)) continue;
      const height = number(point.height?.value), force = number(point.force?.value), label = String(point.label || "").trim();
      if (height == null || height <= 0 || force == null || force < 0) continue;
      const match = label.match(/^[Ff](\d+)$/);
      append(match ? `当弹簧工作高度 H${match[1]} = ${textNumber(height)} mm 时，对应工作载荷 ${label} = ${forceText(point)}。` : `载荷点 ${label}：高度 ${textNumber(height)} mm，力值 ${forceText(point)}。`);
    }
    for (const [label, field] of [["总圈数", "total_coils"], ["有效圈数", "active_coils"]]) {
      if (field === "active_coils" && parameterValue(parameters.end_coils_closed) === 0) continue;
      const value = parameterValue(parameters[field], true);
      if (value != null) append(`${label}：${value} 圈。`);
    }
    const requirementKeys = new Set();
    for (const item of remaining) {
      const key = JSON.stringify(TechnicalRequirementEquivalence.key(item));
      if (requirementKeys.has(key)) continue;
      requirementKeys.add(key);
      append(TechnicalRequirementEquivalence.format(item), item.application_scope);
    }
    if (!requirements.length) {
      const legacy = String(generation.technical_requirements_text || "").replace(/\r\n?/g, "\n").trim().replace(/^技术要求[:：]?\s*(?:\n|$)/, "");
      for (const line of legacy.split("\n")) {
        const body = TechnicalRequirementEquivalence.outputContent({ content: line });
        if (body) append(TechnicalRequirementEquivalence.format({ content: body }));
      }
    }
    return lines.map((line, index) => `${index + 1}.${line}`).join("\n");
  }
  function buildPreview(packageData, review, catalog = {}) {
    const parameters = packageData.generation_parameters?.spring_parameters || {};
    const checks = globalThis.CompressionDesignChecks.calculate(review.spring_parameters || {}, review.spring_features || {}, catalog);
    packageData.derived_parameters ||= {};
    packageData.derived_parameters.solidworks_design_checks = structuredClone({ version: checks.version, material_catalog_version: checks.material_catalog_version, material_properties: checks.material_properties,
      metrics: Object.fromEntries([...Object.values(calculatedProperties), "unit_mass"].map((key) => [key, checks.metrics[key]])) });
    const extra = { "技术要求": technicalText(packageData, review, catalog) };
    for (const [key, metric] of Object.entries(calculatedProperties)) {
      const result = checks.metrics[metric], value = number(result?.value);
      if (["calculated", "estimated"].includes(result?.status) && value != null) extra[key] = rounded(value);
    }
    const titleBlock = {}, material = parameterValue(parameters.material);
    if (typeof material === "string" && material) titleBlock["材料"] = CompressionDesignChecks.materialDisplayValue(material, catalog);
    const mass = checks.metrics.unit_mass, weight = number(mass?.value);
    if (["calculated", "estimated"].includes(mass?.status) && mass.unit === "kg" && weight != null && weight > 0) titleBlock["重量"] = rounded(weight, 8);
    const drawingNo = packageData.source?.drawing_no;
    if (typeof drawingNo === "string" && drawingNo.trim()) titleBlock["客户图号"] = drawingNo.trim();
    const roughness = confirmedRoughness(review);
    if (roughness != null) titleBlock["表面粗糙度"] = roughness.value;
    const modelParameters = Object.fromEntries([["线径", "wire_diameter"], ["中径", "mean_diameter"], ["自由高度", "free_length"], ["圈数", "total_coils"], ["有效圈数n", "active_coils"], ["是否磨平", "end_grinding"], ["是否并紧", "end_coils_closed"]].map(([label, field]) => [label, parameterValue(parameters[field], ["total_coils", "active_coils"].includes(field))]));
    if (modelParameters["是否并紧"] === 0) delete modelParameters["有效圈数n"];
    return {
      ...(packageData.generation_settings ? { DrawingModel: packageData.generation_settings.drawing_model, Username: packageData.generation_settings.username } : {}),
      modelParameters,
      customProperties: { "旋向": handedness(parameterValue(parameters.handedness)) }, extraProperties: extra, titleBlockProperties: titleBlock,
    };
  }
  function exportLoadPoint(point) {
    const height = number(point.height), force = number(point.force), hFactor = lengthUnits[String(point.height_unit || "mm").trim().toLowerCase()], fFactor = forceUnits[String(point.force_unit || "N").trim().toLowerCase()];
    if (height == null || force == null || height <= 0 || force < 0 || hFactor == null || fFactor == null || !Number.isFinite(height * hFactor) || !Number.isFinite(force * fFactor)) return null;
    const tolerance = (value) => number(value) == null ? null : rounded(Number(value) * fFactor, 3);
    const percent = point.load_tolerance_percent ?? point.force_tolerance_percent;
    return { label: String(point.label || "").trim().replace(/\s+/g, " "), height: { value: rounded(height * hFactor, 3), unit: "mm" },
      force: { value: rounded(force * fFactor, 3), unit: "N", tolerance_upper: tolerance(point.load_tolerance_upper), tolerance_lower: tolerance(point.load_tolerance_lower), ...(percent != null ? { tolerance_percent: number(percent) == null ? null : rounded(percent, 3) } : {}) }, confirmation_source: "human_confirmed" };
  }
  globalThis.SolidWorksExport = { buildPreview, technicalText, exportLoadPoint, standaloneRoughness, confirmedRoughness, roughnessMatches, currentRoughness, canPromoteRoughness };
})();
