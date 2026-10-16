import { fetchLocalOwner } from './local-owner-access.ts';

const PATH = '/api/v1/local-owner/financial-upload';
const CONTRACT = 'onejournal.financial-upload.v1';
export type FinancialUploadReceipt = {
  state: 'published'; replayed: boolean; report_release_uid: string;
  portfolio_asof: string; coverage_end_date: string;
  reportable_count: number; withheld_count: number;
};

export async function financialUploadAvailable(): Promise<boolean> {
  const response = await fetchLocalOwner(PATH);
  if (!response.ok) throw new Error('Upload status is unavailable.');
  const value = await response.json();
  if (value.contract_version !== CONTRACT || typeof value.enabled !== 'boolean')
    throw new Error('Upload status could not be verified.');
  return value.enabled;
}

async function packageFiles(files: File[], count: number) {
  if (files.length !== count || !files.some(file => file.name === 'acquisition-manifest.json')
      || new Set(files.map(file => file.name)).size !== count
      || files.some(file => !file.size || file.size > 4 * 1024 * 1024))
    throw new Error(`Select the manifest and its response files: ${count} JSON files for this package.`);
  return { files: await Promise.all(files.map(async file => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 32768)
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
    return { name: file.name, content_base64: btoa(binary) };
  })) };
}

export async function publishFinancialUpload(positions: File[], activity: File[]): Promise<FinancialUploadReceipt> {
  const body = { positions: await packageFiles(positions, 2), activity: await packageFiles(activity, 3) };
  const response = await fetchLocalOwner(PATH, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(response.status === 422
    ? 'These packages could not be published. They must be complete, newer than the saved Portfolio, and for this account. Saved data is unchanged.'
    : response.status === 413 ? 'These packages are too large. Saved data is unchanged.'
      : 'Completion could not be confirmed. Reload saved data to see whether the update was saved.');
  const value = await response.json();
  if (value.contract_version !== CONTRACT || value.state !== 'published' || typeof value.replayed !== 'boolean'
      || typeof value.report_release_uid !== 'string'
      || !/^\d{4}-\d{2}-\d{2}$/.test(value.portfolio_asof)
      || !/^\d{4}-\d{2}-\d{2}$/.test(value.coverage_end_date)
      || !Number.isSafeInteger(value.reportable_count) || value.reportable_count < 0
      || !Number.isSafeInteger(value.withheld_count) || value.withheld_count < 0)
    throw new Error('The saved result could not be confirmed. Reload saved data before trying again.');
  return value;
}
