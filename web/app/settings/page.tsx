import {
  Activity, BellRing, BookOpenText, BriefcaseBusiness, ChevronRight, Database,
  FileChartColumn, Globe2, KeyRound, LayoutDashboard, LockKeyhole, Menu, MonitorCog,
  Search, Settings, ShieldCheck, Sparkles, UserRound,
} from 'lucide-react';
import Link from 'next/link';

const navItems = [
  ['Today', LayoutDashboard, '/'], ['Portfolio', BriefcaseBusiness, '/portfolio'], ['Trades', Activity, '/trades'],
  ['Journal', BookOpenText, '/journal'], ['Reports', FileChartColumn, '/reports'], ['Data', Database, '/data'],
] as const;

const settings = [
  { icon: UserRound, title: 'Owner profile', detail: 'Name, display timezone, and working preferences' },
  { icon: Globe2, title: 'Display & timezone', detail: 'Singapore · 24-hour time · USD formatting' },
  { icon: ShieldCheck, title: 'Privacy & security', detail: 'Private-owner controls are not configured in demo' },
  { icon: KeyRound, title: 'Connections', detail: 'Provider access stays outside the browser preview' },
  { icon: BellRing, title: 'Notifications', detail: 'Review reminders will be configured later' },
];

export default function SettingsPreview() {
  return (
    <main className="app-shell settings-route">
      <aside className="desktop-rail" aria-label="Primary navigation"><div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div><nav className="nav-stack">{navItems.map(([label, Icon, href]) => <a className="nav-item" href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span>{label === 'Journal' ? <span className="nav-count">3</span> : null}</a>)}</nav><div className="rail-footer"><Link className="nav-item is-active" href="/settings" aria-current="page"><Settings aria-hidden="true" /><span>Settings</span></Link><div className="owner-chip"><span className="owner-avatar">ES</span><span><strong>Private owner</strong><small>Demo workspace</small></span></div></div></aside>
      <section className="workspace"><header className="topbar"><button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button><label className="search-box"><Search aria-hidden="true" /><span className="sr-only">Search OneJournal</span><input placeholder="Search settings…" type="search" /><kbd>⌘ K</kbd></label><div className="topbar-actions"><span className="demo-pill"><Sparkles aria-hidden="true" /> Synthetic data</span></div></header>
        <output className="mode-banner"><span><MonitorCog aria-hidden="true" /> Settings preview</span><p>Preferences are illustrative. This route cannot change credentials, data, access, or runtime configuration.</p></output>
        <div className="content-frame settings-frame"><div className="page-heading"><div><p className="eyebrow">Settings · demo workspace</p><h1>Make the workspace yours.</h1><p className="heading-copy">Preferences should be clear, bounded, and reversible—especially where data, privacy, and notifications meet.</p></div></div>
          <section className="panel settings-profile"><span className="settings-avatar">ES</span><div><p className="eyebrow">Private owner</p><h2>Edward’s workspace</h2><p>Demo profile · no identity system is configured</p></div><button className="quiet-button" type="button">Edit profile <ChevronRight aria-hidden="true" /></button></section>
          <section className="settings-list">{settings.map(({ icon: Icon, title, detail }) => <button className="settings-row" type="button" key={title}><span className="settings-icon"><Icon aria-hidden="true" /></span><span><strong>{title}</strong><small>{detail}</small></span><ChevronRight aria-hidden="true" /></button>)}</section>
          <section className="panel settings-boundary"><LockKeyhole aria-hidden="true" /><p><strong>Security configuration is intentionally unavailable in the preview.</strong> Authentication, secure sessions, recovery, retention, backup, and connection ownership require their own accepted implementation and tests.</p></section>
        </div>
      </section>
      <nav className="mobile-nav" aria-label="Mobile navigation">{navItems.slice(0,4).map(([label, Icon, href]) => <a href={href} key={label}><Icon aria-hidden="true" /><span>{label}</span></a>)}</nav>
    </main>
  );
}
