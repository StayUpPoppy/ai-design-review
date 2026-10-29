/* A read-only report: selection and printing never adopt or confirm parameters. */
(() => {
  const logoBase = typeof document === "undefined" ? "" : document.currentScript?.src || document.baseURI;
  const LOGO_ERROR = "Logo加载失败，请点击“刷新预览”重试。";
  let logoRequest = null;
  async function loadLogo() {
    if (!logoRequest) {
      // The only permitted image comes from this bundled PNG, never review text.
      const request = (async () => {
        const response = await fetch(new URL("./assets/incospring-logo.png?v=20261028", logoBase), { cache: "reload", signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw new Error(LOGO_ERROR);
        const bytes = new Uint8Array(await response.arrayBuffer());
        const signature = [137, 80, 78, 71, 13, 10, 26, 10];
        if (!signature.every((value, index) => bytes[index] === value)) throw new Error(LOGO_ERROR);
        return `data:image/png;base64,${btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(""))}`;
      })();
      logoRequest = request;
      request.catch(() => { if (logoRequest === request) logoRequest = null; });
    }
    try { return await logoRequest; } catch { throw new Error(LOGO_ERROR); }
  }
  function printLogoUrl(logoData) {
    // An intrinsic 38mm canvas scales the original PNG without changing its
    // pixels. Foreground page content also prints with backgrounds disabled.
    return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="38mm" height="12mm" viewBox="0 0 380 120"><image width="380" height="120" preserveAspectRatio="xMinYMid meet" href="${logoData}"/></svg>`)}`;
  }
  function printHeaderCss(logoData) {
    // Native page-margin boxes repeat on the final fragment too. Negative
    // fixed-position offsets can omit the header on short final pages.
    return `@page {
      @top-left { content: url("${printLogoUrl(logoData)}"); width: 42mm; margin-top: 6mm; margin-bottom: 4mm; vertical-align: middle; border-bottom: 1px solid #aab3bf; }
      @top-center { content: "弹簧参数确认单"; margin-top: 6mm; margin-bottom: 4mm; vertical-align: middle; color: #172033; font: 700 16pt "Microsoft YaHei", "Segoe UI", Arial, sans-serif; border-bottom: 1px solid #aab3bf; }
      @top-right { content: ""; width: 42mm; margin-top: 6mm; margin-bottom: 4mm; border-bottom: 1px solid #aab3bf; }
    }`;
  }
  const empty = value => value == null || typeof value === "string" && !value.trim();
  const text = value => empty(value) ? "待补充" : String(value);
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function tolerance(item = {}, load = false) {
    if (item.tolerance_input_draft) return String(item.tolerance_input_draft);
    if (load && !empty(item.load_tolerance_percent)) return `±${item.load_tolerance_percent}%`;
    const upper = item[load ? "load_tolerance_upper" : "tolerance_upper"], lower = item[load ? "load_tolerance_lower" : "tolerance_lower"];
    if (empty(upper) && empty(lower)) return "—";
    if (!empty(upper) && !empty(lower) && Number(upper) === -Number(lower) && Number(upper) >= 0) return `±${upper}`;
    const signed = value => empty(value) ? "未注明" : Number(value) > 0 ? `+${value}` : String(value);
    return `${signed(upper)} / ${signed(lower)}`;
  }
  function calculationRows(checks, fieldLabel = field => field, context = {}) {
    const params = context.review?.spring_parameters || {}, points = params.load_points || [];
    const isSolid = point => ["fb", "pb", "压并载荷", "压并负荷", "压并力"].includes(String(point.label || "").replace(/[\s_]/g, "").toLowerCase());
    function fieldProblems(field, path = []) {
      if (path.includes(field)) return [`${fieldLabel(field)}的计算依赖循环`];
      const item = params[field];
      // The calculator may derive a missing mean diameter or active-coil count.
      if (empty(item?.value) && field === "mean_diameter") {
        const alternatives = [["outer_diameter", "inner_diameter"], ["outer_diameter", "wire_diameter"], ["inner_diameter", "wire_diameter"]];
        const actual = alternatives.find(fields => fields.every(f => !empty(params[f]?.value)));
        if (actual) return actual.flatMap(f => fieldProblems(f, [...path, field]));
      }
      if (empty(item?.value) && field === "active_coils" && typeof CompressionDesignChecks !== "undefined") {
        const sources = Array.isArray(item?.source) ? item.source : [item?.source];
        if (!item?.human_modified && !sources.some(s => /^(human|manual)/.test(s || ""))) {
          const inferred = CompressionDesignChecks.activeCalculation(params);
          if (Number.isFinite(inferred.value)) return inferred.source_fields.flatMap(f => fieldProblems(f, [...path, field]));
        }
      }
      const state = context.parameterState?.(field);
      if (state?.state !== "已确认") return [`${fieldLabel(field)}${state?.reason ? `：${state.reason}` : "尚未核对确认"}`];
      const sources = Array.isArray(item?.source) ? item.source : [item?.source];
      const generated = !item?.human_modified && sources.some(s => /formula|derived|company_active_coil/.test(s || ""));
      return generated ? (item.source_fields || []).flatMap(f => fieldProblems(f, [...path, field])) : [];
    }
    function assessment(key, item) {
      if (context.assessmentAvailable === false) return { assessment: "rfi", reason: "本次合理性检查未完成，请核对计算依据。" };
      const estimated = item.estimated === true || item.status === "estimated";
      let fields = [...(item.source_fields || [])].filter(f => f !== "load_points"), problems = [];
      if (key === "solid_stress" || key.startsWith("work_stress:")) {
        const solid = key === "solid_stress", applicable = points.filter(p => isSolid(p) === solid);
        const point = item.load_point_id != null ? applicable.find(p => p.load_point_id === item.load_point_id)
          : applicable.find(p => p.label === item.label) || (solid && applicable.length === 1 ? applicable[0] : null);
        // Explicit forces do not depend on spring rate, free height or other tests.
        fields = ["mean_diameter", "wire_diameter"];
        if (point) {
          const state = context.loadState?.(point);
          if (state?.state !== "已确认") problems.push(`${point.label || "载荷点"}${state?.reason ? `：${state.reason}` : "尚未核对确认"}`);
        } else if (!solid || !estimated) problems.push("对应载荷点的确认依据不完整");
        if (estimated) {
          fields.push("free_length", ...(checks?.metrics?.theoretical_spring_rate?.source_fields || []));
          if (solid) {
            const height = checks?.metrics?.solid_height_used;
            fields.push(...(["book_nominal", "open_nominal"].includes(height?.height_source)
              ? checks?.metrics?.nominal_solid_height?.source_fields || [] : ["solid_height"]));
          }
        }
      }
      if (!fields.length) problems.push("计算依赖尚未核实");
      problems.push(...[...new Set(fields)].flatMap(f => fieldProblems(f)));
      problems = [...new Set(problems)];
      return { assessment: problems.length ? "rfi" : "confirmed", reason: problems.join("；") };
    }
    const definitions = [
      ["spring_index", "旋绕比 C", "中径与线径之比。"],
      ["slenderness_ratio", "细长比 b", "自由高度与中径之比。"],
      ["theoretical_spring_rate", "理论刚度", "按当前尺寸和材料计算，与参数区的刚度分别列示。"],
      ["curvature_factor", "曲度系数 K", "用于剪应力修正。"],
      ["helix_angle", "螺旋角", "按当前节距和中径计算。"],
      ["wire_length", "展开长度", "按当前节距、中径和总圈数估算。"],
      ["unit_mass", "单件重量", "按当前几何和材料密度估算。"],
      ["solid_stress", "压并应力", "按压并载荷和当前几何计算。"],
      ["nominal_solid_height", "压并高度", "按端部形式、线径和圈数估算。"],
    ];
    function row(key, label, description, result) {
      const item = result || {}, inapplicable = ["not_applicable", "not_required"].includes(item.status);
      const estimated = item.estimated === true || item.status === "estimated";
      const valid = !inapplicable && ["calculated", "estimated"].includes(item.status) && Number.isFinite(item.value);
      const translated = value => String(value || "").replace(/\b[a-z]+(?:_[a-z]+)*\b/g, field => fieldLabel(field) || field);
      const missing = (item.missing_fields || []).map(fieldLabel).join("、");
      const reason = translated(item.reason) || (missing ? `缺少有效的${missing}。` : "缺少有效计算依据。");
      // Match the existing display precision, without rounding a nonzero result to zero.
      const rounded = valid ? Number(item.value.toFixed(key === "unit_mass" ? 8 : 4)) : null;
      const value = valid ? rounded === 0 && item.value !== 0 ? item.value : rounded : inapplicable ? "不适用" : "无法计算";
      let note = valid ? `${estimated ? "估算；" : ""}${description}` : `${inapplicable ? "不适用" : "无法计算"}：${reason}`;
      if (valid && Number.isFinite(item.force_n)) note = `${estimated ? "估算载荷" : "已有载荷"}：${Number(item.force_n.toFixed(4))} N；${note}`;
      const evaluated = valid ? assessment(key, item) : { assessment: "rfi", reason };
      return { id: `calculation:${key}`, field: `calculations.${key}`, label, value, unit: item.unit || "", method: valid ? estimated ? "估算" : "计算" : "",
        current: valid ? `${value}${item.unit ? ` ${item.unit}` : ""}` : value,
        note, ...evaluated, state: valid ? "calculated" : inapplicable ? "not_applicable" : "missing_context" };
    }
    const rows = definitions.map(([key, label, description]) => row(key, label, description, checks?.metrics?.[key]));
    for (const [index, item] of (checks?.work_stresses || []).entries()) {
      rows.push(row(`work_stress:${item.load_point_id || index}`, `工作应力（${item.label || `载荷点${index + 1}`}）`, "按当前载荷和几何计算。", item));
    }
    return rows;
  }
  function buildModel(data) {
    const sections = [
      { id: "parameters", label: "输入参数", rows: [...(data.parameters || []), ...(data.advanced || [])] },
      { id: "loads", label: "载荷测试点", rows: data.loads || [] },
      { id: "calculations", label: "设计校核结果", rows: data.calculations || [] },
      { id: "requirements", label: "技术要求", rows: data.requirements || [] },
    ];
    for (const section of sections) section.rows = section.rows.map(row => ({ ...row }));
    const issues = new Map();
    function issue(key, label, current = "待补充", message = "") {
      if (!issues.has(key)) issues.set(key, { id: `issue:${key}`, field: key, label, current, messages: [], suggestions: [] });
      const row = issues.get(key);
      if (message && !row.messages.includes(message)) row.messages.push(message);
      return row;
    }
    const byField = new Map(sections.flatMap(section => section.rows.map(row => [row.field, row])));
    for (const section of sections) for (const row of section.rows) {
      const confirmed = section.id === "calculations" ? row.assessment === "confirmed" : row.state === "已确认";
      row.assessment = confirmed && (data.assessmentAvailable !== false || section.id === "requirements") ? "confirmed" : "rfi";
      if (row.assessment === "rfi") {
        issue(row.field, row.label, row.current ?? row.value, row.reason || ({ "待补充": "缺少数值，请补充或注明不适用。", "已失效": "计算依据已变化，请核对当前值。", "需核对": "参数存在问题，请核对。", not_applicable: "请核对该计算是否适用。" }[row.state]
          || (data.assessmentAvailable === false && section.id !== "requirements" ? "本次合理性检查未完成，请核对。" : section.id === "calculations" ? "计算依据尚未核对确认。" : "请核对本项内容并确认。")));
      }
    }
    for (const item of data.issues || []) {
      const fields = item.fields?.length ? item.fields : [item.rule_id || item.issue_id || "general"];
      for (const field of fields) {
        const related = byField.get(field) || byField.get(`calculations.${field}`) || [...byField].find(([key]) => field.startsWith(`${key}.`))?.[1];
        issue(related?.field || field, related?.label || item.label || "参数核对", related?.current ?? related?.value, item.message || item.basis);
      }
    }
    for (const item of data.suggestions || []) {
      const related = byField.get(item.field);
      // A healthy reviewed value does not need another customer question.
      if (related?.state === "已确认" && !issues.has(item.field)) continue;
      const row = issue(item.field, related?.label || item.label || item.field, related?.current ?? related?.value);
      const proposal = item.stale ? "需重新核对（原建议未采用）" : `待确认建议：${item.value}`;
      const copy = { value: proposal, basis: item.stale ? "建议已过期或计算依据不足，请更新后核对。" : item.basis || "" };
      if (!row.suggestions.some(v => v.value === copy.value && v.basis === copy.basis)) row.suggestions.push(copy);
    }
    if (data.notice) issue("assessment", "检查状态", "—", data.notice);
    for (const section of sections) for (const row of section.rows) if (issues.has(row.field)) row.assessment = "rfi";
    for (const row of issues.values()) row.relatedIds = sections.flatMap(s => s.rows.filter(r => r.field === row.field).map(r => r.id));
    sections.push({ id: "issues", label: "待客户澄清事项", rows: [...issues.values()] });
    return { ...data.info, sections };
  }
  function effectiveSelection(model, selected) {
    const result = new Set(selected || model.sections.flatMap(section => section.rows.map(row => row.id)));
    for (const row of model.sections.find(s => s.id === "issues")?.rows || []) {
      if (row.relatedIds.some(id => result.has(id))) result.add(row.id);
    }
    return result;
  }
  const PRINT_CSS = `
    @page { size: A4 portrait; margin: 24mm 12mm 12mm; }
    * { box-sizing: border-box; }
    html { color-scheme: light; }
    body { margin: 0; color: #172033; background: #e9edf3; font: 10pt/1.32 "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }
    .sheet-wrap { margin: 16px auto; }
    .sheet { width: 210mm; min-height: 297mm; padding: 6mm 12mm 12mm; background: white; transform-origin: top left; }
    .report-content { display: flow-root; }
    .brand-header { display: grid; grid-template-columns: 42mm minmax(0, 1fr) 42mm; align-items: center; height: 14mm; margin-bottom: 4mm; border-bottom: 1px solid #aab3bf; }
    .brand-header img { display: block; width: 38mm; height: auto; max-height: 12mm; object-fit: contain; }
    .brand-header h1 { margin: 0; text-align: center; white-space: nowrap; font-size: 16pt; font-weight: 700; line-height: 1.2; }
    h2 { margin: 3mm 0 1mm; font-size: 11pt; line-height: 1.3; break-after: avoid; }
    .info { display: grid; grid-template-columns: 1fr 1fr; gap: 1mm 6mm; margin-bottom: 2mm; font-size: 9.5pt; }
    .info > div { min-width: 0; overflow-wrap: anywhere; }
    .info .wide { grid-column: 1 / -1; }
    .fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .7mm 6mm; }
    .full-lines { margin: 0; padding: 0; list-style: none; }
    .report-item { margin: 0; min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; break-inside: avoid; }
    .full-lines > .report-item + .report-item { margin-top: .8mm; }
    .long-item { break-inside: auto; }
    .field-label { font-weight: 600; }
    .number { font-variant-numeric: tabular-nums; }
    .assessment { white-space: nowrap; font-size: 9.5pt; font-weight: 600; }
    .assessment[data-state="confirmed"] { color: #245242; }
    .assessment[data-state="rfi"], .rfi-code { color: #8a4b08; }
    .basis { color: #495365; }
    .proposal { margin: .6mm 0 0; }
    .confirmation { margin-top: 3mm; break-inside: avoid; font-size: 9.5pt; }
    .opinion { min-height: 9mm; border-bottom: 1px solid #aab3bf; padding: 1mm 0; }
    .signatures { display: flex; justify-content: space-between; gap: 8mm; margin-top: 2mm; }
    .footnote { margin: 2mm 0 0; font-size: 9.5pt; color: #495365; }
    .sheet.compact { font-size: 9.5pt; line-height: 1.25; }
    .compact h2 { margin-top: 2mm; margin-bottom: .7mm; font-size: 10pt; }
    .compact .fields { row-gap: .4mm; }
    .compact .info { row-gap: .6mm; margin-bottom: 1mm; }
    .compact .full-lines > .report-item + .report-item { margin-top: .5mm; }
    @media print {
      html, body { background: white; }
      .sheet-wrap { width: auto !important; height: auto !important; margin: 0; }
      .sheet { width: auto; min-height: 0; padding: 0; transform: none !important; }
      .brand-header { display: none; }
    }
  `;
  function documentHtml(model, selected, { logoData, renderId = "" } = {}) {
    if (!/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(logoData || "")) throw new Error(LOGO_ERROR);
    selected = effectiveSelection(model, selected);
    const chosen = section => section.rows.filter(row => selected.has(row.id));
    const questions = chosen(model.sections.find(s => s.id === "issues"));
    const codes = new Map(questions.map((row, index) => [row.field, `RFI-${String(index + 1).padStart(2, "0")}`]));
    const mark = row => `<span class="assessment" data-state="${row.assessment}">【${row.assessment === "confirmed" ? "确认" : codes.get(row.field)}】</span>`;
    const attrs = row => `class="report-item${(row.content || "").length > 350 || JSON.stringify(row).length > 1200 ? " long-item" : ""}" data-report-row="${escape(row.id)}"`;
    const valueUnit = row => `${escape(text(row.value))}${!empty(row.value) && row.unit ? ` ${escape(row.unit)}` : ""}`;
    const sections = model.sections.map(section => {
      const rows = chosen(section);
      if (!rows.length) return "";
      let body;
      if (["parameters", "calculations"].includes(section.id)) body = `<div class="fields">${rows.map(row => `<p ${attrs(row)}><span class="field-label">${escape(row.label)}：</span><span class="number">${section.id === "calculations" && row.state !== "calculated" ? escape(row.value) : valueUnit(row)}${row.tolerance && row.tolerance !== "—" ? `（公差 ${escape(row.tolerance)}）` : ""}</span> ${mark(row)}</p>`).join("")}</div>`;
      if (section.id === "loads") body = `<ul class="full-lines">${rows.map(row => `<li ${attrs(row)}><span class="field-label">${escape(row.label)}：</span>高度 ${escape(row.height)}；力值 ${escape(row.force)}${row.tolerance && row.tolerance !== "—" ? `（公差 ${escape(row.tolerance)}）` : ""} ${mark(row)}</li>`).join("")}</ul>`;
      if (section.id === "requirements") body = `<ol class="full-lines">${rows.map((row, index) => `<li ${attrs(row)}>${index + 1}. ${escape(text(row.content))} ${mark(row)}</li>`).join("")}</ol>`;
      if (section.id === "issues") body = `<ol class="full-lines">${rows.map(row => {
        const proposals = row.suggestions.map(s => `<div class="proposal">${escape(s.value)}${s.basis ? ` <span class="basis">（${escape(s.basis)}）</span>` : ""}</div>`).join("");
        return `<li ${attrs(row)}><strong class="rfi-code">${codes.get(row.field)}</strong> <span class="field-label">${escape(row.label)}：</span>${escape(row.messages.join("；") || "请核对建议是否适用。")}${proposals}</li>`;
      }).join("")}</ol>`;
      return `<section><h2>${escape(section.label)}</h2>${body}</section>`;
    }).join("");
    return `<!doctype html><html lang="zh-CN" data-sheet-render="${escape(renderId)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escape(model.drawingName || "弹簧")}-参数确认单</title><style>${PRINT_CSS}${printHeaderCss(logoData)}</style></head><body><div class="sheet-wrap"><main class="sheet"><header class="brand-header"><img data-brand-logo src="${escape(logoData)}" alt="IncoSpring"><h1>弹簧参数确认单</h1></header><div class="report-content"><div class="info"><div class="wide">图纸名称：${escape(model.drawingName || "未填写")}</div><div>图号：${escape(model.drawingNo || "未填写")}</div><div>规格代号：${escape(model.variant || "—")}</div><div>制单人：${escape(model.preparer || "—")}</div><div>日期：${escape(model.date)}</div>${model.local ? '<div>数据来源：本地数据</div>' : ""}</div>${sections || "<p>未选择明细项目。</p>"}<section class="confirmation"><h2>客户回复</h2><div class="opinion">请注明RFI编号及回复；其他异议可一并填写：</div><div class="signatures"><span>姓名：________________</span><span>日期：________________</span></div></section><p class="footnote">确认＝我方已核对；RFI＝需客户澄清。客户无需逐项勾选已确认信息。</p></div></main></div></body></html>`;
  }
  function fitDocument(doc) {
    const sheet = doc.querySelector(".sheet"), content = doc.querySelector(".report-content");
    sheet.classList.remove("compact");
    const pageHeight = 261 * 96 / 25.4;
    if (content.offsetHeight > pageHeight + .5) sheet.classList.add("compact");
    const pages = Math.max(1, Math.ceil((content.offsetHeight - .5) / pageHeight));
    doc.documentElement.dataset.estimatedPages = String(pages);
    return { pages, compact: sheet.classList.contains("compact") };
  }
  // Only report inputs participate. Polling/audit bookkeeping cannot stale a sheet.
  function fingerprint(context) {
    const r = context.review || {};
    return JSON.stringify([context.editSerial, context.revision, r.drawing_summary, r.spring_parameters, r.spring_features,
      r.technical_requirements, r.standardization_results, r.parameter_reasonableness, r.parameter_reasonableness_stale, r.multi_spec_origin,
      context.materialCatalog?.version, context.materialCatalog?.status, context.materialCatalog?.items]);
  }
  function create(hooks) {
    let view = null;
    const owner = c => JSON.stringify([c.scope, c.jobId || "local", c.navigation]);
    function close() { if (view) view.dialog.close(); }
    async function open(trigger) {
      if (view) { view.dialog.querySelector('[data-sheet-action="back"]').focus(); return; }
      document.activeElement?.blur();
      const initial = hooks.context();
      if (!initial.review) return;
      if (initial.source) { hooks.message?.("请先打开对应规格的审图记录，再预览确认单。"); return; }
      if (!initial.supported) return;
      const dialog = document.createElement("dialog");
      dialog.className = "confirmation-sheet-preview";
      dialog.setAttribute("aria-labelledby", "confirmation-sheet-title");
      dialog.innerHTML = `<header><div><h2 id="confirmation-sheet-title">参数确认单预览</h2><p>A4纵向 · <span data-sheet-pages>正在准备排版</span> · 参数修改请返回原编辑区</p></div><div class="confirmation-sheet-actions"><button type="button" data-sheet-action="back">返回修改</button><button type="button" data-sheet-action="refresh">刷新预览</button><button type="button" class="primary-action" data-sheet-action="print" disabled>打印／另存为PDF</button></div></header><p class="confirmation-sheet-message" role="status" aria-live="polite"></p><div class="confirmation-sheet-layout"><details class="confirmation-sheet-options" open><summary>选择打印项目</summary><div data-sheet-choices></div></details><iframe title="A4参数确认单" sandbox="allow-same-origin allow-modals"></iframe></div>`;
      const s = { dialog, owner: owner(initial), trigger, selected: new Set(), known: new Set(), model: null, busy: false, stale: false, serial: 0, paperSerial: 0, logoData: "", token: "" };
      view = s; document.body.append(dialog);
      const active = () => view === s && owner(hooks.context()) === s.owner;
      const message = value => { dialog.querySelector(".confirmation-sheet-message").textContent = value; };
      const control = name => dialog.querySelector(`[data-sheet-action="${name}"]`);
      const frame = dialog.querySelector("iframe");
      const controls = () => {
        control("refresh").disabled = s.busy;
        control("print").disabled = s.busy || s.stale || !s.model || !s.ready;
        const requiredIssues = new Set((s.model?.sections.find(section => section.id === "issues")?.rows || [])
          .filter(row => row.relatedIds.some(id => s.selected.has(id))).map(row => row.id));
        dialog.querySelectorAll("input").forEach(input => {
          input.disabled = s.busy || requiredIssues.has(input.dataset.sheetId);
          input.title = requiredIssues.has(input.dataset.sheetId) ? "RFI说明随关联项目一起打印" : "";
          input.checked = s.selected.has(input.dataset.sheetId);
        });
      };
      const scalePaper = () => {
        const doc = frame.contentDocument, sheet = doc?.querySelector(".sheet"), wrap = doc?.querySelector(".sheet-wrap");
        if (!sheet || !wrap) return;
        const scale = Math.min(1, Math.max(0.1, (frame.clientWidth - 24) / sheet.offsetWidth));
        sheet.style.transform = `scale(${scale})`;
        wrap.style.width = `${sheet.offsetWidth * scale}px`;
        wrap.style.height = `${sheet.scrollHeight * scale}px`;
      };
      const resize = new ResizeObserver(scalePaper); resize.observe(frame);
      frame.addEventListener("load", async () => {
        const doc = frame.contentDocument, renderId = s.paperSerial;
        const current = () => active() && renderId === s.paperSerial && doc === frame.contentDocument
          && doc?.documentElement?.dataset.sheetRender === String(renderId);
        if (!current()) return;
        try {
          const logo = doc.querySelector("img[data-brand-logo]");
          if (!logo) throw new Error(LOGO_ERROR);
          const printLogo = new Image(); printLogo.src = printLogoUrl(s.logoData);
          await Promise.all([logo.decode(), printLogo.decode(), doc.fonts?.ready]);
          if (!current()) return;
          if (!logo.naturalWidth || !logo.naturalHeight) throw new Error(LOGO_ERROR);
          const layout = fitDocument(doc);
          dialog.querySelector("[data-sheet-pages]").textContent = `预计${layout.pages}页${layout.compact ? " · 紧凑排版" : ""}${layout.pages > 1 ? " · 内容完整续页" : ""}`;
          s.ready = true; scalePaper(); controls();
        } catch {
          if (!current()) return;
          logoRequest = null; s.ready = false; s.stale = true;
          message(LOGO_ERROR); controls();
        }
      });
      function renderPaper() {
        s.selected = effectiveSelection(s.model, s.selected);
        s.ready = false; s.paperSerial++; controls();
        dialog.querySelector("[data-sheet-pages]").textContent = "正在计算页数";
        frame.srcdoc = documentHtml(s.model, s.selected, { logoData: s.logoData, renderId: s.paperSerial });
      }
      function renderChoices() {
        const choices = dialog.querySelector("[data-sheet-choices]"); choices.replaceChildren();
        for (const section of s.model.sections) {
          if (!section.rows.length) continue;
          const group = document.createElement("fieldset"), legend = document.createElement("legend"); legend.textContent = section.label; group.append(legend);
          for (const row of section.rows) {
            const label = document.createElement("label"), input = document.createElement("input"), span = document.createElement("span");
            input.type = "checkbox"; input.checked = s.selected.has(row.id); input.dataset.sheetId = row.id;
            span.textContent = row.label; label.append(input, span); group.append(label);
            input.onchange = () => { input.checked ? s.selected.add(row.id) : s.selected.delete(row.id); renderPaper(); };
          }
          choices.append(group);
        }
      }
      async function refresh() {
        if (s.busy || !active()) return;
        s.busy = true; controls(); message("正在保存当前修改并准备确认单…");
        const request = ++s.serial;
        try {
          const context = hooks.context();
          if (context.jobId && !await hooks.save()) throw new Error("当前修改尚未保存，请重试保存后预览。草稿仍保留。");
          if (!active() || request !== s.serial) return;
          // A revision increment from our save is expected; an edit during it is not.
          if (context.editSerial !== hooks.context().editSerial) throw new Error("保存期间参数又发生修改，请刷新预览。");
          const saved = hooks.context(), token = fingerprint(saved);
          const model = await hooks.build({ ...saved, review: structuredClone(saved.review), materialCatalog: structuredClone(saved.materialCatalog) });
          if (!active() || request !== s.serial) return;
          const logoData = await loadLogo();
          if (!active() || request !== s.serial) return;
          if (fingerprint(hooks.context()) !== token) throw new Error("参数已更新，请刷新预览。");
          const ids = model.sections.flatMap(section => section.rows.map(row => row.id));
          for (const id of ids) if (!s.known.has(id)) s.selected.add(id);
          s.known = new Set(ids); s.selected = new Set([...s.selected].filter(id => s.known.has(id)));
          s.model = model; s.logoData = logoData; s.token = token; s.stale = false;
          renderChoices(); renderPaper(); message(model.local ? "本地数据；建议仅供核对。打印窗口中可选择另存为PDF。" : "已按当前保存数据生成。打印窗口中可选择另存为PDF。");
        } catch (error) {
          if (active()) { s.stale = true; message(error.message || "预览失败，请重试。"); }
        } finally { if (active()) { s.busy = false; controls(); } }
      }
      control("back").onclick = () => dialog.close();
      control("refresh").onclick = () => void refresh();
      control("print").onclick = async () => {
        if (!active() || !s.model || s.busy || !s.ready) return;
        if (fingerprint(hooks.context()) !== s.token) { s.stale = true; message("参数已更新，请刷新预览。"); controls(); return; }
        try {
          const doc = frame.contentDocument, renderId = s.paperSerial;
          if (doc?.fonts?.ready) await doc.fonts.ready;
          if (!active() || s.stale || !s.ready || doc !== frame.contentDocument || renderId !== s.paperSerial || fingerprint(hooks.context()) !== s.token) return;
          if (!doc.querySelector("img[data-brand-logo]")?.naturalWidth) {
            logoRequest = null; s.ready = false; s.stale = true; message(LOGO_ERROR); controls(); return;
          }
          frame.contentWindow.focus(); frame.contentWindow.print();
          // afterprint also fires for cancel; never persist or claim success.
        } catch { message("无法打开打印窗口，请允许浏览器打印后重试。"); }
      };
      s.timer = setInterval(() => {
        if (!active()) { dialog.close(); return; }
        if (s.model && !s.busy && !s.stale && fingerprint(hooks.context()) !== s.token) {
          s.stale = true; message("参数已更新，请刷新预览。"); controls();
        }
      }, 250);
      dialog.addEventListener("close", () => {
        clearInterval(s.timer); resize.disconnect(); s.serial++;
        if (view === s) view = null; dialog.remove();
        if (owner(hooks.context()) === s.owner) {
          const candidates = [...document.querySelectorAll('[data-action="preview-confirmation-sheet"]')].filter(el => el.getClientRects().length);
          const target = s.trigger?.isConnected ? s.trigger : candidates.find(el => el.closest('.compare-overlay')) || candidates[0];
          target?.focus({ preventScroll: true });
        }
      });
      if (window.matchMedia("(max-width: 760px)").matches) dialog.querySelector("details").open = false;
      dialog.showModal(); control("back").focus(); await refresh();
    }
    return { open, close };
  }
  globalThis.ParameterConfirmationSheet = { buildModel, documentHtml, tolerance, calculationRows, effectiveSelection, fitDocument, fingerprint, create };
})();
