import {
  Activity, BookOpenText, BriefcaseBusiness, CheckCircle2, ChevronRight,
  CircleAlert, Clock3, Database, FileChartColumn, LayoutDashboard, LockKeyhole,
  Menu, RefreshCw, Search, Settings, ShieldCheck, Sparkles, Upload,
} from 'lucide-react';

const navItems = [
  ['Today', LayoutDashboard, '/'], ['Portfolio', BriefcaseBusiness, '/portfolio'], ['Trades', Activity, '/trades'],
  ['Journal', BookOpenText, '/journal'], ['Reports', FileChartColumn, '/reports'], ['Data', Database, '/data'],
] as const;

const checks = [
  ['Trade activity evidence', 'No demo import connected', 'Unavailable', 'alert'],
  ['Position authority', 'PNL-03 acceptance required', 'Unavailable', 'alert'],
  ['Journal review context', 'Synthetic preview active', 'Preview', 'ready'],
  ['Provider access', 'No credentials in this workspace', 'Protected', 'protected'],
];

export default function DataPreview() {
  return (
    <main className="app-shell data-route">
      <aside className="desktop-rail" aria-label="Primary navigation"><div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div><nav className="nav-stack">{navItems.map(([label, Icon, href]) => <a className={`nav-item ${label === 'Data' ? 'is-active' : ''}`} href={href} key={label} aria-current={label === 'Data' ? 'page' : undefined}><Icon aria-hidden="true" /><span>{label}</span>{label === 'Journal' ? <span className="nav-count">3</span> : null}</a>)}</nav><div className="rail-footer"><a className="nav-item" href="#settings"><Settings aria-hidden="true" /><span>Settings</span></a><div className="owner-chip"><span className="owner-avatar">ES</span><span><strong>Private owner</strong><small>Demo workspace</small></span></div></div></aside>
      <section className="workspace">
        <header className="topbar"><button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button><label className="search-box"><Search aria-hidden="true" /><span className="sr-only">Search OneJournal</span><input placeholder="Search trades, symbols, notes…" type="search" /><kbd>⌘ K</kbd></label><div className="topbar-actions"><span className="demo-pill"><Sparkles aria-hidden="true" /> Synthetic data</span></div></header>
        <output className="mode-banner"><span><Database aria-hidden="true" /> Data &amp; connections preview</span><p>No provider is connected and this interface cannot request, store, or refresh credentials.</p></output>
        <div className="content-frame">
          <div className="page-heading"><div><p className="eyebrow">Data &amp; connections · demo workspace</p><h1>Trust starts at the source.</h1><p className="heading-copy">Every import, transformation, and displayed result must carry a clear answer to where it came from and how current it is.</p></div><button className="outline-action" type="button"><Upload aria-hidden="true" /> Import evidence <ChevronRight aria-hidden="true" /></button></div>
          <section className="data-top-grid">
            <section className="panel connection-panel"><div className="panel-header"><div><p className="eyebrow">Provider connection</p><h2>Schwab</h2></div><span className="connection-lock"><LockKeyhole aria-hidden="true" /> Protected</span></div><div className="connection-empty"><div className="empty-orbit"><Database aria-hidden="true" /></div><div><strong>No connection in demo mode</strong><p>Provider credentials, OAuth refresh, and broker calls remain outside the website preview.</p></div></div><button className="connection-action" type="button">Connection details <ChevronRight aria-hidden="true" /></button></section>
            <section className="panel freshness-panel"><div className="panel-header"><div><p className="eyebrow">Freshness</p><h2>Data health</h2></div><span className="health-score">Demo</span></div><div className="freshness-clock"><Clock3 aria-hidden="true" /><strong>Unavailable</strong><span>No accepted as-of timestamp</span></div><p className="freshness-note"><CircleAlert aria-hidden="true" /> A missing source is visible, never converted to a current-looking value.</p></section>
          </section>
          <section className="panel evidence-panel"><div className="panel-header"><div><p className="eyebrow">Evidence status</p><h2>What this workspace knows</h2></div><button className="quiet-button" type="button"><RefreshCw aria-hidden="true" /> Refresh status</button></div><div className="evidence-list">{checks.map(([title, detail, state, tone]) => <div className="evidence-row" key={title}><span className={`evidence-icon ${tone}`}>{tone === 'ready' ? <CheckCircle2 aria-hidden="true" /> : tone === 'protected' ? <ShieldCheck aria-hidden="true" /> : <CircleAlert aria-hidden="true" />}</span><span><strong>{title}</strong><small>{detail}</small></span><span className={`evidence-state ${tone}`}>{state}</span></div>)}</div></section>
          <section className="panel data-boundary"><LockKeyhole aria-hidden="true" /><p><strong>The web interface is not a credential client.</strong> Approved imports will remain isolated, audited, and explicit about their source, evidence scope, reconciliation, freshness, and failure state.</p></section>
        </div>
      </section>
      <nav className="mobile-nav" aria-label="Mobile navigation">{navItems.slice(0,4).map(([label, Icon, href]) => <a href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span></a>)}</nav>
    </main>
  );
}
