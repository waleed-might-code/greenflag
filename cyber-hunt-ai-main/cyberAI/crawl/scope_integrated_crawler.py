"""
Enhanced crawler with built-in scope enforcement at every layer.
Integrates scope validation into Playwright, HTTP client, and frontier.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from ..governance.engagement_config import EngagementConfig
from ..governance.scope_aware_browser import ScopeAwareBrowserPool
from ..governance.scope_enforcing_client import ScopeEnforcingClient
from ..governance.scope_validator import ScopeValidator
from .priority_frontier import PriorityFrontier, FrontierItem, SourceType
from ..insertion_points.extractor import InsertionPointExtractor
from ..pipeline.kafka_client import get_kafka_producer
from ..pipeline.topics import Topics
from ..pipeline.events import RawCapture


@dataclass
class ScopeIntegratedCrawlConfig:
    """Configuration for scope-integrated crawler."""
    max_pages: int = 10000
    max_depth: int = 10
    max_concurrent: int = 5
    page_timeout: int = 30000
    wait_after_load: int = 2000
    capture_screenshots: bool = True
    capture_network: bool = True
    scroll_for_lazy_load: bool = True
    max_scroll_attempts: int = 3
    # Scope enforcement
    enforce_scope_at_browser: bool = True
    enforce_scope_at_http: bool = True
    enforce_scope_at_frontier: bool = True


@dataclass
class CrawlStats:
    """Statistics for crawl session."""
    pages_crawled: int = 0
    pages_skipped_scope: int = 0
    requests_allowed: int = 0
    requests_blocked: int = 0
    insertion_points_found: int = 0
    errors: int = 0


class ScopeIntegratedCrawler:
    """
    Enterprise crawler with multi-layer scope enforcement.
    
    Scope enforcement happens at THREE layers:
    1. Playwright level: page.route() intercepts and blocks before network
    2. HTTP client level: ScopeEnforcingClient validates before sending
    3. Frontier level: URLs are validated before being added to queue
    
    This ensures NO out-of-scope requests are ever sent, regardless of
    which code path is used.
    """
    
    def __init__(
        self,
        engagement_config: EngagementConfig,
        config: Optional[ScopeIntegratedCrawlConfig] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize scope-integrated crawler.
        
        Args:
            engagement_config: Engagement configuration with scope rules
            config: Crawl configuration
            output_dir: Output directory
        """
        self.engagement_config = engagement_config
        self.config = config or ScopeIntegratedCrawlConfig()
        self.output_dir = output_dir or Path("outputs/scope_crawl")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Scope enforcement components
        self.scope_validator = ScopeValidator(
            target_domains=engagement_config.target_domains,
            out_of_scope_patterns=engagement_config.out_of_scope_patterns,
            allowed_schemes=engagement_config.allowed_schemes,
        )
        
        self.browser_pool = ScopeAwareBrowserPool(engagement_config)
        self.http_client = ScopeEnforcingClient(engagement_config)
        
        # Crawl components
        self.frontier = PriorityFrontier(
            max_depth=self.config.max_depth,
            max_items=self.config.max_pages * 2,
        )
        self.insertion_extractor = InsertionPointExtractor()
        
        # State
        self.stats = CrawlStats()
        self.visited_urls: set[str] = set()
        self.kafka_producer = None
        
        logger.info(
            f"Scope-integrated crawler initialized for: {engagement_config.name}"
        )
    
    async def initialize(self) -> None:
        """Initialize crawler components."""
        await self.browser_pool.initialize()
        
        # Initialize Kafka if available
        try:
            self.kafka_producer = get_kafka_producer()
            logger.info("Kafka producer initialized")
        except Exception as e:
            logger.warning(f"Kafka not available: {e}")
    
    async def crawl(self, seed_urls: list[str]) -> dict:
        """
        Run the crawl with full scope enforcement.
        
        Args:
            seed_urls: Starting URLs
            
        Returns:
            Crawl results and statistics
        """
        logger.info(f"Starting scope-integrated crawl with {len(seed_urls)} seeds")
        
        # Validate and add seed URLs
        for url in seed_urls:
            if self.config.enforce_scope_at_frontier:
                if not self.scope_validator.is_allowed(url):
                    logger.warning(f"Seed URL out of scope: {url}")
                    self.stats.pages_skipped_scope += 1
                    continue
            
            item = FrontierItem(
                url=url,
                depth=0,
                source=SourceType.SEED,
                priority_score=1.0,
            )
            self.frontier.push(item)
        
        # Crawl loop
        tasks = []
        for _ in range(self.config.max_concurrent):
            task = asyncio.create_task(self._crawl_worker())
            tasks.append(task)
        
        # Wait for all workers to complete
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Generate results
        results = self._generate_results()
        
        logger.info(
            f"Crawl complete: {self.stats.pages_crawled} pages, "
            f"{self.stats.requests_blocked} blocked, "
            f"{self.stats.insertion_points_found} insertion points"
        )
        
        return results
    
    async def _crawl_worker(self) -> None:
        """Worker that processes URLs from the frontier."""
        async with self.browser_pool.scope_aware_session() as (context, page, interceptor):
            while self.stats.pages_crawled < self.config.max_pages:
                # Get next URL from frontier
                item = self.frontier.pop()
                if item is None:
                    await asyncio.sleep(0.5)
                    if self.frontier.is_empty():
                        break
                    continue
                
                url = item.url
                
                # Skip if already visited
                if url in self.visited_urls:
                    continue
                
                self.visited_urls.add(url)
                
                # Double-check scope (defense in depth)
                if self.config.enforce_scope_at_frontier:
                    if not self.scope_validator.is_allowed(url):
                        self.stats.pages_skipped_scope += 1
                        continue
                
                # Crawl the page
                try:
                    await self._crawl_page(page, url, item.depth)
                    self.stats.pages_crawled += 1
                except Exception as e:
                    logger.error(f"Error crawling {url}: {e}")
                    self.stats.errors += 1
            
            # Update stats from interceptor
            interceptor_stats = interceptor.get_stats()
            self.stats.requests_allowed += interceptor_stats["allowed_requests"]
            self.stats.requests_blocked += interceptor_stats["blocked_requests"]
    
    async def _crawl_page(self, page: Page, url: str, depth: int) -> None:
        """
        Crawl a single page.
        
        Args:
            page: Playwright page (with scope interception enabled)
            url: URL to crawl
            depth: Current depth
        """
        logger.debug(f"Crawling: {url} (depth {depth})")
        
        # Navigate (scope interceptor will block out-of-scope requests)
        try:
            response = await page.goto(
                url,
                timeout=self.config.page_timeout,
                wait_until="domcontentloaded",
            )
            
            if response is None:
                logger.warning(f"No response for {url}")
                return
            
            # Wait for page to settle
            await asyncio.sleep(self.config.wait_after_load / 1000)
            
            # Scroll for lazy-loaded content
            if self.config.scroll_for_lazy_load:
                await self._scroll_page(page)
            
            # Extract links and add to frontier
            if depth < self.config.max_depth:
                await self._extract_and_queue_links(page, url, depth)
            
            # Capture screenshot
            if self.config.capture_screenshots:
                screenshot_path = self.output_dir / "screenshots" / f"{hash(url)}.png"
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot_path))
            
        except Exception as e:
            logger.debug(f"Error navigating to {url}: {e}")
            raise
    
    async def _scroll_page(self, page: Page) -> None:
        """Scroll page to trigger lazy-loaded content."""
        for _ in range(self.config.max_scroll_attempts):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
    
    async def _extract_and_queue_links(self, page: Page, current_url: str, depth: int) -> None:
        """Extract links from page and add to frontier."""
        try:
            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(href => href && !href.startsWith('javascript:') && !href.startsWith('mailto:'));
            }""")
            
            for link in links:
                # Validate scope before adding to frontier
                if self.config.enforce_scope_at_frontier:
                    if not self.scope_validator.is_allowed(link):
                        continue
                
                if link not in self.visited_urls:
                    item = FrontierItem(
                        url=link,
                        depth=depth + 1,
                        source=SourceType.LINK,
                        priority_score=0.5,
                    )
                    self.frontier.push(item)
        
        except Exception as e:
            logger.debug(f"Error extracting links: {e}")
    
    def _generate_results(self) -> dict:
        """Generate crawl results."""
        browser_stats = self.browser_pool.get_all_stats()
        
        return {
            "engagement": self.engagement_config.name,
            "pages_crawled": self.stats.pages_crawled,
            "pages_skipped_scope": self.stats.pages_skipped_scope,
            "requests_allowed": browser_stats["allowed_requests"],
            "requests_blocked": browser_stats["blocked_requests"],
            "block_rate": browser_stats["block_rate"],
            "insertion_points_found": self.stats.insertion_points_found,
            "errors": self.stats.errors,
            "frontier_stats": self.frontier.get_stats(),
            "scope_validator_stats": self.scope_validator.get_stats(),
        }
    
    async def close(self) -> None:
        """Clean up resources."""
        await self.http_client.close()
        await self.browser_pool.close()
        
        if self.kafka_producer:
            self.kafka_producer.close()
