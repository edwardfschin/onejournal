"""Deterministic, non-private fixture data for the first web API contract."""

from __future__ import annotations

from datetime import date, datetime, timezone

from .contracts import DecimalMetric, PreviewMetadata, PreviewResponse, QualityState


def build_preview_fixture() -> PreviewResponse:
    """Return a stable fixture without opening files, databases, or providers."""

    demo_quality = QualityState(
        status="demo",
        reason="Synthetic fixture only; not broker, account, journal, or market data.",
    )
    unavailable_quality = QualityState(
        status="unavailable",
        reason="Portfolio valuation remains blocked pending PNL-03 authority acceptance.",
    )
    return PreviewResponse(
        metadata=PreviewMetadata(
            contract_version="onejournal.web-fixture.v1",
            mode="demo",
            asof=date(2026, 8, 31),
            generated_at=datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc),
            quality=demo_quality,
        ),
        metrics={
            "illustrative_net_cashflow": DecimalMetric(
                value="184.50",
                currency="USD",
                quality=demo_quality,
            ),
            "portfolio_value": DecimalMetric(
                quality=unavailable_quality,
            ),
        },
        notices=[
            "This endpoint is a deterministic demonstration fixture.",
            "No raw evidence, database, credential, or provider connection is used.",
        ],
    )
