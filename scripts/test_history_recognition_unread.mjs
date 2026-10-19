import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { create } = createRequire(import.meta.url)('../frontend/history-recognition-unread.js');
const data = new Map();
const storage = { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value),
  get length() { return data.size; }, key: (index) => [...data.keys()][index] };
const options = { service: 'http://local/api', userId: 'one', storage };
const item = (id, phase = 'completed', attempt = 1, tick = 1) => ({ job_id: id, recognition_status: phase,
  recognition_attempt_count: attempt, updated_at: new Date(1000 * tick).toISOString() });
let controller = create(options);
controller.observe(item('early', 'processing'));
controller.observe(item('instant'), { submission: true });
controller.observeList([item('old'), item('legacy', 'completed', undefined), item('early', 'processing'), item('instant')]);
assert.equal(controller.isUnread(item('old')), false, 'Existing complete records form a baseline');
assert.equal(controller.isUnread(item('instant')), true, 'Submission before the first list is not swallowed');
controller.observe({ job_id: 'fast', recognition_status: 'completed' }, { submission: true });
controller.markRead('fast', controller.capture({ job_id: 'fast' }));
controller.observe(item('fast', 'completed', 1, 2));
assert.equal(controller.isUnread(item('fast')), false, 'Learning a fast completion counter cannot relight its receipt');
controller.observe(item('early', 'completed', 1, 2));
assert.equal(controller.isUnread(item('early')), true, 'Previously observed processing job completes');
const firstRound = controller.capture(item('early'));
controller.markRead('early', firstRound);
controller.observe(item('early', 'completed', 1, 3));
assert.equal(controller.isUnread(item('early')), false, 'Parameter revisions/list refresh cannot relight a viewed round');
controller.observe(item('early', 'queued', 1, 4), { restart: true });
controller.observe(item('early', 'completed', 1, 3));
assert.equal(controller.isUnread(item('early')), false, 'Old completion after retry is not the new result');
controller.observe(item('early', 'processing', 2, 5));
controller.observe(item('early', 'completed', 2, 6));
controller.markRead('early', firstRound);
assert.equal(controller.isUnread(item('early', 'completed', 2)), true, 'Opening the old result cannot clear the new round');
const secondRound = controller.capture(item('early', 'completed', 2));
const otherTab = create(options);
otherTab.markRead('early', secondRound);
controller.observe(item('early', 'completed', 2, 7));
assert.equal(controller.isUnread(item('early', 'completed', 2)), false, 'Immutable receipts survive stale tab progress writes');
otherTab.markRead('instant', otherTab.capture(item('instant')));
assert.equal(controller.isUnread(item('instant')), false, 'Independent job receipts are not overwritten');

controller.observe(item('closed', 'processing', 3));
controller = create(options);
assert.ok(controller.trackedIds().includes('closed'), 'Persisted active tasks are discoverable without history membership');
controller.observeList([item('old'), item('closed', 'completed', 3, 3)]);
assert.equal(controller.isUnread(item('closed', 'completed', 3)), true, 'Closed-page completion remains unread on reopen');
controller.observe(item('closed', 'processing', 2, 9));
assert.equal(controller.isUnread(item('closed', 'completed', 3)), true, 'Lower attempt cannot overwrite new completion');
controller.remove('closed');
otherTab.observe(item('closed', 'completed', 4, 20));
assert.equal(otherTab.isUnread(item('closed', 'completed', 4)), false, 'Deletion tombstone beats late tab responses');

for (const changes of [{ service: 'http://another/api' }, { userId: 'two' }]) {
  const isolated = create({ ...options, ...changes });
  isolated.observeList([item('instant')]);
  assert.equal(isolated.isUnread(item('instant')), false, 'Service/user namespaces have independent baselines');
}
controller.observe({ job_id: 'no-counter', recognition_status: 'processing' });
controller.observe({ job_id: 'no-counter', recognition_status: 'completed' });
assert.equal(controller.isUnread({ job_id: 'no-counter' }), true, 'Observed legacy active-to-complete transition has a local round');
controller.observeList([{ job_id: 'unknown-legacy' }]);
assert.equal(controller.isUnread({ job_id: 'unknown-legacy' }), false, 'Unknown legacy completion is never inferred from review metadata');

const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('quota'); } };
const session = create({ ...options, storage: broken });
session.observeList([item('old')]);
session.observe(item('new'), { submission: true });
assert.equal(session.isUnread(item('new')), true);
session.markRead('new', session.capture(item('new')));
assert.equal(session.isUnread(item('new')), false, 'Unavailable storage keeps functional session state');
const quota = create({ ...options, service: 'quota', storage: { getItem: () => null, setItem() { throw new Error('full'); } } });
quota.observe(item('new'), { submission: true });
assert.equal(quota.isUnread(item('new')), true, 'Failed persistence does not discard local observation');

let listener, changes = 0, removed = false;
const synced = create({ ...options, eventTarget: { addEventListener: (_, fn) => { listener = fn; },
  removeEventListener: (_, fn) => { removed = fn === listener; } }, onChange: () => changes++ });
listener({ key: 'another-namespace', newValue: '1' }); assert.equal(changes, 0);
listener({ key: [...data.keys()][0], newValue: data.values().next().value }); assert.equal(changes, 1);
synced.dispose(); assert.ok(removed);
console.log('PASS: unread baselines, recognition rounds, stale responses, restart persistence, multi-tab receipts, namespace isolation, legacy jobs and storage fallback.');
