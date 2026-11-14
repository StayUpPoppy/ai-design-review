/* Company choices assist editing; content remains the only drawing text. */
(() => {
  let catalog = { version: "", items: [] };
  const negativePrefix = /(?:不得|禁止|不要|不允许|不准|不需要|无需|未要求|不做|不采用|非|未|无|不)\s*(?:进行|采用|使用|实施|做)?\s*$/;
  const aliases = { 涂清漆: "油漆-清漆", 清漆: "油漆-清漆", 镀锌五彩: "电镀-镀彩锌" };
  const generic = ["锌铝片涂层", "锌铝涂层", "ZINCFLAKE", "ZINC FLAKE", "喷丸强化", "喷丸", "SHOT PEENING",
    "涂漆", "镀锌", "喷塑", "电泳"];
  const broadTerms = new Set(["涂漆", "镀锌", "喷塑", "电泳"]);
  const incompleteBody = /待补充|待确认|待核对|未识别|无法辨认|[□�]|[?？]|⟦ENG_|[：:，,；;]$|^[混批]?丸[。.]?$/;
  const surfaceBody = text => globalThis.TechnicalRequirementEquivalence?.surfaceBody(text) ?? String(text || "").trim();
  function setCatalog(value) {
    if (!value?.version || !Array.isArray(value.items) || value.items.length !== 49
      || new Set(value.items.map((v) => v.id)).size !== 49 || new Set(value.items.map((v) => v.name)).size !== 49
      || value.items.some((v) => typeof v.id !== "string" || !v.id || typeof v.name !== "string" || !v.name.trim())) throw new Error("公司表面处理目录格式无效");
    catalog = structuredClone(value);
  }
  function occurrences(content, { includeAliases = false, includeGeneric = false, includeNegative = false } = {}) {
    const text = String(content || ""), used = new Set(), found = [];
    const terms = new Map(catalog.items.map(item => [item.name, item]));
    if (includeAliases) for (const [term, name] of Object.entries(aliases)) {
      const item = terms.get(name);
      if (item) terms.set(term, item);
    }
    if (includeGeneric) for (const term of generic) if (!terms.has(term)) terms.set(term, { id: "", name: term });
    for (const [term, item] of [...terms].sort(([a], [b]) => b.length - a.length)) {
      const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const pattern = /^[\x00-\x7F]+$/.test(term) ? `(?<![A-Za-z])${escaped}(?![A-Za-z])` : escaped;
      for (const match of text.matchAll(new RegExp(pattern, "gi"))) {
        const start = match.index, end = start + match[0].length;
        const occupied = Array.from({ length: end - start }, (_, i) => start + i);
        if (occupied.some(i => used.has(i))) continue;
        occupied.forEach(i => used.add(i));
        const negative = negativePrefix.test(text.slice(Math.max(0, start - 12), start));
        if (includeNegative || !negative) found.push({ start, end, id: item.id, name: item.name, term: match[0], negative });
      }
    }
    return found.sort((a, b) => a.start - b.start);
  }
  const namesInContent = (content) => [...new Set(occurrences(content).map((v) => v.id))];
  function readingConflict(verification) {
    if (!verification || ["verified", "reviewed"].includes(verification.status)) return false;
    const readings = (verification.readings || []).filter(row => row && row.source !== "initial_body")
      .map(row => surfaceBody(row.text)).filter(body => !incompleteBody.test(body)).map(body => {
      const terms = occurrences(body, { includeAliases: true, includeGeneric: true, includeNegative: true });
      const keys = new Set(terms.filter(term => !broadTerms.has(term.term)).map(term => {
        const equivalent = { SHOTPEENING: "喷丸", ZINCFLAKE: "锌铝涂层", 锌铝片涂层: "锌铝涂层" };
        return JSON.stringify([term.id || equivalent[term.term.toUpperCase().replaceAll(" ", "")] || term.term, term.negative]);
      }));
      const numbers = (body.replace(/[−–]/g, "-").match(/[+-]?[0-9]+(?:\.[0-9]+)?/g) || []).map(Number);
      const aliases = { 毫米: "mm", 微米: "μm", um: "μm", "µm": "μm", 英寸: "in", 小时: "h", 分钟: "min" };
      const units = [...body.matchAll(/(?<=\d)\s*(mm|[μµu]m|cm|in|英寸|毫米|微米|小时|分钟|h|min)(?![A-Za-z])/gi)]
        .map(([, unit]) => aliases[unit.toLowerCase()] || unit.toLowerCase());
      return { keys, numbers, units };
    }).filter(({ keys, numbers }) => keys.size || numbers.length);
    const subset = (a, b) => [...a].every(value => b.has(value));
    return readings.some((a, index) => readings.slice(index + 1).some(b => {
      const left = subset(a.keys, b.keys), right = subset(b.keys, a.keys);
      return (!left && !right) || (a.numbers.length && b.numbers.length && String(a.numbers) !== String(b.numbers)) ||
        (a.units.length && b.units.length && String(a.units) !== String(b.units));
    }));
  }

  function choiceReason(mapping) {
    const { catalog_ids: ids, selection_mode: mode } = mapping;
    if (!["auto", "manual", "none"].includes(mode) || !Array.isArray(ids) || new Set(ids).size !== ids.length ||
        (mode === "none" && ids.length)) return "公司类型无效，请重新选择或置空";
    if (!catalog.items.length && mode !== "none") return "公司类型目录尚未加载，请重试";
    return ids.some(id => !catalog.items.some(item => item.id === id)) ? "公司类型无效，请重新选择或置空" : "";
  }

  function confirmation(item, { batch = false } = {}) {
    if (item?.type !== "surface") return { reason: "", review: false };
    const mapping = item.surface_mapping, verification = mapping?.verification;
    const needsReview = verification?.status === "uncertain" || mapping?.conversion_status === "needs_input";
    const conflict = readingConflict(verification);
    const body = surfaceBody(item.content);
    const blocked = reason => ({ reason, review: false });
    const hasProcess = () => occurrences(body, { includeAliases: true, includeGeneric: true, includeNegative: true }).length > 0;
    if (item.unit_pending) return blocked("单位待核对，请对照原图重新填写");
    if (!/[\u3400-\u9fffA-Za-z]/.test(body) || incompleteBody.test(body) ||
        needsReview && !hasProcess()) {
      return blocked("表面处理正文残缺，请对照原图补充正文");
    }
    if (globalThis.TechnicalRequirementTranslation?.needsTranslation(body) || /Fe\s*\/\s*Ep\.Zn\d+(?:\.[A-Z0-9]+)+/i.test(body)) {
      return blocked("表面处理转换未完成，请补充中文要求");
    }
    const invalidChoice = mapping && choiceReason(mapping);
    if (invalidChoice) return blocked(invalidChoice);
    if (batch && conflict) return blocked("表面处理原图读数有冲突，请单项核对");
    const matches = occurrences(body, { includeAliases: true });
    let chosen = mapping?.catalog_ids?.[0] || "";
    if (chosen && (mapping.choice_needs_edit || !matches.some(match => match.id === chosen))) return blocked(mapping.choice_needs_edit
      ? "已选择公司类型，请核对正文中的工艺名称" : "公司类型与正文不一致");
    if (!chosen && mapping?.selection_mode !== "none" && !conflict && matches.length === 1) chosen = matches[0].id;
    if (!mapping && !chosen && !hasProcess() && item.translation_status !== "translated" &&
        !["matched", "alias_matched", "llm_auto_matched", "human_confirmed"].includes(item.normalization_status)) {
      return blocked("请先明确表面处理标准术语");
    }
    const replacements = matches.filter(match => match.id === chosen);
    const match = replacements.length === 1 ? replacements[0] : null;
    const content = match ? body.slice(0, match.start) + match.name + body.slice(match.end) : body;
    if (chosen && !namesInContent(content).includes(chosen)) return blocked("公司类型与正文不一致");
    return { reason: "", review: needsReview || conflict, conflict, content, chosen };
  }

  function confirm(item, batch = false) {
    const decision = confirmation(item, { batch });
    if (item.type !== "surface" || decision.reason) return;
    const mapping = ensure(item);
    item.content = decision.content;
    mapping.catalog_ids = decision.chosen ? [decision.chosen] : [];
    mapping.selection_mode = decision.chosen ? "manual" : "none";
    mapping.conversion_status = "converted";
    delete mapping.choice_needs_edit;
    if (mapping.verification) mapping.verification = { ...mapping.verification, status: "reviewed" };
    finish(item);
    return { content: item.content, catalog_ids: [...mapping.catalog_ids], mode: batch ? "batch" : "single" };
  }
  function reason(item) {
    const mapping = item?.surface_mapping;
    if (!mapping || typeof mapping !== "object") return "";
    const ids = mapping.catalog_ids;
    if (!["auto", "manual", "none"].includes(mapping.selection_mode)) return "公司类型无效，请重新选择或置空";
    if (mapping.verification?.status === "uncertain") return "表面处理原文待核对，请对照原图补充正文";
    if (mapping.conversion_status === "needs_input") return "表面处理转换未完成，请补充中文要求";
    if (mapping.choice_needs_edit && ids?.length) return "已选择公司类型，请核对正文中的工艺名称";
    if (mapping.selection_mode === "none" && Array.isArray(ids) && !ids.length) return "";
    if (!catalog.items.length) return "公司类型目录尚未加载，请重试";
    if (!Array.isArray(ids) || ids.some((id) => !catalog.items.some((v) => v.id === id)) || new Set(ids).size !== ids.length) return "公司类型无效，请重新选择或置空";
    if (mapping.selection_mode === "none") return ids.length ? "公司类型无效，请重新选择或置空" : "";
    if (mapping.selection_mode === "auto" && mapping.conversion_status !== "converted"
        && !(mapping.verification?.status === "verified" && mapping.conversion_status === "unmatched" && !ids.length)) return "表面处理转换未完成，请补充中文要求";
    return ids.length && !namesInContent(item.content).includes(ids[0]) ? "公司类型与正文不一致" : "";
  }
  function ensure(item) {
    item.surface_mapping ||= { catalog_ids: namesInContent(item.content).slice(0, 1), selection_mode: "manual", conversion_status: "converted" };
    item.surface_mapping.catalog_version = catalog.version;
    return item.surface_mapping;
  }
  function edited(item) {
    const mapping = ensure(item);
    if (mapping.selection_mode !== "none") {
      const ids = namesInContent(item.content);
      if (ids.length) mapping.catalog_ids = ids.slice(0, 1);
      mapping.selection_mode = "manual";
    }
    mapping.conversion_status = "converted";
    delete mapping.choice_needs_edit;
    if (mapping.verification) mapping.verification = { ...mapping.verification, status: "manual", term: "" };
    return finish(item);
  }
  function choose(item, ids) {
    const mapping = ensure(item), before = [...mapping.catalog_ids].slice(0, 1);
    const original = String(item.content || "");
    const selected = [...new Set(ids.filter(Boolean))].slice(0, 1);
    const next = catalog.items.find((v) => v.id === selected[0]);
    let needsEdit = false;
    if (next && before[0] !== next.id) {
      const choices = occurrences(original, { includeAliases: true, includeGeneric: true });
      const matchingSelection = choices.filter(v => v.id === next.id);
      const matches = before[0] ? choices.filter(v => v.id === before[0]) : matchingSelection.length === 1 ? matchingSelection : choices;
      const verifiedTerm = mapping.verification?.term;
      if (!matches.length && verifiedTerm && ["verified", "manual"].includes(mapping.verification.status)) {
        const start = original.indexOf(verifiedTerm);
        const prefix = original.slice(Math.max(0, start - 12), start);
        if (start >= 0 && !negativePrefix.test(prefix) && original.lastIndexOf(verifiedTerm) === start) matches.push({ start, end: start + verifiedTerm.length });
      }
      if (matches.length === 1) {
        const { start, end } = matches[0];
        item.content = original.slice(0, start) + next.name + original.slice(end);
      } else if (!original.trim()) {
        item.content = next.name;
      } else if (!(matches.length === 0 && namesInContent(original).includes(next.id))) {
        needsEdit = true;
      }
      if (item.content !== original && mapping.verification) {
        mapping.verification = { ...mapping.verification, term: next.name };
      }
    }
    mapping.catalog_ids = selected;
    mapping.selection_mode = selected.length ? "manual" : "none";
    if (mapping.conversion_status !== "needs_input" || item.content !== original) mapping.conversion_status = "converted";
    mapping.choice_needs_edit = Boolean(next && (needsEdit || !namesInContent(item.content).includes(next.id)));
    return finish(item);
  }
  function finish(item) {
    const mapping = item.surface_mapping;
    mapping.catalog_ids = mapping.catalog_ids.slice(0, 1);
    mapping.input_snapshot = { content: String(item.content || "").trim(), type: item.type || "surface" };
    mapping.conflict = Boolean(mapping.choice_needs_edit) || reason(item) === "公司类型与正文不一致";
    item.standard_content = String(item.content || "").trim();
    return reason(item);
  }
  function fingerprint(item) {
    const m = item?.surface_mapping;
    return m ? { catalog_version: m.catalog_version, catalog_ids: m.catalog_ids, selection_mode: m.selection_mode, conversion_status: m.conversion_status } : null;
  }
  const withoutNames = (content) => [...catalog.items].sort((a, b) => b.name.length - a.name.length).reduce((text, v) => text.split(v.name).join(""), String(content || ""));
  const sourceKey = (value) => surfaceBody(String(value || "").normalize("NFKC"))
    .replace(/^表面要求\s*[:：]\s*/, "")
    .replace(/\s+/g, " ").trim().replace(/[;；。]+$/, "").trim();
  const scopeKey = (value) => String(value || "").normalize("NFKC").replace(/\s+/g, " ").trim();
  const originalKeys = (item) => [...new Set([item, ...(item.recognition_aliases || [])].filter((v) => v && typeof v === "object")
    .flatMap((v) => [sourceKey(v.original_content), sourceKey(v.raw_content)]).filter(Boolean))];
  const converted = (item) => item.type === "surface" && item.surface_mapping?.conversion_status === "converted" && originalKeys(item).length > 0;
  function samePosition(left, right) {
    const a = left.position, b = right.position;
    const empty = (v) => !v || typeof v === "object" && !Object.keys(v).length;
    if (empty(a) || empty(b)) return true;
    if ((a.coordinate_type ?? null) !== (b.coordinate_type ?? null)) return false;
    return ["x", "y", "width", "height"].every((key) => typeof a[key] === "number" && typeof b[key] === "number"
      && Number.isFinite(a[key]) && Number.isFinite(b[key]) && Math.abs(a[key] - b[key]) <= 1e-6);
  }
  function sourceLinks(review) {
    const notes = (review?.technical_requirements || []).filter((v) => v && typeof v === "object");
    const roots = notes.filter((v) => v.requirement_id && converted(v));
    const sources_by_target = {}, suppressed_ids = [];
    for (const source of notes) {
      if (!source.requirement_id || converted(source)) continue;
      const origins = Array.isArray(source.source) ? source.source : [source.source];
      if (origins.some((v) => ["human_edited", "human_filled", "manual", "ai_chat"].includes(v))) continue;
      const key = sourceKey(source.content);
      if (!key || key !== sourceKey(source.original_content || source.content)) continue;
      const matches = roots.filter((root) => root.requirement_id !== source.requirement_id && originalKeys(root).includes(key)
        && (root.page || 1) === (source.page || 1) && scopeKey(root.application_scope) === scopeKey(source.application_scope) && samePosition(root, source));
      const groups = new Set(matches.map((root) => JSON.stringify(TechnicalRequirementEquivalence.key(root))));
      if (groups.size !== 1) continue;
      const target = matches[0].requirement_id;
      (sources_by_target[target] ||= []).push(source.requirement_id); suppressed_ids.push(source.requirement_id);
    }
    return { sources_by_target, suppressed_ids };
  }
  function bindSources(review) {
    const links = sourceLinks(review), changed = [];
    for (const item of review?.technical_requirements || []) {
      const mapping = item.surface_mapping;
      if (!mapping || typeof mapping !== "object") continue;
      const desired = links.sources_by_target[item.requirement_id] || [], before = mapping.source_requirement_ids || [];
      if (desired.length) mapping.source_requirement_ids = desired; else delete mapping.source_requirement_ids;
      if (JSON.stringify(before) !== JSON.stringify(desired)) changed.push({ requirement_id: item.requirement_id, before, after: desired });
    }
    return changed;
  }
  function outputSourceKeys(review) {
    const links = sourceLinks(review), suppressed = new Set(links.suppressed_ids), keys = new Set();
    const notes = (review?.technical_requirements || []).filter((v) => v && typeof v === "object");
    for (const root of notes.filter(converted)) for (const key of originalKeys(root)) keys.add(JSON.stringify([key, scopeKey(root.application_scope)]));
    for (const item of notes) if (!suppressed.has(item.requirement_id)) keys.delete(JSON.stringify([sourceKey(item.content), scopeKey(item.application_scope)]));
    return [...keys].map((value) => JSON.parse(value));
  }
  function singleSelection(item) {
    if (Array.isArray(item.surface_mapping?.catalog_ids)) item.surface_mapping.catalog_ids = item.surface_mapping.catalog_ids.slice(0, 1);
  }
  function mappingSnapshot(item, links) {
    const mapping = structuredClone(item.surface_mapping);
    mapping.catalog_ids = mapping.catalog_ids.slice(0, 1);
    const ids = links.sources_by_target[item.requirement_id] || [];
    if (ids.length) mapping.source_requirement_ids = [...ids]; else delete mapping.source_requirement_ids;
    return mapping;
  }
  globalThis.CompanySurfaceMapping = { setCatalog, namesInContent, reason, edited, choose, confirmation, confirm, readingConflict, fingerprint, withoutNames,
    sourceKey, scopeKey, sourceLinks, bindSources, outputSourceKeys, singleSelection, mappingSnapshot, getCatalog: () => catalog };
})();
