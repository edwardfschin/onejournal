import assert from 'node:assert/strict';
import { test } from 'node:test';
import { accessJson, ACCESS_REQUIRED_EVENT, decodeBase64url, encodeBase64url, expireAccessIfDue, fetchLocalOwner, listenForAccessRevocation, revokeAccessAcrossTabs, setAccessSession } from '../lib/local-owner-access.ts';

test('private writes attach volatile CSRF; reads do not; all requests bypass cache', async (t) => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (_path, init) => { requests.push(init); return Response.json({}); });
  setAccessSession('synthetic-csrf', 900);
  await fetchLocalOwner('/synthetic', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
  await fetchLocalOwner('/synthetic');
  assert.equal(requests[0].headers.get('X-OneJournal-CSRF'), 'synthetic-csrf');
  assert.equal(requests[1].headers.get('X-OneJournal-CSRF'), null);
  assert.equal(requests[0].credentials, 'same-origin');
  assert.equal(requests[0].cache, 'no-store');
  setAccessSession(null);
});

test('expired authority clears CSRF and server error details are not displayed', async (t) => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (_path, init) => {
    requests.push(init); return Response.json({ detail: 'synthetic-private-value-never-display' }, { status: 401 });
  });
  setAccessSession('synthetic-csrf', 900);
  await fetchLocalOwner('/synthetic');
  await assert.rejects(accessJson('logout', {}), (error) => !error.message.includes('synthetic-private-value'));
  // Clear authority even in non-browser tests, not only when dispatching an event.
  assert.equal(requests[1].headers.get('X-OneJournal-CSRF'), null);
});

test('session deadline locks the browser view and clears write authority', async (t) => {
  const previousWindow = globalThis.window;
  globalThis.window = new EventTarget();
  t.after(() => { setAccessSession(null); globalThis.window = previousWindow; });
  let locks = 0;
  window.addEventListener(ACCESS_REQUIRED_EVENT, () => { locks += 1; });
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (_path, init) => { requests.push(init); return Response.json({}); });

  setAccessSession('synthetic-csrf', 0);
  expireAccessIfDue(); // Focus after a suspended timer must lock immediately.
  assert.equal(locks, 1);
  await fetchLocalOwner('/synthetic', { method: 'POST' });
  assert.equal(requests[0].headers.get('X-OneJournal-CSRF'), null);

  setAccessSession('synthetic-csrf', 0.01);
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(locks, 2); // Active tab timer locks without waiting for polling.
});

test('confirmed logout locks other open tabs immediately', (t) => {
  const previousWindow = globalThis.window;
  const previousChannel = globalThis.BroadcastChannel;
  globalThis.window = new EventTarget();
  class FakeChannel extends EventTarget {
    static instances = [];
    constructor(name) { super(); this.name = name; FakeChannel.instances.push(this); }
    postMessage(value) {
      for (const other of FakeChannel.instances) {
        if (other !== this && other.name === this.name) {
          const event = new Event('message');
          Object.defineProperty(event, 'data', { value });
          other.dispatchEvent(event);
        }
      }
    }
  }
  globalThis.BroadcastChannel = FakeChannel;
  const stopListening = listenForAccessRevocation();
  t.after(() => { stopListening(); setAccessSession(null); globalThis.window = previousWindow; globalThis.BroadcastChannel = previousChannel; });
  let locks = 0;
  window.addEventListener(ACCESS_REQUIRED_EVENT, () => { locks += 1; });
  setAccessSession('synthetic-csrf', 900);
  const otherTab = new FakeChannel('onejournal-access-revoked');
  otherTab.postMessage('unrelated');
  assert.equal(locks, 0);
  otherTab.postMessage('logout');
  assert.equal(locks, 1);
  setAccessSession('synthetic-csrf', 900);
  let sent = 0;
  otherTab.addEventListener('message', () => { sent += 1; });
  revokeAccessAcrossTabs();
  assert.equal(locks, 2);
  assert.equal(sent, 1);
  FakeChannel.instances[0].postMessage = () => { throw new Error('browser channel unavailable'); };
  setAccessSession('synthetic-csrf', 900);
  assert.doesNotThrow(() => revokeAccessAcrossTabs());
  assert.equal(locks, 3);
});

test('WebAuthn binary serialization round trips unpadded base64url', () => {
  const bytes = Uint8Array.of(0, 255, 128, 42);
  const encoded = encodeBase64url(bytes.buffer);
  assert.equal(encoded, 'AP-AKg');
  assert.deepEqual(new Uint8Array(decodeBase64url(encoded)), bytes);
});
