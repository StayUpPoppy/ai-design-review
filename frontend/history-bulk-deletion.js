(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HistoryBulkDeletion = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function create({ getScope, save, requestDelete, onDeleted, onChange = () => {}, onRunningChange = () => {} }) {
    const state = { managing: false, running: false, selected: new Set(), visible: new Map(), results: new Map(),
      notice: "", progress: { current: 0, total: 0 } };
    let operation = null;
    const changed = () => onChange(state);
    const reset = () => {
      const wasRunning = state.running;
      operation = null; state.managing = false; state.running = false;
      state.selected.clear(); state.visible.clear(); state.results.clear(); state.notice = "";
      state.progress = { current: 0, total: 0 };
      if (wasRunning) onRunningChange(false);
      changed();
    };
    function updateVisible(items) {
      state.visible = new Map(items.map((item) => [item.job_id, item]));
      if (!state.running) for (const id of state.selected) if (!state.visible.has(id)) state.selected.delete(id);
      changed();
    }
    function enter() {
      if (state.running) return;
      if (!state.managing) state.results.clear();
      state.managing = true; state.notice = ""; changed();
    }
    function exit() {
      if (state.running) return;
      state.managing = false; state.selected.clear(); state.results.clear(); state.notice = ""; changed();
    }
    function toggle(id) {
      if (!state.managing || state.running || !state.visible.has(id)) return;
      if (state.selected.has(id)) state.selected.delete(id);
      else if (state.selected.size < 100) state.selected.add(id);
      else state.notice = "每次最多选择100条订单，请分批删除。";
      changed();
    }
    function selectAll() {
      if (!state.managing || state.running) return;
      state.selected = new Set([...state.visible.keys()].slice(0, 100));
      state.notice = state.visible.size > 100 ? "已选择前100条，其他订单可在下一批处理。" : ""; changed();
    }
    function clearSelection() { if (state.running) return; state.selected.clear(); changed(); }
    function selectedItems() {
      return [...state.selected].map((id) => state.visible.get(id)).filter((item) => item
        && (state.results.get(item.job_id)?.kind !== "unknown" || state.results.get(item.job_id)?.checked));
    }
    function failedItems() { return selectedItems().filter((item) => state.results.get(item.job_id)?.kind === "failed"); }
    function checkedUnknown(ids) {
      for (const id of ids) {
        const result = state.results.get(id);
        if (result?.kind === "unknown" && state.visible.has(id)) result.checked = true;
      }
      state.notice = "已刷新列表。结果待核对的订单若仍在列表，可重新选择并确认删除；未显示不代表服务器已彻底清理。";
      changed();
    }
    function summary() {
      const counts = { deleted: 0, cancelling: 0, failed: 0, unknown: 0, pending: 0, cleanupPending: 0 };
      for (const result of state.results.values()) { counts[result.kind]++; if (result.cleanupPending) counts.cleanupPending++; }
      return counts;
    }
    async function run(items, { bulk = true } = {}) {
      if (state.running || !items.length || items.length > 100 || !getScope()) return false;
      const captured = items.map((item) => ({ ...item })), current = { scope: getScope() };
      if (captured.reduce((n, item) => n + (item.record_kind === "source" ? item.created_count || 0 : 1), 0) > 100) {
        state.notice = "一次最多删除100条实际审图记录，请分批处理。"; changed(); return false;
      }
      operation = current; state.running = true; state.notice = "正在保存当前修改…";
      state.progress = { current: 0, total: captured.length };
      const active = () => operation === current && getScope() === current.scope;
      onRunningChange(true); changed();
      try {
        if (!await save()) throw new Error("当前参数尚未保存，请先重试保存后再删除订单。");
        if (!active()) return false;
        state.results = new Map([...(bulk ? state.results : []), ...captured.map((item) => [item.job_id, { item, kind: "pending", message: "尚未处理" }])]);
        state.notice = "";
        for (let index = 0; index < captured.length; index++) {
          if (!active()) return false;
          const item = captured[index];
          state.progress.current = index + 1; changed();
          let result;
          try {
            const response = await requestDelete(item, current.scope);
            if (!active()) return false;
            let payload;
            try { payload = await response.json(); }
            catch (error) {
              if ([401, 403].includes(response.status)) payload = { detail: "登录已失效或无删除权限，请恢复登录或权限。" };
              else throw error;
            }
            if (!active()) return false;
            if (!response.ok) {
              const detail = payload?.detail;
              result = { item, kind: "failed", message: typeof detail === "string" ? detail : detail?.message || `删除失败（HTTP ${response.status}）`, auth: [401, 403].includes(response.status) };
            } else if (payload?.deleted !== true || (payload.job_id && payload.job_id !== item.job_id)) {
              result = { item, kind: "unknown", message: "删除回执无效，结果待核对，请先刷新历史订单。" };
            } else {
              result = { item, kind: payload.status === "cancelling" ? "cancelling" : "deleted",
                message: payload.status === "cancelling" ? "已提交取消，后台清理中" : "已删除",
                cleanupPending: payload.artifact_cleanup === "pending", deletedIds: payload.deleted_ids || [item.job_id] };
            }
          } catch {
            if (!active()) return false;
            result = { item, kind: "unknown", message: "网络中断或回执无法读取，结果待核对，请先刷新历史订单。" };
          }
          state.results.set(item.job_id, result);
          if (["deleted", "cancelling"].includes(result.kind)) {
            state.selected.delete(item.job_id);
            onDeleted(item, result);
          }
          changed();
          if (result.auth) { state.notice = "登录已失效或无删除权限，后续删除已停止。请恢复登录或权限后再处理。"; break; }
        }
        if (bulk && ![...state.results.values()].some((result) => ["failed", "unknown", "pending"].includes(result.kind))) {
          state.managing = false; state.selected.clear();
        }
        return true;
      } catch (error) {
        if (active()) state.notice = error.message || "保存失败，本次未删除任何订单。";
        return false;
      } finally {
        if (operation === current) {
          operation = null; state.running = false; onRunningChange(false); changed();
        }
      }
    }
    return { state, reset, updateVisible, enter, exit, toggle, selectAll, clearSelection, selectedItems,
      failedItems, checkedUnknown, summary, run };
  }
  return { create };
});
