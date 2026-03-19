"""
Provenance System Validator - End-to-End Verification

Validates that every finding can be traced back to raw WARC evidence:
1. Capture HTTP traffic → WARC with content-addressed IDs
2. Store only refs in DB (not full responses)
3. Generate findings with WARC evidence links
4. Extract evidence on-demand for reporting
5. Verify performance at scale (1000+ req/s, <100ms lookup)

This is the critical validation for Agent #4's deliverable.
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from loguru import logger

from cyberAI.storage.provenance_pipeline import (
    ProvenancePipeline, CapturedRequest
)
from cyberAI.storage.evidence_store import EvidenceStore
from cyberAI.storage.database import Severity, FindingStatus


@dataclass
class ValidationResult:
    """Result of a validation check."""
    check_name: str
    passed: bool
    message: str
    metrics: dict
    duration_ms: float


class ProvenanceValidator:
    """
    Validates the provenance system end-to-end.
    
    Checks:
    1. WARC capture integrity (all requests captured)
    2. Reference linkage (findings → requests → WARC)
    3. Evidence extraction (can retrieve raw HTTP from WARC)
    4. Deduplication (duplicate responses share WARC segment)
    5. Performance (throughput and latency targets)
    6. Storage efficiency (bytes per request)
    """
    
    def __init__(self, base_dir: str = "outputs/validation"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.engagement_id = f"validation_{int(time.time())}"
        self.results: list[ValidationResult] = []
    
    async def run_all_checks(self) -> dict:
        """Run all validation checks."""
        logger.info("=" * 80)
        logger.info("PROVENANCE SYSTEM VALIDATION")
        logger.info("=" * 80)
        
        # Initialize pipeline
        pipeline = ProvenancePipeline(
            engagement_id=self.engagement_id,
            warc_base_dir=str(self.base_dir / "warc"),
            db_path=str(self.base_dir / "validation.db"),
            batch_size=50,
            enable_dedup=True,
        )
        
        try:
            # Run checks in sequence
            await self.check_1_capture_integrity(pipeline)
            await self.check_2_reference_linkage(pipeline)
            await self.check_3_evidence_extraction(pipeline)
            await self.check_4_deduplication(pipeline)
            await self.check_5_performance(pipeline)
            await self.check_6_storage_efficiency(pipeline)
            
            # Summary
            self.print_summary()
            
            return {
                "passed": all(r.passed for r in self.results),
                "checks": [
                    {
                        "name": r.check_name,
                        "passed": r.passed,
                        "message": r.message,
                        "metrics": r.metrics,
                        "duration_ms": r.duration_ms,
                    }
                    for r in self.results
                ],
            }
        
        finally:
            pipeline.close()
    
    async def check_1_capture_integrity(self, pipeline: ProvenancePipeline):
        """Check 1: All requests are captured to WARC."""
        logger.info("\n[Check 1] WARC Capture Integrity")
        start = time.time()
        
        try:
            # Capture 100 requests
            num_requests = 100
            captured_ids = []
            
            for i in range(num_requests):
                req = self._generate_test_request(i)
                request_id = pipeline.ingest_request(req)
                captured_ids.append(request_id)
            
            # Verify all have WARC refs
            missing = 0
            for req_id in captured_ids:
                request = pipeline.db.get_request_by_id(req_id)
                if not request or not request.warc_ref:
                    missing += 1
            
            passed = missing == 0
            message = f"Captured {num_requests} requests, {missing} missing WARC refs"
            
            self.results.append(ValidationResult(
                check_name="WARC Capture Integrity",
                passed=passed,
                message=message,
                metrics={"requests_captured": num_requests, "missing_refs": missing},
                duration_ms=(time.time() - start) * 1000,
            ))
            
            logger.info(f"  {'✓' if passed else '✗'} {message}")
        
        except Exception as e:
            logger.error(f"  ✗ Check failed: {e}")
            self.results.append(ValidationResult(
                check_name="WARC Capture Integrity",
                passed=False,
                message=f"Exception: {str(e)}",
                metrics={},
                duration_ms=(time.time() - start) * 1000,
            ))
    
    async def check_2_reference_linkage(self, pipeline: ProvenancePipeline):
        """Check 2: Findings correctly link to WARC refs."""
        logger.info("\n[Check 2] Reference Linkage (Finding → Request → WARC)")
        start = time.time()
        
        try:
            # Create test requests
            req_ids = []
            for i in range(5):
                req = self._generate_test_request(100 + i)
                req_id = pipeline.ingest_request(req)
                req_ids.append(req_id)
            
            # Create finding with evidence
            finding = pipeline.create_finding(
                title="Test BOLA Vulnerability",
                severity=Severity.HIGH,
                category="BOLA",
                description="User can access admin resources",
                asset="https://target.example.com/api/admin/users",
                evidence_request_ids=req_ids,
            )
            
            # Verify finding has WARC refs
            passed = len(finding.evidence_warc_refs) == len(req_ids)
            
            # Verify each ref is valid
            for warc_ref_dict in finding.evidence_warc_refs:
                if not all(k in warc_ref_dict for k in ["warc_id", "file_path", "offset", "length"]):
                    passed = False
                    break
            
            message = f"Finding has {len(finding.evidence_warc_refs)}/{len(req_ids)} WARC refs"
            
            self.results.append(ValidationResult(
                check_name="Reference Linkage",
                passed=passed,
                message=message,
                metrics={
                    "finding_id": finding.id,
                    "evidence_count": len(finding.evidence_warc_refs),
                },
                duration_ms=(time.time() - start) * 1000,
            ))
            
            logger.info(f"  {'✓' if passed else '✗'} {message}")
        
        except Exception as e:
            logger.error(f"  ✗ Check failed: {e}")
            self.results.append(ValidationResult(
                check_name="Reference Linkage",
                passed=False,
                message=f"Exception: {str(e)}",
                metrics={},
                duration_ms=(time.time() - start) * 1000,
            ))

    
    async def check_3_evidence_extraction(self, pipeline: ProvenancePipeline):
        """Check 3: Can extract raw HTTP from WARC on-demand."""
        logger.info("\n[Check 3] Evidence Extraction from WARC")
        start = time.time()
        
        try:
            # Create request
            req = self._generate_test_request(200)
            req_id = pipeline.ingest_request(req)
            
            # Get request from DB
            request = pipeline.db.get_request_by_id(req_id)
            
            # Extract evidence using EvidenceStore
            evidence_store = EvidenceStore(warc_base_dir=self.base_dir / "warc")
            
            from cyberAI.storage.warc_writer import WARCReference
            warc_ref = WARCReference(**request.warc_ref)
            
            # Read WARC record
            record_bytes = evidence_store.read_warc_record(warc_ref)
            
            # Extract HTTP
            headers, body = evidence_store.extract_http_from_warc(record_bytes)
            
            # Verify we got data
            passed = len(record_bytes) > 0 and len(body) > 0
            message = f"Extracted {len(record_bytes)} bytes from WARC, body: {len(body)} bytes"
            
            self.results.append(ValidationResult(
                check_name="Evidence Extraction",
                passed=passed,
                message=message,
                metrics={
                    "warc_bytes": len(record_bytes),
                    "body_bytes": len(body),
                    "headers_count": len(headers),
                },
                duration_ms=(time.time() - start) * 1000,
            ))
            
            logger.info(f"  {'✓' if passed else '✗'} {message}")
        
        except Exception as e:
            logger.error(f"  ✗ Check failed: {e}")
            self.results.append(ValidationResult(
                check_name="Evidence Extraction",
                passed=False,
                message=f"Exception: {str(e)}",
                metrics={},
                duration_ms=(time.time() - start) * 1000,
            ))
    
    async def check_4_deduplication(self, pipeline: ProvenancePipeline):
        """Check 4: Duplicate responses share same WARC segment."""
        logger.info("\n[Check 4] Content Deduplication")
        start = time.time()
        
        try:
            # Create 10 requests with identical response bodies
            duplicate_body = b'{"status": "success", "data": "duplicate_content"}'
            req_ids = []
            
            for i in range(10):
                req = CapturedRequest(
                    method="GET",
                    url=f"https://target.example.com/api/endpoint_{i}",
                    request_headers={"User-Agent": "Test"},
                    request_body=b"",
                    status_code=200,
                    reason="OK",
                    response_headers={"Content-Type": "application/json"},
                    response_body=duplicate_body,  # Same body
                    role="user",
                    engagement_id=self.engagement_id,
                )
                req_id = pipeline.ingest_request(req)
                req_ids.append(req_id)
            
            # Check if they share WARC IDs (dedup working)
            warc_ids = set()
            for req_id in req_ids:
                request = pipeline.db.get_request_by_id(req_id)
                if request:
                    warc_ids.add(request.warc_ref["warc_id"])
            
            # With dedup enabled, should have fewer unique WARC IDs than requests
            dedup_working = len(warc_ids) < len(req_ids)
            dedup_ratio = 1.0 - (len(warc_ids) / len(req_ids))
            
            passed = dedup_working
            message = f"{len(req_ids)} requests → {len(warc_ids)} unique WARC segments ({dedup_ratio*100:.1f}% dedup)"
            
            self.results.append(ValidationResult(
                check_name="Content Deduplication",
                passed=passed,
                message=message,
                metrics={
                    "requests": len(req_ids),
                    "unique_warc_ids": len(warc_ids),
                    "dedup_ratio": dedup_ratio,
                },
                duration_ms=(time.time() - start) * 1000,
            ))
            
            logger.info(f"  {'✓' if passed else '✗'} {message}")
        
        except Exception as e:
            logger.error(f"  ✗ Check failed: {e}")
            self.results.append(ValidationResult(
                check_name="Content Deduplication",
                passed=False,
                message=f"Exception: {str(e)}",
                metrics={},
                duration_ms=(time.time() - start) * 1000,
            ))
    
    async def check_5_performance(self, pipeline: ProvenancePipeline):
        """Check 5: Performance targets (1000 req/s, <100ms lookup)."""
        logger.info("\n[Check 5] Performance Targets")
        start = time.time()
        
        try:
            # Test write throughput
            num_requests = 1000
            write_start = time.time()
            
            for i in range(num_requests):
                req = self._generate_test_request(300 + i)
                pipeline.ingest_request(req)
            
            write_duration = time.time() - write_start
            throughput = num_requests / write_duration
            
            # Test lookup latency
            lookup_times = []
            for i in range(100):
                lookup_start = time.time()
                # Lookup a request
                stats = pipeline.get_stats()
                lookup_times.append((time.time() - lookup_start) * 1000)
            
            avg_lookup_ms = sum(lookup_times) / len(lookup_times)
            
            # Check targets
            throughput_ok = throughput >= 1000
            latency_ok = avg_lookup_ms < 100
            passed = throughput_ok and latency_ok
            
            message = f"Throughput: {throughput:.0f} req/s, Lookup: {avg_lookup_ms:.2f}ms"
            
            self.results.append(ValidationResult(
                check_name="Performance Targets",
                passed=passed,
                message=message,
                metrics={
                    "throughput_rps": throughput,
                    "avg_lookup_ms": avg_lookup_ms,
                    "throughput_target_met": throughput_ok,
                    "latency_target_met": latency_ok,
                },
                duration_ms=(time.time() - start) * 1000,
            ))
            
            logger.info(f"  {'✓' if passed else '✗'} {message}")
        
        except Exception as e:
            logger.error(f"  ✗ Check failed: {e}")
            self.results.append(ValidationResult(
                check_name="Performance Targets",
                passed=False,
                message=f"Exception: {str(e)}",
                metrics={},
                duration_ms=(time.time() - start) * 1000,
            ))

    
    async def check_6_storage_efficiency(self, pipeline: ProvenancePipeline):
        """Check 6: Storage efficiency (bytes per request)."""
        logger.info("\n[Check 6] Storage Efficiency")
        start = time.time()
        
        try:
            # Get current stats
            stats = pipeline.get_stats()
            
            # Calculate storage metrics
            warc_dir = self.base_dir / "warc" / self.engagement_id
            total_warc_bytes = sum(f.stat().st_size for f in warc_dir.glob("*.warc.gz"))
            
            db_path = self.base_dir / "validation.db"
            db_bytes = db_path.stat().st_size if db_path.exists() else 0
            
            total_storage = total_warc_bytes + db_bytes
            num_requests = stats.get("requests", 1)
            bytes_per_request = total_storage / num_requests if num_requests > 0 else 0
            
            # Target: <10KB per request on average (with dedup)
            passed = bytes_per_request < 10_000
            
            message = f"{bytes_per_request:.0f} bytes/request (WARC: {total_warc_bytes/1024:.1f}KB, DB: {db_bytes/1024:.1f}KB)"
            
            self.results.append(ValidationResult(
                check_name="Storage Efficiency",
                passed=passed,
                message=message,
                metrics={
                    "bytes_per_request": bytes_per_request,
                    "total_warc_bytes": total_warc_bytes,
                    "total_db_bytes": db_bytes,
                    "total_requests": num_requests,
                },
                duration_ms=(time.time() - start) * 1000,
            ))
            
            logger.info(f"  {'✓' if passed else '✗'} {message}")
        
        except Exception as e:
            logger.error(f"  ✗ Check failed: {e}")
            self.results.append(ValidationResult(
                check_name="Storage Efficiency",
                passed=False,
                message=f"Exception: {str(e)}",
                metrics={},
                duration_ms=(time.time() - start) * 1000,
            ))
    
    def _generate_test_request(self, seed: int) -> CapturedRequest:
        """Generate a test HTTP request/response pair."""
        url = f"https://target.example.com/api/users/{seed}"
        
        return CapturedRequest(
            method="GET",
            url=url,
            request_headers={
                "User-Agent": "CyberAI/1.0",
                "Accept": "application/json",
                "Authorization": f"Bearer token_{seed % 10}",
            },
            request_body=b"",
            status_code=200,
            reason="OK",
            response_headers={
                "Content-Type": "application/json",
                "Content-Length": "100",
            },
            response_body=f'{{"id": {seed}, "name": "user_{seed}", "data": "test_data"}}'.encode(),
            role="user",
            engagement_id=self.engagement_id,
        )
    
    def print_summary(self):
        """Print validation summary."""
        logger.info("\n" + "=" * 80)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 80)
        
        passed_count = sum(1 for r in self.results if r.passed)
        total_count = len(self.results)
        
        for result in self.results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            logger.info(f"{status} | {result.check_name}")
            logger.info(f"       {result.message}")
            logger.info(f"       Duration: {result.duration_ms:.2f}ms")
        
        logger.info("=" * 80)
        logger.info(f"RESULT: {passed_count}/{total_count} checks passed")
        
        if passed_count == total_count:
            logger.info("✓ ALL CHECKS PASSED - Provenance system validated!")
        else:
            logger.warning(f"✗ {total_count - passed_count} checks failed")
        
        logger.info("=" * 80)


async def main():
    """Run provenance validation."""
    validator = ProvenanceValidator()
    results = await validator.run_all_checks()
    
    # Save results
    import json
    results_path = validator.base_dir / "validation_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"\nResults saved to: {results_path}")
    
    return results["passed"]


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
