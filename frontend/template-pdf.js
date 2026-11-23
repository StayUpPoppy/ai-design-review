/* Fixed-template PDF rendering and history, independent of the SW queue. */
globalThis.TemplatePdf = (() => {
  let options, entry = null, serial = 0, busy = false, requestKey = null;
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const context = () => options?.context() || {};
  const scope = c => `${c.scope || ""}|${c.reviewId || ""}|${c.navigation || 0}`;
  const key = c => `${scope(c)}|${c.edit || 0}|${c.revision || 0}`;
  const same = captured => scope(context()) === scope(captured);
  const refresh = () => {
    document.querySelectorAll('.template-pdf-panel').forEach(host => {
      const active = host.contains(document.activeElement) ? document.activeElement.dataset : null;
      const wrapper = document.createElement('div'); wrapper.innerHTML = html();
      const replacement = wrapper.firstElementChild;
      host.replaceWith(replacement);
      if (active?.templatePdfAction) [...replacement.querySelectorAll('[data-template-pdf-action]')]
        .find(button => button.dataset.templatePdfAction === active.templatePdfAction && button.dataset.pdfId === active.pdfId)?.focus({preventScroll:true});
    });
  };
  const errorMessage = (payload, fallback) => payload?.detail?.message || (typeof payload?.detail === "string" ? payload.detail : fallback);

  function configure(settings) { options ||= settings; }

  async function load(force = false) {
    const captured = context();
    if (!captured.reviewId) return;
    if (!force && entry?.key === key(captured)) return;
    const token = ++serial;
    const previous = entry?.scope === scope(captured) ? entry : {};
    entry = {...previous, key:key(captured), scope:scope(captured), loading:true, error:""};
    try {
      const base = `/api/reviews/${encodeURIComponent(captured.reviewId)}`;
      const [readyResponse, historyResponse] = await Promise.all([
        options.request(`${base}/template-pdf-readiness`), options.request(`${base}/template-pdfs`),
      ]);
      const ready = await readyResponse.json(), history = await historyResponse.json();
      if (!same(captured) || serial !== token || key(context()) !== key(captured)) return;
      if (!readyResponse.ok) throw new Error(errorMessage(ready,"无法读取 PDF 出图状态，请重试。"));
      if (ready.review_id !== captured.reviewId || historyResponse.ok && history.review_id !== captured.reviewId) throw new Error("PDF 历史与当前订单不一致，请刷新。 ");
      if (ready.review_revision !== captured.revision) throw new Error("审图版本已更新，请刷新订单后重新出图。");
      entry = {key:key(captured),scope:scope(captured),ready,history:historyResponse.ok ? history.template_pdfs : [],
        error:historyResponse.ok ? "" : errorMessage(history,"PDF 历史暂时无法读取，请重试。"),loading:false};
    } catch (error) {
      if (same(captured) && serial === token) entry = {...entry,ready:null,loading:false,error:error.message};
    } finally {
      if (same(captured) && serial === token) refresh();
    }
  }

  function html() {
    const c = context();
    if (!c.reviewId) return '<section class="template-pdf-panel"><h3>模板 PDF 出图</h3><p>保存为服务器审图记录后，可生成模板 PDF。</p></section>';
    if ((!entry || entry.key !== key(c)) && !busy) queueMicrotask(() => {
      const overlay = document.getElementById('compareOverlay');
      if ([...document.querySelectorAll('.template-pdf-panel')].some(host => host.getClientRects().length && (!overlay || overlay.hidden || overlay.contains(host)))) void load();
    });
    const current = entry?.scope === scope(c) ? entry : null;
    const ready = current?.ready?.readiness, canCreate = ready && ["ready","ready_with_warnings"].includes(ready.status) && entry.key === key(c) && !c.readOnly;
    const issues = [ ...(ready?.missing_fields || []), ...(ready?.pending_fields || []), ...(ready?.blocking_reasonableness || []) ];
    const reasons = [...new Set(issues.map(item => `${item.label ? item.label+"：" : ""}${item.reason || item.message || "请核对输入"}`))];
    return `<section class="template-pdf-panel" aria-label="模板 PDF 出图" aria-busy="${busy}">
      <div class="template-pdf-heading"><h3>模板 PDF 出图</h3><span>固定 A4 竖版 · 模板字体</span></div>
      <p class="template-pdf-note">使用当前已确认参数和成图技术要求；生图人姓名可选，填写后显示在设计栏。</p>
      <p class="template-pdf-status" role="status">${escape(busy ? "正在生成 PDF…" : current?.loading ? "正在检查 PDF 出图条件…" : ready?.summary || "正在读取出图状态…")}</p>
      ${reasons.length ? `<ul class="template-pdf-issues">${reasons.map(reason=>`<li>${escape(reason)}</li>`).join("")}</ul>` : ""}
      ${ready?.warnings?.length ? `<ul class="template-pdf-warnings">${ready.warnings.map(item=>`<li>${escape(item.reason || item.message)}</li>`).join("")}</ul>` : ""}
      ${current?.error ? `<p class="template-pdf-error" role="alert">${escape(current.error)}</p>` : ""}
      <div class="template-pdf-actions"><button type="button" class="primary-action" data-template-pdf-action="create" ${canCreate && !busy && !current?.loading ? "" : "disabled"}>${busy ? "正在生成…" : "模板 PDF 出图"}</button>
      <button type="button" data-template-pdf-action="reload" ${busy || current?.loading ? "disabled" : ""}>刷新 PDF 状态</button></div>
      <details class="template-pdf-history" ${current?.history?.length ? "open" : ""}><summary>模板 PDF 历史（${current?.history?.length || 0}）</summary>
      ${current?.history?.length ? `<ul>${current.history.map(item=>`<li><div><strong>${escape(item.filename)}</strong><span>${escape(new Date(item.created_at).toLocaleString("zh-CN"))} · 来源修订 r${escape(item.review_revision)}</span></div><div class="template-pdf-file-actions"><button type="button" data-template-pdf-action="preview" data-pdf-id="${escape(item.pdf_id)}">预览 PDF</button><button type="button" data-template-pdf-action="download" data-pdf-id="${escape(item.pdf_id)}">下载 PDF</button></div></li>`).join("")}</ul>` : '<p class="template-pdf-empty">暂无模板 PDF；生成后的文件会保留在当前订单中。</p>'}
      </details></section>`;
  }

  async function create() {
    const captured = context();
    if (busy || !captured.reviewId || captured.readOnly) return;
    busy = true; refresh();
    try {
      if (!await options.save()) throw new Error("当前修改尚未保存，请保存后重新出图。");
      if (!same(captured)) return;
      if (options.hasPending()) throw new Error("仍有尚未保存的修改，请保存后重新出图。");
      const saved = context();
      await load(true);
      if (!same(captured)) return;
      if (key(context()) !== key(saved)) throw new Error("保存期间参数已变化，请核对后重新出图。");
      const ready = entry?.ready;
      if (!["ready","ready_with_warnings"].includes(ready?.readiness?.status)) throw new Error(ready?.readiness?.summary || entry?.error || "当前数据尚未满足 PDF 出图条件。");
      const signature = `${scope(captured)}|${saved.revision}`;
      if (requestKey?.signature !== signature) requestKey = {signature,value:`pdf-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`};
      const response = await options.request(`/api/reviews/${encodeURIComponent(captured.reviewId)}/template-pdfs`, {
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_review_revision:saved.revision,idempotency_key:requestKey.value}),
      });
      const payload = await response.json();
      if (!same(captured)) return;
      if (!response.ok) throw new Error(errorMessage(payload,"模板 PDF 生成失败，请重试。"));
      requestKey = null;
      await load(true);
    } catch (error) {
      if (same(captured)) entry = {...entry,key:key(context()),scope:scope(captured),loading:false,error:error.message};
    } finally { if (same(captured)) { busy = false; refresh(); } }
  }

  async function openFile(id, preview) {
    const captured = context();
    const item = entry?.history?.find(row=>row.pdf_id === id);
    if (!item) return;
    try {
      const response = await options.request(preview ? item.inline_url || `${item.url}?inline=true` : item.url);
      if (!response.ok) throw new Error("PDF 文件无法读取，请刷新历史后重试。");
      const blob = await response.blob();
      if (!same(captured)) return;
      const url = URL.createObjectURL(blob);
      if (!preview) {
        const a = document.createElement("a");a.href=url;a.download=item.filename;document.body.append(a);a.click();a.remove();
        setTimeout(()=>URL.revokeObjectURL(url),30000);return;
      }
      document.querySelector(".template-pdf-dialog")?.close();
      const dialog = document.createElement("dialog");dialog.className="generation-pdf-dialog template-pdf-dialog";
      dialog.innerHTML=`<div class="generation-pdf-shell"><header><div><strong>模板 PDF 预览</strong><small>来源修订 r${escape(item.review_revision)} · ${escape(item.filename)}</small></div><button type="button" aria-label="关闭模板 PDF 预览">关闭</button></header><iframe title="模板 PDF 图纸预览"></iframe></div>`;
      dialog.querySelector("iframe").src=`${url}#view=FitH`;
      dialog.querySelector("button").addEventListener("click",()=>dialog.close());
      dialog.addEventListener("keydown",event=>{if(event.key==='Escape') event.stopPropagation();});
      dialog.addEventListener("close",()=>{URL.revokeObjectURL(url);dialog.remove();},{once:true});
      document.body.append(dialog);dialog.showModal();dialog.querySelector("button").focus();
    } catch(error) { if (same(captured)) {entry={...entry,error:error.message};refresh();} }
  }

  document.addEventListener("click",event=>{
    const button=event.target.closest?.("[data-template-pdf-action]");if (!button || button.disabled) return;
    if (button.dataset.templatePdfAction==="create") void create();
    if (button.dataset.templatePdfAction==="reload") void load(true);
    if (["preview","download"].includes(button.dataset.templatePdfAction)) void openFile(button.dataset.pdfId,button.dataset.templatePdfAction==="preview");
  });
  function reset() {++serial;entry=null;requestKey=null;busy=false;document.querySelector(".template-pdf-dialog")?.close();}
  return {configure,html,load,reset};
})();
