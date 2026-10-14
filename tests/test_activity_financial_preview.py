from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import csv
from io import StringIO
import unittest

from onejournal.activity_financial_preview import _build_preview,report_preview,report_preview_csv,trade_preview
from onejournal.journal.schwab_evidence_assembly import build_schwab_phase1_evidence_assembly_v3
from onejournal.refresh_activity import ConfirmedActivityImport
from onejournal.pnl import ApprovedOptionLifecycleEvent,build_instrument_key
from onejournal.pnl.bounded_reconciliation import normalized_fill_from_lifecycle_transaction_row
from test_snapshot_cutoff_evidence import inputs


class ActivityFinancialPreviewTests(unittest.TestCase):
    def setUp(self):
        self.assembly = build_schwab_phase1_evidence_assembly_v3(**inputs())
        self.original = {f.family:f.records for f in self.assembly.families}
        self.close = dict(self.original['fills'][0],source_fill_id='schwab_txn:close-1:order:close-order:position:1:item:0',
            source_order_id='close-order',asof='2026-09-07',filled_at='2026-09-07T13:00:00+00:00',
            side='sell',open_close='close',fill_price='110',commission='0.10',fees='0.20')
        self.transaction = dict(self.original['transactions'][0],transaction_uid='synthetic-close-transaction',
            source_transaction_id='close-1',source_order_id='close-order',transaction_at_utc=self.close['filled_at'],net_amount='219.70')

    def baseline(self, *, close=None, transaction=None, records=None):
        additions = dict(fills=(close or self.close,),transactions=(transaction or self.transaction,))
        additions.update(records or {})
        return ConfirmedActivityImport('synthetic-activation','synthetic-revision',self.assembly,
            'a'*64,datetime(2026,9,8,14,tzinfo=UTC),additions)

    def preview(self, baseline=None):
        return _build_preview(baseline or self.baseline(),approved_events=(),account_alias='Primary')

    def filters(self, preview):
        return dict(from_date=preview.coverage_start_date,to_date=preview.coverage_end_date)

    def test_new_close_reconciles_fees_and_reuses_trade_report_contracts(self):
        preview = self.preview()
        report = report_preview(preview,**self.filters(preview))
        self.assertEqual(report['metadata']['quality'],'valid')
        self.assertEqual(report['items'][0]['realized_pnl'],'19.70')
        self.assertFalse(report['metadata']['owner_accepted'])
        self.assertEqual(len(preview.executions),2)
        self.assertEqual(len(preview.trades),1)
        trade = trade_preview(preview,preview.trades[0]['episode_uid'])
        self.assertEqual(trade.trade.episode_status,'closed')
        self.assertEqual(trade.trade.instrument_count,1)
        self.assertEqual(trade.trade.strategy_type,'stock_long')
        self.assertEqual(trade.executions[1].calculated_net_cash_movement,'219.70')
        rows = list(csv.DictReader(StringIO(report_preview_csv(preview,**self.filters(preview)))))
        self.assertEqual(rows[0]['realized_pnl'],report['items'][0]['realized_pnl'])
        self.assertEqual(self.preview().result_fingerprint,preview.result_fingerprint)
        outside = report_preview(preview,from_date=date(2020,1,1),to_date=preview.coverage_end_date)
        self.assertEqual(outside['metadata']['quality'],'unavailable')
        self.assertEqual(outside['items'],[])

    def test_precise_values_are_not_rounded_to_database_projection_scale(self):
        close = dict(self.close,fill_price='110.1234567890123',commission='0.000000000012345',fees='0')
        net = Decimal(close['fill_price'])*Decimal('2')-Decimal(close['commission'])
        preview = self.preview(self.baseline(close=close,transaction=dict(self.transaction,net_amount=str(net))))
        self.assertEqual(preview.items[0].realized_pnl,net-Decimal('200'))
        self.assertEqual(preview.executions[-1].fill_price,Decimal(close['fill_price']))

    def test_missing_opening_or_cash_mismatch_cannot_produce_pnl(self):
        missing = dict(self.close,quantity='3')
        preview = self.preview(self.baseline(close=missing,transaction=dict(self.transaction,net_amount='329.70')))
        self.assertEqual(preview.items,())
        self.assertEqual(preview.omissions[0].reason_code,'opening_history_missing')
        with self.assertRaisesRegex(ValueError,'cash movement'):
            self.preview(self.baseline(transaction=dict(self.transaction,net_amount='219.71')))

    def test_new_cycle_open_position_requires_a_fresh_snapshot(self):
        reopened = dict(self.original['fills'][0],source_fill_id='schwab_txn:reopen:order:reopen:position:1:item:0',
            source_order_id='reopen',asof='2026-09-08',filled_at='2026-09-08T13:00:00+00:00',fill_price='120')
        txn = dict(self.transaction,transaction_uid='synthetic-reopen',source_transaction_id='reopen',net_amount='-240')
        preview = self.preview(self.baseline(records=dict(fills=(self.close,reopened),transactions=(self.transaction,txn))))
        report = report_preview(preview,**self.filters(preview))
        self.assertEqual(len(preview.trades),2)
        self.assertEqual(len(preview.items),1)
        self.assertEqual(report['metadata']['quality'],'reconciliation_pending')
        self.assertEqual(report['counts']['reconciliation_pending_count'],1)
        self.assertEqual(preview.position_snapshot_utc,self.assembly.snapshot_cutoff_utc)

    def test_duplicate_evidence_and_post_checkpoint_rows_are_not_double_counted(self):
        baseline = self.baseline(records=dict(fills=(self.close,self.close,self.original['fills'][0]),
            transactions=(self.transaction,self.transaction)))
        self.assertEqual(self.preview(baseline).result_fingerprint,self.preview().result_fingerprint)
        late = dict(self.close,source_fill_id='later-fill',filled_at='2026-09-08T14:01:00+00:00')
        self.assertEqual(self.preview(self.baseline(records=dict(fills=(self.close,late)))).result_fingerprint,
                         self.preview().result_fingerprint)

    def test_unreviewed_terminal_evidence_is_withheld(self):
        event = dict(event_uid='unreviewed-event',event_at='2026-09-07T13:00:00+00:00',event_type='ASSIGNMENT')
        leg = dict(event_uid='unreviewed-event',event_leg_uid='unreviewed-leg',leg_kind='security',
                   asset_class='stock',symbol='AAPL',currency='USD')
        preview = self.preview(self.baseline(records=dict(lifecycle_events=(event,),lifecycle_event_legs=(leg,))))
        self.assertEqual(preview.items,())
        self.assertEqual(preview.omissions[0].reason_code,'lifecycle_review_required')

    def test_order_observation_status_changes_do_not_change_financial_fills(self):
        order = self.original['orders'][0]
        baseline = self.baseline(records=dict(orders=(dict(order,status='WORKING'),dict(order,status='FILLED'))))
        self.assertEqual(self.preview(baseline).result_fingerprint,self.preview().result_fingerprint)

    def test_later_terminal_event_does_not_erase_a_previously_closed_result(self):
        event = dict(event_uid='later-unreviewed-event',event_at='2026-09-08T13:00:00+00:00',event_type='ASSIGNMENT')
        leg = dict(event_uid=event['event_uid'],event_leg_uid='later-unreviewed-leg',leg_kind='security',
                   asset_class='stock',symbol='AAPL',currency='USD')
        preview = self.preview(self.baseline(records=dict(lifecycle_events=(event,),lifecycle_event_legs=(leg,))))
        self.assertEqual(preview.items[0].realized_pnl,Decimal('19.70'))

    def test_approved_expiration_closes_option_and_preserves_lifecycle_pnl(self):
        row = dict(self.original['fills'][0],source_fill_id='schwab_txn:option-1:order:option-order:position:1:item:0',
            source_order_id='option-order',asset_class='option',side='sell',quantity='1',fill_price='2',commission='0.5',
            symbol='AAPL  260907P00200000',option_symbol='AAPL  260907P00200000',underlying_symbol='AAPL',
            option_type='PUT',expiry='2026-09-07',strike='200',multiplier='100',asof='2026-09-07',
            filled_at='2026-09-07T12:00:00+00:00')
        txn = dict(self.transaction,transaction_uid='synthetic-option',source_transaction_id='option-1',net_amount='199.5')
        event = dict(event_uid='approved-expiration',event_at='2026-09-07T13:00:00+00:00',event_type='EXPIRATION')
        leg = dict(event_uid=event['event_uid'],event_leg_uid='approved-expiration-leg',leg_kind='security')
        fill = normalized_fill_from_lifecycle_transaction_row(row,fetched_at=datetime(2026,9,8,tzinfo=UTC),raw_path='synthetic')
        approval = ApprovedOptionLifecycleEvent(event['event_uid'],'EXPIRATION','schwab',fill.source_account_id,'USD',
            datetime(2026,9,7,13,tzinfo=UTC),('schwab',fill.source_account_id,build_instrument_key(fill),'USD'),
            'SHORT',Decimal('1'),(fill.fill_uid,),Decimal('0'),Decimal('0'),'approved',(leg['event_leg_uid'],))
        baseline = self.baseline(records=dict(fills=(row,),transactions=(txn,),lifecycle_events=(event,),lifecycle_event_legs=(leg,)))
        preview = _build_preview(baseline,approved_events=(approval,),account_alias='Primary')
        self.assertEqual(preview.items[0].realized_pnl,Decimal('199.5'))
        option = next(t for t in preview.trades if t['asset_class']=='option')
        self.assertEqual(option['episode_status'],'closed')
        self.assertEqual(option['lifecycle_quality'],'resolved')
        with self.assertRaisesRegex(ValueError,'links differ'):
            _build_preview(baseline,approved_events=(replace(approval,source_event_leg_uids=('missing-leg',)),),account_alias='Primary')
