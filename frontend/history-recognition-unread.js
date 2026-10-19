(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HistoryRecognitionUnread = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // Read receipts are separate, immutable keys. A stale tab can update a job's
  // progress, but can never overwrite another tab's receipt for the same round.
  function create({ service, userId, storage, onChange = () => {}, eventTarget } = {}) {
    const prefix = `aiDesignReview:recognition-unread:v1:${encodeURIComponent(String(service || "").replace(/\/+$/, ""))}:${encodeURIComponent(String(userId || ""))}:`;
    const memory = new Map();
    let persistent = storage;
    if (persistent === undefined) {
      try { persistent = globalThis.localStorage; } catch { persistent = null; }
    }
    const read = (key) => {
      try {
        const value = persistent?.getItem(prefix + key);
        if (value != null) memory.set(key, value);
      } catch { persistent = null; }
      return memory.get(key) ?? null;
    };
    const write = (key, value) => {
      if (read(key) === value) return;
      memory.set(key, value);
      try { persistent?.setItem(prefix + key, value); } catch { persistent = null; }
    };
    const jobKey = (id) => `job:${encodeURIComponent(id)}`;
    const deleted = (id) => read(`deleted:${encodeURIComponent(id)}`) === "1";
    const receipt = (id, round) => `read:${encodeURIComponent(id)}:${encodeURIComponent(round)}`;
    const record = (id) => {
      try {
        const data = JSON.parse(read(jobKey(id)) || "null");
        return data && typeof data.round === "string" && ["queued", "processing", "completed", "failed"].includes(data.phase) ? data : null;
      } catch { return null; }
    };
    let sequence = 0;
    const localRound = () => `local:${Date.now()}:${Math.random().toString(36).slice(2)}:${++sequence}`;
    const attemptOf = (item) => {
      const value = item.recognition_attempt_count;
      return (typeof value === "number" || typeof value === "string") && String(value).trim() !== ""
        && Number.isInteger(Number(value)) && Number(value) >= 0 ? Number(value) : null;
    };

    function observe(item, { baseline = false, submission = false, restart = false } = {}) {
      const id = item?.job_id;
      if (!id || deleted(id)) return;
      const phase = item.recognition_status || "completed";
      if (!["queued", "processing", "completed", "failed"].includes(phase)) return;
      const previous = record(id), attempt = attemptOf(item);
      const time = Date.parse(item.updated_at);
      if (previous && !restart) {
        if (attempt != null && previous.attempt != null && attempt < previous.attempt) return;
        if (!(attempt != null && (previous.attempt == null || attempt > previous.attempt))) {
          if (Number.isFinite(time) && previous.time != null && time < previous.time) return;
          // Retrying enqueues the old attempt counter; the worker increments it
          // when claiming the next round. Its old completion is not a new result.
          if (phase === "completed" && previous.minimumAttempt != null && attempt != null && attempt < previous.minimumAttempt) return;
          if (["completed", "failed"].includes(previous.phase) && ["queued", "processing"].includes(phase)
              && !(Number.isFinite(time) && previous.time != null && time > previous.time)) return;
        }
      }
      const active = ["queued", "processing"].includes(phase);
      const newAttempt = attempt != null && (!previous || previous.attempt !== attempt);
      const startsRound = restart || (previous && !["queued", "processing"].includes(previous.phase) && active);
      let round = previous?.round || (attempt == null ? localRound() : `attempt:${attempt}`);
      // A fast upload may complete before its receipt exposes attempt_count.
      // Learning the counter later identifies that same completion; it must not
      // relight a result that has already been displayed and acknowledged.
      if (newAttempt && !(previous?.attempt == null && previous?.phase === "completed" && !startsRound)) round = `attempt:${attempt}`;
      if (startsRound) round = localRound();
      const next = { phase, attempt: attempt ?? previous?.attempt ?? null, round,
        time: Number.isFinite(time) ? time : previous?.time ?? null,
        minimumAttempt: restart && attempt != null ? attempt + 1 : previous?.minimumAttempt ?? null };
      if (newAttempt && !restart) next.minimumAttempt = null;
      write(jobKey(id), JSON.stringify(next));
      // Unknown legacy results have no reliable recognition-round identity.
      // Existing completions are a baseline, except jobs already tracked active
      // (including submissions observed before the first list arrives).
      if (phase === "completed" && !previous && !submission && (baseline || attempt == null)) markRead(id, round);
      return round;
    }

    function observeList(items) {
      const baseline = read("baseline") !== "1";
      for (const item of items) observe(item, { baseline });
      write("baseline", "1");
    }
    function capture(item) {
      if (!item || (item.recognition_status && item.recognition_status !== "completed") || deleted(item.job_id)) return null;
      const saved = record(item.job_id), attempt = attemptOf(item);
      if (!saved || saved.phase !== "completed" || (attempt != null && saved.attempt !== attempt)) return null;
      return saved.round;
    }
    function markRead(id, round) {
      if (id && round && !deleted(id)) write(receipt(id, round), "1");
    }
    function isUnread(item) {
      const round = capture(item);
      return Boolean(round && read(receipt(item.job_id, round)) !== "1");
    }
    function remove(id) { write(`deleted:${encodeURIComponent(id)}`, "1"); }
    function trackedIds() {
      // Enumerate per-job keys so tasks outside the current 100-row history
      // window continue polling after a browser restart as well.
      try {
        for (let index = 0; persistent && index < persistent.length; index += 1) {
          const key = persistent.key(index);
          if (key?.startsWith(prefix + "job:")) read(key.slice(prefix.length));
        }
      } catch { persistent = null; }
      return [...memory.keys()].filter((key) => key.startsWith("job:")).map((key) => decodeURIComponent(key.slice(4)))
        .filter((id) => !deleted(id) && ["queued", "processing"].includes(record(id)?.phase));
    }
    const listener = (event) => {
      if (event.key == null || event.key.startsWith(prefix)) {
        if (event.key?.startsWith(prefix) && event.newValue != null) memory.set(event.key.slice(prefix.length), event.newValue);
        onChange();
      }
    };
    eventTarget?.addEventListener("storage", listener);
    return { observe, observeList, capture, markRead, isUnread, remove, trackedIds,
      dispose: () => eventTarget?.removeEventListener("storage", listener) };
  }
  return { create };
});
