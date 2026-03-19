"""
Enhanced crawler orchestrator for massive data collection.
Integrates priority frontier, insertion point extraction, and multi-source discovery.
"""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from ..governance.scope_validator import ScopeValidator
from ..insertion_points.extractor import InsertionPointExtractor
from .priority_frontier import PriorityFrontier, FrontierItem, SmartFrontierBuilder, SourceType
from .api_discovery import APIDiscoverer
from .form_extractor import FormExtractor
from .js_analyzer import JSAnalyzer


@dataclass
class CrawlConfig:
    """Configuration for crawler."""
    max_pages: int = 10000
    max_depth: int = 10
    max_concurrent: int = 5
    page_timeout: int = 30000
    wait_after_load: int = 2000
    enable_javascript: bool = True
    capture_screenshots: bool = True
    capture_network: bool = True
    extract_forms: bool = True
    extract_apis: bool = True
    extract_js_endpoints: bool = True
    scroll_for_lazy_load: bool = True
    max_scroll_attempts: int = 3


@dataclass
class CrawlStats:
    """Statistics for crawl session."""
    pages_crawled: int = 0
    apis_discovered: int = 0
    forms_found: int = 0
    js_endpoints_found: int = 0
    insertion_points_found: int = 0
    network_requests_captured: int = 0
    errors: int = 0
    scope_violations: int = 0


class EnhancedCrawler:
    """
    Enterprise-grade crawler for massive data collection.
    
    Features:
    - Priority-based frontier for intelligent crawling
    - Multi-source discovery (links, forms, APIs, JS, GraphQL)
    - Network traffic capture and analysis
    - Insertion point extraction
    - Scope enforcement
    - State-flow detection
    """
    
    def __init__(
        self,
        scope_validator: ScopeValidator,
        config: Optional[CrawlConfig] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize crawler.
        
        Args:
            scope_validator: Scope validator for enforcement
            config: Crawl configuration
            output_dir: Directory for outputs
        """
        self.scope_validator = scope_validator
        self.config = config or CrawlConfig()
        self.output_dir = output_dir or Path("outputs/crawl")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Core components
        self.frontier = PriorityFrontier(
            max_depth=self.config.max_depth,
            max_items=self.config.max_pages * 2,
        )
        self.insertion_extractor = InsertionPointExtractor()
        
        # Discovery modules
        self.api_discoverer = APIDiscoverer()
        self.form_extractor = FormExtractor()
        self.js_analyzer = JSAnalyzer()
        
        # State
        self.stats = CrawlStats()
        self.browser: Optional[Browser] = None
        self.contexts: list[BrowserContext] = []
        
        # Data collection
        self.captured_requests: list[dict] = []
        self.discovered_endpoints: set[str] = set()
        self.insertion_points_db: list[dict] = []
        
        logger.info(f"Enhanced crawler initialized with config: {self.config}")
    
    async def crawl(self, seed_urls: list[str], session_cookies: Optional[dict] = None):
        """
        Start crawling from seed URLs.
        
        Args:
            seed_urls: Initial URLs to crawl
            session_cookies: Optional session cookies for authenticated crawling
        """
        logger.info(f"Starting crawl with {len(seed_urls)} seed URLs")
        
        # Seed the frontier
        for url in seed_urls:
            if self.scope_validator.is_allowed(url):
                item = SmartFrontierBuilder.from_url(
                    url=url,
                    source_type=SourceType.SEED,
                    depth=0,
                    novelty_score=1.0,  # Seeds are always novel
                )
                self.frontier.add(item)
            else:
                logger.warning(f"Seed URL out of scope: {url}")
                self.stats.scope_violations += 1
        
        # Start browser
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=True)
            
            # Create browser context with session
            context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            
            if session_cookies:
                await context.add_cookies(session_cookies)
            
            self.contexts.append(context)
            
            # Crawl loop
            tasks = []
            for _ in range(self.config.max_concurrent):
                task = asyncio.create_task(self._crawl_worker(context))
                tasks.append(task)
            
            # Wait for all workers to complete
            await asyncio.gather(*tasks, return_exceptions=True)
            
            await context.close()
        
        # Save results
        await self._save_results()
        
        logger.info(f"Crawl complete. Stats: {self.stats.__dict__}")
    
    async def _crawl_worker(self, context: BrowserContext):
        """Worker that processes items from frontier."""
        page = await context.new_page()
        
        # Setup network capture
        if self.config.capture_network:
            page.on("request", lambda req: self._on_request(req))
            page.on("response", lambda resp: self._on_response(resp))
        
        try:
            while not self.frontier.is_empty() and self.stats.pages_crawled < self.config.max_pages:
                # Get next item
                item = self.frontier.pop()
                if not item:
                    await asyncio.sleep(0.1)
                    continue
                
                # Crawl page
                try:
                    await self._crawl_page(page, item)
                except Exception as e:
                    logger.error(f"Error crawling {item.url}: {e}")
                    self.stats.errors += 1
        
        finally:
            await page.close()
    
    async def _crawl_page(self, page: Page, item: FrontierItem):
        """Crawl a single page."""
        url = item.url
        logger.info(f"Crawling [{self.stats.pages_crawled + 1}/{self.config.max_pages}]: {url}")
        
        try:
            # Navigate
            response = await page.goto(
                url,
                wait_until="networkidle",
                timeout=self.config.page_timeout,
            )
            
            if not response:
                logger.warning(f"No response for {url}")
                return
            
            # Wait for dynamic content
            await asyncio.sleep(self.config.wait_after_load / 1000)
            
            # Scroll for lazy-loaded content
            if self.config.scroll_for_lazy_load:
                await self._scroll_page(page)
            
            # Extract data
            await self._extract_page_data(page, url, item.depth)
            
            self.stats.pages_crawled += 1
        
        except Exception as e:
            logger.error(f"Error processing page {url}: {e}")
            self.stats.errors += 1
    
    async def _scroll_page(self, page: Page):
        """Scroll page to trigger lazy loading."""
        for i in range(self.config.max_scroll_attempts):
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
            except Exception as e:
                logger.debug(f"Scroll attempt {i} failed: {e}")
                break
    
    async def _extract_page_data(self, page: Page, url: str, depth: int):
        """Extract all data from a page."""
        try:
            # Get page content
            content = await page.content()
            
            # Extract links
            links = await self._extract_links(page, url, depth)
            logger.debug(f"Found {len(links)} links on {url}")
            
            # Extract forms
            if self.config.extract_forms:
                forms = await self.form_extractor.extract_forms(page)
                self.stats.forms_found += len(forms)
                logger.debug(f"Found {len(forms)} forms on {url}")
                
                # Add form submission endpoints to frontier
                for form in forms:
                    form_url = urljoin(url, form.get("action", ""))
                    if self.scope_validator.is_allowed(form_url):
                        item = SmartFrontierBuilder.from_url(
                            url=form_url,
                            method=form.get("method", "POST").upper(),
                            source_type=SourceType.FORM,
                            depth=depth + 1,
                            parent_url=url,
                            novelty_score=0.8,
                        )
                        self.frontier.add(item)
            
            # Extract JS endpoints
            if self.config.extract_js_endpoints:
                js_endpoints = await self.js_analyzer.extract_endpoints(content, url)
                self.stats.js_endpoints_found += len(js_endpoints)
                logger.debug(f"Found {len(js_endpoints)} JS endpoints on {url}")
                
                # Add to frontier
                for endpoint in js_endpoints:
                    if self.scope_validator.is_allowed(endpoint):
                        item = SmartFrontierBuilder.from_url(
                            url=endpoint,
                            source_type=SourceType.XHR,
                            depth=depth + 1,
                            parent_url=url,
                            novelty_score=0.9,
                        )
                        self.frontier.add(item)
            
            # Extract API specs
            if self.config.extract_apis:
                api_endpoints = await self.api_discoverer.discover_from_page(page, url)
                self.stats.apis_discovered += len(api_endpoints)
                logger.debug(f"Found {len(api_endpoints)} API endpoints on {url}")
                
                # Add to frontier
                for endpoint in api_endpoints:
                    if self.scope_validator.is_allowed(endpoint):
                        item = SmartFrontierBuilder.from_url(
                            url=endpoint,
                            source_type=SourceType.API_SPEC,
                            depth=depth + 1,
                            parent_url=url,
                            novelty_score=1.0,  # APIs are high value
                        )
                        self.frontier.add(item)
            
            # Capture screenshot
            if self.config.capture_screenshots:
                screenshot_path = self.output_dir / "screenshots" / f"{self.stats.pages_crawled}.png"
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot_path), full_page=False)
        
        except Exception as e:
            logger.error(f"Error extracting data from {url}: {e}")
            self.stats.errors += 1
    
    async def _extract_links(self, page: Page, base_url: str, depth: int) -> list[str]:
        """Extract all links from page."""
        try:
            links = await page.evaluate("""
                () => {
                    const links = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        links.push(a.href);
                    });
                    return links;
                }
            """)
            
            # Add to frontier
            for link in links:
                # Resolve relative URLs
                absolute_url = urljoin(base_url, link)
                
                # Check scope
                if not self.scope_validator.is_allowed(absolute_url):
                    self.stats.scope_violations += 1
                    continue
                
                # Skip if already seen
                if self.frontier.has_seen(absolute_url):
                    continue
                
                # Add to frontier
                item = SmartFrontierBuilder.from_url(
                    url=absolute_url,
                    source_type=SourceType.LINK,
                    depth=depth + 1,
                    parent_url=base_url,
                    novelty_score=0.5,
                )
                self.frontier.add(item)
            
            return links
        
        except Exception as e:
            logger.error(f"Error extracting links: {e}")
            return []
    
    def _on_request(self, request):
        """Handle network request."""
        try:
            url = request.url
            
            # Check scope
            if not self.scope_validator.is_allowed(url):
                return
            
            # Capture request data
            request_data = {
                "url": url,
                "method": request.method,
                "headers": request.headers,
                "post_data": request.post_data,
                "resource_type": request.resource_type,
            }
            
            self.captured_requests.append(request_data)
            self.stats.network_requests_captured += 1
            
            # Extract insertion points
            if request.post_data:
                try:
                    _, insertion_points = self.insertion_extractor.extract_from_request(
                        method=request.method,
                        url=url,
                        headers=request.headers,
                        body=request.post_data.encode() if isinstance(request.post_data, str) else request.post_data,
                    )
                    
                    self.stats.insertion_points_found += len(insertion_points)
                    
                    # Store insertion points
                    for ip in insertion_points:
                        self.insertion_points_db.append(ip.to_dict())
                
                except Exception as e:
                    logger.debug(f"Error extracting insertion points: {e}")
        
        except Exception as e:
            logger.debug(f"Error handling request: {e}")
    
    def _on_response(self, response):
        """Handle network response."""
        try:
            url = response.url
            
            # Check scope
            if not self.scope_validator.is_allowed(url):
                return
            
            # Track discovered endpoints
            self.discovered_endpoints.add(f"{response.request.method} {url}")
        
        except Exception as e:
            logger.debug(f"Error handling response: {e}")
    
    async def _save_results(self):
        """Save crawl results to disk."""
        logger.info("Saving crawl results...")
        
        # Save captured requests
        requests_file = self.output_dir / "captured_requests.json"
        with open(requests_file, "w") as f:
            json.dump(self.captured_requests, f, indent=2)
        logger.info(f"Saved {len(self.captured_requests)} requests to {requests_file}")
        
        # Save insertion points
        ip_file = self.output_dir / "insertion_points.json"
        with open(ip_file, "w") as f:
            json.dump(self.insertion_points_db, f, indent=2)
        logger.info(f"Saved {len(self.insertion_points_db)} insertion points to {ip_file}")
        
        # Save discovered endpoints
        endpoints_file = self.output_dir / "discovered_endpoints.txt"
        with open(endpoints_file, "w") as f:
            for endpoint in sorted(self.discovered_endpoints):
                f.write(f"{endpoint}\n")
        logger.info(f"Saved {len(self.discovered_endpoints)} endpoints to {endpoints_file}")
        
        # Save stats
        stats_file = self.output_dir / "crawl_stats.json"
        with open(stats_file, "w") as f:
            json.dump({
                **self.stats.__dict__,
                "frontier_stats": self.frontier.get_stats(),
                "novelty_stats": self.insertion_extractor.get_novelty_stats(),
            }, f, indent=2)
        logger.info(f"Saved stats to {stats_file}")
        
        # Export novelty index
        novelty_file = self.output_dir / "novelty_index.json"
        self.insertion_extractor.export_novelty_index(str(novelty_file))
