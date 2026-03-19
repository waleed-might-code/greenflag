"""
Provenance-enabled crawler integration.

Demonstrates how to integrate provenance tracking with the existing crawler
to mine massive amounts of data while maintaining full evidence trails.

Key features:
- Every HTTP request → WARC archive
- Every finding → linked to WARC evidence
- Batch processing for scale (1000+ req/sec)
- Content-addressed deduplication
- Real-time statistics
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.async_api import async_playwright, Page, Response

from cyberAI.storage.batch_processor import StreamingProcessor, CapturedRequest
from cyberAI.storage.provenance_pipeline import ProvenancePipeline
from cyberAI.storage.database import Severity, FindingStatus
from cyberAI.storage.evidence_store import EvidenceStore


class ProvenanceCrawler:
    """
    Crawler with full provenance tracking.
    
    Every request is captured to WARC with content-addressed IDs.
    Every finding links back to the exact HTTP evidence.
    """
    
    def __init__(
        self,
        engagement_id: str,
        target_url: str,
        role: str = "guest",
        enable_streaming: bool = True,
        batch_size: int = 100,
    ):
        """
        Initialize provenance-enabled crawler.
        
        Args:
            engagement_id: Unique engagement identifier
            target_url: Target URL to crawl
            role: User role (guest, user, admin)
            enable_streaming: Use streaming processor for async writes
            batch_size: Batch size for database writes
        """
        self.engagement_id = engagement_id
        self.target_url = target_url
        self.role = role
        self.enable_streaming = enable_streaming
        
        # Initialize processor
        if enable_streaming:
            self.processor = StreamingProcessor(
                engagement_id=engagement_id,
                batch_size=batch_size,
            )
        else:
            from cyberAI.storage.batch_processor import BatchProcessor
            self.processor = BatchProcessor(
                engagement_id=engagement_id,
                batch_size=batch_size,
            )
        
        # Track request IDs for finding generation
        self.request_ids = []
        
        logger.info(
            f"Provenance crawler initialized: engagement={engagement_id}, "
            f"target={target_url}, role={role}"
        )
    
    async def crawl(self, max_pages: int = 100, max_depth: int = 3):
        """
        Crawl target with full provenance tracking.
        
        Args:
            max_pages: Maximum pages to crawl
            max_depth: Maximum crawl depth
        """
        if self.enable_streaming:
            self.processor.start()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            # Set up network interception
            page.on("response", lambda response: asyncio.create_task(
                self._handle_response(response)
            ))
            
            # Crawl
            visited = set()
            queue = [(self.target_url, 0)]
            pages_crawled = 0
            
            while queue and pages_crawled < max_pages:
                url, depth = queue.pop(0)
                
                if url in visited or depth > max_depth:
                    continue
                
                visited.add(url)
                
                try:
                    logger.info(f"Crawling: {url} (depth={depth})")
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    pages_crawled += 1
                    
                    # Extract links for further crawling
                    if depth < max_depth:
                        links = await page.eval_on_selector_all(
                            "a[href]",
                            "elements => elements.map(e => e.href)"
                        )
                        
                        for link in links:
                            if link.startswith(self.target_url) and link not in visited:
                                queue.append((link, depth + 1))
                    
                    # Small delay to avoid overwhelming target
                    await asyncio.sleep(0.5)
                
                except Exception as e:
                    logger.error(f"Failed to crawl {url}: {e}")
            
            await browser.close()
        
        # Stop processor and get stats
        if self.enable_streaming:
            self.processor.stop()
        else:
            self.processor.close()
        
        stats = self.processor.get_stats()
        logger.info(f"Crawl complete: {stats.to_dict()}")
        
        return stats
    
    async def _handle_response(self, response: Response):
        """Handle intercepted HTTP response."""
        try:
            # Skip non-HTTP resources
            if not response.url.startswith("http"):
                return
            
            # Get request details
            request = response.request
            
            # Capture request/response
            captured = CapturedRequest(
                method=request.method,
                url=response.url,
                request_headers=await request.all_headers(),
                request_body=request.post_data_buffer or b"",
                status_code=response.status,
                reason=response.status_text,
                response_headers=await response.all_headers(),
                response_body=await response.body() if response.ok else b"",
                role=self.role,
                engagement_id=self.engagement_id,
                timestamp=datetime.now(timezone.utc),
            )
            
            # Submit to processor
            if self.enable_streaming:
                self.processor.submit(captured)
            else:
                request_id = self.processor.add(captured)
                if request_id:
                    self.request_ids.append(request_id)
        
        except Exception as e:
            logger.debug(f"Failed to capture response: {e}")
    
    def generate_sample_findings(self):
        """Generate sample findings from captured data."""
        if not self.request_ids:
            logger.warning("No requests captured, cannot generate findings")
            return []
        
        # Create pipeline for finding generation
        pipeline = ProvenancePipeline(engagement_id=self.engagement_id)
        
        findings = []
        
        # Sample finding: Unauthenticated access
        if len(self.request_ids) >= 2:
            finding = pipeline.create_finding(
                title="Unauthenticated API Access Detected",
                severity=Severity.MEDIUM,
                category="Authentication",
                description="API endpoints accessible without authentication",
                asset=self.target_url,
                evidence_request_ids=self.request_ids[:2],
                metadata={
                    "role": self.role,
                    "crawl_timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            findings.append(finding)
        
        pipeline.close()
        return findings


async def demo_provenance_crawl():
    """
    Demo: Full provenance-enabled crawl with evidence generation.
    """
    logger.info("=" * 80)
    logger.info("PROVENANCE CRAWLER DEMO")
    logger.info("=" * 80)
    
    # Configuration
    engagement_id = f"demo_{int(time.time())}"
    target_url = "https://example.com"  # Replace with actual target
    
    logger.info(f"Engagement ID: {engagement_id}")
    logger.info(f"Target: {target_url}")
    logger.info("")
    
    # Create crawler
    crawler = ProvenanceCrawler(
        engagement_id=engagement_id,
        target_url=target_url,
        role="guest",
        enable_streaming=True,
        batch_size=50,
    )
    
    # Run crawl
    logger.info("Starting crawl...")
    stats = await crawler.crawl(max_pages=10, max_depth=2)
    
    logger.info("")
    logger.info("Crawl Statistics:")
    logger.info(f"  Total requests: {stats.total_requests}")
    logger.info(f"  Duplicates skipped: {stats.duplicates_skipped}")
    logger.info(f"  Data captured: {stats.bytes_written / 1024 / 1024:.2f} MB")
    logger.info(f"  Processing time: {stats.processing_time_sec:.2f}s")
    logger.info(f"  Throughput: {stats.total_requests / stats.processing_time_sec:.1f} req/s")
    logger.info("")
    
    # Generate findings
    logger.info("Generating sample findings...")
    findings = crawler.generate_sample_findings()
    
    logger.info(f"Generated {len(findings)} findings")
    for finding in findings:
        logger.info(f"  - {finding.title} ({finding.severity.value})")
        logger.info(f"    Evidence: {len(finding.evidence_warc_refs)} WARC refs")
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("DEMO COMPLETE")
    logger.info("=" * 80)
    
    return engagement_id, stats, findings


def demo_evidence_pack_generation(engagement_id: str):
    """
    Demo: Generate evidence pack from findings.
    """
    logger.info("=" * 80)
    logger.info("EVIDENCE PACK GENERATION DEMO")
    logger.info("=" * 80)
    
    # Get findings
    pipeline = ProvenancePipeline(engagement_id=engagement_id)
    findings = pipeline.get_findings()
    
    if not findings:
        logger.warning("No findings to generate evidence for")
        pipeline.close()
        return
    
    logger.info(f"Found {len(findings)} findings")
    
    # Generate evidence pack for first finding
    finding = findings[0]
    logger.info(f"Generating evidence pack for: {finding.title}")
    
    # Convert WARC ref dicts to WARCReference objects
    from cyberAI.storage.warc_writer import WARCReference
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
    
    # Generate pack
    evidence_store = EvidenceStore(warc_base_dir="outputs/warc")
    pack_path = evidence_store.generate_evidence_pack(
        finding_id=finding.id,
        warc_refs=warc_refs,
        output_dir=Path("outputs/evidence_packs"),
    )
    
    logger.info(f"Evidence pack generated: {pack_path}")
    logger.info(f"  Finding: {finding.title}")
    logger.info(f"  Severity: {finding.severity.value}")
    logger.info(f"  Evidence records: {len(warc_refs)}")
    
    pipeline.close()
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("EVIDENCE PACK DEMO COMPLETE")
    logger.info("=" * 80)


if __name__ == "__main__":
    # Run demo
    engagement_id, stats, findings = asyncio.run(demo_provenance_crawl())
    
    # Generate evidence pack
    if findings:
        demo_evidence_pack_generation(engagement_id)
