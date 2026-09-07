export const LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH =
  '/api/v1/local-owner/portfolio/current';
export const BROKER_CURRENT_CONTRACT_VERSION =
  'onejournal.api.broker-current-position-valuation.v1';

export type BrokerCurrentPosition = {
  instrument_key: string;
  asset_class: 'equity' | 'option';
  market_scope: string;
  currency: string;
  symbol: string | null;
  underlying_symbol: string | null;
  expiry: string | null;
  option_right: 'CALL' | 'PUT' | null;
  strike: string | null;
  multiplier: string | null;
  quantity: string | null;
  tax_lot_average_price: string | null;
  open_cost_basis: string | null;
  broker_market_value: string | null;
  broker_reported_unrealized_pnl: string | null;
  unrealized_pnl: string | null;
  unrealized_reconciliation_difference: string | null;
  cost_basis_status: 'available' | 'unavailable';
  market_value_status: 'available' | 'unavailable';
  unrealized_pnl_status: 'available' | 'unavailable';
  position_status: 'available' | 'partial' | 'unavailable';
  reason_codes: string[];
};

export type BrokerCurrentPortfolioTotal = {
  currency: string;
  portfolio_cost_basis: string | null;
  portfolio_market_value: string | null;
  portfolio_unrealized_pnl: string | null;
};

export type BrokerCurrentPortfolio = {
  metadata: {
    contract_version: typeof BROKER_CURRENT_CONTRACT_VERSION;
    view_type: 'broker_reconciled_current_position';
    source_contract_version: string;
    basis_method: string;
    valuation_run_uid: string;
    result_fingerprint: string;
    snapshot_uid: string;
    source_broker: string;
    asof: string;
    retrieved_at: string;
    evaluated_at: string;
    max_snapshot_age_seconds: number;
    snapshot_age_seconds: string;
    currency_quantum_by_currency: Record<string, string>;
    release_status: 'owner_accepted';
    owner_acceptance_uid: string;
    owner_accepted_at: string;
  };
  counts: {
    position_count: number;
    cost_basis_available_count: number;
    market_value_available_count: number;
    unrealized_pnl_available_count: number;
  };
  positions: BrokerCurrentPosition[];
  portfolio_totals: BrokerCurrentPortfolioTotal[];
  complete_portfolio_cost_basis_available: boolean;
  complete_portfolio_market_value_available: boolean;
  complete_portfolio_unrealized_pnl_available: boolean;
  final_status: 'complete' | 'partial';
};

const DECIMAL_STRING = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const POSITIVE_DECIMAL_STRING = /^(?:0\.(?:0*[1-9][0-9]*)|[1-9][0-9]*(?:\.[0-9]+)?)$/;
const SHA256 = /^[0-9a-f]{64}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isDecimalOrNull(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && DECIMAL_STRING.test(value));
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isUtcInstant(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    (value.endsWith('Z') || value.endsWith('+00:00')) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function isNonNegativeDecimal(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    DECIMAL_STRING.test(value) &&
    !value.startsWith('-')
  );
}

function requireCount(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new Error('The portfolio returned invalid availability counts.');
  }
  return value;
}

function assertMetric(
  position: Record<string, unknown>,
  statusField: string,
  valueField: string,
) {
  const status = position[statusField];
  const value = position[valueField];
  if ((status !== 'available' && status !== 'unavailable') || !isDecimalOrNull(value)) {
    throw new Error('The portfolio returned an invalid metric contract.');
  }
  if ((status === 'available') !== (value !== null)) {
    throw new Error('The portfolio returned inconsistent metric availability.');
  }
}

export function validateBrokerCurrentPortfolio(value: unknown): BrokerCurrentPortfolio {
  if (!isObject(value) || !isObject(value.metadata) || !isObject(value.counts)) {
    throw new Error('The portfolio returned an invalid contract.');
  }
  if (
    value.metadata.contract_version !== BROKER_CURRENT_CONTRACT_VERSION ||
    value.metadata.view_type !== 'broker_reconciled_current_position' ||
    value.metadata.release_status !== 'owner_accepted' ||
    !isNonEmptyString(value.metadata.source_contract_version) ||
    !isNonEmptyString(value.metadata.basis_method) ||
    !isNonEmptyString(value.metadata.valuation_run_uid) ||
    typeof value.metadata.result_fingerprint !== 'string' ||
    !SHA256.test(value.metadata.result_fingerprint) ||
    !isNonEmptyString(value.metadata.snapshot_uid) ||
    !isNonEmptyString(value.metadata.source_broker) ||
    !isIsoDate(value.metadata.asof) ||
    !isUtcInstant(value.metadata.retrieved_at) ||
    !isUtcInstant(value.metadata.evaluated_at) ||
    !isUtcInstant(value.metadata.owner_accepted_at) ||
    !isNonEmptyString(value.metadata.owner_acceptance_uid) ||
    !isNonNegativeDecimal(value.metadata.snapshot_age_seconds)
  ) {
    throw new Error('The portfolio is not an owner-accepted broker-current result.');
  }
  if (
    Date.parse(value.metadata.retrieved_at) > Date.parse(value.metadata.evaluated_at) ||
    Date.parse(value.metadata.evaluated_at) > Date.parse(value.metadata.owner_accepted_at)
  ) {
    throw new Error('The portfolio returned inconsistent time lineage.');
  }
  requireCount(value.metadata.max_snapshot_age_seconds);
  if (!isObject(value.metadata.currency_quantum_by_currency)) {
    throw new Error('The portfolio returned invalid currency lineage.');
  }
  const currencyQuanta = Object.entries(value.metadata.currency_quantum_by_currency);
  if (
    currencyQuanta.length < 1 ||
    currencyQuanta.some(
      ([currency, quantum]) =>
        !currency || typeof quantum !== 'string' || !POSITIVE_DECIMAL_STRING.test(quantum),
    )
  ) {
    throw new Error('The portfolio returned invalid currency lineage.');
  }
  if (!Array.isArray(value.positions) || !Array.isArray(value.portfolio_totals)) {
    throw new Error('The portfolio returned invalid position or total records.');
  }
  const positionCount = requireCount(value.counts.position_count);
  const expectedCostBasisAvailable = requireCount(
    value.counts.cost_basis_available_count,
  );
  const expectedMarketValueAvailable = requireCount(
    value.counts.market_value_available_count,
  );
  const expectedUnrealizedAvailable = requireCount(
    value.counts.unrealized_pnl_available_count,
  );
  if (positionCount < 1 || value.positions.length !== positionCount) {
    throw new Error('The portfolio position count does not match its records.');
  }

  let costBasisAvailable = 0;
  let marketValueAvailable = 0;
  let unrealizedAvailable = 0;
  for (const item of value.positions) {
    if (!isObject(item)) throw new Error('The portfolio returned an invalid position.');
    if (
      !isNonEmptyString(item.instrument_key) ||
      (item.asset_class !== 'equity' && item.asset_class !== 'option') ||
      !isNonEmptyString(item.market_scope) ||
      !isNonEmptyString(item.currency) ||
      !isStringOrNull(item.symbol) ||
      !isStringOrNull(item.underlying_symbol) ||
      !(item.expiry === null || isIsoDate(item.expiry)) ||
      (item.option_right !== null && item.option_right !== 'CALL' && item.option_right !== 'PUT') ||
      !Array.isArray(item.reason_codes) ||
      !item.reason_codes.every((reason) => typeof reason === 'string')
    ) {
      throw new Error('The portfolio returned an invalid position identity or state.');
    }
    for (const field of [
      'strike',
      'multiplier',
      'tax_lot_average_price',
      'broker_reported_unrealized_pnl',
      'unrealized_reconciliation_difference',
    ]) {
      if (!isDecimalOrNull(item[field])) {
        throw new Error('The portfolio returned an invalid decimal value.');
      }
    }
    assertMetric(item, 'cost_basis_status', 'open_cost_basis');
    assertMetric(item, 'market_value_status', 'broker_market_value');
    assertMetric(item, 'unrealized_pnl_status', 'unrealized_pnl');
    if (item.quantity === null || !isDecimalOrNull(item.quantity)) {
      throw new Error('The accepted portfolio omitted a position quantity.');
    }
    if (item.cost_basis_status === 'available') costBasisAvailable += 1;
    if (item.market_value_status === 'available') marketValueAvailable += 1;
    if (item.unrealized_pnl_status === 'available') unrealizedAvailable += 1;
    const availableMetricCount = [
      item.cost_basis_status,
      item.market_value_status,
      item.unrealized_pnl_status,
    ].filter((status) => status === 'available').length;
    const expectedPositionStatus =
      availableMetricCount === 3
        ? 'available'
        : availableMetricCount === 0
          ? 'unavailable'
          : 'partial';
    if (item.position_status !== expectedPositionStatus) {
      throw new Error('The portfolio returned an inconsistent position state.');
    }
  }
  if (
    costBasisAvailable !== expectedCostBasisAvailable ||
    marketValueAvailable !== expectedMarketValueAvailable ||
    unrealizedAvailable !== expectedUnrealizedAvailable
  ) {
    throw new Error('The portfolio availability counts do not match its positions.');
  }

  const completeMetrics = [
    ['complete_portfolio_cost_basis_available', 'portfolio_cost_basis', costBasisAvailable],
    ['complete_portfolio_market_value_available', 'portfolio_market_value', marketValueAvailable],
    [
      'complete_portfolio_unrealized_pnl_available',
      'portfolio_unrealized_pnl',
      unrealizedAvailable,
    ],
  ] as const;
  const totalCurrencies = new Set<string>();
  for (const item of value.portfolio_totals) {
    if (!isObject(item) || !isNonEmptyString(item.currency) || totalCurrencies.has(item.currency)) {
      throw new Error('The portfolio returned an invalid total currency scope.');
    }
    totalCurrencies.add(item.currency);
  }
  if (
    totalCurrencies.size !== currencyQuanta.length ||
    currencyQuanta.some(([currency]) => !totalCurrencies.has(currency))
  ) {
    throw new Error('The portfolio total currencies do not match their quantum lineage.');
  }
  for (const [flagField, totalField, availableCount] of completeMetrics) {
    const flag = value[flagField];
    if (typeof flag !== 'boolean' || flag !== (availableCount === positionCount)) {
      throw new Error('The portfolio returned an invalid complete-total flag.');
    }
    for (const item of value.portfolio_totals) {
      if (!isObject(item) || !isDecimalOrNull(item[totalField])) {
        throw new Error('The portfolio returned an invalid total.');
      }
      if (flag !== (item[totalField] !== null)) {
        throw new Error('The portfolio total does not match its availability flag.');
      }
    }
  }
  const expectedFinalStatus = completeMetrics.every(
    ([flagField]) => value[flagField] === true,
  )
    ? 'complete'
    : 'partial';
  if (value.final_status !== expectedFinalStatus) {
    throw new Error('The portfolio returned an inconsistent final status.');
  }

  return value as BrokerCurrentPortfolio;
}

export async function fetchBrokerCurrentPortfolio(): Promise<BrokerCurrentPortfolio> {
  const response = await fetch(LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH, {
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error('The accepted broker-current portfolio is unavailable.');
  }
  return validateBrokerCurrentPortfolio(await response.json());
}
