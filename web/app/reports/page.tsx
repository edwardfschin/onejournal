import {
  Activity, ArrowUpRight, BookOpenText, BriefcaseBusiness, CalendarRange,
  ChevronRight, CircleAlert, Database, Download, FileChartColumn, LayoutDashboard,
  Menu, Search, Settings, Sparkles, TableProperties,
} from 'lucide-react';

const navItems = [
  ['Today', LayoutDashboard, '/'], ['Portfolio', BriefcaseBusiness, '/portfolio'], ['Trades', Activity, '/trades'],
  ['Journal', BookOpenText, '/journal'], ['Reports', FileChartColumn, '/reports'], ['Data', Database, '/data'],
] as const;

const reportRows = [
  ['August review', '1–31 Aug 2026', 'Trade summary', 'Ready'],
  ['Weekly reflection', '24–30 Aug 2026', 'Journal review', 'Draft'],
  ['Strategy pattern', 'Last 90 days', 'Learning view', 'Unavailable'],
];

export default function ReportsPreview() {
  return (
    <main className="app-shell reports-route">
      <aside className="desktop-rail" aria-label="Primary navigation"><div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div><nav className="nav-stack">{navItems.map(([label, Icon, href]) => <a className={`nav-item ${label === 'Reports' ? 'is-active' : ''}`} href={href} key={label} aria-current={label === 'Reports' ? 'page' : undefined}><Icon aria-hidden="true" /><span>{label}</span>{label === 'Journal' ? <span className="nav-count">3</span> : null}</a>)}</nav><div className="rail-footer"><a className="nav-item" href="#settings"><Settings aria-hidden="true" /><span>Settings</span></a><div className="owner-chip"><span className="owner-avatar">ES</span><span><strong>Private owner</strong><small>Demo workspace</small></span></div></div></aside>
      <section className="workspace">
        <header className="topbar"><button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button><label className="search-box"><Search aria-hidden="true" /><span className="sr-only">Search OneJournal</span><input placeholder="Search trades, symbols, notes…" type="search" /><kbd>⌘ K</kbd></label><div className="topbar-actions"><span className="demo-pill"><Sparkles aria-hidden="true" /> Synthetic data</span></div></header>
        <output className="mode-banner"><span><FileChartColumn aria-hidden="true" /> Reports preview</span><p>Generated values and exports are illustrative; no authoritative financial report is available in demo mode.</p></output>
        <div className="content-frame">
          <div className="page-heading"><div><p className="eyebrow">Reports · demo workspace</p><h1>Turn activity into a clearer pattern.</h1><p className="heading-copy">Choose a period, understand its quality, and export only when the underlying scope is reconciled.</p></div><button className="outline-action" type="button"><CalendarRange aria-hidden="true" /> Aug 2026 <ChevronRight aria-hidden="true" /></button></div>
          <section className="report-top-grid">
            <article className="metric-card report-feature"><div className="card-label"><span>August review</span><span className="quality-chip">Synthetic</span></div><p className="report-headline">A month built around fewer, more deliberate decisions.</p><div className="report-visual"><span className="report-bar b1" /><span className="report-bar b2" /><span className="report-bar b3" /><span className="report-bar b4" /><span className="report-bar b5" /></div><div className="report-feature-foot"><span><ArrowUpRight aria-hidden="true" /> Demo trend</span><span>31 days · illustrative</span></div></article>
            <article className="panel report-quality"><div className="panel-header"><div><p className="eyebrow">Report quality</p><h2>What can be trusted</h2></div></div><div className="quality-state ready"><span>01</span><p><strong>Trade activity</strong><small>Demo view available</small></p></div><div className="quality-state pending"><span>02</span><p><strong>P&amp;L history</strong><small>Not yet authoritative</small></p></div><div className="quality-state blocked"><span>03</span><p><strong>CSV export</strong><small>Disabled until reconciliation</small></p></div></article>
          </section>
          <section className="panel reports-list-panel"><div className="panel-header"><div><p className="eyebrow">Saved views</p><h2>Report workspace</h2></div><button className="quiet-button" type="button"><Download aria-hidden="true" /> Export <ChevronRight aria-hidden="true" /></button></div><div className="reports-list">{reportRows.map(([title, period, kind, state]) => <button className="report-row" type="button" key={title}><span className="report-icon"><TableProperties aria-hidden="true" /></span><span><strong>{title}</strong><small>{period} · {kind}</small></span><span className={`report-state ${state.toLowerCase()}`}>{state}</span><ChevronRight aria-hidden="true" /></button>)}</div></section>
          <section className="panel report-boundary"><CircleAlert aria-hidden="true" /><p><strong>Reporting will fail closed.</strong> A future export must match the displayed canonical result, preserve its period, scope, as-of, calculation, and quality state—or remain unavailable.</p></section>
        </div>
      </section>
      <nav className="mobile-nav" aria-label="Mobile navigation">{navItems.slice(0,4).map(([label, Icon, href]) => <a href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span></a>)}</nav>
    </main>
  );
}
