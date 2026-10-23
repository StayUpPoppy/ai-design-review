/* Company choices assist editing; content remains the only drawing text. */
(() => {
  let catalog = { version: "", items: [] };
  function setCatalog(value) {
    if (!value?.version || !Array.isArray(value.items) || value.items.length !== 49
      || new Set(value.items.map((v) => v.id)).size !== 49 || new Set(value.items.map((v) => v.name)).size !== 49
      || value.items.some((v) => typeof v.id !== "string" || !v.id || typeof v.name !== "string" || !v.name.trim())) throw new Error("公司表面处理目录格式无效");
    catalog = structuredClone(value);
  }
  function occurrences(content) {
    const text = String(content || ""), used = new Set(), found = [];
    for (const item of [...catalog.items].sort((a, b) => b.name.length - a.name.length)) {
      let start = text.indexOf(item.name);
      while (start !== -1) {
        const end = start + item.name.length;
        const occupied = Array.from({ length: end - start }, (_, i) => start + i);
        if (!occupied.some((i) => used.has(i)) && !/(?:不得|禁止|不要|不允许|不准|不需要|无需|未要求|不做|不采用|非|未|无|不)\s*(?:进行|采用|使用|实施|做)?\s*$/.test(text.slice(Math.max(0, start - 12), start))) {
          occupied.forEach((i) => used.add(i)); found.push({ start, end, id: item.id, name: item.name });
        }
        start = text.indexOf(item.name, end);
      }
    }
    return found.sort((a, b) => a.start - b.start);
  }
  const namesInContent = (content) => [...new Set(occurrences(content).map((v) => v.id))];
  function reason(item) {
    const mapping = item?.surface_mapping;
    if (!mapping || typeof mapping !== "object") return "";
    const ids = mapping.catalog_ids;
    if (!["auto", "manual", "none"].includes(mapping.selection_mode)) return "公司类型无效，请重新选择或置空";
    if (mapping.conversion_status === "needs_input") return "表面处理转换未完成，请补充中文要求";
    if (mapping.selection_mode === "none" && Array.isArray(ids) && !ids.length) return "";
    if (!catalog.items.length) return "公司类型目录尚未加载，请重试";
    if (!Array.isArray(ids) || ids.some((id) => !catalog.items.some((v) => v.id === id)) || new Set(ids).size !== ids.length) return "公司类型无效，请重新选择或置空";
    if (mapping.selection_mode === "none") return ids.length ? "公司类型无效，请重新选择或置空" : "";
    if (mapping.selection_mode === "auto" && mapping.conversion_status !== "converted") return "表面处理转换未完成，请补充中文要求";
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
    return finish(item);
  }
  function choose(item, ids) {
    const mapping = ensure(item), before = [...mapping.catalog_ids].slice(0, 1);
    const original = String(item.content || "");
    const selected = [...new Set(ids.filter(Boolean))].slice(0, 1);
    if (before.length === selected.length) {
      const replacements = [];
      for (let i = 0; i < before.length; i++) {
        if (before[i] === selected[i]) continue;
        const matches = occurrences(original).filter((v) => v.id === before[i]);
        const next = catalog.items.find((v) => v.id === selected[i]);
        if (matches.length !== 1 || !next) { replacements.length = 0; break; }
        replacements.push({ ...matches[0], value: next.name });
      }
      let content = original;
      for (const r of replacements.sort((a, b) => b.start - a.start)) content = content.slice(0, r.start) + r.value + content.slice(r.end);
      item.content = content;
    } else if (!original.trim() && selected.length) {
      item.content = selected.map((id) => catalog.items.find((v) => v.id === id)?.name || "").join("，");
    }
    mapping.catalog_ids = selected;
    mapping.selection_mode = selected.length ? "manual" : "none";
    if (mapping.conversion_status !== "needs_input" || item.content !== original) mapping.conversion_status = "converted";
    return finish(item);
  }
  function finish(item) {
    const mapping = item.surface_mapping;
    mapping.catalog_ids = mapping.catalog_ids.slice(0, 1);
    mapping.input_snapshot = { content: String(item.content || "").trim(), type: item.type || "surface" };
    mapping.conflict = reason(item) === "公司类型与正文不一致";
    item.standard_content = String(item.content || "").trim();
    return reason(item);
  }
  function fingerprint(item) {
    const m = item?.surface_mapping;
    return m ? { catalog_version: m.catalog_version, catalog_ids: m.catalog_ids, selection_mode: m.selection_mode, conversion_status: m.conversion_status } : null;
  }
  const withoutNames = (content) => [...catalog.items].sort((a, b) => b.name.length - a.name.length).reduce((text, v) => text.split(v.name).join(""), String(content || ""));
  const sourceKey = (value) => String(value || "").normalize("NFKC").trim()
    .replace(/^\d+\s*[.、)]\s*(?=[^\d\s])/, "").replace(/^(?:表面处理|表面處理|表面要求)\s*[:：]\s*/, "")
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
    for (const item of notes) if (!suppressed.has(item.requirement_id) && !converted(item)) keys.delete(JSON.stringify([sourceKey(item.content), scopeKey(item.application_scope)]));
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
  globalThis.CompanySurfaceMapping = { setCatalog, namesInContent, reason, edited, choose, fingerprint, withoutNames,
    sourceKey, scopeKey, sourceLinks, bindSources, outputSourceKeys, singleSelection, mappingSnapshot, getCatalog: () => catalog };
})();
