#!/usr/bin/env python3
"""Backtest CLI — run strategies from the command line.

Usage:
    uv run python scripts/backtest.py run momentum_12_1 --start 2015-01-01 --end 2024-12-31
    uv run python scripts/backtest.py run momentum_12_1 --params '{"top_pct": 0.1}' --engine event_driven
    uv run python scripts/backtest.py list
    uv run python scripts/backtest.py reconcile momentum_12_1 --start 2020-01-01 --end 2024-12-31
    uv run python scripts/backtest.py monte-carlo <run_hash> --paths 1000
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

import structlog

logger = structlog.get_logger("astraeus.backtest.cli")

# Strategy registry (importable strategies)
STRATEGY_REGISTRY: dict[str, type] = {}


def _load_strategies() -> None:
    """Lazy-load all reference strategies into the registry."""
    from astraeus_strategy.strategies.factor_blend import FactorBlend
    from astraeus_strategy.strategies.mean_reversion import MeanReversion5d
    from astraeus_strategy.strategies.ml_forecast import MLForecast
    from astraeus_strategy.strategies.momentum import Momentum12_1
    from astraeus_strategy.strategies.pairs import PairsTrading

    STRATEGY_REGISTRY["momentum_12_1"] = Momentum12_1
    STRATEGY_REGISTRY["mean_reversion_5d"] = MeanReversion5d
    STRATEGY_REGISTRY["pairs_cointegration"] = PairsTrading
    STRATEGY_REGISTRY["factor_blend"] = FactorBlend
    STRATEGY_REGISTRY["ml_xgboost_meta"] = MLForecast


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Astraeus backtest CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run a backtest")
    run_parser.add_argument("strategy", help="Strategy name")
    run_parser.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    run_parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    run_parser.add_argument("--params", type=str, default="{}", help="JSON params")
    run_parser.add_argument(
        "--engine", choices=["vectorized", "event_driven"], default="vectorized"
    )
    run_parser.add_argument("--seed", type=int, default=42)
    run_parser.add_argument("--capital", type=float, default=1_000_000.0)

    # --- list ---
    subparsers.add_parser("list", help="List available strategies")

    # --- reconcile ---
    rec_parser = subparsers.add_parser("reconcile", help="Run reconciliation between engines")
    rec_parser.add_argument("strategy", help="Strategy name")
    rec_parser.add_argument("--start", type=date.fromisoformat, default=date(2020, 1, 1))
    rec_parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    rec_parser.add_argument("--seed", type=int, default=42)

    # --- monte-carlo ---
    mc_parser = subparsers.add_parser("monte-carlo", help="Run Monte Carlo on returns")
    mc_parser.add_argument("strategy", help="Strategy name")
    mc_parser.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    mc_parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    mc_parser.add_argument("--paths", type=int, default=1000)
    mc_parser.add_argument("--seed", type=int, default=42)

    # --- walk-forward ---
    wf_parser = subparsers.add_parser("walk-forward", help="Run walk-forward analysis")
    wf_parser.add_argument("strategy", help="Strategy name")
    wf_parser.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    wf_parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    wf_parser.add_argument("--mode", choices=["anchored", "rolling"], default="anchored")

    return parser.parse_args()


def cmd_list() -> None:
    """List available strategies."""
    _load_strategies()
    print("\nAvailable strategies:")
    print(f"{'Name':<25} {'Version':<10} {'Universe':<15} {'Frequency'}")
    print("-" * 65)
    for _name, cls in sorted(STRATEGY_REGISTRY.items()):
        instance = cls()
        print(
            f"{instance.name:<25} {instance.version:<10} "
            f"{instance.dependencies.universe.name:<15} {instance.dependencies.frequency}"
        )
    print()


def cmd_run(args: argparse.Namespace) -> None:
    """Run a backtest."""
    _load_strategies()

    if args.strategy not in STRATEGY_REGISTRY:
        print(f"ERROR: Unknown strategy '{args.strategy}'", file=sys.stderr)
        print(f"Available: {', '.join(sorted(STRATEGY_REGISTRY.keys()))}", file=sys.stderr)
        sys.exit(1)

    params = json.loads(args.params)
    strategy = STRATEGY_REGISTRY[args.strategy]()

    from astraeus_strategy.types import BacktestConfig

    BacktestConfig(
        strategy_name=args.strategy,
        params=params,
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
        seed=args.seed,
        engine=args.engine,
    )

    print(f"\nRunning backtest: {args.strategy}")
    print(f"  Engine:  {args.engine}")
    print(f"  Range:   {args.start} → {args.end}")
    print(f"  Params:  {params}")
    print(f"  Seed:    {args.seed}")
    print(f"  Capital: ${args.capital:,.0f}")
    print()

    # Note: actual execution requires price data from the database
    # This CLI validates the setup and would connect to the DB in production
    print("Strategy loaded and validated successfully.")
    print(f"  Name:         {strategy.name}")
    print(f"  Version:      {strategy.version}")
    print(f"  Universe:     {strategy.dependencies.universe.name}")
    print(f"  Features:     {[f.name for f in strategy.dependencies.features]}")
    print(f"  Frequency:    {strategy.dependencies.frequency}")
    print(f"  History:      {strategy.dependencies.history_horizon.days} days")
    print()
    print("To execute with data, ensure the database is running and populated.")
    print("  Config hash would be computed from: code + params + data lineage + seed")


def cmd_reconcile(args: argparse.Namespace) -> None:
    """Run reconciliation between engines."""
    _load_strategies()

    if args.strategy not in STRATEGY_REGISTRY:
        print(f"ERROR: Unknown strategy '{args.strategy}'", file=sys.stderr)
        sys.exit(1)

    print(f"\nReconciliation: {args.strategy}")
    print(f"  Range: {args.start} → {args.end}")
    print(f"  Seed:  {args.seed}")
    print()
    print("  Would run both vectorized and event-driven engines")
    print("  and compare metrics within tolerance band:")
    print("    - Annualized return: ≤ 30 bps")
    print("    - Sharpe: ≤ 0.15")
    print("    - Max drawdown: ≤ 100 bps")
    print("    - Turnover: ≤ 5% relative")
    print()
    print("  Requires price data in the database.")


def cmd_monte_carlo(args: argparse.Namespace) -> None:
    """Run Monte Carlo simulation."""
    print(f"\nMonte Carlo: {args.strategy}")
    print(f"  Paths: {args.paths}")
    print(f"  Range: {args.start} → {args.end}")
    print(f"  Seed:  {args.seed}")
    print()
    print("  Would bootstrap returns and report confidence bands.")
    print("  Requires a completed backtest run.")


def cmd_walk_forward(args: argparse.Namespace) -> None:
    """Run walk-forward analysis."""
    from astraeus_strategy.walk_forward import WalkForwardConfig, generate_windows

    config = WalkForwardConfig(mode=args.mode)
    windows = generate_windows(args.start, args.end, config)

    print(f"\nWalk-Forward Analysis: {args.strategy}")
    print(f"  Mode:    {args.mode}")
    print(f"  Range:   {args.start} → {args.end}")
    print(f"  Windows: {len(windows)}")
    print()

    for w in windows:
        print(
            f"  Fold {w.fold_index}: train [{w.train_start} → {w.train_end}] "
            f"val [{w.val_start} → {w.val_end}] "
            f"OOS [{w.oos_start} → {w.oos_end}]"
        )

    print()
    print("  Requires price data in the database for execution.")


def main() -> None:
    args = parse_args()

    if args.command == "list":
        cmd_list()
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "reconcile":
        cmd_reconcile(args)
    elif args.command == "monte-carlo":
        cmd_monte_carlo(args)
    elif args.command == "walk-forward":
        cmd_walk_forward(args)


if __name__ == "__main__":
    main()
