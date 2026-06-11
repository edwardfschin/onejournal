#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Schwab orders JSON to OneJournal normalized fills CSV.")
    parser.add_argument("--asof", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    print("===== Schwab orders JSON to normalized fills =====", flush=True)
    print(f"INPUT     : {args.input}", flush=True)
    print(f"OUTPUT    : {args.output}", flush=True)
    print(f"ASOF      : {args.asof}", flush=True)
    print("MODE      : read-only", flush=True)
    print("BROKER API: disabled", flush=True)
    print("ORDER API : disabled", flush=True)
    print("", flush=True)

    t = time.time()
    print("IMPORTING : onejournal.brokers.schwab.orders_json", flush=True)
    from onejournal.brokers.schwab.orders_json import convert_orders_json_to_normalized_csv, validate_asof
    print(f"IMPORT_OK : {round(time.time() - t, 3)} sec", flush=True)

    validate_asof(args.asof)
    stats = convert_orders_json_to_normalized_csv(
        input_path=Path(args.input),
        output_path=Path(args.output),
        asof=args.asof,
    )

    print("")
    print("===== Stats =====")
    stats_dict = stats if isinstance(stats, dict) else vars(stats)
    for k, v in stats_dict.items():
        print(f"{k.upper():24}: {v}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
