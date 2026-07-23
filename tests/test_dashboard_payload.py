from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.dashboard.payload import build_dashboard_payload
from onejournal.journal.episodes import build_episode_previews_from_fills
from onejournal.journal.reviews import ManualReview


PROJECT_DIR = Path(__file__).resolve().parents[1]
FILLS_FIXTURE = PROJECT_DIR / "docs/examples/manual_csv/fills_template.csv"


class DashboardPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.episodes = build_episode_previews_from_fills(parse_manual_fills_csv(FILLS_FIXTURE))

    def test_payload_is_deterministic_and_read_only(self) -> None:
        generated_at = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
        reviewed_uid = "manual_csv:DEMO_ACCOUNT:option:AAPL_SELL_PUT_001"
        reviews = {
            reviewed_uid: ManualReview(
                episode_uid=reviewed_uid,
                review_status="reviewed",
                setup_quality="good",
                entry_reason="Contract test",
                notes="No broker action",
            )
        }

        payload = build_dashboard_payload(
            asof=date(2026, 6, 2),
            episodes=self.episodes,
            generated_at=generated_at,
            reviews=reviews,
        )

        self.assertEqual(payload["metadata"]["asof"], "2026-06-02")
        self.assertEqual(payload["metadata"]["generated_at"], generated_at.isoformat())
        self.assertEqual(payload["metadata"]["mode"], "read_only")
        self.assertEqual(payload["metadata"]["auto_trade"], "disabled")
        self.assertEqual(payload["metadata"]["record_counts"]["trade_episode_previews"], 8)
        self.assertEqual(payload["trade_summary"]["gross_cashflow"], "-10415.00")
        self.assertEqual(payload["trade_summary"]["commission"], "6.50")
        self.assertEqual(payload["trade_summary"]["fees"], "0.52")
        self.assertEqual(payload["open_positions"], [])
        self.assertEqual(payload["metrics_by_strategy"], [])

        reviewed = next(row for row in payload["recent_trade_episodes"] if row["episode_uid"] == reviewed_uid)
        self.assertEqual(reviewed["review_status"], "reviewed")
        self.assertEqual(reviewed["setup_quality"], "good")
        self.assertEqual(reviewed["entry_reason"], "Contract test")

    def test_empty_payload_has_explicit_zero_state(self) -> None:
        payload = build_dashboard_payload(asof=date(2026, 6, 2), episodes=[])
        self.assertEqual(payload["trade_summary"]["gross_cashflow"], "0")
        self.assertEqual(payload["recent_trade_episodes"], [])
        self.assertEqual(payload["metadata"]["record_counts"]["trade_episode_previews"], 0)


if __name__ == "__main__":
    unittest.main()
