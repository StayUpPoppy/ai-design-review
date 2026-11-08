/* Order-scoped drafts: opening/cancelling never mutates engineering values. */
(() => {
  const { number, esc, text, signed, empty, validate, read, equals, preview } = ToleranceValues;
  const isLoad = kind => kind === "load" || kind === "load-create";
  const pencil = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15z"/></svg>';
  class Controller {
    constructor(config) { this.config = config; this.drafts = new Map(); this.bindings = new WeakMap(); }
    owner() { return this.config.owner(); }
    current() { return this.drafts.get(this.owner()); }
    dirty() { const d = this.current(); return Boolean(d && JSON.stringify([d.mode, d.magnitude, d.upper, d.lower, d.clear]) !== d.initial); }
    basis(r, kind) { return JSON.stringify([r.liveNominal ? null : r.nominal, r.unit, read(r.item, isLoad(kind)), r.item.tolerance_input_draft ?? null]); }
    seed(kind, target, r) {
      const value = read(r.item, isLoad(kind));
      const mode = value.percent != null ? "percent" : value.upper == null && value.lower == null || number(value.upper) >= 0 && number(value.upper) === -number(value.lower) ? "symmetric" : "pair";
      const d = { kind, target, mode, magnitude: text(value.percent ?? (mode === "symmetric" ? value.upper : null)), upper: text(value.upper), lower: text(value.lower), clear: false, notice: "", needsInput: false, basis: this.basis(r, kind) };
      if (r.item.tolerance_input_draft) { d.magnitude = r.item.tolerance_input_draft; d.mode = "symmetric"; }
      d.initial = JSON.stringify([d.mode, d.magnitude, d.upper, d.lower, d.clear]);
      return d;
    }
    matching(kind, target) {
      let d = this.current();
      if (!d || d.kind !== kind || d.target !== target) return null;
      const r = this.config.resolve(kind, target);
      if (r && !this.dirty() && d.basis !== this.basis(r, kind)) { d = this.seed(kind, target, r); this.drafts.set(this.owner(), d); }
      return d;
    }
    guard() {
      if (!this.dirty()) return true;
      this.current().notice = "请先保存或取消当前公差编辑，再继续操作。";
      this.config.notice(this.current().notice); this.config.reveal(); this.sync(document); this.focus();
      return false;
    }
    open(kind, target) {
      if (this.config.busy()) return;
      if (this.dirty() && !this.matching(kind, target)) return this.guard();
      const r = this.config.resolve(kind, target); if (!r) return;
      if (!this.matching(kind, target)) this.drafts.set(this.owner(), this.seed(kind, target, r));
      this.config.render(); this.focus();
    }
    focus() {
      const d = this.current(); if (!d) return;
      requestAnimationFrame(() => {
        const overlay = document.getElementById('compareOverlay');
        const scope = overlay && !overlay.hidden ? overlay.querySelector('[data-compare-panel="parameters"]') : document;
        const el = [...(scope || document).querySelectorAll('[data-tolerance-editor]')].find(n => n.dataset.toleranceKind === d.kind && n.dataset.toleranceTarget === d.target);
        if (!el) return;
        const details = el.closest('details'); if (details) details.open = true;
        el.scrollIntoView({ block: "nearest" }); el.querySelector('[data-tolerance-input]')?.focus({ preventScroll: true });
      });
    }
    result(d = this.current()) {
      if (d.clear) return validate(null, null);
      if (d.mode === "pair") return d.needsInput && empty(d.upper) && empty(d.lower)
        ? { ok: false, error: "请填写上下偏差，或点击清除公差。" } : validate(d.upper, d.lower);
      if (empty(d.magnitude)) return d.needsInput ? { ok: false, error: "请填写公差幅值，或点击清除公差。" } : validate(null, null);
      if (d.mode === "percent") return validate(null, null, d.magnitude);
      const n = number(d.magnitude);
      return n != null && n >= 0 ? validate(n, -n) : { ok: false, error: "对称公差幅值必须是有限的非负数。" };
    }
    error(d, r, value) {
      return !r ? "参数已删除，请取消当前编辑。" : d.basis !== this.basis(r, d.kind) ? "当前参数或公差已变化，请取消后重新打开编辑。" : value.error || "";
    }
    save() {
      const d = this.current(); if (!d || this.config.busy()) return;
      const r = this.config.resolve(d.kind, d.target), value = this.result(d);
      if (this.error(d, r, value)) { this.sync(document); return; }
      if (!equals(read(r.item, isLoad(d.kind)), value) || r.item.tolerance_input_draft) {
        if (this.config.commit(d, r, value) === false) return;
      }
      this.drafts.delete(this.owner()); this.config.render(); this.restoreFocus(d);
    }
    restoreFocus(d) {
      requestAnimationFrame(() => [...document.querySelectorAll('[data-tolerance-action="open"]')].find(n => n.dataset.toleranceKind === d.kind && n.dataset.toleranceTarget === d.target && n.getClientRects().length)?.focus({ preventScroll: true }));
    }
    cancel() { const d = this.current(); if (!d) return; this.drafts.delete(this.owner()); this.config.render(); this.restoreFocus(d); }
    button(kind, target, label) {
      return `<button type="button" class="tolerance-edit-button" data-tolerance-action="open" data-tolerance-kind="${kind}" data-tolerance-target="${esc(target)}" aria-label="编辑${esc(label)}公差" title="编辑公差">${pencil}</button>`;
    }
    html(kind, target) {
      const d = this.matching(kind, target); if (!d) return "";
      const r = this.config.resolve(kind, target); return r ? editorHtml(this, d, r) : "";
    }
    sync(root) {
      const d = this.current(); if (!d) return;
      const r = this.config.resolve(d.kind, d.target), v = this.result(d), error = this.error(d, r, v);
      root.querySelectorAll('[data-tolerance-editor]').forEach(node => {
        if (node.dataset.toleranceKind !== d.kind || node.dataset.toleranceTarget !== d.target) return;
        node.querySelector('[data-tolerance-error]').textContent = error || d.notice;
        node.querySelector('[data-tolerance-preview]').textContent = preview(v, r?.nominal, r?.unit);
        node.querySelector('[data-tolerance-nominal]').textContent = `当前${isLoad(d.kind) ? "力值" : "数值"}：${text(r?.nominal)} ${r?.unit || ""}`;
        node.querySelector('[data-tolerance-label]').textContent = `编辑公差 · ${r?.label || ""}`;
        node.querySelector('[data-tolerance-action="save"]').disabled = Boolean(error || this.config.busy());
      });
    }
    bind(root, binding) { bindEditor(this, root, binding); }
  }
  function editorHtml(controller, d, r) {
    const v = controller.result(d), error = controller.error(d, r, v);
    const modes = [["symmetric", "对称公差"], ["pair", "上下偏差"], ...(isLoad(d.kind) ? [["percent", "百分比"]] : [])];
    return `<div class="tolerance-editor" data-tolerance-editor data-tolerance-kind="${d.kind}" data-tolerance-target="${esc(d.target)}">
      <div class="tolerance-editor-heading"><strong data-tolerance-label>编辑公差 · ${esc(r.label)}</strong><span>单位：${esc(d.mode === "percent" ? "%" : r.unit || "无量纲")}</span></div>
      <div class="tolerance-editor-modes" role="group" aria-label="公差类型">${modes.map(([mode, label]) => `<button type="button" data-tolerance-action="mode" data-tolerance-mode="${mode}" aria-pressed="${mode === d.mode}">${label}</button>`).join("")}</div>
      <div class="tolerance-editor-fields">${d.mode === "pair" ? `<label>上偏差${r.unit ? `（${esc(r.unit)}）` : ""}<input data-tolerance-input="upper" inputmode="decimal" autocomplete="off" value="${esc(d.upper)}" placeholder="例如：+0.1"></label><label>下偏差${r.unit ? `（${esc(r.unit)}）` : ""}<input data-tolerance-input="lower" inputmode="decimal" autocomplete="off" value="${esc(d.lower)}" placeholder="例如：-0.2"></label>` : `<label>${d.mode === "percent" ? "公差百分比（%）" : "公差幅值"}<span class="tolerance-magnitude">±<input data-tolerance-input="magnitude" inputmode="decimal" autocomplete="off" value="${esc(d.magnitude)}" placeholder="例如：0.1">${esc(d.mode === "percent" ? "%" : r.unit)}</span></label>`}</div>
      <small class="tolerance-editor-help">${d.mode === "pair" ? "支持正、负偏差；单边公差请将另一侧填 0。" : "只填写非负数，无需输入 ± 符号。"}</small>
      <p class="tolerance-editor-error" data-tolerance-error role="status">${esc(error || d.notice)}</p>
      <div class="tolerance-editor-footer"><div class="tolerance-editor-preview" aria-live="polite"><small>${isLoad(d.kind) ? "力值" : "尺寸"}范围（按公差计算）</small><strong data-tolerance-preview>${esc(preview(v, r.nominal, r.unit))}</strong><small data-tolerance-nominal>当前${isLoad(d.kind) ? "力值" : "数值"}：${esc(text(r.nominal))} ${esc(r.unit)}</small></div><div class="tolerance-editor-actions"><button type="button" class="secondary-action" data-tolerance-action="clear">清除公差</button><button type="button" class="secondary-action" data-tolerance-action="cancel">取消</button><button type="button" data-tolerance-action="save"${error || controller.config.busy() ? " disabled" : ""}>保存公差</button></div></div>
    </div>`;
  }
  function bindEditor(c, root, binding) {
    if (c.bindings.has(root)) { c.bindings.set(root, binding); return; }
    c.bindings.set(root, binding);
    root.addEventListener('click', event => {
      const b = c.bindings.get(root);
      if (b.current() && c.dirty() && c.config.blocks(event.target)) { event.preventDefault(); event.stopImmediatePropagation(); c.guard(); }
    }, true);
    root.addEventListener('click', event => {
      const b = c.bindings.get(root); if (!b.current()) return;
      const button = event.target.closest('[data-tolerance-action]');
      if (!button || !root.contains(button)) return;
      b.activate(); event.preventDefault();
      const action = button.dataset.toleranceAction;
      if (action === 'open') return c.open(button.dataset.toleranceKind, button.dataset.toleranceTarget);
      if (action === 'cancel') return c.cancel();
      if (action === 'save') return c.save();
      const d = c.current(); if (!d) return;
      if (action === 'clear') { Object.assign(d, { magnitude: '', upper: '', lower: '', clear: true, notice: '', needsInput: false }); c.config.render(); c.focus(); }
      if (action === 'mode') {
        const value = c.result(d), mode = button.dataset.toleranceMode;
        if (mode === 'pair' && empty(d.upper) && empty(d.lower) && value.ok && value.upper != null) { d.upper = signed(value.upper); d.lower = signed(value.lower); }
        d.mode = mode; d.clear = false; d.notice = '';
        if (mode === 'pair') d.needsInput = empty(d.upper) && empty(d.lower) && value.percent != null;
        if (mode !== 'pair') { d.magnitude = value.ok && (mode === 'percent' ? value.percent != null : value.upper != null && value.upper === -value.lower) ? text(mode === 'percent' ? value.percent : value.upper) : ''; d.needsInput = empty(d.magnitude); }
        c.config.render(); c.focus();
      }
    });
    root.addEventListener('input', event => {
      const b = c.bindings.get(root); if (!b.current() || !event.target.matches('[data-tolerance-input]')) return;
      b.activate(); const d = c.current(); if (!d) return;
      d[event.target.dataset.toleranceInput] = event.target.value; d.clear = false; d.notice = ''; d.needsInput = false; c.sync(root);
    });
    root.addEventListener('keydown', event => {
      const b = c.bindings.get(root); if (!b.current() || !event.target.closest('[data-tolerance-editor]') || event.isComposing) return;
      b.activate();
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); c.cancel(); }
      if (event.key === 'Enter' && event.target.matches('[data-tolerance-input]')) { event.preventDefault(); event.stopPropagation(); c.save(); }
    });
  }
  globalThis.ToleranceEditor = { Controller };
})();
