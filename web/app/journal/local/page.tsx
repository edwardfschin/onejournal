'use client';

import { useEffect, useRef, useState } from 'react';
import type { SyntheticEvent } from 'react';
import Link from 'next/link';
import {
  Activity, ArrowRight, BookOpenText, BriefcaseBusiness, CheckCircle2,
  ChevronDown, ChevronRight, Database, FileChartColumn, LayoutDashboard, LoaderCircle,
  LockKeyhole, Menu, NotebookPen, RefreshCw, Search, Settings, ShieldCheck,
} from 'lucide-react';
import { LOCAL_ROUTES } from '@/lib/routes';

const API_ROOT = '/api/v5/local-owner/journal';
const CONTRACT_VERSION = 'onejournal.local-owner-journal.v5';

const navItems = [
  ['Today', LayoutDashboard, null], ['Portfolio', BriefcaseBusiness, LOCAL_ROUTES.portfolio],
  ['Trades', Activity, LOCAL_ROUTES.trades], ['Journal', BookOpenText, LOCAL_ROUTES.journal],
  ['Reports', FileChartColumn, null], ['Data', Database, null],
] as const;

const reviewStatuses = ['unreviewed', 'needs_review', 'mistake_review', 'reviewed'];
const setupQualities = ['unknown', 'good', 'acceptable', 'poor', 'mistake'];
const entryTypes = [
  'pre_trade_plan', 'entry_thesis', 'execution_review', 'exit_review',
  'post_trade_reflection', 'weekly_review', 'monthly_review', 'mistake', 'lesson', 'note',
];

type Metadata = { contract_version: string; mode: string };
type Episode = {
  episode_uid: string;
  source_broker: string;
  primary_symbol: string;
  asset_class: string;
  strategy_type: string;
  strategy_label: string;
  opened_at: string;
  episode_status: string;
  review_status: string;
  setup_quality: string;
  lifecycle_quality: string;
  lifecycle_reason: string | null;
  position_reconciliation_status: string;
  instrument_count: number;
  execution_count: number;
  lifecycle_sequence: number;
  lifecycle_count: number;
  instrument_summary: string;
};
type Entry = {
  entry_uid: string;
  revision_no: number;
  episode_uid: string | null;
  entry_type: string;
  title: string | null;
  body: string;
  occurred_at: string | null;
  created_at: string;
  entry_status: string;
};
type SearchEntry = Omit<Entry, 'title' | 'body'>;
type VerticalGroupMember = {
  episode_uid: string;
  member_index: number;
  role: string;
  strike: string;
  option_type: string;
  expiry: string;
  quantity: string;
  average_open_price: string;
  opening_cash_movement: string;
  commission: string;
  fees: string;
};
type VerticalGroup = {
  presentation_group_uid: string;
  contract_version: string;
  strategy_type: string;
  strategy_label: string;
  primary_symbol: string;
  opened_at: string;
  expiry: string;
  quantity: string;
  currency: string;
  net_opening_cash_movement: string;
  commission: string;
  fees: string;
  episode_status: string;
  source_evidence: 'schwab_filled_vertical_opening_order';
  members: VerticalGroupMember[];
};
type LifecyclePhase = {
  phase: 'opening' | 'closing';
  instruction: 'BUY_TO_OPEN' | 'SELL_TO_OPEN' | 'BUY_TO_CLOSE' | 'SELL_TO_CLOSE';
  occurred_at: string;
  quantity: string;
  average_fill_price: string;
  cash_movement: string;
  commission: string;
  fees: string;
  currency: string;
  execution_count: number;
};
type OptionStockSettlement = {
  settlement_uid: string;
  settlement_kind: 'assignment' | 'exercise';
  settled_at: string;
  option_quantity: string;
  stock_symbol: string;
  stock_quantity: string;
  stock_price: string;
  currency: string;
  stock_episode_uid: string;
  stock_execution_uid: string;
  evidence_quality: 'exact_structured_match';
  source_evidence: 'schwab_unique_option_stock_settlement';
};
type OptionExpiration = {
  expiration_uid: string;
  outcome_kind: 'expiration_indicated';
  expires_on: string;
  posted_at: string;
  option_quantity: string;
  evidence_quality: 'review_required';
  source_evidence: 'schwab_receive_and_deliver_expiration_description_hint';
};
type LifecycleStory = {
  episode_uid: string;
  contract_version: string;
  primary_symbol: string;
  asset_class: string;
  strategy_type: string;
  strategy_label: string;
  option_type: string | null;
  expiry: string | null;
  strike: string | null;
  opening_direction: string | null;
  episode_status: string;
  history_completeness: 'complete' | 'opening_history_missing';
  phases: LifecyclePhase[];
  option_stock_settlements: OptionStockSettlement[];
  option_expirations: OptionExpiration[];
};
type SearchResponse = { metadata: Metadata; episodes: Episode[]; entries: SearchEntry[]; presentation_groups: VerticalGroup[]; lifecycle_stories: LifecycleStory[] };
type QueueItem = {
  episode_uid: string;
  source_broker: string;
  primary_symbol: string;
  asset_class: string;
  instrument_summary: string;
  opened_at: string;
  episode_status: string;
  review_status: string;
  setup_quality: string;
  lifecycle_quality: string;
  lifecycle_reason: string | null;
  reason_codes: string[];
};
type QueueResponse = { metadata: Metadata; queues: Record<string, QueueItem[]>; presentation_groups: VerticalGroup[]; lifecycle_stories: LifecycleStory[] };
type Lifecycle = {
  metadata: Metadata;
  trade: Episode;
  instruments: Array<{
    instrument_index: number;
    instrument_uid: string;
    asset_class: string;
    symbol: string;
    underlying_symbol: string | null;
    option_type: string | null;
    expiry: string | null;
    strike: string | null;
    multiplier: string | null;
    currency: string;
    opening_direction: string | null;
    execution_count: number;
    buy_quantity: string;
    sell_quantity: string;
    captured_quantity_delta: string;
  }>;
  executions: Array<{
    execution_index: number;
    execution_uid: string;
    instrument_uid: string;
    filled_at: string;
    side: string;
    quantity: string;
    fill_price: string;
    multiplier: string;
    commission: string;
    fees: string;
    currency: string;
    schwab_net_cash_movement: string;
    calculated_net_cash_movement: string;
    reconciliation_status: 'matched_schwab_transaction';
  }>;
  entries: Entry[];
  presentation_group: VerticalGroup | null;
  lifecycle_story: LifecycleStory | null;
};
type JournalEntryResponse = { metadata: Metadata; entry: Entry };
type WriteReceipt = {
  metadata: Metadata;
  operation_uid: string;
  resource_uid: string;
  revision_no: number | null;
  replayed: boolean;
};

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) throw new ApiError('The local journal request could not be completed.', response.status);
  const value = await response.json() as T;
  const metadata = (value as { metadata?: Metadata }).metadata;
  if (!metadata || metadata.contract_version !== CONTRACT_VERSION || metadata.mode !== 'local_owner') {
    throw new Error('The local journal returned an incompatible contract.');
  }
  return value;
}

function label(value: string) {
  return value.replaceAll('_', ' ');
}

function shortDate(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function shortDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function decimalText(value: string) {
  const [whole, fraction = ''] = value.split('.');
  const compactFraction = fraction.replace(/0+$/, '');
  return compactFraction ? `${whole}.${compactFraction}` : whole;
}

function roundedDecimalText(value: string, maximumPlaces: number, minimumPlaces: number) {
  const compact = decimalText(value);
  const negative = compact.startsWith('-');
  const unsigned = negative ? compact.slice(1) : compact;
  const [whole = '0', fraction = ''] = unsigned.split('.');
  const factor = BigInt(10) ** BigInt(maximumPlaces);
  const retained = fraction.slice(0, maximumPlaces).padEnd(maximumPlaces, '0');
  let scaled = BigInt(whole || '0') * factor + BigInt(retained || '0');
  if ((fraction[maximumPlaces] ?? '0') >= '5') scaled += BigInt(1);
  const digits = scaled.toString().padStart(maximumPlaces + 1, '0');
  const roundedWhole = maximumPlaces ? digits.slice(0, -maximumPlaces) : digits;
  let roundedFraction = maximumPlaces ? digits.slice(-maximumPlaces) : '';
  while (roundedFraction.length > minimumPlaces && roundedFraction.endsWith('0')) roundedFraction = roundedFraction.slice(0, -1);
  const sign = negative && scaled !== BigInt(0) ? '-' : '';
  return `${sign}${roundedWhole}${roundedFraction ? `.${roundedFraction}` : ''}`;
}

function strikeText(value: string) {
  return roundedDecimalText(value, 2, 2);
}

function optionInstrumentSummary(value: string) {
  const match = /^(\d{4}-\d{2}-\d{2})\s+(-?\d+(?:\.\d+)?)\s+(CALL|PUT)$/i.exec(value.trim());
  return match ? `${match[1]} ${strikeText(match[2])} ${match[3].toUpperCase()}` : value;
}

function money(value: string, currency: string, maximumPlaces = 2, minimumPlaces = 2) {
  const compact = roundedDecimalText(value, maximumPlaces, minimumPlaces);
  const negative = compact.startsWith('-');
  const unsigned = negative ? compact.slice(1) : compact;
  const [whole, fraction] = unsigned.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${currency} ${negative ? '-' : ''}${grouped}${fraction ? `.${fraction}` : ''}`;
}

function absoluteDecimal(value: string) {
  const compact = decimalText(value);
  return compact.startsWith('-') ? compact.slice(1) : compact;
}

function netCashLabel(value: string, currency: string) {
  const compact = decimalText(value);
  if (compact === '0' || compact === '-0') return 'Net opening cash zero';
  return `${compact.startsWith('-') ? 'Net paid' : 'Net received'} ${money(absoluteDecimal(compact), currency)}`;
}

function legCashLabel(value: string, currency: string) {
  const compact = decimalText(value);
  if (compact === '0' || compact === '-0') return 'No opening cash movement';
  return `${compact.startsWith('-') ? 'Paid' : 'Received'} ${money(absoluteDecimal(compact), currency)}`;
}

function signedQuantity(value: string) {
  const compact = decimalText(value);
  return compact.startsWith('-') || compact === '0' ? compact : `+${compact}`;
}

function stockSettlementLabel(value: string, settlementKind: 'assignment' | 'exercise') {
  if (!decimalText(value).startsWith('-')) return 'Stock acquired';
  return settlementKind === 'assignment' ? 'Stock called away' : 'Stock delivered';
}

type LocalOwnerJournalPageProps = {
  activeSection?: 'Trades' | 'Journal';
};

export default function LocalOwnerJournalPage({ activeSection = 'Journal' }: LocalOwnerJournalPageProps) {
  const [query, setQuery] = useState('');
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null);
  const [queues, setQueues] = useState<QueueResponse | null>(null);
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null);
  const [openedEntry, setOpenedEntry] = useState<Entry | null>(null);
  const [selectedEpisode, setSelectedEpisode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lifecycleLoading, setLifecycleLoading] = useState(false);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [writeState, setWriteState] = useState<'idle' | 'review' | 'entry'>('idle');
  const [notice, setNotice] = useState<string | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const [reviewStatus, setReviewStatus] = useState('reviewed');
  const [setupQuality, setSetupQuality] = useState('unknown');
  const [entryReason, setEntryReason] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  const [entryType, setEntryType] = useState('post_trade_reflection');
  const [entryTitle, setEntryTitle] = useState('');
  const [entryBody, setEntryBody] = useState('');
  const pendingOperationIds = useRef(new Map<string, string>());

  async function loadQueues() {
    const response = await apiJson<QueueResponse>(`${API_ROOT}/review-queues`);
    setQueues(response);
  }

  async function searchJournal(searchText = query) {
    const params = new URLSearchParams({ limit: '100' });
    if (searchText.trim()) params.set('q', searchText.trim());
    const response = await apiJson<SearchResponse>(`${API_ROOT}/search?${params.toString()}`);
    setSearchResult(response);
  }

  async function loadInitial() {
    setLoading(true);
    setServiceError(null);
    try {
      await Promise.all([loadQueues(), searchJournal(query)]);
    } catch {
      setServiceError('The local journal API is unavailable. Start the loopback API and local web proxy; no fallback data is shown.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    void Promise.all([
      apiJson<QueueResponse>(`${API_ROOT}/review-queues`),
      apiJson<SearchResponse>(`${API_ROOT}/search?limit=100`),
    ]).then(([queueResponse, searchResponse]) => {
      if (!active) return;
      setQueues(queueResponse);
      setSearchResult(searchResponse);
    }).catch(() => {
      if (active) setServiceError('The local journal API is unavailable. Start the loopback API and local web proxy; no fallback data is shown.');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []); // The operator-selected database is fixed for this page session.

  async function runSearch(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setServiceError(null);
    setLoading(true);
    try {
      await searchJournal();
    } catch {
      setServiceError('Search is unavailable. The page did not substitute cached or synthetic results.');
    } finally {
      setLoading(false);
    }
  }

  async function openLifecycle(episodeUid: string) {
    setSelectedEpisode(episodeUid);
    setLifecycle(null);
    setOpenedEntry(null);
    setLifecycleLoading(true);
    setNotice(null);
    setServiceError(null);
    try {
      const response = await apiJson<Lifecycle>(`${API_ROOT}/trades/${encodeURIComponent(episodeUid)}`);
      setLifecycle(response);
      setReviewStatus(response.trade.review_status === 'unreviewed' ? 'reviewed' : response.trade.review_status);
      setSetupQuality(response.trade.setup_quality);
    } catch {
      setServiceError('The selected trade lifecycle is unavailable. No partial lifecycle is shown.');
    } finally {
      setLifecycleLoading(false);
    }
  }

  async function openJournalEntry(entryUid: string) {
    setSelectedEpisode(null);
    setLifecycle(null);
    setOpenedEntry(null);
    setLifecycleLoading(true);
    setNotice(null);
    setServiceError(null);
    try {
      const response = await apiJson<JournalEntryResponse>(`${API_ROOT}/entries/${encodeURIComponent(entryUid)}`);
      setOpenedEntry(response.entry);
    } catch {
      setServiceError('The selected journal entry is unavailable. No partial entry is shown.');
    } finally {
      setLifecycleLoading(false);
    }
  }

  async function postReplaySafe<T extends object>(path: string, payload: T): Promise<WriteReceipt> {
    const fingerprint = `${path}:${JSON.stringify(payload)}`;
    let operationUid = pendingOperationIds.current.get(fingerprint);
    if (!operationUid) {
      operationUid = crypto.randomUUID();
      pendingOperationIds.current.set(fingerprint, operationUid);
    }
    const response = await apiJson<WriteReceipt>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-OneJournal-Operation-Id': operationUid },
      body: JSON.stringify(payload),
    });
    pendingOperationIds.current.delete(fingerprint);
    return response;
  }

  async function refreshSelected() {
    await Promise.all([loadQueues(), searchJournal(query)]);
    if (selectedEpisode) await openLifecycle(selectedEpisode);
  }

  async function saveReview(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEpisode) return;
    setWriteState('review');
    setNotice(null);
    try {
      const receipt = await postReplaySafe(`${API_ROOT}/reviews`, {
        episode_uid: selectedEpisode,
        review_status: reviewStatus,
        setup_quality: setupQuality,
        entry_reason: entryReason,
        notes: reviewNotes,
      });
      setEntryReason('');
      setReviewNotes('');
      try {
        await refreshSelected();
        setNotice(receipt.replayed ? 'Review confirmed from its existing replay receipt.' : 'Review saved with durable append-only history.');
      } catch {
        setServiceError('The review was saved, but refreshed journal state is unavailable.');
        setNotice('Review saved. Refresh before making another change to this trade.');
      }
    } catch (error) {
      setNotice(error instanceof ApiError && error.status === 409
        ? 'That operation identity conflicts with a different request. Nothing was overwritten.'
        : 'Review not confirmed. Your text remains here; retrying the unchanged request reuses its operation identity.');
    } finally {
      setWriteState('idle');
    }
  }

  async function saveEntry(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEpisode || !entryBody.trim()) return;
    setWriteState('entry');
    setNotice(null);
    try {
      const receipt = await postReplaySafe(`${API_ROOT}/entries`, {
        entry_type: entryType,
        episode_uid: selectedEpisode,
        title: entryTitle.trim() || null,
        body: entryBody,
      });
      setEntryTitle('');
      setEntryBody('');
      try {
        await refreshSelected();
        setNotice(receipt.replayed ? 'Entry confirmed from its existing replay receipt.' : 'Journal entry saved as immutable revision 1.');
      } catch {
        setServiceError('The entry was saved, but refreshed journal state is unavailable.');
        setNotice('Entry saved. Refresh before making another change to this trade.');
      }
    } catch (error) {
      setNotice(error instanceof ApiError && error.status === 409
        ? 'That operation identity conflicts with a different request. Nothing was overwritten.'
        : 'Entry not confirmed. Your text remains here; retrying the unchanged request reuses its operation identity.');
    } finally {
      setWriteState('idle');
    }
  }

  const queueItems = (() => {
    if (!queues) return [];
    const combined = new Map<string, QueueItem & { queueNames: string[] }>();
    for (const [queueName, rows] of Object.entries(queues.queues)) {
      for (const row of rows) {
        const existing = combined.get(row.episode_uid);
        if (existing) {
          existing.queueNames.push(queueName);
          existing.reason_codes = [...new Set([...existing.reason_codes, ...row.reason_codes])];
        } else {
          combined.set(row.episode_uid, { ...row, queueNames: [queueName] });
        }
      }
    }
    const priority = (item: QueueItem & { queueNames: string[] }) =>
      item.queueNames.includes('incomplete') ? 0 : item.queueNames.includes('risk_flagged') ? 1 : 2;
    return [...combined.values()].sort((left, right) =>
      priority(left) - priority(right) || right.opened_at.localeCompare(left.opened_at) ||
      left.episode_uid.localeCompare(right.episode_uid));
  })();
  const episodeResults = searchResult?.episodes ?? [];
  const entryResults = searchResult?.entries ?? [];
  const episodeByUid = new Map(episodeResults.map((episode) => [episode.episode_uid, episode]));
  const groupByEpisodeUid = new Map<string, VerticalGroup>();
  for (const group of searchResult?.presentation_groups ?? []) {
    for (const member of group.members) groupByEpisodeUid.set(member.episode_uid, group);
  }
  const storyByEpisodeUid = new Map(
    (searchResult?.lifecycle_stories ?? []).map((story) => [story.episode_uid, story]),
  );
  const linkedStockEpisodes = new Set(
    (searchResult?.lifecycle_stories ?? [])
      .filter((story) => episodeByUid.has(story.episode_uid))
      .flatMap((story) => story.option_stock_settlements)
      .map((settlement) => settlement.stock_episode_uid),
  );
  const renderedGroups = new Set<string>();
  const browserItems: Array<
    | { kind: 'vertical'; group: VerticalGroup }
    | { kind: 'lifecycle'; episode: Episode; story: LifecycleStory }
    | { kind: 'episode'; episode: Episode }
  > = [];
  for (const episode of episodeResults) {
    if (linkedStockEpisodes.has(episode.episode_uid)) continue;
    const group = groupByEpisodeUid.get(episode.episode_uid);
    const completeGroup = group?.members.every((member) => episodeByUid.has(member.episode_uid));
    if (group && completeGroup) {
      if (!renderedGroups.has(group.presentation_group_uid)) {
        browserItems.push({ kind: 'vertical', group });
        renderedGroups.add(group.presentation_group_uid);
      }
    } else {
      const story = storyByEpisodeUid.get(episode.episode_uid);
      if (story && (story.phases.length > 1 || story.history_completeness === 'opening_history_missing' || story.option_stock_settlements.length > 0 || story.option_expirations.length > 0)) {
        browserItems.push({ kind: 'lifecycle', episode, story });
        continue;
      }
      browserItems.push({ kind: 'episode', episode });
    }
  }

  return (
    <main className="app-shell local-journal-route">
      <aside className="desktop-rail" aria-label="Primary navigation">
        <div className="brand-mark"><span className="brand-glyph">1</span><span className="brand-wordmark">OneJournal</span></div>
        <nav className="nav-stack">{navItems.map(([itemLabel, Icon, href]) => href ? <Link className={`nav-item ${itemLabel === activeSection ? 'is-active' : ''}`} href={href} key={itemLabel} aria-current={itemLabel === activeSection ? 'page' : undefined}><Icon aria-hidden="true" /><span>{itemLabel}</span></Link> : <span className="nav-item is-disabled" key={itemLabel} aria-disabled="true" title="Not connected to private journal data yet"><Icon aria-hidden="true" /><span>{itemLabel}</span></span>)}</nav>
        <div className="rail-footer"><span className="nav-item is-disabled" aria-disabled="true" title="Not connected to private journal data yet"><Settings aria-hidden="true" /><span>Settings</span></span><div className="owner-chip"><span className="owner-avatar">LO</span><span><strong>Private owner</strong><small>Local journal</small></span></div></div>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu aria-hidden="true" /></button>
          <form className="search-box" onSubmit={runSearch}><Search aria-hidden="true" /><label className="sr-only" htmlFor="journal-search">Search trades and journal</label><input id="journal-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search trades, symbols, notes…" type="search" /><button className="local-search-submit" type="submit" aria-label="Run search"><ArrowRight aria-hidden="true" /></button></form>
          <div className="topbar-actions"><span className="local-pill"><LockKeyhole aria-hidden="true" /> Loopback only</span></div>
        </header>
        <output className="mode-banner"><span><ShieldCheck aria-hidden="true" /> Private historical journal</span><p>This is trade history, not a list of current holdings. Lifecycle status comes from Schwab fills, terminal events, and the reconciled position snapshot. No demo fallback.</p></output>
        <div className="content-frame">
          <div className="page-heading"><div><p className="eyebrow">{activeSection} · local owner</p><h1>{activeSection === 'Trades' ? 'Inspect historical trades and their evidence.' : 'Review historical trades and their decisions.'}</h1><p className="heading-copy">Closed trades remain here as history. Search durable journal state, inspect its reconciled lifecycle status, then append a review or reflection without changing financial evidence.</p></div><button className="outline-action" type="button" onClick={() => void loadInitial()} disabled={loading}><RefreshCw aria-hidden="true" /> Refresh</button></div>

          {serviceError ? <section className="panel local-state local-state-error" role="alert"><LockKeyhole aria-hidden="true" /><div><strong>Local journal unavailable</strong><p>{serviceError}</p></div><button className="quiet-button" type="button" onClick={() => void loadInitial()}>Try again</button></section> : null}

          <section className="local-journal-grid">
            <section className="panel local-browser-panel" aria-busy={loading}>
              <div className="panel-header"><div><p className="eyebrow">Historical lifecycle browser</p><h2>{query.trim() ? 'Search results' : 'Recent journal history'}</h2></div>{loading ? <LoaderCircle className="local-spinner" aria-label="Loading" /> : <span className="health-score">{browserItems.length} items</span>}</div>
              {!loading && searchResult && episodeResults.length === 0 && entryResults.length === 0 ? <div className="local-empty"><Search aria-hidden="true" /><strong>No matching journal state</strong><p>Try a symbol, note phrase, or clear the search. No substitute results are shown.</p></div> : null}
              <div className="local-result-list">{browserItems.map((item) => {
                if (item.kind === 'episode') {
                  const episode = item.episode;
                  return <button className={`local-result-row ${selectedEpisode === episode.episode_uid ? 'is-selected' : ''}`} type="button" key={episode.episode_uid} onClick={() => void openLifecycle(episode.episode_uid)}><span className="trade-symbol">{episode.primary_symbol.slice(0, 4)}</span><span><small>{shortDateTime(episode.opened_at)} · {label(episode.asset_class)} lifecycle</small><strong>{episode.asset_class === 'option' ? `${episode.primary_symbol} option · ${optionInstrumentSummary(episode.instrument_summary)}` : `${episode.primary_symbol} stock`}</strong><span>Historical status: {label(episode.episode_status)}{episode.position_reconciliation_status === 'matched_current' ? ' · matches current Schwab position' : ''} · {episode.execution_count} Schwab {episode.execution_count === 1 ? 'execution' : 'executions'}</span></span><ChevronRight aria-hidden="true" /></button>;
                }
                if (item.kind === 'lifecycle') {
                  const { episode, story } = item;
                  const disclosureKey = `lifecycle:${episode.episode_uid}`;
                  const collapsed = collapsedGroups.has(disclosureKey);
                  const settlement = story.option_stock_settlements[0];
                  const expiration = story.option_expirations[0];
                  const missingOpening = story.history_completeness === 'opening_history_missing';
                  const outcome = settlement ? label(settlement.settlement_kind) : expiration ? 'expired' : missingOpening ? 'closing execution' : label(episode.episode_status);
                  const outcomeStatus = missingOpening ? ' · incomplete history' : (settlement || expiration) && episode.lifecycle_quality !== 'resolved' ? ` · ${label(episode.lifecycle_quality)}` : '';
                  return <article className="local-vertical-group local-lifecycle-story" key={episode.episode_uid}>
                    <button className="local-vertical-header" type="button" aria-expanded={!collapsed} onClick={() => setCollapsedGroups((current) => { const next = new Set(current); if (next.has(disclosureKey)) next.delete(disclosureKey); else next.add(disclosureKey); return next; })}>
                      <span className="local-disclosure">{collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}</span>
                      <span><small>{shortDateTime(episode.opened_at)}{story.expiry ? ` · expires ${shortDate(story.expiry)}` : ''}{story.strike ? ` · ${strikeText(story.strike)} ${label(story.option_type ?? '')}` : ''}</small><strong>{story.primary_symbol} {story.strategy_label} · {outcome}{outcomeStatus}</strong><span>{story.phases.length} lifecycle {story.phases.length === 1 ? 'phase' : 'phases'} · {episode.execution_count} Schwab {episode.execution_count === 1 ? 'execution' : 'executions'}</span></span>
                    </button>
                    {!collapsed ? <div className="local-vertical-members">{story.phases.map((phase, index) => <div className="local-vertical-member-wrap" key={`${episode.episode_uid}:${phase.phase}`}>
                      {index > 0 ? <span className="local-vertical-connector" aria-hidden="true">↕</span> : null}
                      <button className={`local-vertical-member ${selectedEpisode === episode.episode_uid ? 'is-selected' : ''}`} type="button" onClick={() => void openLifecycle(episode.episode_uid)}>
                        <span className="local-vertical-branch">└─</span>
                        <span><strong>{phase.phase === 'opening' ? 'Opened' : 'Closed'} · {label(phase.instruction)}</strong><small>{shortDateTime(phase.occurred_at)} · qty {decimalText(phase.quantity)} · avg {money(phase.average_fill_price, phase.currency, 4, 2)} · {legCashLabel(phase.cash_movement, phase.currency)} · fees {money(phase.fees, phase.currency)} · {phase.execution_count} {phase.execution_count === 1 ? 'execution' : 'executions'}</small></span>
                        <ChevronRight aria-hidden="true" />
                      </button>
                    </div>)}
                    {story.option_stock_settlements.map((linked, index) => <div className="local-vertical-member-wrap" key={linked.settlement_uid}>
                      {(story.phases.length > 0 || index > 0) ? <span className="local-vertical-connector" aria-hidden="true">↕</span> : null}
                      <button className={`local-vertical-member local-settlement-member ${selectedEpisode === linked.stock_episode_uid ? 'is-selected' : ''}`} type="button" onClick={() => void openLifecycle(linked.stock_episode_uid)}>
                        <span className="local-vertical-branch">└─</span>
                        <span><strong>{label(linked.settlement_kind)} · {shortDateTime(linked.settled_at)}</strong><small>{decimalText(linked.option_quantity)} {decimalText(linked.option_quantity) === '1' ? 'contract' : 'contracts'} · {stockSettlementLabel(linked.stock_quantity, linked.settlement_kind)} {signedQuantity(linked.stock_quantity)} {linked.stock_symbol} @ {money(linked.stock_price, linked.currency, 4, 2)} · exact Schwab link</small></span>
                        <ChevronRight aria-hidden="true" />
                      </button>
                    </div>)}
                    {story.option_expirations.map((expired, index) => <div className="local-vertical-member-wrap" key={expired.expiration_uid}>
                      {(story.phases.length > 0 || story.option_stock_settlements.length > 0 || index > 0) ? <span className="local-vertical-connector" aria-hidden="true">↕</span> : null}
                      <button className={`local-vertical-member local-expiration-member ${selectedEpisode === episode.episode_uid ? 'is-selected' : ''}`} type="button" onClick={() => void openLifecycle(episode.episode_uid)}>
                        <span className="local-vertical-branch">└─</span>
                        <span><strong>Schwab expiration indicated · review required</strong><small>Expired {shortDate(expired.expires_on)} · posted {shortDateTime(expired.posted_at)} · {decimalText(expired.option_quantity)} {decimalText(expired.option_quantity) === '1' ? 'contract' : 'contracts'} · no matched stock settlement</small></span>
                        <ChevronRight aria-hidden="true" />
                      </button>
                    </div>)}</div> : null}
                  </article>;
                }
                const group = item.group;
                const collapsed = collapsedGroups.has(group.presentation_group_uid);
                return <article className="local-vertical-group" key={group.presentation_group_uid}>
                  <button className="local-vertical-header" type="button" aria-expanded={!collapsed} onClick={() => setCollapsedGroups((current) => { const next = new Set(current); if (next.has(group.presentation_group_uid)) next.delete(group.presentation_group_uid); else next.add(group.presentation_group_uid); return next; })}>
                    <span className="local-disclosure">{collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}</span>
                    <span><small>{shortDateTime(group.opened_at)} · expires {shortDate(group.expiry)} · qty {decimalText(group.quantity)}</small><strong>{group.primary_symbol} {group.strategy_label} · {label(group.episode_status)}</strong><span>{netCashLabel(group.net_opening_cash_movement, group.currency)} · fees {money(group.fees, group.currency)}</span></span>
                  </button>
                  {!collapsed ? <div className="local-vertical-members">{group.members.map((member, index) => {
                    const episode = episodeByUid.get(member.episode_uid);
                    return <div className="local-vertical-member-wrap" key={member.episode_uid}>
                      {index > 0 ? <span className="local-vertical-connector" aria-hidden="true">↕</span> : null}
                      <button className={`local-vertical-member ${selectedEpisode === member.episode_uid ? 'is-selected' : ''}`} type="button" onClick={() => void openLifecycle(member.episode_uid)}>
                        <span className="local-vertical-branch">└─</span>
                        <span><strong>{strikeText(member.strike)} {label(member.option_type)} · {label(member.role)}</strong><small>Qty {decimalText(member.quantity)} · avg {money(member.average_open_price, group.currency, 4, 2)} · {legCashLabel(member.opening_cash_movement, group.currency)} · {episode?.execution_count ?? 0} {(episode?.execution_count ?? 0) === 1 ? 'execution' : 'executions'}</small></span>
                        <ChevronRight aria-hidden="true" />
                      </button>
                    </div>;
                  })}</div> : null}
                </article>;
              })}</div>
              {entryResults.length > 0 ? <div className="local-entry-results"><p className="eyebrow">Matching journal entries · metadata only</p>{entryResults.map((entry) => <button className={`local-result-row ${openedEntry?.entry_uid === entry.entry_uid ? 'is-selected' : ''}`} type="button" key={entry.entry_uid} onClick={() => entry.episode_uid ? void openLifecycle(entry.episode_uid) : void openJournalEntry(entry.entry_uid)}><span className="trade-symbol violet">JN</span><span><small>{shortDate(entry.occurred_at ?? entry.created_at)} · revision {entry.revision_no}</small><strong>{label(entry.entry_type)}</strong><span>{entry.episode_uid ? 'Linked trade · open lifecycle' : 'Standalone entry · open privately'}</span></span><ChevronRight aria-hidden="true" /></button>)}</div> : null}
            </section>

            <section className="panel local-queue-panel">
              <div className="panel-header"><div><p className="eyebrow">Review queues</p><h2>Needs attention</h2></div><span className="health-score">{queueItems.length} items</span></div>
              {!loading && queues && queueItems.length === 0 ? <div className="local-empty"><CheckCircle2 aria-hidden="true" /><strong>No queued reviews</strong><p>The current journal has no reason-coded review items.</p></div> : null}
              <div className="local-queue-list">{queueItems.slice(0, 12).map((item) => <button className="local-queue-row" type="button" key={item.episode_uid} onClick={() => void openLifecycle(item.episode_uid)}><span><small>{item.queueNames.map(label).join(' · ')}</small><strong>{item.asset_class === 'option' ? `${item.primary_symbol} option · ${optionInstrumentSummary(item.instrument_summary)}` : `${item.primary_symbol} stock`} · {label(item.episode_status)}</strong><span>{item.reason_codes.map(label).join(' · ')}</span></span><span className="prompt-status">{label(item.review_status)}</span></button>)}</div>
            </section>
          </section>

          <section className="panel local-lifecycle-panel" aria-busy={lifecycleLoading}>
            <div className="panel-header"><div><p className="eyebrow">Private historical inspection</p><h2>{lifecycle ? `${lifecycle.trade.primary_symbol} · ${label(lifecycle.trade.strategy_label)}` : openedEntry ? label(openedEntry.entry_type) : 'Select a trade or entry'}</h2></div>{lifecycleLoading ? <LoaderCircle className="local-spinner" aria-label="Loading private journal state" /> : lifecycle ? <span className="prompt-status">Historical status: {label(lifecycle.trade.episode_status)}</span> : openedEntry ? <span className="prompt-status">Revision {openedEntry.revision_no}</span> : null}</div>
            {!lifecycle && !openedEntry && !lifecycleLoading ? <div className="local-empty local-empty-inline"><Activity aria-hidden="true" /><strong>Nothing open</strong><p>Choose a trade, queue item, or journal-entry match. Private prose is not loaded until you intentionally open it.</p></div> : null}
            {lifecycle ? <>
              {lifecycle.trade.lifecycle_quality !== 'resolved' ? <output className="local-quality-warning"><ShieldCheck aria-hidden="true" /><p><strong>Financial lifecycle unavailable</strong><span>{label(lifecycle.trade.lifecycle_reason ?? 'lifecycle review required')}. The captured fills remain visible, but aggregates are withheld until the missing history is reconciled.</span></p></output> : null}
              <div className="local-trade-meta"><span><small>Opened</small><strong>{shortDateTime(lifecycle.trade.opened_at)}</strong></span><span><small>Instrument</small><strong>{label(lifecycle.trade.asset_class)} · {lifecycle.trade.asset_class === 'option' ? optionInstrumentSummary(lifecycle.trade.instrument_summary) : lifecycle.trade.instrument_summary}</strong></span><span><small>Position check</small><strong>{label(lifecycle.trade.position_reconciliation_status)}</strong></span><span><small>Source</small><strong>{lifecycle.trade.execution_count} Schwab {lifecycle.trade.execution_count === 1 ? 'execution' : 'executions'}</strong></span></div>
              <div className="local-instrument-list"><p className="eyebrow">Instrument summary · executions are grouped, not removed</p>{lifecycle.instruments.map((instrument) => <article key={instrument.instrument_uid}><header><span>{String(instrument.instrument_index).padStart(2, '0')}</span><div><small>{label(instrument.asset_class)} · {instrument.opening_direction ? `${label(instrument.opening_direction)} opening` : 'opening history unavailable'}</small><strong>{instrument.symbol}</strong><p>{instrument.option_type ? `${label(instrument.option_type)} · ${instrument.expiry ?? 'no expiry'} · strike ${instrument.strike ? strikeText(instrument.strike) : '—'} · multiplier ${instrument.multiplier ?? '—'}` : 'Equity instrument'}</p></div></header><footer><span>{instrument.execution_count} {instrument.execution_count === 1 ? 'execution' : 'executions'}</span><span>Bought {decimalText(instrument.buy_quantity)}</span><span>Sold {decimalText(instrument.sell_quantity)}</span><span>Captured delta {decimalText(instrument.captured_quantity_delta)}</span></footer></article>)}</div>
              <div className="local-execution-list"><p className="eyebrow">Exact Schwab executions · not strategy legs</p>{lifecycle.executions.map((execution) => <article key={execution.execution_uid}><span>{String(execution.execution_index).padStart(2, '0')}</span><div><small>{shortDateTime(execution.filled_at)} · matched to Schwab transaction</small><strong>{execution.side} {decimalText(execution.quantity)} @ {money(execution.fill_price, execution.currency, 4, 2)}</strong><p>Schwab net cash movement {money(execution.schwab_net_cash_movement, execution.currency)} · commission {money(execution.commission, execution.currency)} · fees {money(execution.fees, execution.currency)}</p></div></article>)}</div>
              {lifecycle.lifecycle_story && lifecycle.lifecycle_story.option_stock_settlements.length > 0 ? <div className="local-execution-list local-settlement-list"><p className="eyebrow">Linked Schwab option settlement</p>{lifecycle.lifecycle_story.option_stock_settlements.map((settlement) => <button className="local-settlement-detail" type="button" key={settlement.settlement_uid} onClick={() => void openLifecycle(settlement.stock_episode_uid)}><span>↕</span><div><small>{shortDateTime(settlement.settled_at)} · exact structured match</small><strong>{label(settlement.settlement_kind)} · {stockSettlementLabel(settlement.stock_quantity, settlement.settlement_kind).toLowerCase()} {signedQuantity(settlement.stock_quantity)} {settlement.stock_symbol} @ {money(settlement.stock_price, settlement.currency, 4, 2)}</strong><p>Open the resulting stock lifecycle. This link does not merge or alter either Schwab-backed trade.</p></div><ChevronRight aria-hidden="true" /></button>)}</div> : null}
              {lifecycle.lifecycle_story && lifecycle.lifecycle_story.option_expirations.length > 0 ? <div className="local-execution-list local-settlement-list"><p className="eyebrow">Schwab terminal lifecycle evidence</p>{lifecycle.lifecycle_story.option_expirations.map((expiration) => <article className="local-expiration-detail" key={expiration.expiration_uid}><span>↕</span><div><small>Expired {shortDate(expiration.expires_on)} · Schwab posted {shortDateTime(expiration.posted_at)}</small><strong>Expiration indicated · {decimalText(expiration.option_quantity)} {decimalText(expiration.option_quantity) === '1' ? 'contract' : 'contracts'}</strong><p>No assignment or resulting stock settlement was matched. Financial authority remains review required because Schwab supplied a description hint rather than a structured event type.</p></div></article>)}</div> : null}
              <div className="local-entry-list"><p className="eyebrow">Current journal entries</p>{lifecycle.entries.length === 0 ? <p className="local-muted">No entries are attached to this trade.</p> : lifecycle.entries.map((entry) => <article key={entry.entry_uid}><header><span>{label(entry.entry_type)}</span><small>Revision {entry.revision_no}</small></header><strong>{entry.title || 'Untitled entry'}</strong><p>{entry.body}</p></article>)}</div>
            </> : null}
            {openedEntry ? <div className="local-entry-list local-standalone-entry"><p className="eyebrow">Intentionally opened journal prose</p><article><header><span>{label(openedEntry.entry_type)}</span><small>Revision {openedEntry.revision_no}</small></header><strong>{openedEntry.title || 'Untitled entry'}</strong><p>{openedEntry.body}</p></article></div> : null}
          </section>

          {lifecycle ? <section className="local-author-grid">
            <form className="panel local-author-panel" onSubmit={saveReview}>
              <div className="panel-header"><div><p className="eyebrow">Append review</p><h2>Record the assessment</h2></div><ShieldCheck aria-hidden="true" /></div>
              <div className="local-field-grid"><label><span>Status</span><select value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value)}>{reviewStatuses.map((value) => <option value={value} key={value}>{label(value)}</option>)}</select></label><label><span>Setup quality</span><select value={setupQuality} onChange={(event) => setSetupQuality(event.target.value)}>{setupQualities.map((value) => <option value={value} key={value}>{label(value)}</option>)}</select></label></div>
              <label className="local-field"><span>Entry reason</span><input value={entryReason} onChange={(event) => setEntryReason(event.target.value)} maxLength={4000} placeholder="Why the trade was entered" /></label>
              <label className="local-field"><span>Private review notes</span><textarea value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} maxLength={20000} rows={5} placeholder="What should be remembered?" /></label>
              <div className="local-submit-row"><button className="primary-preview" type="submit" disabled={writeState !== 'idle'}>{writeState === 'review' ? 'Saving…' : 'Save append-only review'}</button><small>Replay-safe operation identity</small></div>
            </form>
            <form className="panel local-author-panel" onSubmit={saveEntry}>
              <div className="panel-header"><div><p className="eyebrow">Append journal entry</p><h2>Add a reflection</h2></div><NotebookPen aria-hidden="true" /></div>
              <label className="local-field"><span>Entry type</span><select value={entryType} onChange={(event) => setEntryType(event.target.value)}>{entryTypes.map((value) => <option value={value} key={value}>{label(value)}</option>)}</select></label>
              <label className="local-field"><span>Title <small>optional</small></span><input value={entryTitle} onChange={(event) => setEntryTitle(event.target.value)} maxLength={512} /></label>
              <label className="local-field"><span>Private entry</span><textarea value={entryBody} onChange={(event) => setEntryBody(event.target.value)} maxLength={20000} rows={5} required placeholder="Capture the decision, mistake, or lesson." /></label>
              <div className="local-submit-row"><button className="primary-preview" type="submit" disabled={writeState !== 'idle' || !entryBody.trim()}>{writeState === 'entry' ? 'Saving…' : 'Save immutable revision 1'}</button><small>Financial evidence is unchanged</small></div>
            </form>
          </section> : null}

          {notice ? <output className="panel local-write-notice" aria-live="polite"><ShieldCheck aria-hidden="true" /><p>{notice}</p></output> : null}
          <section className="panel journal-boundary"><LockKeyhole aria-hidden="true" /><p><strong>Private narrative is never audit content.</strong> Audit records contain stable identities, outcomes, timestamps, and request fingerprints—not notes, account identifiers, raw evidence, or credentials.</p></section>
        </div>
      </section>
      <nav className="mobile-nav" aria-label="Mobile navigation">{navItems.slice(0, 4).map(([itemLabel, Icon, href]) => href ? <Link className={itemLabel === activeSection ? 'is-active' : ''} href={href} key={itemLabel}><Icon aria-hidden="true" /><span>{itemLabel}</span></Link> : <span className="is-disabled" key={itemLabel} aria-disabled="true"><Icon aria-hidden="true" /><span>{itemLabel}</span></span>)}</nav>
    </main>
  );
}
