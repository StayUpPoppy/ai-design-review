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
      @top-center { content: "弹簧参数确认单"; margin-top: 6mm; margin-bottom: 4mm; vertical-align: middle; color: #172033; font: 700 14pt "Microsoft YaHei", "Segoe UI", Arial, sans-serif; border-bottom: 1px solid #aab3bf; }
      @top-right { content: ""; width: 42mm; margin-top: 6mm; margin-bottom: 4mm; border-bottom: 1px solid #aab3bf; }
    }`;
  }
  const empty = value => value == null || typeof value === "string" && !value.trim();
  const text = value => empty(value) ? "待补充" : String(value);
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function tolerance(item = {}, load = false) {
    if (item.tolerance_input_draft) return String(item.tolerance_input_draft);
    const percent = item.load_tolerance_percent ?? item.force_tolerance_percent;
    const upper = item[load ? "load_tolerance_upper" : "tolerance_upper"], lower = item[load ? "load_tolerance_lower" : "tolerance_lower"];
    if (load && empty(upper) && empty(lower) && !empty(percent)) return `±${percent}%`;
    if (empty(upper) && empty(lower)) return "—";
    if (!empty(upper) && !empty(lower) && Number(upper) === -Number(lower) && Number(upper) >= 0) return `±${upper}`;
    const signed = value => empty(value) ? "未注明" : Number(value) > 0 ? `+${value}` : String(value);
    return `${signed(upper)} / ${signed(lower)}`;
  }
  // Customer-report policy is independent of internal confirmation and generation.
  const parameterFields = Object.freeze(['material', 'wire_diameter', 'outer_diameter', 'inner_diameter', 'mean_diameter', 'free_length', 'total_coils', 'active_coils', 'handedness']);
  const parameterNumbers = Object.freeze({ material: 1, wire_diameter: 2, outer_diameter: 3, inner_diameter: 4, mean_diameter: 5, free_length: 6, total_coils: 7, active_coils: 8, handedness: 10 });
  const defaultRequired = new Set(['material', 'wire_diameter', 'outer_diameter', 'free_length', 'total_coils', 'handedness']);
  function reportableIssue(issue) {
    if (issue?.customer_report === false) return false;
    if (issue?.customer_report === true) return true;
    // These describe internal formula/standardization availability, not a drawing error.
    if (['missing_context', 'standard_scope'].includes(issue?.category) || /^(FORMULA|GBT.*SCOPE)/.test(issue?.rule_id || '')) return false;
    return ['blocked', 'warning', 'needs_input'].includes(issue?.severity) &&
      (['geometry', 'load_condition', 'load_relation', 'design_risk'].includes(issue?.category) || !!issue?.customer_question);
  }
  function selectionRows(model) {
    return model.sections.flatMap(section => section.rows.flatMap(row => row.items || [row]));
  }
  function uniqueMessages(values) {
    const seen = new Set();
    return values.map(value => String(value || '').trim()).filter(value => {
      const key = value.replace(/\s+/g, '').replace(/[。；;，,！？!?]+$/, '');
      if (!key || seen.has(key)) return false;
      seen.add(key); return true;
    });
  }
  function issueSummary(items) {
    const reasons = uniqueMessages(items.flatMap(row => row.reasons || row.messages || []));
    const questions = uniqueMessages(items.flatMap(row => row.questions || []));
    if (reasons.length && !questions.length && !reasons.some(reason => /请|(?:需|建议)(?:由)?(?:客户)?(?:确认|核对|补充|明确|提供)/.test(reason))) {
      questions.push(`请确认${uniqueMessages(items.map(row => row.label)).join('、')}的正确内容。`);
    }
    return { reasons, questions, messages: uniqueMessages([...reasons, ...questions]) };
  }
  function buildModel(data) {
    const issues = (data.issues || []).filter(reportableIssue);
    const matches = (row, field) => row.field === field || row.field?.startsWith(`${field}.`) || field?.startsWith(`${row.field}.`);
    const hasIssue = row => issues.some(issue => (issue.fields || []).some(field => matches(row, field)));
    const items = [
      ...(data.parameters || []).filter(row => parameterFields.includes(row.field)).map(row => ({ ...row, kind: 'parameter', number: parameterNumbers[row.field], required: row.required ?? defaultRequired.has(row.field) })),
      ...(data.loads || []).map((row, index) => ({ ...row, kind: 'load', number: row.number ?? index + 1 })),
      ...(data.requirements || []).map((row, index) => ({ ...row, kind: 'technical', number: row.number ?? index + 1 })),
    ].map(row => ({ ...row, current: row.current || (row.kind === 'load' ? `高度 ${row.height}；力值 ${row.force}${row.tolerance && row.tolerance !== '—' ? `；公差 ${row.tolerance}` : ''}` : row.current), ref: rowRef(row), reasons: uniqueMessages(row.customer_issues || []), questions: [] }));
    const present = [];
    for (const row of items) {
      if (row.internal_only && !row.reasons.length) continue;
      if (row.kind === 'parameter') {
        if (row.provisional_default) {
          row.current = '原图未明确';
          if (row.required) row.reasons.push('原图未明确，请提供参数值及必要公差。');
          else if (!row.reasons.length && !hasIssue(row)) continue;
        } else if (empty(row.value)) {
          if (row.required) row.reasons.push('缺少必要参数，请补充数值及必要公差。');
          else if (!row.reasons.length && !hasIssue(row)) continue;
        }
      } else if (row.kind === 'technical' && empty(row.content)) row.reasons.push('技术要求正文为空，请明确要求。');
      present.push(row);
    }
    const parent = new Map(present.map(row => [row.id, row.id]));
    const find = id => parent.get(id) === id ? id : (parent.set(id, find(parent.get(id))), parent.get(id));
    const join = (a, b) => parent.set(find(b), find(a));
    for (const issue of issues) {
      const affected = present.filter(row => (issue.fields || []).some(field => matches(row, field)));
      if (!affected.length) continue;
      if (empty(issue.message) && empty(issue.customer_question)) continue;
      for (const row of affected) {
        if (!empty(issue.message)) row.reasons.push(issue.message);
        if (!empty(issue.customer_question)) row.questions.push(issue.customer_question);
        join(affected[0].id, row.id);
      }
    }
    const groups = new Map();
    for (const row of present) {
      row.reasons = uniqueMessages(row.reasons);
      row.questions = uniqueMessages(row.questions);
      row.messages = uniqueMessages([...row.reasons, ...row.questions]);
      if (!row.messages.length) continue;
      const root = find(row.id);
      if (!groups.has(root)) groups.set(root, []);
      groups.get(root).push(row);
    }
    const abnormal = new Set([...groups.values()].flat().map(row => row.id));
    const sections = [
      { id: 'parameters', label: '最终参数', rows: present.filter(row => row.kind === 'parameter' && !abnormal.has(row.id)) },
      { id: 'loads', label: '载荷测试点', rows: present.filter(row => row.kind === 'load' && !abnormal.has(row.id)) },
      { id: 'requirements', label: '技术要求', rows: present.filter(row => row.kind === 'technical' && !abnormal.has(row.id)) },
      { id: 'issues', label: '待客户澄清事项', rows: [...groups.values()].map(rows => ({
        id: rows[0].id, field: rows[0].field, label: rows.map(row => row.label).join(' / '), items: rows,
        ...issueSummary(rows),
      })) },
    ];
    return { ...data.info, notice: data.notice || '', sections };
  }
  function rowRef(row) {
    return row.kind === 'parameter' ? `参数${row.number}` : row.kind === 'load' ? `载荷点${row.label || row.number}` : `要求${row.number}`;
  }
  function effectiveSelection(model, selected) {
    const valid = new Set(selectionRows(model).map(row => row.id));
    return new Set(selected == null ? valid : [...selected].filter(id => valid.has(id)));
  }
  const PRINT_CSS = `
    @page { size: A4 portrait; margin: 24mm 12mm 12mm; }
    * { box-sizing: border-box; }
    html { color-scheme: light; }
    body { margin: 0; color: #172033; background: #e9edf3; font: 9.5pt/1.3 "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }
    .sheet-wrap { margin: 16px auto; }
    .sheet { width: 210mm; min-height: 297mm; padding: 6mm 12mm 12mm; background: white; transform-origin: top left; }
    .report-content { display: flow-root; }
    .brand-header { display: grid; grid-template-columns: 42mm minmax(0, 1fr) 42mm; align-items: center; height: 14mm; margin-bottom: 4mm; border-bottom: 1px solid #aab3bf; }
    .brand-header img { display: block; width: 38mm; height: auto; max-height: 12mm; object-fit: contain; }
    .brand-header h1 { margin: 0; text-align: center; white-space: nowrap; font-size: 14pt; font-weight: 700; line-height: 1.2; }
    h2 { margin: 3mm 0 1.5mm; font-size: 10.5pt; line-height: 1.3; break-after: avoid; }
    h3 { margin: 2mm 0 1mm; font-size: 9.5pt; break-after: avoid; }
    .info { display: grid; grid-template-columns: 1fr 1fr; gap: 1mm 6mm; margin-bottom: 2mm; font-size: 9pt; }
    .info > div { min-width: 0; overflow-wrap: anywhere; }
    .info .wide { grid-column: 1 / -1; }
    .report-table { width: 100%; border-collapse: collapse; table-layout: fixed; border: .5pt solid #ccd6e3; }
    .report-table th, .report-table td { padding: 1.1mm 2mm; text-align: left; vertical-align: middle; border-bottom: .4pt solid #dce3ec; overflow-wrap: anywhere; white-space: pre-wrap; }
    .report-table th { background: #f3f6fa; font-weight: 600; }
    .report-table thead { display: table-header-group; }
    .report-table tr { break-inside: avoid; }
    .report-table .report-number { text-align: center; }
    .full-lines { margin: 0; padding: 0; list-style: none; }
    .report-item { margin: 0; min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; break-inside: avoid; }
    .full-lines > .report-item + .report-item { margin-top: 1mm; }
    .long-item { break-inside: auto !important; }
    .issue-item { padding: 0; }
    .issue-ref { font-weight: 600; color: #8a4b08; }
    .issue-reply { display: flex; align-items: baseline; margin: .6mm 0 0 2mm; white-space: nowrap; break-before: avoid; break-inside: avoid; }
    .issue-reply-label { flex: none; }
    .issue-reply-line { flex: 1; min-width: 0; height: 1em; border-bottom: .5pt solid currentColor; }
    .number { font-variant-numeric: tabular-nums; }
    .confirmation { margin-top: 3mm; break-inside: avoid; }
    .confirmation p { margin: 0 0 1.5mm; }
    .opinion { min-height: 7mm; border-bottom: 1px solid #aab3bf; padding: 1mm 0; }
    .signatures { display: flex; justify-content: space-between; gap: 8mm; margin-top: 2mm; }
    .sheet.compact { font-size: 9pt; line-height: 1.25; }
    .compact h2 { margin-top: 2mm; margin-bottom: 1mm; }
    .compact .report-table th, .compact .report-table td { padding-block: .7mm; }
    .compact .info { row-gap: .6mm; margin-bottom: 1mm; }
    .compact .full-lines > .report-item + .report-item { margin-top: .5mm; }
    @media print {
      html, body { background: white; }
      .sheet-wrap { width: auto !important; height: auto !important; margin: 0; }
      .sheet { width: auto; min-height: 0; padding: 0; transform: none !important; }
      .brand-header { display: none; }
    }
  `;
  function documentHtml(model, selected, { logoData, renderId = '' } = {}) {
    if (!/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(logoData || '')) throw new Error(LOGO_ERROR);
    selected = effectiveSelection(model, selected);
    const chosen = id => (model.sections.find(section => section.id === id)?.rows || []).filter(row => selected.has(row.id));
    const attrs = row => `class="report-item${(row.content || '').length > 350 || JSON.stringify(row).length > 1200 ? ' long-item' : ''}" data-report-row="${escape(row.id)}"`;
    const valueUnit = row => `${escape(text(row.value))}${!empty(row.value) && row.unit ? ` ${escape(row.unit)}` : ''}`;
    const parameters = chosen('parameters'), loads = chosen('loads'), requirements = chosen('requirements');
    const questions = (model.sections.find(section => section.id === 'issues')?.rows || []).map(group => {
      const items = group.items.filter(row => selected.has(row.id));
      return { ...group, id: items[0]?.id, items, ...issueSummary(items) };
    }).filter(group => group.items.length);
    let sectionNumber = 0;
    const title = label => `<h2>${['一', '二', '三'][sectionNumber++]}、${label}</h2>`;
    let sections = '';
    if (parameters.length || loads.length) {
      let body = '';
      if (parameters.length) body += `<table class="report-table parameter-report-table"><colgroup><col style="width:8%"><col style="width:25%"><col style="width:31%"><col style="width:36%"></colgroup><thead><tr><th class="report-number">序号</th><th>参数</th><th>确认值</th><th>公差 / 说明</th></tr></thead><tbody>${parameters.map(row => `<tr ${attrs(row)}><td class="report-number">${row.number}</td><td>${escape(row.label)}</td><td class="number">${valueUnit(row)}</td><td>${escape(row.tolerance || '—')}</td></tr>`).join('')}</tbody></table>`;
      if (loads.length) body += `<h3>载荷测试点</h3><table class="report-table load-report-table"><thead><tr><th>测试点</th><th>测试高度</th><th>对应力值</th><th>力值公差</th></tr></thead><tbody>${loads.map(row => `<tr ${attrs(row)}><td>${escape(row.label)}</td><td class="number">${escape(row.height)}</td><td class="number">${escape(row.force)}</td><td>${escape(row.tolerance || '—')}</td></tr>`).join('')}</tbody></table>`;
      sections += `<section>${title('最终参数')}${body}</section>`;
    }
    if (requirements.length) sections += `<section>${title('技术要求')}<ol class="full-lines">${requirements.map(row => `<li ${attrs(row)}>${row.number}. ${escape(text(row.content))}</li>`).join('')}</ol></section>`;
    if (questions.length) sections += `<section>${title('待客户澄清事项')}<ol class="full-lines">${questions.map(group => {
      const refs = group.items.map(row => `${row.ref} | ${row.label}`).join('；');
      const current = group.items.map(row => `${row.label}：${row.current || (row.kind === 'technical' ? row.content : !empty(row.value) ? `${row.value}${row.unit ? ` ${row.unit}` : ''}${row.tolerance && row.tolerance !== '—' ? `，公差${row.tolerance}` : ''}` : '未注明')}`).join('；');
      const row = group.items[0];
      const sentence = value => /[。！？.!?]$/.test(value) ? value : `${value}。`;
      return `<li ${attrs({ ...row, id: group.id, content: `${current}${group.messages.join('；')}` })}><span class="issue-ref">${escape(refs)}</span>　当前：${escape(sentence(current))}${group.messages.map(message => escape(sentence(message))).join('')}<p class="issue-reply"><span class="issue-reply-label">客户回复：</span><span class="issue-reply-line" aria-hidden="true"></span></p></li>`;
    }).join('')}</ol></section>`;
    return `<!doctype html><html lang="zh-CN" data-sheet-render="${escape(renderId)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escape(model.drawingName || '弹簧')}-参数确认单</title><style>${PRINT_CSS}${printHeaderCss(logoData)}</style></head><body><div class="sheet-wrap"><main class="sheet"><header class="brand-header"><img data-brand-logo src="${escape(logoData)}" alt="IncoSpring"><h1>弹簧参数确认单</h1></header><div class="report-content"><div class="info"><div class="wide">图纸名称：${escape(model.drawingName || '未填写')}</div><div>图号：${escape(model.drawingNo || '未填写')}</div><div>规格代号：${escape(model.variant || '—')}</div><div>制单人：${escape(model.preparer || '—')}</div><div>日期：${escape(model.date)}</div>${model.local ? '<div>数据来源：本地数据</div>' : ''}</div>${sections || '<p>未选择明细项目。</p>'}<section class="confirmation"><p><strong>客户确认</strong>　${questions.length ? '请填写以上异常项目回复，并确认其余参数及技术要求。' : '请核对以上参数及技术要求，确认后签字或盖章。'}</p><div class="opinion">其他调整意见：</div><div class="signatures"><span>客户签字 / 盖章：________________</span><span>日期：________________</span></div></section></div></main></div></body></html>`;
  }
  function fitDocument(doc) {
    const sheet = doc.querySelector('.sheet'), content = doc.querySelector('.report-content');
    sheet.classList.remove('compact');
    const pageHeight = 261 * 96 / 25.4;
    if (content.offsetHeight > pageHeight + .5) sheet.classList.add('compact');
    const pages = Math.max(1, Math.ceil((content.offsetHeight - .5) / pageHeight));
    doc.documentElement.dataset.estimatedPages = String(pages);
    return { pages, compact: sheet.classList.contains('compact') };
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
      const s = { dialog, owner: owner(initial), trigger, selected: new Set(), choices: new Map(), model: null, busy: false, stale: false, serial: 0, paperSerial: 0, logoData: "", token: "" };
      view = s; document.body.append(dialog);
      const active = () => view === s && owner(hooks.context()) === s.owner;
      const message = value => { dialog.querySelector(".confirmation-sheet-message").textContent = value; };
      const control = name => dialog.querySelector(`[data-sheet-action="${name}"]`);
      const frame = dialog.querySelector("iframe");
      const controls = () => {
        control("refresh").disabled = s.busy;
        control("print").disabled = s.busy || s.stale || !s.model || !s.ready;
        dialog.querySelectorAll('input').forEach(input => {
          input.disabled = s.busy;
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
          for (const row of section.rows.flatMap(row => row.items || [row])) {
            const label = document.createElement("label"), input = document.createElement("input"), span = document.createElement("span");
            input.type = "checkbox"; input.checked = s.selected.has(row.id); input.dataset.sheetId = row.id;
            span.textContent = `${row.ref} · ${row.label}`; label.append(input, span); group.append(label);
            input.onchange = () => { s.choices.set(row.id, input.checked); input.checked ? s.selected.add(row.id) : s.selected.delete(row.id); renderPaper(); };
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
          const ids = selectionRows(model).map(row => row.id);
          for (const id of ids) if (!s.choices.has(id)) s.choices.set(id, true);
          s.selected = new Set(ids.filter(id => s.choices.get(id)));
          s.model = model; s.logoData = logoData; s.token = token; s.stale = false;
          renderChoices(); renderPaper(); message([model.local ? "本地数据。" : "已按当前保存数据生成。", model.notice, "打印窗口中可选择另存为PDF。"].filter(Boolean).join(" "));
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
  globalThis.ParameterConfirmationSheet = { buildModel, documentHtml, tolerance, effectiveSelection, fitDocument, fingerprint, create, parameterFields, parameterNumbers, reportableIssue, selectionRows };
})();
