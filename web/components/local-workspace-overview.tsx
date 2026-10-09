'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowRight, CircleAlert, RefreshCw } from 'lucide-react';
import { LocalWorkspaceNavigation } from '@/components/local-workspace-navigation';
import { fetchSavedWorkspace, fetchWorkspaceSession, type SavedWorkspace, type WorkspaceSession } from '@/lib/local-owner-workspace';
import { LOCAL_ROUTES } from '@/lib/routes';
import type { ReportContext } from '@/lib/local-owner-reports';

type View = 'today' | 'data' | 'settings';
const headings = {
  today: ['Start with the evidence.', 'Your saved data, decisions and learning. This is not a live market dashboard.'],
  data: ['Know what your data covers.', 'Snapshot dates and unresolved gaps stay visible. Reloading does not fetch broker data.'],
  settings: ['Your private Mac workspace.', 'Verified access status and the controls already available to you.'],
} as const;
const qualityLabels = {
  valid: 'Complete for this selection', stale: 'Stale data', incomplete: 'Partial results',
  reconciliation_pending: 'Reconciliation pending', unavailable: 'Unavailable', failed: 'Failed',
};
const reasonLabels: Record<string, string> = {
  opening_history_missing: 'Opening history missing', position_reconciliation_incomplete: 'Position reconciliation incomplete',
  lifecycle_review_required: 'Lifecycle review needed', outside_accepted_coverage: 'Outside accepted coverage',
  metric_unavailable: 'One or more metrics unavailable',
};

function QualityDetails({ report, unit }: { report: ReportContext; unit: string }) {
  return <div className={`bounded-report-quality ${report.metadata.quality}`}>
    <strong>{qualityLabels[report.metadata.quality]}</strong>
    <p>{report.counts.available_count} available · {report.counts.unavailable_count} withheld · {report.counts.reconciliation_pending_count} pending</p>
    <p>{report.counts.processed_count} {unit} checked.</p>
    {Object.entries(report.metadata.reason_counts).length ? <ul>{Object.entries(report.metadata.reason_counts).map(([reason, count]) =>
      <li key={reason}>{reasonLabels[reason] ?? reason.replaceAll('_', ' ')}: {count}</li>)}</ul> : null}
  </div>;
}

function SavedContext({ saved }: { saved: SavedWorkspace }) {
  return <section className="workspace-overview-grid" aria-label="Saved data coverage">
    <article className="panel report-section">
      <p className="eyebrow">Portfolio snapshot</p><h2>{saved.current.metadata.current_valuation_asof}</h2>
      <p>New York market date. Saved valuation, not live prices or today’s performance.</p>
      <QualityDetails report={saved.current} unit="account/currency groups" />
      <Link className="workspace-action" href={LOCAL_ROUTES.portfolio}>Inspect holdings <ArrowRight aria-hidden="true" /></Link>
    </article>
    <article className="panel report-section">
      <p className="eyebrow">Realized history</p><h2>{saved.history.metadata.coverage_start_date} — {saved.history.metadata.coverage_end_date}</h2>
      <p>Accepted coverage, using the New York market day. Withheld results are not zero.</p>
      <QualityDetails report={saved.history} unit="allocations/scopes" />
      <Link className="workspace-action" href={LOCAL_ROUTES.reports}>Inspect results and export <ArrowRight aria-hidden="true" /></Link>
    </article>
  </section>;
}

export default function LocalWorkspaceOverview({ view }: { view: View }) {
  const [reload, setReload] = React.useState(0);
  return <OverviewContent key={`${view}-${reload}`} view={view} onReload={() => setReload((value) => value + 1)} />;
}

function OverviewContent({ view, onReload }: { view: View; onReload: () => void }) {
  const [saved, setSaved] = React.useState<SavedWorkspace | null>(null);
  const [session, setSession] = React.useState<WorkspaceSession | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => {
    const controller = new AbortController();
    const request = view === 'settings'
      ? fetchWorkspaceSession().then((value) => { if (!controller.signal.aborted) setSession(value); })
      : fetchSavedWorkspace(controller.signal).then((value) => { if (!controller.signal.aborted) setSaved(value); });
    void request.catch(() => { if (!controller.signal.aborted) setFailed(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [view]);

  const title = view[0].toUpperCase() + view.slice(1);
  return <main className="app-shell local-reports-route local-workspace-overview">
    <a className="workspace-skip-link" href="#workspace-content">Skip to content</a>
    <section className="workspace">
      <header className="topbar">
        <Link className="brand-mark" href={LOCAL_ROUTES.today} aria-label="OneJournal Today"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></Link>
        <LocalWorkspaceNavigation />
      </header>
      <div className="mode-banner local-portfolio-banner"><span>Private Mac workspace</span><p>Saved evidence · manual updates · no trading</p></div>
      <div className="content-frame" id="workspace-content" tabIndex={-1}>
        <div className="page-heading"><div><p className="eyebrow">{title} · local owner</p><h1>{headings[view][0]}</h1><p className="heading-copy">{headings[view][1]}</p></div>
          <button className="report-download" type="button" disabled={loading} onClick={onReload}><RefreshCw aria-hidden="true" />{view === 'settings' ? 'Check access status' : 'Reload saved data'}</button>
        </div>
        {loading ? <section className="panel local-portfolio-state" aria-live="polite"><RefreshCw className="local-spinner" aria-hidden="true" /><div><strong>{view === 'settings' ? 'Checking your session' : 'Checking the accepted release'}</strong><p>No cached or demo data is substituted.</p></div></section> : null}
        {failed ? <section className="panel local-portfolio-state is-unavailable" role="alert"><CircleAlert aria-hidden="true" /><div><strong>{view === 'settings' ? 'Access status unavailable' : 'Saved data unavailable'}</strong><p>{view === 'settings' ? 'The protected session could not be verified. No access claim is made.' : 'The accepted reports could not be verified together. Check the local service, then reload.'}</p></div></section> : null}
        {saved ? <SavedContext saved={saved} /> : null}
        {view === 'today' ? <section className="workspace-overview-grid">
          <article className="panel report-section"><p className="eyebrow">Trades</p><h2>Why did I make this trade?</h2><p>Inspect the trade’s evidence and record the decision behind it.</p><Link className="workspace-action" href={LOCAL_ROUTES.trades}>Review a trade <ArrowRight aria-hidden="true" /></Link></article>
          <article className="panel report-section"><p className="eyebrow">Journal</p><h2>What did I learn?</h2><p>Capture a reflection or lesson without changing financial evidence.</p><Link className="workspace-action" href={LOCAL_ROUTES.journal}>Open your journal <ArrowRight aria-hidden="true" /></Link></article>
        </section> : null}
        {view === 'data' ? <>
          <section className="panel report-section"><h2>How new data reaches this workspace</h2><ol className="workspace-steps"><li>Capture a bounded set of fresh broker evidence through the existing OneBot-owned route.</li><li>Validate and reconcile it privately. Missing evidence stays withheld.</li><li>Accept the exact new results, append a release with a verified backup, then activate it.</li></ol><p>Fresh broker capture is not wired to this screen yet. There is no automatic sync or browser-to-broker connection. Reload reads the currently active saved release only.</p></section>
          {saved ? <section className="panel report-section report-context"><h2>Release provenance</h2><dl><dt>Release</dt><dd>{saved.current.metadata.report_release_uid}</dd><dt>Prepared (UTC)</dt><dd>{saved.current.metadata.generated_at_utc}</dd><dt>Owner accepted (UTC)</dt><dd>{saved.current.metadata.owner_accepted_at_utc}</dd><dt>Calculation version</dt><dd>{saved.current.metadata.calculation_version}</dd></dl></section> : null}
        </> : null}
        {view === 'settings' ? <>
          {session ? <section className="panel report-section"><p className="eyebrow">Verified now</p><h2>Signed in with a passkey</h2><p>{session.passkeyCount} registered passkey{session.passkeyCount === 1 ? '' : 's'}. Device verification is required by the Mac access service.</p><p>Use the session bar above to sign out or add a backup passkey. These are the existing controls; this page does not change access policy.</p></section> : null}
          <section className="panel report-section"><h2>Recovery and operating scope</h2><p>Recovery uses the private offline procedure. The encrypted USB access image backs up access setup, not the passkey itself; keep its password separately. Journal and evidence backups are separate.</p><p>No password, SMS or email fallback is provided. This is the Mac-only testing workspace, not a VPS or public launch.</p><p>Backup currency, broker freshness and production readiness are not verified by this settings page.</p></section>
        </> : <section className="panel report-section"><h2>Keep the scopes separate</h2><p>Total P&amp;L remains unavailable when realized history and current holdings cover different scopes. This overview does not calculate profits, infer missing trades or label saved data as live.</p><Link className="workspace-action" href={view === 'today' ? LOCAL_ROUTES.data : LOCAL_ROUTES.reports}>{view === 'today' ? 'Check data coverage' : 'Open the full reports'} <ArrowRight aria-hidden="true" /></Link></section>}
      </div>
    </section>
  </main>;
}
