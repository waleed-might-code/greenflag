"""
Provenance at Scale: Performance test for millions of requests.

Tests:
1. Write 1M+ requests with WARC refs
2. Verify deduplication works (duplicate responses share same WARC segment)
3. Verify O(1) lookup performance
4. Generate findings with evidence links
5. Extract evidence on demand for reporting

Target: Handle 1000 requests/second sustained, with <100ms lookup latency.
"""

import asyncio
import hashlib
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from loguru import logger

from cyberAI.storage.provenance_pipeline import (
    ProvenancePipeline, CapturedRequest
)
from cyberAI.storage.database import Severity


class ProvenanceScaleTest:
    """
    Scale test for provenance system.
    
    Simulates a large-scale security scan with:
    - 100k unique endpoints
    - 1M total requests (with duplicates)
    - 10k findings with evidence
    """
    
    def __init__(self, base_dir: str = "outputs/scale_test"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.engagement_id = f"scale_test_{int(time.time())}"
        
        # Test parameters
        self.num_unique_endpoints = 100_000
        self.num_total_requests = 1_000_000
        self.num_findings = 10_000
        
        # Performance metrics
        self.metrics = {
            "write_throughput_rps": 0,
            "dedup_ratio": 0.0,
            "lookup_latency_ms": 0.0,
            "storage_efficiency_mb": 0.0,
        }
    
    def generate_realistic_request(
        self, endpoint_id: int, is_duplicate: bool = False
    ) -> CapturedRequest:
        """Generate a realistic HTTP request/response pair."""
        
        # Simulate different endpoint types
        endpoint_types = [
            ("/api/users/{id}", "GET"),
            ("/api/posts/{id}", "GET"),
            ("/api/comments", "POST"),
            ("/api/orders/{id}", "PUT"),
            ("/api/products", "GET"),
        ]
        
        path_template, method = random.choice(endpoint_types)
        path = path_template.replace("{id}", str(random.randint(1, 10000)))
        url = f"https://target.example.com{path}"
        
        # Request
        request_headers = {
            "User-Agent": "CyberAI/1.0",
            "Accept": "application/json",
            "Authorization": f"Bearer token_{random.randint(1, 100)}",
        }
        
        request_body = b""
        if method == "POST":
            request_body = b'{"data": "test_payload"}'
            request_headers["Content-Type"] = "application/json"
        
        # Response (simulate duplicate responses for dedup testing)
        if is_duplicate:
            # Use a common response body to trigger dedup
            response_body = b'{"status": "success", "data": []}'
        else:
            # Unique response
            response_body = f'{{"id": {endpoint_id}, "data": "unique_{uuid4()}"}}'.encode()
        
        response_headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(response_body)),
        }
        
        return CapturedRequest(
            method=method,
            url=url,
            request_headers=request_headers,
            request_body=request_body,
            status_code=200,
            reason="OK",
            response_headers=response_headers,
            response_body=response_body,
            role=random.choice(["guest", "user", "admin"]),
            engagement_id=self.engagement_id,
            timestamp=datetime.now(timezone.utc),
        )
    
    async def test_write_throughput(self, pipeline: ProvenancePipeline) -> float:
        """
        Test write throughput.
        
        Returns:
            Requests per second
        """
        logger.info(f"Testing write throughput: {self.num_total_requests:,} requests...")
        
        start_time = time.time()
        
        # Write requests in batches
        batch_size = 1000
        num_batches = self.num_total_requests // batch_size
        
        for batch_idx in range(num_batches):
            for i in range(batch_size):
                request_idx = batch_idx * batch_size + i
                
                # 30% of requests are duplicates (same response body)
                is_duplicate = random.random() < 0.3
                
                captured = self.generate_realistic_request(request_idx, is_duplicate)
                pipeline.ingest_request(captured)
            
            # Log progress
            if (batch_idx + 1) % 10 == 0:
                elapsed = time.time() - start_time
                processed = (batch_idx + 1) * batch_size
                rps = processed / elapsed
                logger.info(
                    f"  Progress: {processed:,}/{self.num_total_requests:,} "
                    f"({rps:.0f} req/s)"
                )
        
        # Flush remaining
        pipeline.warc_writer.flush()
        
        elapsed = time.time() - start_time
        rps = self.num_total_requests / elapsed
        
        logger.info(
            f"✓ Write throughput: {rps:.0f} req/s "
            f"({self.num_total_requests:,} requests in {elapsed:.1f}s)"
        )
        
        return rps
    
    def test_deduplication(self, pipeline: ProvenancePipeline) -> float:
        """
        Test deduplication efficiency.
        
        Returns:
            Deduplication ratio (0.0 = no dedup, 1.0 = all deduped)
        """
        logger.info("Testing deduplication...")
        
        stats = pipeline.warc_writer.get_stats()
        records_written = stats["records_written"]
        records_deduped = stats["records_deduped"]
        
        dedup_ratio = records_deduped / self.num_total_requests if self.num_total_requests > 0 else 0.0
        
        logger.info(
            f"✓ Deduplication: {records_deduped:,} / {self.num_total_requests:,} "
            f"({dedup_ratio * 100:.1f}% deduped)"
        )
        
        return dedup_ratio
    
    def test_lookup_performance(self, pipeline: ProvenancePipeline) -> float:
        """
        Test lookup latency.
        
        Returns:
            Average lookup latency in milliseconds
        """
        logger.info("Testing lookup performance...")
        
        # Get sample of request IDs
        sample_size = 1000
        all_requests = pipeline.db.get_requests_by_engagement(self.engagement_id)
        
        if len(all_requests) < sample_size:
            sample_size = len(all_requests)
        
        sample_requests = random.sample(all_requests, sample_size)
        
        # Time lookups
        start_time = time.time()
        
        for req in sample_requests:
            # Lookup by ID (should be O(1))
            result = pipeline.db.get_request_by_id(req.id)
            assert result is not None
        
        elapsed = time.time() - start_time
        avg_latency_ms = (elapsed / sample_size) * 1000
        
        logger.info(
            f"✓ Lookup latency: {avg_latency_ms:.2f}ms average "
            f"({sample_size} lookups in {elapsed:.3f}s)"
        )
        
        return avg_latency_ms
    
    def test_finding_generation(self, pipeline: ProvenancePipeline) -> int:
        """
        Test finding generation with evidence links.
        
        Returns:
            Number of findings created
        """
        logger.info(f"Testing finding generation: {self.num_findings:,} findings...")
        
        all_requests = pipeline.db.get_requests_by_engagement(self.engagement_id)
        
        if len(all_requests) < self.num_findings * 2:
            logger.warning(f"Not enough requests for {self.num_findings} findings")
            return 0
        
        findings_created = 0
        
        for i in range(self.num_findings):
            # Each finding has 2-5 evidence requests
            num_evidence = random.randint(2, 5)
            evidence_requests = random.sample(all_requests, num_evidence)
            evidence_ids = [req.id for req in evidence_requests]
            
            # Create finding
            severity = random.choice(list(Severity))
            
            finding = pipeline.create_finding(
                title=f"Test Finding {i+1}",
                severity=severity,
                category="BOLA",
                description=f"Test finding with {num_evidence} evidence requests",
                asset=evidence_requests[0].url,
                evidence_request_ids=evidence_ids,
                metadata={"test": True, "index": i},
            )
            
            findings_created += 1
            
            if (i + 1) % 1000 == 0:
                logger.info(f"  Created {i+1:,}/{self.num_findings:,} findings")
        
        logger.info(f"✓ Created {findings_created:,} findings with evidence links")
        
        return findings_created
    
    def test_storage_efficiency(self, pipeline: ProvenancePipeline) -> dict:
        """
        Test storage efficiency.
        
        Returns:
            Storage metrics
        """
        logger.info("Testing storage efficiency...")
        
        # Calculate WARC storage size
        warc_dir = self.base_dir / "warc" / self.engagement_id
        warc_size_bytes = sum(f.stat().st_size for f in warc_dir.glob("*.warc.gz"))
        warc_size_mb = warc_size_bytes / (1024 * 1024)
        
        # Calculate DB size
        db_path = self.base_dir / "provenance.db"
        db_size_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0
        
        # Calculate efficiency
        total_size_mb = warc_size_mb + db_size_mb
        bytes_per_request = warc_size_bytes / self.num_total_requests if self.num_total_requests > 0 else 0
        
        logger.info(
            f"✓ Storage: WARC={warc_size_mb:.1f}MB, DB={db_size_mb:.1f}MB, "
            f"Total={total_size_mb:.1f}MB ({bytes_per_request:.0f} bytes/request)"
        )
        
        return {
            "warc_size_mb": warc_size_mb,
            "db_size_mb": db_size_mb,
            "total_size_mb": total_size_mb,
            "bytes_per_request": bytes_per_request,
        }
    
    async def run_full_test(self) -> dict:
        """
        Run complete scale test.
        
        Returns:
            Test results and metrics
        """
        logger.info("=" * 80)
        logger.info("PROVENANCE SCALE TEST")
        logger.info("=" * 80)
        logger.info(f"Engagement: {self.engagement_id}")
        logger.info(f"Target: {self.num_total_requests:,} requests, {self.num_findings:,} findings")
        logger.info("")
        
        # Create pipeline
        pipeline = ProvenancePipeline(
            engagement_id=self.engagement_id,
            warc_base_dir=str(self.base_dir / "warc"),
            db_path=str(self.base_dir / "provenance.db"),
            batch_size=100,  # Batch for performance
            enable_dedup=True,
        )
        
        try:
            # Test 1: Write throughput
            rps = await self.test_write_throughput(pipeline)
            self.metrics["write_throughput_rps"] = rps
            
            # Test 2: Deduplication
            dedup_ratio = self.test_deduplication(pipeline)
            self.metrics["dedup_ratio"] = dedup_ratio
            
            # Test 3: Lookup performance
            latency_ms = self.test_lookup_performance(pipeline)
            self.metrics["lookup_latency_ms"] = latency_ms
            
            # Test 4: Finding generation
            findings_created = self.test_finding_generation(pipeline)
            self.metrics["findings_created"] = findings_created
            
            # Test 5: Storage efficiency
            storage = self.test_storage_efficiency(pipeline)
            self.metrics.update(storage)
            
            # Get final stats
            stats = pipeline.get_stats()
            
            logger.info("")
            logger.info("=" * 80)
            logger.info("TEST RESULTS")
            logger.info("=" * 80)
            logger.info(f"Write Throughput:    {rps:.0f} req/s")
            logger.info(f"Deduplication:       {dedup_ratio * 100:.1f}%")
            logger.info(f"Lookup Latency:      {latency_ms:.2f}ms")
            logger.info(f"Findings Created:    {findings_created:,}")
            logger.info(f"Storage Efficiency:  {storage['bytes_per_request']:.0f} bytes/request")
            logger.info("")
            logger.info("Database Stats:")
            for key, value in stats.items():
                logger.info(f"  {key}: {value}")
            logger.info("=" * 80)
            
            # Verify targets
            success = True
            if rps < 1000:
                logger.warning(f"⚠ Write throughput below target (1000 req/s): {rps:.0f}")
                success = False
            if latency_ms > 100:
                logger.warning(f"⚠ Lookup latency above target (100ms): {latency_ms:.2f}ms")
                success = False
            
            if success:
                logger.info("✓ All performance targets met!")
            
            return {
                "success": success,
                "metrics": self.metrics,
                "stats": stats,
            }
        
        finally:
            pipeline.close()


async def main():
    """Run scale test."""
    test = ProvenanceScaleTest()
    results = await test.run_full_test()
    
    # Save results
    import json
    results_path = test.base_dir / "scale_test_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"Results saved to: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
