(function (root) {
  "use strict";
  const MAX_FILES = 50;
  const extensions = /\.(pdf|png|jpe?g|tiff?|bmp|webp)$/i;
  const waiting = new Set(["pending", "upload_failed", "unknown"]);
  const activeStates = new Set(["queued", "processing", "cancel_requested"]);
  const terminalStates = new Set(["completed", "failed", "cancelled", "deleted"]);
  const supported = (file) => Boolean(file && extensions.test(file.name || ""));
  const pathText = (path) => String(path || "").replace(/\\/g, "/").replace(/^\/+/, "");
  const yieldUi = () => new Promise((resolve) => setTimeout(resolve, 0));

  // Capture entries/files before returning from drop: DataTransfer then becomes protected.
  function snapshotDrop(transfer) {
    const roots = Array.from(transfer?.items || []).filter((item) => item.kind === "file").map((item) => {
      try {
        const entry = item.webkitGetAsEntry?.() || item.getAsEntry?.();
        if (entry) return { entry };
        if (item.getAsFileSystemHandle) return {
          handle: item.getAsFileSystemHandle().then((handle) => ({ handle }), (error) => ({ error })),
        };
        const file = item.getAsFile?.();
        return file ? { file, fallback: true } : { error: new Error("无法读取拖入项目；文件夹请改用“选择文件夹”。") };
      } catch (error) { return { error }; }
    });
    if (!roots.length) for (const file of Array.from(transfer?.files || [])) roots.push({ file, fallback: true });
    return roots;
  }

  function create(options = {}) {
    let serial = 0, epoch = 0, batch = null, batchSerial = 0;
    const queue = {
      entries: [], scans: new Map(), running: false, notice: "",
      seenKeys: new Set(), knownJobs: new Map(), trackedJobs: new Map(), batches: new Map(),
      latestBatchId: null, completionHidden: true, pendingRevision: 0,
      get scanning() { return this.scans.size > 0; },
      get discovered() { return Array.from(this.scans.values()).reduce((sum, count) => sum + count, 0); },
      get unsubmitted() { return this.entries.filter((item) => item.valid && !item.jobId && waiting.has(item.status)); },
      get pending() { return this.entries.filter((item) => item.status === "pending"); },
      get tooMany() { return this.unsubmitted.length > MAX_FILES; },
      get hasUnsent() { return this.scanning || this.running || this.unsubmitted.length > 0; },
      get resumable() { return Boolean(batch && batch.ids.some((id) => this.entries.some((item) => item.id === id && item.status === "pending"))); },
      get completion() {
        const latest = this.batches.get(this.latestBatchId);
        if (this.completionHidden || !latest?.states.size) return null;
        const states = Array.from(latest.states.values());
        if (!states.every((status) => terminalStates.has(status))) return null;
        return { batchId: latest.id, total: states.length, completed: states.filter((status) => status === "completed").length,
          failed: states.filter((status) => status === "failed").length,
          cancelled: states.filter((status) => ["cancelled", "deleted"].includes(status)).length };
      },
      changed() { options.onChange?.(this); },
      hasJob(jobId) { return this.knownJobs.has(jobId); },
      isTracking(jobId) { return this.trackedJobs.has(jobId); },
      recordStatus(item) { this.batches.get(item.batchId)?.states.set(item.id, item.status); },
      pruneBatches() {
        for (const [id, record] of this.batches) {
          if (id !== this.latestBatchId && Array.from(record.states.values()).every((status) => terminalStates.has(status))) this.batches.delete(id);
        }
      },
      dismissCompletion() {
        this.completionHidden = true;
        if (!this.entries.length && !this.scanning && !this.running) this.notice = "";
        this.changed();
      },
      add(file, path, scanId, scanEpoch, fallback = false) {
        if (epoch !== scanEpoch) return;
        const normalizedPath = pathText(path || file.name);
        const key = JSON.stringify([normalizedPath, file.name, file.size, file.lastModified]);
        if (this.seenKeys.has(key)) {
          this.notice = "已跳过重复选择的同一路径文件；不同文件夹的同名文件分别保留。";
          return;
        }
        let error = !supported(file) ? "不支持的格式，请选择 PDF、PNG、JPG、TIFF、BMP 或 WEBP。" : "";
        if (!supported(file) && fallback && !file.type && !file.size) error = "无法读取目录或不支持的文件；文件夹请改用“选择文件夹”。";
        if (supported(file) && !file.size) error = "文件为空，无法识别。";
        this.seenKeys.add(key);
        this.entries.push({ id: `upload-${++serial}`, key, name: file.name, path: normalizedPath,
          size: file.size, file: error ? null : file, valid: !error, status: error ? "invalid" : "pending", error, jobId: null });
        if (!error) { this.pendingRevision++; this.completionHidden = true; }
        this.scans.set(scanId, (this.scans.get(scanId) || 0) + 1); this.changed();
      },
      problem(path, error, scanEpoch) {
        if (epoch !== scanEpoch) return;
        this.entries.push({ id: `upload-${++serial}`, name: pathText(path) || "拖入项目", path: pathText(path),
          size: null, valid: false, status: "invalid", file: null, jobId: null, error: String(error || "读取失败，请重新选择文件夹。") });
        this.changed();
      },
      async collect(reader) {
        const scanId = ++serial, scanEpoch = epoch;
        this.scans.set(scanId, 0); this.changed();
        const context = {
          active: () => epoch === scanEpoch,
          add: (file, path, fallback) => this.add(file, path, scanId, scanEpoch, fallback),
          problem: (path, error) => this.problem(path, error, scanEpoch),
        };
        try { await reader(context); }
        catch (error) { context.problem("文件夹", `读取失败：${error.message || error}。请重新选择文件夹。`); }
        finally { this.scans.delete(scanId); this.changed(); }
      },
      collectFiles(files) {
        const captured = Array.from(files || []);
        return this.collect(async (context) => {
          if (!captured.length) context.problem("所选文件夹", "未找到文件，文件夹可能为空或已取消选择。");
          for (let index = 0; index < captured.length && context.active(); index++) {
            const file = captured[index]; context.add(file, file.webkitRelativePath || file.name);
            if (index % 32 === 31) await yieldUi();
          }
        });
      },
      collectDrop(roots) {
        return this.collect(async (context) => {
          const visitEntry = async (entry, parent = "") => {
            if (!context.active()) return;
            const path = `${parent}${entry.name}`;
            try {
              if (entry.isFile) {
                const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
                if (context.active()) context.add(file, path);
              } else if (entry.isDirectory) {
                const reader = entry.createReader(); let count = 0;
                while (context.active()) {
                  const children = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
                  if (!children.length) break;
                  count += children.length;
                  children.sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
                  for (const child of children) { if (!context.active()) return; await visitEntry(child, `${path}/`); }
                }
                if (!count) context.problem(path, "空文件夹，未找到可上传文件。");
              } else context.problem(path, "无法读取目录；请改用“选择文件夹”。");
            } catch (error) { context.problem(path, `读取失败：${error.message || error}。请重新选择此项目。`); }
          };
          const visitHandle = async (handle, parent = "") => {
            if (!context.active()) return;
            const path = `${parent}${handle.name}`;
            try {
              if (handle.kind === "file") context.add(await handle.getFile(), path);
              else if (handle.kind === "directory") {
                let count = 0;
                for await (const child of handle.values()) {
                  if (!context.active()) return;
                  count++; await visitHandle(child, `${path}/`);
                }
                if (!count) context.problem(path, "空文件夹，未找到可上传文件。");
              } else context.problem(path, "无法读取目录；请改用“选择文件夹”。");
            } catch (error) { context.problem(path, `读取失败：${error.message || error}。请重新选择此项目。`); }
          };
          if (!roots.length) context.problem("拖入项目", "无法读取拖入项目；请改用选择文件或选择文件夹。");
          for (const root of roots) {
            if (!context.active()) break;
            if (root.entry) await visitEntry(root.entry);
            else if (root.handle) {
              const resolved = await root.handle;
              if (!context.active()) break;
              if (resolved.handle) await visitHandle(resolved.handle);
              else context.problem("拖入项目", resolved.error?.message || "无法读取目录；请改用“选择文件夹”。");
            } else if (root.file) context.add(root.file, root.file.webkitRelativePath || root.file.name, root.fallback);
            else context.problem("拖入项目", root.error?.message);
          }
        });
      },
      remove(id) {
        const item = this.entries.find((entry) => entry.id === id);
        if (!item || item.jobId || item.status === "uploading") return;
        this.seenKeys.delete(item.key); this.batches.get(item.batchId)?.states.delete(item.id);
        this.entries = this.entries.filter((entry) => entry !== item); this.pruneBatches(); this.changed();
      },
      clearPending() {
        epoch++; this.scans.clear(); this.notice = "";
        for (const item of this.entries.filter((entry) => !entry.jobId && entry.status !== "uploading")) {
          this.seenKeys.delete(item.key); this.batches.get(item.batchId)?.states.delete(item.id);
        }
        this.entries = this.entries.filter((item) => item.jobId || item.status === "uploading"); this.changed();
      },
      stop() {
        if (batch) batch.stopped = true;
        this.notice = "当前上传结束后暂停，已入队任务继续识别。"; this.changed();
      },
      async run(snapshot) {
        if (this.running || this.scanning || this.tooMany || !this.pending.length) return false;
        if (!this.resumable) {
          const pending = this.pending;
          const fresh = pending.filter((item) => !item.batchId);
          if (fresh.length) {
            const id = `batch-${++batchSerial}`;
            this.batches.set(id, { id, states: new Map() });
            for (const item of fresh) { item.batchId = id; this.recordStatus(item); }
            this.latestBatchId = id; this.completionHidden = false; this.pruneBatches();
          }
          batch = { ids: pending.map((item) => item.id), options: structuredClone(snapshot), stopped: false };
        }
        batch.stopped = false;
        const activeBatch = batch;
        this.running = true; this.notice = ""; this.changed();
        try {
          for (const id of activeBatch.ids) {
            if (activeBatch.stopped) break;
            const item = this.entries.find((entry) => entry.id === id);
            if (!item || item.status !== "pending") continue;
            if (options.canUpload && !options.canUpload(item.options || activeBatch.options)) {
              this.notice = "登录身份或服务地址已变化，后续上传已暂停；请恢复原登录及服务后继续。"; break;
            }
            item.status = "uploading"; item.error = ""; item.options ||= activeBatch.options;
            this.recordStatus(item); this.changed();
            let payload;
            try {
              payload = await options.upload(item, item.options);
              if (!payload || typeof payload.job_id !== "string" || !payload.job_id.trim()
                  || !["queued", "processing", "completed", "failed"].includes(payload.recognition_status)) {
                throw Object.assign(new Error("上传返回无效，结果未知；请先核对历史订单。"), { uncertain: true });
              }
            } catch (error) {
              item.status = error.uncertain ? "unknown" : "upload_failed";
              this.recordStatus(item);
              item.error = error.message || "上传失败，请重试。";
              if (error.auth || error.uncertain) {
                activeBatch.stopped = true;
                this.notice = error.auth ? "登录已失效或无上传权限，后续上传已暂停。" : "上传结果未知，后续上传已暂停；请先核对历史订单。";
              }
              this.changed(); continue;
            }
            item.jobId = payload.job_id; item.status = payload.recognition_status;
            item.progress = payload.recognition_progress; item.file = null;
            this.knownJobs.set(item.jobId, { id: item.id, batchId: item.batchId });
            if (activeStates.has(item.status)) this.trackedJobs.set(item.jobId, item);
            this.recordStatus(item); this.changed();
            try { await options.onAccepted?.(item, payload, activeBatch); }
            catch (error) {
              item.syncError = `已入队，界面同步失败：${error.message || error}；请刷新历史订单。`;
              this.notice = item.syncError;
            }
            if (terminalStates.has(item.status)) {
              this.entries = this.entries.filter((entry) => entry !== item);
              this.trackedJobs.delete(item.jobId); this.pruneBatches();
            }
          }
        } finally {
          this.running = false;
          if (!this.resumable) batch = null;
          if (!this.unsubmitted.length && this.notice === "当前上传结束后暂停，已入队任务继续识别。") this.notice = "";
          this.pruneBatches();
          this.changed();
        }
        return true;
      },
      retryUpload(id) {
        if (this.running || this.scanning) return;
        const item = this.entries.find((entry) => entry.id === id);
        if (!item || !["upload_failed", "unknown"].includes(item.status)) return;
        if (item.status === "unknown" && !item.checkedUnknown) return;
        item.status = "pending"; item.error = ""; this.pendingRevision++;
        this.recordStatus(item); this.changed();
      },
      updateRecognition(jobId, recognition) {
        const known = this.knownJobs.get(jobId);
        if (!known) return;
        const status = recognition.recognition_status || recognition.status;
        if (!activeStates.has(status) && !terminalStates.has(status)) return;
        let item = this.trackedJobs.get(jobId);
        if (!item) item = this.entries.find((entry) => entry.jobId === jobId);
        if (!item) item = { ...known, jobId, name: recognition.drawing_name || jobId, path: "", size: null, file: null, valid: true };
        item.status = status;
        if ("recognition_progress" in recognition) item.progress = recognition.recognition_progress;
        else if ("progress" in recognition) item.progress = recognition.progress;
        item.error = recognition.recognition_error || recognition.error_message || "";
        item.syncError = recognition.recognition_sync_error || "";
        this.recordStatus(item);
        if (activeStates.has(status)) {
          this.trackedJobs.set(jobId, item);
          if (!this.entries.some((entry) => entry.jobId === jobId)) this.entries.push(item);
        } else {
          this.trackedJobs.delete(jobId);
          this.entries = this.entries.filter((entry) => entry.jobId !== jobId);
          this.pruneBatches();
        }
        this.changed();
      },
      markDeleted(jobId) {
        const known = this.knownJobs.get(jobId);
        if (known) this.recordStatus({ ...known, status: "deleted" });
        this.knownJobs.delete(jobId); this.trackedJobs.delete(jobId);
        this.entries = this.entries.filter((entry) => entry.jobId !== jobId);
        this.pruneBatches(); this.changed();
      },
    };
    return queue;
  }
  function statusText(item) {
    const labels = { pending: "待上传", uploading: "上传中", queued: "排队中", processing: "识别中", completed: "识别完成",
      failed: "识别失败", upload_failed: "上传失败", unknown: "结果待核对", invalid: "未加入识别", cancelled: "已取消", cancel_requested: "正在取消", deleted: "已删除" };
    const value = item.progress;
    const numeric = (typeof value === "number" || (typeof value === "string" && value.trim())) && Number.isFinite(Number(value));
    return `${labels[item.status] || "待核对"}${item.status === "processing" && numeric ? ` ${Math.min(99, Math.max(0, Math.floor(Number(value))))}%` : ""}`;
  }
  function formatBytes(size) {
    if (size == null) return "";
    return size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`;
  }
  root.DrawingUploadQueue = { create, supported, snapshotDrop, statusText, formatBytes, MAX_FILES };
  if (typeof module !== "undefined" && module.exports) module.exports = root.DrawingUploadQueue;
})(typeof globalThis !== "undefined" ? globalThis : this);
