import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/app.js', 'utf8');
const block = source.slice(source.indexOf('async function loadRecentReviews('), source.indexOf('async function openPersistedReview('));
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const response = (recognition, extra = {}) => ({ ok: true, status: 200, json: async () => ({ job_id: 'one', recognition, ...extra }) });
let timers, fetches, requests, opened, messages, context;
function setup(items = []) {
  timers = new Map(); fetches = []; requests = []; opened = []; messages = [];
  let timerId = 0;
  context = { console, Map, Set, Number, Date, Intl,
    state: { identityReady: true, recentReviews: structuredClone(items), recentReviewsLoading: false,
      recognitionRequestSerial: 0, recognitionStatusVersions: new Map(), deletedReviewIds: new Set(),
      recognitionPollers: {}, recognitionMessageIds: {}, lastJob: null },
    recentReviews: {}, recentReviewList: { querySelectorAll: () => [] }, refreshRecentReviewsButton: {},
    historyUnread: null, historyRecognitionScope: () => 'local-test', historyOrderIsUnread: () => false,
    updateHistoryUnreadCount() {},
    SPRING_TYPE_LABELS: { compression_spring: '压缩弹簧' }, formatRecentReviewTime: (value) => value || '',
    apiFetch: async (url) => { requests.push(url); if (!fetches.length) throw new Error('offline'); return await fetches.shift(); },
    replaceMessage: (...args) => messages.push(args), removeMessage() {},
    openPersistedReview: async (...args) => opened.push(args),
    window: { setInterval: (callback) => { timers.set(++timerId, callback); return timerId; }, clearInterval: (id) => timers.delete(id) },
  };
  vm.createContext(context); vm.runInContext(block, context);
  context.renderRecentReviews = () => {};
}
setup();
for (const [input, label, progress] of [
  [{}, '识别完成', null], [{ overall_status: 'need_review' }, '识别完成', null],
  [{ recognition_status: 'queued', recognition_progress: 85 }, '识别中', 0],
  [{ recognition_status: 'processing', recognition_progress: 62.9 }, '识别中', 62],
  [{ recognition_status: 'processing', recognition_progress: '35' }, '识别中', 35],
  [{ recognition_status: 'processing', recognition_progress: 100 }, '识别中', 99],
  [{ recognition_status: 'processing', recognition_progress: -4 }, '识别中', 0],
  ...[undefined, null, '', ' ', 'bad', Infinity, NaN, true, []].map((value) => [{ recognition_status: 'processing', recognition_progress: value }, '识别中', null]),
  [{ recognition_status: 'failed', recognition_progress: 65 }, '识别失败', null],
  [{ recognition_status: 'completed', recognition_progress: 100 }, '识别完成', null],
]) {
  const model = context.historyRecognitionState(input);
  assert.equal(model.label, label); assert.equal(model.progress, progress);
}
const stamp = (n) => `2026-10-19T01:00:${String(n).padStart(2, '0')}Z`;
const item = (progress, attempt = 1, status = 'processing', time = 10) => ({ job_id: 'one', drawing_name: '<Order>',
  recognition_status: status, recognition_progress: progress, recognition_attempt_count: attempt, updated_at: stamp(time) });
let current = context.reconcileRecognitionListItem(null, item(35), 10);
current = context.reconcileRecognitionListItem(current, item(65, 1, 'processing', 11), 11);
assert.equal(current.recognition_progress, 65);
for (const value of [null, undefined, 'bad', Infinity, '']) {
  current = context.reconcileRecognitionListItem(current, item(value, 1, 'processing', 12), 12);
  assert.equal(current.recognition_progress, 65, 'Missing progress preserves the latest valid value');
}
assert.equal(context.reconcileRecognitionListItem(current, item(80, 1, 'processing', 13), 9), current, 'Late request cannot overwrite current progress');
assert.equal(context.reconcileRecognitionListItem(current, item(80, 1, 'processing', 10), 20), current, 'Older saved snapshot is rejected');
assert.equal(context.reconcileRecognitionListItem(current, item(80, 0, 'processing', 20), 30), current, 'Lower retry count is rejected');
current = context.reconcileRecognitionListItem(current, item(null, 2, 'processing', 20), 21);
assert.equal(current.recognition_progress, null, 'New attempt cannot inherit old progress');
current = context.reconcileRecognitionListItem(current, item(100, 2, 'completed', 22), 22);
assert.equal(context.reconcileRecognitionListItem(current, item(65, 2, 'processing', 22), 23), current);
current = context.reconcileRecognitionListItem(current, item(80, 2, 'queued', 23), 24, { restart: true });
assert.equal(current.recognition_progress, 0, 'Explicit retry may reset to zero before attempt_count increments');
setup([item(55, 1, 'failed', 12)]);
context.state.recognitionRequestSerial = 5;
context.mergeRecognitionStatus('one', { status: 'queued', progress: 0, attempt_count: 1, updated_at: stamp(12) }, { requestSerial: 1, restart: true });
const restarted = context.state.recentReviews[0];
assert.equal(context.reconcileRecognitionListItem(restarted, item(55, 1, 'failed', 12), 5), restarted,
  'Retry response rejects all earlier in-flight snapshots even within the same timestamp');
assert.equal(context.historyOrderIsVisible({ job_id: 'one', recognition_status: 'cancel_requested' }), false);
assert.equal(context.historyOrderIsVisible({ job_id: 'one', recognition_status: 'cancelled' }), false);

setup([item(35)]);
const waiting = deferred(); fetches.push(waiting.promise);
context.trackRecognitionJob('one', 'message');
assert.equal(requests.length, 1);
timers.values().next().value(); timers.values().next().value();
assert.equal(requests.length, 1, 'Slow requests cannot overlap');
waiting.resolve(response({ status: 'processing', progress: 65, attempt_count: 1, updated_at: stamp(11) }));
await tick(); assert.equal(context.state.recentReviews[0].recognition_progress, 65);
fetches.push(response({ status: 'completed', progress: 100, attempt_count: 1, updated_at: stamp(12) }));
context.state.lastJob = { job_id: 'one' };
timers.values().next().value(); await tick();
assert.equal(timers.size, 0, 'Completion stops polling'); assert.equal(opened.length, 1);
assert.equal(context.state.recentReviews[0].recognition_status, 'completed');

setup([item(55)]);
context.trackRecognitionJob('one'); await tick();
assert.equal(context.state.recentReviews[0].recognition_progress, 55);
assert.equal(context.state.recentReviews[0].recognition_status, 'processing', 'Network errors are not recognition failures');
assert.ok(context.historyOrderTooltip(context.state.recentReviews[0]).includes('进度暂时无法刷新'));
assert.equal(timers.size, 0);
fetches.push(response({ status: 'processing', progress: 78, attempt_count: 1, updated_at: stamp(12) }));
context.trackRecognitionJob('one'); await tick();
assert.equal(context.state.recentReviews[0].recognition_sync_error, '');
assert.equal(context.state.recentReviews[0].recognition_progress, 78);

setup([item(55)]);
fetches.push(response({ status: 'failed', progress: 55, attempt_count: 1, error_message: 'Engine failed', updated_at: stamp(12) }));
context.trackRecognitionJob('one'); await tick();
assert.equal(context.state.recentReviews[0].recognition_status, 'failed');
assert.equal(timers.size, 0, 'Failure stops polling without changing its server-supplied reason');
assert.ok(context.historyOrderTooltip(context.state.recentReviews[0]).includes('Engine failed'));

for (const action of ['delete', 'restart', 'wrong_job']) {
  setup([item(55)]); const held = deferred(); fetches.push(held.promise);
  context.trackRecognitionJob('one');
  if (action === 'delete') {
    context.state.deletedReviewIds.add('one'); context.state.recentReviews = []; context.stopTrackingRecognitionJob('one');
  } else if (action === 'restart') {
    context.stopTrackingRecognitionJob('one');
    context.mergeRecognitionStatus('one', { status: 'queued', progress: 0, attempt_count: 1, updated_at: stamp(12) }, { restart: true });
  }
  held.resolve(response({ status: 'completed', progress: 100, attempt_count: 1, updated_at: stamp(11) }, action === 'wrong_job' ? { job_id: 'other' } : {}));
  await tick();
  if (action === 'delete') assert.equal(context.state.recentReviews.length, 0);
  else assert.equal(context.state.recentReviews[0].recognition_status, action === 'restart' ? 'queued' : 'processing');
  assert.equal(opened.length, 0);
}

setup([item(55)]);
const listing = deferred(); fetches.push(listing.promise);
const loading = context.loadRecentReviews();
context.mergeRecognitionStatus('one', { status: 'completed', progress: 100, attempt_count: 1, updated_at: stamp(12) });
listing.resolve({ ok: true, json: async () => ({ reviews: [item(35)] }) }); await loading;
assert.equal(context.state.recentReviews[0].recognition_status, 'completed', 'Old list snapshot cannot roll back live progress');
context.state.deletedReviewIds.add('one');
fetches.push({ ok: true, json: async () => ({ reviews: [item(35)] }) });
await context.loadRecentReviews(); assert.equal(context.state.recentReviews.length, 0);

setup([item(55)]);
fetches.push({ ok: true, json: async () => ({ reviews: 'invalid' }) });
await context.loadRecentReviews();
assert.equal(context.state.recentReviews.length, 1, 'Malformed list responses retain existing records');

setup([]);
const oldList = deferred(); fetches.push(oldList.promise);
const oldLoading = context.loadRecentReviews();
context.mergeRecognitionStatus('new-job', { status: 'processing', progress: 35, attempt_count: 1, updated_at: stamp(12) });
context.trackRecognitionJob = () => {};
oldList.resolve({ ok: true, json: async () => ({ reviews: [] }) }); await oldLoading;
assert.equal(context.state.recentReviews[0].job_id, 'new-job', 'Old list response cannot drop a job added while the request was pending');

setup([{ job_id: 'first' }, { job_id: 'second' }]);
fetches.push({ ok: true, json: async () => ({ reviews: [{ job_id: 'second' }, { job_id: 'new' }, { job_id: 'first' }] }) });
await context.loadRecentReviews();
assert.equal(context.state.recentReviews.map((item) => item.job_id).join(','), 'new,first,second', 'Refresh adds new records first while preserving the order of existing rows');
console.log('PASS: three history states, real percentages, retry/sequence guards, no overlapping polls, network recovery and deleted/late response protection');
