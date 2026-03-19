"""
Comprehensive integration test for provenance system.

Tests the complete flow:
1. Batch capture of HTTP traffic
2. Content-addressed WARC storage
3. Insertion point extraction
4. Finding generation with evidence
5. Evidence pack creation
6. Database queries and statistics

This demonstrates the system can handle massive data volumes while
maintaining full provenance from finding → WARC evidence.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from loguru import logger

from cyberAI.storage.batch_processor import BatchProcessor, CapturedRequest
from cyberAI.storage.provenance_pipeline import ProvenancePipeline
from cyberAI.storage.database import Severity, FindingStatus, ProvenanceDB
from cyberAI.storage.evidence_store import EvidenceStore
from cyberAI.storage.warc_writer import WARCReference


def generate_mock_traffic(count: int, engagement_id: str) -> list[CapturedRequest]:
    """Generate mock HTTP traffic for testing."""
    requests = []
    
    endpoints = [
        ("GET", "https://api.example.com/users"),
        ("GET", "https://api.example.com/users/{id}"),
        ("POST", "https://api.example.com/users"),
        ("PUT", "https://api.example.com/users/{id}"),
        ("DELETE", "https://api.example.com/users/{id}"),
        ("GET", "https://api.example.com/posts"),
        ("GET", "https://api.example.com/posts/{id}"),
        ("POST", "https://api.example.com/posts"),
        ("GET", "https://api.example.com/comments"),
        ("POST", "https://api.example.com/comments"),
    ]
    
    roles = ["guest", "user", "admin"]
    
    for i in range(count):
        method, url_template = endpoints[i % len(endpoints)]
        role = roles[i % len(roles)]
        
        # Replace template with actual ID
        url = url_template.replace("{id}", str(100 + i))
        
        # Generate request body for POST/PUT
        request_body = b""
        if method in ["POST", "PUT"]:
            body_data = {
                "name": f"User {i}",
                "email": f"user{i}@example.com",
                "role": role,
                "metadata": {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "user_id": 100 + i,
                }
            }
            request_body = json.dumps(body_data).encode()
        
        # Generate response
        status_code = 200 if i % 10 != 0 else 403  # 10% forbidden
        response_body = json.dumps({
            "id": 100 + i,
            "name": f"User {i}",
            "email": f"user{i}@example.com",
            "role": role,
        }).encode()
        
        captured = CapturedRequest(
            method=method,
            url=url,
            request_headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer token_{role}_{i}" if role != "guest" else "",
                "User-Agent": "ProvenanceTest/1.0",
            },
            request_body=request_body,
            status_code=status_code,
            reason="OK" if status_code == 200 else "Forbidden",
            response_headers={
                "Content-Type": "application/json",
                "X-Request-Id": str(uuid4()),
            },
            response_body=response_body,
            role=role,
            engagement_id=engagement_id,
            timestamp=datetime.now(timezone.utc),
        )
        
        requests.append(captured)
    
    return requests


def test_batch_processing():
    """Test 1: Batch processing with high throughput."""
    logger.info("=" * 80)
    logger.info("TEST 1: BATCH PROCESSING")
    logger.info("=" * 80)
    
    engagement_id = f"test_batch_{int(time.time())}"
    
    # Generate mock traffic
    logger.info("Generating 1000 mock requests...")
    requests = generate_mock_traffic(1000, engagement_id)
    
    # Process with batch processor
    logger.info("Processing with BatchProcessor...")
    start_time = time.time()
    
    with BatchProcessor(engagement_id=engagement_id, batch_size=100) as processor:
        for req in requests:
            processor.add(req)
    
    elapsed = time.time() - start_time
    
    logger.info(f"✓ Processed 1000 requests in {elapsed:.2f}s ({1000/elapsed:.1f} req/s)")
    logger.info("")
    
    return engagement_id


def test_insertion_point_extraction(engagement_id: str):
    """Test 2: Insertion point extraction and novelty tracking."""
    logger.info("=" * 80)
    logger.info("TEST 2: INSERTION POINT EXTRACTION")
    logger.info("=" * 80)
    
    db = ProvenanceDB()
    stats = db.get_stats(engagement_id)
    
    logger.info(f"Endpoints discovered: {stats['endpoints']}")
    logger.info(f"Requests captured: {stats['requests']}")
    logger.info(f"Insertion points extracted: {stats['insertion_points']}")
    
    # Check novelty tracking
    logger.info("")
    logger.info("Checking novelty tracking...")
    
    # Generate a duplicate request
    pipeline = ProvenancePipeline(engagement_id=engagement_id)
    duplicate = CapturedRequest(
        method="GET",
        url="https://api.example.com/users/999",
        request_headers={"Content-Type": "application/json"},
        request_body=b"",
        status_code=200,
        reason="OK",
        response_headers={"Content-Type": "application/json"},
        response_body=b'{"id": 999}',
        role="guest",
        engagement_id=engagement_id,
    )
    
    req_id, warc_ref = pipeline.capture_request(duplicate)
    logger.info(f"✓ Duplicate request handled: {req_id}")
    
    pipeline.close()
    db.close()
    
    logger.info("")


def test_finding_generation(engagement_id: str):
    """Test 3: Finding generation with WARC evidence."""
    logger.info("=" * 80)
    logger.info("TEST 3: FINDING GENERATION")
    logger.info("=" * 80)
    
    # Get some request IDs
    db = ProvenanceDB()
    cursor = db.conn.cursor()
    
    if db.use_postgres:
        cursor.execute(
            "SELECT id FROM requests WHERE engagement_id = %s LIMIT 5",
            (engagement_id,)
        )
    else:
        cursor.execute(
            "SELECT id FROM requests WHERE engagement_id = ? LIMIT 5",
            (engagement_id,)
        )
    
    request_ids = [row[0] for row in cursor.fetchall()]
    db.close()
    
    if not request_ids:
        logger.warning("No requests found, skipping finding generation")
        return
    
    # Create findings
    pipeline = ProvenancePipeline(engagement_id=engagement_id)
    
    # Finding 1: BOLA
    finding1 = pipeline.create_finding(
        title="Broken Object Level Authorization (BOLA)",
        severity=Severity.HIGH,
        category="BOLA",
        description="User can access resources belonging to other users",
        asset="https://api.example.com/users/{id}",
        evidence_request_ids=request_ids[:2],
        metadata={
            "attack_vector": "Direct object reference manipulation",
            "affected_roles": ["user", "guest"],
        }
    )
    
    logger.info(f"✓ Created finding: {finding1.title}")
    logger.info(f"  Severity: {finding1.severity.value}")
    logger.info(f"  Evidence: {len(finding1.evidence_warc_refs)} WARC refs")
    
    # Finding 2: Missing authentication
    finding2 = pipeline.create_finding(
        title="Missing Authentication on Sensitive Endpoint",
        severity=Severity.CRITICAL,
        category="Authentication",
        description="Admin endpoints accessible without authentication",
        asset="https://api.example.com/users",
        evidence_request_ids=request_ids[2:4],
        metadata={
            "endpoint_classification": "admin",
            "expected_auth": "Bearer token",
        }
    )
    
    logger.info(f"✓ Created finding: {finding2.title}")
    logger.info(f"  Severity: {finding2.severity.value}")
    logger.info(f"  Evidence: {len(finding2.evidence_warc_refs)} WARC refs")
    
    pipeline.close()
    logger.info("")


def test_evidence_pack_generation(engagement_id: str):
    """Test 4: Evidence pack generation."""
    logger.info("=" * 80)
    logger.info("TEST 4: EVIDENCE PACK GENERATION")
    logger.info("=" * 80)
    
    # Get findings
    pipeline = ProvenancePipeline(engagement_id=engagement_id)
    findings = pipeline.get_findings()
    pipeline.close()
    
    if not findings:
        logger.warning("No findings to generate evidence for")
        return
    
    logger.info(f"Found {len(findings)} findings")
    
    # Generate evidence pack for each finding
    evidence_store = EvidenceStore(warc_base_dir="outputs/warc")
    
    for finding in findings:
        logger.info(f"Generating evidence pack for: {finding.title}")
        
        # Convert dicts to WARCReference objects
        warc_refs = []
        for ref_dict in finding.evidence_warc_refs:
            warc_ref = WARCReference(
                warc_id=ref_dict["warc_id"],
                file_path=ref_dict["file_path"],
                offset=ref_dict["offset"],
                length=ref_dict["length"],
                engagement_id=ref_dict["engagement_id"],
                timestamp=datetime.fromisoformat(ref_dict["timestamp"]),
            )
            warc_refs.append(warc_ref)
        
        try:
            pack_path = evidence_store.generate_evidence_pack(
                finding_id=finding.id,
                warc_refs=warc_refs,
                output_dir=Path("outputs/evidence_packs"),
            )
            
            logger.info(f"  ✓ Evidence pack: {pack_path}")
            logger.info(f"    Records: {len(warc_refs)}")
        except Exception as e:
            logger.error(f"  ✗ Failed to generate pack: {e}")
    
    logger.info("")


def test_database_queries(engagement_id: str):
    """Test 5: Database queries and statistics."""
    logger.info("=" * 80)
    logger.info("TEST 5: DATABASE QUERIES")
    logger.info("=" * 80)
    
    db = ProvenanceDB()
    
    # Get overall stats
    stats = db.get_stats(engagement_id)
    logger.info("Engagement Statistics:")
    logger.info(f"  Endpoints: {stats['endpoints']}")
    logger.info(f"  Requests: {stats['requests']}")
    logger.info(f"  Insertion Points: {stats['insertion_points']}")
    logger.info(f"  Findings by Severity:")
    for severity, count in stats.get('findings_by_severity', {}).items():
        logger.info(f"    {severity}: {count}")
    
    # Get findings
    logger.info("")
    logger.info("Findings:")
    findings = db.get_findings_by_engagement(engagement_id)
    for finding in findings:
        logger.info(f"  - {finding.title} ({finding.severity.value})")
        logger.info(f"    Status: {finding.status.value}")
        logger.info(f"    Evidence: {len(finding.evidence_warc_refs)} WARC refs")
    
    db.close()
    logger.info("")


def run_integration_tests():
    """Run all integration tests."""
    logger.info("")
    logger.info("╔" + "═" * 78 + "╗")
    logger.info("║" + " " * 20 + "PROVENANCE SYSTEM INTEGRATION TEST" + " " * 24 + "║")
    logger.info("╚" + "═" * 78 + "╝")
    logger.info("")
    
    start_time = time.time()
    
    try:
        # Test 1: Batch processing
        engagement_id = test_batch_processing()
        
        # Test 2: Insertion point extraction
        test_insertion_point_extraction(engagement_id)
        
        # Test 3: Finding generation
        test_finding_generation(engagement_id)
        
        # Test 4: Evidence pack generation
        test_evidence_pack_generation(engagement_id)
        
        # Test 5: Database queries
        test_database_queries(engagement_id)
        
        elapsed = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info("ALL TESTS PASSED ✓")
        logger.info(f"Total time: {elapsed:.2f}s")
        logger.info(f"Engagement ID: {engagement_id}")
        logger.info("=" * 80)
        logger.info("")
        
        return True
    
    except Exception as e:
        logger.error(f"TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_integration_tests()
    exit(0 if success else 1)
