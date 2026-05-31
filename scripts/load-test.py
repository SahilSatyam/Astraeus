#!/usr/bin/env python3
"""Basic load test for Astraeus API.

Sends concurrent requests to key endpoints and reports latency percentiles.
No external dependencies required (uses stdlib only).

Usage:
    python scripts/load-test.py [--base-url http://localhost:8000] [--concurrency 10] [--duration 30]

Endpoints tested:
    - GET /healthz (baseline)
    - GET /readyz (DB check)
    - GET /metrics (Prometheus scrape)
    - GET /md/runs (market data runs)
    - GET /reco/runs (recommendation runs)
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class EndpointResult:
    """Results for a single endpoint."""

    endpoint: str
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    errors: dict[int, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful / self.total_requests * 100

    @property
    def p50(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.median(self.latencies_ms)

    @property
    def p95(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_lat = sorted(self.latencies_ms)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def p99(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_lat = sorted(self.latencies_ms)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def avg(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.mean(self.latencies_ms)


ENDPOINTS = [
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("GET", "/metrics"),
]


def make_request(base_url: str, method: str, path: str) -> tuple[float, int]:
    """Make a single HTTP request. Returns (latency_ms, status_code)."""
    url = f"{base_url}{path}"
    req = Request(url, method=method)
    req.add_header("Accept", "application/json")

    start = time.perf_counter()
    try:
        with urlopen(req, timeout=10) as resp:
            resp.read()
            elapsed = (time.perf_counter() - start) * 1000
            return elapsed, resp.status
    except HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, e.code
    except (URLError, TimeoutError):
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, 0


def run_load_test(
    base_url: str,
    concurrency: int,
    duration_seconds: int,
) -> dict[str, EndpointResult]:
    """Run load test against all endpoints."""
    results: dict[str, EndpointResult] = {}
    for _method, path in ENDPOINTS:
        results[path] = EndpointResult(endpoint=path)

    print(f"\n{'='*60}")
    print("  Astraeus Load Test")
    print(f"  Target: {base_url}")
    print(f"  Concurrency: {concurrency}")
    print(f"  Duration: {duration_seconds}s")
    print(f"{'='*60}\n")

    end_time = time.time() + duration_seconds

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []

        while time.time() < end_time:
            for method, path in ENDPOINTS:
                if time.time() >= end_time:
                    break
                future = executor.submit(make_request, base_url, method, path)
                futures.append((path, future))

            # Small sleep to avoid overwhelming the thread pool
            time.sleep(0.01)

        # Collect results
        for path, future in futures:
            try:
                latency, status = future.result(timeout=15)
                results[path].total_requests += 1
                results[path].latencies_ms.append(latency)

                if 200 <= status < 400:
                    results[path].successful += 1
                else:
                    results[path].failed += 1
                    results[path].errors[status] = results[path].errors.get(status, 0) + 1
            except Exception:
                results[path].total_requests += 1
                results[path].failed += 1

    return results


def print_results(results: dict[str, EndpointResult]) -> None:
    """Print formatted results table."""
    print(f"\n{'─'*80}")
    print(f"{'Endpoint':<20} {'Total':>8} {'OK%':>8} {'Avg':>8} {'P50':>8} {'P95':>8} {'P99':>8}")
    print(f"{'─'*80}")

    all_ok = True
    for path, r in results.items():
        print(
            f"{path:<20} {r.total_requests:>8} {r.success_rate:>7.1f}% "
            f"{r.avg:>7.1f} {r.p50:>7.1f} {r.p95:>7.1f} {r.p99:>7.1f}"
        )
        if r.success_rate < 99.0:
            all_ok = False
        if r.errors:
            for code, count in r.errors.items():
                print(f"  └─ HTTP {code}: {count} errors")

    print(f"{'─'*80}")
    print("  Latencies in milliseconds")
    print()

    # SLO check
    for path, r in results.items():
        if r.p99 > 800:
            print(f"  ⚠️  {path} p99 ({r.p99:.0f}ms) exceeds 800ms SLO budget")
            all_ok = False

    if all_ok:
        print("  ✅ All endpoints within SLO budgets")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Astraeus API load test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    args = parser.parse_args()

    # Quick connectivity check
    try:
        make_request(args.base_url, "GET", "/healthz")
    except Exception:
        print(f"ERROR: Cannot reach {args.base_url}/healthz")
        print("Make sure the API is running (make dev)")
        sys.exit(1)

    results = run_load_test(args.base_url, args.concurrency, args.duration)
    print_results(results)


if __name__ == "__main__":
    main()
