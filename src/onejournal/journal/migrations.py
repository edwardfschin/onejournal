"""Journal database migration helpers and migration metadata tracking."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from subprocess import CalledProcessError, check_output
from typing import Iterable
from uuid import uuid4

import duckdb

try:
    from onejournal import __version__ as onejournal_version
except Exception:  # pragma: no cover - defensive for environments with unusual packaging
    onejournal_version = None


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"
SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


@dataclass(frozen=True)
class _ColumnSpec:
    name: str
    type_decl: str
    not_null: bool


@dataclass(frozen=True)
class MigrationSpec:
    version: str
    name: str
    path: Path
    checksum: str


BASELINE_TABLE_DEFINITIONS: dict[str, str] = {
    "import_runs": """
        CREATE TABLE import_runs (
            import_run_id VARCHAR PRIMARY KEY,
            source_type VARCHAR NOT NULL,
            source_path VARCHAR,
            asof_date DATE,
            imported_at TIMESTAMP NOT NULL,
            row_count INTEGER NOT NULL,
            status VARCHAR NOT NULL,
            notes VARCHAR
        )
    """,
    "normalized_fills": """
        CREATE TABLE normalized_fills (
            fill_uid VARCHAR PRIMARY KEY,
            source_broker VARCHAR NOT NULL,
            source_account_id VARCHAR NOT NULL,
            source_fill_id VARCHAR NOT NULL,
            source_order_id VARCHAR,
            episode_group_id VARCHAR,
            asof_date DATE NOT NULL,
            filled_at TIMESTAMP NOT NULL,
            asset_class VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            quantity DECIMAL(38, 10) NOT NULL,
            fill_price DECIMAL(38, 10) NOT NULL,
            commission DECIMAL(38, 10) NOT NULL,
            fees DECIMAL(38, 10) NOT NULL,
            currency VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL,
            raw_path VARCHAR,
            option_symbol VARCHAR,
            underlying_symbol VARCHAR,
            option_type VARCHAR,
            expiry DATE,
            strike DECIMAL(38, 10),
            multiplier DECIMAL(38, 10),
            open_close VARCHAR,
            execution_venue VARCHAR,
            liquidity_flag VARCHAR,
            import_run_id VARCHAR
        )
    """,
    "manual_reviews": """
        CREATE TABLE manual_reviews (
            episode_uid VARCHAR PRIMARY KEY,
            review_status VARCHAR NOT NULL,
            setup_quality VARCHAR NOT NULL,
            entry_reason VARCHAR,
            notes VARCHAR,
            updated_at TIMESTAMP NOT NULL
        )
    """,
    "trade_episodes": """
        CREATE TABLE trade_episodes (
            episode_uid VARCHAR PRIMARY KEY,
            source_broker VARCHAR NOT NULL,
            source_account_id VARCHAR NOT NULL,
            primary_symbol VARCHAR NOT NULL,
            asset_class VARCHAR NOT NULL,
            strategy_type VARCHAR NOT NULL,
            strategy_label VARCHAR NOT NULL,
            opened_at TIMESTAMP NOT NULL,
            status VARCHAR NOT NULL,
            fill_count INTEGER NOT NULL,
            leg_count INTEGER NOT NULL,
            leg_summary VARCHAR,
            cashflow_label VARCHAR,
            net_quantity DECIMAL(38, 10),
            gross_cashflow DECIMAL(38, 10),
            commission DECIMAL(38, 10),
            fees DECIMAL(38, 10),
            updated_at TIMESTAMP NOT NULL
        )
    """,
    "trade_episode_legs": """
        CREATE TABLE trade_episode_legs (
            episode_uid VARCHAR NOT NULL,
            leg_index INTEGER NOT NULL,
            asset_class VARCHAR,
            symbol VARCHAR,
            side VARCHAR,
            quantity DECIMAL(38, 10),
            option_type VARCHAR,
            expiry DATE,
            strike DECIMAL(38, 10),
            raw_leg_json VARCHAR,
            PRIMARY KEY (episode_uid, leg_index)
        )
    """,
}


BASELINE_COLUMNS: dict[str, tuple[_ColumnSpec, ...]] = {
    "import_runs": (
        _ColumnSpec("import_run_id", "VARCHAR", True),
        _ColumnSpec("source_type", "VARCHAR", True),
        _ColumnSpec("source_path", "VARCHAR", False),
        _ColumnSpec("asof_date", "DATE", False),
        _ColumnSpec("imported_at", "TIMESTAMP", True),
        _ColumnSpec("row_count", "INTEGER", True),
        _ColumnSpec("status", "VARCHAR", True),
        _ColumnSpec("notes", "VARCHAR", False),
    ),
    "normalized_fills": (
        _ColumnSpec("fill_uid", "VARCHAR", True),
        _ColumnSpec("source_broker", "VARCHAR", True),
        _ColumnSpec("source_account_id", "VARCHAR", True),
        _ColumnSpec("source_fill_id", "VARCHAR", True),
        _ColumnSpec("source_order_id", "VARCHAR", False),
        _ColumnSpec("episode_group_id", "VARCHAR", False),
        _ColumnSpec("asof_date", "DATE", True),
        _ColumnSpec("filled_at", "TIMESTAMP", True),
        _ColumnSpec("asset_class", "VARCHAR", True),
        _ColumnSpec("symbol", "VARCHAR", True),
        _ColumnSpec("side", "VARCHAR", True),
        _ColumnSpec("quantity", "DECIMAL(38, 10)", True),
        _ColumnSpec("fill_price", "DECIMAL(38, 10)", True),
        _ColumnSpec("commission", "DECIMAL(38, 10)", True),
        _ColumnSpec("fees", "DECIMAL(38, 10)", True),
        _ColumnSpec("currency", "VARCHAR", True),
        _ColumnSpec("fetched_at", "TIMESTAMP", True),
        _ColumnSpec("raw_path", "VARCHAR", False),
        _ColumnSpec("option_symbol", "VARCHAR", False),
        _ColumnSpec("underlying_symbol", "VARCHAR", False),
        _ColumnSpec("option_type", "VARCHAR", False),
        _ColumnSpec("expiry", "DATE", False),
        _ColumnSpec("strike", "DECIMAL(38, 10)", False),
        _ColumnSpec("multiplier", "DECIMAL(38, 10)", False),
        _ColumnSpec("open_close", "VARCHAR", False),
        _ColumnSpec("execution_venue", "VARCHAR", False),
        _ColumnSpec("liquidity_flag", "VARCHAR", False),
        _ColumnSpec("import_run_id", "VARCHAR", False),
    ),
    "manual_reviews": (
        _ColumnSpec("episode_uid", "VARCHAR", True),
        _ColumnSpec("review_status", "VARCHAR", True),
        _ColumnSpec("setup_quality", "VARCHAR", True),
        _ColumnSpec("entry_reason", "VARCHAR", False),
        _ColumnSpec("notes", "VARCHAR", False),
        _ColumnSpec("updated_at", "TIMESTAMP", True),
    ),
    "trade_episodes": (
        _ColumnSpec("episode_uid", "VARCHAR", True),
        _ColumnSpec("source_broker", "VARCHAR", True),
        _ColumnSpec("source_account_id", "VARCHAR", True),
        _ColumnSpec("primary_symbol", "VARCHAR", True),
        _ColumnSpec("asset_class", "VARCHAR", True),
        _ColumnSpec("strategy_type", "VARCHAR", True),
        _ColumnSpec("strategy_label", "VARCHAR", True),
        _ColumnSpec("opened_at", "TIMESTAMP", True),
        _ColumnSpec("status", "VARCHAR", True),
        _ColumnSpec("fill_count", "INTEGER", True),
        _ColumnSpec("leg_count", "INTEGER", True),
        _ColumnSpec("leg_summary", "VARCHAR", False),
        _ColumnSpec("cashflow_label", "VARCHAR", False),
        _ColumnSpec("net_quantity", "DECIMAL(38, 10)", False),
        _ColumnSpec("gross_cashflow", "DECIMAL(38, 10)", False),
        _ColumnSpec("commission", "DECIMAL(38, 10)", False),
        _ColumnSpec("fees", "DECIMAL(38, 10)", False),
        _ColumnSpec("updated_at", "TIMESTAMP", True),
    ),
    "trade_episode_legs": (
        _ColumnSpec("episode_uid", "VARCHAR", True),
        _ColumnSpec("leg_index", "INTEGER", True),
        _ColumnSpec("asset_class", "VARCHAR", False),
        _ColumnSpec("symbol", "VARCHAR", False),
        _ColumnSpec("side", "VARCHAR", False),
        _ColumnSpec("quantity", "DECIMAL(38, 10)", False),
        _ColumnSpec("option_type", "VARCHAR", False),
        _ColumnSpec("expiry", "DATE", False),
        _ColumnSpec("strike", "DECIMAL(38, 10)", False),
        _ColumnSpec("raw_leg_json", "VARCHAR", False),
    ),
}


def _ordered_migration_files(migrations_dir: Path) -> Iterable[Path]:
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.is_file():
            yield path


def _is_versioned_migration(path: Path) -> bool:
    return path.stem[:4].isdigit()


def _migration_version(path: Path) -> str:
    stem = path.stem
    version = stem.split("_", 1)[0]
    if len(version) != 4 or not version.isdigit():
        raise ValueError(f"Malformed migration filename {path.name}; expected NNNN_description.sql")
    return version


def _migration_name(path: Path) -> str:
    return "_".join(path.stem.split("_")[1:])

def _checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_migrations(migrations_dir: Path) -> list[MigrationSpec]:
    migrations: list[MigrationSpec] = []
    for path in _ordered_migration_files(migrations_dir):
        if not _is_versioned_migration(path):
            continue
        version = _migration_version(path)
        name = _migration_name(path)
        migrations.append(MigrationSpec(version=version, name=name, path=path, checksum=_checksum(path)))
    return migrations


def _table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def _normalize_type_decl(type_decl: str) -> str:
    return re.sub(r"\s+", "", str(type_decl).upper())


def _existing_column_specs(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, tuple[str, bool]]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1]: (_normalize_type_decl(row[2]), bool(row[3])) for row in rows}


def _ensure_baseline_tables(con: duckdb.DuckDBPyConnection) -> None:
    existing = _table_names(con)
    existing_without_ledger = existing - {SCHEMA_MIGRATIONS_TABLE}
    required_tables = set(BASELINE_TABLE_DEFINITIONS.keys())
    missing = required_tables - existing_without_ledger
    if not existing_without_ledger:
        for table_name in ("import_runs", "normalized_fills", "manual_reviews", "trade_episodes", "trade_episode_legs"):
            con.execute(BASELINE_TABLE_DEFINITIONS[table_name])
        return

    if missing:
        raise RuntimeError(
            "cannot apply baseline migration on partially-created schema; "
            f"missing baseline table(s): {', '.join(sorted(missing))}"
        )

    for table_name, expected_columns in BASELINE_COLUMNS.items():
        existing_columns = _existing_column_specs(con, table_name)
        expected_names = [col.name for col in expected_columns]
        missing_columns = set(expected_names) - set(existing_columns.keys())
        if missing_columns:
            raise RuntimeError(
                f"baseline schema mismatch for {table_name}: "
                f"missing baseline columns {sorted(missing_columns)}; "
                f"found {sorted(existing_columns.keys())}"
            )
        for expected in expected_columns:
            existing_type, existing_not_null = existing_columns[expected.name]
            if _normalize_type_decl(expected.type_decl) != existing_type:
                raise RuntimeError(
                    f"baseline schema mismatch for {table_name}.{expected.name}: "
                    f"expected {expected.type_decl}, found {existing_type}"
                )
            if bool(expected.not_null) != existing_not_null:
                raise RuntimeError(
                    f"baseline schema mismatch for {table_name}.{expected.name}: "
                    f"expected not_null={expected.not_null}, found {existing_not_null}"
                )


def _current_version(con: duckdb.DuckDBPyConnection) -> int:
    if SCHEMA_MIGRATIONS_TABLE not in _table_names(con):
        return 0
    rows = con.execute(f"SELECT version, status FROM {SCHEMA_MIGRATIONS_TABLE} WHERE status = 'applied'").fetchall()
    if not rows:
        return 0
    return max(int(version) for version, _ in rows)


def _validate_applied_migrations(con: duckdb.DuckDBPyConnection, migrations: list[MigrationSpec]) -> None:
    migration_map = {m.version: m.checksum for m in migrations}
    rows = con.execute(
        f"SELECT version, migration_name, file_checksum, status FROM {SCHEMA_MIGRATIONS_TABLE}"
    ).fetchall()
    seen_versions: set[str] = set()
    for version, name, checksum, status in rows:
        if version in seen_versions:
            raise RuntimeError(f"duplicated migration version in ledger: {version}")
        seen_versions.add(version)
        if status != "applied":
            raise RuntimeError(f"migration {version} exists in ledger with non-applied status '{status}'")
        expected_checksum = migration_map.get(version)
        if expected_checksum is None:
            raise RuntimeError(f"migration {version} exists in ledger but file is missing from local migrations")
        if checksum != expected_checksum:
            raise RuntimeError(f"migration checksum mismatch for version {version}: expected {expected_checksum}, found {checksum}")
        expected_migration = next((m for m in migrations if m.version == version), None)
        if expected_migration is not None and expected_migration.name != name:
            raise RuntimeError(f"migration name mismatch for version {version}: expected {expected_migration.name}, found {name}")


def _create_ledger_if_missing(con: duckdb.DuckDBPyConnection) -> None:
    if SCHEMA_MIGRATIONS_TABLE in _table_names(con):
        return
    con.execute(
        f"""
        CREATE TABLE {SCHEMA_MIGRATIONS_TABLE} (
            version VARCHAR PRIMARY KEY,
            migration_name VARCHAR NOT NULL,
            file_checksum VARCHAR(64) NOT NULL,
            applied_at TIMESTAMP NOT NULL,
            application_version VARCHAR,
            git_revision VARCHAR,
            run_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL
        )
        """
    )


def _current_git_rev() -> str | None:
    try:
        raw = check_output(["git", "rev-parse", "HEAD"])
        return raw.decode().strip()
    except (OSError, CalledProcessError, FileNotFoundError):
        return None


def _run_id() -> str:
    return uuid4().hex


def _run_migration(con: duckdb.DuckDBPyConnection, migration: MigrationSpec, run_id: str) -> None:
    sql = migration.path.read_text(encoding="utf-8")
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(sql)
        con.execute(
            f"""
            INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (
                version, migration_name, file_checksum, applied_at,
                application_version, git_revision, run_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                migration.version,
                migration.name,
                migration.checksum,
                datetime.now(),
                onejournal_version,
                _current_git_rev(),
                run_id,
                "applied",
            ),
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def apply_schema_migrations(
    db_path: Path,
    *,
    target_version: str | None = None,
    migrations_dir: Path | None = None,
) -> int:
    """Apply journal migrations and return resulting schema version.

    target_version may be set to stop at a specific migration version.
    """
    migrations_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    migrations = _load_migrations(migrations_dir)
    if target_version is None:
        target_version_value = None
    else:
        target_version_value = int(target_version)
        if target_version_value < 1:
            raise ValueError("target_version must be >= 0001")

    con = duckdb.connect(str(db_path))
    try:
        _create_ledger_if_missing(con)
        _validate_applied_migrations(con, migrations)
        _ensure_baseline_tables(con)
        applied = _current_version(con)
        expected_next = 1 if applied == 0 else applied + 1
        run_id_value = _run_id()
        for migration in migrations:
            migration_version = int(migration.version)
            if target_version_value is not None and migration_version > target_version_value:
                break
            if migration.version in {row[0] for row in con.execute(
                f"SELECT version FROM {SCHEMA_MIGRATIONS_TABLE} WHERE status='applied'"
            ).fetchall()}:
                expected_checksum = migration.checksum
                stored_checksum = con.execute(
                    f"SELECT file_checksum FROM {SCHEMA_MIGRATIONS_TABLE} WHERE version = ?",
                    (migration.version,),
                ).fetchone()[0]
                if expected_checksum != stored_checksum:
                    raise RuntimeError(
                        f"checksum mismatch for migration {migration.version}: "
                        f"expected {stored_checksum}, found {expected_checksum}"
                    )
                continue
            if migration_version != expected_next:
                raise RuntimeError(
                    f"migration out of order: expected next migration {expected_next:04d}, got {migration.version}"
                )
            _run_migration(con, migration, run_id=run_id_value)
            expected_next += 1
            if target_version_value is not None and migration_version == target_version_value:
                break
        return _current_version(con)
    finally:
        con.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply OneJournal DuckDB schema migrations.")
    parser.add_argument("--db", required=True, help="DuckDB database path.")
    parser.add_argument("--target-version", default=None, help="Stop after this four-digit migration version.")
    parser.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help="Directory containing migration SQL files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    version = apply_schema_migrations(
        db_path,
        target_version=args.target_version,
        migrations_dir=Path(args.migrations_dir),
    )
    print(f"database version: {version:04d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
