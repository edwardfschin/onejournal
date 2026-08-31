/**
 * Hand-maintained compatibility seam for `onejournal.web-fixture.v1`.
 *
 * WEB-W05 deliberately consumes only this public fixture shape. It does not
 * read DuckDB, raw evidence, dashboard artifacts, or financial calculations.
 */

import type { PreviewFixture } from './generated/onejournal-api';

export type { DecimalMetric, PreviewFixture, QualityState } from './generated/onejournal-api';

export async function fetchPreviewFixture(baseUrl: string): Promise<PreviewFixture> {
  const response = await fetch(`${baseUrl}/api/v1/preview`);
  if (!response.ok) {
    throw new Error('The demonstration fixture is unavailable.');
  }
  return response.json() as Promise<PreviewFixture>;
}
