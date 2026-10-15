import { fetchLocalOwner } from './local-owner-access.ts';

const PATH = '/api/v1/local-owner/manual-capture';
const CONTRACT = 'onejournal.manual-capture-upload.v1';
export type ManualCaptureReceipt = {
  state: 'verified_and_staged'; scope: 'current_positions' | 'activity';
  manifest_sha256: string; replayed: boolean;
};

export async function manualCaptureAvailable(): Promise<boolean> {
  const response = await fetchLocalOwner(PATH);
  if (!response.ok) throw new Error('Capture upload status is unavailable.');
  const value = await response.json();
  if (value.contract_version !== CONTRACT || typeof value.enabled !== 'boolean')
    throw new Error('Capture upload status could not be verified.');
  return value.enabled;
}

function encode(bytes: Uint8Array): string {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 32768)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  return btoa(binary);
}

export async function stageManualCapture(selected: File[]): Promise<ManualCaptureReceipt> {
  if (![2, 3].includes(selected.length) || !selected.some(file => file.name === 'acquisition-manifest.json')
      || new Set(selected.map(file => file.name)).size !== selected.length
      || selected.some(file => file.size === 0 || file.size > 4 * 1024 * 1024))
    throw new Error('Select one capture manifest and its exact response files (two or three JSON files total).');
  const files = await Promise.all(selected.map(async file => ({
    name: file.name, content_base64: encode(new Uint8Array(await file.arrayBuffer())),
  })));
  const response = await fetchLocalOwner(PATH, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ files }),
  });
  if (!response.ok) throw new Error(response.status === 413
    ? 'The selected package is too large. Saved results are unchanged.'
    : 'The package could not be verified. Saved results are unchanged.');
  const value = await response.json();
  if (value.contract_version !== CONTRACT || value.state !== 'verified_and_staged'
      || !['current_positions', 'activity'].includes(value.scope)
      || !/^[0-9a-f]{64}$/.test(value.manifest_sha256)
      || typeof value.replayed !== 'boolean'
      || value.journal_written !== false || value.financial_publication_authorized !== false)
    throw new Error('Capture receipt could not be verified. Saved results are unchanged.');
  return { state: value.state, scope: value.scope, manifest_sha256: value.manifest_sha256, replayed: value.replayed };
}
