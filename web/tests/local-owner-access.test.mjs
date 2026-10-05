import assert from 'node:assert/strict';
import { test } from 'node:test';
import { accessJson, decodeBase64url, encodeBase64url, fetchLocalOwner, setAccessSession } from '../lib/local-owner-access.ts';

test('private writes attach volatile CSRF; reads do not; all requests bypass cache', async (t) => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (_path, init) => { requests.push(init); return Response.json({}); });
  setAccessSession('synthetic-csrf');
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
  setAccessSession('synthetic-csrf');
  await fetchLocalOwner('/synthetic');
  await assert.rejects(accessJson('logout', {}), (error) => !error.message.includes('synthetic-private-value'));
  // Clear authority even in non-browser tests, not only when dispatching an event.
  assert.equal(requests[1].headers.get('X-OneJournal-CSRF'), null);
});

test('WebAuthn binary serialization round trips unpadded base64url', () => {
  const bytes = Uint8Array.of(0, 255, 128, 42);
  const encoded = encodeBase64url(bytes.buffer);
  assert.equal(encoded, 'AP-AKg');
  assert.deepEqual(new Uint8Array(decodeBase64url(encoded)), bytes);
});
