/* Read-only provenance filtering, including saved candidates from older rules. */
(function (root) {
  const VERSION = "diameter-candidates/v1";
  const number = "\\d+(?:\\.\\d+)?", mark = "[φΦϕøØ⌀]";
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
    if (["local_ocr", "pdf_text"].includes(observation.source) && numeric(observation.value) === numeric(candidate.value)) return false;
    const value = numeric(candidate.value);
    if (value == null) return false;
    const text = String(candidate.evidence || evidence.original_evidence || "").normalize("NFKC").trim();
    const source = Array.isArray(candidate.source) ? candidate.source : [candidate.source];
    if (source.includes("formula_calculation") || candidate.formula_calculation_kind === "diameter_completion") return true;
    return Boolean((derivation.test(text) || formulaResult(text, value)) && !directClaim(text, value));
  }
  function pending(review) {
    return (review?.diameter_role_candidates || []).filter(item => item && !item.selected_field && !item.ignored && !modelDerived(item));
  }
  root.DiameterRoleCandidates = { VERSION, modelDerived, pending };
})(globalThis);
