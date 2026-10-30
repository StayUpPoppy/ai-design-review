/* Read-only SW text, provenance and advisory duplicate hints. No review writes. */
(() => {
  let options, scheduled = false, scope;
  const hosts = new Map(), roots = new WeakSet(), cache = new Map(), views = new Map();
  let localModels = new WeakMap();
  const html = () => `<details class="technical-output-preview" data-role="technical-output-preview" open>
    <summary>成图技术要求预览<span data-role="technical-output-count">（0条）</span></summary>
    <div class="technical-output-state"><small data-role="technical-output-status" role="status"></small><button type="button" class="secondary-action" data-role="technical-output-retry" hidden>重试核对</button></div>
    <div class="technical-output-scroll" tabindex="0" aria-label="成图技术要求正文"><ol data-role="technical-output-lines"></ol><p data-role="technical-output-empty">确认参数或技术要求后，将在此呈现成图内容。</p></div>
  </details>`;

  function refresh() {
    if (scheduled || !options) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      const currentScope = options.scope();
      if (scope !== currentScope) { scope = currentScope; cache.clear(); views.clear(); localModels = new WeakMap(); }
      for (const [host, record] of hosts) {
        if (!host.isConnected) { hosts.delete(host); continue; }
        host.hidden = record.scope !== currentScope;
        if (!host.hidden) render(record);
      }
    });
  }
  function localModel(record, context) {
    let model = localModels.get(record.review);
    if (model?.signature === context.signature) return model;
    try { model = { signature: context.signature, projection: options.build(record.review) }; }
    catch { model = { signature: context.signature, projection: { text: "", entries: [], ready: false }, error: true }; }
    localModels.set(record.review, model);
    return model;
  }
  function current(record, captured) {
    const now = options.context(record.review, record.messageId);
    return now.active && !now.dirty && now.scope === captured.scope && now.session === captured.session
      && now.revision === captured.revision && now.edit === captured.edit && now.dataSignature === captured.dataSignature;
  }
  function serverModel(record, context, model) {
    if (!context.active || !context.scope || !context.jobId || context.dirty || model.error || !(context.ready ?? model.projection.ready)) return null;
    const key = JSON.stringify([context.scope, context.jobId, context.revision]);
    record.cacheKey = key;
    if (cache.has(key)) return cache.get(key);
    const overlay = document.getElementById("compareOverlay");
    if (!record.host.getClientRects().length || overlay && !overlay.hidden && !overlay.contains(record.host)) return null;
    const entry = { status: "loading" };
    cache.set(key, entry);
    if (cache.size > 40) for (const [oldKey, value] of cache) { if (cache.size <= 32) break; if (value.status !== "loading") cache.delete(oldKey); }
    (async () => {
      try {
        const response = await options.request(`/api/reviews/${encodeURIComponent(context.jobId)}/generation-package`, { signal: AbortSignal.timeout(15000) });
        const payload = await response.json();
        if (!current(record, context)) { if (cache.get(key) === entry) cache.delete(key); return; }
        const text = payload.parameter_package?.solidworks_preview?.extraProperties?.["技术要求"];
        if (!response.ok || payload.review_id !== context.jobId || payload.review_revision !== context.revision || typeof text !== "string") throw new Error("preview unavailable");
        entry.status = "ready"; entry.text = text;
      } catch {
        if (!current(record, context)) { if (cache.get(key) === entry) cache.delete(key); return; }
        entry.status = "error";
      } finally { refresh(); }
    })();
    return entry;
  }
  function effectiveProjection(local, server) {
    if (server?.status !== "ready" || server.text === local.text) return local;
    // Server text is authoritative. Never guess provenance for an unmapped line.
    return { text: server.text, entries: server.text.split(/\r?\n/).filter(line => line.trim()).map((line, index) => {
      const body = line.replace(/^\d+\./, ""), matches = local.entries.filter(entry => entry.body === body);
      return matches.length === 1 ? { ...matches[0], id: `server-${index}`, display: line }
        : { id: `server-${index}`, body, display: line, automatic: false, fields: [], requirement_ids: [], load_point_ids: [] };
    }) };
  }
  function lineElements(projection, record) {
    return projection.entries.map((entry, index) => {
      const li = document.createElement("li"), linkable = entry.fields?.length || entry.requirement_ids?.length;
      const text = document.createElement(linkable ? "button" : "span");
      text.textContent = entry.display ?? `${index + 1}.${entry.body}`;
      if (linkable) {
        text.type = "button"; text.className = "technical-output-link";
        text.title = entry.automatic ? "定位对应参数" : "定位原图／人工要求";
        text.addEventListener("click", () => options.focus(entry, record.messageId));
      }
      li.append(text);
      if (entry.automatic) { const tag = document.createElement("small"); tag.textContent = "自动"; tag.className = "technical-output-auto"; li.append(tag); }
      return li;
    });
  }
  function duplicateHints(record, projection) {
    const matches = item => globalThis.SolidWorksExport.automaticMatches(projection, item, options.catalog()).length > 0;
    record.section.querySelectorAll('[data-kind="technical"][data-requirement-id]').forEach(row => {
      const ids = JSON.parse(row.dataset.requirementIds || "[]");
      const members = (record.review.technical_requirements || []).filter(item => ids.includes(String(item.requirement_id)) || item.requirement_id === row.dataset.requirementId);
      const hint = row.querySelector('[data-role="technical-automatic-duplicate"]');
      if (!hint) return;
      hint.hidden = !members.length || !members.every(matches);
      hint.textContent = hint.hidden ? "" : "已包含在自动项中，成图仅输出一次";
    });
    const form = record.section.querySelector('[data-kind="technical_requirement_create"]');
    const hint = form?.querySelector('[data-role="technical-automatic-add-hint"]');
    if (hint) {
      const content = form.querySelector('[data-role="new-technical-content"]').value.trim();
      const duplicate = Boolean(content) && matches({ type: form.querySelector('[data-role="new-technical-type"]').value, content });
      hint.hidden = !duplicate;
      hint.textContent = duplicate ? "已由参数自动生成；仍可添加原文记录，确认后成图仅输出一次。" : "";
    }
  }
  function render(record) {
    const context = options.context(record.review, record.messageId), model = localModel(record, context);
    const server = serverModel(record, context, model), projection = effectiveProjection(model.projection, server);
    const details = record.host.querySelector("details"), session = context.session;
    record.session = session;
    if (!views.has(session)) views.set(session, true);
    if (views.size > 64) views.delete(views.keys().next().value);
    details.open = views.get(session);
    const list = record.host.querySelector('[data-role="technical-output-lines"]');
    const signature = JSON.stringify(projection.entries);
    if (record.rendered !== signature) {
      const scroll = list.parentElement.scrollTop;
      list.replaceChildren(...lineElements(projection, record));
      list.parentElement.scrollTop = scroll;
      record.rendered = signature;
    }
    record.host.querySelector('[data-role="technical-output-count"]').textContent = `（${projection.entries.length}条）`;
    const empty = record.host.querySelector('[data-role="technical-output-empty"]');
    empty.hidden = projection.entries.length > 0;
    empty.textContent = model.error ? "预览暂不可用，请核对当前输入。" : "确认参数或技术要求后，将在此呈现成图内容。";
    const status = model.error ? "草稿预览 · 尚未完成服务端核对"
      : context.dirty ? `草稿预览 · ${context.saveFailed ? "保存失败" : context.saving ? "保存中…" : "尚未保存"}`
      : !context.jobId ? "本地草稿预览 · 仅包含已确认有效内容"
      : server?.status === "ready" ? "已与服务器核对 · 仅包含当前可输出内容"
      : server?.status === "loading" ? "当前预览 · 正在与服务器核对…"
      : server?.status === "error" ? "草稿预览 · 尚未完成服务端核对"
      : "当前预览 · 仍有内容待补充或确认";
    record.host.querySelector('[data-role="technical-output-status"]').textContent = status;
    record.host.querySelector('[data-role="technical-output-retry"]').hidden = server?.status !== "error";
    duplicateHints(record, projection);
  }
  function mount(root, review, messageId) {
    if (!options) return;
    if (!roots.has(root)) {
      roots.add(root);
      root.addEventListener("input", refresh); root.addEventListener("change", refresh);
    }
    root.querySelectorAll('[data-kind="technical_output_preview"]').forEach(host => {
      if (hosts.has(host)) return;
      host.innerHTML = html();
      const record = { host, section: host.closest(".technical-requirements-block"), review, messageId, scope: options.context(review, messageId).scope };
      hosts.set(host, record);
      host.querySelector("summary").addEventListener("click", () => { if (record.session) views.set(record.session, !host.querySelector("details").open); });
      host.querySelector("details").addEventListener("toggle", () => {
        if (!record.session) return;
        views.set(record.session, host.querySelector("details").open);
      });
      host.querySelector('[data-role="technical-output-retry"]').addEventListener("click", () => { cache.delete(record.cacheKey); refresh(); });
    });
    refresh();
  }
  globalThis.TechnicalRequirementPreview = { configure: value => { options = value; }, mount, refresh };
})();
