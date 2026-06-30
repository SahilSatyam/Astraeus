## YYYY-MM-DD - Rolling Beta Recalculation Bottleneck

**Learning:** Rolling betas for assets vs market (SPY) were computed via a python list comprehension and sequential `np.sum()`, creating a slow $O(N)$ overhead loop in the `task_estimate_betas` function.

**Action:** Replaced the list comprehension with vectorized `np.mean(axis=0)` and matrix dot product `(assets_demean.T @ market_demean)`, reducing operation time substantially without changing precision.
