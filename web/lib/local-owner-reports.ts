export const LOCAL_OWNER_REPORTS_API_PREFIX = '/api/v1/local-owner/reports';

export type ReportingMetadata = {
  contract_version: 'onejournal.phase1-report-release.v1';
  report_release_uid: string;
  report_release_fingerprint: string;
  selection_fingerprint: string;
  coverage_start_date: string;
  coverage_end_date: string;
  quality: 'valid' | 'stale' | 'incomplete' | 'reconciliation_pending' | 'unavailable' | 'failed';
  reason_counts: Record<string, number>;
};

type Counts = { processed_count: number; available_count: number; unavailable_count: number; reconciliation_pending_count: number };
export type AccountBreakdown = { account_alias: string; symbol: null; currency: string; position_count: number; open_cost_basis: string | null; broker_market_value: string | null; unrealized_pnl: string | null; open_cost_basis_status: string; broker_market_value_status: string; unrealized_pnl_status: string; reason_codes: string[] };
export type SymbolBreakdown = Omit<AccountBreakdown, 'symbol'> & { symbol: string };
export type RealizedItem = { item_uid: string; account_alias: string; symbol: string; asset_class: 'equity' | 'option'; close_market_date: string; currency: string; realized_pnl: string; item_status: 'valid'; reason_codes: string[]; calculation_version: string };

function object(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function response(value: unknown): { metadata: ReportingMetadata; counts: Counts } {
  if (!object(value) || !object(value.metadata) || !object(value.counts) || value.metadata.contract_version !== 'onejournal.phase1-report-release.v1') throw new Error('The reporting service returned an invalid contract.');
  return value as { metadata: ReportingMetadata; counts: Counts };
}

async function request(path: string) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error('The accepted reporting release is unavailable.');
  return response(await res.json());
}

export async function fetchReportAccounts() { const value = await request(`${LOCAL_OWNER_REPORTS_API_PREFIX}/current/accounts`); return { ...value, accounts: (value as typeof value & { accounts: AccountBreakdown[] }).accounts }; }
export async function fetchReportSymbols() { const value = await request(`${LOCAL_OWNER_REPORTS_API_PREFIX}/current/symbols`); return { ...value, symbols: (value as typeof value & { symbols: SymbolBreakdown[] }).symbols }; }
export async function fetchRealizedHistory(from: string, to: string) { const query = new URLSearchParams({ from_date: from, to_date: to }); const value = await request(`${LOCAL_OWNER_REPORTS_API_PREFIX}/realized-history?${query}`); return { ...value, items: (value as typeof value & { items: RealizedItem[] }).items }; }
