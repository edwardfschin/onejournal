import test from 'node:test';
import assert from 'node:assert/strict';
import { stageManualCapture } from '../lib/manual-capture.ts';

test('upload distinguishes saved Journal from staged files and rejects a contradictory receipt', async t => {
  const files = ['acquisition-manifest.json', 'orders.json', 'transactions.json']
    .map(name => new File(['{}'], name, { type: 'application/json' }));
  const receipt = { contract_version: 'onejournal.manual-capture-upload.v1',
    state: 'journal_saved', scope: 'activity', manifest_sha256: 'a'.repeat(64),
    replayed: false, journal_written: true, financial_publication_authorized: false, new_records: 3 };
  const fetch = t.mock.method(globalThis, 'fetch', async (path, init) => {
    assert.equal(path, '/api/v1/local-owner/manual-capture');
    assert.equal(init.credentials, 'same-origin');
    assert.deepEqual(JSON.parse(init.body).files.map(f => f.name), files.map(f => f.name));
    return Response.json(receipt, { status: 202 });
  });
  assert.equal((await stageManualCapture(files)).state, 'journal_saved');
  fetch.mock.mockImplementation(async () => Response.json({ ...receipt,
    state: 'verified_and_staged', journal_written: false }));
  assert.equal((await stageManualCapture(files)).state, 'verified_and_staged');
  fetch.mock.mockImplementation(async () => Response.json({ ...receipt, journal_written: false }));
  await assert.rejects(stageManualCapture(files), /receipt could not be verified/);
});
