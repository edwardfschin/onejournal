from dataclasses import replace
from decimal import Decimal
import unittest

from onejournal.activity_report_preparation import _validate_draft,_calculation_revision
from onejournal.activity_financial_preview import (
    CURRENT_CALCULATION_REVISION,LEGACY_CALCULATION_REVISION,
)
import test_activity_financial_preview as financial_fixture


class ReportPreparationGuardTests(unittest.TestCase):
    def test_recovery_dispatch_preserves_legacy_and_requires_known_new_marker(self):
        self.assertEqual(_calculation_revision({'metadata':{}}),LEGACY_CALCULATION_REVISION)
        self.assertEqual(_calculation_revision({'metadata':{
            'calculation_version':'fifo+'+CURRENT_CALCULATION_REVISION}}),CURRENT_CALCULATION_REVISION)
        for metadata in (None,{'calculation_version':None},{'calculation_version':'unknown'}):
            with self.assertRaises(ValueError):
                _calculation_revision({'metadata':metadata})

    def test_release_precision_and_identity_checks_do_not_require_fake_acceptance(self):
        fixture = financial_fixture.ActivityFinancialPreviewTests()
        fixture.setUp()
        preview = fixture.preview()
        _validate_draft(preview)
        for amount in (Decimal('123456789012'),Decimal('0.1234567890123456789012345678')):
            invalid = replace(preview,items=(replace(preview.items[0],realized_pnl=amount),))
            with self.assertRaisesRegex(ValueError,'precision'):
                _validate_draft(invalid)
        with self.assertRaisesRegex(ValueError,'duplicated'):
            _validate_draft(replace(preview,items=(preview.items[0],preview.items[0])))
