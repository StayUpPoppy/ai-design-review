/* Optional project reference, never an inferred drawing value or a confirmation. */
(() => {
  const source = "human_roughness_reference";
  const referenceValues = [12.5, 6.3];
  const expandedEvidence = new WeakMap();
  const sources = (item) => (Array.isArray(item?.source) ? item.source : [item?.source]).filter(Boolean);
  const empty = (item) => item?.value == null || typeof item.value === "string" && !item.value.trim();
  const manual = (item) => Boolean(item?.human_modified) || sources(item).some((s) =>
    String(s).startsWith("human") || ["manual", "manual_input", "standardization_chat", "ai_chat"].includes(s));
  function eligible(item) {
    const unit = String(item?.unit || "μm").trim().toLowerCase().replace(/µ/g, "μ");
    return Boolean(item && ["μm", "um"].includes(unit) && empty(item) && !item.roughness_conflict && !item.derived_value_stale
      && !item.formula_recommendation_stale && !(item.roughness_candidates || []).length);
  }
  const dismissed = (item) => item?.roughness_reference_dismissed === true || empty(item) && manual(item);
  const adopted = (item) => sources(item).includes(source);
  function removeConfirmation(item) {
    item.need_human_review = true;
    delete item.confirmation_snapshot;
    item.source = ["human_edited", ...sources(item).filter((s) => ![source, "human_confirmed", "human_edited"].includes(s))];
  }
  function adopt(item, value = 12.5) {
    if (!eligible(item) || !referenceValues.includes(value)) return false;
    removeConfirmation(item);
    Object.assign(item, { value, unit: "μm", surface_location: "两端面", roughness_reference_dismissed: false });
    item.source.push(source);
    return true;
  }
  function dismiss(item) {
    if (!eligible(item)) return false;
    removeConfirmation(item);
    item.value = null;
    item.roughness_reference_dismissed = true;
    return true;
  }
  function edited(item) {
    // Returning to an old reference value must not silently restore its confirmation.
    if (adopted(item)) {
      delete item.confirmation_snapshot;
      item.source = sources(item).filter((s) => s !== source);
    }
    item.roughness_reference_dismissed = empty(item);
  }
  const speculation = /可能|也许|大概|猜测|推测|怀疑|似乎|不确定|无法确认|看不清|假设|例如|比如|举例|推荐|建议|默认|常规|参考|possibly|perhaps|example|recommend|default/iu;
  const negation = /(?:未|没有|无|并无|不含|不存在|未见|不要求|无需|不需要|不涉及).{0,12}(?:粗糙度|Ra|标注)|(?:不是|并非|不属于|不作为|不应作为).{0,8}(?:粗糙度|Ra)|(?:粗糙度|Ra).{0,8}(?:未标注|没有标注|不要求|未出现|没有出现|不适用)|not\s+(?:roughness|Ra)|no\s+(?:roughness|Ra)/iu;
  const discussion = /need_human_review|surface_roughness_ra|我们|我再|再看|再确认|无法辨认|无法确定/iu;
  const positive = (value) => {
    const text = String(value ?? "").trim().replace(",", ".");
    return typeof value !== "boolean" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/iu.test(text) && Number.isFinite(Number(text)) && Number(text) > 0;
  };
  function assessEvidence(value, evidence, structured = false) {
    const text = String(evidence || "").trim(), statuses = [];
    const patterns = [/(?<![A-Za-z])Ra\s*[:：=]?\s*(\d+(?:[.,]\d+)?)/giu, /(?:表面)?粗糙度\s*(?:Ra\s*)?[:：=]?\s*(\d+(?:[.,]\d+)?)/giu, /[▽△▼]\s*(\d+(?:[.,]\d+)?)/gu];
    for (const pattern of patterns) for (const match of text.matchAll(pattern)) {
      if (!positive(value) || Number(match[1].replace(",", ".")) !== Number(String(value).replace(",", "."))) continue;
      const edges = [...text.matchAll(/[。；;\n|，]|(?<!\d),|,(?!\d)|而是|实际为/gu)];
      const start = Math.max(0, ...edges.filter((edge) => edge.index + edge[0].length <= match.index).map((edge) => edge.index + edge[0].length));
      const end = Math.min(text.length, ...edges.filter((edge) => edge.index >= match.index + match[0].length).map((edge) => edge.index));
      const clause = text.slice(start, end);
      if (negation.test(clause)) statuses.push(["excluded", "该数值所在语句否定了粗糙度标注，不作为原图候选。"]);
      else if (speculation.test(clause)) statuses.push(["excluded", "该数值来自推测、举例或参考说明，不作为原图候选。"]);
      else if (clause.length > 160 || discussion.test(text) || text.length > 240) statuses.push(["unverified", "依据包含长篇解释，尚不能证明是原图明确标注。"]);
      else statuses.push(["direct", "包含与候选一致的明确粗糙度文字或符号。"]);
    }
    return statuses.find(([status]) => status === "direct") || statuses.find(([status]) => status === "unverified") || statuses[0]
      || (structured && positive(value) && positive(text) && Number(String(value).replace(",", ".")) === Number(text.replace(",", "."))
        ? ["direct", "粗糙度结构化字段保留了对应原图数值。"] : ["unverified", "缺少与候选一致的原图粗糙度文字或符号，请核对。"]);
  }
  function candidateEvidence(candidate) {
    if (["direct", "unverified"].includes(candidate?.evidence_status)) return [candidate.evidence_status, String(candidate.evidence_reason || "")];
    const [status, reason] = assessEvidence(candidate?.value, candidate?.evidence, true);
    return [status === "excluded" ? "unverified" : status, reason]; // Old records are never removed on read.
  }
  function summary(item) {
    if (adopted(item)) return `人工采用项目参考 · 两端面 · ${item.need_human_review ? "待确认" : "已确认"}`;
    if (manual(item) && (item.human_modified || !sources(item).every((s) => s === "human_confirmed"))) return empty(item) ? "已选择不添加粗糙度" : `人工填写 · ${item.need_human_review ? "待确认" : "已确认"}`;
    if (item?.derived_value_stale || item?.formula_recommendation_stale) return "原值已失效，请核对";
    if (item?.roughness_conflict) return "存在多个候选，请核对";
    const candidates = item?.roughness_candidates || [];
    if (candidates.length && candidates.every((candidate) => candidateEvidence(candidate)[0] !== "direct")) return "候选依据不足，请核对";
    if (!empty(item)) return "已有识别值，请核对原图依据";
    return candidates.length ? "存在识别候选，请核对" : "未识别到粗糙度";
  }
  function evidenceEntries(item) {
    const entries = new Map();
    function add(text, metadata = {}, candidate = null) {
      text = String(text || "").trim();
      if (!text) return;
      if (!entries.has(text)) entries.set(text, { text, sources: [], pages: [], labels: [], reasons: [] });
      const entry = entries.get(text);
      for (const source of sources(metadata)) if (!entry.sources.includes(source)) entry.sources.push(source);
      if (metadata.page != null && !entry.pages.includes(metadata.page)) entry.pages.push(metadata.page);
      if (candidate) {
        const label = `Ra ${candidate.value} μm · ${candidate.location || "部位未明确"}`;
        if (!entry.labels.includes(label)) entry.labels.push(label);
        const [, reason] = candidateEvidence(candidate);
        if (reason && !entry.reasons.includes(reason)) entry.reasons.push(reason);
      }
    }
    for (const candidate of item?.roughness_candidates || []) {
      if (candidate.evidence_records?.length) candidate.evidence_records.forEach((record) => add(record.evidence, record, candidate));
      else add(candidate.evidence, candidate, candidate);
    }
    for (const text of String(item?.evidence || "").split(" | ")) add(text, item);
    return [...entries.values()];
  }
  globalThis.SurfaceRoughnessReference = { eligible, dismissed, adopted, adopt, dismiss, edited, referenceValues,
    assessEvidence, candidateEvidence, summary, evidenceEntries,
    evidenceOpen: (item) => expandedEvidence.get(item) === true,
    setEvidenceOpen: (item, open) => expandedEvidence.set(item, Boolean(open)) };
})();
