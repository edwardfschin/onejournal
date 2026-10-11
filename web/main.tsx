import { Component, lazy, Suspense, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import PasskeyBoundary from '@/components/passkey-boundary';
import { DEMO_ROUTES, LOCAL_ROUTES, LEGACY_ROUTE_REDIRECTS } from '@/lib/routes';
import './app/globals.css';

class PageLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <main className="content-frame">
      <h1>Workspace could not load</h1>
      <p>No substitute data is shown. Reload the page or check the local service.</p>
      <a href={window.location.pathname + window.location.search}>Reload OneJournal</a>
    </main> : this.props.children;
  }
}

const pages = {
  [DEMO_ROUTES.today]: lazy(() => import('./app/demo/page')),
  [DEMO_ROUTES.portfolio]: lazy(() => import('./app/demo/portfolio/page')),
  [DEMO_ROUTES.trades]: lazy(() => import('./app/demo/trades/page')),
  [DEMO_ROUTES.journal]: lazy(() => import('./app/demo/journal/page')),
  [DEMO_ROUTES.reports]: lazy(() => import('./app/demo/reports/page')),
  [DEMO_ROUTES.data]: lazy(() => import('./app/demo/data/page')),
  [DEMO_ROUTES.settings]: lazy(() => import('./app/demo/settings/page')),
  [LOCAL_ROUTES.today]: lazy(() => import('./app/local/today/page')),
  [LOCAL_ROUTES.portfolio]: lazy(() => import('./app/local/portfolio/page')),
  [LOCAL_ROUTES.trades]: lazy(() => import('./app/local/trades/page')),
  [LOCAL_ROUTES.journal]: lazy(() => import('./app/local/journal/page')),
  [LOCAL_ROUTES.reports]: lazy(() => import('./app/local/reports/page')),
  [LOCAL_ROUTES.data]: lazy(() => import('./app/local/data/page')),
  [LOCAL_ROUTES.settings]: lazy(() => import('./app/local/settings/page')),
};

const redirect = LEGACY_ROUTE_REDIRECTS.find(({ source }) => source === window.location.pathname);
if (redirect) {
  window.location.replace(redirect.destination + window.location.search + window.location.hash);
} else {
  const Page = pages[window.location.pathname as keyof typeof pages];
  createRoot(document.getElementById('root')!).render(<PageLoadBoundary>{Page ?
    <PasskeyBoundary enabled={import.meta.env.PROD || import.meta.env.VITE_ONEJOURNAL_PASSKEY_MODE === '1'}>
      <Suspense fallback={<main className="content-frame"><output>Loading OneJournal…</output></main>}><Page /></Suspense>
    </PasskeyBoundary> :
    <main className="content-frame"><h1>Page not found</h1><a href={DEMO_ROUTES.today}>Open OneJournal demo</a></main>}</PageLoadBoundary>);
}
