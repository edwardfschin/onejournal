import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fetchRealizedHistory, fetchReportCsv, formatReportMoney } from '../lib/local-owner-reports.ts';

const filters = { from: '2026-09-01', to: '2026-09-30', accountAlias: 'Primary', symbol: 'S00' };
function report() {
  return {
    metadata: {
      contract_version: 'onejournal.phase1-report-release.v1', report_release_uid: 'synthetic-release',
      report_release_fingerprint: 'a'.repeat(64), selection_fingerprint: 'b'.repeat(64),
      coverage_start_date: '2026-09-01', coverage_end_date: '2026-09-30', current_valuation_asof: null,
      calculation_version: 'synthetic-v1', generated_at_utc: '2026-09-04T20:00:00Z', owner_accepted_at_utc: '2026-09-04T20:00:00Z',
      quality: 'incomplete', reason_counts: { opening_history_missing: 1 },
    },
    counts: { processed_count: 2, available_count: 1, unavailable_count: 1, reconciliation_pending_count: 0 },
    items: [{ item_uid: 'synthetic-item', account_alias: 'Primary', symbol: 'S00', asset_class: 'equity', close_market_date: '2026-09-04', currency: 'USD', realized_pnl: '12.345678901234567890123456789', item_status: 'valid', reason_codes: [], calculation_version: 'synthetic-v1' }],
  };
}
function csvResponse(value, changes = {}) {
  return new Response('realized_pnl\n12.345678901234567890123456789\n', { headers: {
    'Content-Type': 'text/csv',
    'X-OneJournal-Report-Release-Fingerprint': value.metadata.report_release_fingerprint,
    'X-OneJournal-Selection-Fingerprint': value.metadata.selection_fingerprint,
    'X-OneJournal-Quality': value.metadata.quality,
    'X-OneJournal-Reason-Counts': JSON.stringify(value.metadata.reason_counts),
    'X-OneJournal-Processed-Count': String(value.counts.processed_count),
    'X-OneJournal-Available-Count': String(value.counts.available_count),
    'X-OneJournal-Unavailable-Count': String(value.counts.unavailable_count),
    'X-OneJournal-Reconciliation-Pending-Count': String(value.counts.reconciliation_pending_count),
    ...changes,
  } });
}

test('display rounding preserves large decimal amounts and missing is never zero', () => {
  assert.equal(formatReportMoney('9007199254740993.995', 'USD'), 'USD 9,007,199,254,740,994.00');
  assert.equal(formatReportMoney('-0.005', 'USD'), 'USD -0.01');
  assert.equal(formatReportMoney('0', 'USD'), 'USD 0.00');
  assert.equal(formatReportMoney(null, 'USD'), 'Unavailable');
});

test('HTTP 200 retains unavailable quality rather than presenting an empty valid result', async (t) => {
  const value = report();
  value.metadata.quality = 'unavailable';
  value.metadata.reason_counts = { outside_accepted_coverage: 1 };
  value.counts = { processed_count: 1, available_count: 0, unavailable_count: 1, reconciliation_pending_count: 0 };
  value.items = [];
  t.mock.method(globalThis, 'fetch', async () => Response.json(value));
  assert.equal((await fetchRealizedHistory(filters)).metadata.quality, 'unavailable');
});

test('inconsistent counts, malformed amounts and unavailable values fail closed', async (t) => {
  for (const change of [
    (value) => { value.counts.available_count = 3; },
    (value) => { value.items[0].realized_pnl = 'NaN'; },
    (value) => { value.metadata.quality = 'unavailable'; },
    (value) => { value.metadata.quality = 'valid'; },
  ]) {
    const value = report();
    change(value);
    const mock = t.mock.method(globalThis, 'fetch', async () => Response.json(value));
    await assert.rejects(fetchRealizedHistory(filters), /invalid report/);
    mock.mock.restore();
  }
});

test('JSON and CSV use the same submitted filters and preserve exact decimal text', async (t) => {
  const value = report();
  const paths = [];
  t.mock.method(globalThis, 'fetch', async (path) => {
    paths.push(path);
    return path.includes('.csv?') ? csvResponse(value) : Response.json(value);
  });
  const loaded = await fetchRealizedHistory(filters);
  const blob = await fetchReportCsv(loaded, { report: loaded, filters });
  assert.equal(new URL(paths[0], 'http://localhost').search, new URL(paths[1], 'http://localhost').search);
  assert.match(await blob.text(), /12\.345678901234567890123456789/);
});

test('downloads reject changed release, selection, counts, reasons, or unavailable quality', async (t) => {
  const value = report();
  for (const changes of [
    { 'X-OneJournal-Report-Release-Fingerprint': 'c'.repeat(64) },
    { 'X-OneJournal-Selection-Fingerprint': 'c'.repeat(64) },
    { 'X-OneJournal-Available-Count': '0' },
    { 'X-OneJournal-Reason-Counts': '{}' },
    { 'X-OneJournal-Quality': 'unavailable' },
  ]) {
    const mock = t.mock.method(globalThis, 'fetch', async () => csvResponse(value, changes));
    await assert.rejects(fetchReportCsv(value, { report: value, filters }));
    mock.mock.restore();
  }
});
