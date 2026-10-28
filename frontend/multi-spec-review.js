/* Sources hold read-only specifications; only independent children are editable. */
(function (root) {
  "use strict";
  function create({ request, scope, storageScope = scope, save, openReview, assetUrl, changed, viewed, deleted, renderRow }) {
    const groups = new Map(), preferences = new Map(), pending = []; let view = null, serial = 0, currentScope = scope(), activeLoads = 0;
    function reset() { serial++; view?.dialog.close(); view = null; groups.clear(); pending.length = 0; currentScope = scope(); }
    function checkScope() { if (currentScope !== scope()) reset(); }
    function preference(id, value) {
      const key = `aiDesignReview:multi-spec-expanded:v1:${storageScope()}:${id}`;
      if (value) { preferences.set(key, value); try { localStorage.setItem(key, JSON.stringify(value)); } catch {} return value; }
      try { const saved = JSON.parse(localStorage.getItem(key) || "null"); if (saved && typeof saved.expanded === "boolean") preferences.set(key, saved); } catch {}
      return preferences.get(key);
    }
    function groupFor(id) {
      if (!groups.has(id)) groups.set(id, { expanded: preference(id)?.expanded || false, request: 0 });
      return groups.get(id);
    }
    function drain() {
      while (activeLoads < 2 && pending.length) {
        const task = pending.shift(); activeLoads++;
        void task().finally(() => { activeLoads--; drain(); });
      }
    }
    function load(id, force = false) {
      checkScope(); const captured = scope(), group = groupFor(id);
      if (group.loading) return force ? group.loading.catch(() => {}).then(() => load(id, true)) : group.loading;
      const n = ++group.request;
      const loading = (async () => {
        const response = await request(`/api/reviews/${encodeURIComponent(id)}/variants`), value = await response.json();
        if (captured !== scope() || deleted(id) || group !== groups.get(id) || n !== group.request) throw new Error("订单或登录状态已变化，请重新打开。");
        if (!response.ok) throw new Error(value.detail || "无法读取规格清单");
        if (!Array.isArray(value.variants)) throw new Error("规格清单返回无效。");
        Object.assign(group, { value, error: "" }); return value;
      })();
      group.loading = loading;
      void loading.finally(() => { if (group.loading === loading) group.loading = null; }).catch(() => {});
      return loading;
    }
    function items() { checkScope(); return [...groups.values()].flatMap(g => g.value?.variants.map(v => v.review).filter(Boolean) || []); }
    function find(id) { checkScope(); for (const g of groups.values()) { const item = g.value?.variants.find(v => v.review?.job_id === id)?.review; if (item) return item; } }
    function remove(ids) {
      ids.forEach(id => groups.delete(id));
      for (const g of groups.values()) if (g.value) {
        let removed = false;
        for (const v of g.value.variants) if (ids.includes(v.review?.job_id)) { v.review = null; v.creation_status = "deleted"; removed = true; }
        if (removed) g.request++;
        g.value.created_count = g.value.variants.filter(v => v.review).length;
      }
      if (view && ids.includes(view.id)) { view.dialog.close(); view = null; serial++; }
      else view?.render?.();
    }
    function decorate(item, row) {
      checkScope(); if (item.record_kind !== "source") return;
      const group = groupFor(item.job_id), round = `attempt:${item.recognition_attempt_count ?? 1}`;
      group.item = item;
      if (item.creation_mode === "auto" && (!item.recognition_status || item.recognition_status === "completed") && group.round !== round) {
        const saved = preference(item.job_id);
        group.expanded = saved?.round === round ? saved.expanded : true;
        group.round = round; preference(item.job_id, { expanded: group.expanded, round });
      }
      let toggle = row.querySelector('[data-role="expand-specifications"]');
      if (!toggle) {
        toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "history-variants-toggle"; toggle.dataset.role = "expand-specifications";
        toggle.addEventListener("click", () => {
          group.expanded = !group.expanded;
          preference(item.job_id, { expanded: group.expanded, round: group.round || `attempt:${group.item.recognition_attempt_count ?? 1}` });
          if (group.expanded) { group.failedSignature = null; group.error = ""; }
          changed();
        }); row.append(toggle);
      }
      const signature = `${item.revision}:${item.created_count}`;
      if (group.expanded && group.loadedSignature !== signature && group.failedSignature !== signature && !group.pending) {
        group.pending = true; const captured = scope();
        pending.push(async () => {
          try {
            if (captured !== scope() || group !== groups.get(item.job_id) || deleted(item.job_id)) return;
            await load(item.job_id); group.loadedSignature = signature;
          } catch (error) { group.error = error.message; group.failedSignature = signature; }
          finally { group.pending = false; if (captured === scope() && group === groups.get(item.job_id)) changed(); }
        }); drain();
      }
      toggle.textContent = `${group?.expanded ? "收起" : "展开"}规格（${group?.value?.created_count ?? item.created_count ?? 0}／${item.variant_count ?? group?.value?.variants.length ?? 0}）`;
      toggle.setAttribute("aria-expanded", String(!!group?.expanded));
      let list = row.querySelector(".history-source-children");
      if (!list) { list = document.createElement("div"); list.className = "history-source-children"; row.append(list); }
      list.hidden = !group?.expanded;
      if (!group.expanded) return;
      if (group.error) {
        list.replaceChildren(); const retry = document.createElement("button"); retry.type = "button";
        retry.textContent = "规格加载失败，点击重试"; retry.title = group.error;
        retry.onclick = () => { group.failedSignature = null; group.error = ""; changed(); }; list.append(retry); return;
      }
      if (!group.value) { list.textContent = "正在读取规格…"; return; }
      if (list.firstChild?.nodeType === 3) list.replaceChildren();
      list.querySelectorAll(":scope > button").forEach(button => button.remove());
      list.querySelector(".history-variants-empty")?.remove();
      const old = new Map([...list.children].map(r => [r.dataset.historyJobId, r]));
      group.value.variants.filter(v => v.review && !deleted(v.review.job_id)).forEach((v, index) => {
        const child = renderRow(v.review, old.get(v.review.job_id));
        if (list.children[index] !== child) list.insertBefore(child, list.children[index] || null); old.delete(v.review.job_id);
      }); old.forEach(r => r.remove());
      if (!list.children.length) { const p = document.createElement("p"); p.className = "history-variants-empty"; p.textContent = "暂无子审图记录，可打开来源核对规格。"; list.append(p); }
    }
    async function open(id, round) {
      checkScope(); const n = ++serial, captured = scope(), value = await load(id);
      if (n !== serial || captured !== scope()) return false;
      view?.dialog.close();
      const dialog = document.createElement("dialog"); dialog.className = "specification-workbench"; dialog.setAttribute("aria-label", "规格核对");
      dialog.innerHTML = `<header><div><h2>规格核对</h2><p class="specification-subtitle"></p></div><button type="button" data-action="close">返回审图</button></header>
        <div class="specification-body"><section class="specification-evidence" aria-label="原图区域"><label>原图页码 <select aria-label="原图页码"></select></label><div class="specification-image"><img alt="多规格来源图纸"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><rect fill="rgba(36,82,203,.08)" stroke="#2452cb" stroke-width=".25"/></svg></div><p data-role="region-status"></p></section>
        <section class="specification-checklist" aria-label="只读规格清单"><div class="specification-actions"><button type="button" data-action="fill-missing" hidden>补建未创建规格</button><button type="button" data-action="refresh">刷新清单</button></div><div class="specification-table-scroll"><table><thead><tr><th>规格／代号</th><th>主要尺寸（mm）</th><th>圈数</th><th>问题／操作</th></tr></thead><tbody></tbody></table></div><p class="specification-message" role="status"></p><footer><span data-role="selection-count"></span></footer></section></div>`;
      document.body.append(dialog);
      const state = { id, dialog, value, busy: false, key: null, keyIds: "" }; view = state;
      const active = () => view === state && captured === scope() && !deleted(id);
      const message = text => { dialog.querySelector(".specification-message").textContent = text; };
      const controls = () => {
        const missing = state.value.variants.filter(v => !v.review && v.creation_status !== "deleted");
        const fill = dialog.querySelector('[data-action="fill-missing"]');
        fill.hidden = state.value.creation_mode === "auto" || !missing.length;
        fill.textContent = `补建未创建规格（${missing.length}）`;
        dialog.querySelector('[data-role="selection-count"]').textContent = `共${state.value.variants.length}种 · 已创建${state.value.created_count}种`;
        dialog.querySelectorAll("button,select").forEach(el => el.disabled = state.busy);
      };
      const showRegion = candidate => {
        const page = (state.value.pages || []).find(p => p.page === candidate.page) || state.value.pages?.[0];
        const url = page?.image_url || state.value.image_url, img = dialog.querySelector("img"); img.hidden = !url;
        if (url) img.src = assetUrl(url); else img.removeAttribute("src");
        dialog.querySelector("select").value = String(page?.page || candidate.page);
        const svg = dialog.querySelector("svg"), region = candidate.region; svg.toggleAttribute("hidden", !url || !region || page?.page !== candidate.page);
        if (!svg.hasAttribute("hidden")) for (const key of ["x", "y", "width", "height"]) svg.querySelector("rect").setAttribute(key, region[key] * 100);
        dialog.querySelector('[data-role="region-status"]').textContent = region ? `第${candidate.page}页 · 规格${candidate.order}原图区域` : "原图区域待定位";
      };
      function render() {
        const body = dialog.querySelector("tbody"); body.replaceChildren();
        dialog.querySelector(".specification-subtitle").textContent = `${state.value.drawing_summary?.drawing_name || "压缩弹簧"} · 清单只读；打开对应规格后核对参数与生图`;
        const select = dialog.querySelector("select"); select.replaceChildren();
        for (const p of state.value.pages || []) { const o = document.createElement("option"); o.value = p.page; o.textContent = `第${p.page}页`; select.append(o); }
        for (const v of state.value.variants) {
          const tr = document.createElement("tr"), valueOf = key => { const p = v.parameters?.[key]; return p && typeof p === "object" ? p.value ?? "—" : p ?? "—"; };
          tr.innerHTML = '<td><button type="button" class="specification-locate"></button></td><td></td><td></td><td class="specification-problems"></td>';
          const locate = tr.querySelector("button"); locate.textContent = `${v.order}. ${v.code || `规格${v.order}`}`; locate.title = v.source_context?.row_text || "定位原图区域";
          locate.addEventListener("click", () => { showRegion(v); body.querySelectorAll("tr").forEach(row => row.classList.toggle("is-located", row === tr)); });
          const diameter = [["mean_diameter", "Dm"], ["inner_diameter", "内径"], ["outer_diameter", "外径"]].find(([key]) => valueOf(key) !== "—") || ["mean_diameter", "Dm"];
          tr.cells[1].textContent = `d ${valueOf("wire_diameter")} · ${diameter[1]} ${valueOf(diameter[0])} · H₀ ${valueOf("free_length")}`;
          tr.cells[2].textContent = `总 ${valueOf("total_coils")} · 有效 ${valueOf("active_coils")}`;
          tr.cells[3].textContent = (v.issues || []).join("；") || "待人工核对";
          if (v.review) { const button = document.createElement("button"); button.type = "button"; button.textContent = "打开审图"; button.addEventListener("click", () => { dialog.close(); void openReview(v.review.job_id); }); tr.cells[3].append(button); }
          else if (v.creation_status === "deleted") {
            tr.cells[3].textContent = "已删除"; const button = document.createElement("button"); button.type = "button"; button.textContent = "重新创建审图";
            button.onclick = () => void createRecords([v.variant_id]); tr.cells[3].append(button);
          }
          tr.addEventListener("click", event => { if (!event.target.closest("input,button")) { showRegion(v); body.querySelectorAll("tr").forEach(row => row.classList.toggle("is-located", row === tr)); } });
          body.append(tr);
        } showRegion(state.value.variants[0]); controls();
      }
      dialog.querySelector('[data-action="close"]').onclick = () => { if (!state.busy) dialog.close(); };
      dialog.addEventListener("cancel", e => { if (state.busy) e.preventDefault(); });
      dialog.addEventListener("close", () => { dialog.remove(); if (view === state) view = null; });
      dialog.querySelector("select").onchange = e => { const p = state.value.pages.find(p => String(p.page) === e.target.value); dialog.querySelector("img").src = assetUrl(p.image_url); dialog.querySelector("svg").setAttribute("hidden", ""); };
      dialog.querySelector('[data-action="refresh"]').onclick = async () => {
        state.busy = true; controls();
        try { const value = await load(id, true); if (active()) { state.value = value; render(); message("清单已刷新。"); changed(); } }
        catch (error) { if (active()) message(error.message); }
        finally { if (active()) { state.busy = false; controls(); } }
      };
      async function createRecords(ids) {
        if (state.busy || !ids.length) return; state.busy = true; controls(); message("正在保存当前修改…");
        try {
          if (!await save()) throw new Error("当前修改未保存，未创建规格记录。请先重试保存。"); if (!active()) return;
          const signature = JSON.stringify(ids.slice().sort());
          if (!state.key || state.keyIds !== signature) { state.key = globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `variants-${Date.now()}-${Math.random().toString(16).slice(2)}`; state.keyIds = signature; }
          message("正在创建独立审图记录…");
          const response = await request(`/api/reviews/${encodeURIComponent(id)}/variants/create-reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ variant_ids: ids, expected_source_revision: state.value.source_revision, idempotency_key: state.key }) });
          const result = await response.json(); if (!active()) return;
          if (!response.ok) throw new Error(result.detail || "创建失败，请刷新后重试。");
          const value = await load(id, true); if (!active()) return; state.value = value; state.key = null; render(); changed();
          message(`已创建或找到${result.reviews.length}条独立审图记录。点击“打开审图”继续核对。`);
        } catch (error) { if (active()) message(`${error.message} 网络结果不明时可重试本次操作，不会重复建单。`); }
        finally { if (active()) { state.busy = false; controls(); } }
      }
      dialog.querySelector('[data-action="fill-missing"]').onclick = () => void createRecords(state.value.variants.filter(v => !v.review && v.creation_status !== "deleted").map(v => v.variant_id));
      state.render = render;
      render(); dialog.showModal(); viewed(id, round); return true;
    }
    return { open, load, decorate, items, find, remove, reset };
  }
  root.MultiSpecReview = { create };
})(globalThis);
