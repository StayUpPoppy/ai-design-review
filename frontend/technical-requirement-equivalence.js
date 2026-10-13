/* Deterministic engineering-note equivalence; fixtures also run against Python. */
(() => {
  const labels = { surface: "表面处理", surface_roughness: "表面粗糙度", hardness: "硬度要求", heat_treatment: "热处理", salt_spray: "盐雾试验", environmental: "环保要求", lifetime: "寿命要求", process: "工艺要求", other: "其他要求" };
  const prefixes = { "热处理要求": "heat_treatment", "热处理": "heat_treatment", "盐雾要求": "salt_spray", "盐雾试验": "salt_spray", "盐雾测试": "salt_spray", "表面处理要求": "surface", "表面处理": "surface", "硬度要求": "hardness", "材料环保要求": "environmental", "环保要求": "environmental", "寿命要求": "lifetime", "寿命测试": "lifetime", "工艺要求": "process", "其他要求": "other" };
  const aliases = { surface_requirement: "surface", surface_treatment: "surface", roughness: "surface_roughness", surface_finish: "surface_roughness", "表面粗糙度": "surface_roughness", hardness_requirement: "hardness", heat: "heat_treatment", "heat-treatment": "heat_treatment", salt: "salt_spray", salt_spray_test: "salt_spray", environment: "environmental", environmental_requirement: "environmental", life: "lifetime", process_requirement: "process" };
  const prefixPattern = new RegExp(`^(${Object.keys(prefixes).join("|")})\\s*(?::\\s*|(?=[+\\-±]?\\d))`);
  const displayPrefixPattern = new RegExp(`^(${Object.keys(prefixes).join("|")})\\s*(?:[:：]\\s*|(?=[+\\-±]?\\d))`);
  function normalize(value) {
    return String(value ?? "").trim().replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
      .replace(/\u3000/g, " ").replace(/℃/g, "°C").replace(/µm/g, "μm").replace(/。/g, ".").replace(/，/g, ",").replace(/；/g, ";").replace(/−/g, "-").replace(/\s+/g, " ").trim();
  }
  function outputContent(item) {
    return String(item?.content || "").trim().replace(/^\s*[0-9０-９]+\s*[.．、)）]\s*(?=[^0-9０-９\s])/, "");
  }

  function body(value) {
    let text = normalize(value).replace(/^\d+\s*[.、)]\s*(?=[^\d\s])/, ""), kind = null, match;
    while ((match = text.match(prefixPattern))) {
      const labelKind = prefixes[match[1]];
      if (!["other", "process"].includes(labelKind) || kind == null) kind = labelKind;
      text = text.slice(match[0].length).trim();
    }
    return [text.replace(/[.]+$/, "").trim(), kind];
  }
  function comparison(value) {
    return normalize(value).replace(/[.]+$/, "").replace(/(?<![A-Za-z0-9])\s+|\s+(?![A-Za-z0-9])/g, "")
      .replace(/(?<![A-Za-z0-9_])(Ra|Hb|H\d+|F\d+)\s+(?=[+\-±]?\d)/g, "$1")
      .replace(/(?<=\d)\s+(?=(?:mm|cm|μm|min|MPa|N|h|s|kg)(?![A-Za-z0-9_]))/g, "");
  }
  function type(value) {
    const normalized = String(value || "").trim().toLowerCase().replace(/ /g, "_");
    return aliases[normalized] || (labels[normalized] ? normalized : "other");
  }
  function key(item) {
    const [text, prefixKind] = body(outputContent(item).replace(/(?:\s*(?:\r\n?|\n)\s*)+/g, "；").replace(/[\t ]+/g, " ").replace(/；{2,}/g, "；"));
    const kind = prefixKind || type(item?.type);
    return [kind === "process" ? "other" : kind, comparison(text), comparison(item?.application_scope)];
  }
  function equivalent(left, right) {
    return Boolean(String(left?.content || "").trim()) && JSON.stringify(key(left)) === JSON.stringify(key(right));
  }
  function format(item) {
    let text = outputContent(item).replace(/(?:\s*(?:\r\n?|\n)\s*)+/g, "；").replace(/[\t ]+/g, " ").replace(/；{2,}/g, "；").trim();
    if (!text) return "";
    const [, prefixKind] = body(text), kind = prefixKind || type(item?.type);
    text = text.replace(/^\d+\s*[.．、)]\s*(?=[^\d\s])/, "");
    let match;
    while ((match = text.match(displayPrefixPattern))) text = text.slice(match[0].length).trim();
    const scope = String(item?.application_scope || "").trim();
    if (text && scope && !text.includes(scope)) text = `${text.replace(/[。.]+$/, "")}（作用范围：${scope}）`;
    return !text ? "" : kind === "surface_roughness" ? text : `${labels[kind]}：${text}`;
  }
  function unlabel(item) {
    let text = outputContent(item), match;
    while ((match = text.match(displayPrefixPattern))) text = text.slice(match[0].length).trim();
    return text;
  }
  function formatText(requirements) {
    const lines = [], seen = new Set();
    for (const item of Array.isArray(requirements) ? requirements : []) {
      if (!item || typeof item !== "object") continue;
      const line = format(item), identity = JSON.stringify(key(item));
      if (!line || seen.has(identity)) continue;
      seen.add(identity);
      lines.push(`${lines.length + 1}.${line}`);
    }
    return lines.join("\n");
  }
  function groups(requirements, isExportable = (item) => item.need_human_review === false && Boolean(String(item.content || "").trim())) {
    const result = [], byKey = new Map();
    for (const [index, item] of (Array.isArray(requirements) ? requirements : []).entries()) {
      if (!item || typeof item !== "object") continue;
      // Empty requirements remain separately editable rather than hiding errors.
      const identity = String(item.content || "").trim() ? JSON.stringify(key(item)) : `empty:${index}`;
      let group = byKey.get(identity);
      if (!group) { group = { key: identity, members: [] }; byKey.set(identity, group); result.push(group); }
      group.members.push({ item, index });
    }
    for (const group of result) {
      group.representative = group.members.find(({ item }) => isExportable(item)) || group.members[0];
      group.exportable = group.members.some(({ item }) => isExportable(item));
      group.confirmed = group.members.every(({ item }) => isExportable(item));
      group.ids = group.members.map(({ item }) => String(item.requirement_id || ""));
    }
    return result.sort((left, right) => left.representative.index - right.representative.index);
  }
  globalThis.TechnicalRequirementEquivalence = { normalize, body, comparison, key, equivalent, format, formatText, outputContent, groups, unlabel };
})();
