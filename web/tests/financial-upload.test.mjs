import test from 'node:test';
import assert from 'node:assert/strict';
import { publishFinancialUpload, financialUploadAvailable } from '../lib/financial-upload.ts';

const files = names => names.map(name => new File(['{}'], name, { type: 'application/json' }));
const positions = files(['acquisition-manifest.json', 'positions.json']);
const activity = files(['acquisition-manifest.json', 'orders.json', 'transactions.json']);

test('paired upload publishes dates and preserves separate manifest names', async t => {
  const receipt = { contract_version: 'onejournal.financial-upload.v1', state: 'published', replayed: false,
    report_release_uid: 'synthetic-release', portfolio_asof: '2026-10-16', coverage_end_date: '2026-10-16',
    reportable_count: 3, withheld_count: 1 };
  const fetch = t.mock.method(globalThis, 'fetch', async (path, init) => {
    assert.equal(path, '/api/v1/local-owner/financial-upload');
    assert.equal(init.credentials, 'same-origin');
    const body = JSON.parse(init.body);
    assert.equal(body.positions.files.length, 2);
    assert.equal(body.activity.files.length, 3);
    return Response.json(receipt);
  });
  assert.equal((await publishFinancialUpload(positions, activity)).reportable_count, 3);
  fetch.mock.mockImplementation(async () => Response.json({ ...receipt, withheld_count: -1 }));
  await assert.rejects(publishFinancialUpload(positions, activity), /could not be confirmed/);
});

test('incomplete files never post; rejection and uncertain completion differ', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('private details', { status: 422 }));
  await assert.rejects(publishFinancialUpload(positions, []), /3 JSON files/);
  assert.equal(fetch.mock.callCount(), 0);
  await assert.rejects(publishFinancialUpload(positions, activity), /Saved data is unchanged/);
  fetch.mock.mockImplementation(async () => new Response('', { status: 503 }));
  await assert.rejects(publishFinancialUpload(positions, activity), /whether the update was saved/);
  fetch.mock.mockImplementation(async () => Response.json({ contract_version: 'onejournal.financial-upload.v1', enabled: true }));
  assert.equal(await financialUploadAvailable(), true);
});
