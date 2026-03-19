"""
Batch data processor - enriches captured requests and prepares for testing.
Handles massive data volumes with streaming and batching.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional
from datetime import datetime

from loguru import logger

from ..insertion_points.extractor import InsertionPointExtractor
from ..storage.warc_writer import WARCWriter


@dataclass
class EnrichedRequest:
    """Enriched request with insertion points and metadata."""
    request_id: str
    method: str
    url: str
    url_template: str
    headers: dict
    body: Optional[bytes]
    insertion_points: list[dict]
    endpoint: str
    novelty_score: float
    timestamp: str
    warc_ref: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "method": self.method,
            "url": self.url,
            "url_template": self.url_template,
            "headers": self.headers,
            "body": self.body.decode("utf-8", errors="ignore") if self.body else None,
            "insertion_points": self.insertion_points,
            "endpoint": self.endpoint,
            "novelty_score": self.novelty_score,
            "timestamp": self.timestamp,
            "warc_ref": self.warc_ref,
        }


class BatchDataProcessor:
    """
    Processes captured requests in batches for efficiency.
    Enriches with insertion points, novelty scores, and WARC references.
    """
    
    def __init__(
        self,
        output_dir: Path,
        batch_size: int = 100,
        enable_warc: bool = True,
    ):
        """
        Initialize batch processor.
        
        Args:
            output_dir: Output directory for processed data
            batch_size: Number of requests per batch
            enable_warc: Whether to write WARC files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.batch_size = batch_size
        self.enable_warc = enable_warc
        
        # Components
        self.insertion_extractor = InsertionPointExtractor()
        self.warc_writer = WARCWriter(str(self.output_dir / "warc")) if enable_warc else None
        
        # Stats
        self.stats = {
            "requests_processed": 0,
            "batches_processed": 0,
            "insertion_points_extracted": 0,
            "warc_records_written": 0,
            "errors": 0,
        }
        
        logger.info(f"Batch processor initialized: batch_size={batch_size}, warc={enable_warc}")
    
    async def process_captured_requests(
        self,
        requests_file: Path,
        engagement_id: str = "default",
    ) -> Path:
        """
        Process captured requests from file.
        
        Args:
            requests_file: Path to captured_requests.json
            engagement_id: Engagement identifier
        
        Returns:
            Path to enriched data file
        """
        logger.info(f"Processing captured requests from {requests_file}")
        
        # Load requests
        with open(requests_file, "r") as f:
            requests = json.load(f)
        
        logger.info(f"Loaded {len(requests)} requests")
        
        # Process in batches
        enriched_requests = []
        batch = []
        
        for i, req in enumerate(requests):
            batch.append(req)
            
            if len(batch) >= self.batch_size or i == len(requests) - 1:
                # Process batch
                enriched_batch = await self._process_batch(batch, engagement_id)
                enriched_requests.extend(enriched_batch)
                
                self.stats["batches_processed"] += 1
                logger.info(
                    f"Processed batch {self.stats['batches_processed']}: "
                    f"{len(enriched_batch)} requests"
                )
                
                batch = []
        
        # Save enriched data
        output_file = self.output_dir / f"enriched_requests_{engagement_id}.json"
        with open(output_file, "w") as f:
            json.dump([r.to_dict() for r in enriched_requests], f, indent=2)
        
        logger.info(f"Saved {len(enriched_requests)} enriched requests to {output_file}")
        
        # Save stats
        stats_file = self.output_dir / f"processing_stats_{engagement_id}.json"
        with open(stats_file, "w") as f:
            json.dump({
                **self.stats,
                "novelty_stats": self.insertion_extractor.get_novelty_stats(),
            }, f, indent=2)
        
        return output_file
    
    async def _process_batch(
        self,
        batch: list[dict],
        engagement_id: str,
    ) -> list[EnrichedRequest]:
        """Process a batch of requests."""
        enriched = []
        
        for req in batch:
            try:
                enriched_req = await self._enrich_request(req, engagement_id)
                if enriched_req:
                    enriched.append(enriched_req)
                    self.stats["requests_processed"] += 1
            
            except Exception as e:
                logger.error(f"Error enriching request {req.get('url')}: {e}")
                self.stats["errors"] += 1
        
        return enriched
    
    async def _enrich_request(
        self,
        req: dict,
        engagement_id: str,
    ) -> Optional[EnrichedRequest]:
        """Enrich a single request."""
        url = req.get("url")
        method = req.get("method", "GET")
        headers = req.get("headers", {})
        post_data = req.get("post_data")
        
        # Convert post_data to bytes
        body = None
        if post_data:
            if isinstance(post_data, str):
                body = post_data.encode("utf-8")
            elif isinstance(post_data, bytes):
                body = post_data
        
        # Extract insertion points
        try:
            canonical, insertion_points = self.insertion_extractor.extract_from_request(
                method=method,
                url=url,
                headers=headers,
                body=body,
            )
            
            self.stats["insertion_points_extracted"] += len(insertion_points)
        
        except Exception as e:
            logger.debug(f"Error extracting insertion points from {url}: {e}")
            return None
        
        # Write to WARC
        warc_ref = None
        if self.warc_writer and body:
            try:
                # Create mock response for WARC
                response_data = {
                    "status": 200,
                    "headers": {},
                    "body": b"",
                }
                
                warc_ref = await asyncio.to_thread(
                    self.warc_writer.write_request_response,
                    url=url,
                    method=method,
                    request_headers=headers,
                    request_body=body or b"",
                    response_status=response_data["status"],
                    response_headers=response_data["headers"],
                    response_body=response_data["body"],
                )
                
                self.stats["warc_records_written"] += 1
            
            except Exception as e:
                logger.debug(f"Error writing WARC for {url}: {e}")
        
        # Get novelty score
        endpoint = f"{method} {canonical.url_template}"
        novelty_score = self.insertion_extractor.novelty_index.get_endpoint_novelty_score(endpoint)
        
        # Create enriched request
        return EnrichedRequest(
            request_id=canonical.request_id,
            method=method,
            url=url,
            url_template=canonical.url_template,
            headers=headers,
            body=body,
            insertion_points=[ip.to_dict() for ip in insertion_points],
            endpoint=endpoint,
            novelty_score=novelty_score,
            timestamp=datetime.utcnow().isoformat(),
            warc_ref=warc_ref,
        )
    
    def get_stats(self) -> dict:
        """Get processing statistics."""
        return self.stats


class StreamingDataProcessor:
    """
    Streaming processor for real-time data enrichment.
    Processes requests as they arrive without batching.
    """
    
    def __init__(self, output_dir: Path):
        """Initialize streaming processor."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.insertion_extractor = InsertionPointExtractor()
        self.processed_count = 0
    
    async def process_stream(
        self,
        request_stream: AsyncIterator[dict],
    ) -> AsyncIterator[EnrichedRequest]:
        """
        Process requests from an async stream.
        
        Args:
            request_stream: Async iterator of request dicts
        
        Yields:
            EnrichedRequest objects
        """
        async for req in request_stream:
            try:
                # Extract insertion points
                canonical, insertion_points = self.insertion_extractor.extract_from_request(
                    method=req.get("method", "GET"),
                    url=req.get("url"),
                    headers=req.get("headers", {}),
                    body=req.get("body"),
                )
                
                # Get novelty score
                endpoint = f"{canonical.method} {canonical.url_template}"
                novelty_score = self.insertion_extractor.novelty_index.get_endpoint_novelty_score(endpoint)
                
                # Create enriched request
                enriched = EnrichedRequest(
                    request_id=canonical.request_id,
                    method=canonical.method,
                    url=req.get("url"),
                    url_template=canonical.url_template,
                    headers=req.get("headers", {}),
                    body=req.get("body"),
                    insertion_points=[ip.to_dict() for ip in insertion_points],
                    endpoint=endpoint,
                    novelty_score=novelty_score,
                    timestamp=datetime.utcnow().isoformat(),
                )
                
                self.processed_count += 1
                yield enriched
            
            except Exception as e:
                logger.error(f"Error processing request: {e}")
                continue
