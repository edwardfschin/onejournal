from __future__ import annotations

import unittest
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from onejournal.api.app import app
from onejournal.api.contracts import DecimalMetric, PreviewMetadata, QualityState
from onejournal.api.fixtures import build_preview_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = PROJECT_ROOT / "scripts/web/generate_fixture_api_client.py"


class WebApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_preview_is_versioned_deterministic_and_private_safe(self) -> None:
        first = self.client.get("/api/v1/preview")
        second = self.client.get("/api/v1/preview")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        body = first.json()
        self.assertEqual(body["metadata"]["contract_version"], "onejournal.web-fixture.v1")
        self.assertEqual(body["metadata"]["mode"], "demo")
        self.assertEqual(body["metadata"]["generated_at"], "2026-08-31T00:00:00Z")
        self.assertEqual(body["metrics"]["illustrative_net_cashflow"]["value"], "184.50")
        self.assertEqual(body["metrics"]["portfolio_value"]["value"], None)
        self.assertTrue(_response_keys(body).isdisjoint({"account", "account_id", "token", "credential", "raw_path"}))

    def test_openapi_publishes_the_v1_response_contract(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        operation = response.json()["paths"]["/api/v1/preview"]["get"]
        self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/PreviewResponse")

    def test_contract_rejects_non_decimal_and_non_utc_values(self) -> None:
        quality = QualityState(status="demo", reason="fixture")
        with self.assertRaises(ValidationError):
            DecimalMetric(value="184.5 dollars", currency="USD", quality=quality)
        with self.assertRaises(ValidationError):
            DecimalMetric(value="184.50", quality=quality)
        with self.assertRaises(ValidationError):
            PreviewMetadata(
                contract_version="onejournal.web-fixture.v1",
                mode="demo",
                asof="2026-08-31",
                generated_at="2026-08-31T00:00:00+08:00",
                quality=quality,
            )

    def test_fixture_does_not_depend_on_database_or_provider_configuration(self) -> None:
        fixture = build_preview_fixture()

        self.assertEqual(fixture.metadata.mode, "demo")
        self.assertEqual(fixture.metrics["portfolio_value"].quality.status, "unavailable")

    def test_generated_frontend_client_matches_openapi(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def _response_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_response_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_response_keys(item) for item in value))
    return set()


if __name__ == "__main__":
    unittest.main()
