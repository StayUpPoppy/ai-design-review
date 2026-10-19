import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { create } = createRequire(import.meta.url)('../frontend/history-bulk-deletion.js');
const item = (id) => ({ job_id: String(id), drawing_name: `Order ${id}` });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const response = (id, values = {}, status = 200) => ({ ok: status < 400, status, json: async () => ({ job_id: id, deleted: true, ...values }) });
function setup() {
  const model = { scope: 'first', saved: true, calls: [], deleted: [], responses: new Map(), active: 0, peak: 0, locks: [] };
  model.queue = create({ getScope: () => model.scope, save: async () => model.saved,
    requestDelete: async (entry) => {
      model.calls.push(entry.job_id); model.peak = Math.max(model.peak, ++model.active);
      try { return await (model.responses.get(entry.job_id)?.() ?? response(entry.job_id)); }
      finally { model.active--; }
    }, onDeleted: (entry, result) => model.deleted.push([entry.job_id, result.kind]),
    onRunningChange: (running) => model.locks.push(running) });
  model.queue.updateVisible(Array.from({ length: 100 }, (_, index) => item(index)));
  return model;
}
{
  const { queue } = setup(); queue.enter(); queue.toggle('1'); queue.toggle('2');
  queue.updateVisible([...queue.state.visible.values(), item('new')]);
  assert.deepEqual([...queue.state.selected], ['1', '2'], 'New arrivals and status updates preserve ID-based selection');
  queue.updateVisible([item('2'), item('new')]); assert.deepEqual([...queue.state.selected], ['2']);
  queue.selectAll(); assert.equal(queue.state.selected.size, 2);
  queue.clearSelection(); assert.equal(queue.state.selected.size, 0);
  queue.exit(); assert.equal(queue.state.managing, false);
}
{
  const model = setup(), { queue } = model; queue.enter(); queue.selectAll();
  const gate = deferred(); model.responses.set('0', () => gate.promise);
  const running = queue.run(queue.selectedItems());
  await Promise.resolve(); await Promise.resolve();
  queue.toggle('1'); queue.exit(); queue.selectAll();
  assert.equal(queue.state.selected.size, 100); assert.equal(queue.state.managing, true);
  assert.equal(await queue.run([item('1')]), false, 'Double submission is blocked');
  gate.resolve(response('0')); await running;
  assert.equal(model.peak, 1); assert.equal(model.calls.length, 100);
  assert.equal(queue.summary().deleted, 100); assert.equal(queue.state.managing, false);
  assert.deepEqual(model.locks, [true, false]);
}
{
  const model = setup(), { queue } = model; queue.enter(); queue.selectAll(); model.saved = false;
  assert.equal(await queue.run(queue.selectedItems()), false);
  assert.equal(model.calls.length, 0); assert.equal(queue.state.selected.size, 100);
  assert.ok(queue.state.notice.includes('保存')); assert.equal(queue.state.running, false);
}
{
  const model = setup(), { queue } = model;
  queue.enter(); ['0', '1', '2', '3'].forEach((id) => queue.toggle(id));
  model.responses.set('1', () => response('1', { deleted: false, detail: '模拟失败' }, 500));
  model.responses.set('2', () => { throw new Error('network'); });
  model.responses.set('3', () => response('3', { status: 'cancelling', artifact_cleanup: 'pending_worker_cancellation' }));
  await queue.run(queue.selectedItems());
  assert.deepEqual(model.deleted, [['0', 'deleted'], ['3', 'cancelling']]);
  assert.deepEqual([...queue.state.selected], ['1', '2']);
  assert.deepEqual(queue.failedItems().map((entry) => entry.job_id), ['1']);
  assert.deepEqual(queue.selectedItems().map((entry) => entry.job_id), ['1'], 'Unknown outcomes are not retried without a manual check');
  model.responses.delete('1'); await queue.run(queue.failedItems());
  assert.deepEqual(model.calls, ['0', '1', '2', '3', '1'], 'Retry only sends failed IDs');
  assert.equal(queue.state.managing, true, 'Unresolved selection is retained after retrying other failures');
}
{
  const model = setup(), { queue } = model; queue.enter(); ['0', '1', '2'].forEach((id) => queue.toggle(id));
  model.responses.set('0', () => response('0', { deleted: false, detail: 'expired' }, 401));
  await queue.run(queue.selectedItems());
  assert.deepEqual(model.calls, ['0']); assert.equal(queue.summary().pending, 2);
  assert.equal(queue.state.selected.size, 3); assert.equal(queue.state.managing, true);
}
{
  const model = setup(), { queue } = model; queue.enter(); queue.selectAll();
  model.responses.set('0', () => ({ ok: false, status: 401, json: async () => { throw new Error('login HTML'); } }));
  await queue.run(queue.selectedItems()); assert.deepEqual(model.calls, ['0'], 'Non-JSON auth errors also stop the remaining batch');
  assert.equal(queue.summary().failed, 1);
}
{
  const model = setup(), { queue } = model; queue.enter(); queue.toggle('0');
  const gate = deferred(); model.responses.set('0', () => gate.promise);
  const running = queue.run(queue.selectedItems()); await Promise.resolve(); await Promise.resolve();
  model.scope = 'second'; queue.reset(); gate.resolve(response('0')); await running;
  assert.deepEqual(model.deleted, [], 'Old-session response cannot delete new-session UI state');
  assert.equal(queue.state.results.size, 0); assert.equal(queue.state.running, false);
}
{
  const model = setup(), { queue } = model; queue.enter(); queue.toggle('0');
  model.responses.set('0', () => response('wrong-id')); await queue.run(queue.selectedItems());
  assert.equal(queue.summary().unknown, 1); assert.equal(queue.selectedItems().length, 0);
  queue.checkedUnknown(['0']); assert.equal(queue.selectedItems().length, 1);
  model.responses.set('0', () => response('0', { artifact_cleanup: 'pending' })); await queue.run(queue.selectedItems());
  assert.equal(queue.summary().cleanupPending, 1);
}
console.log('PASS: 100 sequential deletions, stable selection, save guard, partial failure, manual unknown check, cancellation, auth stop, cleanup warning and stale-session protection.');
