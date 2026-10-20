import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { create, snapshotDrop, statusText, supported } = createRequire(import.meta.url)('../frontend/drawing-upload-queue.js');
const file = (name, path = '', size = 10) => ({ name, size, type: '', lastModified: 123, webkitRelativePath: path });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const entry = (value) => ({ name: value.name, isFile: true, file: (resolve) => resolve(value) });
const directory = (name, pages) => ({ name, isDirectory: true, createReader: () => {
  let page = 0; return { readEntries: (resolve) => resolve(pages[page++] || []) };
} });
const snapshot = { apiBase: 'http://example.test', userId: 'a', fields: { use_qwen: true } };
const receipt = (id) => ({ job_id: id, recognition_status: 'queued', recognition_progress: 0 });

assert.equal(supported(file('A.PDF')), true);
assert.equal(supported({ ...file('bad.svg'), type: 'image/svg+xml' }), false);
assert.equal(statusText({ status: 'processing', progress: '62.9' }), '识别中 62%');
for (const progress of [null, undefined, '', 'bad', NaN, Infinity, true]) assert.equal(statusText({ status: 'processing', progress }), '识别中');
assert.equal(statusText({ status: 'processing', progress: 100 }), '识别中 99%');
assert.equal(statusText({ status: 'completed', progress: 100 }), '识别完成');

let queue = create();
await queue.collectFiles([file('a.pdf', 'root/a.pdf'), file('a.pdf', 'root/a.pdf'), file('a.pdf', 'other/a.pdf'), file('bad.zip'), file('empty.jpg', '', 0)]);
assert.equal(queue.pending.length, 3); assert.equal(queue.entries.length, 5);
assert.equal(queue.notice, ''); assert.equal(queue.entries[3].status, 'invalid');
assert.equal(new Set(queue.entries.map((item) => item.id)).size, 5, 'Every selection gets an independent entry');
assert.equal(queue.hasUnsent, true);
queue.clearPending(); assert.equal(queue.entries.length, 0); assert.equal(queue.hasUnsent, false);

// Directory readers can return several pages. Include a >100-entry directory and nested paths.
const first = Array.from({ length: 100 }, (_, i) => entry(file(`${i}.pdf`)));
await queue.collectDrop([{ entry: directory('large', [first, [directory('nested', [[entry(file('a.pdf'))]])]]) },
  { entry: directory('empty', []) }, { entry: { name: 'denied', isDirectory: true,
    createReader: () => ({ readEntries: (_resolve, reject) => reject(new Error('permission denied')) }) } }]);
assert.equal(queue.pending.length, 101, 'Read all directory batches');
assert.ok(queue.entries.some((item) => item.path === 'large/nested/a.pdf'));
assert.ok(queue.entries.some((item) => item.error.includes('空文件夹')));
assert.ok(queue.entries.some((item) => item.error.includes('permission denied')));
assert.equal(queue.tooMany, true); assert.equal(await queue.run(snapshot), false, 'Never silently truncate >50');
queue.clearPending();

// Clearing a scan invalidates late callbacks without cancelling a new scan.
const slowFile = deferred();
const scanning = queue.collectDrop([{ entry: { name: 'old.pdf', isFile: true, file: (resolve) => slowFile.promise.then(resolve) } }]);
assert.equal(queue.scanning, true); queue.clearPending();
await queue.collectFiles([file('new.pdf')]); slowFile.resolve(file('old.pdf')); await scanning;
assert.deepEqual(queue.pending.map((item) => item.name), ['new.pdf']);
const another = deferred();
const old = queue.collectDrop([{ entry: { name: 'slow.pdf', isFile: true, file: (resolve) => another.promise.then(resolve) } }]);
await queue.collectFiles([file('added.pdf')]); another.resolve(file('slow.pdf')); await old;
assert.equal(queue.pending.length, 3, 'Concurrent additions are merged');

// DataTransfer is captured synchronously, including file-system handle fallbacks.
let access = true;
const roots = snapshotDrop({ items: [{ kind: 'file', webkitGetAsEntry() { assert.ok(access); return entry(file('drop.pdf')); } }] });
access = false; queue.clearPending(); await queue.collectDrop(roots); assert.equal(queue.pending[0].name, 'drop.pdf');
await queue.collectDrop(snapshotDrop({ items: [{ kind: 'file', getAsFileSystemHandle: async () => ({ name: 'handles', kind: 'directory',
  async *values() { yield { kind: 'file', name: 'h.pdf', getFile: async () => file('h.pdf') }; } }) }] }));
assert.ok(queue.entries.some((item) => item.path === 'handles/h.pdf'));
await queue.collectDrop(snapshotDrop({ items: [{ kind: 'file', getAsFile: () => file('unreadable-folder', '', 0) }] }));
assert.ok(queue.entries.some((item) => item.error.includes('选择文件夹')));

// Upload 50 independently, serially, without waiting for recognition.
let active = 0, peak = 0, accepted = [];
queue = create({ upload: async (item) => { peak = Math.max(peak, ++active); await Promise.resolve(); active--; return receipt(item.id); },
  onAccepted: (item) => accepted.push(item.jobId) });
await queue.collectFiles(Array.from({ length: 50 }, (_, i) => file(`${i}.pdf`)));
await queue.run(snapshot); assert.equal(peak, 1); assert.equal(accepted.length, 50);
assert.ok(queue.entries.every((item) => item.status === 'queued' && item.file === null));
assert.equal(queue.hasUnsent, false);
queue.updateRecognition(accepted[0], { recognition_status: 'processing', recognition_progress: 70 });
assert.equal(queue.entries[0].status, 'processing');
queue.updateRecognition(accepted[0], { recognition_status: 'failed', recognition_error: 'OCR timeout' });
assert.equal(queue.entries.some((item) => item.jobId === accepted[0]), false, 'Failed recognition leaves the upload UI');
assert.equal(queue.isTracking(accepted[0]), false);
assert.equal(queue.hasJob(accepted[0]), true, 'History retry still identifies a page upload');
queue.updateRecognition(accepted[0], { recognition_status: 'queued', recognition_progress: 0 });
assert.equal(queue.entries.find((item) => item.jobId === accepted[0]).error, '');
queue.updateRecognition(accepted[0], { recognition_status: 'processing', recognition_progress: null });
assert.equal(statusText(queue.entries.find((item) => item.jobId === accepted[0])), '识别中', 'A new attempt cannot display stale progress');
queue.markDeleted(accepted[0]); queue.updateRecognition(accepted[0], { status: 'completed' });
assert.equal(queue.entries.some((item) => item.jobId === accepted[0]), false); assert.equal(queue.hasJob(accepted[0]), false);

// Pause after in-flight request; preserve frozen settings on resume and isolate newly added files.
const uploading = deferred(); let calls = [];
queue = create({ upload: async (item, settings) => { calls.push([item.name, settings.fields.use_qwen]);
  return calls.length === 1 ? uploading.promise : receipt(item.id); } });
await queue.collectFiles([file('a.pdf'), file('b.pdf')]);
const mutable = structuredClone(snapshot), running = queue.run(mutable);
mutable.fields.use_qwen = false;
queue.stop(); uploading.resolve(receipt('a')); await running;
assert.equal(calls.length, 1); assert.equal(queue.resumable, true);
await queue.collectFiles([file('next.pdf')]);
await queue.run({ ...snapshot, fields: { use_qwen: false } });
assert.deepEqual(calls, [['a.pdf', true], ['b.pdf', true]]);
assert.equal(queue.pending.length, 1);
await queue.run({ ...snapshot, fields: { use_qwen: false } }); assert.deepEqual(calls[2], ['next.pdf', false]);

// A definite failure doesn't block other files; retries don't recreate accepted jobs.
let fail = true, attempts = [];
queue = create({ upload: async (item) => { attempts.push(item.name); if (fail && item.name === 'bad.pdf') throw new Error('413 too large'); return receipt(item.id); } });
await queue.collectFiles([file('bad.pdf'), file('good.pdf')]); await queue.run(snapshot);
assert.equal(queue.entries[0].status, 'upload_failed'); assert.equal(queue.entries[1].status, 'queued');
fail = false; queue.retryUpload(queue.entries[0].id); await queue.run(snapshot);
assert.deepEqual(attempts, ['bad.pdf', 'good.pdf', 'bad.pdf']);

// Unknown result and auth failures pause, never auto retry. A real accepted result stays accepted if UI fails.
for (const error of [Object.assign(new Error('connection lost'), { uncertain: true }), Object.assign(new Error('401'), { auth: true })]) {
  let count = 0;
  queue = create({ upload: async () => { count++; throw error; } });
  await queue.collectFiles([file('first.pdf'), file('later.pdf')]); await queue.run(snapshot);
  assert.equal(count, 1); assert.equal(queue.entries[1].status, 'pending');
  if (error.uncertain) { queue.retryUpload(queue.entries[0].id); assert.equal(queue.entries[0].status, 'unknown'); }
}
queue = create({ upload: async () => receipt('accepted'), onAccepted: () => { throw new Error('UI error'); } });
await queue.collectFiles([file('ok.pdf')]); await queue.run(snapshot);
assert.equal(queue.entries[0].status, 'queued'); assert.ok(queue.entries[0].syncError.includes('已入队'));
queue = create({ upload: async () => ({}) }); await queue.collectFiles([file('bad.pdf')]); await queue.run(snapshot);
assert.equal(queue.entries[0].status, 'unknown');
queue = create({ upload: async () => { throw new Error('must not upload'); }, canUpload: () => false });
await queue.collectFiles([file('guarded.pdf')]); await queue.run(snapshot); assert.equal(queue.entries[0].status, 'pending');
// Terminal rows are released; selecting the same originals creates new pending entries.
let uploads = 0;
queue = create({ upload: async () => receipt(`summary-${++uploads}`) });
const originalFiles = ['one.pdf', 'two.pdf', 'three.pdf', 'four.pdf'].map((name) => file(name));
await queue.collectFiles(originalFiles); await queue.run(snapshot);
const batchId = queue.latestBatchId;
for (let index = 1; index <= 4; index++) queue.updateRecognition(`summary-${index}`, { status: index === 4 ? 'failed' : 'completed' });
assert.equal(queue.entries.length, 0); assert.equal(queue.trackedJobs.size, 0);
assert.deepEqual(queue.completion, { batchId, total: 4, completed: 3, failed: 1, cancelled: 0 });
assert.equal(queue.hasUnsent, false);
queue.dismissCompletion(); queue.updateRecognition('summary-1', { status: 'completed' }); assert.equal(queue.completion, null);
const revision = queue.pendingRevision;
await queue.collectFiles(originalFiles); assert.equal(queue.pending.length, 4, 'Completed originals can be selected again without refreshing');
assert.equal(queue.pendingRevision, revision + 4);
queue.clearPending();
await queue.collectFiles([file('next.pdf')]); assert.equal(queue.completion, null);
await queue.run(snapshot); assert.notEqual(queue.latestBatchId, batchId);
assert.equal(queue.batches.size, 1, 'Finished older batch statistics are released');
queue.updateRecognition('summary-5', { status: 'completed' }); assert.equal(queue.completion.total, 1);
await queue.collectFiles([file('future.pdf')]);
queue.updateRecognition('summary-5', { status: 'completed' }); assert.equal(queue.completion, null, 'Late terminal snapshots never restore old completion notices');

// Prior active batches remain until terminal, independently of the latest batch counters.
queue = create({ upload: async () => receipt(`active-${++uploads}`) });
await queue.collectFiles([file('old-a.pdf'), file('old-b.pdf')]); await queue.run(snapshot);
const priorJobs = [...queue.trackedJobs.keys()];
await queue.collectFiles([file('current.pdf')]); await queue.run(snapshot);
const currentJob = [...queue.trackedJobs.keys()].at(-1);
assert.equal(queue.entries.length, 3); assert.equal(queue.batches.size, 2);
queue.updateRecognition(priorJobs[0], { status: 'completed' });
queue.updateRecognition(priorJobs[1], { status: 'failed' });
assert.equal(queue.entries.length, 1); assert.equal(queue.isTracking(currentJob), true);
assert.equal(queue.completion, null); assert.equal(queue.batches.size, 1);
queue.updateRecognition(currentJob, { status: 'completed' }); assert.equal(queue.completion.total, 1);
queue.updateRecognition(currentJob, { status: 'queued', progress: 0 });
assert.equal(queue.completion, null, 'History retry invalidates completion without adding a count');
queue.updateRecognition(currentJob, { status: 'completed' }); assert.equal(queue.completion.total, 1);

// Identical files across all collection paths remain separate through upload, progress and deletion.
let repeatUploads = 0;
queue = create({ upload: async () => receipt(`repeat-${++repeatUploads}`) });
const same = file('same.pdf'), sameFolder = { ...same, webkitRelativePath: 'root/same.pdf' };
await queue.collectFiles([same, same]);
await queue.collectFiles([same]);
await queue.collectDrop([{ file: same }, { file: same }]);
await queue.collectFiles([sameFolder, sameFolder]);
const repeatedDirectory = directory('root', [[entry(same)]]);
await queue.collectDrop([{ entry: repeatedDirectory }, { entry: repeatedDirectory }]);
assert.equal(queue.pending.length, 9);
const removedId = queue.pending[0].id;
queue.remove(removedId); assert.equal(queue.pending.length, 8);
assert.equal(new Set(queue.pending.map((item) => item.id)).size, 8);
await queue.run(snapshot); assert.equal(repeatUploads, 8); assert.equal(queue.trackedJobs.size, 8);
queue.updateRecognition('repeat-1', { status: 'processing', progress: 73 });
queue.updateRecognition('repeat-2', { status: 'processing', progress: 26 });
assert.equal(queue.trackedJobs.get('repeat-1').progress, 73); assert.equal(queue.trackedJobs.get('repeat-2').progress, 26);
await queue.collectFiles([same]); await queue.run(snapshot);
assert.equal(repeatUploads, 9, 'Same file can be uploaded again while its older orders are processing');
queue.markDeleted('repeat-1'); queue.updateRecognition('repeat-1', { status: 'completed' });
assert.equal(queue.isTracking('repeat-1'), false); assert.equal(queue.isTracking('repeat-2'), true);
for (const id of [...queue.trackedJobs.keys()]) queue.updateRecognition(id, { status: 'completed' });
await queue.collectFiles([same]); await queue.run(snapshot);
assert.equal(repeatUploads, 10, 'Completion and cleanup impose no same-file restriction');

queue = create({ upload: async (item) => receipt(item.id) });
await queue.collectFiles(Array(51).fill(same));
assert.equal(queue.pending.length, 51); assert.equal(queue.tooMany, true); assert.equal(await queue.run(snapshot), false);
queue.remove(queue.pending[0].id); assert.equal(queue.tooMany, false);
await queue.run(snapshot); assert.equal(queue.knownJobs.size, 50, 'Repeated files count individually toward the 50-file limit');

let unknownCalls = 0;
queue = create({ upload: async () => {
  if (++unknownCalls === 1) throw Object.assign(new Error('lost response'), { uncertain: true });
  return receipt('manual-new-upload');
} });
await queue.collectFiles([same]); await queue.run(snapshot);
const unknownId = queue.entries[0].id;
await queue.collectFiles([same]); await queue.run(snapshot);
assert.equal(unknownCalls, 2); assert.equal(queue.entries.find((item) => item.id === unknownId).status, 'unknown');
queue.retryUpload(unknownId); assert.equal(queue.entries.find((item) => item.id === unknownId).status, 'unknown');
assert.equal(queue.entries.length, 2, 'Manual re-selection does not discard or automatically retry the unknown item');
console.log('PASS: repeated file/folder selections, independent IDs and jobs, active/completed re-upload, 50-file limit, safe retries, terminal cleanup and batch regressions.');
