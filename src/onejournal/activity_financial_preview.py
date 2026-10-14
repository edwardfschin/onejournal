"""Isolated, read-only financial preview of confirmed incremental activity.

Reuses released lifecycle, execution reconciliation, FIFO and reporting types.
Does not create an assembly, activate history, accept a report or persist P&L.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from hashlib import sha256
import csv
from io import StringIO
import json

import duckdb

from onejournal.instruments import InstrumentIdentity
from onejournal.journal.episodes import TradeEpisodePreview, build_episode_previews_from_fills
from onejournal.journal.lifecycle import LifecycleContractError, build_lifecycle_fill_events
from onejournal.journal.pnl_repository import load_approved_lifecycle_events
from onejournal.journal.schwab_evidence_assembly import canonical_schwab_evidence_json
from onejournal.journal.schwab_evidence_materialization import (
    _scope_key, _episode, build_schwab_journal_materialization_plan,
)
from onejournal.journal.schwab_execution_projection import _build_execution_projection_plan
from onejournal.journal.schwab_journal_lifecycle_reconciliation import (
    build_schwab_journal_lifecycle_reconciliation, _event_instrument_key,
)
from onejournal.journal.phase1_reporting_calculation import _ordinary_realized_item, NEW_YORK
from onejournal.journal.phase1_reporting_repository import (
    RealizedHistoryItem, ReportingAccount, ReportingOmission, realized_history,
)
from onejournal.local_web import private_file
from onejournal.pnl import (
    build_instrument_key, calculate_fifo_pnl_with_lifecycle_events,
    build_fill_input_fingerprint, build_lifecycle_input_fingerprint,
)
from onejournal.pnl.bounded_reconciliation import normalized_fill_from_lifecycle_transaction_row
from onejournal.refresh_activity import _confirmed_import, _index, _FAMILIES

CONTRACT = 'onejournal.activity-financial-preview.v1'


def _digest(value):
    return sha256(canonical_schwab_evidence_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class ActivityFinancialPreview:
    checkpoint_uid: str
    checkpoint_utc: datetime
    position_snapshot_utc: datetime
    coverage_start_date: date
    coverage_end_date: date
    calculation_version: str
    accounts: tuple
    items: tuple
    omissions: tuple
    trades: tuple
    executions: tuple
    instruments: tuple
    result_fingerprint: str


def _combined_records(baseline):
    families = {f.family: f for f in baseline.assembly.families}
    return {name: tuple(json.loads(v) for v in _index(
        (*families[name].records, *baseline.appended_records.get(name, ())), identity, observation).values())
        for name, (identity, observation, _) in _FAMILIES.items() if name!='orders'}


def _build_preview(baseline, *, approved_events, account_alias, reviews=None):
    records = _combined_records(baseline)
    assembly = baseline.assembly
    source = baseline.checkpoint_uid or assembly.result_fingerprint
    fills = tuple(normalized_fill_from_lifecycle_transaction_row(row,
        fetched_at=assembly.assembled_at_utc if row in next(f.records for f in assembly.families if f.family=='fills') else baseline.cutoff,
        raw_path=f'activity-preview:{source}:fills:{_digest(row)}')
        for row in records['fills'] if datetime.fromisoformat(row['filled_at'].replace('Z','+00:00')) <= baseline.cutoff)
    if any((f.source_broker,f.source_account_id) != ('schwab',assembly.source_account_id) for f in fills):
        raise ValueError('Activity financial scope differs.')
    original_plan = build_schwab_journal_materialization_plan(assembly)
    original_states = build_schwab_journal_lifecycle_reconciliation(assembly)
    original_state_by_id = {s.episode_uid:s for s in original_states.states}
    original_by_id = {e.preview.episode_uid:e for e in original_plan.episodes}
    held_scopes = {original_by_id[s.episode_uid].scope_uid:s.reason_code or 'lifecycle_review_required'
                   for s in original_states.states if s.lifecycle_quality != 'resolved'}
    grouped = defaultdict(list)
    for fill in fills:
        grouped[_scope_key(fill)].append(fill)
    episodes = []
    for key, rows in sorted(grouped.items()):
        scope_uid = 'journal-scope:' + _digest(key)
        try:
            build_lifecycle_fill_events(rows)
            previews = build_episode_previews_from_fills(rows)
            reason = held_scopes.get(scope_uid)
        except LifecycleContractError as exc:
            if not str(exc).startswith('Unmatched close quantity'):
                raise
            first = rows[0]
            previews = [TradeEpisodePreview('review-required',first.source_account_id,
                first.underlying_symbol or first.symbol,first.asset_class,first.filled_at,'review_required',
                len(rows),Decimal('0'),Decimal('0'),Decimal('0'),Decimal('0'),first.source_broker,
                'unknown','Lifecycle Review Required',len(rows),'Opening history is missing','unavailable',
                [{'fill_uid':f.fill_uid} for f in rows])]
            reason = 'opening_history_missing'
        episodes.extend(_episode(p,scope_uid=scope_uid,quality='review_required' if reason else 'resolved',reason=reason)
                        for p in previews)
    by_fill = {f.fill_uid:f for f in fills}
    episode_by_fill = {uid:e for e in episodes for uid in e.fill_uids}
    if len(episode_by_fill) != len(fills):
        raise ValueError('Activity episode coverage differs.')
    # Reuse the released execution reconciler, preserving exact decimal input.
    projection_rows = []
    for e in episodes:
        for index, uid in enumerate(e.fill_uids,1):
            f = by_fill[uid]
            projection_rows.append(dict(asdict(f),episode_uid=e.preview.episode_uid,
                stored_leg_index=index,lifecycle_quality=e.lifecycle_quality,scope_uid=e.scope_uid,
                filled_at_utc=f.filled_at))
    projection = _build_execution_projection_plan(materialization_uid='activity-preview:'+source,
        expected_fill_count=len(fills),expected_episode_count=len(episodes),
        transaction_records=records['transactions'],fills=projection_rows,
        episode_rows=[dict(episode_uid=e.preview.episode_uid,scope_uid=e.scope_uid,
                          lifecycle_quality=e.lifecycle_quality,opened_at=e.preview.opened_at) for e in episodes])

    event_records = {r['event_uid']:r for r in records['lifecycle_events']
                     if datetime.fromisoformat(r['event_at'].replace('Z','+00:00')) <= baseline.cutoff}
    events = tuple(e for e in approved_events if e.event_uid in event_records
                   and e.effective_at <= baseline.cutoff
                   and (e.source_broker,e.source_account_id)==('schwab',assembly.source_account_id))
    source_legs = {r['event_leg_uid']:r['event_uid'] for r in records['lifecycle_event_legs']}
    if any(any(source_legs.get(uid)!=e.event_uid for uid in e.source_event_leg_uids) for e in events):
        raise ValueError('Approved lifecycle links differ from retained evidence.')
    approved_ids = {e.event_uid for e in events}
    blocked_instruments = defaultdict(list)
    unresolved_events = set(event_records) - approved_ids
    unscoped_events = []
    for uid in unresolved_events:
        legs = [r for r in records['lifecycle_event_legs'] if r['event_uid']==uid and r.get('leg_kind')=='security']
        at = datetime.fromisoformat(event_records[uid]['event_at'].replace('Z','+00:00'))
        if not legs:
            unscoped_events.append((uid,at))
        for leg in legs:
            currency = str(leg.get('currency','')).strip()
            if not currency:
                unscoped_events.append((uid,at))
                continue
            blocked_instruments[_event_instrument_key(leg,currency=currency)].append((uid,at))
    calculation = calculate_fifo_pnl_with_lifecycle_events(fills, events, allow_unmatched_close=True)
    reasons = {}
    covered_events = set()
    statuses = {e.preview.episode_uid:(original_state_by_id[e.preview.episode_uid].reconciled_status
                if e.preview.episode_uid in original_state_by_id else e.preview.status) for e in episodes}
    # Reuse approved FIFO allocations to recognize a fully settled option
    # episode; source descriptions never close an episode by themselves.
    for e in episodes:
        allocations = [a for a in calculation.lifecycle_allocations if a.predecessor_open_fill_uid in e.fill_uids]
        if not allocations or e.lifecycle_quality!='resolved':
            continue
        residuals = defaultdict(lambda:Decimal('0'))
        for uid in e.fill_uids:
            f = by_fill[uid]
            residuals[build_instrument_key(f)] += f.quantity if f.side.upper().startswith('BUY') else -f.quantity
        for a in allocations:
            residuals[a.option_scope_key[2]] -= a.contracts if a.predecessor_direction=='LONG' else -a.contracts
        if all(q==0 for q in residuals.values()):
            statuses[e.preview.episode_uid] = 'closed'
    for e in episodes:
        if e.reason_code:
            reasons[e.preview.episode_uid] = e.reason_code
        last = max(by_fill[uid].filled_at for uid in e.fill_uids)
        affected = [*unscoped_events,*(event for uid in e.fill_uids
            for event in blocked_instruments[InstrumentIdentity.from_fill(by_fill[uid]).key])]
        matches = {uid for uid,at in affected if e.preview.opened_at<=at
                   and (statuses[e.preview.episode_uid]!='closed' or at<=last)}
        if matches:
            covered_events.update(matches)
            reasons[e.preview.episode_uid] = 'lifecycle_review_required'
    for uid in calculation.unmatched_close_fill_uids:
        reasons[episode_by_fill[uid].preview.episode_uid] = 'opening_history_missing'
    # A stale complete position observation cannot reconcile today's open trade.
    stale = baseline.cutoff > assembly.snapshot_cutoff_utc
    for e in episodes:
        if stale and statuses[e.preview.episode_uid] == 'open':
            reasons.setdefault(e.preview.episode_uid,'fresh_position_snapshot_required')
    items = []
    for allocation in calculation.closed_allocations:
        if any(episode_by_fill[uid].preview.episode_uid in reasons
               for uid in (allocation.open_fill_uid,allocation.close_fill_uid)):
            continue
        item = _ordinary_realized_item(allocation,by_fill[allocation.close_fill_uid])
        items.append(RealizedHistoryItem(**{k:getattr(item,k) for k in RealizedHistoryItem.__dataclass_fields__ if k!='reason_codes'}))
    # Approved lifecycle allocations are preserved as explicitly scoped results.
    # Their raw event never grants authority; missing opening evidence withholds.
    for a in calculation.lifecycle_allocations:
        e = episode_by_fill[a.predecessor_open_fill_uid]
        if e.lifecycle_quality != 'resolved' or e.preview.episode_uid in reasons:
            continue
        f = by_fill[a.predecessor_open_fill_uid]
        items.append(RealizedHistoryItem('realized-item:'+_digest(dict(event_uid=a.event_uid,
            allocation_index=a.allocation_index,predecessor_open_fill_uid=a.predecessor_open_fill_uid,
            realized_pnl=a.realized_pnl)),f.source_broker,f.source_account_id,a.option_scope_key[2],
            f.underlying_symbol or f.symbol,'option',a.effective_at.astimezone(NEW_YORK).date(),
            a.effective_at,a.option_scope_key[3],a.realized_pnl))
    omissions = tuple(ReportingOmission('activity-omission:'+_digest((source,e.preview.episode_uid,reasons[e.preview.episode_uid])),
        'schwab',assembly.source_account_id,max(by_fill[uid].filled_at.astimezone(NEW_YORK).date() for uid in e.fill_uids),
        e.preview.primary_symbol,reasons[e.preview.episode_uid],
        'reconciliation_pending' if reasons[e.preview.episode_uid]=='fresh_position_snapshot_required' else 'incomplete')
        for e in episodes if e.preview.episode_uid in reasons)
    omissions += tuple(ReportingOmission('activity-event-omission:'+_digest((source,uid)),
        'schwab',assembly.source_account_id,
        datetime.fromisoformat(event_records[uid]['event_at'].replace('Z','+00:00')).astimezone(NEW_YORK).date(),
        next((str(r.get('underlying_symbol') or r.get('symbol')) for r in records['lifecycle_event_legs']
              if r['event_uid']==uid and r.get('leg_kind')=='security' and (r.get('underlying_symbol') or r.get('symbol'))),None),
        'lifecycle_review_required','incomplete') for uid in sorted(unresolved_events-covered_events))
    trades = []
    projected = {p.episode_uid:p for p in projection.episodes}
    for e in episodes:
        p = projected[e.preview.episode_uid]
        review = (reviews or {}).get(e.preview.episode_uid,('unreviewed','unknown'))
        reason = reasons.get(e.preview.episode_uid)
        trades.append(dict(episode_uid=e.preview.episode_uid,source_broker='schwab',primary_symbol=e.preview.primary_symbol,
            asset_class=e.preview.asset_class,strategy_type=p.strategy_type,strategy_label=p.strategy_label,
            opened_at=e.preview.opened_at,episode_status=statuses[e.preview.episode_uid],review_status=review[0],setup_quality=review[1],
            lifecycle_quality='review_required' if reason else 'resolved',lifecycle_reason=reason,
            position_reconciliation_status='pending' if stale and statuses[e.preview.episode_uid]=='open' else 'not_applicable',
            instrument_count=p.instrument_count,execution_count=p.execution_count,lifecycle_sequence=p.lifecycle_sequence,
            lifecycle_count=p.lifecycle_count,instrument_summary=p.instrument_summary))
    start = datetime.combine(assembly.lifecycle_window_start,time(),UTC).astimezone(NEW_YORK).date()
    end = baseline.cutoff.astimezone(NEW_YORK).date()
    version = calculation.calculation_version+'+activity-preview-v1'
    payload = dict(contract_version=CONTRACT,source=source,checkpoint_utc=baseline.cutoff,
        fill_fingerprint=build_fill_input_fingerprint(fills),lifecycle_fingerprint=build_lifecycle_input_fingerprint(events),
        projection=projection.result_fingerprint,trades=trades,items=[asdict(i) for i in items],
        omissions=[asdict(o) for o in omissions],account_alias=account_alias,calculation_version=version)
    return ActivityFinancialPreview(source,baseline.cutoff,assembly.snapshot_cutoff_utc,start,end,version,
        (ReportingAccount('schwab',assembly.source_account_id,account_alias),),tuple(sorted(items,key=lambda i:i.item_uid)),
        omissions,tuple(trades),projection.executions,projection.instruments,_digest(payload))


def load_activity_financial_preview(db, binding, *, expected_checkpoint_uid, account_alias):
    if not isinstance(account_alias,str) or not account_alias.strip() or len(account_alias)>64:
        raise ValueError('An explicit private account alias is required.')
    checked = private_file(db,'activity journal',private_parent=True)
    with duckdb.connect(str(checked),read_only=True) as con:
        con.execute('BEGIN TRANSACTION')
        baseline = _confirmed_import(con,binding)
        if (baseline.checkpoint_uid or baseline.assembly.result_fingerprint) != expected_checkpoint_uid:
            raise ValueError('Financial preview checkpoint differs.')
        aliases = {r[0] for r in con.execute('''SELECT DISTINCT account_alias
            FROM phase1_reporting_release_accounts WHERE source_broker='schwab' AND source_account_id=?''',
            [binding.source_account_id]).fetchall()}
        if aliases and account_alias not in aliases:
            raise ValueError('Financial preview alias differs from released account identity.')
        events = load_approved_lifecycle_events(con,asof=baseline.cutoff.date())
        reviews = {uid:(status,quality) for uid,status,quality in con.execute(
            'SELECT episode_uid,review_status,setup_quality FROM manual_reviews').fetchall()}
        return _build_preview(baseline,approved_events=events,account_alias=account_alias,reviews=reviews)


def report_preview(preview, *, from_date, to_date, account_alias=None, symbol=None):
    quality, items, reasons = realized_history(preview,from_date=from_date,to_date=to_date,
        account_alias=account_alias,symbol=symbol)
    alias = preview.accounts[0].account_alias
    rows = [dict(item_uid=i.item_uid,account_alias=alias,symbol=i.symbol,asset_class=i.asset_class,
        close_market_date=i.close_market_date.isoformat(),currency=i.currency,realized_pnl=format(i.realized_pnl,'f'),
        item_status='valid',reason_codes=list(i.reason_codes),calculation_version=preview.calculation_version) for i in items]
    pending = sum(o.item_status=='reconciliation_pending' for o in preview.omissions
        if from_date<=o.close_market_date<=to_date and (symbol is None or o.symbol==symbol)) if quality!='unavailable' else 0
    return dict(metadata=dict(contract_version=CONTRACT,quality=quality,reason_counts=reasons,
        result_fingerprint=preview.result_fingerprint,checkpoint_utc=preview.checkpoint_utc.isoformat(),
        position_snapshot_utc=preview.position_snapshot_utc.isoformat(),owner_accepted=False),
        counts=dict(processed_count=len(rows)+sum(reasons.values()),available_count=len(rows),
                    unavailable_count=sum(reasons.values())-pending,reconciliation_pending_count=pending),items=rows)


def report_preview_csv(preview, **filters):
    response = report_preview(preview,**filters)
    stream = StringIO(newline='')
    fields = ('item_uid','account_alias','symbol','asset_class','close_market_date','currency',
              'realized_pnl','item_status','reason_codes','calculation_version')
    writer = csv.DictWriter(stream,fieldnames=fields)
    writer.writeheader()
    writer.writerows(dict(row,reason_codes=';'.join(row['reason_codes'])) for row in response['items'])
    return stream.getvalue()


def trade_preview(preview, episode_uid):
    """Validate the adapter output with the released Trades response types."""
    from onejournal.api.local_owner_journal import (
        TradeLifecycleResponse, LocalOwnerMetadata, _instrument, _execution,
    )
    trade = next(t for t in preview.trades if t['episode_uid']==episode_uid)
    instruments = [_instrument({k:v for k,v in asdict(i).items()
        if k not in ('episode_uid','instrument_projection_fingerprint')}) for i in preview.instruments if i.episode_uid==episode_uid]
    executions = []
    for e in preview.executions:
        if e.episode_uid!=episode_uid:
            continue
        row = {k:v for k,v in asdict(e).items() if k not in ('episode_uid','fill_uid','execution_projection_fingerprint','filled_at_utc')}
        row.update(filled_at=e.filled_at_utc,reconciliation_status='matched_schwab_transaction')
        executions.append(_execution(row))
    return TradeLifecycleResponse(metadata=LocalOwnerMetadata(),trade=trade,instruments=instruments,
        executions=executions,entries=[],presentation_group=None,lifecycle_story=None)


def rehearse_financial_preview(source, binding, *, expected_checkpoint_uid, account_alias):
    """Read retained activity on a verified disposable copy; emit counts only."""
    from onejournal.activity_rehearsal import disposable_journal, prepare_copy, _proof
    with disposable_journal(source) as target:
        state = prepare_copy(target)
        names = [r[1] for r in state['relations']]
        with duckdb.connect(str(target),read_only=True) as con:
            before = _proof(con,names)
        preview = load_activity_financial_preview(target,binding,
            expected_checkpoint_uid=expected_checkpoint_uid,account_alias=account_alias)
        for trade in preview.trades:
            trade_preview(preview,trade['episode_uid'])
        filters = dict(from_date=preview.coverage_start_date,to_date=preview.coverage_end_date)
        report = report_preview(preview,**filters)
        exported = list(csv.DictReader(StringIO(report_preview_csv(preview,**filters))))
        if len(exported)!=len(report['items']) or any(a['item_uid']!=b['item_uid'] or a['realized_pnl']!=b['realized_pnl']
            for a,b in zip(exported,report['items'])):
            raise ValueError('Preview JSON/CSV parity differs.')
        with duckdb.connect(str(target),read_only=True) as con:
            if _proof(con,names)!=before:
                raise ValueError('Financial preview changed disposable journal state.')
    return dict(contract_version=CONTRACT,status='offline_financial_rehearsal_passed',
        trade_count=len(preview.trades),execution_count=len(preview.executions),counts=report['counts'],
        quality=report['metadata']['quality'],original_unchanged=True,financial_publication_authorized=False)


def main(argv=None):
    import argparse
    from pathlib import Path
    from onejournal.brokers.schwab.account_binding import load_schwab_account_private_binding_bytes
    from onejournal.refresh_intake import read_private
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--account-binding',required=True,type=Path)
    parser.add_argument('--expected-checkpoint-uid',required=True)
    parser.add_argument('--account-alias',required=True)
    args = parser.parse_args(argv)
    try:
        binding = load_schwab_account_private_binding_bytes(read_private(args.account_binding,256*1024))
        result = rehearse_financial_preview(args.db,binding,
            expected_checkpoint_uid=args.expected_checkpoint_uid,account_alias=args.account_alias)
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception:
        print('Financial rehearsal stopped. Check the pinned activity checkpoint, account identity and reconciliation evidence. The temporary copy is discarded; no live write or broker call was attempted.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
