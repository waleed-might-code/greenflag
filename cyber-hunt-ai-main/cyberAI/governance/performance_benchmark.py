"""
Performance benchmark for scope enforcement.
Proves that scope validation doesn't slow the pipeline.

Tests:
1. Raw validation throughput (ops/sec)
2. Cache hit rate impact
3. Comparison: with vs without scope enforcement
4. Concurrent request handling
5. Memory footprint
"""

import asyncio
import time
from statistics import mean, median, stdev
from typing import List

from loguru import logger

from .engagement_config import EngagementConfig
from .scope_enforcing_client import ScopeEnforcingClient
from .scope_validator import ScopeValidator


class PerformanceBenchmark:
    """Benchmark suite for scope enforcement performance."""
    
    def __init__(self):
        self.results = {}
    
    def benchmark_validator_throughput(
        self,
        validator: ScopeValidator,
        test_urls: List[str],
        iterations: int = 10000,
    ) -> dict:
        """
        Measure raw validation throughput.
        
        Target: >100k validations/sec on modern hardware.
        """
        logger.info(f"Benchmarking validator throughput ({iterations} iterations)...")
        
        timings = []
        for _ in range(iterations):
            url = test_urls[_ % len(test_urls)]
            start = time.perf_counter()
            validator.is_in_scope(url, "GET")
            elapsed = time.perf_counter() - start
            timings.append(elapsed)
        
        total_time = sum(timings)
        ops_per_sec = iterations / total_time
        
        return {
            "iterations": iterations,
            "total_time_sec": total_time,
            "ops_per_sec": ops_per_sec,
            "avg_latency_us": mean(timings) * 1_000_000,
            "median_latency_us": median(timings) * 1_000_000,
            "p95_latency_us": sorted(timings)[int(len(timings) * 0.95)] * 1_000_000,
            "p99_latency_us": sorted(timings)[int(len(timings) * 0.99)] * 1_000_000,
            "max_latency_us": max(timings) * 1_000_000,
        }
    
    def benchmark_cache_impact(
        self,
        test_urls: List[str],
        iterations: int = 10000,
    ) -> dict:
        """
        Compare performance with and without cache.
        """
        logger.info("Benchmarking cache impact...")
        
        # Without cache
        validator_no_cache = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=["*/logout", "*/delete/*"],
            allowed_schemes=["https"],
            enable_cache=False,
        )
        
        start = time.perf_counter()
        for i in range(iterations):
            url = test_urls[i % len(test_urls)]
            validator_no_cache.is_in_scope(url, "GET")
        time_no_cache = time.perf_counter() - start
        
        # With cache
        validator_with_cache = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=["*/logout", "*/delete/*"],
            allowed_schemes=["https"],
            enable_cache=True,
            cache_size=1000,
        )
        
        start = time.perf_counter()
        for i in range(iterations):
            url = test_urls[i % len(test_urls)]
            validator_with_cache.is_in_scope(url, "GET")
        time_with_cache = time.perf_counter() - start
        
        cache_stats = validator_with_cache.get_stats()["cache"]
        
        return {
            "iterations": iterations,
            "time_no_cache_sec": time_no_cache,
            "time_with_cache_sec": time_with_cache,
            "speedup_factor": time_no_cache / time_with_cache,
            "cache_hit_rate": cache_stats["hit_rate"],
            "cache_hits": cache_stats["hits"],
            "cache_misses": cache_stats["misses"],
        }

    
    async def benchmark_concurrent_validation(
        self,
        validator: ScopeValidator,
        test_urls: List[str],
        num_workers: int = 100,
        requests_per_worker: int = 100,
    ) -> dict:
        """
        Test concurrent validation performance.
        Simulates multiple crawl workers validating URLs simultaneously.
        """
        logger.info(f"Benchmarking concurrent validation ({num_workers} workers)...")
        
        async def worker(worker_id: int):
            timings = []
            for i in range(requests_per_worker):
                url = test_urls[(worker_id * requests_per_worker + i) % len(test_urls)]
                start = time.perf_counter()
                validator.is_in_scope(url, "GET")
                elapsed = time.perf_counter() - start
                timings.append(elapsed)
            return timings
        
        start = time.perf_counter()
        results = await asyncio.gather(*[worker(i) for i in range(num_workers)])
        total_time = time.perf_counter() - start
        
        all_timings = [t for worker_timings in results for t in worker_timings]
        total_requests = num_workers * requests_per_worker
        
        return {
            "num_workers": num_workers,
            "requests_per_worker": requests_per_worker,
            "total_requests": total_requests,
            "total_time_sec": total_time,
            "throughput_req_per_sec": total_requests / total_time,
            "avg_latency_us": mean(all_timings) * 1_000_000,
            "p95_latency_us": sorted(all_timings)[int(len(all_timings) * 0.95)] * 1_000_000,
            "p99_latency_us": sorted(all_timings)[int(len(all_timings) * 0.99)] * 1_000_000,
        }
    
    async def benchmark_enforcing_client_overhead(
        self,
        config: EngagementConfig,
        test_urls: List[str],
        iterations: int = 1000,
    ) -> dict:
        """
        Measure overhead added by ScopeEnforcingClient vs raw validation.
        
        Target: <10% overhead compared to raw validator.
        """
        logger.info("Benchmarking enforcing client overhead...")
        
        # Raw validator timing
        validator = ScopeValidator(
            target_domains=config.target_domains,
            out_of_scope_patterns=config.out_of_scope_patterns,
            allowed_schemes=config.allowed_schemes,
        )
        
        start = time.perf_counter()
        for i in range(iterations):
            url = test_urls[i % len(test_urls)]
            validator.is_in_scope(url, "GET")
        raw_time = time.perf_counter() - start
        
        # Enforcing client timing (without actual HTTP)
        client = ScopeEnforcingClient(config)
        
        validation_times = []
        for i in range(iterations):
            url = test_urls[i % len(test_urls)]
            start = time.perf_counter()
            try:
                await client._enforce_scope(url, "GET")
            except Exception:
                pass
            validation_times.append(time.perf_counter() - start)
        
        enforcing_time = sum(validation_times)
        overhead_pct = ((enforcing_time - raw_time) / raw_time) * 100
        
        await client.close()
        
        return {
            "iterations": iterations,
            "raw_validator_time_sec": raw_time,
            "enforcing_client_time_sec": enforcing_time,
            "overhead_percent": overhead_pct,
            "avg_latency_us": mean(validation_times) * 1_000_000,
            "passes_target": overhead_pct < 10.0,
        }
