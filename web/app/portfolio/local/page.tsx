'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Activity, BookOpenText, BriefcaseBusiness, CheckCircle2, CircleAlert,
  Database, FileChartColumn, LayoutDashboard, LoaderCircle, LockKeyhole, Menu,
  RefreshCw, Search, Settings, ShieldCheck,
} from 'lucide-react';

import {
  fetchBrokerCurrentPortfolio,
  type BrokerCurrentPortfolio,
  type BrokerCurrentPosition,
} from '@/lib/local-owner-portfolio';
import { LOCAL_ROUTES } from '@/lib/routes';

const navItems = [
  ['Today', LayoutDashboard, null],
  ['Portfolio', BriefcaseBusiness, LOCAL_ROUTES.portfolio],
  ['Trades', Activity, LOCAL_ROUTES.trades],
  ['Journal', BookOpenText, LOCAL_ROUTES.journal],
  ['Reports', FileChartColumn, null],
  ['Data', Database, null],
] as const;

function label(value: string) {
  return value.replaceAll('_', ' ');
}

function compactDecimal(value: string) {
  const [whole, fraction = ''] = value.split('.');
  const compactFraction = fraction.replace(/0+$/, '');
  return compactFraction ? `${whole}.${compactFraction}` : whole;
}

function roundedDecimalText(value: string, maximumPlaces: number, minimumPlaces: number) {
  const compact = compactDecimal(value);
  const negative = compact.startsWith('-');
  const unsigned = negative ? compact.slice(1) : compact;
  const [whole = '0', fraction = ''] = unsigned.split('.');
  const factor = BigInt(10) ** BigInt(maximumPlaces);
  const retained = fraction.slice(0, maximumPlaces).padEnd(maximumPlaces, '0');
  let scaled = BigInt(whole || '0') * factor + BigInt(retained || '0');
  if ((fraction[maximumPlaces] ?? '0') >= '5') scaled += BigInt(1);
  const digits = scaled.toString().padStart(maximumPlaces + 1, '0');
  const roundedWhole = maximumPlaces ? digits.slice(0, -maximumPlaces) : digits;
  let roundedFraction = maximumPlaces ? digits.slice(-maximumPlaces) : '';
  while (roundedFraction.length > minimumPlaces && roundedFraction.endsWith('0')) {
    roundedFraction = roundedFraction.slice(0, -1);
  }
  const sign = negative && scaled !== BigInt(0) ? '-' : '';
  return `${sign}${roundedWhole}${roundedFraction ? `.${roundedFraction}` : ''}`;
}

function money(value: string | null, currency: string) {
  if (value === null) return 'Unavailable';
  const compact = roundedDecimalText(value, 2, 2);
  const negative = compact.startsWith('-');
  const unsigned = negative ? compact.slice(1) : compact;
  const [whole, fraction] = unsigned.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${currency} ${negative ? '-' : ''}${grouped}.${fraction}`;
}

function shortDate(value: string) {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf())
    ? value
    : parsed.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
      });
}

function shortDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? value
    : parsed.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
      });
}

function positionName(position: BrokerCurrentPosition) {
  return position.asset_class === 'equity'
    ? position.symbol ?? position.instrument_key
    : position.underlying_symbol ?? position.instrument_key;
}

function positionDetail(position: BrokerCurrentPosition) {
  if (position.asset_class === 'equity') return 'Equity';
  return [
    position.expiry,
    position.strike ? roundedDecimalText(position.strike, 2, 2) : null,
    position.option_right,
  ]
    .filter(Boolean)
    .join(' · ');
}

function metricClass(value: string | null) {
  if (value === null) return 'is-unavailable';
  return compactDecimal(value).startsWith('-') ? 'negative' : 'positive';
}

export default function LocalOwnerPortfolioPage() {
  const [portfolio, setPortfolio] = useState<BrokerCurrentPortfolio | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadPortfolio() {
    setLoading(true);
    setError(null);
    try {
      setPortfolio(await fetchBrokerCurrentPortfolio());
    } catch {
      setPortfolio(null);
      setError(
        'The accepted broker-current portfolio is unavailable. No cached, synthetic, or historical FIFO values were substituted.',
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    void fetchBrokerCurrentPortfolio()
      .then((value) => {
        if (active) setPortfolio(value);
      })
      .catch(() => {
        if (active) {
          setError(
            'The accepted broker-current portfolio is unavailable. No cached, synthetic, or historical FIFO values were substituted.',
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const counts = portfolio?.counts;

  return (
    <main className="app-shell local-portfolio-route">
      <aside className="desktop-rail" aria-label="Primary navigation">
        <div className="brand-mark">
          <span className="brand-glyph">1</span>
          <span className="brand-wordmark">OneJournal</span>
        </div>
        <nav className="nav-stack">
          {navItems.map(([itemLabel, Icon, href]) =>
            href ? (
              <Link
                className={`nav-item ${itemLabel === 'Portfolio' ? 'is-active' : ''}`}
                href={href}
                key={itemLabel}
                aria-current={itemLabel === 'Portfolio' ? 'page' : undefined}
              >
                <Icon aria-hidden="true" />
                <span>{itemLabel}</span>
              </Link>
            ) : (
              <span className="nav-item is-disabled" key={itemLabel} aria-disabled="true">
                <Icon aria-hidden="true" />
                <span>{itemLabel}</span>
              </span>
            ),
          )}
        </nav>
        <div className="rail-footer">
          <span className="nav-item is-disabled" aria-disabled="true">
            <Settings aria-hidden="true" />
            <span>Settings</span>
          </span>
          <div className="owner-chip">
            <span className="owner-avatar">ES</span>
            <span>
              <strong>Private owner</strong>
              <small>Local application</small>
            </span>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu" type="button" aria-label="Open navigation">
            <Menu aria-hidden="true" />
          </button>
          <label className="search-box">
            <Search aria-hidden="true" />
            <span className="sr-only">Portfolio scope</span>
            <input value="Current broker positions" readOnly aria-readonly="true" />
          </label>
          <div className="topbar-actions">
            <span className="local-pill">
              <LockKeyhole aria-hidden="true" /> Local owner
            </span>
          </div>
        </header>

        <output className="mode-banner local-portfolio-banner">
          <span>
            <ShieldCheck aria-hidden="true" /> Broker-current authority
          </span>
          <p>
            {portfolio
              ? `Owner-accepted ${portfolio.metadata.source_broker} result · as of ${shortDate(portfolio.metadata.asof)}`
              : 'No fallback data is shown when the exact accepted result is unavailable.'}
          </p>
        </output>

        <div className="content-frame">
          <div className="page-heading portfolio-heading">
            <div>
              <p className="eyebrow">Portfolio · private local owner</p>
              <h1>Current positions, with their authority intact.</h1>
              <p className="heading-copy">
                Broker-reconciled current valuation is kept separate from FIFO history and realized P&amp;L.
              </p>
            </div>
            {portfolio ? (
              <div className="asof-block">
                <span className="status-dot" />
                <span>
                  <small>Accepted as of</small>
                  <strong>{shortDate(portfolio.metadata.asof)}</strong>
                </span>
              </div>
            ) : null}
          </div>

          {loading ? (
            <section className="panel local-portfolio-state" aria-live="polite">
              <LoaderCircle className="local-spinner" aria-hidden="true" />
              <div>
                <strong>Loading the exact accepted valuation</strong>
                <p>No prior result is displayed while the authority check completes.</p>
              </div>
            </section>
          ) : null}

          {!loading && error ? (
            <section className="panel local-portfolio-state is-unavailable" role="alert">
              <CircleAlert aria-hidden="true" />
              <div>
                <strong>Authoritative portfolio unavailable</strong>
                <p>{error}</p>
              </div>
              <button className="quiet-button" type="button" onClick={() => void loadPortfolio()}>
                <RefreshCw aria-hidden="true" /> Retry
              </button>
            </section>
          ) : null}

          {portfolio && counts ? (
            <>
              <section className="authority-callout is-accepted" aria-label="Portfolio authority status">
                <span className="authority-icon">
                  <CheckCircle2 aria-hidden="true" />
                </span>
                <div>
                  <strong>Owner-accepted broker-current valuation</strong>
                  <p>
                    {counts.position_count} complete snapshot members · evaluated{' '}
                    {shortDateTime(portfolio.metadata.evaluated_at)} · accepted{' '}
                    {shortDateTime(portfolio.metadata.owner_accepted_at)} ·{' '}
                    {portfolio.metadata.basis_method}
                  </p>
                </div>
                <span className="local-acceptance-chip">Exact fingerprint match</span>
              </section>

              <section className="local-portfolio-summary" aria-label="Current portfolio totals">
                {portfolio.portfolio_totals.map((total) => (
                  <article className="metric-card local-total-card" key={`${total.currency}-market-value`}>
                    <div className="card-label">
                      <span>Portfolio market value</span>
                      <span className="quality-chip">
                        {portfolio.complete_portfolio_market_value_available
                          ? 'Complete'
                          : 'Unavailable'}
                      </span>
                    </div>
                    <p className="metric-value small">
                      {money(total.portfolio_market_value, total.currency)}
                    </p>
                    <p className="metric-context">
                      {counts.market_value_available_count}/{counts.position_count} positions available
                    </p>
                  </article>
                ))}
                {portfolio.portfolio_totals.map((total) => (
                  <article className="metric-card local-total-card" key={`${total.currency}-cost-basis`}>
                    <div className="card-label">
                      <span>Broker current cost basis</span>
                      <span className="quality-chip">
                        {portfolio.complete_portfolio_cost_basis_available
                          ? 'Complete'
                          : 'Unavailable'}
                      </span>
                    </div>
                    <p className="metric-value small">
                      {money(total.portfolio_cost_basis, total.currency)}
                    </p>
                    <p className="metric-context">
                      {counts.cost_basis_available_count}/{counts.position_count} positions available
                    </p>
                  </article>
                ))}
                {portfolio.portfolio_totals.map((total) => (
                  <article className="metric-card local-total-card" key={`${total.currency}-unrealized`}>
                    <div className="card-label">
                      <span>Broker current unrealized P&amp;L</span>
                      <span className="quality-chip">
                        {portfolio.complete_portfolio_unrealized_pnl_available
                          ? 'Reconciled'
                          : 'Unavailable'}
                      </span>
                    </div>
                    <p className={`metric-value small ${metricClass(total.portfolio_unrealized_pnl)}`}>
                      {money(total.portfolio_unrealized_pnl, total.currency)}
                    </p>
                    <p className="metric-context">
                      {counts.unrealized_pnl_available_count}/{counts.position_count} positions available
                    </p>
                  </article>
                ))}
                <article className="metric-card local-total-card local-count-card">
                  <div className="card-label">
                    <span>Current positions</span>
                    <BriefcaseBusiness aria-hidden="true" />
                  </div>
                  <p className="metric-value small">{counts.position_count}</p>
                  <p className="metric-context">Complete broker snapshot</p>
                </article>
              </section>

              <section className="panel local-holdings-panel">
                <div className="panel-header">
                  <div>
                    <p className="eyebrow">Accepted current snapshot</p>
                    <h2>{counts.position_count} broker-current positions</h2>
                  </div>
                  <span className="health-score">{portfolio.final_status}</span>
                </div>
                <div className="local-holdings-header" aria-hidden="true">
                  <span>Instrument</span>
                  <span>Quantity</span>
                  <span>Current basis</span>
                  <span>Market value</span>
                  <span>Unrealized P&amp;L</span>
                </div>
                <div className="local-holdings-list">
                  {portfolio.positions.map((position) => (
                    <article className="local-holding-row" key={position.instrument_key}>
                      <span className={`symbol-tile ${position.asset_class === 'option' ? 'violet' : ''}`}>
                        {positionName(position).slice(0, 1)}
                      </span>
                      <span className="local-holding-name">
                        <strong>{positionName(position)}</strong>
                        <small>{positionDetail(position)}</small>
                      </span>
                      <span className="local-holding-cell">
                        <small>Quantity</small>
                        <strong>{position.quantity ? compactDecimal(position.quantity) : 'Unavailable'}</strong>
                      </span>
                      <span className="local-holding-cell">
                        <small>Current basis</small>
                        <strong>{money(position.open_cost_basis, position.currency)}</strong>
                      </span>
                      <span className="local-holding-cell">
                        <small>Market value</small>
                        <strong>{money(position.broker_market_value, position.currency)}</strong>
                      </span>
                      <span className={`local-holding-cell ${metricClass(position.unrealized_pnl)}`}>
                        <small>Unrealized P&amp;L</small>
                        <strong>{money(position.unrealized_pnl, position.currency)}</strong>
                      </span>
                      <span className={`local-metric-state ${position.position_status}`}>
                        {label(position.position_status)}
                      </span>
                    </article>
                  ))}
                </div>
              </section>

              <section className="panel local-portfolio-lineage">
                <ShieldCheck aria-hidden="true" />
                <div>
                  <strong>Exact accepted lineage</strong>
                  <p>
                    Snapshot {portfolio.metadata.snapshot_uid} · valuation {portfolio.metadata.valuation_run_uid} ·
                    {' '}retrieved {shortDateTime(portfolio.metadata.retrieved_at)} · evaluated{' '}
                    {shortDateTime(portfolio.metadata.evaluated_at)}.
                  </p>
                </div>
              </section>
              <section className="panel journal-boundary">
                <LockKeyhole aria-hidden="true" />
                <p>
                  <strong>This view is not the historical FIFO 48/10 result.</strong> It does not fabricate lots,
                  realized P&amp;L, holding periods, or tax treatment. Missing authority makes the entire local view
                  unavailable rather than substituting a subtotal.
                </p>
              </section>
            </>
          ) : null}
        </div>
      </section>

      <nav className="mobile-nav" aria-label="Mobile navigation">
        {navItems.slice(0, 4).map(([itemLabel, Icon, href]) =>
          href ? (
            <Link
              className={itemLabel === 'Portfolio' ? 'is-active' : ''}
              href={href}
              key={itemLabel}
            >
              <Icon aria-hidden="true" />
              <span>{itemLabel}</span>
            </Link>
          ) : (
            <span className="is-disabled" key={itemLabel} aria-disabled="true">
              <Icon aria-hidden="true" />
              <span>{itemLabel}</span>
            </span>
          ),
        )}
      </nav>
    </main>
  );
}
