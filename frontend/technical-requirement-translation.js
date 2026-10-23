/* Text-only translation. Never a second parameter editor or a generation source. */
(() => {
  const standards = /(?:ГОСТ|GOST|GB\s*\/?\s*T|ISO|DIN|ASTM|EN|JIS|СТ\s*[А-Я]+)\s*[A-ZА-Я]*\d+(?:[./–—-]\d+)*/giu;
  // Language recognition only, not engineering equivalence to Cyrillic ST.
  const standardIdentifiers = /(?:СТ|ST)\s*[A-Za-zА-Яа-яЁё]{2,12}\s*\d+(?:[./–—-]\d+)+/giu;
  const codes = /Zn\d+(?:\.[a-z]{1,3})?|(?<![A-Za-zА-Яа-яЁё0-9_])(?:INCONEL\s+\d+|[A-ZА-ЯЁ]{1,8}(?:-\d+(?:[.,]\d+)?)+|[A-Z]{1,8}(?:-\d[A-Za-z\d.]*)+|[A-Z]{2,8}\d[A-Za-z\d-]*|(?![23][Dd])\d+[A-ZА-ЯЁ][A-Za-zА-ЯЁ\d]*|[А-ЯЁ]+\d[А-ЯЁ\d-]*(?:\.[a-zа-яё]{1,3})?)(?![A-Za-zА-Яа-яЁё0-9_])/gu;
  const drawingReferences = /(?<![A-Za-z0-9_])(?:2D|3D)(?![A-Za-z0-9_])/giu;
  const units = /(?<![A-Za-zΑ-Ωα-ωА-Яа-я_])(?:MPa|GPa|Pa|МПа|ГПа|mm|мм|μm|µm|um|мкм|N\/mm|N|Н|kg|g|min|h|HRC|HB|HV|Ra|Rz|°C|℃)(?![A-Za-zΑ-Ωα-ωА-Яа-я_])/gu;
  // Same bounded symbol grammar as technical_translation.py. Compound symbols
  // require formula context; natural language such as "load = 30 N" stays prose.
  const symbolBoundary = String.raw`A-Za-zΑ-Ωα-ωА-Яа-яЁё\d_ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ`;
  const symbolBody = String.raw`[A-Za-zΑ-Ωα-ω](?:[0-9₀-₉]+|_[A-Za-zΑ-Ωα-ω0-9₀-₉]{1,3}|[ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ]+|(?:min|max|nom|eff|tot|[hbdnt]))?\*?`;
  const variables = new RegExp(String.raw`(?<![${symbolBoundary}])(?:${symbolBody}(?![${symbolBoundary}])(?=\s*[=<>≤≥])|[A-Za-z][0-9₀-₉]+\*?(?![${symbolBoundary}])|III(?![A-Za-z\d_])|II(?![A-Za-z\d_])|IV(?![A-Za-z\d_]))`, "gu");
  const equations = new RegExp(String.raw`(?<![${symbolBoundary}])${symbolBody}(?![${symbolBoundary}])\s*[=<>≤≥]=?\s*(?:${symbolBody}(?![${symbolBoundary}])|\d+(?:[.,]\d+)?|[\s+−*/^().%±-])+`, "gu");
  const snapshot = (item) => ({ content: String(item?.content || "").trim(), type: String(item?.type || "other") });
  const same = (a, b) => a?.content === b?.content && a?.type === b?.type;
  function masked(content) {
    return String(content || "").replace(drawingReferences, " ").replace(standards, " ").replace(standardIdentifiers, " ").replace(codes, " ").replace(units, " ").replace(equations, " ").replace(variables, " ").replace(/(?<![A-Za-zΑ-Ωα-ω\d_])[A-Za-zΑ-Ωα-ω](?![A-Za-zΑ-Ωα-ω\d_])/gu, " ");
  }
  function needsTranslation(content) {
    if (/⟦ENG_/u.test(String(content || ""))) return true;
    const text = masked(content);
    return [...text].some((char) => /\p{L}/u.test(char) && !/[\u3400-\u9fff\u{20000}-\u{2fa1f}]/u.test(char));
  }
  function validResultText(content) {
    return typeof content === "string" && Boolean(content.trim()) && !/⟦ENG_/u.test(content);
  }
  function isCurrent(item) {
    return item?.translation_status === "translated" && validResultText(item.content)
      && (!item.translation_output_snapshot || same(item.translation_output_snapshot, snapshot(item)));
  }
  function blocksExport(item) {
    if (/⟦ENG_/u.test(String(item?.content || ""))) return true;
    if (isCurrent(item)) return false;
    return needsTranslation(item?.content)
      || (item?.translation_status === "failed" && (!item.translation_input_snapshot || same(item.translation_input_snapshot, snapshot(item))));
  }
  function warnings(item) {
    return [];
  }
  function canRecover(item) {
    const current = snapshot(item);
    return item?.translation_status === "failed" && String(item.translation_error || "").startsWith("译文仍包含外语说明")
      && Boolean(current.content) && same(item.translation_input_snapshot, current)
      && String(item.original_content || "").trim() === current.content && !needsTranslation(current.content);
  }
  const sessions = new WeakMap();
  const edits = new WeakMap();
  let hooks = {};
  let timer;
  const session = (review) => {
    if (!sessions.has(review)) sessions.set(review, { running: false, rerun: false, pending: new Map(), recoveryErrors: new Map(), checked: new Map(), previews: new Map() });
    return sessions.get(review);
  };
  function isPending(review, item) { return Boolean(review && session(review).pending.has(item.requirement_id)); }
  function pendingMode(review, item) { return review && session(review).pending.get(item.requirement_id); }
  function preview(review, item) {
    const stored = review && session(review).previews.get(item.requirement_id);
    return stored && stored.item === item && stored.edit === (edits.get(item) || 0) && same(stored.snapshot, snapshot(item)) ? stored.result : null;
  }
  function recoveryError(review, item) {
    const failure = review && session(review).recoveryErrors.get(item.requirement_id);
    return failure && same(failure.snapshot, snapshot(item)) ? failure.error : "";
  }
  function changed(item, { typeOnly = false } = {}) {
    edits.set(item, (edits.get(item) || 0) + 1);
    if (item.translation_status === "translated") {
      if (typeOnly || item.translation_output_snapshot?.content === snapshot(item).content) {
        // A type-only edit changes the snapshot, never triggers another translation.
        item.translation_output_snapshot = snapshot(item);
      } else {
        item.translation_status = "not_required";
        item.translation_output_snapshot = null;
      }
    }
  }
  function schedule() {
    clearTimeout(timer);
    const review = hooks.getReview?.();
    if (review && session(review).running) { session(review).rerun = true; return; }
    timer = setTimeout(() => { void run(); }, 0);
  }
  function apply(review, item, result) {
    const before = structuredClone(item);
    const recovered = ["automatic", "adopted"].includes(result.recovery_mode) || result.translation_status === "not_required";
    const keys = result.translation_status === "not_required" ? ["translation_status", "translation_error", "translation_input_snapshot", "translation_error_code", "translation_error_details", "translation_output_snapshot"]
      : ["content", "original_content", "source_language", "translation_status", "translation_error", "translation_source", "translation_input_snapshot", "translation_error_code", "translation_error_details", "translation_warnings", "translation_warning_snapshot", "translation_output_snapshot"];
    for (const key of keys) {
      if (Object.hasOwn(result, key)) item[key] = structuredClone(result[key]);
    }
    item.translation_warnings = [];
    item.translation_warning_snapshot = null;
    item.need_human_review = true;
    item.human_confirmed = false;
    delete item.confirmation_snapshot;
    if (!recovered) item.source = [...new Set([...(Array.isArray(item.source) ? item.source : [item.source].filter(Boolean)), "machine_translation"])];
    // Preserve raw_content: it records terminology normalization, not translation.
    if (item.type === "surface") {
      if (item.surface_mapping && typeof CompanySurfaceMapping !== "undefined" && result.translation_status === "translated") {
        const mode = item.surface_mapping.selection_mode;
        CompanySurfaceMapping.edited(item);
        item.surface_mapping.selection_mode = mode;
      }
      if (result.translation_status === "translated") item.standard_content = item.content;
      if (result.translation_status === "translated" || item.normalization_status === "human_confirmed") item.normalization_status = "needs_confirmation";
    }
    const index = review.technical_requirements.indexOf(item);
    const confirmations = review.manual_confirmations || {};
    for (const key of Object.keys(confirmations)) {
      if ([`technical_requirement_${item.requirement_id}`, `technical_requirements.${item.requirement_id}`, `technical_${index}`].includes(key)
        || confirmations[key]?.requirement_id === item.requirement_id) delete confirmations[key];
    }
    hooks.audit({ event_type: recovered ? "technical_requirement_translation_recovered" : result.translation_status === "translated" ? "technical_requirement_translated" : "technical_requirement_translation_failed",
      target_field: `technical_requirements.${item.requirement_id}`, source: recovered ? "translation_validation" : "machine_translation",
      reason: recovered ? "恢复已保存译文（仍需人工确认）" : "填入返回译文（仍需人工确认）",
      before_state: before, after_state: structuredClone(item), metadata: { requirement_id: item.requirement_id, translation_source: item.translation_source, translation_error: item.translation_error || "", translation_error_code: item.translation_error_code || "", translation_warnings: warnings(item), recovery_mode: result.recovery_mode } });
  }
  async function run(retryId = null, modeOverride = null) {
    const review = hooks.getReview?.(), jobId = hooks.getJobId?.();
    if (!review || !jobId || session(review).running) return false;
    const entry = session(review);
    const suppressed = new Set(typeof CompanySurfaceMapping !== "undefined" ? CompanySurfaceMapping.sourceLinks(review).suppressed_ids : []);
    const operation = (item) => {
      if (suppressed.has(item.requirement_id)) return null;
      if (!retryId && item.surface_mapping?.selection_mode === "auto" && item.surface_mapping?.conversion_status !== "converted") return null;
      if (isCurrent(item)) return null;
      if (retryId && item.requirement_id !== retryId) return null;
      if (retryId && modeOverride === "revalidate") return item.translation_status === "failed" ? "revalidate" : null;
      if (retryId) return needsTranslation(item.content) && !canRecover(item) ? "translate" : item.translation_status === "failed" ? "revalidate" : null;
      if (item.translation_status === "failed" && (!item.translation_input_snapshot || same(item.translation_input_snapshot, snapshot(item)))) {
        const checked = entry.checked.get(item.requirement_id);
        return checked && same(checked.snapshot, snapshot(item)) && checked.edit === (edits.get(item) || 0) ? null : "revalidate";
      }
      return needsTranslation(item.content) ? "translate" : null;
    };
    const eligible = (item) => Boolean(operation(item));
    if (!(review.technical_requirements || []).some(eligible)) return false;
    entry.running = true;
    entry.rerun = false;
    const active = () => hooks.getReview() === review && hooks.getJobId() === jobId;
    let saved = false;
    let completedCheck = false;
    let requested = [];
    try {
      // Never translate unsaved drafts or proceed through an unresolved 409.
      if (!await hooks.save() || !active()) return false;
      if (hooks.canTranslate && !hooks.canTranslate()) return false;
      requested = (review.technical_requirements || []).filter(eligible).slice(0, 50).map((item) => ({ item, edit: edits.get(item) || 0,
        requirement_id: item.requirement_id, source_snapshot: snapshot(item), mode: operation(item) }));
      if (!requested.length) return false;
      requested.forEach((row) => {
        entry.pending.set(row.requirement_id, row.mode);
        if (row.mode === "revalidate") entry.checked.set(row.requirement_id, { snapshot: row.source_snapshot, edit: row.edit });
      });
      hooks.update(false);
      const results = [];
      for (const mode of ["revalidate", "translate"]) {
        const batch = requested.filter((row) => row.mode === mode);
        if (!batch.length) continue;
        try {
          const response = await hooks.fetch(`/api/reviews/${encodeURIComponent(jobId)}/technical-requirements/translate`, {
          method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode, requirements: batch.map(({ requirement_id, source_snapshot }) => ({ requirement_id, source_snapshot })) }),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "翻译服务请求失败，请重试。");
          results.push(...(Array.isArray(payload.requirements) ? payload.requirements : []));
        } catch (error) {
          results.push(...batch.map((row) => ({ requirement_id: row.requirement_id, source_snapshot: row.source_snapshot, content: row.source_snapshot.content,
          original_content: row.source_snapshot.content, source_language: row.item.source_language || "unknown", translation_status: "failed",
            translation_error_details: same(row.item.translation_input_snapshot, row.source_snapshot)
              && typeof row.item.translation_error_details?.candidate_content === "string"
              && !/⟦ENG_/u.test(row.item.translation_error_details.candidate_content)
              ? { candidate_content: row.item.translation_error_details.candidate_content } : {},
            translation_error: error.message || "网络不可用，请重试。", translation_error_code: "request_failed", translation_source: "request_failed", translation_input_snapshot: row.source_snapshot })));
        }
      }
      if (!active()) return false;
      let applied = 0;
      for (const row of requested) {
        const matches = results.filter((r) => r.requirement_id === row.requirement_id);
        const result = matches.length === 1 && ["not_required", "translated", "failed"].includes(matches[0].translation_status) ? matches[0] : { requirement_id: row.requirement_id, source_snapshot: row.source_snapshot,
          content: row.source_snapshot.content, original_content: row.source_snapshot.content, translation_status: "failed", translation_error: "翻译返回条目不完整，请重试。",
          translation_error_code: "invalid_response", translation_error_details: {},
          translation_input_snapshot: row.source_snapshot, translation_source: "invalid_response" };
        if (!review.technical_requirements.includes(row.item) || (edits.get(row.item) || 0) !== row.edit || !same(snapshot(row.item), row.source_snapshot)
          || !same(result.source_snapshot, row.source_snapshot)) continue;
        if (row.mode === "revalidate" && result.recovery_mode === "preview") {
          entry.previews.set(row.requirement_id, { item: row.item, snapshot: row.source_snapshot, edit: row.edit, result });
          continue;
        }
        if (row.mode === "revalidate" && result.translation_status === "failed") {
          entry.recoveryErrors.set(row.requirement_id, { snapshot: row.source_snapshot, error: result.translation_error || row.item.translation_error });
          entry.previews.set(row.requirement_id, { item: row.item, snapshot: row.source_snapshot, edit: row.edit, result });
          continue;
        }
        if (row.mode === "revalidate" && !canRecover(row.item) && result.recovery_mode !== "automatic") {
          entry.recoveryErrors.set(row.requirement_id, { snapshot: row.source_snapshot, error: "已有译文检查返回无效，请重新检查。" });
          continue;
        }
        if (canRecover(row.item)) {
          if (result.translation_status !== "not_required" || result.content !== row.item.content
            || result.translation_error || !same(result.translation_input_snapshot, row.source_snapshot)) {
            entry.recoveryErrors.set(row.requirement_id, { snapshot: row.source_snapshot, error: result.translation_error || "翻译状态检查失败，请重试。" });
            continue;
          }
          entry.recoveryErrors.delete(row.requirement_id);
        } else if (result.translation_status === "not_required") {
          // A foreign note may never be cleared by an inconsistent response.
          result.translation_status = "failed";
          result.content = row.source_snapshot.content;
          result.translation_error = "翻译返回状态与当前文本不一致，请重试。";
          result.translation_error_code = "invalid_response";
          result.translation_error_details = {};
          result.translation_input_snapshot = row.source_snapshot;
        }
        if (result.translation_status === "translated" && !validResultText(result.content)) {
          result.translation_status = "failed";
          result.translation_error_details = {};
          result.content = row.source_snapshot.content;
          result.translation_error = "翻译返回空内容或无法还原的占位符，请重试。";
          result.translation_error_code = "invalid_response";
          result.translation_input_snapshot = row.source_snapshot;
          result.translation_warnings = [];
          result.translation_warning_snapshot = null;
        }
        result.translation_output_snapshot = result.translation_status === "translated"
          ? { content: result.content.trim(), type: row.source_snapshot.type } : null;
        apply(review, row.item, result);
        if (result.translation_status === "failed") entry.checked.set(row.requirement_id, { snapshot: snapshot(row.item), edit: row.edit });
        entry.previews.delete(row.requirement_id);
        entry.recoveryErrors.delete(row.requirement_id);
        applied++;
      }
      entry.pending.clear();
      if (applied) {
        hooks.update(true);
        saved = await hooks.save();
        if (active()) hooks.update(false);
      }
      completedCheck = !applied && requested.every((row) => row.mode === "revalidate");
      return saved;
    } finally {
      entry.running = false;
      entry.pending.clear();
      if (active()) hooks.update(false);
      // A new text entered during translation is a new draft, not an automatic
      // retry of a failed identical input. Failed saves remain for explicit retry.
      if ((saved || entry.rerun || completedCheck) && active() && (!hooks.canTranslate || hooks.canTranslate()) && (review.technical_requirements || []).some(eligible)) schedule();
    }
  }
  async function adoptCandidate(id, index) {
    const review = hooks.getReview?.(), jobId = hooks.getJobId?.();
    if (!review || !jobId || session(review).running) return false;
    const item = review.technical_requirements.find((note) => note.requirement_id === id);
    const stored = item && preview(review, item);
    const candidate = stored?.translation_candidates?.[index];
    if (!candidate || !validResultText(candidate.content)) return false;
    const before = snapshot(item), edit = edits.get(item) || 0;
    const entry = session(review);
    entry.running = true;
    try {
      if (!await hooks.save() || (hooks.canTranslate && !hooks.canTranslate()) || hooks.getReview() !== review || hooks.getJobId() !== jobId
        || !review.technical_requirements.includes(item) || edit !== (edits.get(item) || 0)
        || !same(before, snapshot(item)) || preview(review, item) !== stored) return false;
      apply(review, item, { ...candidate, requirement_id: id, source_snapshot: before, translation_input_snapshot: before,
        translation_status: "translated", translation_error: "", translation_error_code: "", translation_error_details: {}, recovery_mode: "adopted",
        translation_warnings: [], translation_warning_snapshot: null,
        translation_output_snapshot: { content: candidate.content.trim(), type: item.type || "other" } });
      entry.previews.delete(id);
      entry.recoveryErrors.delete(id);
      hooks.update(true);
      return await hooks.save();
    } finally {
      entry.running = false;
      if (hooks.getReview() === review && hooks.getJobId() === jobId) hooks.update(false);
    }
  }
  window.TechnicalRequirementTranslation = { configure: (value) => {
    hooks = value;
    for (const item of hooks.getReview?.()?.technical_requirements || []) {
      if (isCurrent(item) && !item.translation_output_snapshot) item.translation_output_snapshot = snapshot(item);
    }
  }, needsTranslation, blocksExport, warnings, isCurrent, canRecover, recoveryError, snapshot, same, isPending, pendingMode, preview, adoptCandidate, changed, schedule, run };
})();
