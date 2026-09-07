export const DEMO_ROUTES = {
  today: '/demo',
  portfolio: '/demo/portfolio',
  trades: '/demo/trades',
  journal: '/demo/journal',
  reports: '/demo/reports',
  data: '/demo/data',
  settings: '/demo/settings',
} as const;

export const LOCAL_ROUTES = {
  portfolio: '/local/portfolio',
  trades: '/local/trades',
  journal: '/local/journal',
} as const;

export const LEGACY_ROUTE_REDIRECTS = [
  { source: '/', destination: DEMO_ROUTES.today },
  { source: '/portfolio', destination: DEMO_ROUTES.portfolio },
  { source: '/trades', destination: DEMO_ROUTES.trades },
  { source: '/journal', destination: DEMO_ROUTES.journal },
  { source: '/reports', destination: DEMO_ROUTES.reports },
  { source: '/data', destination: DEMO_ROUTES.data },
  { source: '/settings', destination: DEMO_ROUTES.settings },
  { source: '/portfolio/local', destination: LOCAL_ROUTES.portfolio },
  { source: '/journal/local', destination: LOCAL_ROUTES.journal },
] as const;
