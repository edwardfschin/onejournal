'use client';
import * as React from 'react';
import { financialUploadAvailable, publishFinancialUpload } from '@/lib/financial-upload';

export default function DataRefresh({ onPublished }: { onPublished?: () => void }) {
  const [enabled, setEnabled] = React.useState(false);
  const [checked, setChecked] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [positions, setPositions] = React.useState<File[]>([]);
  const [activity, setActivity] = React.useState<File[]>([]);
  const [message, setMessage] = React.useState('');
  const [error, setError] = React.useState('');
  const positionInput = React.useRef<HTMLInputElement>(null);
  const activityInput = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    void financialUploadAvailable().then(value => { setEnabled(value); setChecked(true); })
      .catch(() => { setChecked(true); setError('Capture upload status is unavailable. Saved results are unchanged.'); });
  }, []);
  async function upload() {
    setBusy(true); setError(''); setMessage('');
    try {
      const receipt = await publishFinancialUpload(positions, activity);
      setMessage(`${receipt.replayed ? 'Already saved; no duplicates added.' : 'Journal, Portfolio and Reports updated.'} Portfolio: ${receipt.portfolio_asof}. Reports through: ${receipt.coverage_end_date} (New York dates). ${receipt.reportable_count} reportable results; ${receipt.withheld_count} withheld. Saved prices, not live quotes.`);
      setPositions([]); setActivity([]);
      if (positionInput.current) positionInput.current.value = '';
      if (activityInput.current) activityInput.current.value = '';
      onPublished?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Completion could not be confirmed. Reload saved data before trying again.');
    } finally { setBusy(false); }
  }
  return <section className="panel report-section" aria-labelledby="refresh-heading">
    <h2 id="refresh-heading">Update Journal, Portfolio and Reports</h2>
    <p>Upload both verified Schwab packages below. OneJournal checks them, keeps a rollback copy and automatically saves the update. New activity is added without duplicating earlier trades. Results missing evidence remain withheld.</p>
    <p>This upload does not download from Schwab. Use the verified JSON packages—not a statement CSV.</p>
    <label className="manual-capture-label" htmlFor="position-capture-files">1. Current positions — manifest and positions response (2 JSON files)</label>
    <input className="manual-capture-files" id="position-capture-files" ref={positionInput} type="file" accept=".json,application/json" multiple
      disabled={!enabled || busy} onChange={event => setPositions(Array.from(event.target.files ?? []))} />
    <label className="manual-capture-label" htmlFor="activity-capture-files">2. New activity — manifest, orders and transactions (3 JSON files)</label>
    <input className="manual-capture-files" id="activity-capture-files" ref={activityInput} type="file" accept=".json,application/json" multiple
      disabled={!enabled || busy} onChange={event => setActivity(Array.from(event.target.files ?? []))} />
    <div className="report-filter-actions">
      <button className="report-download" type="button" disabled={!enabled || busy || positions.length !== 2 || activity.length !== 3}
        onClick={() => void upload()}>Upload and update</button>
    </div>
    <output aria-live="polite">{busy ? 'Checking both packages and preparing your update. Keep this page open…' : message ||
      (checked && !enabled ? 'Automatic financial upload is not enabled on this site. Your saved results are unchanged.' :
        !checked ? 'Checking whether private upload is available…' : 'Choose both packages, then select Upload and update.')}</output>
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
