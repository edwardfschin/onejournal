'use client';

import Link from 'next/link';
import { CircleAlert, FileSpreadsheet, LockKeyhole, RefreshCw } from 'lucide-react';
import * as React from 'react';
import { fetchRealizedHistory, fetchReportAccounts, fetchReportSymbols, type AccountBreakdown, type RealizedItem, type SymbolBreakdown } from '@/lib/local-owner-reports';
import { LOCAL_ROUTES } from '@/lib/routes';

function money(value: string | null, currency: string) {
  return value === null ? "Unavailable" : new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(value));
}

export default function LocalReportsPage() {
  const [accounts, setAccounts] = React.useState<AccountBreakdown[]>([]);
  const [symbols, setSymbols] = React.useState<SymbolBreakdown[]>([]);
  const [history, setHistory] = React.useState<RealizedItem[]>([]);
  const [from, setFrom] = React.useState('');
  const [to, setTo] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    void Promise.all([fetchReportAccounts(), fetchReportSymbols()])
      .then(([a, s]) => {
        setAccounts(a.accounts);
        setSymbols(s.symbols);
      })
      .catch(() => setError('The accepted reporting release is unavailable. No current or historical values are substituted.'))
      .finally(() => setLoading(false));
  }, []);

  async function loadHistory(event: { preventDefault: () => void }) {
    event.preventDefault();
    if (!from || !to) return;
    setError(null);
    try {
      const value = await fetchRealizedHistory(from, to);
      setHistory(value.items);
    } catch {
      setHistory([]);
      setError('That reporting range is unavailable or incomplete. No zero value was assumed.');
    }
  }

  return (
    <main className="app-shell local-portfolio-route">
      <section className="workspace">
        <header className="topbar">
          <div className="brand-mark">
            <span className="brand-glyph">1</span>
            <span className="brand-wordmark">OneJournal</span>
          </div>
          <div className="topbar-actions">
            <span className="local-pill">
              <LockKeyhole aria-hidden="true" /> Local owner
            </span>
            <Link className="nav-item" href={LOCAL_ROUTES.portfolio}>Portfolio</Link>
          </div>
        </header>
        <output className="mode-banner local-portfolio-banner">
          <span><FileSpreadsheet aria-hidden="true" /> Bounded reporting authority</span>
          <p>Only an exact owner-accepted report release can supply breakdowns, history, or exports.</p>
        </output>
        <div className="content-frame">
          <div className="page-heading portfolio-heading">
            <div>
              <p className="eyebrow">Reports · private local owner</p>
              <h1>Breakdowns that keep uncertainty visible.</h1>
              <p className="heading-copy">
                Current valuation and bounded realized history remain separate unless their scopes match exactly.
              </p>
            </div>
          </div>
          {loading ? (
            <section className="panel local-portfolio-state">
              <RefreshCw className="local-spinner" aria-hidden="true" />
              <div>
                <strong>Checking the accepted reporting release</strong>
                <p>No cached or synthetic report is shown.</p>
              </div>
            </section>
          ) : null}
          {error ? (
            <section className="panel local-portfolio-state is-unavailable" role="alert">
              <CircleAlert aria-hidden="true" />
              <div>
                <strong>Reporting unavailable</strong>
                <p>{error}</p>
              </div>
            </section>
          ) : null}
          {!loading && !error ? (
            <>
              <section className="local-metric-grid">
                {accounts.map((row) => (
                  <article className="metric-card portfolio-stat" key={`${row.account_alias}-${row.currency}`}>
                    <div className="card-label">
                      <span>{row.account_alias} · current value</span>
                    </div>
                    <p className="metric-value small">{money(row.broker_market_value, row.currency)}</p>
                    <p className="metric-context">{row.position_count} positions · {row.broker_market_value_status}</p>
                  </article>
                ))}
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Current symbols</p>
                    <h2>Broker-current breakdown</h2>
                  </div>
                </div>
                <div className="local-holdings-list">
                  {symbols.map((row) => (
                    <article className="local-holding-row" key={`${row.symbol}-${row.currency}`}>
                      <span className="symbol-tile">{row.symbol.slice(0, 1)}</span>
                      <span className="local-holding-name">
                        <strong>{row.symbol}</strong>
                        <small>{row.position_count} positions</small>
                      </span>
                      <span className="holding-cell">
                        <small>Market value</small>
                        <strong>{money(row.broker_market_value, row.currency)}</strong>
                      </span>
                      <span className="holding-cell">
                        <small>Unrealized P&amp;L</small>
                        <strong>{money(row.unrealized_pnl, row.currency)}</strong>
                      </span>
                    </article>
                  ))}
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Realized history</p>
                    <h2>Accepted date range only</h2>
                  </div>
                </div>
                <form className="local-report-filter" onSubmit={loadHistory}>
                  <label>From
                    <input aria-label="From market date" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
                  </label>
                  <label>To
                    <input aria-label="To market date" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
                  </label>
                  <button className="primary-action" type="submit">Load history</button>
                </form>
                {history.map((item) => (
                  <div className="local-holding-row" key={item.item_uid}>
                    <span className="symbol-tile violet">{item.symbol.slice(0, 1)}</span>
                    <span className="local-holding-name">
                      <strong>{item.symbol}</strong>
                      <small>{item.close_market_date} · {item.account_alias}</small>
                    </span>
                    <span className="holding-cell">
                      <small>Realized P&amp;L</small>
                      <strong>{money(item.realized_pnl, item.currency)}</strong>
                    </span>
                  </div>
                ))}
              </section>
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}
