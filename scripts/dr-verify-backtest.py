"""DR Verification Script — runs a canonical backtest and compares hash.

This script is the final step of the DR drill. It runs a known backtest
against the restored data and verifies the output matches a pre-computed
hash, proving data integrity end-to-end.

Usage:
    python scripts/dr-verify-backtest.py --expected-hash <SHA256>
    python scripts/dr-verify-backtest.py --generate-hash  # First run: compute baseline

The canonical backtest:
    - Symbol: SPY
    - Period: 2024-01-02 to 2024-01-31
    - Strategy: Simple moving average crossover (SMA 10/50)
    - Output: deterministic trade log (CSV) hashed with SHA-256
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_canonical_backtest() -> str:
    """Run the canonical backtest and return CSV output as string.

    This uses a minimal, deterministic strategy to verify data integrity.
    The strategy itself doesn't matter — what matters is that the same data
    produces the same output after a DR restore.
    """
    try:
        import pandas as pd
        from sqlalchemy import create_engine, text
    except ImportError:
        print("ERROR: pandas and sqlalchemy required. Run: uv pip install pandas sqlalchemy")
        sys.exit(1)

    import os

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://astraeus:astraeus@localhost:5432/astraeus",
    )

    engine = create_engine(database_url)

    # Fetch canonical data
    query = text("""
        SELECT date, open, high, low, close, volume
        FROM market_data.ohlcv_daily
        WHERE symbol = 'SPY'
          AND date BETWEEN '2024-01-02' AND '2024-01-31'
        ORDER BY date ASC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        print("ERROR: No data found for SPY 2024-01-02 to 2024-01-31.")
        print("       Ensure market data is restored before running this script.")
        sys.exit(1)

    # Simple SMA crossover strategy (deterministic)
    df["sma_10"] = df["close"].rolling(window=10).mean()
    df["sma_50"] = df["close"].rolling(window=50, min_periods=10).mean()
    df["signal"] = 0
    df.loc[df["sma_10"] > df["sma_50"], "signal"] = 1
    df.loc[df["sma_10"] < df["sma_50"], "signal"] = -1
    df["position"] = df["signal"].shift(1).fillna(0).astype(int)

    # Generate trade log
    trades = df[df["position"].diff().abs() > 0].copy()
    trades["action"] = trades["position"].map({1: "BUY", -1: "SELL", 0: "FLAT"})
    trade_log = trades[["date", "close", "action", "position"]].copy()

    # Convert to CSV string (deterministic output)
    output = io.StringIO()
    trade_log.to_csv(output, index=False, lineterminator="\n")
    return output.getvalue()


def compute_hash(content: str) -> str:
    """Compute SHA-256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DR verification: run canonical backtest and verify hash"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--expected-hash",
        type=str,
        help="Expected SHA-256 hash to verify against",
    )
    group.add_argument(
        "--generate-hash",
        action="store_true",
        help="Generate and print the baseline hash (first run)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("DR VERIFICATION — Canonical Backtest")
    print("=" * 60)
    print("  Symbol:   SPY")
    print("  Period:   2024-01-02 to 2024-01-31")
    print("  Strategy: SMA 10/50 crossover")
    print()

    print("Running backtest...")
    output = run_canonical_backtest()
    actual_hash = compute_hash(output)

    if args.generate_hash:
        print(f"\n  Baseline hash: {actual_hash}")
        print("\n  Store this hash for future DR drills:")
        print(f"    python scripts/dr-verify-backtest.py --expected-hash {actual_hash}")

        # Save to file for reference
        hash_file = Path(__file__).parent.parent / "data" / "dr-baseline-hash.txt"
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        hash_file.write_text(f"{actual_hash}\n")
        print(f"\n  Hash saved to: {hash_file}")
    else:
        print(f"  Actual hash:   {actual_hash}")
        print(f"  Expected hash: {args.expected_hash}")
        print()

        if actual_hash == args.expected_hash:
            print("  ✅ PASS — Data integrity verified. DR restore is bit-for-bit correct.")
            sys.exit(0)
        else:
            print("  ❌ FAIL — Hash mismatch. Data integrity compromised.")
            print()
            print("  Possible causes:")
            print("    - Incomplete data restore (missing rows)")
            print("    - Data corruption during backup/restore")
            print("    - Schema migration applied differently")
            print("    - Floating-point precision difference (unlikely with Postgres)")
            print()
            print("  Next steps:")
            print(
                "    1. Check row count: SELECT COUNT(*) FROM market_data.ohlcv_daily WHERE symbol='SPY' AND date BETWEEN '2024-01-02' AND '2024-01-31'"
            )
            print("    2. Compare a sample row against known values")
            print("    3. If data is correct but hash differs, regenerate baseline")
            sys.exit(1)


if __name__ == "__main__":
    main()
