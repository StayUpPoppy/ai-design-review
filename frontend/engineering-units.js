(function (global) {
  const pound = 0.45359237;
  const inch = 25.4;
  const force = pound * 9.80665;
  const stress = force * 1000 / inch ** 2;
  const imperial = {
    mm: ["in", inch], N: ["lbf", force], "N/mm": ["lbf/in", force / inch], MPa: ["ksi", stress],
    "μm": ["μin", 0.0254], kg: ["lb", pound], "g/cm³": ["lb/in³", pound * 1e6 / inch ** 3], "N·mm": ["lbf·in", force * inch],
  };
  const metric = Object.fromEntries(Object.entries(imperial).map(([unit, [display, factor]]) => [display, [unit, factor]]));
  Object.assign(metric, { inch: metric.in, inches: metric.in, kgf: ["N", 9.80665], "kgf/mm": ["N/mm", 9.80665],
    lbs: ["lb", 1], psi: ["MPa", stress / 1000], kN: ["N", 1000], "µin": metric["μin"], um: ["μm", 1], "µm": ["μm", 1] });

  function number(value, factor) {
    if (value == null || value === "" || typeof value === "boolean" || !Number.isFinite(Number(value))) return value;
    if (factor === 1) return Number(value);
    return Number((Number(value) * factor).toPrecision(15));
  }

  const displayNumber = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3, useGrouping: false });
  function format(value) {
    if (value == null || value === "" || typeof value === "boolean" || !Number.isFinite(Number(value))) return String(value ?? "");
    return displayNumber.format(value).replace(/^-0$/, "0");
  }

  function scale(unit, mode) { return mode === "imperial" ? imperial[unit]?.[1] || 1 : 1; }
  function displayUnit(unit, mode) { return mode === "imperial" ? imperial[unit]?.[0] || unit : unit; }
  function toDisplay(value, unit, mode) { return number(value, 1 / scale(unit, mode)); }
  function fromDisplay(value, unit, mode) { return number(value, scale(unit, mode)); }

  function annotationBaseValue(record, kind) {
    if (!record || record.unit_pending || record.value == null || record.value === "" || typeof record.value === "boolean") return null;
    const unit = String(record.unit || "").normalize("NFKC").trim().toLowerCase().replace(/\.$/, "");
    const factors = kind === "length"
      ? { mm: 1, 毫米: 1, cm: 10, 厘米: 10, m: 1000, 米: 1000, in: inch, inch, inches: inch, 英寸: inch, '"': inch, "″": inch, ft: 12 * inch }
      : { "μm": 1, um: 1, "μin": 0.0254, uin: 0.0254, microinch: 0.0254, microinches: 0.0254 };
    const result = Number(record.value) * factors[unit];
    return Number.isFinite(result) ? result : null;
  }

  function item(record, mode, fallback) {
    const unit = record.unit || fallback;
    if (mode !== "imperial" || record.unit_pending || !imperial[unit]) return record;
    const result = { ...record, unit: displayUnit(unit, mode) };
    for (const key of ["value", "tolerance_upper", "tolerance_lower", "minimum", "maximum", "lower_limit", "upper_limit"]) {
      if (key in record) result[key] = toDisplay(record[key], unit, mode);
    }
    if (record.formula_recalculation_candidate) result.formula_recalculation_candidate = item(record.formula_recalculation_candidate, mode, unit);
    return result;
  }

  function point(record, mode) {
    if (mode !== "imperial" || record.unit_pending) return record;
    const heightUnit = record.height_unit || "mm", forceUnit = record.force_unit || "N";
    return { ...record, height_unit: displayUnit(heightUnit, mode), force_unit: displayUnit(forceUnit, mode),
      height: toDisplay(record.height, heightUnit, mode), force: toDisplay(record.force, forceUnit, mode),
      load_tolerance_upper: toDisplay(record.load_tolerance_upper, forceUnit, mode),
      load_tolerance_lower: toDisplay(record.load_tolerance_lower, forceUnit, mode),
      force_alternatives: record.force_alternatives?.map(value => toDisplay(value, forceUnit, mode)),
    };
  }

  function tolerance(value, factor) {
    if (!value.ok || factor === 1) return value;
    return { ...value, upper: number(value.upper, factor), lower: number(value.lower, factor) };
  }

  const numeric = String.raw`[+−-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?`;
  const unitPattern = String.raw`(?:lbf|lbs?|kgf|kg|英磅|磅力|磅|公斤力)\s*(?:/|per\s+|每)\s*(?:inches|inch|in\.?|mm|毫米|英寸)|(?:kN|N)\s*/\s*mm(?:\^?2|²)?|g/cm[³3]|lb/in[³3]|N·mm|lbf·in|[μµu](?:m|in)|MPa|ksi|psi|kgf|kg|lbs?|lbf|kN|N|mm|inches|inch|in|英寸|毫米|英磅|磅力|磅|公斤力|公斤|牛顿`;
  const span = new RegExp(String.raw`(?<![A-Za-z\d_.])(${numeric}(?:(?:\s*(?:±|\+\s*/\s*-|/|\bto\b|至|～|–|-)\s*|\s*\+(?=\s*[\d.]))${numeric}){0,2})(\s*)(${unitPattern}|%|°)(?![a-z\d]|\s*\.?\s*w\.?\s*c\.?\b|\s*H2O\b|\s*/\s*[a-z])`, "giu");
  const canonicalUnits = { "毫米": "mm", "英寸": "in", "牛顿": "N", "公斤力": "kgf", "磅力": "lbf", "磅": "lb", "英磅": "lb", "公斤": "kg",
    "n": "N", "kn": "kN", "mpa": "MPa", "n/mm": "N/mm", "n·mm": "N·mm", "n/mm²": "MPa", "n/mm2": "MPa", "lb/in3": "lb/in³", "g/cm3": "g/cm³",
    "lb/in": "lbf/in", "lbs/in": "lbf/in", "英磅/英寸": "lbf/in", "磅力/英寸": "lbf/in", "公斤力/毫米": "kgf/mm", "kg/mm": "kgf/mm" };

  function text(content, mode, { display = false, original = null } = {}) {
    const oldValues = original == null ? [] : [...String(original).matchAll(span)];
    const editedValues = original == null ? [] : [...String(content ?? "").matchAll(span)];
    const retained = new Map();
    if (original != null) {
      const projected = [...text(original, mode).matchAll(span)].map(match => match[0]);
      // Match the engineering spans in order so edits to surrounding prose
      // leave the exact canonical values and units intact.
      const lengths = Array.from({ length: oldValues.length + 1 }, () => new Uint32Array(editedValues.length + 1));
      for (let i = oldValues.length - 1; i >= 0; i--) {
        for (let j = editedValues.length - 1; j >= 0; j--) {
          lengths[i][j] = projected[i] === editedValues[j][0] ? 1 + lengths[i + 1][j + 1] : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
        }
      }
      for (let i = 0, j = 0; i < oldValues.length && j < editedValues.length;) {
        if (projected[i] === editedValues[j][0]) retained.set(editedValues[j++].index, oldValues[i++][0]);
        else if (lengths[i + 1][j] >= lengths[i][j + 1]) i++;
        else j++;
      }
      mode = "metric";
    }
    return String(content ?? "").replace(span, (match, values, gap, suffix, offset, source) => {
      if (retained.has(offset)) return retained.get(offset);
      const key = suffix.toLowerCase().replace(/\s*per\s*|每/gi, "/").replace(/[\s.]/g, "");
      let unit = canonicalUnits[key] || key;
      const context = source.slice(Math.max(source.lastIndexOf("；", offset), source.lastIndexOf(";", offset), source.lastIndexOf("\n", offset)) + 1, offset);
      if (mode === "metric" && /^(?:lb|lbs|kg)$/.test(unit)) {
        if (/\b(?:load|force)\b|载荷|负载|负荷|力值|弹力/i.test(context)) unit = unit === "kg" ? "kgf" : "lbf";
        else if (!/\b(?:mass|weight)\b|重量|质量/i.test(context) && !display) return match;
        else if (unit === "lbs") unit = "lb";
      }
      const pair = (mode === "imperial" ? imperial : metric)[unit];
      if (!pair && !display) return match;
      const [target, factor] = pair || [suffix, 1];
      const numbers = values.replace(new RegExp(numeric, "gi"), (token, index) => {
        // A hyphen between unsigned range endpoints belongs to the range.
        const separator = token.startsWith("-") && /[\d.]$/.test(values.slice(0, index)) ? "-" : "";
        if (separator) token = token.slice(1);
        const value = Number(token.replace("−", "-"));
        const converted = number(value, mode === "imperial" ? 1 / factor : factor);
        return separator + (token.startsWith("+") ? "+" : "") + (display ? format(converted) : converted);
      });
      return `${numbers}${pair ? " " : gap}${target}`;
    });
  }

  global.EngineeringUnits = { item, point, displayUnit, scale, fromDisplay, toDisplay, tolerance, text, format, annotationBaseValue };
})(globalThis);
