import {
  Activity, ArrowDownRight, ArrowUpRight, BookOpenText, BriefcaseBusiness,
  CalendarDays, ChevronRight, CircleAlert, CircleCheck, Command, Database,
  FileChartColumn, Fingerprint, LayoutDashboard, Menu, Search, Settings, Sparkles,
} from 'lucide-react';

const navItems = [
  ['Today', LayoutDashboard, '/'], ['Portfolio', BriefcaseBusiness, '/portfolio'], ['Trades', Activity, '/trades'],
  ['Journal', BookOpenText, '/journal'], ['Reports', FileChartColumn, '/reports'], ['Data', Database, '/data'],
] as const;

const positions = [
  { symbol: 'NVDA', name: 'NVIDIA', weight: '28.4%', move: '+2.31%', up: true },
  { symbol: 'MSFT', name: 'Microsoft', weight: '21.7%', move: '+0.82%', up: true },
  { symbol: 'SPY', name: 'S&P 500 ETF', weight: '18.2%', move: '-0.24%', up: false },
];

const attentionItems = [
  ['Review NVDA earnings trade', 'Journal prompt · 3 questions', 'violet'],
  ['2 trades need a strategy tag', 'Data quality · about 2 min', 'amber'],
  ['Weekly review is ready', '12–16 Aug · 6 closed trades', 'cyan'],
];

export default function Home() {
  return (
    <main className="app-shell" id="today">
      <aside className="desktop-rail" aria-label="Primary navigation">
        <div className="brand-mark" aria-label="OneJournal">
          <span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span>
        </div>
        <nav className="nav-stack">
          {navItems.map(([label, Icon, href], index) => (
            <a className={`nav-item ${index === 0 ? 'is-active' : ''}`} href={href} key={label} aria-current={index === 0 ? 'page' : undefined}>
              <Icon aria-hidden="true" /><span>{label}</span>{label === 'Journal' ? <span className="nav-count">3</span> : null}
            </a>
          ))}
        </nav>
        <div className="rail-footer">
          <a className="nav-item" href="#preview"><Settings aria-hidden="true" /><span>Settings</span></a>
          <div className="owner-chip"><span className="owner-avatar">ES</span><span><strong>Private owner</strong><small>Demo workspace</small></span></div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button>
          <label className="search-box">
            <Search aria-hidden="true" /><span className="sr-only">Search OneJournal</span>
            <input placeholder="Search trades, symbols, notes…" type="search" />
            <kbd><Command aria-hidden="true" /> K</kbd>
          </label>
          <div className="topbar-actions">
            <span className="demo-pill"><Sparkles aria-hidden="true" /> Synthetic data</span>
            <button className="date-control" type="button"><CalendarDays aria-hidden="true" /><span>31 Aug 2026</span><ChevronRight aria-hidden="true" /></button>
          </div>
        </header>

        <output className="mode-banner">
          <span><Fingerprint aria-hidden="true" /> Demo workspace</span>
          <p>Everything on this screen is illustrative. No broker, account, or journal data is connected.</p>
        </output>

        <div className="content-frame">
          <div className="page-heading">
            <div><p className="eyebrow">Monday · private owner preview</p><h1>Good morning, Edward.</h1><p className="heading-copy">See what changed, what needs attention, and what deserves a note.</p></div>
            <div className="asof-block"><span className="status-dot" /><span><small>Demo as of</small><strong>09:30 SGT</strong></span></div>
          </div>

          <section className="metrics-grid" aria-label="Demo portfolio overview">
            <article className="metric-card hero-metric">
              <div className="card-label"><span>Portfolio value</span><span className="quality-chip">Illustrative</span></div>
              <div className="metric-main">
                <div><p className="metric-value">$428,760.42</p><p className="metric-delta positive"><ArrowUpRight aria-hidden="true" /> +$3,842.18 <span>today</span></p></div>
                <div className="mini-chart" aria-label="Illustrative upward portfolio trend">
                  <svg aria-label="Illustrative upward portfolio trend" viewBox="0 0 240 80"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--signal-cyan)" stopOpacity=".28" /><stop offset="1" stopColor="var(--signal-cyan)" stopOpacity="0" /></linearGradient></defs><path className="chart-area" d="M0 68 C25 64 30 48 53 52 S85 61 102 42 S132 34 147 42 S177 29 194 33 S220 12 240 16 L240 80 L0 80 Z" /><path className="chart-line" d="M0 68 C25 64 30 48 53 52 S85 61 102 42 S132 34 147 42 S177 29 194 33 S220 12 240 16" /></svg>
                </div>
              </div>
              <div className="metric-foot"><span><strong>+$18,406</strong> 30 day change</span><span><strong>4.49%</strong> illustrative return</span></div>
            </article>
            <article className="metric-card compact-metric"><div className="card-label"><span>Realized P&amp;L</span><CircleCheck aria-hidden="true" /></div><p className="metric-value small">+$12,480.36</p><p className="metric-delta positive"><ArrowUpRight aria-hidden="true" /> +$1,220 this month</p><p className="metric-context">Demo · after fees</p></article>
            <article className="metric-card compact-metric"><div className="card-label"><span>Unrealized P&amp;L</span><CircleAlert aria-hidden="true" /></div><p className="metric-value small">+$8,216.74</p><p className="metric-delta negative"><ArrowDownRight aria-hidden="true" /> -$642 since open</p><p className="metric-context">Illustrative marks · not accepted</p></article>
          </section>

          <div className="main-grid" id="preview">
            <section className="panel attention-panel">
              <div className="panel-header"><div><p className="eyebrow">Your focus</p><h2>Three things deserve attention</h2></div><button className="quiet-button" type="button">View queue <ChevronRight aria-hidden="true" /></button></div>
              <div className="attention-list">
                {attentionItems.map(([label, detail, tone], index) => <button className="attention-row" type="button" key={label}><span className={`attention-index ${tone}`}>0{index + 1}</span><span className="attention-copy"><strong>{label}</strong><small>{detail}</small></span><ChevronRight aria-hidden="true" /></button>)}
              </div>
            </section>

            <section className="panel health-panel">
              <div className="panel-header"><div><p className="eyebrow">Truth layer</p><h2>Data health</h2></div><span className="health-score">Demo</span></div>
              <div className="health-orbit" aria-label="Three of four illustrative data checks complete"><div className="orbit-ring"><strong>3/4</strong><span>checks</span></div></div>
              <ul className="health-list"><li><CircleCheck aria-hidden="true" /><span>Trade history</span><strong>Ready</strong></li><li><CircleCheck aria-hidden="true" /><span>Journal links</span><strong>Ready</strong></li><li><CircleAlert aria-hidden="true" /><span>Position marks</span><strong>Unavailable</strong></li></ul>
            </section>

            <section className="panel positions-panel">
              <div className="panel-header"><div><p className="eyebrow">Demo allocation</p><h2>Largest positions</h2></div><button className="quiet-button" type="button">Portfolio <ChevronRight aria-hidden="true" /></button></div>
              <div className="position-table" aria-label="Illustrative largest positions">
                {positions.map((position) => <div className="position-row" key={position.symbol}><span className="symbol-tile">{position.symbol[0]}</span><span className="position-name"><strong>{position.symbol}</strong><small>{position.name}</small></span><span className="weight"><small>Weight</small><strong>{position.weight}</strong></span><span className={position.up ? 'positive' : 'negative'}>{position.move}</span></div>)}
              </div>
            </section>
          </div>
        </div>
      </section>

      <nav className="mobile-nav" aria-label="Mobile navigation">
        {navItems.slice(0, 4).map(([label, Icon, href], index) => <a className={index === 0 ? 'is-active' : ''} href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span></a>)}
      </nav>
    </main>
  );
}
