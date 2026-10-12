"""Pure review of retained website history, never canonical import authority.

Website rows lack activity IDs and intraday timestamps. Economic matches are
diagnostic only; dates and repeated rows are never converted into fill IDs.
Assignment links retain posting/as-of dates and reject ambiguous day-only FIFO.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
import re
from zoneinfo import ZoneInfo


class WebHistoryReviewError(ValueError):
    """Value-free failure at the private raw-evidence boundary."""


TRADE_ACTIONS = {'Buy', 'Sell', 'Sell Short', 'Buy to Open', 'Buy to Close',
                 'Sell to Open', 'Sell to Close'}
OPTION_RE = re.compile(r'([A-Z0-9.\-]+) (\d{2}/\d{2}/\d{4}) (\d+(?:\.\d+)?) ([CP])')


def _decimal(value):
    if isinstance(value, float) or value is None or str(value).strip() == '':
        raise WebHistoryReviewError('required exact decimal is missing')
    try:
        result = Decimal(str(value).replace('$', '').replace(',', '').strip())
    except InvalidOperation as exc:
        raise WebHistoryReviewError('invalid exact decimal') from exc
    if not result.is_finite():
        raise WebHistoryReviewError('non-finite decimal')
    return result


def _day(value):
    try:
        return datetime.strptime(value, '%m/%d/%Y').date()
    except (ValueError, TypeError) as exc:
        raise WebHistoryReviewError('unsupported website date') from exc


def _identity(symbol):
    match = OPTION_RE.fullmatch(symbol)
    if match:
        return ('option', match[1], _day(match[2]).isoformat(),
                _decimal(match[3]), 'CALL' if match[4] == 'C' else 'PUT')
    return ('equity', symbol)


@dataclass(frozen=True)
class WebHistoryRow:
    source_row: int
    posting_date: date
    asof_date: date | None
    action: str
    identity: tuple
    quantity: Decimal | None
    price: Decimal | None
    fees: Decimal | None
    amount: Decimal | None
    raw: dict


def parse_web_history(document):
    records = document.get('BrokerageTransactions')
    if not isinstance(records, list) or not records:
        raise WebHistoryReviewError('website history records are required')
    result = []
    for index, raw in enumerate(records, 1):
        if not isinstance(raw, dict) or not {'Date', 'Action', 'Symbol', 'Description',
                'Quantity', 'Price', 'Fees & Comm', 'Amount'} <= raw.keys():
            raise WebHistoryReviewError('website history fields differ')
        dates = raw['Date'].split(' as of ')
        if len(dates) not in {1, 2}:
            raise WebHistoryReviewError('website date semantics differ')
        optional = lambda key: None if raw[key] == '' else _decimal(raw[key])
        row = WebHistoryRow(index, _day(dates[0]), _day(dates[1]) if len(dates) == 2 else None,
            raw['Action'], _identity(raw['Symbol']), optional('Quantity'), optional('Price'),
            optional('Fees & Comm'), optional('Amount'), dict(raw))
        if row.action in TRADE_ACTIONS and (row.quantity is None or row.quantity <= 0
                or row.price is None or row.price < 0 or row.amount is None
                or (row.fees is not None and row.fees < 0)):
            raise WebHistoryReviewError('trade economics are incomplete')
        result.append(row)
    return tuple(result)


def compare_web_history_to_fills(rows, normalized_rows, *, currency):
    """Compare exact economics and known dates; never infer record identity."""
    indexed = defaultdict(list)
    ids = set()
    for fill in normalized_rows:
        if fill['currency'] != currency or fill['source_fill_id'] in ids:
            raise WebHistoryReviewError('fill currency or identity scope differs')
        ids.add(fill['source_fill_id'])
        identity = (('option', fill['underlying_symbol'], str(fill['expiry']),
            _decimal(fill['strike']), fill['option_type']) if fill['asset_class'] == 'option'
            else ('equity', fill['symbol']))
        stamp = datetime.fromisoformat(str(fill['filled_at']).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise WebHistoryReviewError('canonical execution timezone is missing')
        fill_dates = {stamp.astimezone(ZoneInfo('America/New_York')).date(),
                      date.fromisoformat(str(fill['asof']))}
        effect = fill['open_close'].lower() if fill['asset_class'] == 'option' else ''
        fees = _decimal(fill['commission']) + _decimal(fill['fees'])
        gross = _decimal(fill['quantity']) * _decimal(fill['fill_price']) * (
            _decimal(fill['multiplier']) if fill['asset_class'] == 'option' else Decimal(1))
        side = str(fill['side']).upper()
        if side not in {'BUY', 'SELL'}:
            raise WebHistoryReviewError('normalized fill side is unsupported')
        net = (gross if side == 'SELL' else -gross) - fees
        key = (identity, side, effect, _decimal(fill['quantity']), _decimal(fill['fill_price']))
        indexed[key].append((fill['source_fill_id'], fees, net, fill_dates))
    results = []
    owners = defaultdict(list)
    for row in rows:
        if row.action not in TRADE_ACTIONS:
            continue
        side = 'BUY' if row.action.startswith('Buy') else 'SELL'
        effect = ('open' if row.action.endswith('Open') else 'close') if row.identity[0] == 'option' else ''
        key = (row.identity, side, effect, row.quantity, row.price)
        row_dates = {row.posting_date, row.asof_date} - {None}
        matches = sorted((uid, 'posting_date' if row.posting_date in days else 'asof_date')
                   for uid, fee, net, days in indexed[key]
                   if row_dates & days and net == row.amount and (row.fees is None or fee == row.fees))
        result = {'source_row': row.source_row,
                  'status': 'economic_match' if len(matches) == 1 else 'ambiguous' if matches else 'not_matched',
                  'matched_fill_ids': [uid for uid, _ in matches],
                  'date_matches': [kind for _, kind in matches], 'canonical_import_authority': False}
        for uid, _ in matches:
            owners[uid].append(result)
        results.append(result)
    for matches in owners.values():
        if len(matches) > 1:
            for match in matches:
                match['status'] = 'ambiguous_repeated_web_economics'
    return tuple(results)


def compare_web_execution_groups(rows, normalized_rows, *, currency):
    """Reconcile complete dated bundles, without merging or identifying fills.

    Website rows can consolidate partial executions or distribute per-row fees
    differently. Complete quantity, net cash and known fees must agree exactly.
    Distinct source-date alternatives, mixed deliverables and reuse remain
    ambiguous. No rounding/tolerance, subset selection or winning ID is used.
    """
    web = defaultdict(list)
    fills = {'execution_market_date': defaultdict(list), 'normalized_asof': defaultdict(list)}
    ids, accounts = set(), set()
    for fill in normalized_rows:
        uid = fill['source_fill_id']
        if uid in ids or fill['currency'] != currency:
            raise WebHistoryReviewError('group fill identity or currency differs')
        ids.add(uid); accounts.add((fill['source_broker'], fill['source_account_id']))
        identity = (('option', fill['underlying_symbol'], str(fill['expiry']),
            _decimal(fill['strike']), fill['option_type']) if fill['asset_class'] == 'option'
            else ('equity', fill['symbol']))
        side = str(fill['side']).upper()
        if side not in {'BUY', 'SELL'}:
            raise WebHistoryReviewError('normalized fill side is unsupported')
        effect = fill['open_close'].lower() if fill['asset_class'] == 'option' else ''
        stamp = datetime.fromisoformat(str(fill['filled_at']).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise WebHistoryReviewError('canonical execution timezone is missing')
        for kind, day in [('execution_market_date', stamp.astimezone(ZoneInfo('America/New_York')).date()),
                          ('normalized_asof', date.fromisoformat(str(fill['asof'])))]:
            fills[kind][(identity, side, effect, day)].append(fill)
    if len(accounts) > 1:
        raise WebHistoryReviewError('group comparison requires one broker account')
    for row in rows:
        if row.action in TRADE_ACTIONS:
            side = 'BUY' if row.action.startswith('Buy') else 'SELL'
            effect = ('open' if row.action.endswith('Open') else 'close') if row.identity[0] == 'option' else ''
            web[(row.identity, side, effect, row.posting_date, row.asof_date)].append(row)
    result, owners = [], defaultdict(list)
    with localcontext() as context:
        context.prec = 80
        for (identity, side, effect, posted, asof), members in web.items():
            web_quantity = sum((row.quantity for row in members), Decimal(0))
            web_cash = sum((row.amount for row in members), Decimal(0))
            web_fees = sum((row.fees for row in members), Decimal(0)) if all(row.fees is not None for row in members) else None
            alternatives = {}
            for kind, groups in fills.items():
                for day in {posted, asof} - {None}:
                    candidates = groups[(identity, side, effect, day)]
                    if not candidates:
                        continue
                    multipliers = {(_decimal(fill['multiplier']) if identity[0] == 'option'
                                    else Decimal(1)) for fill in candidates}
                    if len(multipliers) != 1:
                        continue
                    if any(_decimal(fill['quantity']) <= 0 or _decimal(fill['fill_price']) < 0
                           or _decimal(fill['commission']) < 0 or _decimal(fill['fees']) < 0
                           for fill in candidates) or next(iter(multipliers)) <= 0:
                        raise WebHistoryReviewError('invalid group fill economics')
                    quantity = sum((_decimal(fill['quantity']) for fill in candidates), Decimal(0))
                    costs = sum((_decimal(fill['commission']) + _decimal(fill['fees']) for fill in candidates), Decimal(0))
                    if quantity <= 0 or costs < 0:
                        raise WebHistoryReviewError('invalid group economics')
                    gross = sum((_decimal(fill['quantity']) * _decimal(fill['fill_price']) * next(iter(multipliers))
                                 for fill in candidates), Decimal(0))
                    cash = (gross if side == 'SELL' else -gross) - costs
                    if quantity == web_quantity and cash == web_cash and (web_fees is None or costs == web_fees):
                        candidate_ids = tuple(sorted(fill['source_fill_id'] for fill in candidates))
                        alternatives.setdefault(candidate_ids, []).append((kind, day.isoformat()))
            item = {'source_rows': sorted(row.source_row for row in members),
                    'status': 'group_economic_match' if len(alternatives) == 1 else
                              'ambiguous_date_groups' if alternatives else 'not_matched',
                    'candidate_fill_groups': [{'source_fill_ids': list(uids),
                                              'date_evidence': sorted(set(dates))}
                                             for uids, dates in sorted(alternatives.items())],
                    'row_identity_proven': False, 'canonical_import_authority': False}
            for uid in {uid for candidate_ids in alternatives for uid in candidate_ids}:
                owners[uid].append(item)
            result.append(item)
    for matches in owners.values():
        if len(matches) > 1:
            for item in matches:
                item['status'] = 'ambiguous_source_reuse'
    return tuple(sorted(result, key=lambda item: item['source_rows']))


def _short_predecessors(rows, target):
    relevant = [row for row in rows if row.identity == target.identity
                and row.posting_date <= target.posting_date and row.action in
                {'Sell to Open', 'Buy to Close', 'Assigned', 'Expired', 'Journaled Shares'}]
    by_day = defaultdict(list)
    for row in relevant:
        by_day[row.posting_date].append(row)
    lots = []
    for day in sorted(by_day):
        group = by_day[day]
        active = [r for r in group if r.action != 'Expired' or (r.quantity is not None and r.quantity > 0)]
        if any(r.action == 'Journaled Shares' for r in group):
            return None, 'option_transfer_requires_original_basis'
        if len(active) > 1:
            # Multiple reductions of one earlier lot have identical lineage and
            # proportional premium under every intraday order. Prove this narrow
            # case; never choose a display order for competing lots or new opens.
            if (len(lots) == 1 and all(r.action in {'Buy to Close', 'Assigned', 'Expired'}
                    and r.quantity is not None and r.quantity > 0 for r in active)):
                total = sum((r.quantity for r in active), Decimal(0))
                if total <= lots[0][1]:
                    selected = next((r for r in active if r.source_row == target.source_row), None)
                    if selected is not None:
                        return [(lots[0][0], selected.quantity)], None
                    lots[0][1] -= total
                    lots = [lot for lot in lots if lot[1] > 0]
                    continue
            return None, 'same_day_option_order_requires_execution_evidence'
        for row in active:
            if row.quantity is None or row.quantity <= 0:
                return None, 'terminal_contract_quantity_missing'
            if row.action == 'Sell to Open':
                lots.append([row, row.quantity])
                continue
            remaining = row.quantity
            allocations = []
            for lot in lots:
                matched = min(remaining, lot[1])
                if matched:
                    allocations.append((lot[0], matched))
                    lot[1] -= matched
                    remaining -= matched
            lots = [lot for lot in lots if lot[1] > 0]
            if remaining:
                return None, 'short_opening_history_missing'
            if row.source_row == target.source_row:
                return allocations, None
    return None, 'assignment_predecessor_not_resolved'


def review_assignment_links(rows):
    """Find exact strike deliveries and date-unambiguous short-option lots."""
    result = []
    for event in rows:
        if event.action != 'Assigned':
            continue
        item = {'assignment_row': event.source_row, 'status': 'withheld',
                'posting_date': event.posting_date.isoformat(),
                'asof_date': event.asof_date.isoformat() if event.asof_date else None,
                'option_identity': event.identity, 'canonical_import_authority': False}
        if event.identity[0] != 'option' or event.quantity is None or event.quantity <= 0:
            item['reason'] = 'assignment_option_identity_or_quantity_missing'
            result.append(item); continue
        actions = {'Buy'} if event.identity[-1] == 'PUT' else {'Sell', 'Sell Short'}
        shares = [row for row in rows if row.identity == ('equity', event.identity[1])
                  and row.action in actions and row.raw['Date'] == event.raw['Date']
                  and row.price == event.identity[3]]
        if len(shares) != 1:
            item['reason'] = 'share_delivery_missing_or_ambiguous'
            result.append(item); continue
        share = shares[0]
        action = 'Buy' if share.action == 'Buy' else 'Sell'
        multiplier = share.quantity / event.quantity
        predecessors, reason = _short_predecessors(rows, event)
        if reason:
            item.update(reason=reason, share_row=share.source_row)
            result.append(item); continue
        with localcontext() as context:
            context.prec = 80
            premium = Decimal(0)
            links = []
            for opening, contracts in predecessors:
                fees = opening.fees
                if fees is None or opening.amount != opening.quantity * opening.price * multiplier - fees:
                    reason = 'opening_cash_or_deliverable_not_reconciled'; break
                allocated = opening.amount * contracts / opening.quantity
                premium += allocated
                links.append({'opening_row': opening.source_row, 'contracts': str(contracts),
                              'net_premium_allocated': str(allocated)})
            gross = share.quantity * share.price
            implied_share_fees = (gross if action == 'Sell' else -gross) - share.amount
            if implied_share_fees < 0 or (share.fees is not None and implied_share_fees != share.fees):
                reason = 'share_cash_not_reconciled'
            if reason:
                item.update(reason=reason, share_row=share.source_row)
            else:
                item.update(status='source_linked_candidate', share_row=share.source_row,
                    share_action=share.action,
                    predecessor_order_status=('single_prior_lot_day_order_invariant' if sum(
                        1 for row in rows if row.identity == event.identity
                        and row.posting_date == event.posting_date and row.action in
                        {'Buy to Close', 'Assigned', 'Sell to Open'}
                    ) > 1 else 'date_order_unambiguous'),
                    contracts=str(event.quantity), delivered_shares=str(share.quantity),
                    cash_confirmed_deliverable_ratio=str(multiplier), opening_links=links,
                    net_premium=str(premium), share_cash=str(share.amount),
                    assignment_cash_fees_unknown=event.amount is None,
                    financial_acceptance=False)
        result.append(item)
    return tuple(result)


def isolated_put_assignment_cash_review(rows, link):
    """Recorded cash only for an isolated put/delivery/full-sale chain.

    No synthetic timestamps, approved events, changed fill values or reporting
    allocations are created. Separate fees/adjustments and strategy trades remain
    outside this bounded recorded-cash result; it is not accepted/tax P&L.
    """
    if link['status'] != 'source_linked_candidate' or link['option_identity'][-1] != 'PUT':
        raise WebHistoryReviewError('isolated review requires a linked put assignment')
    by_row = {row.source_row: row for row in rows}
    delivery = by_row[link['share_row']]
    equity = [row for row in rows if row.identity == delivery.identity and row.quantity is not None]
    closes = [row for row in equity if row.action == 'Sell' and row.quantity == delivery.quantity
              and row.posting_date >= delivery.posting_date]
    if len(equity) != 2 or len(closes) != 1:
        raise WebHistoryReviewError('equity scope needs transfer, partial or additional-lot reconciliation')
    close = closes[0]
    gross = close.quantity * close.price
    if close.fees is None or gross - close.fees != close.amount:
        raise WebHistoryReviewError('share disposal cash does not reconcile')
    with localcontext() as context:
        context.prec = 80
        premium = Decimal(link['net_premium'])
        net_basis = -delivery.amount - premium
        result = premium + delivery.amount + close.amount
    return {'symbol': delivery.identity[1], 'quantity': str(delivery.quantity),
            'opening_rows': [entry['opening_row'] for entry in link['opening_links']],
            'assignment_row': link['assignment_row'], 'delivery_row': delivery.source_row,
            'sale_row': close.source_row, 'sale_posting_date': close.posting_date.isoformat(),
            'net_put_premium': str(premium), 'share_purchase_cash': str(delivery.amount),
            'share_sale_net_cash': str(close.amount), 'premium_adjusted_cash_basis': str(net_basis),
            'recorded_chain_net_cash': str(result), 'separate_strategy_trades_excluded': True,
            'unlisted_event_fees_not_proven_absent': link['assignment_cash_fees_unknown'],
            'authoritative_pnl': False, 'financial_acceptance': False, 'report_persistence_authority': False}
