import { fetchLocalOwner } from './local-owner-access.ts';

const PATH = '/api/v1/local-owner/data-refresh';
export const REFRESH_STATES = ['queued', 'capturing', 'captured', 'closed', 'failed'] as const;
export type RefreshState = typeof REFRESH_STATES[number];
export type RefreshJob = { request_id: string; provider: string; requested_at: string; state: RefreshState };
export type RefreshStatus = { enabled: boolean; provider: string; latest: RefreshJob | null };

function job(value: unknown): RefreshJob {
  const v = value as RefreshJob;
  if (!v || typeof v.request_id !== 'string' || !/^[0-9a-f-]{36}$/.test(v.request_id)
    || typeof v.provider !== 'string' || !/^[a-z][a-z0-9_]{1,31}$/.test(v.provider)
    || typeof v.requested_at !== 'string' || !Number.isFinite(Date.parse(v.requested_at))
    || !REFRESH_STATES.includes(v.state)) throw new Error('Refresh status could not be verified.');
  return { request_id: v.request_id, provider: v.provider, requested_at: v.requested_at, state: v.state };
}

export async function fetchRefreshStatus(): Promise<RefreshStatus> {
  const response = await fetchLocalOwner(PATH);
  if (!response.ok) throw new Error('Refresh status is unavailable. Your saved data is unchanged.');
  const v = await response.json();
  if (v.contract_version !== 'onejournal.data-refresh.v1' || typeof v.enabled !== 'boolean'
    || typeof v.provider !== 'string' || !/^[a-z][a-z0-9_]{1,31}$/.test(v.provider))
    throw new Error('Refresh status could not be verified.');
  const latest = v.latest === null ? null : job(v.latest);
  if (latest && latest.provider !== v.provider) throw new Error('Refresh connection differs.');
  return { enabled: v.enabled, provider: v.provider, latest };
}

export async function requestRefresh(requestId: string): Promise<RefreshJob> {
  const response = await fetchLocalOwner(PATH, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId }) });
  if (!response.ok) throw new Error(response.status === 409
    ? 'A refresh is already pending. Check its status.'
    : 'Refresh was not confirmed. Check its status before trying again.');
  return job(await response.json());
}
