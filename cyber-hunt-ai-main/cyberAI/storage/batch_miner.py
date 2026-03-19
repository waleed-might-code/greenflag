"""
Batch data mining utilities for large-scale crawling.
Orchestrates massive data collection with WARC storage.
"""

import asyncio
from pathlib import Path
from typing import List, Optional, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from cyberAI.storage import WARCIntegration
from cyberAI.models import RequestRecord, HttpMethod


@dataclass
class CrawlTarget:
    """Target for batch crawling."""
    url: str
    method: str = "GET"
    headers: dict = None
    body: Optional[str] = None
    priority: int = 0


class BatchDataMiner:
    """
    Orchestrate large-scale data mining with WARC storage.
    
    Usage:
        miner = BatchDataMiner(engagement_id="eng_001", max_workers=10)
        
        # Add targets
        miner.add_target("https://api.target.com/users")
        miner.add_target("https://api.target.com/products")
        
        # Mine data
        await miner.mine_all()
    """
    
    def __init__(
        self,
        engagement_id: str,
        max_workers: int = 10,
        rate_limit_rps: int = 100,
    ):
        """
        Initialize batch miner.
        
        Args:
            engagement_id: Engagement identifier
            max_workers: Maximum concurrent workers
            rate_limit_rps: Requests per second limit
        """
        self.engagement_id = engagement_id
        self.max_workers = max_workers
        self.rate_limit_rps = rate_limit_rps
        self.targets: List[CrawlTarget] = []
        self.completed = 0
        self.failed = 0
    
    def add_target(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        body: Optional[str] = None,
        priority: int = 0
    ):
        """Add target to crawl queue."""
        target = CrawlTarget(
            url=url,
            method=method,
            headers=headers or {},
            body=body,
            priority=priority
        )
        self.targets.append(target)
    
    def add_targets_from_file(self, file_path: Path):
        """
        Load targets from file (one URL per line).
        
        Format:
            https://api.target.com/users
            https://api.target.com/products
            POST https://api.target.com/search {"query": "test"}
        """
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                parts = line.split(maxsplit=2)
                if len(parts) == 1:
                    self.add_target(parts[0])
                elif len(parts) == 2:
                    self.add_target(parts[1], method=parts[0])
                elif len(parts) == 3:
                    self.add_target(parts[1], method=parts[0], body=parts[2])
    
    async def mine_target(self, target: CrawlTarget) -> bool:
        """
        Mine single target and capture to WARC.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Simulate HTTP request (in real implementation, use httpx)
            # For demo, create mock response
            request = RequestRecord(
                method=HttpMethod[target.method],
                url=target.url,
                headers=target.headers,
                body=target.body,
                response_status=200,
                response_body='{"data": "mined"}',
                response_headers={"Content-Type": "application/json"}
            )
            
            # Capture to WARC
            ref = WARCIntegration.capture_request(self.engagement_id, request)
            
            self.completed += 1
            logger.debug(f"Mined: {target.url} -> {ref.warc_id[:8]}...")
            
            return True
        
        except Exception as e:
            self.failed += 1
            logger.error(f"Failed to mine {target.url}: {e}")
            return False
    
    async def mine_all(self, progress_callback: Optional[Callable] = None):
        """
        Mine all targets with rate limiting and concurrency control.
        
        Args:
            progress_callback: Optional callback(completed, total)
        """
        logger.info(f"Starting batch mining: {len(self.targets)} targets")
        
        # Sort by priority
        self.targets.sort(key=lambda t: t.priority, reverse=True)
        
        # Rate limiting
        delay = 1.0 / self.rate_limit_rps
        
        # Process in batches
        semaphore = asyncio.Semaphore(self.max_workers)
        
        async def mine_with_limit(target):
            async with semaphore:
                result = await self.mine_target(target)
                await asyncio.sleep(delay)
                
                if progress_callback:
                    progress_callback(self.completed, len(self.targets))
                
                return result
        
        # Execute all
        tasks = [mine_with_limit(target) for target in self.targets]
        await asyncio.gather(*tasks)
        
        logger.info(f"Batch mining complete:")
        logger.info(f"  Completed: {self.completed}")
        logger.info(f"  Failed: {self.failed}")
        logger.info(f"  Success rate: {self.completed / len(self.targets) * 100:.1f}%")
    
    def get_statistics(self) -> dict:
        """Get mining statistics."""
        return {
            "total_targets": len(self.targets),
            "completed": self.completed,
            "failed": self.failed,
            "success_rate": self.completed / len(self.targets) if self.targets else 0,
        }


class APIDiscovery:
    """
    Discover API endpoints from various sources.
    """
    
    @staticmethod
    def from_sitemap(sitemap_url: str) -> List[str]:
        """Discover URLs from sitemap.xml."""
        # Implementation would parse sitemap
        return []
    
    @staticmethod
    def from_openapi_spec(spec_url: str) -> List[CrawlTarget]:
        """Discover endpoints from OpenAPI/Swagger spec."""
        # Implementation would parse OpenAPI spec
        return []
    
    @staticmethod
    def from_javascript(js_content: str) -> List[str]:
        """Extract API endpoints from JavaScript code."""
        import re
        
        # Find URL patterns
        patterns = [
            r'["\']https?://[^"\']+["\']',
            r'["\']\/api\/[^"\']+["\']',
            r'fetch\(["\']([^"\']+)["\']',
            r'axios\.[a-z]+\(["\']([^"\']+)["\']',
        ]
        
        urls = set()
        for pattern in patterns:
            matches = re.findall(pattern, js_content)
            urls.update(matches)
        
        return list(urls)
    
    @staticmethod
    def from_graphql_introspection(endpoint: str) -> List[CrawlTarget]:
        """Discover GraphQL schema via introspection."""
        introspection_query = """
        {
          __schema {
            types {
              name
              fields {
                name
              }
            }
          }
        }
        """
        
        return [CrawlTarget(
            url=endpoint,
            method="POST",
            body=introspection_query,
            headers={"Content-Type": "application/json"}
        )]


def mine_engagement_at_scale(
    engagement_id: str,
    target_urls: List[str],
    max_workers: int = 50,
    rate_limit_rps: int = 100
):
    """
    Mine data at scale for an engagement.
    
    Args:
        engagement_id: Engagement identifier
        target_urls: List of URLs to mine
        max_workers: Maximum concurrent workers
        rate_limit_rps: Requests per second limit
    """
    miner = BatchDataMiner(
        engagement_id=engagement_id,
        max_workers=max_workers,
        rate_limit_rps=rate_limit_rps
    )
    
    # Add all targets
    for url in target_urls:
        miner.add_target(url)
    
    # Progress callback
    def progress(completed, total):
        pct = completed / total * 100
        print(f"\rProgress: {completed}/{total} ({pct:.1f}%)", end="", flush=True)
    
    # Mine all
    asyncio.run(miner.mine_all(progress_callback=progress))
    print()  # New line after progress
    
    # Close WARC writer
    WARCIntegration.close_writer(engagement_id)
    
    return miner.get_statistics()
