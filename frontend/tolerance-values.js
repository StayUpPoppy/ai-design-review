/* Signed engineering values shared by quick input and the inline editor. */
(() => {
  const number = value => {
    if (typeof value === "boolean" || value == null || String(value).trim() === "") return null;
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(String(value).trim())) return null;
    const result = Number(value); return Number.isFinite(result) ? result || 0 : null;
  };
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const text = value => value == null ? "" : String(value === 0 ? 0 : value);
  const signed = value => value > 0 ? `+${text(value)}` : text(value);
  const empty = value => value == null || String(value).trim() === "";
  function validate(upper, lower, percent = null) {
    if (percent != null) return number(percent) != null && Number(percent) >= 0
      ? { ok: true, upper: null, lower: null, percent: Number(percent) || 0 }
      : { ok: false, error: "百分比必须是有限的非负数。" };
    if (empty(upper) && empty(lower)) return { ok: true, upper: null, lower: null, percent: null };
    if (empty(upper) || empty(lower)) return { ok: false, error: "请填写上下偏差；单边公差请将另一侧明确填 0。" };
    const u = number(upper), l = number(lower);
    if (u == null || l == null) return { ok: false, error: "上下偏差必须是有效数字，可带正负号。" };
    if (u < l) return { ok: false, error: "上偏差不能小于下偏差，请核对正负号。" };
    return { ok: true, upper: u, lower: l, percent: null };
  }
  function parse(value, { load = false, unit = "" } = {}) {
    let input = String(value ?? "").normalize("NFKC").trim().replace(/−/g, "-");
    const normalizedUnit = String(unit).normalize("NFKC");
    if (unit && input.toLowerCase().endsWith(normalizedUnit.toLowerCase())) input = input.slice(0, -normalizedUnit.length).trim();
    if (!input) return validate(null, null);
    if (load && input.endsWith("%")) return validate(null, null, input.slice(0, -1).replace(/^±\s*/, ""));
    if (input.startsWith("±")) {
      const magnitude = number(input.slice(1).trim());
      return magnitude != null && magnitude >= 0 ? validate(magnitude, -magnitude) : { ok: false, error: "对称公差幅值必须是非负数，例如 ±0.1。" };
    }
    const parts = input.split("/");
    return parts.length === 2 ? validate(parts[0], parts[1]) : { ok: false, error: "请输入 ±0.1 或 +0.1/-0.2，也可点击编辑公差。" };
  }
  function read(item, load = false) {
    const upper = item?.[load ? "load_tolerance_upper" : "tolerance_upper"] ?? null;
    const lower = item?.[load ? "load_tolerance_lower" : "tolerance_lower"] ?? null;
    const percent = load && upper == null && lower == null ? item?.load_tolerance_percent ?? item?.force_tolerance_percent ?? null : null;
    return { upper, lower, percent };
  }
  function format(value) {
    if (value.percent != null) return `±${text(value.percent)}%`;
    if (value.upper == null && value.lower == null) return "";
    if (value.upper != null && value.lower != null && Number(value.upper) >= 0 && Number(value.upper) === -Number(value.lower)) return `±${text(Number(value.upper))}`;
    return `${value.upper == null ? "" : signed(Number(value.upper))}/${value.lower == null ? "" : signed(Number(value.lower))}`;
  }
  const equals = (a, b) => ["upper", "lower", "percent"].every(k => a[k] == null && b[k] == null || a[k] != null && b[k] != null && number(a[k]) === number(b[k]));
  const pretty = value => String(Number(value.toPrecision(12)) || 0);
  function preview(value, nominal, unit) {
    if (!value.ok) return "请填写有效公差后查看范围";
    if (value.upper == null && value.lower == null && value.percent == null) return "未设置公差";
    const base = number(nominal);
    if (base == null) return "补齐有效名义值后显示允许范围";
    const upper = value.percent != null ? Math.abs(base) * value.percent / 100 : value.upper;
    const lower = value.percent != null ? -Math.abs(base) * value.percent / 100 : value.lower;
    if (![base + lower, base + upper].every(Number.isFinite)) return "数值超出可计算范围，请核对";
    return `${pretty(base + lower)} ～ ${pretty(base + upper)}${unit ? ` ${unit}` : ""}`;
  }
  globalThis.ToleranceValues = { number, esc, text, signed, empty, validate, parse, read, format, equals, preview };
})();
