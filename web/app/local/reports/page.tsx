'use client';

import Link from 'next/link';
import { CircleAlert, Download, FileSpreadsheet, LockKeyhole, RefreshCw } from 'lucide-react';
import * as React from 'react';
import {
  fetchRealizedHistory, fetchReportAccounts, fetchReportCsv, fetchReportSymbols, formatReportMoney,
  type AccountBreakdown, type AccountReport, type HistoryFilters, type HistoryReport, type Quality,
  type ReportContext, type SymbolBreakdown, type SymbolReport,
} from '@/lib/local-owner-reports';
import { LOCAL_ROUTES } from '@/lib/routes';

const qualityLabels: Record<Quality, string> = {
  valid: 'Complete for this selection', stale: 'Stale data', incomplete: 'Partial results',
  reconciliation_pending: 'Reconciliation pending', unavailable: 'Unavailable', failed: 'Report failed',
};
const reasonLabels: Record<string, string> = {
  opening_history_missing: 'Opening history missing',
  position_reconciliation_incomplete: 'Position reconciliation incomplete',
  lifecycle_review_required: 'Lifecycle review needed',
  outside_accepted_coverage: 'Dates outside the accepted coverage',
  metric_unavailable: 'One or more metrics unavailable',
};
function label(value: string) { return reasonLabels[value] ?? value.replaceAll('_', ' '); }
function readable(report: ReportContext) { return !['unavailable', 'failed'].includes(report.metadata.quality); }
function message(error: unknown) { return error instanceof Error ? error.message : 'The reporting service is unavailable. Try again.'; }

function QualitySummary({ report, unit }: { report: ReportContext; unit: string }) {
  const { metadata, counts } = report;
  return (
    <section className={`bounded-report-quality ${metadata.quality}`} aria-label="Report quality" aria-live="polite">
      <strong>{qualityLabels[metadata.quality]}</strong>
      <p>{counts.available_count} available · {counts.unavailable_count} withheld · {counts.reconciliation_pending_count} pending · {counts.processed_count} {unit} checked</p>
      {Object.entries(metadata.reason_counts).length ? (
        <ul>{Object.entries(metadata.reason_counts).map(([reason, count]) => <li key={reason}>{label(reason)}: {count}</li>)}</ul>
      ) : null}
    </section>
  );
}

function BreakdownTable({ rows, symbols = false }: { rows: (AccountBreakdown | SymbolBreakdown)[]; symbols?: boolean }) {
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- The scroll region needs keyboard focus so every metric remains reachable.
    <section className="report-table-region" aria-label={symbols ? 'Symbol breakdown, scroll for all metrics' : 'Account breakdown, scroll for all metrics'} tabIndex={0}>
      <table className="report-table">
        <caption className="sr-only">{symbols ? 'Current symbol breakdown' : 'Current account breakdown'}</caption>
        <thead><tr>{symbols ? <th scope="col">Symbol</th> : null}<th scope="col">Account</th><th scope="col">Positions</th><th scope="col">Cost basis</th><th scope="col">Market value</th><th scope="col">Unrealized P&amp;L</th></tr></thead>
        <tbody>{rows.map((row) => (
          <tr key={`${row.account_alias}-${row.symbol ?? 'account'}-${row.currency}`}>
            {symbols ? <th scope="row">{row.symbol}</th> : null}
            {symbols ? <td>{row.account_alias}</td> : <th scope="row">{row.account_alias}</th>}
            <td>{row.position_count}</td>
            {(['open_cost_basis', 'broker_market_value', 'unrealized_pnl'] as const).map((metric) => (
              <td key={metric}><span title={row[metric] ?? undefined}>{formatReportMoney(row[metric], row.currency)}</span><small>{row[`${metric}_status`] === 'valid' ? 'Available' : qualityLabels[row[`${metric}_status`]]}</small></td>
            ))}
          </tr>
        ))}</tbody>
      </table>
    </section>
  );
}

export default function LocalReportsPage() {
  const [current, setCurrent] = React.useState<{ accounts: AccountReport; symbols: SymbolReport } | null>(null);
  const [history, setHistory] = React.useState<{ report: HistoryReport; filters: HistoryFilters } | null>(null);
  const [filters, setFilters] = React.useState<HistoryFilters>({ from: '', to: '', accountAlias: '', symbol: '' });
  const [error, setError] = React.useState<string | null>(null);
  const [historyError, setHistoryError] = React.useState<string | null>(null);
  const [downloadError, setDownloadError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [downloading, setDownloading] = React.useState(false);
  const historyRequest = React.useRef<AbortController | null>(null);

  React.useEffect(() => {
    const controller = new AbortController();
    void Promise.all([fetchReportAccounts(controller.signal), fetchReportSymbols(controller.signal)])
      .then(([accounts, symbols]) => {
        if (controller.signal.aborted) return;
        if (accounts.metadata.report_release_fingerprint !== symbols.metadata.report_release_fingerprint
          || accounts.metadata.current_valuation_asof !== symbols.metadata.current_valuation_asof
          || accounts.metadata.current_valuation_asof === null) throw new Error('The current reports do not match. Reload after checking the reporting service.');
        setCurrent({ accounts, symbols });
        setFilters({ from: accounts.metadata.coverage_start_date, to: accounts.metadata.coverage_end_date, accountAlias: '', symbol: '' });
      })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(message(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); historyRequest.current?.abort(); };
  }, []);

  function changeFilter(key: keyof HistoryFilters, value: string) {
    historyRequest.current?.abort();
    setHistoryLoading(false);
    setHistory(null);
    setHistoryError(null);
    setDownloadError(null);
    setFilters((previous) => ({ ...previous, [key]: value }));
  }

  async function loadHistory(event: { preventDefault(): void }) {
    event.preventDefault();
    if (!current) return;
    historyRequest.current?.abort();
    setHistory(null);
    setHistoryError(null);
    setDownloadError(null);
    const selection = { ...filters, symbol: filters.symbol.trim() };
    if (!selection.from || !selection.to || selection.from > selection.to) {
      setHistoryError('Choose a start date on or before the end date.');
      return;
    }
    const controller = new AbortController();
    historyRequest.current = controller;
    setHistoryLoading(true);
    try {
      const report = await fetchRealizedHistory(selection, controller.signal);
      if (controller.signal.aborted) return;
      if (report.metadata.report_release_fingerprint !== current.accounts.metadata.report_release_fingerprint) throw new Error('The reporting release changed. Reload this page before selecting history.');
      setHistory({ report, filters: selection });
    } catch (cause) {
      if (!controller.signal.aborted) setHistoryError(message(cause));
    } finally {
      if (!controller.signal.aborted) setHistoryLoading(false);
    }
  }

  async function download(kind: 'positions' | 'history') {
    if (!current || (kind === 'history' && (!history || !readable(history.report)))) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await fetchReportCsv(current.accounts, kind === 'history' && history ? history : undefined);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = kind === 'positions' ? 'onejournal-current-positions.csv' : 'onejournal-realized-history.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setDownloadError(message(cause));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <main className="app-shell local-reports-route">
      <section className="workspace">
        <header className="topbar">
          <div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div>
          <nav className="report-navigation" aria-label="Private workspace">
            <span className="report-owner"><LockKeyhole aria-hidden="true" /> Local owner</span>
            <Link href={LOCAL_ROUTES.portfolio}>Portfolio</Link><Link href={LOCAL_ROUTES.trades}>Trades</Link><Link href={LOCAL_ROUTES.journal}>Journal</Link>
          </nav>
        </header>
        <div className="mode-banner local-portfolio-banner"><span><FileSpreadsheet aria-hidden="true" /> Private reports</span><p>Saved snapshots and accepted history. Updates are manually released.</p></div>
        <div className="content-frame">
          <div className="page-heading"><div><p className="eyebrow">Reports</p><h1>Your results, with the full context.</h1><p className="heading-copy">Current holdings and realized history show their own dates and coverage.</p></div></div>
          {loading ? <section className="panel local-portfolio-state" aria-live="polite"><RefreshCw className="local-spinner" aria-hidden="true" /><div><strong>Loading your saved reports</strong><p>Checking the accepted release.</p></div></section> : null}
          {error ? <section className="panel local-portfolio-state is-unavailable" role="alert"><CircleAlert aria-hidden="true" /><div><strong>Reporting unavailable</strong><p>{error}</p></div></section> : null}
          {current ? (
            <>
              <section className="panel report-section">
                <div className="report-section-heading"><div><p className="eyebrow">Current portfolio</p><h2>Account breakdown</h2><p>Snapshot date: {current.accounts.metadata.current_valuation_asof}. This is a saved snapshot, not a live quote.</p></div><button className="report-download" type="button" onClick={() => void download('positions')} disabled={downloading || !readable(current.accounts)}><Download aria-hidden="true" /> Download positions CSV</button></div>
                <QualitySummary report={current.accounts} unit="account/currency groups" />
                {readable(current.accounts) && current.accounts.accounts.length ? <BreakdownTable rows={current.accounts.accounts} /> : <p className="report-empty">No account values are available for this release.</p>}
              </section>
              <section className="panel report-section">
                <div className="report-section-heading"><div><p className="eyebrow">Current portfolio</p><h2>Symbol breakdown</h2><p>Equities use their symbol; options use their underlying symbol. Currencies remain separate.</p></div></div>
                <QualitySummary report={current.symbols} unit="symbol/currency groups" />
                {readable(current.symbols) && current.symbols.symbols.length ? <BreakdownTable rows={current.symbols.symbols} symbols /> : <p className="report-empty">No symbol values are available for this release.</p>}
              </section>
              <section className="panel report-section" aria-busy={historyLoading}>
                <div className="report-section-heading"><div><p className="eyebrow">Realized P&amp;L</p><h2>Trade history</h2><p>Accepted coverage: {current.accounts.metadata.coverage_start_date} through {current.accounts.metadata.coverage_end_date}. Dates use the New York market day.</p></div></div>
                <form className="local-report-filter" onSubmit={(event) => void loadHistory(event)}>
                  <label>From<input type="date" required disabled={downloading} value={filters.from} min={current.accounts.metadata.coverage_start_date} max={current.accounts.metadata.coverage_end_date} onChange={(event) => changeFilter('from', event.target.value)} /></label>
                  <label>To<input type="date" required disabled={downloading} value={filters.to} min={filters.from || current.accounts.metadata.coverage_start_date} max={current.accounts.metadata.coverage_end_date} onChange={(event) => changeFilter('to', event.target.value)} /></label>
                  <label>Account<select aria-label="Account" disabled={downloading} value={filters.accountAlias} onChange={(event) => changeFilter('accountAlias', event.target.value)}><option value="">All admitted accounts</option>{[...new Set(current.accounts.accounts.map((row) => row.account_alias))].map((alias) => <option key={alias} value={alias}>{alias}</option>)}</select></label>
                  <label>Symbol<input type="text" disabled={downloading} list="report-symbols" maxLength={64} placeholder="All admitted symbols" value={filters.symbol} onChange={(event) => changeFilter('symbol', event.target.value)} /></label>
                  <datalist id="report-symbols">{[...new Set(current.symbols.symbols.map((row) => row.symbol))].map((symbol) => <option key={symbol} value={symbol}>{symbol}</option>)}</datalist>
                  <button className="primary-action" type="submit" disabled={historyLoading || downloading}>{historyLoading ? 'Loading…' : 'Load history'}</button>
                </form>
                {historyError ? <p className="report-error" role="alert">{historyError}</p> : null}
                {historyLoading ? <output className="report-empty">Loading the selected history…</output> : null}
                {!history && !historyLoading && !historyError ? <p className="report-empty">Choose your filters, then load history.</p> : null}
                {history ? (
                  <>
                    <p className="report-selection">Loaded: {history.filters.from} through {history.filters.to} · {history.filters.accountAlias || 'All admitted accounts'} · {history.filters.symbol || 'All admitted symbols'}</p>
                    <QualitySummary report={history.report} unit="allocations/scopes" />
                    {readable(history.report) ? (
                      <>
                        {history.report.items.length ? (
                          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Keyboard users must be able to scroll the history columns.
                          <section className="report-table-region" aria-label="Realized history, scroll for all columns" tabIndex={0}><table className="report-table"><caption className="sr-only">Realized results for the loaded filters</caption><thead><tr><th scope="col">Market date</th><th scope="col">Account</th><th scope="col">Symbol</th><th scope="col">Instrument</th><th scope="col">Realized P&amp;L</th></tr></thead><tbody>{history.report.items.map((item) => <tr key={item.item_uid}><td>{item.close_market_date}</td><td>{item.account_alias}</td><th scope="row">{item.symbol}</th><td>{item.asset_class}</td><td><span title={item.realized_pnl}>{formatReportMoney(item.realized_pnl, item.currency)}</span></td></tr>)}</tbody></table></section>
                        ) : <p className="report-empty">{history.report.metadata.quality === 'valid' ? 'No realized activity in this fully covered selection.' : 'No admitted results in this selection. Withheld scopes remain unresolved.'}</p>}
                        <button className="report-download" type="button" onClick={() => void download('history')} disabled={downloading}><Download aria-hidden="true" /> Download this history CSV</button>
                        {history.report.metadata.quality !== 'valid' ? <p className="report-note">The CSV contains admitted records only. The withheld and pending counts above still apply.</p> : null}
                      </>
                    ) : <p className="report-empty">No financial result or download is available for this selection.</p>}
                  </>
                ) : null}
              </section>
              {downloadError ? <p className="report-error" role="alert">{downloadError}</p> : null}
              {downloading ? <output className="report-note">Checking the download against the loaded report…</output> : null}
              <section className="panel report-section report-context">
                <h2>What these reports cover</h2>
                <p>Total P&amp;L is unavailable: realized history and current holdings do not cover the same scope. Partial history is never added to a wider unrealized total.</p>
                <p>Amounts are rounded to two decimal places for display. CSV downloads preserve the stored decimal text.</p>
                <details><summary>Report source and acceptance</summary><dl><dt>Release</dt><dd>{current.accounts.metadata.report_release_uid}</dd><dt>Prepared (UTC)</dt><dd>{current.accounts.metadata.generated_at_utc}</dd><dt>Accepted (UTC)</dt><dd>{current.accounts.metadata.owner_accepted_at_utc}</dd><dt>Calculation</dt><dd>{current.accounts.metadata.calculation_version}</dd></dl></details>
              </section>
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}
