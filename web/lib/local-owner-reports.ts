export const LOCAL_OWNER_REPORTS_API_PREFIX = '/api/v1/local-owner/reports';

export type Quality = 'valid' | 'stale' | 'incomplete' | 'reconciliation_pending' | 'unavailable' | 'failed';
export type ReportingMetadata = {
  contract_version: 'onejournal.phase1-report-release.v1';
  report_release_uid: string;
  report_release_fingerprint: string;
  selection_fingerprint: string;
  coverage_start_date: string;
  coverage_end_date: string;
  current_valuation_asof: string | null;
  calculation_version: string;
  generated_at_utc: string;
  owner_accepted_at_utc: string;
  quality: Quality;
  reason_counts: Record<string, number>;
};
export type Counts = { processed_count: number; available_count: number; unavailable_count: number; reconciliation_pending_count: number };
export type ReportContext = { metadata: ReportingMetadata; counts: Counts };
export type AccountBreakdown = { account_alias: string; symbol: null; currency: string; position_count: number; open_cost_basis: string | null; broker_market_value: string | null; unrealized_pnl: string | null; open_cost_basis_status: Quality; broker_market_value_status: Quality; unrealized_pnl_status: Quality; reason_codes: string[] };
export type SymbolBreakdown = Omit<AccountBreakdown, 'symbol'> & { symbol: string };
export type RealizedItem = { item_uid: string; account_alias: string; symbol: string; asset_class: 'equity' | 'option'; close_market_date: string; currency: string; realized_pnl: string; item_status: 'valid'; reason_codes: string[]; calculation_version: string };
export type AccountReport = ReportContext & { accounts: AccountBreakdown[] };
export type SymbolReport = ReportContext & { symbols: SymbolBreakdown[] };
export type HistoryReport = ReportContext & { items: RealizedItem[] };
export type HistoryFilters = { from: string; to: string; accountAlias: string; symbol: string };

const qualities = new Set(['valid', 'stale', 'incomplete', 'reconciliation_pending', 'unavailable', 'failed']);
const decimal = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const sha256 = /^[0-9a-f]{64}$/;
const isoDate = /^\d{4}-\d{2}-\d{2}$/;
const invalidReport = 'The reporting service returned an invalid report. Reload after checking the service.';
function object(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function text(value: unknown): value is string { return typeof value === 'string' && value.length > 0; }
function count(value: unknown): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0; }
function date(value: unknown): value is string { return text(value) && isoDate.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value; }
function utc(value: unknown): value is string { return text(value) && /(?:Z|\+00:00)$/.test(value) && !Number.isNaN(Date.parse(value)); }
function reasons(value: unknown): value is string[] { return Array.isArray(value) && value.every(text); }
function currency(value: unknown): value is string { return text(value) && /^[A-Z]{3}$/.test(value); }

function context(value: unknown): ReportContext {
  if (!object(value) || !object(value.metadata) || !object(value.counts)) throw new Error(invalidReport);
  const m = value.metadata;
  const c = value.counts;
  if (m.contract_version !== 'onejournal.phase1-report-release.v1' || !text(m.report_release_uid)
    || !text(m.report_release_fingerprint) || !sha256.test(m.report_release_fingerprint)
    || !text(m.selection_fingerprint) || !sha256.test(m.selection_fingerprint)
    || !date(m.coverage_start_date) || !date(m.coverage_end_date) || m.coverage_start_date > m.coverage_end_date
    || !(m.current_valuation_asof === null || date(m.current_valuation_asof))
    || !text(m.calculation_version) || !utc(m.generated_at_utc) || !utc(m.owner_accepted_at_utc)
    || !text(m.quality) || !qualities.has(m.quality) || !object(m.reason_counts)
    || !Object.values(m.reason_counts).every(count)
    || !count(c.processed_count) || !count(c.available_count) || !count(c.unavailable_count) || !count(c.reconciliation_pending_count)
    || c.processed_count !== c.available_count + c.unavailable_count + c.reconciliation_pending_count
    || Object.values(m.reason_counts).reduce((sum: number, n) => sum + (n as number), 0) !== c.unavailable_count + c.reconciliation_pending_count
    || (m.quality === 'valid' && (c.unavailable_count !== 0 || c.reconciliation_pending_count !== 0))) throw new Error(invalidReport);
  return value as ReportContext;
}

function breakdown(value: unknown, withSymbol: boolean): boolean {
  if (!object(value) || !text(value.account_alias) || !currency(value.currency) || !count(value.position_count)
    || !(withSymbol ? text(value.symbol) : value.symbol === null) || !reasons(value.reason_codes)) return false;
  return ['open_cost_basis', 'broker_market_value', 'unrealized_pnl'].every((key) => {
    const amount = value[key];
    const quality = value[`${key}_status`];
    return text(quality) && qualities.has(quality) && (amount === null ? quality !== 'valid' : text(amount) && decimal.test(amount) && quality !== 'unavailable' && quality !== 'failed');
  });
}

function realizedItem(value: unknown): boolean {
  return object(value) && text(value.item_uid) && text(value.account_alias) && text(value.symbol)
    && (value.asset_class === 'equity' || value.asset_class === 'option') && date(value.close_market_date)
    && currency(value.currency) && text(value.realized_pnl) && decimal.test(value.realized_pnl)
    && value.item_status === 'valid' && reasons(value.reason_codes) && text(value.calculation_version);
}

async function request(path: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const res = await fetch(path, { cache: 'no-store', signal });
  if (!res.ok) throw new Error(res.status === 422 ? 'Check the dates, account, and symbol. This selection is not supported.' : 'The reporting service is unavailable. Try again when it is running.');
  const value: unknown = await res.json();
  context(value);
  return value as Record<string, unknown>;
}

export async function fetchReportAccounts(signal?: AbortSignal): Promise<AccountReport> {
  const value = await request(`${LOCAL_OWNER_REPORTS_API_PREFIX}/current/accounts`, signal);
  if (!Array.isArray(value.accounts) || !value.accounts.every((row) => breakdown(row, false))) throw new Error(invalidReport);
  return value as AccountReport;
}
export async function fetchReportSymbols(signal?: AbortSignal): Promise<SymbolReport> {
  const value = await request(`${LOCAL_OWNER_REPORTS_API_PREFIX}/current/symbols`, signal);
  if (!Array.isArray(value.symbols) || !value.symbols.every((row) => breakdown(row, true))) throw new Error(invalidReport);
  return value as SymbolReport;
}

function historyQuery(filters: HistoryFilters) {
  const query = new URLSearchParams({ from_date: filters.from, to_date: filters.to });
  if (filters.accountAlias) query.set('account_alias', filters.accountAlias);
  if (filters.symbol) query.set('symbol', filters.symbol);
  return query;
}

export async function fetchRealizedHistory(filters: HistoryFilters, signal?: AbortSignal): Promise<HistoryReport> {
  const value = await request(`${LOCAL_OWNER_REPORTS_API_PREFIX}/realized-history?${historyQuery(filters)}`, signal);
  const report = value as HistoryReport;
  if (!Array.isArray(value.items) || !value.items.every(realizedItem) || value.items.length !== report.counts.available_count
    || ((report.metadata.quality === 'unavailable' || report.metadata.quality === 'failed') && value.items.length !== 0)) throw new Error(invalidReport);
  return report;
}

// Check the export belongs to the loaded release/selection before saving it.
export async function fetchReportCsv(current: ReportContext, history?: { report: HistoryReport; filters: HistoryFilters }): Promise<Blob> {
  const path = history ? `realized-history.csv?${historyQuery(history.filters)}` : 'current/positions.csv';
  const res = await fetch(`${LOCAL_OWNER_REPORTS_API_PREFIX}/${path}`, { cache: 'no-store' });
  const expected = history?.report ?? current;
  if (!res.ok || !res.headers.get('content-type')?.startsWith('text/csv')
    || res.headers.get('X-OneJournal-Report-Release-Fingerprint') !== expected.metadata.report_release_fingerprint
    || !sha256.test(res.headers.get('X-OneJournal-Selection-Fingerprint') ?? '')
    || ['unavailable', 'failed'].includes(res.headers.get('X-OneJournal-Quality') ?? 'unavailable')) throw new Error('The download is unavailable or no longer matches this report. Reload the report and try again.');
  if (history) {
    const expectedHeaders = {
      'X-OneJournal-Selection-Fingerprint': expected.metadata.selection_fingerprint,
      'X-OneJournal-Quality': expected.metadata.quality,
      'X-OneJournal-Processed-Count': String(expected.counts.processed_count),
      'X-OneJournal-Available-Count': String(expected.counts.available_count),
      'X-OneJournal-Unavailable-Count': String(expected.counts.unavailable_count),
      'X-OneJournal-Reconciliation-Pending-Count': String(expected.counts.reconciliation_pending_count),
    };
    if (Object.entries(expectedHeaders).some(([key, value]) => res.headers.get(key) !== value)) throw new Error('The download does not match the loaded selection. Reload the report and try again.');
    const actualReasons: unknown = JSON.parse(res.headers.get('X-OneJournal-Reason-Counts') ?? 'null');
    if (!object(actualReasons) || Object.keys(actualReasons).length !== Object.keys(expected.metadata.reason_counts).length
      || Object.entries(expected.metadata.reason_counts).some(([key, value]) => actualReasons[key] !== value)) throw new Error('The download has different omission reasons. Reload the report and try again.');
  }
  return res.blob();
}

export function formatReportMoney(value: string | null, currencyCode: string) {
  if (value === null) return 'Unavailable';
  const negative = value.startsWith('-');
  const [whole, fraction = ''] = (negative ? value.slice(1) : value).split('.');
  let cents = BigInt(whole) * BigInt(100) + BigInt(fraction.slice(0, 2).padEnd(2, '0'));
  if ((fraction[2] ?? '0') >= '5') cents += BigInt(1);
  const digits = cents.toString().padStart(3, '0');
  const grouped = digits.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${currencyCode} ${negative && cents !== BigInt(0) ? '-' : ''}${grouped}.${digits.slice(-2)}`;
}
