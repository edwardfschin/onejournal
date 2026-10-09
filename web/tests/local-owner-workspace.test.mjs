import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fetchSavedWorkspace, fetchWorkspaceSession } from '../lib/local-owner-workspace.ts';

function response(history = false) {
  return {
    metadata: {
      contract_version: 'onejournal.phase1-report-release.v1', report_release_uid: 'synthetic-release',
      report_release_fingerprint: 'a'.repeat(64), selection_fingerprint: 'b'.repeat(64),
      coverage_start_date: '2026-09-01', coverage_end_date: '2026-09-04', current_valuation_asof: history ? null : '2026-09-04',
      calculation_version: 'synthetic-v1', generated_at_utc: '2026-09-04T20:00:00Z', owner_accepted_at_utc: '2026-09-04T21:00:00Z',
      quality: history ? 'incomplete' : 'valid', reason_counts: history ? { opening_history_missing: 1 } : {},
    },
    counts: { processed_count: history ? 1 : 0, available_count: 0, unavailable_count: history ? 1 : 0, reconciliation_pending_count: 0 },
    ...(history ? { items: [] } : { accounts: [] }),
  };
}

test('loads the exact full accepted coverage with existing same-origin GETs, keeping context only', async (t) => {
  const paths = [];
  t.mock.method(globalThis, 'fetch', async (path, init) => {
    paths.push(path); assert.equal(init.credentials, 'same-origin'); assert.equal(init.cache, 'no-store');
    assert.ok(!init.method || init.method === 'GET');
    return Response.json(response(path.includes('realized-history')));
  });
  const saved = await fetchSavedWorkspace();
  assert.deepEqual(paths, ['/api/v1/local-owner/reports/current/accounts',
    '/api/v1/local-owner/reports/realized-history?from_date=2026-09-01&to_date=2026-09-04']);
  assert.equal(saved.history.counts.unavailable_count, 1);
  assert.equal(saved.history.metadata.quality, 'incomplete');
  assert.equal('accounts' in saved.current, false); assert.equal('items' in saved.history, false);
});

test('mixed releases, missing snapshot dates and failed services never become a successful overview', async (t) => {
  for (const key of ['report_release_uid', 'report_release_fingerprint', 'coverage_end_date', 'calculation_version']) {
    const mock = t.mock.method(globalThis, 'fetch', async (path) => {
      const history = path.includes('realized-history'); const value = response(history);
      if (history) value.metadata[key] = key.includes('fingerprint') ? 'c'.repeat(64)
        : key.includes('date') ? '2026-09-05' : 'changed';
      return Response.json(value);
    });
    await assert.rejects(fetchSavedWorkspace(), /reports changed/); mock.mock.restore();
  }
  const missing = response(); missing.metadata.current_valuation_asof = null;
  let mock = t.mock.method(globalThis, 'fetch', async () => Response.json(missing));
  await assert.rejects(fetchSavedWorkspace(), /snapshot date/); mock.mock.restore();
  mock = t.mock.method(globalThis, 'fetch', async () => new Response('private error body', { status: 503 }));
  await assert.rejects(fetchSavedWorkspace(), /reporting service is unavailable/); mock.mock.restore();
});

test('settings reports only a verified, unexpired Mac session without retaining CSRF', async (t) => {
  const valid = { contract_version: 'onejournal.mac-passkey.v1', authenticated: true, passkey_count: 2, expires_in_seconds: 60, csrf: 'synthetic-csrf' };
  for (const change of [{}, { authenticated: false }, { passkey_count: null }, { passkey_count: 0 },
    { expires_in_seconds: 0 }, { expires_in_seconds: 999999 }, { contract_version: 'other' }]) {
    const mock = t.mock.method(globalThis, 'fetch', async (path) => {
      assert.equal(path, '/api/v1/local-owner/access/session');
      return Response.json({ ...valid, ...change });
    });
    if (Object.keys(change).length) await assert.rejects(fetchWorkspaceSession(), /session could not be verified/);
    else assert.deepEqual(await fetchWorkspaceSession(), { passkeyCount: 2 });
    mock.mock.restore();
  }
});
