import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchRefreshStatus, requestRefresh } from '../lib/data-refresh.ts';

const id = '00000000-0000-4000-8000-000000000001';
const latest = { request_id: id, provider: 'schwab', requested_at: '2026-10-13T01:00:00Z', state: 'queued' };
test('refresh uses same-origin owner API and sends no broker/account/history inputs', async (t) => {
  t.mock.method(globalThis, 'fetch', async (path, init) => {
    assert.equal(path, '/api/v1/local-owner/data-refresh');
    assert.equal(init.credentials, 'same-origin'); assert.equal(init.cache, 'no-store');
    assert.equal(init.method, 'POST'); assert.deepEqual(JSON.parse(init.body), { request_id: id });
    return Response.json(latest, { status: 202 });
  });
  assert.deepEqual(await requestRefresh(id), latest);
});
test('disabled and pending states are explicit; malformed/private failures do not become success', async (t) => {
  const base = { contract_version: 'onejournal.data-refresh.v1', enabled: false, provider: 'schwab', latest: null };
  for (const value of [base, { ...base, enabled: true, latest }, { ...base, latest: { ...latest, state: 'published' } },
    { ...base, latest: { ...latest, provider: 'ibkr' } }, { ...base, enabled: 'yes' }]) {
    const mock = t.mock.method(globalThis, 'fetch', async () => Response.json(value));
    if (value === base || value.latest === latest) assert.equal((await fetchRefreshStatus()).enabled, value.enabled);
    else await assert.rejects(fetchRefreshStatus());
    mock.mock.restore();
  }
  t.mock.method(globalThis, 'fetch', async () => new Response('private details', { status: 503 }));
  await assert.rejects(requestRefresh(id), /not confirmed/);
  await assert.rejects(fetchRefreshStatus(), /saved data is unchanged/);
});
