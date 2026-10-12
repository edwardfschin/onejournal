from copy import deepcopy

import pytest

from onejournal.brokers.schwab.web_history_review import (
    WebHistoryReviewError, compare_web_history_to_fills, isolated_put_assignment_cash_review,
    parse_web_history, review_assignment_links,
)


def raw(day, action, symbol, quantity, price='', fees='', amount=''):
    return {'Date': day, 'Action': action, 'Symbol': symbol, 'Description': 'Synthetic',
            'Quantity': quantity, 'Price': price, 'Fees & Comm': fees, 'Amount': amount}


def example():
    return {'BrokerageTransactions': [
        raw('02/20/2024', 'Sell', 'TEST', '100', '$45.00', '$0.10', '$4,499.90'),
        raw('01/19/2024 as of 01/18/2024', 'Assigned', 'TEST 01/19/2024 40.00 P', '1'),
        raw('01/19/2024 as of 01/18/2024', 'Buy', 'TEST', '100', '$40.00', '', '-$4,000.00'),
        raw('01/02/2024', 'Sell to Open', 'TEST 01/19/2024 40.00 P', '1', '$1.20', '$0.50', '$119.50'),
    ]}


def normalized():
    return {'source_fill_id': 'synthetic-existing', 'currency': 'USD', 'asset_class': 'stock',
            'symbol': 'TEST', 'filled_at': '2024-02-20T16:00:00+00:00', 'asof': '2024-02-20',
            'quantity': '100', 'fill_price': '45', 'commission': '0', 'fees': '0.10',
            'side': 'sell', 'open_close': 'close'}


def test_exact_assignment_cash_and_date_lineage_without_canonical_mutation():
    document = example(); before = deepcopy(document)
    rows = parse_web_history(document)
    link = review_assignment_links(rows)[0]
    assert link['status'] == 'source_linked_candidate'
    assert link['posting_date'] == '2024-01-19' and link['asof_date'] == '2024-01-18'
    assert link['net_premium'] == '119.50'
    result = isolated_put_assignment_cash_review(rows, link)
    assert result['premium_adjusted_cash_basis'] == '3880.50'
    assert result['recorded_chain_net_cash'] == '619.40'
    assert result['authoritative_pnl'] is False and result['report_persistence_authority'] is False
    assert result['unlisted_event_fees_not_proven_absent'] is True
    assert document == before


def test_one_to_one_economic_comparison_is_not_identity_authority():
    result = compare_web_history_to_fills(parse_web_history(example()), [normalized()], currency='USD')
    assert result[0]['status'] == 'economic_match'
    assert result[0]['matched_fill_ids'] == ['synthetic-existing']
    assert result[0]['canonical_import_authority'] is False


def test_uppercase_fill_side_is_equivalent_but_unknown_side_is_rejected():
    fill = dict(normalized(), side='SELL')
    assert compare_web_history_to_fills(parse_web_history(example()), [fill], currency='USD')[0]['status'] == 'economic_match'
    with pytest.raises(WebHistoryReviewError, match='side'):
        compare_web_history_to_fills(parse_web_history(example()), [dict(fill,side='unknown')], currency='USD')


def test_duplicate_web_rows_are_not_deduplicated_or_imported():
    document = example(); document['BrokerageTransactions'].append(deepcopy(document['BrokerageTransactions'][0]))
    result = compare_web_history_to_fills(parse_web_history(document), [normalized()], currency='USD')
    assert result[0]['status'] == result[-1]['status'] == 'ambiguous_repeated_web_economics'


def test_multiple_existing_economic_matches_are_withheld():
    second = dict(normalized(), source_fill_id='synthetic-other')
    result = compare_web_history_to_fills(parse_web_history(example()), [normalized(), second], currency='USD')
    assert result[0]['status'] == 'ambiguous'
    assert result == compare_web_history_to_fills(parse_web_history(example()), [second, normalized()], currency='USD')


@pytest.mark.parametrize('field,value', [('commission', '0.10'), ('fill_price', '45.01'),
                                         ('filled_at', '2024-02-21T16:00:00+00:00')])
def test_cost_price_and_date_conflicts_do_not_match(field, value):
    fill = normalized(); fill[field] = value
    if field == 'filled_at': fill['asof'] = '2024-02-21'
    assert compare_web_history_to_fills(parse_web_history(example()), [fill], currency='USD')[0]['status'] == 'not_matched'


def test_asof_match_retains_distinct_posting_date():
    document = {'BrokerageTransactions': [raw('02/21/2024 as of 02/20/2024', 'Sell', 'TEST',
        '100', '$45.00', '$0.10', '$4,499.90')]}
    result = compare_web_history_to_fills(parse_web_history(document), [normalized()], currency='USD')[0]
    assert result['status'] == 'economic_match' and result['date_matches'] == ['asof_date']


def test_same_day_open_and_assignment_do_not_invent_intraday_order():
    document = example(); document['BrokerageTransactions'][-1]['Date'] = '01/19/2024'
    assert review_assignment_links(parse_web_history(document))[0]['reason'] == 'same_day_option_order_requires_execution_evidence'


def test_missing_opening_and_ambiguous_delivery_are_withheld():
    document = example(); document['BrokerageTransactions'].pop()
    assert review_assignment_links(parse_web_history(document))[0]['reason'] == 'short_opening_history_missing'
    document = example(); document['BrokerageTransactions'].append(deepcopy(document['BrokerageTransactions'][2]))
    assert review_assignment_links(parse_web_history(document))[0]['reason'] == 'share_delivery_missing_or_ambiguous'


def test_missing_fees_and_wrong_deliverable_cash_are_not_guessed():
    for field,value in [('Fees & Comm', ''), ('Amount', '$118.50')]:
        document = example(); document['BrokerageTransactions'][-1][field] = value
        assert review_assignment_links(parse_web_history(document))[0]['reason'] == 'opening_cash_or_deliverable_not_reconciled'


def test_transfers_or_extra_stock_lots_prevent_isolated_cash_result():
    document = example(); document['BrokerageTransactions'].append(raw('01/01/2024','Journaled Shares','TEST','10'))
    rows = parse_web_history(document)
    with pytest.raises(WebHistoryReviewError, match='transfer, partial'):
        isolated_put_assignment_cash_review(rows, review_assignment_links(rows)[0])


def test_partial_short_close_allocates_only_remaining_premium():
    document = example(); opener = document['BrokerageTransactions'][-1]
    opener.update(Quantity='2', Amount='$239.00', **{'Fees & Comm':'$1.00'})
    document['BrokerageTransactions'].append(raw('01/03/2024', 'Buy to Close', opener['Symbol'],
        '1', '$0.30', '$0.50', '-$30.50'))
    link = review_assignment_links(parse_web_history(document))[0]
    assert link['net_premium'] == '119.50'


def test_call_assignment_can_explicitly_deliver_a_short_stock_position():
    document = {'BrokerageTransactions': [
        raw('01/19/2024 as of 01/18/2024','Assigned','TEST 01/19/2024 40.00 C','1'),
        raw('01/19/2024 as of 01/18/2024','Sell Short','TEST','100','$40.00','$0.10','$3,999.90'),
        raw('01/02/2024','Sell to Open','TEST 01/19/2024 40.00 C','1','$1.20','$0.50','$119.50')]}
    rows = parse_web_history(document)
    link = review_assignment_links(rows)[0]
    assert link['status'] == 'source_linked_candidate' and link['share_action'] == 'Sell Short'
    with pytest.raises(WebHistoryReviewError, match='put'):
        isolated_put_assignment_cash_review(rows,link)


def test_same_day_reductions_of_one_prior_lot_are_order_independent():
    document = example(); opener = document['BrokerageTransactions'][-1]
    opener.update(Quantity='5', Amount='$597.50', **{'Fees & Comm':'$2.50'})
    document['BrokerageTransactions'].append(raw('01/19/2024','Buy to Close',opener['Symbol'],
        '4','$0.30','$2.00','-$122.00'))
    rows = parse_web_history(document)
    link = review_assignment_links(rows)[0]
    assert link['net_premium'] == '119.50'
    assert link['predecessor_order_status'] == 'single_prior_lot_day_order_invariant'
    assert link == review_assignment_links(tuple(reversed(rows)))[0]


def test_same_day_competing_lots_or_quantity_deficit_are_not_resolved():
    document = example(); symbol = document['BrokerageTransactions'][-1]['Symbol']
    document['BrokerageTransactions'].append(raw('01/03/2024','Sell to Open',symbol,'1','$2.00','$0.50','$199.50'))
    document['BrokerageTransactions'].append(raw('01/19/2024','Buy to Close',symbol,'1','$0.30','$0.50','-$30.50'))
    assert review_assignment_links(parse_web_history(document))[0]['status'] == 'withheld'
    document = example()
    document['BrokerageTransactions'].append(raw('01/19/2024','Buy to Close',symbol,'1','$0.30','$0.50','-$30.50'))
    assert review_assignment_links(parse_web_history(document))[0]['status'] == 'withheld'


def test_blank_trade_amount_nonfinite_or_float_fail_closed():
    for field,value in [('Amount',''), ('Price','NaN'), ('Quantity',100.0)]:
        document = example(); document['BrokerageTransactions'][0][field] = value
        with pytest.raises(WebHistoryReviewError): parse_web_history(document)
