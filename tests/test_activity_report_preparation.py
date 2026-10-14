from dataclasses import replace
from decimal import Decimal
import unittest

from onejournal.activity_report_preparation import _validate_draft
import test_activity_financial_preview as financial_fixture


class ReportPreparationGuardTests(unittest.TestCase):
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
