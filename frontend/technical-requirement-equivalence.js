/* Deterministic engineering-note equivalence; fixtures also run against Python. */
(() => {
  const labels = { surface: "表面处理", surface_roughness: "表面粗糙度", hardness: "硬度要求", heat_treatment: "热处理", salt_spray: "盐雾试验", environmental: "环保要求", lifetime: "寿命要求", process: "工艺要求", other: "其他要求" };
  const prefixes = { "热处理要求": "heat_treatment", "热处理": "heat_treatment", "盐雾要求": "salt_spray", "盐雾试验": "salt_spray", "盐雾测试": "salt_spray", "表面处理要求": "surface", "表面处理": "surface", "硬度要求": "hardness", "硬度": "hardness", "材料环保要求": "environmental", "环保要求": "environmental", "环保": "environmental", "寿命要求": "lifetime", "寿命测试": "lifetime", "寿命": "lifetime", "盐雾": "salt_spray", "工艺要求": "process", "工艺": "process", "其他要求": "other", "其他": "other" };
  const aliases = { surface_requirement: "surface", surface_treatment: "surface", roughness: "surface_roughness", surface_finish: "surface_roughness", "表面粗糙度": "surface_roughness", hardness_requirement: "hardness", heat: "heat_treatment", "heat-treatment": "heat_treatment", salt: "salt_spray", salt_spray_test: "salt_spray", environment: "environmental", environmental_requirement: "environmental", life: "lifetime", process_requirement: "process" };
  const hardnessScale = "(?:HBW|HRC|HRA|HRB|HV|HB)", numberToken = String.raw`[+\-]?[0-9]+(?:\.[0-9]+)?`;
  const prefixLabels = Object.keys(prefixes).sort((a, b) => b.length - a.length);
  function leadingLabel(text) {
    for (const label of prefixLabels) {
      if (!text.startsWith(label)) continue;
      const rest = text.slice(label.length).replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
      let boundary = rest.match(/^\s*[:：]\s*/) || rest.match(/^\s*(?=[+\-±]?[0-9０-９])/);
      if (!boundary && prefixes[label] === "hardness") boundary = rest.match(new RegExp(String.raw`^\s*(?=${hardnessScale}\s*(?:[<>≤≥]=?\s*)?[+\-]?[0-9０-９])`, "i"));
      if (boundary) return { end: label.length + boundary[0].length, kind: prefixes[label] };
    }
    return null;
  }
  function normalize(value) {
    return String(value ?? "").trim().replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
      .replace(/\u3000/g, " ").replace(/℃/g, "°C").replace(/µm/g, "μm").replace(/。/g, ".").replace(/，/g, ",").replace(/；/g, ";").replace(/−/g, "-").replace(/\s+/g, " ").trim();
  }
  function outputContent(item) {
    return String(item?.content || "").trim().replace(/^\s*[0-9０-９]+\s*[.．、)）]\s*(?=[^0-9０-９\s])/, "");
  }

  function body(value) {
    let text = normalize(value).replace(/^\d+\s*[.、)]\s*(?=[^\d\s])/, ""), kind = null, match;
    while ((match = leadingLabel(text))) {
      if (!["other", "process"].includes(match.kind) || kind == null) kind = match.kind;
      text = text.slice(match.end).trim();
    }
    return [text.replace(/[.]+$/, "").trim(), kind];
  }
  function comparison(value) {
    return normalize(value).replace(/[.]+$/, "").replace(/(?<![A-Za-z0-9])\s+|\s+(?![A-Za-z0-9])/g, "")
      .replace(/(?<![A-Za-z0-9_])(Ra|Hb|H\d+|F\d+)\s+(?=[+\-±]?\d)/g, "$1")
      .replace(/(?<=\d)\s+(?=(?:mm|cm|μm|min|MPa|N|h|s|kg)(?![A-Za-z0-9_]))/g, "");
  }
  // Lossless comparison: rewrite recognized tokens; keep every unmatched condition in order.
  const unitAliases = { "摄氏度": "°C", "°C": "°C", "微米": "μm", "µm": "μm", um: "μm", "μm": "μm",
    "毫米": "mm", mm: "mm", "厘米": "cm", cm: "cm", "纳米": "nm", nm: "nm", "分钟": "min", min: "min",
    "小时": "h", h: "h", "秒钟": "s", "秒": "s", s: "s", "兆帕": "MPa", MPa: "MPa", "牛顿": "N", N: "N", "%": "%" };
  const escapePattern = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const unitPattern = String.raw`(?:°\s*C|${Object.keys(unitAliases).filter((u) => u !== "°C").sort((a,b) => b.length-a.length).map(escapePattern).join("|")})`;
  const quantityPattern = new RegExp(String.raw`(?<![\d.])(${numberToken})\s*(${unitPattern})(?![A-Za-z0-9_])`, "g");
  const rangePattern = new RegExp(String.raw`(?<![A-Za-z0-9_.])(${numberToken})\s*(${unitPattern})?\s*([~–—至到-])\s*(${numberToken})\s*(${unitPattern})(?![A-Za-z0-9_])`, "g");
  const hardnessRange = new RegExp(String.raw`(?<![A-Za-z0-9_])(${hardnessScale})\s*(${numberToken})\s*([~–—至到-])\s*(${numberToken})(?![\d.])`, "gi");
  const rangeBody = (left, separator, right) => Number(left) > Number(right) ? `${left}${separator}${right}` : `${left}~${right}`;
  function engineeringComparison(value, kind) {
    let text = normalize(value);
    if (kind === "surface_roughness") return comparison(text);
    if (kind === "lifetime") {
      text = text.replace(/(?<![A-Za-z0-9_.])([0-9]+)万次/g, (_, n) => `${n.replace(/^0+/, "") ? n.replace(/^0+/, "") + "0000" : "0"}次`)
        .replace(/(?:每)?(?:(?<![一二三四五六七八九十])一|(?<![A-Za-z0-9_.])1)\s*秒(?:钟)?\s*(?:一|1)\s*次/g, "每秒1次")
        .replace(/每\s*秒(?:钟)?\s*([0-9]+)\s*次/g, "每秒$1次")
        .replace(/(?<![A-Za-z0-9_.])([0-9]+)\s*次\s*\/\s*秒(?:钟)?/g, "每秒$1次");
    }
    if (kind === "hardness") {
      const suffix = new RegExp(String.raw`(?<![A-Za-z0-9_.])(${numberToken})(?:\s*([~–—至到-])\s*(${numberToken}))?\s*(${hardnessScale})(?![A-Za-z0-9_/]|\.[0-9])`, "gi");
      text = text.replace(suffix, (_, left, separator, right, scale) => scale.toUpperCase() + (right != null ? rangeBody(left, separator, right) : left));
      text = text.replace(new RegExp(String.raw`(?<![A-Za-z0-9_])(${hardnessScale})\s*(?=[<>≤≥+\-\d])`, "gi"), (_, scale) => scale.toUpperCase());
      text = text.replace(hardnessRange, (_, scale, left, separator, right) => scale.toUpperCase() + rangeBody(left, separator, right));
    }
    if (kind === "salt_spray") {
      for (const [wording, code] of [["铜加速乙酸盐雾", "CASS"], ["乙酸盐雾", "AASS"], ["中性盐雾", "NSS"]]) text = text.replace(new RegExp(`${wording}(?:试验|测试)?`, "g"), code);
      text = text.replace(/(?<![A-Za-z0-9_])(NSS|AASS|CASS)(?![A-Za-z_])/gi, (code) => code.toUpperCase());
    }
    if (kind === "environmental") text = text.replace(/(?<![A-Za-z0-9_])(RoHS|REACH)(?![A-Za-z_])/gi, (code) => code.toLowerCase() === "rohs" ? "RoHS" : "REACH");
    if (["salt_spray", "environmental"].includes(kind)) text = text.replace(/(?<![A-Za-z0-9_])(NSS|AASS|CASS|RoHS|REACH)\s+(?=[0-9])/g, "$1");
    for (const [wording, symbol] of [["小于等于", "≤"], ["大于等于", "≥"], ["不大于", "≤"], ["不小于", "≥"], ["小于", "<"], ["大于", ">"]]) text = text.replace(new RegExp(String.raw`${wording}(?=\s*[+\-]?[0-9])`, "g"), symbol);
    text = text.replace(/<=/g, "≤").replace(/>=/g, "≥");
    text = text.replace(quantityPattern, (_, n, unit) => n + unitAliases[unit.replace(/\s+/g, "")]);
    text = text.replace(rangePattern, (full, left, leftUnit, separator, right, rightUnit) => {
      leftUnit = (leftUnit || "").replace(/\s+/g, ""); rightUnit = rightUnit.replace(/\s+/g, "");
      if (leftUnit && (leftUnit !== rightUnit || separator === "-")) return full;
      if (separator === "-" && ["other", "process", "environmental"].includes(kind)) return full;
      return rangeBody(left, separator, right) + rightUnit;
    });
    text = text.replace(/(?<![A-Za-z0-9_])(GB\/T|GB|ISO|EN|DIN)\s+(?=[0-9])/g, "$1");
    return comparison(text);
  }
  function type(value) {
    const normalized = String(value || "").trim().toLowerCase().replace(/ /g, "_");
    return aliases[normalized] || (labels[normalized] ? normalized : "other");
  }
  function key(item) {
    const [text, prefixKind] = body(outputContent(item).replace(/(?:\s*(?:\r\n?|\n)\s*)+/g, "；").replace(/[\t ]+/g, " ").replace(/；{2,}/g, "；"));
    const kind = prefixKind || type(item?.type);
    const comparisonKind = kind === "process" ? "other" : kind;
    return [comparisonKind, engineeringComparison(text, comparisonKind), comparison(item?.application_scope)];
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
    while ((match = leadingLabel(text))) text = text.slice(match.end).trim();
    const scope = String(item?.application_scope || "").trim();
    if (text && scope && !text.includes(scope)) text = `${text.replace(/[。.]+$/, "")}（作用范围：${scope}）`;
    return !text ? "" : kind === "surface_roughness" ? text : `${labels[kind]}：${text}`;
  }
  function unlabel(item) {
    let text = outputContent(item), match;
    while ((match = leadingLabel(text))) text = text.slice(match.end).trim();
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
