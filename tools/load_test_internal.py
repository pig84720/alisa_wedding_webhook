"""
tools/load_test_internal.py — 內部壓測腳本

用途：
1. 對受保護的 /internal/diagnostics/load-probe 發送併發請求
2. 測量 p50 / p95 / p99 latency、錯誤率與成功率
3. 避免直接打真實 LINE Reply API

範例：
    python tools/load_test_internal.py \
      --base-url https://your-app.azurewebsites.net \
      --token your-diagnostic-token \
      --scenario seat_lookup \
      --concurrency 100 \
      --requests 300
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass

import aiohttp


@dataclass
class RequestResult:
    ok: bool
    status_code: int | None
    elapsed_ms: float
    error: str | None = None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * p)
    return ordered[index]


async def hit_endpoint(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
) -> RequestResult:
    started_at = time.monotonic()
    try:
        async with session.get(url, headers=headers, params=params) as response:
            await response.read()
            elapsed_ms = (time.monotonic() - started_at) * 1000
            return RequestResult(
                ok=response.status == 200,
                status_code=response.status,
                elapsed_ms=elapsed_ms,
                error=None if response.status == 200 else f"HTTP {response.status}",
            )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - started_at) * 1000
        return RequestResult(
            ok=False,
            status_code=None,
            elapsed_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_load_test(args: argparse.Namespace) -> list[RequestResult]:
    url = f"{args.base_url.rstrip('/')}/internal/diagnostics/load-probe"
    headers = {"X-Diagnostic-Token": args.token}
    params = {
        "scenario": args.scenario,
        "query_name": args.query_name,
    }
    timeout = aiohttp.ClientTimeout(total=args.timeout_seconds)
    connector = aiohttp.TCPConnector(limit=max(args.concurrency, 1))
    semaphore = asyncio.Semaphore(args.concurrency)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async def bounded_request() -> RequestResult:
            async with semaphore:
                return await hit_endpoint(session, url, headers, params)

        tasks = [asyncio.create_task(bounded_request()) for _ in range(args.requests)]
        return await asyncio.gather(*tasks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Internal load test for App Service diagnostics endpoint.")
    parser.add_argument("--base-url", required=True, help="例如 https://alisa-wedding-2.azurewebsites.net")
    parser.add_argument("--token", required=True, help="DIAGNOSTIC_TOKEN")
    parser.add_argument(
        "--scenario",
        choices=["settings_read", "seat_lookup"],
        default="seat_lookup",
        help="settings_read 較輕；seat_lookup 較接近桌號查詢壓力。",
    )
    parser.add_argument("--query-name", default="王小明", help="seat_lookup 模擬查詢用姓名")
    parser.add_argument("--concurrency", type=int, default=50, help="同時併發數")
    parser.add_argument("--requests", type=int, default=200, help="總請求數")
    parser.add_argument("--timeout-seconds", type=float, default=15.0, help="單請求 timeout")
    return parser.parse_args()


def print_summary(results: list[RequestResult]) -> None:
    latencies = [result.elapsed_ms for result in results]
    successes = [result for result in results if result.ok]
    failures = [result for result in results if not result.ok]

    print("=== Load Test Summary ===")
    print(f"total_requests: {len(results)}")
    print(f"successes: {len(successes)}")
    print(f"failures: {len(failures)}")
    print(f"success_rate: {len(successes) / len(results) * 100:.1f}%")
    print(f"avg_ms: {statistics.fmean(latencies):.1f}")
    print(f"p50_ms: {percentile(latencies, 0.50):.1f}")
    print(f"p95_ms: {percentile(latencies, 0.95):.1f}")
    print(f"p99_ms: {percentile(latencies, 0.99):.1f}")

    if failures:
        print("\n=== Sample Failures ===")
        for result in failures[:10]:
            print(
                f"status={result.status_code} elapsed_ms={result.elapsed_ms:.1f} error={result.error}"
            )


def main() -> None:
    args = parse_args()
    results = asyncio.run(run_load_test(args))
    print_summary(results)


if __name__ == "__main__":
    main()
