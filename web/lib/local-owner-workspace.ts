import { accessJson } from './local-owner-access.ts';
import { fetchReportAccounts, fetchRealizedHistory, type ReportContext } from './local-owner-reports.ts';

export type SavedWorkspace = { current: ReportContext; history: ReportContext };
export type WorkspaceSession = { passkeyCount: number };

export async function fetchSavedWorkspace(signal?: AbortSignal): Promise<SavedWorkspace> {
  const accounts = await fetchReportAccounts(signal);
  if (accounts.metadata.current_valuation_asof === null) throw new Error('The saved snapshot date is unavailable.');
  const history = await fetchRealizedHistory({
    from: accounts.metadata.coverage_start_date, to: accounts.metadata.coverage_end_date,
    accountAlias: '', symbol: '',
  }, signal);
  // One coherent accepted release, not metadata mixed across an API restart.
  for (const key of ['report_release_uid', 'report_release_fingerprint', 'coverage_start_date',
    'coverage_end_date', 'calculation_version', 'generated_at_utc', 'owner_accepted_at_utc'] as const) {
    if (accounts.metadata[key] !== history.metadata[key]) throw new Error('The saved reports changed. Reload to check the new release.');
  }
  // These screens need context only. Do not retain account amounts or trade rows.
  return {
    current: { metadata: accounts.metadata, counts: accounts.counts },
    history: { metadata: history.metadata, counts: history.counts },
  };
}

export async function fetchWorkspaceSession(): Promise<WorkspaceSession> {
  const value = await accessJson<{
    contract_version: string; authenticated: boolean; passkey_count: number | null;
    expires_in_seconds: number | null;
  }>('session');
  if (value.contract_version !== 'onejournal.mac-passkey.v1' || value.authenticated !== true
    || !Number.isSafeInteger(value.passkey_count) || (value.passkey_count ?? 0) < 1
    || typeof value.expires_in_seconds !== 'number' || !Number.isFinite(value.expires_in_seconds)
    || value.expires_in_seconds <= 0 || value.expires_in_seconds > 8 * 60 * 60) {
    throw new Error('The protected session could not be verified.');
  }
  return { passkeyCount: value.passkey_count! };
}
