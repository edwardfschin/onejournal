import {
  Activity, ArrowUpRight, BookOpenText, BriefcaseBusiness, ChevronRight,
  CircleAlert, CircleCheck, Command, Database, FileChartColumn, LayoutDashboard,
  Menu, Search, Settings, Sparkles, WalletCards,
} from 'lucide-react';
import Link from 'next/link';

const navItems = [
  ['Today', LayoutDashboard, '/'], ['Portfolio', BriefcaseBusiness, '/portfolio'], ['Trades', Activity, '/trades'],
  ['Journal', BookOpenText, '/journal'], ['Reports', FileChartColumn, '/reports'], ['Data', Database, '/data'],
] as const;

const holdings = [
  ['NVDA', 'NVIDIA', '120', '$184.62', '$22,154.40', '+$1,668.00', 'cyan'],
  ['MSFT', 'Microsoft', '95', '$512.41', '$48,678.95', '+$1,102.60', 'violet'],
  ['SPY', 'S&P 500 ETF', '60', '$588.24', '$35,294.40', '+$246.00', 'amber'],
  ['CASH', 'Unallocated cash', '—', '—', '$84,320.00', '—', 'neutral'],
] as const;

export default function PortfolioPreview() {
  return (
    <main className="app-shell portfolio-route">
      <aside className="desktop-rail" aria-label="Primary navigation">
        <div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div>
        <nav className="nav-stack">
          {navItems.map(([label, Icon, href]) => <a className={`nav-item ${label === 'Portfolio' ? 'is-active' : ''}`} href={href} key={label} aria-current={label === 'Portfolio' ? 'page' : undefined}><Icon aria-hidden="true" /><span>{label}</span>{label === 'Journal' ? <span className="nav-count">3</span> : null}</a>)}
        </nav>
        <div className="rail-footer"><a className="nav-item" href="#settings"><Settings aria-hidden="true" /><span>Settings</span></a><div className="owner-chip"><span className="owner-avatar">ES</span><span><strong>Private owner</strong><small>Demo workspace</small></span></div></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button>
          <label className="search-box"><Search aria-hidden="true" /><span className="sr-only">Search OneJournal</span><input placeholder="Search trades, symbols, notes…" type="search" /><kbd><Command aria-hidden="true" /> K</kbd></label>
          <div className="topbar-actions"><span className="demo-pill"><Sparkles aria-hidden="true" /> Synthetic data</span></div>
        </header>
        <output className="mode-banner"><span><WalletCards aria-hidden="true" /> Portfolio preview</span><p>Illustrative allocation only. Broker-reconciled positions and marks are not connected.</p></output>

        <div className="content-frame">
          <div className="page-heading portfolio-heading">
            <div><p className="eyebrow">Portfolio · demo workspace</p><h1>Capital, at a glance.</h1><p className="heading-copy">The finished product will make scope, evidence, and data quality visible before any number earns trust.</p></div>
            <button className="outline-action" type="button">Account scope: All <ChevronRight aria-hidden="true" /></button>
          </div>

          <section className="authority-callout" aria-label="Portfolio authority status">
            <span className="authority-icon"><CircleAlert aria-hidden="true" /></span>
            <div><strong>Authoritative portfolio is unavailable</strong><p>This local preview has no approved position authority, cost basis, or valuation marks. The samples below exist only to review the interface.</p></div>
            <Link href="/" className="callout-link">View data health <ChevronRight aria-hidden="true" /></Link>
          </section>

          <section className="portfolio-summary-grid" aria-label="Illustrative portfolio summary">
            <article className="metric-card allocation-card"><div className="card-label"><span>Illustrative allocation</span><span className="quality-chip">Demo only</span></div><div className="allocation-body"><div className="allocation-ring"><span>4</span><small>assets</small></div><div className="allocation-legend"><p><i className="dot cyan" />Equities <strong>50.1%</strong></p><p><i className="dot violet" />ETFs <strong>18.2%</strong></p><p><i className="dot amber" />Cash <strong>19.7%</strong></p><p><i className="dot muted" />Other <strong>12.0%</strong></p></div></div></article>
            <article className="metric-card portfolio-stat"><div className="card-label"><span>Open positions</span><CircleCheck aria-hidden="true" /></div><p className="metric-value small">12</p><p className="metric-context">Illustrative count · not reconciled</p></article>
            <article className="metric-card portfolio-stat"><div className="card-label"><span>Cash allocation</span><CircleAlert aria-hidden="true" /></div><p className="metric-value small">19.7%</p><p className="metric-context">Sample only · no account connection</p></article>
          </section>

          <section className="panel holdings-panel">
            <div className="panel-header"><div><p className="eyebrow">Sample holdings</p><h2>Allocation detail</h2></div><button className="quiet-button" type="button">Customize columns <ChevronRight aria-hidden="true" /></button></div>
            <div className="holdings-header"><span>Instrument</span><span>Quantity</span><span>Last price</span><span>Market value</span><span>Day move</span></div>
            <div className="holdings-list">
              {holdings.map(([symbol, name, quantity, price, value, move, tone]) => <div className="holding-row" key={symbol}><span className={`symbol-tile ${tone}`}>{symbol === 'CASH' ? '$' : symbol[0]}</span><span className="holding-name"><strong>{symbol}</strong><small>{name}</small></span><span className="holding-cell"><small>Quantity</small><strong>{quantity}</strong></span><span className="holding-cell"><small>Last price</small><strong>{price}</strong></span><span className="holding-cell"><small>Market value</small><strong>{value}</strong></span><span className={move ? 'positive holding-move' : 'holding-move'}>{move ? <><ArrowUpRight aria-hidden="true" />{move}</> : '—'}</span></div>)}
            </div>
          </section>
        </div>
      </section>
      <nav className="mobile-nav" aria-label="Mobile navigation">{navItems.slice(0, 4).map(([label, Icon, href]) => <a className={label === 'Portfolio' ? 'is-active' : ''} href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span></a>)}</nav>
    </main>
  );
}
