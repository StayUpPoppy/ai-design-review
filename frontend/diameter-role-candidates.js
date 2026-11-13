/* Read-only provenance filtering, including saved candidates from older rules. */
(function (root) {
  const VERSION = "diameter-candidates/v3";
  const number = "(?:\\d+(?:\\.\\d+)?|\\.\\d+)", mark = "[φΦϕøØ⌀]";
  const derivation = /推算|推导|计算|换算|\b(?:derived|calculated|inferred|computed)\b|(?:外径|内径|中径|线径).{0,24}(?:减去|减|加上|乘以|除以)|(?:外径|内径|中径|线径|\bD[oim]?\b|\bd\b)\s*[-+−×*÷/]\s*(?:外径|内径|中径|线径|\bD[oim]?\b|\bd\b)/i;
  const drawing = /图中|图纸|原图|标注|marked|drawing/i;
  const numeric = value => typeof value === "boolean" || value == null || value === "" ? null
    : Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : null;
  function formulaResult(text, value) {
    return [...text.matchAll(new RegExp(`[=＝≈]\\s*(?:约\\s*)?${mark}?\\s*(${number})(?![\\d.])`, "g"))]
      .some(match => numeric(match[1]) === value && /[+\-−×*÷/]/.test(text.slice(0, match.index)));
  }
  function directClaim(text, value) {
    return text.split(/[，,;；。\n]/).some(clause => {
      if (/未(?:直接)?标|没有标|无.*标注|not\s+(?:shown|marked)/i.test(clause) || formulaResult(clause, value)) return false;
      const derived = derivation.exec(clause);
      if (derived) {
        clause = clause.slice(0, derived.index);
        if (!drawing.test(clause)) return false;
      }
      return [...clause.matchAll(new RegExp(`${mark}\\s*(${number})(?![\\d.])`, "g"))].some(match => numeric(match[1]) === value)
        || drawing.test(clause) && [...clause.matchAll(new RegExp(number, "g"))].some(match => numeric(match[0]) === value);
    });
  }
  function modelDerived(candidate) {
    const evidence = candidate.diameter_role_evidence || {}, observation = evidence.observation || {};
    if (["local_ocr", "pdf_text"].includes(observation.source) && numeric(observation.value) === numeric(candidate.engineering_source?.value ?? candidate.value)) return false;
    const value = numeric(candidate.value);
    if (value == null) return false;
    const text = String(candidate.evidence || evidence.original_evidence || "").normalize("NFKC").trim();
    const source = Array.isArray(candidate.source) ? candidate.source : [candidate.source];
    if (source.includes("formula_calculation") || candidate.formula_calculation_kind === "diameter_completion") return true;
    return Boolean((derivation.test(text) || formulaResult(text, value)) && !directClaim(text, value));
  }
  function observation(candidate) {
    const item = candidate?.diameter_role_evidence?.observation, value = numeric(candidate?.engineering_source?.value ?? candidate?.value);
    const position = item?.position;
    const marked = text => [...String(text || "").normalize("NFKC").matchAll(new RegExp(`${mark}\\s*(${number})(?![\\d.])`, "g"))]
      .some(match => numeric(match[1]) === value);
    return item && value != null && ["local_ocr", "pdf_text"].includes(item.source)
      && numeric(item.value) === value && (item.page ?? candidate.page ?? 1) === (candidate.page ?? 1)
      && position && ["x", "y", "width", "height"].every(key => typeof position[key] === "number")
      && position.width > 0 && position.height > 0
      && (item.roles?.length || item.geometry?.length || marked(item.text) || item.dimensions?.length && marked(item.normalized_text))
      ? item : null;
  }
  function eligible(candidate) {
    return Boolean(candidate && !candidate.selected_field && !candidate.ignored && observation(candidate));
  }
  function excerpt(candidate) {
    const text = String(observation(candidate)?.text || "").trim().replace(/\s+/g, " ");
    return text.length <= 96 ? text : "";
  }
  const pending = review => (review?.diameter_role_candidates || []).filter(eligible);
  root.DiameterRoleCandidates = { VERSION, modelDerived, eligible, excerpt, pending };
})(globalThis);
