/* Sources hold read-only specifications; only independent children are editable. */
(function (root) {
  "use strict";
  function create({ request, scope, save, openReview, assetUrl, changed, viewed, deleted, renderRow }) {
    const groups = new Map(); let view = null, serial = 0, currentScope = scope();
    function reset() { serial++; view?.dialog.close(); view = null; groups.clear(); currentScope = scope(); }
    function checkScope() { if (currentScope !== scope()) reset(); }
    async function load(id) {
      checkScope(); const captured = scope(), response = await request(`/api/reviews/${encodeURIComponent(id)}/variants`), value = await response.json();
      if (captured !== scope() || deleted(id)) throw new Error("订单或登录状态已变化，请重新打开。");
      if (!response.ok) throw new Error(value.detail || "无法读取规格清单");
      if (!Array.isArray(value.variants)) throw new Error("规格清单返回无效。");
      const group = groups.get(id) || { expanded: false }; Object.assign(group, { value }); groups.set(id, group); return value;
    }
    function items() { checkScope(); return [...groups.values()].flatMap(g => g.value?.variants.map(v => v.review).filter(Boolean) || []); }
    function find(id) { checkScope(); for (const g of groups.values()) { const item = g.value?.variants.find(v => v.review?.job_id === id)?.review; if (item) return item; } }
    function remove(ids) {
      ids.forEach(id => groups.delete(id));
      for (const g of groups.values()) if (g.value) {
        for (const v of g.value.variants) if (ids.includes(v.review?.job_id)) v.review = null;
        g.value.created_count = g.value.variants.filter(v => v.review).length;
      }
      if (view && ids.includes(view.id)) { view.dialog.close(); view = null; serial++; }
    }
    function decorate(item, row) {
      checkScope(); if (item.record_kind !== "source") return;
      let toggle = row.querySelector('[data-role="expand-specifications"]');
      if (!toggle) {
        toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "history-variants-toggle"; toggle.dataset.role = "expand-specifications";
        toggle.addEventListener("click", async () => {
          const group = groups.get(item.job_id) || { expanded: false }; groups.set(item.job_id, group); group.expanded = !group.expanded; toggle.disabled = true;
          try { if (group.expanded) await load(item.job_id); changed(); }
          catch (error) { toggle.title = error.message; group.expanded = false; changed(); }
          finally { toggle.disabled = false; }
        }); row.append(toggle);
      }
      const group = groups.get(item.job_id);
      toggle.textContent = `${group?.expanded ? "收起" : "展开"}规格（${group?.value?.created_count ?? item.created_count ?? 0}／${item.variant_count ?? group?.value?.variants.length ?? 0}）`;
      toggle.setAttribute("aria-expanded", String(!!group?.expanded));
      let list = row.querySelector(".history-source-children");
      if (!list) { list = document.createElement("div"); list.className = "history-source-children"; row.append(list); }
      list.hidden = !group?.expanded;
      if (!group?.expanded || !group.value) return;
      list.querySelector(".history-variants-empty")?.remove();
      const old = new Map([...list.children].map(r => [r.dataset.historyJobId, r]));
      group.value.variants.filter(v => v.review && !deleted(v.review.job_id)).forEach((v, index) => {
        const child = renderRow(v.review, old.get(v.review.job_id));
        if (list.children[index] !== child) list.insertBefore(child, list.children[index] || null); old.delete(v.review.job_id);
      }); old.forEach(r => r.remove());
      if (!list.children.length) { const p = document.createElement("p"); p.className = "history-variants-empty"; p.textContent = "尚未创建审图记录，点击来源核对规格。"; list.append(p); }
    }
    async function open(id, round) {
      checkScope(); const n = ++serial, captured = scope(), value = await load(id);
      if (n !== serial || captured !== scope()) return false;
      view?.dialog.close();
      const dialog = document.createElement("dialog"); dialog.className = "specification-workbench"; dialog.setAttribute("aria-label", "规格核对");
      dialog.innerHTML = `<header><div><h2>规格核对</h2><p class="specification-subtitle"></p></div><button type="button" data-action="close">返回审图</button></header>
        <div class="specification-body"><section class="specification-evidence" aria-label="原图区域"><label>原图页码 <select aria-label="原图页码"></select></label><div class="specification-image"><img alt="多规格来源图纸"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><rect fill="rgba(36,82,203,.08)" stroke="#2452cb" stroke-width=".25"/></svg></div><p data-role="region-status"></p></section>
        <section class="specification-checklist" aria-label="只读规格清单"><div class="specification-actions"><button type="button" data-action="select">全选未创建规格</button><button type="button" data-action="refresh">刷新清单</button></div><div class="specification-table-scroll"><table><thead><tr><th>选择</th><th>规格／代号</th><th>主要尺寸（mm）</th><th>圈数</th><th>问题／操作</th></tr></thead><tbody></tbody></table></div><p class="specification-message" role="status"></p><footer><span data-role="selection-count"></span><button type="button" data-action="create">创建所选规格的审图记录（0）</button></footer></section></div>`;
      document.body.append(dialog);
      const state = { id, dialog, value, selected: new Set(), busy: false, key: null, keyIds: "" }; view = state;
      const active = () => view === state && captured === scope() && !deleted(id);
      const message = text => { dialog.querySelector(".specification-message").textContent = text; };
      const controls = () => {
        const count = state.selected.size;
        dialog.querySelector('[data-action="create"]').textContent = `创建所选规格的审图记录（${count}）`;
        dialog.querySelector('[data-role="selection-count"]').textContent = `共${state.value.variants.length}种 · 已创建${state.value.created_count}种`;
        dialog.querySelectorAll("button,input,select").forEach(el => el.disabled = state.busy || (el.dataset.action === "create" && !count) || el.dataset.created === "true");
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
        dialog.querySelector(".specification-subtitle").textContent = `${state.value.drawing_summary?.drawing_name || "压缩弹簧"} · 选择后分别审图和生图，清单只读`;
        const select = dialog.querySelector("select"); select.replaceChildren();
        for (const p of state.value.pages || []) { const o = document.createElement("option"); o.value = p.page; o.textContent = `第${p.page}页`; select.append(o); }
        for (const v of state.value.variants) {
          const tr = document.createElement("tr"), valueOf = key => { const p = v.parameters?.[key]; return p && typeof p === "object" ? p.value ?? "—" : p ?? "—"; };
          tr.innerHTML = '<td><input type="checkbox"></td><td><button type="button" class="specification-locate"></button></td><td></td><td></td><td class="specification-problems"></td>';
          const input = tr.querySelector("input"); input.dataset.created = String(!!v.review); input.checked = state.selected.has(v.variant_id); input.setAttribute("aria-label", `选择规格${v.order} ${v.code || ""}`);
          input.addEventListener("change", () => { input.checked ? state.selected.add(v.variant_id) : state.selected.delete(v.variant_id); state.key = null; controls(); });
          const locate = tr.querySelector("button"); locate.textContent = `${v.order}. ${v.code || `规格${v.order}`}`; locate.title = v.source_context?.row_text || "定位原图区域";
          locate.addEventListener("click", () => { showRegion(v); body.querySelectorAll("tr").forEach(row => row.classList.toggle("is-located", row === tr)); });
          tr.cells[2].textContent = `d ${valueOf("wire_diameter")} · Dm ${valueOf("mean_diameter")} · H₀ ${valueOf("free_length")}`;
          tr.cells[3].textContent = `总 ${valueOf("total_coils")} · 有效 ${valueOf("active_coils")}`;
          tr.cells[4].textContent = (v.issues || []).join("；") || "待人工核对";
          if (v.review) { const button = document.createElement("button"); button.type = "button"; button.textContent = "打开审图"; button.addEventListener("click", () => { dialog.close(); void openReview(v.review.job_id); }); tr.cells[4].append(button); }
          tr.addEventListener("click", event => { if (!event.target.closest("input,button")) { showRegion(v); body.querySelectorAll("tr").forEach(row => row.classList.toggle("is-located", row === tr)); } });
          body.append(tr);
        } showRegion(state.value.variants[0]); controls();
      }
      dialog.querySelector('[data-action="close"]').onclick = () => { if (!state.busy) dialog.close(); };
      dialog.addEventListener("cancel", e => { if (state.busy) e.preventDefault(); });
      dialog.addEventListener("close", () => { dialog.remove(); if (view === state) view = null; });
      dialog.querySelector("select").onchange = e => { const p = state.value.pages.find(p => String(p.page) === e.target.value); dialog.querySelector("img").src = assetUrl(p.image_url); dialog.querySelector("svg").setAttribute("hidden", ""); };
      dialog.querySelector('[data-action="select"]').onclick = () => { for (const v of state.value.variants) if (!v.review) state.selected.add(v.variant_id); state.key = null; render(); };
      dialog.querySelector('[data-action="refresh"]').onclick = async () => {
        state.busy = true; controls();
        try { const value = await load(id); if (active()) { state.value = value; for (const v of value.variants) if (v.review) state.selected.delete(v.variant_id); render(); message("清单已刷新。"); changed(); } }
        catch (error) { if (active()) message(error.message); }
        finally { if (active()) { state.busy = false; controls(); } }
      };
      dialog.querySelector('[data-action="create"]').onclick = async () => {
        if (state.busy || !state.selected.size) return; state.busy = true; controls(); message("正在保存当前修改…");
        try {
          if (!await save()) throw new Error("当前修改未保存，未创建规格记录。请先重试保存。"); if (!active()) return;
          const ids = [...state.selected], signature = JSON.stringify(ids.slice().sort());
          if (!state.key || state.keyIds !== signature) { state.key = globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `variants-${Date.now()}-${Math.random().toString(16).slice(2)}`; state.keyIds = signature; }
          message("正在创建独立审图记录…");
          const response = await request(`/api/reviews/${encodeURIComponent(id)}/variants/create-reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ variant_ids: ids, expected_source_revision: state.value.source_revision, idempotency_key: state.key }) });
          const result = await response.json(); if (!active()) return;
          if (!response.ok) throw new Error(result.detail || "创建失败，请刷新后重试。");
          const value = await load(id); if (!active()) return; state.value = value; state.selected.clear(); state.key = null; render(); changed();
          message(`已创建或找到${result.reviews.length}条独立审图记录。点击“打开审图”继续核对。`);
        } catch (error) { if (active()) message(`${error.message} 网络结果不明时可使用同一选择重试，不会重复建单。`); }
        finally { if (active()) { state.busy = false; controls(); } }
      };
      render(); dialog.showModal(); viewed(id, round); return true;
    }
    return { open, load, decorate, items, find, remove, reset };
  }
  root.MultiSpecReview = { create };
})(globalThis);
