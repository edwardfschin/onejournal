from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from fastapi.testclient import TestClient

from onejournal.api.app import app as demo_app
from onejournal.api.broker_current_position_contracts import (
    BROKER_CURRENT_FINANCIAL_RELEASE_AUTHORIZATION_VERSION,
    BrokerCurrentApiContractError,
    BrokerCurrentFinancialReleaseAuthorization,
    load_broker_current_financial_release_authorization,
)
from onejournal.api.local_owner_journal import (
    LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH,
    create_local_owner_journal_app,
)
from onejournal.instruments import InstrumentIdentity
from onejournal.journal.broker_current_position_valuation_repository import (
    calculate_broker_current_position_result_fingerprint,
    persist_broker_current_position_valuation_run,
)
from onejournal.pnl.broker_current_position_valuation import (
    build_broker_current_position_valuation,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)
from scripts.journal.init_journal_db import init_schema


class LocalOwnerPortfolioApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.db_path = self.root / "journal.duckdb"
        init_schema(self.db_path)
        self.db_path.chmod(0o600)
        self.evaluated_at = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)

        positions = []
        for index in range(58):
            tax_lot_average = Decimal("100") + Decimal(index)
            market_value = tax_lot_average + Decimal("10")
            positions.append(
                BrokerPositionRecord(
                    identity=InstrumentIdentity(
                        asset_class="equity",
                        market_scope="US",
                        currency="USD",
                        symbol=f"S{index:02d}",
                    ),
                    quantity=Decimal("1"),
                    broker_market_value=market_value,
                    broker_unrealized_pnl=Decimal("10"),
                    broker_tax_lot_average_price=tax_lot_average,
                )
            )
        self.snapshot = BrokerPositionSnapshot(
            snapshot_uid="broker-position-snapshot:" + "a" * 64,
            source_broker="schwab",
            connection_uid="connection:synthetic-private",
            source_account_id="account:synthetic-should-not-leak",
            asof=date(2026, 9, 4),
            retrieved_at=self.evaluated_at,
            raw_path="private/synthetic/positions.json",
            raw_sha256="b" * 64,
            account_complete=True,
            adapter_version="schwab-position-json-v3",
            positions=tuple(positions),
        )
        self.run = build_broker_current_position_valuation(
            broker_snapshot=self.snapshot,
            evaluated_at=self.evaluated_at,
            max_snapshot_age_seconds=0,
            currency_quantum_by_currency={"USD": Decimal("0.01")},
        )
        persist_broker_current_position_valuation_run(
            self.db_path,
            run=self.run,
            broker_snapshot=self.snapshot,
        )
        self.authorization = BrokerCurrentFinancialReleaseAuthorization(
            owner_acceptance_uid="owner-acceptance:synthetic",
            valuation_run_uid=self.run.run_uid,
            result_fingerprint=(
                calculate_broker_current_position_result_fingerprint(self.run)
            ),
            accepted_at=self.evaluated_at,
        )

    def test_exact_owner_accepted_58_position_result_is_exposed_and_audited(
        self,
    ) -> None:
        client = TestClient(
            create_local_owner_journal_app(
                journal_db_path=self.db_path,
                broker_current_authorization=self.authorization,
            )
        )

        response = client.get(LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["metadata"]["contract_version"],
            "onejournal.api.broker-current-position-valuation.v1",
        )
        self.assertEqual(body["metadata"]["release_status"], "owner_accepted")
        self.assertEqual(
            body["metadata"]["owner_accepted_at"],
            "2026-09-04T20:00:00Z",
        )
        self.assertEqual(body["metadata"]["asof"], "2026-09-04")
        self.assertEqual(body["counts"]["position_count"], 58)
        self.assertEqual(body["counts"]["cost_basis_available_count"], 58)
        self.assertEqual(body["counts"]["market_value_available_count"], 58)
        self.assertEqual(body["counts"]["unrealized_pnl_available_count"], 58)
        self.assertEqual(len(body["positions"]), 58)
        self.assertTrue(body["complete_portfolio_cost_basis_available"])
        self.assertTrue(body["complete_portfolio_market_value_available"])
        self.assertTrue(body["complete_portfolio_unrealized_pnl_available"])
        self.assertTrue(
            all(item["position_status"] == "available" for item in body["positions"])
        )
        serialized = json.dumps(body, sort_keys=True)
        self.assertNotIn("account:synthetic-should-not-leak", serialized)
        self.assertNotIn("connection:synthetic-private", serialized)
        self.assertNotIn("private/synthetic/positions.json", serialized)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            audit = con.execute(
                """SELECT action, valuation_run_uid, result_fingerprint,
                          owner_acceptance_uid, outcome,
                          request_sha256
                   FROM local_owner_financial_api_audit_events"""
            ).fetchall()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0][0], "broker_current_portfolio_read")
        self.assertEqual(audit[0][1], self.run.run_uid)
        self.assertEqual(audit[0][2], self.authorization.result_fingerprint)
        self.assertEqual(audit[0][3], self.authorization.owner_acceptance_uid)
        self.assertEqual(audit[0][4], "accepted")
        self.assertEqual(len(audit[0][5]), 64)

    def test_route_is_unavailable_without_process_start_authorization(self) -> None:
        client = TestClient(
            create_local_owner_journal_app(journal_db_path=self.db_path)
        )

        response = client.get(LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "broker-current portfolio is unavailable"},
        )

    def test_mismatched_or_missing_accepted_run_fails_at_process_start(self) -> None:
        wrong_fingerprint = self.authorization.model_copy(
            update={"result_fingerprint": "0" * 64}
        )
        with self.assertRaisesRegex(ValueError, "does not match persisted state"):
            create_local_owner_journal_app(
                journal_db_path=self.db_path,
                broker_current_authorization=wrong_fingerprint,
            )

        missing_run = self.authorization.model_copy(
            update={"valuation_run_uid": "broker-current-position-valuation:missing"}
        )
        with self.assertRaisesRegex(ValueError, "run is unavailable"):
            create_local_owner_journal_app(
                journal_db_path=self.db_path,
                broker_current_authorization=missing_run,
            )

    def test_authorization_loader_requires_exact_document_and_private_permissions(
        self,
    ) -> None:
        authorization_path = self.root / "financial-release-authorization.json"
        authorization_path.write_text(
            json.dumps(
                {
                    "contract_version": (
                        BROKER_CURRENT_FINANCIAL_RELEASE_AUTHORIZATION_VERSION
                    ),
                    "owner_acceptance_uid": "owner-acceptance:synthetic",
                    "valuation_run_uid": self.run.run_uid,
                    "result_fingerprint": self.authorization.result_fingerprint,
                    "accepted_at": "2026-09-04T20:00:00Z",
                    "decision": "accepted",
                    "accepted_scope": "broker_reconciled_current_position",
                    "approval_source": "project_owner_explicit_proceed",
                    "fifo_history_reinterpreted": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        authorization_path.chmod(0o600)

        loaded = load_broker_current_financial_release_authorization(
            authorization_path
        )

        self.assertEqual(loaded, self.authorization)
        authorization_path.chmod(0o644)
        with self.assertRaisesRegex(BrokerCurrentApiContractError, "mode 0600"):
            load_broker_current_financial_release_authorization(
                authorization_path
            )
        authorization_path.chmod(0o600)
        symlink_path = self.root / "authorization-link.json"
        symlink_path.symlink_to(authorization_path)
        with self.assertRaisesRegex(BrokerCurrentApiContractError, "symlink"):
            load_broker_current_financial_release_authorization(symlink_path)

    def test_demo_fixture_app_never_registers_local_owner_portfolio(self) -> None:
        self.assertEqual(
            TestClient(demo_app).get(LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH).status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
