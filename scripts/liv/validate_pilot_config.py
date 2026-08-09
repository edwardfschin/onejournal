#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LIV-02 pilot config contract validator.

Purpose:
    Validate a pilot config artifact against the guarded execution control contract.

Usage:
    python scripts/liv/validate_pilot_config.py --config path/to/pilot.yaml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from datetime import datetime

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


ALLOWED_STATUS = {"disabled", "paper", "live"}
ALLOWED_ENV = {"paper", "live"}
TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OneJournal LIV pilot config.")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the pilot config YAML/JSON file.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as hard failures.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable output.",
    )
    return parser.parse_args(argv)


def parse_datetime_text(value: str | None, *, field: str) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v)
    except ValueError as exc:
        raise ValueError(f"{field}: {value!r} is not a valid ISO-8601 datetime") from exc


def parse_time_text(value: str | None, *, field: str) -> str:
    if not value:
        raise ValueError(f"{field}: missing required time")
    text = value.strip()
    if not TIME_RE.match(text):
        raise ValueError(f"{field}: invalid time {value!r}; expected HH:MM")
    return text


def require_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field}: expected integer, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{field}: expected > 0, got {value}")
    return value


def require_nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field}: expected integer, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field}: expected >= 0, got {value}")
    return value


def require_positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected number, got {type(value).__name__}")
    number = float(value)
    if number <= 0:
        raise ValueError(f"{field}: expected > 0, got {number}")
    return number


def require_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field}: expected non-empty string")
    return text


def require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field}: expected list, got {type(value).__name__}")
    return value


def require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field}: expected mapping, got {type(value).__name__}")
    return value


def validate_pilot_config(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        pilot = require_dict(payload.get("pilot"), "pilot")

        version = pilot.get("version")
        if not isinstance(version, int) or version <= 0:
            raise ValueError("pilot.version: expected positive integer")

        policy_id = require_nonempty_str(pilot.get("policy_id"), "pilot.policy_id")

        status = require_nonempty_str(pilot.get("status"), "pilot.status").lower()
        if status not in ALLOWED_STATUS:
            raise ValueError(f"pilot.status: {status!r} invalid; allowed: {sorted(ALLOWED_STATUS)}")
        environment = require_nonempty_str(pilot.get("environment"), "pilot.environment").lower()
        if environment not in ALLOWED_ENV:
            raise ValueError(f"pilot.environment: {environment!r} invalid; allowed: {sorted(ALLOWED_ENV)}")

        if status == "paper" and environment != "paper":
            raise ValueError("pilot.status=paper requires pilot.environment=paper")
        if status == "live" and environment != "live":
            raise ValueError("pilot.status=live requires pilot.environment=live")

        effective_from_raw = pilot.get("effective_from_utc")
        effective_from = parse_datetime_text(effective_from_raw, field="pilot.effective_from_utc")
        if effective_from is None:
            raise ValueError("pilot.effective_from_utc: required (ISO-8601 UTC timestamp)")

        effective_until_raw = pilot.get("effective_until_utc")
        if effective_until_raw:
            effective_until = parse_datetime_text(effective_until_raw, field="pilot.effective_until_utc")
            if effective_until <= effective_from:
                raise ValueError("pilot.effective_until_utc must be after pilot.effective_from_utc")

        kill_switch_required = pilot.get("kill_switch_required")
        if not isinstance(kill_switch_required, bool):
            raise ValueError("pilot.kill_switch_required: expected boolean")
        if status in {"paper", "live"} and not kill_switch_required:
            raise ValueError("pilot.kill_switch_required must be true for paper/live status")

        force_paper_first = pilot.get("force_paper_first")
        if not isinstance(force_paper_first, bool):
            raise ValueError("pilot.force_paper_first: expected boolean")
        if status == "live" and force_paper_first:
            warnings.append("pilot.force_paper_first should be false while status=live")

        _ = require_nonempty_str(pilot.get("kill_switch_env_var"), "pilot.kill_switch_env_var")

        allow_list = require_dict(pilot.get("allow_list"), "pilot.allow_list")
        accounts = require_list(allow_list.get("accounts"), "pilot.allow_list.accounts")
        symbols = require_list(allow_list.get("symbols"), "pilot.allow_list.symbols")
        strategies = require_list(allow_list.get("strategies"), "pilot.allow_list.strategies")

        if status != "disabled":
            if not accounts:
                raise ValueError("active pilot requires at least one allow-list account")
            if not symbols:
                raise ValueError("active pilot requires at least one allow-list symbol")
            if not strategies:
                raise ValueError("active pilot requires at least one allow-list strategy")

        for index, account in enumerate(accounts, start=1):
            item = require_dict(account, f"pilot.allow_list.accounts[{index}]")
            account_id = require_nonempty_str(item.get("id"), f"pilot.allow_list.accounts[{index}].id")
            _ = require_nonempty_str(item.get("currency"), f"pilot.allow_list.accounts[{index}].currency")
            require_positive_number(item.get("max_notional"), f"pilot.allow_list.accounts[{index}].max_notional")
            require_nonnegative_int(item.get("max_orders_per_day"), f"pilot.allow_list.accounts[{index}].max_orders_per_day")
            require_positive_number(item.get("max_daily_loss_limit"), f"pilot.allow_list.accounts[{index}].max_daily_loss_limit")

            if status == "live" and account_id.upper().startswith("TEST"):
                warnings.append(
                    f"pilot.allow_list.accounts[{index}].id looks like test account while status=live"
                )

        for index, symbol in enumerate(symbols, start=1):
            item = require_dict(symbol, f"pilot.allow_list.symbols[{index}]")
            _ = require_nonempty_str(item.get("symbol"), f"pilot.allow_list.symbols[{index}].symbol")
            require_positive_int(item.get("max_qty"), f"pilot.allow_list.symbols[{index}].max_qty")

        if not all(isinstance(s, str) and s.strip() for s in strategies):
            raise ValueError("pilot.allow_list.strategies: every item must be a non-empty string")

        risk_limits = require_dict(pilot.get("risk_limits"), "pilot.risk_limits")
        require_positive_number(risk_limits.get("max_notional_per_order"), "pilot.risk_limits.max_notional_per_order")
        require_positive_number(risk_limits.get("max_notional_daily"), "pilot.risk_limits.max_notional_daily")
        require_positive_int(risk_limits.get("max_quantity_per_order"), "pilot.risk_limits.max_quantity_per_order")
        require_positive_number(
            risk_limits.get("max_position_delta_notional"),
            "pilot.risk_limits.max_position_delta_notional",
        )
        if not isinstance(risk_limits.get("min_market_hours_only"), bool):
            raise ValueError("pilot.risk_limits.min_market_hours_only: expected boolean")

        allowed_sessions = risk_limits.get("allowed_sessions")
        if not isinstance(allowed_sessions, list) or not all(
            isinstance(session, str) and session.strip() for session in allowed_sessions
        ):
            raise ValueError("pilot.risk_limits.allowed_sessions: expected non-empty list of strings")
        if not allowed_sessions:
            raise ValueError("pilot.risk_limits.allowed_sessions: at least one session is required")

        schedule = require_dict(pilot.get("schedule"), "pilot.schedule")
        timezone = require_nonempty_str(schedule.get("timezone"), "pilot.schedule.timezone")
        if timezone.upper() not in {"AMERICA/NEW_YORK", "ASIA/SINGAPORE", "UTC"}:
            raise ValueError("pilot.schedule.timezone: expected IANA timezone such as UTC, America/New_York, Asia/Singapore")

        windows = require_list(schedule.get("enabled_windows_utc"), "pilot.schedule.enabled_windows_utc")
        if not windows:
            raise ValueError("pilot.schedule.enabled_windows_utc: at least one UTC window is required")
        for index, win in enumerate(windows, start=1):
            item = require_dict(win, f"pilot.schedule.enabled_windows_utc[{index}]")
            start = parse_time_text(item.get("start_time"), field=f"pilot.schedule.enabled_windows_utc[{index}].start_time")
            end = parse_time_text(item.get("end_time"), field=f"pilot.schedule.enabled_windows_utc[{index}].end_time")
            if start == end:
                raise ValueError(
                    f"pilot.schedule.enabled_windows_utc[{index}]: start_time and end_time cannot be identical"
                )
            if item.get("allow") is not None and not isinstance(item.get("allow"), bool):
                raise ValueError(
                    f"pilot.schedule.enabled_windows_utc[{index}].allow: expected boolean"
                )

        controls = require_dict(pilot.get("controls"), "pilot.controls")
        duplicate_prevention = require_dict(
            controls.get("duplicate_prevention"),
            "pilot.controls.duplicate_prevention",
        )
        if not isinstance(duplicate_prevention.get("require_idempotency_key"), bool):
            raise ValueError("pilot.controls.duplicate_prevention.require_idempotency_key: expected boolean")
        require_nonnegative_int(
            duplicate_prevention.get("duplicate_tolerance_seconds"),
            "pilot.controls.duplicate_prevention.duplicate_tolerance_seconds",
        )

        approvals = require_dict(controls.get("approvals"), "pilot.controls.approvals")
        if not isinstance(approvals.get("requires_two_step_approval"), bool):
            raise ValueError("pilot.controls.approvals.requires_two_step_approval: expected boolean")
        require_positive_int(approvals.get("default_ttl_minutes"), "pilot.controls.approvals.default_ttl_minutes")

        if status == "live" and not policy_id.lower().startswith("liv-pilot-"):
            warnings.append("live status should use policy_id with liv-pilot-* prefix")

    except ValueError as exc:
        errors.append(str(exc))

    return errors, warnings


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is not installed. Install dependency pyyaml.")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("config payload must be a YAML/JSON object")
    return data


def run_validation(path: Path, strict: bool, emit_json: bool) -> int:
    try:
        payload = load_config(path)
        errors, warnings = validate_pilot_config(payload)
    except Exception as exc:  # pragma: no cover - robust user-facing error path
        if emit_json:
            print(json.dumps({"status": "failed", "errors": [str(exc)], "warnings": []}, ensure_ascii=False))
        else:
            print(f"ERROR: {exc}")
        return 1

    if emit_json:
        print(
            json.dumps(
                {
                    "status": "ok" if not errors else "failed",
                    "errors": errors,
                    "warnings": warnings,
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"Validating: {path}")
        if errors:
            print("STATUS: failed")
            for issue in errors:
                print(f"- {issue}")
            return 1
        if warnings and strict:
            print("STATUS: failed (strict)")
            for issue in warnings:
                print(f"- {issue}")
            return 1
        print("STATUS: OK")

    if warnings and strict:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_validation(Path(args.config).expanduser(), strict=args.strict, emit_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
