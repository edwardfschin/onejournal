import {
  Activity, ArrowRight, BookOpenText, BriefcaseBusiness, CheckCircle2, ChevronRight,
  Clock3, Database, FileChartColumn, LayoutDashboard, Menu, NotebookPen, Search,
  Settings, Sparkles, Target, TextQuote,
} from 'lucide-react';

const navItems = [
  ['Today', LayoutDashboard, '/'], ['Portfolio', BriefcaseBusiness, '/portfolio'], ['Trades', Activity, '/trades'],
  ['Journal', BookOpenText, '/journal'], ['Reports', FileChartColumn, '/reports'], ['Data', Database, '/data'],
] as const;

const prompts = [
  ['Process', 'What did you see before the trade that you would want to see again?', 'Ready'],
  ['Decision', 'Where did your thesis improve or weaken after entry?', 'Draft'],
  ['Lesson', 'What single change would make the next execution cleaner?', 'Ready'],
];

export default function JournalPreview() {
  return (
    <main className="app-shell journal-route">
      <aside className="desktop-rail" aria-label="Primary navigation"><div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div><nav className="nav-stack">{navItems.map(([label, Icon, href]) => <a className={`nav-item ${label === 'Journal' ? 'is-active' : ''}`} href={href} key={label} aria-current={label === 'Journal' ? 'page' : undefined}><Icon aria-hidden="true" /><span>{label}</span>{label === 'Journal' ? <span className="nav-count">3</span> : null}</a>)}</nav><div className="rail-footer"><a className="nav-item" href="#settings"><Settings aria-hidden="true" /><span>Settings</span></a><div className="owner-chip"><span className="owner-avatar">ES</span><span><strong>Private owner</strong><small>Demo workspace</small></span></div></div></aside>
      <section className="workspace">
        <header className="topbar"><button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button><label className="search-box"><Search aria-hidden="true" /><span className="sr-only">Search OneJournal</span><input placeholder="Search trades, symbols, notes…" type="search" /><kbd>⌘ K</kbd></label><div className="topbar-actions"><span className="demo-pill"><Sparkles aria-hidden="true" /> Synthetic data</span></div></header>
        <output className="mode-banner"><span><NotebookPen aria-hidden="true" /> Journal preview</span><p>No notes are saved here. Private append-only authoring is a later approved application slice.</p></output>
        <div className="content-frame">
          <div className="page-heading"><div><p className="eyebrow">Journal · demo workspace</p><h1>Make the learning compound.</h1><p className="heading-copy">Turn the moments that mattered into a review practice you can return to.</p></div><button className="outline-action" type="button"><NotebookPen aria-hidden="true" /> New entry <ChevronRight aria-hidden="true" /></button></div>
          <section className="journal-grid">
            <section className="panel journal-focus"><div className="panel-header"><div><p className="eyebrow">Today’s reflection</p><h2>One clear prompt</h2></div><span className="health-score">Demo</span></div><div className="focus-quote"><TextQuote aria-hidden="true" /><p>“What made this setup worth taking, and what would make it worth passing on next time?”</p></div><div className="draft-surface"><span>Write a private reflection…</span><small>Preview only · nothing is stored</small></div><div className="journal-actions"><button className="primary-preview" type="button">Save reflection</button><span><Clock3 aria-hidden="true" /> Not enabled in demo</span></div></section>
            <section className="panel routine-panel"><div className="panel-header"><div><p className="eyebrow">Your rhythm</p><h2>Review cadence</h2></div></div><div className="routine-metric"><strong>3</strong><span>reflection prompts<br />ready this week</span></div><div className="routine-list"><p><CheckCircle2 aria-hidden="true" /><span>Friday trade review</span><strong>Complete</strong></p><p><Target aria-hidden="true" /><span>Monthly pattern review</span><strong>Next</strong></p></div></section>
          </section>
          <section className="panel prompts-panel"><div className="panel-header"><div><p className="eyebrow">Review prompts</p><h2>Small questions, durable signal</h2></div><button className="quiet-button" type="button">Prompt library <ChevronRight aria-hidden="true" /></button></div><div className="prompt-list">{prompts.map(([category, question, status], index) => <button className="prompt-row" type="button" key={category}><span className="prompt-index">0{index + 1}</span><span><small>{category}</small><strong>{question}</strong></span><span className={`prompt-status ${status === 'Draft' ? 'draft' : ''}`}>{status}</span><ArrowRight aria-hidden="true" /></button>)}</div></section>
          <section className="panel journal-boundary"><BookOpenText aria-hidden="true" /><p><strong>Journal truth is intentionally separate from financial truth.</strong> This design connects reflective context to a future trade lifecycle without rewriting its evidence or calculations.</p></section>
        </div>
      </section>
      <nav className="mobile-nav" aria-label="Mobile navigation">{navItems.slice(0,4).map(([label, Icon, href]) => <a className={label === 'Journal' ? 'is-active' : ''} href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span></a>)}</nav>
    </main>
  );
}
