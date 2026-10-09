/* Historical recovery is an explicit preview, never a second parameter editor. */
(() => {
  const sessions = new WeakMap();
  let hooks;
  const session = (review) => {
    if (!sessions.has(review)) sessions.set(review, { status: "idle", items: [], selected: new Set() });
    return sessions.get(review);
  };
  const active = (review, jobId) => hooks.getReview() === review && hooks.getJobId() === jobId;
  const token = () => JSON.stringify([hooks.getRevision(), hooks.getEditSerial(), hooks.canOperate()]);
  const refresh = () => hooks.update();
  const errorText = (payload, fallback) => typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message || fallback;

  async function preview() {
    const review = hooks.getReview(), jobId = hooks.getJobId();
    if (!review || !jobId) return false;
    const entry = session(review);
    if (["loading", "saving"].includes(entry.status)) return false;
    if (entry.status === "save_failed") return retrySave();
    if (!hooks.canOperate()) {
      entry.error = "当前有未完成的编辑或计算，请先确认／保存这些内容再预览。";
      entry.status = "error"; refresh(); return false;
    }
    entry.status = "loading"; entry.error = ""; refresh();
    try {
      if (!await hooks.save()) throw new Error("当前修改尚未保存，请重试保存后再预览。");
      if (!active(review, jobId)) return false;
      if (!hooks.canOperate()) throw new Error("当前编辑尚未保存，请保存后重新预览。");
      const sourceToken = token();
      const response = await hooks.fetch(`/api/reviews/${encodeURIComponent(jobId)}/technical-requirements/recover-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: hooks.getRevision() ?? null }),
      });
      const payload = await response.json();
      if (!active(review, jobId)) return false;
      if (!response.ok) throw new Error(errorText(payload, "补回预览加载失败，请重试。"));
      if (sourceToken !== token() || payload.job_id !== jobId || (payload.based_on_revision ?? null) !== (hooks.getRevision() ?? null)) {
        throw new Error("预览期间审图内容已变化，请重新加载预览；当前输入未改动。");
      }
      if (!Array.isArray(payload.items)) throw new Error("预览返回的数据不完整，请重试。");
      entry.items = payload.items.filter((row) => row?.requirement?.requirement_id && row.requirement.recognition_key
        && String(row.requirement.content || "").trim() && ["available", "possible_existing"].includes(row.status));
      entry.selected = new Set(entry.items.filter((row) => row.status === "available").map((row) => row.requirement.recognition_key));
      entry.orderHints = Array.isArray(payload.order_hints) ? payload.order_hints : [];
      entry.message = payload.message || "请选择需要补回的条目。";
      entry.sourceToken = sourceToken;
      entry.status = "preview";
      refresh(); return true;
    } catch (error) {
      entry.status = "error"; entry.error = error.message || "补回预览加载失败，请重试。";
      if (active(review, jobId)) refresh();
      return false;
    } finally {
      if (entry.status === "loading") entry.status = "idle";
    }
  }

  async function retrySave() {
    const review = hooks.getReview(), jobId = hooks.getJobId();
    if (!review) return false;
    const entry = session(review);
    if (entry.status === "saving") return false;
    entry.status = "saving"; entry.error = ""; refresh();
    let saved = false;
    try { saved = await hooks.save(); } catch (error) { entry.error = error.message; }
    entry.status = saved ? "saved" : "save_failed";
    entry.message = saved ? "补回条目已保存，请核对后确认。" : "保存失败，补回条目仍保留在当前页面；重试保存不会重复补入。";
    if (active(review, jobId)) refresh();
    return saved;
  }

  async function apply() {
    const review = hooks.getReview();
    if (!review) return false;
    const entry = session(review);
    if (entry.status !== "preview") return false;
    if (entry.sourceToken !== token()) {
      entry.status = "error"; entry.error = "审图内容已变化，请重新预览后再补回；未修改当前内容。"; refresh(); return false;
    }
    const selected = entry.items.filter((row) => entry.selected.has(row.requirement.recognition_key));
    if (!selected.length) return false;
    const existingKeys = new Set((review.technical_requirements || []).map((item) => item.recognition_key).filter(Boolean));
    const existingIds = new Set((review.technical_requirements || []).map((item) => item.requirement_id));
    const additions = selected.map((row) => structuredClone(row.requirement));
    if (additions.some((item) => existingKeys.has(item.recognition_key) || existingIds.has(item.requirement_id))) {
      entry.status = "error"; entry.error = "部分条目已存在，请重新预览，避免重复补入。"; refresh(); return false;
    }
    // One explicit operation: only provenance hints change on existing notes.
    (entry.orderHints || []).forEach((hint) => {
      const current = (review.technical_requirements || []).find((item) => item.requirement_id === hint.requirement_id);
      if (current && !current.recognition_key) {
        ["original_number", "source_order", "recognition_key", "recognized_content", "page"].forEach((name) => { if (hint[name] != null) current[name] = hint[name]; });
      }
    });
    review.technical_requirements ||= [];
    additions.forEach((item) => {
      item.need_human_review = true;
      delete item.human_confirmed;
      delete item.confirmation_snapshot;
      const index = review.technical_requirements.findIndex((current) => current.source_order != null
        && ((Number(current.page || 1) > Number(item.page || 1)) || (Number(current.page || 1) === Number(item.page || 1) && Number(current.source_order) > Number(item.source_order))));
      review.technical_requirements.splice(index < 0 ? review.technical_requirements.length : index, 0, item);
      hooks.audit({ event_type: "technical_requirement_recovered", target_field: `technical_requirements.${item.requirement_id}`,
        source: "recognition_recovery", reason: "用户选择补回原始识别条目，仍需人工确认",
        after_state: structuredClone(item), metadata: { requirement_id: item.requirement_id, recognition_key: item.recognition_key, original_number: item.original_number } });
    });
    hooks.changed();
    entry.items = []; entry.selected.clear(); entry.status = "save_failed";
    return retrySave();
  }

  function render(review) {
    if (!hooks) return "";
    const entry = session(review), escape = hooks.escape;
    if (entry.status === "idle") return "";
    if (entry.status === "loading") return '<div class="technical-recovery" role="status">正在读取原始识别记录…不会修改当前要求。</div>';
    if (["error", "saving", "save_failed", "saved"].includes(entry.status)) return `<div class="technical-recovery" role="status">
      <p>${escape(entry.status === "saving" ? "补回条目保存中…" : entry.error || entry.message)}</p>
      ${entry.status === "error" ? '<button type="button" class="secondary-action" data-recovery-action="preview">重新加载预览</button>' : ""}
      ${entry.status === "save_failed" ? '<button type="button" class="secondary-action" data-recovery-action="save">保存失败·重试保存</button>' : ""}</div>`;
    return `<div class="technical-recovery" aria-label="遗漏技术要求补回预览">
      <p role="status">${escape(entry.message)}</p>
      ${entry.items.map((row, index) => {
        const item = row.requirement;
        return `<div class="technical-recovery-item">
          <label class="technical-recovery-choice"><input type="checkbox" data-recovery-index="${index}"${entry.selected.has(item.recognition_key) ? " checked" : ""}>
            <span>${escape(item.original_number != null ? `原图第 ${item.original_number} 条` : `候选 ${index + 1}`)} · ${escape(hooks.typeLabel(item.type))}${row.status === "possible_existing" ? " · 可能已存在" : ""}</span></label>
          <p>${escape(item.content)}</p><small>${escape(row.reason)}</small>
          ${item.original_content ? `<details><summary>查看原文与依据</summary><p dir="auto">${escape(item.original_content)}</p><p dir="auto">${escape(item.evidence || "未保存额外识别依据。")}</p></details>` : ""}
        </div>`;
      }).join("")}
      <div class="technical-recovery-actions">
        ${entry.items.length ? `<button type="button" data-recovery-action="apply"${entry.selected.size ? "" : " disabled"}>补回所选（${entry.selected.size} 项）</button>` : ""}
        <button type="button" class="secondary-action" data-recovery-action="preview">重新加载预览</button>
        <button type="button" class="secondary-action" data-recovery-action="close">收起预览</button>
      </div></div>`;
  }

  function bind(root, activate = () => {}) {
    root.querySelectorAll("[data-recovery-action]").forEach((button) => button.addEventListener("click", () => {
      activate();
      const action = button.dataset.recoveryAction;
      if (action === "preview") void preview();
      if (action === "apply") void apply();
      if (action === "save") void retrySave();
      if (action === "close") { const entry = session(hooks.getReview()); entry.status = "idle"; refresh(); }
    }));
    root.querySelectorAll("[data-recovery-index]").forEach((input) => input.addEventListener("change", () => {
      activate();
      const entry = session(hooks.getReview()), row = entry.items[Number(input.dataset.recoveryIndex)];
      if (!row) return;
      if (input.checked) entry.selected.add(row.requirement.recognition_key); else entry.selected.delete(row.requirement.recognition_key);
      const button = root.querySelector('[data-recovery-action="apply"]');
      if (button) { button.disabled = !entry.selected.size; button.textContent = `补回所选（${entry.selected.size} 项）`; }
    }));
  }
  window.TechnicalRequirementRecovery = { configure: (value) => { hooks = value; }, render, bind, preview, apply, retrySave, getState: session };
})();
