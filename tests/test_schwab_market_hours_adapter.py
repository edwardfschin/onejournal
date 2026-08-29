from __future__ import annotations

from copy import deepcopy
from datetime import date
import unittest

from onejournal.brokers.schwab.market_hours_json import (
    SchwabMarketHoursAdapterError,
    market_hours_from_payload,
)


NORMAL_DATE = date(2026, 8, 31)


def normal_payload() -> dict:
    return {
        "equity": {
            "EQ": {
                "date": "2026-08-31",
                "marketType": "EQUITY",
                "product": "EQ",
                "productName": "equity",
                "isOpen": True,
                "sessionHours": {
                    "preMarket": [
                        {
                            "start": "2026-08-31T07:00:00-04:00",
                            "end": "2026-08-31T09:30:00-04:00",
                        }
                    ],
                    "regularMarket": [
                        {
                            "start": "2026-08-31T09:30:00-04:00",
                            "end": "2026-08-31T16:00:00-04:00",
                        }
                    ],
                    "postMarket": [
                        {
                            "start": "2026-08-31T16:00:00-04:00",
                            "end": "2026-08-31T20:00:00-04:00",
                        }
                    ],
                },
            }
        },
        "option": {
            "EQO": {
                "date": "2026-08-31",
                "marketType": "OPTION",
                "product": "EQO",
                "productName": "equity option",
                "isOpen": True,
                "sessionHours": {
                    "regularMarket": [
                        {
                            "start": "2026-08-31T09:30:00-04:00",
                            "end": "2026-08-31T16:00:00-04:00",
                        }
                    ]
                },
            },
            "IND": {
                "date": "2026-08-31",
                "marketType": "OPTION",
                "product": "IND",
                "productName": "index option",
                "isOpen": True,
                "sessionHours": {
                    "regularMarket": [
                        {
                            "start": "2026-08-31T09:30:00-04:00",
                            "end": "2026-08-31T16:15:00-04:00",
                        }
                    ]
                },
            },
        },
    }


def closed_payload() -> dict:
    return {
        "equity": {
            "equity": {
                "date": "2026-09-07",
                "marketType": "EQUITY",
                "product": "equity",
                "isOpen": False,
            }
        },
        "option": {
            "option": {
                "date": "2026-09-07",
                "marketType": "OPTION",
                "product": "option",
                "isOpen": False,
            }
        },
    }


class SchwabMarketHoursAdapterTests(unittest.TestCase):
    def test_open_response_preserves_products_phases_and_offsets(self) -> None:
        response = market_hours_from_payload(
            normal_payload(),
            expected_date=NORMAL_DATE,
        )

        equity = response.product(provider_market="equity", product_code="EQ")
        equity_option = response.product(
            provider_market="option",
            product_code="EQO",
        )

        self.assertTrue(equity.is_open)
        self.assertFalse(equity.is_closed_sentinel)
        self.assertEqual(
            [phase.market_session for phase in equity.phases],
            ["pre_market", "regular", "after_hours"],
        )
        self.assertEqual(
            equity.phases[1].started_at.utcoffset().total_seconds(),
            -4 * 60 * 60,
        )
        self.assertEqual(
            [phase.market_session for phase in equity_option.phases],
            ["regular"],
        )

    def test_closed_response_preserves_unspecified_closed_sentinel(self) -> None:
        response = market_hours_from_payload(
            closed_payload(),
            expected_date=date(2026, 9, 7),
        )

        equity = response.product(provider_market="equity", product_code="EQ")
        equity_option = response.product(
            provider_market="option",
            product_code="EQO",
        )

        for product in (equity, equity_option):
            self.assertFalse(product.is_open)
            self.assertTrue(product.is_closed_sentinel)
            self.assertEqual(product.phases, ())
            self.assertIsNone(product.product_name)

    def test_early_close_boundary_is_preserved_without_classification(self) -> None:
        payload = normal_payload()
        for products in payload.values():
            for item in products.values():
                item["date"] = "2026-11-27"
                for intervals in item["sessionHours"].values():
                    for interval in intervals:
                        interval["start"] = interval["start"].replace(
                            "2026-08-31", "2026-11-27"
                        ).replace("-04:00", "-05:00")
                        interval["end"] = interval["end"].replace(
                            "2026-08-31", "2026-11-27"
                        ).replace("-04:00", "-05:00")
        payload["equity"]["EQ"]["sessionHours"]["regularMarket"][0]["end"] = (
            "2026-11-27T13:00:00-05:00"
        )
        payload["equity"]["EQ"]["sessionHours"]["postMarket"][0] = {
            "start": "2026-11-27T13:00:00-05:00",
            "end": "2026-11-27T17:00:00-05:00",
        }
        payload["option"]["EQO"]["sessionHours"]["regularMarket"][0]["end"] = (
            "2026-11-27T13:00:00-05:00"
        )
        payload["option"]["IND"]["sessionHours"]["regularMarket"][0]["end"] = (
            "2026-11-27T13:15:00-05:00"
        )

        response = market_hours_from_payload(
            payload,
            expected_date=date(2026, 11, 27),
        )
        regular = response.product(
            provider_market="equity",
            product_code="EQ",
        ).phases[1]

        self.assertEqual(regular.ended_at.hour, 13)
        self.assertEqual(regular.ended_at.utcoffset().total_seconds(), -5 * 60 * 60)

    def test_scope_identity_date_and_closed_shape_fail_closed(self) -> None:
        cases = []

        missing_market = normal_payload()
        missing_market.pop("option")
        cases.append(missing_market)

        wrong_product = normal_payload()
        wrong_product["option"]["EQO"]["product"] = "IND"
        cases.append(wrong_product)

        naive_time = normal_payload()
        naive_time["equity"]["EQ"]["sessionHours"]["regularMarket"][0][
            "start"
        ] = "2026-08-31T09:30:00"
        cases.append(naive_time)

        malformed_closed = closed_payload()
        malformed_closed["equity"]["equity"]["productName"] = "invented"
        cases.append(malformed_closed)

        mixed = closed_payload()
        mixed["option"] = deepcopy(normal_payload()["option"])
        for item in mixed["option"].values():
            item["date"] = "2026-09-07"
            for intervals in item["sessionHours"].values():
                for interval in intervals:
                    interval["start"] = interval["start"].replace(
                        "2026-08-31", "2026-09-07"
                    )
                    interval["end"] = interval["end"].replace(
                        "2026-08-31", "2026-09-07"
                    )
        cases.append(mixed)

        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(SchwabMarketHoursAdapterError):
                    market_hours_from_payload(
                        payload,
                        expected_date=(
                            date(2026, 9, 7)
                            if payload is malformed_closed or payload is mixed
                            else NORMAL_DATE
                        ),
                    )

    def test_overlapping_or_unknown_session_phase_fails_closed(self) -> None:
        overlap = normal_payload()
        overlap["equity"]["EQ"]["sessionHours"]["regularMarket"][0][
            "start"
        ] = "2026-08-31T09:00:00-04:00"
        unknown = normal_payload()
        unknown["equity"]["EQ"]["sessionHours"]["overnight"] = [
            {
                "start": "2026-08-31T00:00:00-04:00",
                "end": "2026-08-31T06:00:00-04:00",
            }
        ]

        for payload in (overlap, unknown):
            with self.subTest(payload=payload):
                with self.assertRaises(SchwabMarketHoursAdapterError):
                    market_hours_from_payload(payload, expected_date=NORMAL_DATE)


if __name__ == "__main__":
    unittest.main()
