"""
Comprehensive Crawl Orchestrator - Ties everything together.
Manages frontier, state detection, API discovery, and data extraction.
"""

import asyncio
import time
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from .api_discovery import APIDiscovery
from .frontier import CrawlFrontier, SourceType
from .state_flow import StateFlowDetector
from ..recon.insertion_point_extractor import InsertionPointExtractor
from ..recon.novelty_index import NoveltyIndex


class CrawlOrchestrator:
    """
    Orchestrates comprehensive crawling with:
    - Priority-based frontier
    - State-flow detection for SPAs
    - API discovery from specs and traffic
    - Insertion point extraction
    - Novelty tracking for prioritization
    """
    
    def __init__(
        self,
        base_url: str,
        max_depth: int = 10,
        max_pages: int = 10000,
        output_dir: Path = Path("outputs/crawl"),
    ):
        """
        Initialize crawl orchestrator.
        
        Args:
            base_url: Base URL to crawl
            max_depth: Maximum crawl depth
            max_pages: Maximum pages to crawl
            output_dir: Output directory for results
        """
        self.base_url = base_url
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Components
        self.frontier = CrawlFrontier(max_depth=max_depth, max_items=max_pages * 2)
        self.state_detector = StateFlowDetector()
        self.api_discovery = APIDiscovery()
        self.insertion_extractor = InsertionPointExtractor()
        self.novelty_index = NoveltyIndex()
        
        # HTTP client
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100),
        )
        
        # Statistics
        self.stats = {
            "pages_crawled": 0,
            "apis_discovered": 0,
            "states_discovered": 0,
            "insertion_points": 0,
            "start_time": 0.0,
            "end_time": 0.0,
        }
    
    async def crawl(self) -> dict:
        """
        Run comprehensive crawl.
        
        Returns:
            Statistics dictionary
        """
        self.stats["start_time"] = time.time()
        
        logger.info(f"Starting comprehensive crawl of {self.base_url}")
        logger.info(f"Max depth: {self.max_depth}, Max pages: {self.max_pages}")
        
        # Phase 1: API Discovery
        logger.info("Phase 1: API Discovery")
        await self._discover_apis()
        
        # Phase 2: Seed frontier
        logger.info("Phase 2: Seeding frontier")
        self._seed_frontier()
        
        # Phase 3: Crawl
        logger.info("Phase 3: Crawling")
        await self._crawl_loop()
        
        # Phase 4: Export results
        logger.info("Phase 4: Exporting results")
        self._export_results()
        
        self.stats["end_time"] = time.time()
        duration = self.stats["end_time"] - self.stats["start_time"]
        
        logger.success(f"Crawl complete in {duration:.2f}s")
        logger.info(f"Pages: {self.stats['pages_crawled']}")
        logger.info(f"APIs: {self.stats['apis_discovered']}")
        logger.info(f"States: {self.stats['states_discovered']}")
        logger.info(f"Insertion points: {self.stats['insertion_points']}")
        
        return self.stats
    
    async def _discover_apis(self) -> None:
        """Discover APIs from specs."""
        endpoints = await self.api_discovery.discover_from_base_url(
            self.base_url,
            self.client,
        )
        
        self.stats["apis_discovered"] = len(endpoints)
        
        # Add API endpoints to frontier with high priority
        for endpoint in endpoints:
            url = self.base_url.rstrip('/') + endpoint.path
            self.frontier.add(
                url=url,
                depth=0,
                source=SourceType.API_SPEC,
                feature_vector={
                    "content_type": "api",
                    "novelty": 1.0,
                },
            )
        
        logger.info(f"Discovered {len(endpoints)} API endpoints")
    
    def _seed_frontier(self) -> None:
        """Seed frontier with initial URLs."""
        # Add base URL
        self.frontier.add(
            url=self.base_url,
            depth=0,
            source=SourceType.SEED,
        )
        
        # Add common paths
        common_paths = [
            "/",
            "/api",
            "/admin",
            "/dashboard",
            "/login",
            "/register",
            "/profile",
            "/settings",
            "/search",
        ]
        
        for path in common_paths:
            url = self.base_url.rstrip('/') + path
            self.frontier.add(
                url=url,
                depth=1,
                source=SourceType.SEED,
            )
    
    async def _crawl_loop(self) -> None:
        """Main crawl loop."""
        while not self.frontier.is_empty() and self.stats["pages_crawled"] < self.max_pages:
            item = self.frontier.pop()
            if not item:
                break
            
            try:
                await self._crawl_url(item.url, item.depth)
            except Exception as e:
                logger.error(f"Error crawling {item.url}: {e}")
            
            # Rate limiting
            await asyncio.sleep(0.1)
    
    async def _crawl_url(self, url: str, depth: int) -> None:
        """Crawl a single URL."""
        logger.debug(f"Crawling: {url} (depth={depth})")
        
        try:
            response = await self.client.get(url)
            
            if response.status_code != 200:
                return
            
            self.stats["pages_crawled"] += 1
            
            # Extract insertion points
            canonical = self.insertion_extractor.extract(
                method="GET",
                url=url,
                headers=dict(response.headers),
                body=response.content,
                content_type=response.headers.get("content-type"),
            )
            
            # Record novelty
            is_novel = self.novelty_index.record(
                canonical.url_template,
                canonical.shape_hash,
            )
            
            self.stats["insertion_points"] += len(canonical.insertion_points)
            
            # State detection (for SPAs)
            if "text/html" in response.headers.get("content-type", ""):
                state, is_new_state = self.state_detector.record_state(
                    url=url,
                    dom=response.text,
                )
                
                if is_new_state:
                    self.stats["states_discovered"] += 1
            
            # Extract links and add to frontier
            if "text/html" in response.headers.get("content-type", ""):
                links = self._extract_links(response.text, url)
                
                for link in links:
                    novelty_score = 1.0 if is_novel else 0.3
                    
                    self.frontier.add(
                        url=link,
                        depth=depth + 1,
                        source=SourceType.LINK,
                        feature_vector={
                            "novelty": novelty_score,
                            "url": link,
                        },
                        parent_url=url,
                    )
        
        except Exception as e:
            logger.debug(f"Failed to crawl {url}: {e}")
    
    def _extract_links(self, html: str, base_url: str) -> list[str]:
        """Extract links from HTML."""
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlparse
        
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        
        for tag in soup.find_all(['a', 'link']):
            href = tag.get('href')
            if not href:
                continue
            
            # Resolve relative URLs
            absolute_url = urljoin(base_url, href)
            
            # Only include same-origin links
            if urlparse(absolute_url).netloc == urlparse(self.base_url).netloc:
                links.append(absolute_url)
        
        return links
    
    def _export_results(self) -> None:
        """Export crawl results."""
        import json
        
        # Export state graph
        state_graph_path = self.output_dir / "state_graph.json"
        self.state_detector.export_to_json(str(state_graph_path))
        
        # Export novelty stats
        novelty_stats = self.novelty_index.get_stats()
        novelty_path = self.output_dir / "novelty_stats.json"
        with open(novelty_path, 'w') as f:
            json.dump({
                "total_requests": novelty_stats.total_requests,
                "unique_shapes": novelty_stats.unique_shapes,
                "novel_endpoints": novelty_stats.novel_endpoints,
                "duplicate_requests": novelty_stats.duplicate_requests,
                "top_novel": self.novelty_index.get_top_novel_endpoints(20),
            }, f, indent=2)
        
        # Export frontier stats
        frontier_stats = self.frontier.get_stats()
        frontier_path = self.output_dir / "frontier_stats.json"
        with open(frontier_path, 'w') as f:
            json.dump(frontier_stats, f, indent=2)
        
        # Export overall stats
        stats_path = self.output_dir / "crawl_stats.json"
        with open(stats_path, 'w') as f:
            json.dump(self.stats, f, indent=2)
        
        logger.info(f"Results exported to {self.output_dir}")
    
    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
