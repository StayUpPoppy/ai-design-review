/* Original drawing UI only. This module never edits or saves spring parameters. */
window.DrawingAnnotations = (() => {
  const fields = ["material", "standard_no", "accuracy_grade", "wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter", "free_length", "solid_height", "total_coils", "active_coils", "surface_roughness_ra", "handedness", "end_type", "end_grinding"];
  const cache = new Map();
  let config;
  let resizeObserver;
  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const bound = (value) => Math.max(0, Math.min(1, value));
  function entry() {
    const id = config?.getJobId();
    if (!id || !config.isCompression()) return null;
    if (!cache.has(id)) cache.set(id, { id, document: null, page: 1, visible: true, editing: false, selected: "", placing: "", pending: new Map(), loading: false, error: "", phase: "idle", conflict: null, saving: null });
    return cache.get(id);
  }
  function notify(item) {
    if (entry() === item) config.updateViewer();
  }
  async function load(item = entry(), retry = false) {
    if (!item || item.loading || item.document || (item.loadAttempted && !retry)) return;
    item.loadAttempted = true;
    item.loading = true;
    item.error = "";
    try {
      const response = await config.fetch(`/api/reviews/${encodeURIComponent(item.id)}/annotations`);
      if (!response.ok) throw new Error("标注加载失败，可重试；参数操作不受影响。");
      item.document = await response.json();
    } catch (error) {
      item.error = error.message;
    } finally {
      item.loading = false;
      notify(item);
    }
  }
  function page() {
    const item = entry();
    return item?.document?.pages?.find((p) => p.page === item.page);
  }
  function annotation(field, item = entry()) {
    return item?.document?.annotations?.find((a) => a.field === field);
  }
  function toolsHtml() {
    const item = entry();
    if (!item) return "";
    if (!item.document) return `<div class="annotation-status" role="status">${esc(item.error || "正在定位原图参数…")}${item.error ? ' <button type="button" data-annotation-action="load">重试加载标注</button>' : ""}</div>`;
    const pages = item.document.pages || [];
    return `<div class="annotation-tools">
      ${pages.length > 1 ? `<label>原图页码 <select data-annotation-page aria-label="原图页码">${pages.map((p) => `<option value="${p.page}" ${p.page === item.page ? "selected" : ""}>第 ${p.page} 页</option>`).join("")}</select></label>` : ""}
      <button type="button" data-annotation-action="visible" aria-pressed="${item.visible}">${item.visible ? "隐藏标注" : "显示标注"}</button>
      <button type="button" data-annotation-action="edit" aria-pressed="${item.editing}" ${item.relocalizing ? "disabled" : ""}>${item.editing ? "结束调整" : "调整标注"}</button>
      <button type="button" data-annotation-action="relocalize" ${item.relocalizing || item.conflict ? "disabled" : ""}>${item.relocalizing ? "正在补定位…" : "重新补定位"}</button>
      <span role="status">${item.phase === "saving" ? "标注保存中…" : item.phase === "saved" ? "标注已保存" : ""}</span>
      ${item.phase === "failed" ? '<button type="button" data-annotation-action="retry">保存失败·重试保存</button>' : ""}
      ${item.conflict ? '<span>位置已被其他页面更新</span><button type="button" data-annotation-action="server">使用服务器位置</button><button type="button" data-annotation-action="local">保留本地位置</button>' : ""}
    </div>`;
  }
  function infoHtml() {
    const item = entry();
    if (!item?.document) return "";
    const selected = annotation(item.selected);
    const current = selected ? config.getParameter(selected.field) : null;
    const unlocated = item.document.annotations.filter((a) => !a.locations.length && (a.original_value != null || config.getParameter(a.field)?.value != null && config.getParameter(a.field)?.value !== ""));
    const diagnostics = (item.document.diagnostics || []).filter((d) => d.kind !== "unlocated" && (d.kind !== "value_mismatch" || String(d.evidence_value) !== String(config.getParameter(d.field)?.value)));
    return `<div class="annotation-info" aria-live="polite">
      ${selected ? `<span><strong>${selected.number} · ${esc(selected.label)}</strong>　原图识别值：${esc(selected.original_value ?? "无直接标注")}　当前值：${esc(current?.value ?? "未填写")}</span>${item.editing ? ` <button type="button" data-annotation-place="${esc(selected.field)}">重新定位</button>` : ""}` : ""}
      ${item.placing ? '<p>点击原图中的标注位置。Esc 可取消；拖动气泡或使用方向键仅调整气泡位置。</p>' : item.editing ? '<p>拖动气泡调整位置；选择未定位参数可在原图补位置。调整不改变参数。</p>' : ""}
      ${item.error ? `<p class="annotation-error">${esc(item.error)}</p>` : ""}
      ${diagnostics.length ? `<ul class="annotation-diagnostics">${diagnostics.map((d) => `<li><strong>${esc(config.fieldLabel(d.field))}</strong>：${d.kind === "value_mismatch" ? `原图证据 ${esc(d.evidence_value)}，当前参数 ${esc(config.getParameter(d.field)?.value ?? "未填写")}。请核对后修改并重新确认。` : esc(d.reason)}</li>`).join("")}</ul>` : ""}
      ${unlocated.length ? `<details class="annotation-unlocated"><summary>${unlocated.length} 项暂无可靠原图位置</summary><ul>${unlocated.map((a) => `<li><span>${a.number} · ${esc(a.label)}：${esc(a.reason)}</span><button type="button" data-annotation-place="${esc(a.field)}">人工定位</button></li>`).join("")}</ul></details>` : ""}
      <small class="annotation-layout-warning" role="status">${esc(item.layoutWarning || "")}</small>
      ${selected?.locations?.length && selected.reason ? `<small>${esc(selected.reason)}</small>` : ""}
      ${(item.document.warnings || []).map((warning) => `<small>${esc(warning)}</small>`).join("")}
    </div>`;
  }
  function badgeHtml(field, param) {
    const index = fields.indexOf(field);
    if (index < 0 || !config?.isCompression()) return "";
    return `<button type="button" class="parameter-annotation-number" data-annotation-field="${esc(field)}" aria-label="定位${esc(config.fieldLabel(field))}原图标注">${index + 1}</button>`;
  }
  function bindFields(root, before) {
    root.querySelectorAll("[data-annotation-field]").forEach((button) => button.addEventListener("click", () => { before?.(); config.openViewer(); void focusField(button.dataset.annotationField); }));
  }
  async function focusField(field) {
    const item = entry();
    if (!item) return;
    await load(item);
    if (entry() !== item) return;
    item.selected = field;
    const target = annotation(field, item)?.locations?.[0];
    if (target) {
      item.page = target.page;
      item.visible = true;
      config.updateViewer();
      config.center(target.anchor);
    } else {
      item.error = "未找到可靠原图位置，可点击调整标注后人工定位。";
      notify(item);
    }
  }
  function screenPoint(point) {
    const image = config.getImage();
    const view = config.getView();
    return { x: view.x + point.x * image.naturalWidth * view.scale, y: view.y + point.y * image.naturalHeight * view.scale };
  }
  function imagePoint(event) {
    const viewport = config.getViewport();
    const image = config.getImage();
    const view = config.getView();
    const rect = viewport.getBoundingClientRect();
    return { x: bound((event.clientX - rect.left - view.x) / (image.naturalWidth * view.scale)), y: bound((event.clientY - rect.top - view.y) / (image.naturalHeight * view.scale)) };
  }
  const automatic = (location) => ["ocr", "pdf_text", "candidate", "local_ocr"].includes(location.source);
  const locationKey = (a, l) => `${a.field}:${l.location_id}`;
  function intersects(a, b, c, d) {
    const side = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
    return side(a, b, c) * side(a, b, d) < 0 && side(c, d, a) * side(c, d, b) < 0;
  }
  // Pure, bounded screen-space solver. It never moves evidence or writes back
  // automatic positions. Pan is deliberately absent from its inputs.
  function layoutLocations(entries, obstacles, width, height) {
    const positions = new Map(), anchors = new Map(), fixed = new Set();
    const pixel = (p) => ({ x: p.x * width, y: p.y * height });
    const clampPoint = (p) => ({ x: Math.max(Math.min(17, width / 2), Math.min(Math.max(width - 17, width / 2), p.x)), y: Math.max(Math.min(17, height / 2), Math.min(Math.max(height - 17, height / 2), p.y)) });
    const boxes = obstacles.map((b) => ({ x: b.x * width, y: b.y * height, width: b.width * width, height: b.height * height }));
    for (const e of entries) {
      anchors.set(e.key, pixel(e.location.anchor));
      if (!automatic(e.location)) { fixed.add(e.key); positions.set(e.key, pixel(e.location.bubble)); }
    }
    function score(key, p) {
      let collisions = 0, covered = 0, crossings = 0;
      for (const [other, q] of positions) {
        if (other === key) continue;
        if (Math.hypot(p.x - q.x, p.y - q.y) < 36) collisions++;
        if (intersects(anchors.get(key), p, anchors.get(other), q)) crossings++;
      }
      for (const b of boxes) {
        const dx = Math.max(b.x - p.x, 0, p.x - b.x - b.width);
        const dy = Math.max(b.y - p.y, 0, p.y - b.y - b.height);
        if (Math.hypot(dx, dy) < 18) covered++;
      }
      const a = anchors.get(key);
      return [collisions, covered, crossings, Math.hypot(p.x - a.x, p.y - a.y)];
    }
    const before = (a, b) => { for (let i = 0; i < a.length; i++) { if (a[i] !== b[i]) return a[i] < b[i]; } return false; };
    const movable = entries.filter((e) => !fixed.has(e.key));
    for (const pass of [movable, [...movable].reverse()]) {
      for (const e of pass) {
        const a = anchors.get(e.key);
        const choices = [positions.get(e.key) || clampPoint(pixel(e.location.bubble))];
        for (const radius of [36, 54, 78, 110, 150, 210]) {
          for (let i = 0; i < 16; i++) {
            const angle = -Math.PI / 4 + i * Math.PI / 8;
            choices.push(clampPoint({ x: a.x + Math.cos(angle) * radius, y: a.y + Math.sin(angle) * radius }));
          }
        }
        let best = choices[0], bestScore = score(e.key, best);
        for (const p of choices.slice(1)) { const s = score(e.key, p); if (before(s, bestScore)) { best = p; bestScore = s; } }
        positions.set(e.key, best);
      }
    }
    let crowded = false;
    for (const e of entries) { const s = score(e.key, positions.get(e.key)); if (s[0] || s[1] || s[2]) crowded = true; }
    return { positions, crowded };
  }
  function adoptVisualPosition(item, a, location) {
    const p = item.layout?.positions.get(locationKey(a, location));
    const image = config.getImage(), scale = config.getView().scale;
    if (p && automatic(location)) location.bubble = { x: bound(p.x / (image.naturalWidth * scale)), y: bound(p.y / (image.naturalHeight * scale)) };
  }
  function renderLayer() {
    const layer = config.getViewport()?.querySelector(".drawing-annotation-layer");
    const image = config.getImage();
    const item = entry();
    if (!layer || !image?.naturalWidth) return;
    const entries = (item?.document?.annotations || []).flatMap((a) => a.locations.filter((l) => l.page === item.page).map((l) => ({ a, location: l, key: locationKey(a, l) })));
    const view = config.getView();
    const width = image.naturalWidth * view.scale, height = image.naturalHeight * view.scale;
    const key = JSON.stringify([item?.page, width, height, item?.document?.annotation_revision, entries.map((e) => [e.key, e.location.source, e.location.bubble])]);
    if (item && item.layout?.key !== key) {
      const obstacles = (item.document?.text_obstacles || []).filter((o) => o.page === item.page).map((o) => o.bbox);
      item.layout = { key, ...layoutLocations(entries, obstacles, width, height) };
      item.layoutWarning = item.layout.crowded ? "标注较密集，建议放大查看或调整气泡位置。" : "";
    }
    layer.innerHTML = !item?.visible ? "" : entries.map(({ a, location: l, key }) => {
      const anchor = screenPoint(l.anchor), p = item.layout.positions.get(key);
      const bubble = { x: view.x + p.x, y: view.y + p.y };
      return `<line x1="${anchor.x}" y1="${anchor.y}" x2="${bubble.x}" y2="${bubble.y}"/><circle class="annotation-anchor" cx="${anchor.x}" cy="${anchor.y}" r="3"/>
        <g class="annotation-bubble ${item.selected === a.field ? "selected" : ""}" transform="translate(${bubble.x} ${bubble.y})" role="button" tabindex="0" aria-label="${esc(`${a.number} ${a.label}，定位参数${item.editing ? '，方向键移动气泡' : ''}`)}" data-annotation-id="${esc(a.field)}" data-location-id="${esc(l.location_id)}"><title>${esc(a.label)}：原图 ${esc(a.original_value ?? "人工定位")}；当前 ${esc(config.getParameter(a.field)?.value ?? "未填写")}</title><circle r="15"/><text text-anchor="middle" dy=".35em">${a.number}</text></g>`;
    }).join("");
    const viewport = config.getViewport();
    const warning = viewport.parentElement?.querySelector(".annotation-layout-warning");
    if (warning) warning.textContent = item?.visible ? item?.layoutWarning || "" : "";
    viewport.classList.toggle("annotation-placing", Boolean(item?.placing));
  }
  function queue(item, a, location) {
    location.source = "manual";
    item.pending.set(`${a.field}:${location.location_id}`, { annotation_id: a.field, location_id: location.location_id, page: location.page, anchor: clone(location.anchor), bubble: clone(location.bubble) });
    item.error = "";
    item.phase = "dirty";
  }
  function mergePending(item) {
    for (const change of item.pending.values()) {
      const a = annotation(change.annotation_id, item);
      if (!a) continue;
      let location = a.locations.find((l) => l.location_id === change.location_id);
      if (!location && !a.locations.length) { location = { location_id: change.location_id, bbox: null, source: "manual" }; a.locations.push(location); }
      if (location) Object.assign(location, clone(change), { source: "manual" });
      a.status = "located";
      a.reason = "";
    }
  }
  async function save(item = entry()) {
    if (!item?.pending.size || item.conflict || !item.document) return;
    if (item.saving) return item.saving;
    item.saving = (async () => {
      while (item.pending.size) {
        item.phase = "saving";
        notify(item);
        const submitted = Array.from(item.pending.values(), clone);
        try {
          const response = await config.fetch(`/api/reviews/${encodeURIComponent(item.id)}/annotations`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_document_id: item.document.source_document_id, expected_annotation_revision: item.document.annotation_revision, changes: submitted }) });
          const payload = await response.json();
          if (response.status === 409) {
            item.conflict = payload.detail?.annotations;
            throw new Error(payload.detail?.message || "标注位置发生冲突，请选择要保留的位置。");
          }
          if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "标注保存失败，本地位置已保留。");
          for (const change of submitted) {
            const key = `${change.annotation_id}:${change.location_id}`;
            if (JSON.stringify(item.pending.get(key)) === JSON.stringify(change)) item.pending.delete(key);
          }
          item.document = payload;
          mergePending(item);
          item.phase = item.pending.size ? "dirty" : "saved";
          item.error = "";
        } catch (error) {
          item.phase = "failed";
          item.error = error.message;
          break;
        }
      }
    })();
    try { await item.saving; } finally { item.saving = null; notify(item); }
  }
  function place(item, field) {
    if (item.relocalizing) return;
    item.selected = field;
    item.placing = field;
    item.visible = true;
    item.editing = true;
    notify(item);
  }
  async function relocalize(item = entry()) {
    if (!item?.document || item.relocalizing || item.conflict) return;
    item.relocalizing = true;
    item.placing = "";
    item.error = "";
    notify(item);
    try {
      await save(item);
      if (item.pending.size || item.conflict) throw new Error("请先保存标注位置或处理位置冲突，再重新补定位。");
      const response = await config.fetch(`/api/reviews/${encodeURIComponent(item.id)}/annotations/relocalize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_document_id: item.document.source_document_id, expected_annotation_revision: item.document.annotation_revision }) });
      const payload = await response.json();
      if (response.status === 409) {
        item.conflict = payload.detail?.annotations;
        throw new Error(payload.detail?.message || "标注位置已更新，请先使用服务器位置，再重试补定位。");
      }
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "补定位失败，原位置已保留，可重试。");
      item.document = payload;
      item.phase = "saved";
    } catch (error) {
      item.error = error.message;
    } finally {
      item.relocalizing = false;
      notify(item);
    }
  }
  function bindViewer(root) {
    const item = entry();
    if (!item) return;
    root.querySelectorAll("[data-annotation-action]").forEach((button) => button.addEventListener("click", () => {
      const action = button.dataset.annotationAction;
      if (action === "relocalize") { void relocalize(item); return; }
      if (action === "load") { void load(item, true); return; }
      if (action === "visible") item.visible = !item.visible;
      if (action === "edit") { item.editing = !item.editing; item.placing = ""; item.visible = true; }
      if (action === "retry") { void save(item); return; }
      if (["server", "local"].includes(action) && item.conflict) {
        if (action === "local" && item.document.source_document_id !== item.conflict.source_document_id) { item.error = "原图已变化，不能把旧位置应用到新原图。"; notify(item); return; }
        item.document = item.conflict;
        item.conflict = null;
        item.error = "";
        if (action === "server") { item.pending.clear(); item.phase = "saved"; }
        else { mergePending(item); void save(item); }
      }
      notify(item);
    }));
    root.querySelectorAll("[data-annotation-place]").forEach((button) => button.addEventListener("click", () => place(item, button.dataset.annotationPlace)));
    root.querySelector("[data-annotation-page]")?.addEventListener("change", (event) => {
      item.page = Number(event.target.value);
      item.placing = "";
      config.changePage();
    });
    const viewport = config.getViewport();
    if (!viewport) return;
    // Delegate so zoom redraws never accumulate pointer/key listeners.
    viewport.addEventListener("pointerdown", (event) => {
      if (item.relocalizing) return;
      if (event.button !== 0) return;
      const group = event.target.closest("[data-annotation-id]");
      if (group) {
        item.selected = group.dataset.annotationId;
        if (item.editing) {
          event.preventDefault();
          item.drag = { field: group.dataset.annotationId, id: group.dataset.locationId, moved: false };
          viewport.setPointerCapture(event.pointerId);
        } else config.focusParameter(item.selected);
      } else if (item.placing) {
        const a = annotation(item.placing, item);
        const point = imagePoint(event);
        if (a) {
          const location = a.locations[0] || { location_id: `${a.field}-manual`, bbox: null, source: "manual" };
          if (!a.locations.length) a.locations.push(location);
          Object.assign(location, { page: item.page, anchor: point, bubble: { x: bound(point.x + .025), y: bound(point.y - .025) }, source: "manual" });
          a.status = "located";
          a.reason = "";
          queue(item, a, location);
          item.placing = "";
          void save(item);
        }
      }
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!item.drag) return;
      const a = annotation(item.drag.field, item);
      const location = a?.locations.find((l) => l.location_id === item.drag.id);
      if (!location) return;
      location.bubble = imagePoint(event);
      item.drag.moved = true;
      queue(item, a, location);
      renderLayer();
    });
    const finish = () => { if (item.drag) { item.drag = null; void save(item); } };
    viewport.addEventListener("pointerup", finish);
    viewport.addEventListener("pointercancel", finish);
    viewport.addEventListener("lostpointercapture", finish);
    viewport.addEventListener("click", (event) => {
      const group = event.target.closest("[data-annotation-id]");
      if (group && item.editing) { item.selected = group.dataset.annotationId; notify(item); }
    });
    viewport.addEventListener("keydown", (event) => {
      if (item.relocalizing) return;
      if (event.key === "Escape") { item.placing = ""; notify(item); return; }
      const group = event.target.closest("[data-annotation-id]");
      if (!group) return;
      if (["Enter", " "].includes(event.key)) { event.preventDefault(); item.selected = group.dataset.annotationId; config.focusParameter(item.selected); return; }
      const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
      if (!item.editing || !moves[event.key]) return;
      event.preventDefault();
      const a = annotation(group.dataset.annotationId, item), l = a.locations.find((location) => location.location_id === group.dataset.locationId);
      const image = config.getImage(), scale = config.getView().scale;
      adoptVisualPosition(item, a, l);
      const [dx, dy] = moves[event.key];
      l.bubble = { x: bound(l.bubble.x + dx * 5 / (image.naturalWidth * scale)), y: bound(l.bubble.y + dy * 5 / (image.naturalHeight * scale)) };
      queue(item, a, l);
      renderLayer();
      viewport.querySelector(`[data-location-id="${l.location_id}"]`)?.focus();
      clearTimeout(item.keySaveTimer);
      item.keySaveTimer = setTimeout(() => void save(item), 250);
    });
    resizeObserver?.disconnect();
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => { config.onResize(); renderLayer(); });
      resizeObserver.observe(viewport);
    }
    void load(item);
    renderLayer();
  }
  return { configure: (options) => { config = options; }, toolsHtml, infoHtml, badgeHtml, bindFields, bindViewer, renderLayer,
    imageUrl: () => page()?.image_url ? config.assetUrl(page().image_url) : null,
    capturesPointer: (event) => Boolean(entry()?.placing || event.target.closest("[data-annotation-id]")),
    hasUnsaved: () => Array.from(cache.values()).some((item) => item.pending.size || item.saving),
    // Exposed pure helpers also make coordinate/saving tests independent of the application.
    fields, screenPoint, imagePoint, focusField, save, entry, layoutLocations, relocalize,
  };
})();
