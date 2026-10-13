"""Private receipt and exact comparison boundaries; synthetic values only."""
from contextlib import redirect_stdout
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onejournal.hosted_migration import _value, _temporary_private_directory
from scripts.web import rehearse_hosted_migration as command


class HostedMigrationTests(unittest.TestCase):
    def test_exact_scalars_and_private_temporary_boundary(self):
        self.assertNotEqual(_value(Decimal('1.0000000000000001')), _value(Decimal('1.0000000000000002')))
        for value in [float('nan'), Decimal('Infinity')]:
            with self.assertRaises(ValueError):
                _value(value)
        with self.assertRaises(ValueError):
            _temporary_private_directory(Path('/Users/edward/Projects/Private/OneJournal'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o755)
            with self.assertRaises(ValueError):
                _temporary_private_directory(root)

    def test_receipt_is_private_no_overwrite_and_failure_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            dsn = root / 'target'
            dsn.write_text('host=/private/tmp/example port=55439 dbname=oj_rehearsal_test user=synthetic')
            dsn.chmod(0o600)
            receipt = root / 'receipt.json'
            args = ['rehearse', '--source-copy', str(root / 'copy.duckdb'), '--source-sha256', 'a'*64,
                    '--target-dsn-file', str(dsn), '--receipt', str(receipt)]
            output = io.StringIO()
            with patch('sys.argv', args), patch.object(command, 'rehearse', return_value={'activated': False}), redirect_stdout(output):
                self.assertEqual(command.main(), 0)
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(receipt.read_text()), {'activated': False})
                self.assertEqual(command.main(), 1)
                self.assertEqual(json.loads(receipt.read_text()), {'activated': False})
            receipt.unlink()
            with patch('sys.argv', args), patch.object(command, 'rehearse', side_effect=ValueError('private-value')), redirect_stdout(output):
                self.assertEqual(command.main(), 1)
            self.assertFalse(receipt.exists())
            self.assertNotIn('private-value', output.getvalue())
