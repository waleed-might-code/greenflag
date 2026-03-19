"""
Integration patch for CoreDiscovery to use scope-enforcing client.
This shows how to integrate the governance layer with existing crawling code.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Optional

from loguru import logger

from governance.engagement_config import EngagementConfig
from governance.scope_enforcing_client import ScopeEnforcingClient
from utils.http_client import AsyncHTTPClient


class ScopeAwareCrawler:
    """
    Wrapper that adds scope enforcement to any crawler.
    
    Usage:
        config = EngagementConfig.from_file("engagement.yaml")
        crawler = ScopeAwareCrawler(config)
        
        # Use crawler.client for all HTTP requests
        response, record = await crawler.client.get(url)
    """
    
    def __init__(
        self,
        engagement_config: EngagementConfig,
        underlying_client: Optional[AsyncHTTPClient] = None,
    ):
        """
        Initialize scope-aware crawler.
        
        Args:
            engagement_config: Engagement configuration
            underlying_client: Optional existing HTTP client to wrap
        """
        self.config = engagement_config
        self.client = ScopeEnforcingClient(
            engagement_config=engagement_config,
            underlying_client=underlying_client,
            audit_log_path="outputs/logs/crawl_scope_audit.jsonl",
        )
        
        logger.info(f"Initialized scope-aware crawler for: {engagement_config.name}")
        logger.info(f"Target domains: {engagement_config.target_domains}")
        logger.info(f"Out-of-scope patterns: {len(engagement_config.out_of_scope_patterns)}")
    
    async def crawl_url(self, url: str) -> Optional[dict]:
        """
        Crawl a URL with scope enforcement.
        
        Args:
            url: URL to crawl
            
        Returns:
            Response data if successful, None if blocked or failed
        """
        try:
            response, record = await self.client.get(url)
            
            return {
                "url": str(response.url),
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "content_length": len(response.content),
                "record": record,
            }
        
        except Exception as e:
            logger.warning(f"Failed to crawl {url}: {e}")
            return None
    
    def get_stats(self) -> dict:
        """Get crawl statistics."""
        return self.client.get_stats()
    
    async def close(self) -> None:
        """Close the client."""
        await self.client.close()


# Example: Patching CoreDiscovery to use scope enforcement
def patch_core_discovery_with_scope():
    """
    Example of how to patch CoreDiscovery to use scope enforcement.
    
    In practice, you would:
    1. Add an optional engagement_config parameter to CoreDiscovery.__init__
    2. If provided, wrap the HTTP client with ScopeEnforcingClient
    3. All requests automatically go through scope validation
    """
    
    # Pseudocode for the patch:
    """
    class CoreDiscovery:
        def __init__(
            self,
            run_id: Optional[str] = None,
            engagement_config: Optional[EngagementConfig] = None,  # NEW
        ):
            self.config = get_config()
            self.run_id = run_id or generate_run_id()
            
            # NEW: Wrap HTTP client with scope enforcement
            if engagement_config:
                self._http_client = ScopeEnforcingClient(
                    engagement_config=engagement_config,
                    audit_log_path=f"outputs/logs/discovery_{self.run_id}_scope.jsonl",
                )
                logger.info(f"Scope enforcement enabled for discovery run {self.run_id}")
            else:
                self._http_client = AsyncHTTPClient()
            
            # Rest of initialization...
        
        async def _fetch_url(self, url: str):
            # Use self._http_client instead of creating new clients
            response, record = await self._http_client.get(url)
            return response, record
    """
    
    logger.info("To integrate scope enforcement with CoreDiscovery:")
    logger.info("1. Add engagement_config parameter to __init__")
    logger.info("2. Wrap HTTP client with ScopeEnforcingClient if config provided")
    logger.info("3. All requests automatically validated against scope")
    logger.info("4. Out-of-scope requests blocked before hitting the wire")


if __name__ == "__main__":
    import asyncio
    
    async def demo():
        # Create engagement config
        config = EngagementConfig.create_default(
            target_url="https://httpbin.org",
            name="Demo Crawl"
        )
        config.out_of_scope_patterns = ["*/status/500"]
        
        # Create scope-aware crawler
        crawler = ScopeAwareCrawler(config)
        
        # Crawl some URLs
        urls = [
            "https://httpbin.org/get",
            "https://httpbin.org/headers",
            "https://httpbin.org/status/500",  # Will be blocked
        ]
        
        for url in urls:
            result = await crawler.crawl_url(url)
            if result:
                logger.success(f"✓ Crawled: {url} - {result['status']}")
            else:
                logger.warning(f"✗ Blocked or failed: {url}")
        
        # Show stats
        stats = crawler.get_stats()
        logger.info(f"\nCrawl stats: {stats}")
        
        await crawler.close()
    
    asyncio.run(demo())
