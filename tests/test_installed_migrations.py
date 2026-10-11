"""Installed migration resources must retain the authoritative SQL bytes."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from onejournal.journal import migrations


class InstalledMigrationTests(unittest.TestCase):
    def test_source_directory_is_unchanged(self):
        self.assertEqual(migrations.DEFAULT_MIGRATIONS_DIR,
                         migrations.PROJECT_ROOT / "scripts/journal/migrations")

    def test_relocated_module_uses_its_install_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relocated = root / "lib/python/site-packages/onejournal/journal/migrations.py"
            relocated.parent.mkdir(parents=True)
            relocated.write_bytes(Path(migrations.__file__).read_bytes())
            spec = importlib.util.spec_from_file_location("installed_migration_probe", relocated)
            module = importlib.util.module_from_spec(spec)
            with patch.object(sys, "prefix", str(root)), patch.dict(sys.modules, {spec.name: module}):
                spec.loader.exec_module(module)
            self.assertEqual(module.DEFAULT_MIGRATIONS_DIR, root / "share/onejournal/migrations")

    def test_wheel_declares_the_single_authoritative_sql_source(self):
        config = tomllib.loads((migrations.PROJECT_ROOT / "pyproject.toml").read_text())
        self.assertEqual(config["tool"]["setuptools"]["data-files"]["share/onejournal/migrations"],
                         ["scripts/journal/migrations/*.sql"])


if __name__ == "__main__":
    unittest.main()
