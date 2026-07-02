## YYYY-MM-DD - Rolling Beta Recalculation Bottleneck

**Learning:** Rolling betas for assets vs market (SPY) were computed via a python list comprehension and sequential `np.sum()`, creating a slow $O(N)$ overhead loop in the `task_estimate_betas` function.

**Action:** Replaced the list comprehension with vectorized `np.mean(axis=0)` and matrix dot product `(assets_demean.T @ market_demean)`, reducing operation time substantially without changing precision.

## YYYY-MM-DD - Vectorized Engine Return Computation Bottleneck

**Learning:** `_compute_day_return` in `VectorizedEngine` performed `O(N)` Polars filter and `.item()` operations inside a loop over all target symbols, leading to extremely slow execution during backtests (nearly 50s for 1-year backtest on 100 symbols).

**Action:** Replaced repetitive Polars frame filtering with `iter_rows()` and built dictionaries out of the loop for `O(1)` row access. Execution time dropped by >95% (~50s -> ~2s) while producing the exact same Sharpe ratio and backtest metrics.
