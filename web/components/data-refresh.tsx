'use client';
import * as React from 'react';
import { manualCaptureAvailable, stageManualCapture } from '@/lib/manual-capture';

export default function DataRefresh() {
  const [enabled, setEnabled] = React.useState(false);
  const [checked, setChecked] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [selected, setSelected] = React.useState<File[]>([]);
  const [message, setMessage] = React.useState('');
  const [error, setError] = React.useState('');
  const input = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    void manualCaptureAvailable().then(value => { setEnabled(value); setChecked(true); })
      .catch(() => { setChecked(true); setError('Capture upload status is unavailable. Saved results are unchanged.'); });
  }, []);
  async function upload() {
    setBusy(true); setError(''); setMessage('');
    try {
      const receipt = await stageManualCapture(selected);
      setMessage(receipt.state === 'journal_saved'
        ? receipt.replayed ? 'This package is already in your Journal. No duplicate trades were added.'
          : 'Your Journal is updated. Open Trades to review the activity or Journal to write your notes.'
        : receipt.replayed
        ? 'This exact package was already received. Your saved results are unchanged.'
        : 'The package was verified and saved privately on this Mac. Portfolio and Reports have not changed yet.');
      setSelected([]);
      if (input.current) input.current.value = '';
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The package could not be verified. Saved results are unchanged.');
    } finally { setBusy(false); }
  }
  return <section className="panel report-section" aria-labelledby="refresh-heading">
    <h2 id="refresh-heading">Refresh from Schwab</h2>
    <p>Upload your verified Schwab activity package to add new trades to your saved Journal when Journal saving is enabled. Repeated uploads do not duplicate trades. Portfolio and Reports keep their separately accepted figures.</p>
    <label className="manual-capture-label" htmlFor="manual-capture-files">Capture manifest and response files</label>
    <input className="manual-capture-files" id="manual-capture-files" ref={input} type="file" accept=".json,application/json" multiple
      disabled={!enabled || busy} onChange={event => setSelected(Array.from(event.target.files ?? []))} />
    <div className="report-filter-actions">
      <button className="report-download" type="button" disabled={!enabled || busy || selected.length === 0}
        onClick={() => void upload()}>Upload activity package</button>
    </div>
    <output aria-live="polite">{busy ? 'Checking and saving your activity…' : message ||
      (checked && !enabled ? 'Manual package upload is not configured yet. Your saved results are unchanged.' :
        !checked ? 'Checking whether private upload is available…' : 'Choose the package files to verify.')}</output>
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
