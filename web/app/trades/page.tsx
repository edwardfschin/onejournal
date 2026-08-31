import {
  Activity, BookOpenText, BriefcaseBusiness, CalendarDays, CheckCircle2,
  ChevronRight, CircleAlert, Clock3, Database, FileChartColumn, LayoutDashboard,
  Menu, Search, Settings, Sparkles, Tag, TextQuote, WalletCards,
} from 'lucide-react';

const navItems = [
  ['Today', LayoutDashboard, '/'], ['Portfolio', BriefcaseBusiness, '/portfolio'], ['Trades', Activity, '/trades'],
  ['Journal', BookOpenText, '/journal'], ['Reports', FileChartColumn, '/reports'], ['Data', Database, '/data'],
] as const;

const reviewQueue = [
  ['NVDA', 'Long equity · demo episode', 'Needs post-trade note', 'violet'],
  ['MSFT', 'Short put spread · demo episode', 'Strategy tag incomplete', 'amber'],
  ['SPY', 'Index ETF · demo episode', 'Review ready', 'cyan'],
];

export default function TradesPreview() {
  return (
    <main className="app-shell trades-route">
      <aside className="desktop-rail" aria-label="Primary navigation">
        <div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div>
        <nav className="nav-stack">{navItems.map(([label, Icon, href]) => <a className={`nav-item ${label === 'Trades' ? 'is-active' : ''}`} href={href} key={label} aria-current={label === 'Trades' ? 'page' : undefined}><Icon aria-hidden="true" /><span>{label}</span>{label === 'Journal' ? <span className="nav-count">3</span> : null}</a>)}</nav>
        <div className="rail-footer"><a className="nav-item" href="#settings"><Settings aria-hidden="true" /><span>Settings</span></a><div className="owner-chip"><span className="owner-avatar">ES</span><span><strong>Private owner</strong><small>Demo workspace</small></span></div></div>
      </aside>

      <section className="workspace">
        <header className="topbar"><button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button><label className="search-box"><Search aria-hidden="true" /><span className="sr-only">Search OneJournal</span><input placeholder="Search trades, symbols, notes…" type="search" /><kbd>⌘ K</kbd></label><div className="topbar-actions"><span className="demo-pill"><Sparkles aria-hidden="true" /> Synthetic data</span></div></header>
        <output className="mode-banner"><span><WalletCards aria-hidden="true" /> Trades preview</span><p>Episodes, costs, and results are illustrative—not imported broker activity.</p></output>

        <div className="content-frame">
          <div className="page-heading"><div><p className="eyebrow">Trade lifecycle · demo workspace</p><h1>Review the decision, not just the result.</h1><p className="heading-copy">A trade stays traceable from thesis through outcome, with financial facts kept separate from reflection.</p></div><button className="outline-action" type="button"><CalendarDays aria-hidden="true" /> Last 30 days <ChevronRight aria-hidden="true" /></button></div>

          <section className="trade-layout">
            <section className="panel review-panel"><div className="panel-header"><div><p className="eyebrow">Review queue</p><h2>Three episodes need attention</h2></div><button className="quiet-button" type="button">All trades <ChevronRight aria-hidden="true" /></button></div><div className="review-list">{reviewQueue.map(([symbol, detail, state, tone]) => <button className="review-row" type="button" key={symbol}><span className={`trade-symbol ${tone}`}>{symbol}</span><span><strong>{detail}</strong><small>{state}</small></span><ChevronRight aria-hidden="true" /></button>)}</div></section>
            <section className="panel progress-panel"><div className="panel-header"><div><p className="eyebrow">Workflow</p><h2>Review coverage</h2></div><span className="health-score">Demo</span></div><div className="review-progress"><strong>68%</strong><span>of closed demo episodes have a note</span></div><div className="progress-track"><span /></div><p className="progress-foot"><CheckCircle2 aria-hidden="true" /> 8 reviewed <span>·</span> <CircleAlert aria-hidden="true" /> 4 awaiting review</p></section>
          </section>

          <section className="panel lifecycle-panel"><div className="panel-header"><div><p className="eyebrow">Selected demo episode</p><h2>NVDA · long equity</h2></div><span className="demo-status"><Clock3 aria-hidden="true" /> Reflection pending</span></div><div className="lifecycle-grid"><div className="lifecycle-step is-complete"><span>01</span><div><small>Thesis</small><strong>Defined</strong><p>Momentum continuation through earnings.</p></div></div><div className="lifecycle-step is-complete"><span>02</span><div><small>Entry</small><strong>Illustrative fill</strong><p>Demo data only · no broker evidence.</p></div></div><div className="lifecycle-step is-current"><span>03</span><div><small>Review</small><strong>Awaiting note</strong><p>Capture what changed and what you learned.</p></div></div></div><div className="reflection-card"><span className="reflection-icon"><TextQuote aria-hidden="true" /></span><div><p className="eyebrow">Journal prompt</p><strong>What would make this decision repeatable?</strong><span>Draft response · private authoring begins in a later, approved slice.</span></div><button className="quiet-button" type="button">Open prompt <ChevronRight aria-hidden="true" /></button></div></section>
          <section className="panel trade-truth-callout"><Tag aria-hidden="true" /><p><strong>Financial authority remains separate.</strong> This route does not claim accepted realized P&amp;L, fees, fills, or lifecycle reconciliation.</p></section>
        </div>
      </section>
      <nav className="mobile-nav" aria-label="Mobile navigation">{navItems.slice(0,4).map(([label, Icon, href]) => <a className={label === 'Trades' ? 'is-active' : ''} href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span></a>)}</nav>
    </main>
  );
}
