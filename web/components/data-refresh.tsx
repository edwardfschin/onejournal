'use client';
import * as React from 'react';
import { fetchRefreshStatus, requestRefresh, type RefreshStatus } from '@/lib/data-refresh';

const labels = {
  queued: 'Refresh requested. Waiting for the broker connection.',
  capturing: 'Downloading current positions. Your saved reports are unchanged.',
  captured: 'Download received. Validation and review are required before updating your reports.',
  closed: 'Refresh review closed. Check the saved release date for published data.',
  failed: 'Refresh stopped. Your saved reports are unchanged.',
};

export default function DataRefresh() {
  const [status, setStatus] = React.useState<RefreshStatus | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  // Keep the same identity after an uncertain response; retry cannot duplicate.
  const operation = React.useRef<string | null>(null);
  async function check() {
    setBusy(true);
    try { setStatus(await fetchRefreshStatus()); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Refresh status is unavailable.'); }
    finally { setBusy(false); }
  }
  React.useEffect(() => { void check(); }, []);
  async function refresh() {
    if (!status?.enabled) return;
    setBusy(true);
    operation.current ??= crypto.randomUUID();
    try {
      const latest = await requestRefresh(operation.current);
      setStatus({ ...status, latest }); setError(''); operation.current = null;
    } catch (e) { setError(e instanceof Error ? e.message : 'Refresh was not confirmed.'); }
    finally { setBusy(false); }
  }
  const pending = status?.latest && ['queued', 'capturing', 'captured'].includes(status.latest.state);
  const provider = status?.provider === 'schwab' ? 'Schwab' : status?.provider ?? 'Schwab';
  return <section className="panel report-section" aria-labelledby="refresh-heading">
    <h2 id="refresh-heading">Refresh from {provider}</h2>
    <p>Request the latest current positions. Historical backfill is separate. A download does not automatically replace your saved reports.</p>
    <div className="report-filter-actions">
      <button className="report-download" type="button" disabled={busy || !status?.enabled || Boolean(pending) || Boolean(error)} onClick={() => void refresh()}>Refresh from {provider}</button>
      <button className="report-download" type="button" disabled={busy} onClick={() => void check()}>Check refresh status</button>
    </div>
    <p role="status" aria-live="polite">{busy ? 'Checking refresh…' : status?.enabled === false
      ? 'The broker refresh connection is not activated yet. Reload saved data still reads the current saved release.'
      : status?.latest ? labels[status.latest.state] : status ? 'No refresh has been requested.' : 'Refresh status has not been verified.'}</p>
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
