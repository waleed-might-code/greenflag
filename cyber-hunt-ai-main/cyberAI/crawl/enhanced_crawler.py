"""
Enhanced State-Flow Crawler with Adaptive State Management.
Designed for massive-scale data extraction with intelligent deduplication.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page, Browser, async_playwright
from loguru import logger

from .adaptive_state_manager import AdaptiveStateManager
from .frontier import CrawlFrontier, FrontierItem, ActionType
from .dom_hasher import DOMHasher
from ..insertion_points import NestedInsertionPointExtractor, NoveltyTracker
from ..storage.warc_writer import WARCWriter


class EnhancedCrawler:
    """
    Enhanced crawler for massive-scale data extraction.
    
    Features:
    - Adaptive state management (prevents explosion)
    - SimHash-based deduplication
    - Attack surface prioritization
    - WARC evidence storage
    - Real-time metrics
    - API traffic capture
    """
    
    def __init__(
        self,
        target_url: str,
        engagement_id: str,
        max_states: int = 10000,
        max_depth: int = 10,
        output_dir: Optional[Path] = None,
        headless: bool = True,
    ):
        """
        Initialize enhanced crawler.
        
        Args:
            target_url: Target URL to crawl
            engagement_id: Engagement identifier
            max_states: Initial maximum states
            max_depth: Maximum crawl depth
            output_dir: Output directory
            headless: Run browser headless
        """
        self.target_url = target_url
        self.engagement_id = engagement_id
        self.max_depth = max_depth
        self.headless = headless
        
        # Output setup
        self.output_dir = output_dir or Path(f"outputs/crawl/{engagement_id}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir = self.output_dir / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)
        
        # Core components
        self.state_manager = AdaptiveStateManager(
            initial_max_states=max_states,
            clustering_threshold=5,
        )
        self.frontier = CrawlFrontier(max_states=max_states * 2, max_depth=max_depth)
        self.dom_hasher = DOMHasher(similarity_threshold=3)
        self.insertion_extractor = NestedInsertionPointExtractor(max_depth=3)
        self.novelty_tracker = NoveltyTracker()
        
        # WARC writer for evidence
        warc_dir = self.output_dir / "warc"
        warc_dir.mkdir(exist_ok=True)
        self.warc_writer = WARCWriter(
            output_dir=warc_dir,
            engagement_id=engagement_id,
        )
        
        # Metrics
        self.metrics = {
            'start_time': None,
            'end_time': None,
            'pages_crawled': 0,
            'api_calls_captured': 0,
            'forms_discovered': 0,
            'inputs_discovered': 0,
            'insertion_points_found': 0,
            'bytes_captured': 0,
            'warc_records_written': 0,
        }
        
        # Network traffic capture
        self.captured_requests: List[Dict] = []
    
    async def crawl(self) -> Dict[str, Any]:
        """
        Run comprehensive crawl with massive data extraction.
        
        Returns:
            Crawl results and metrics
        """
        self.metrics['start_time'] = datetime.utcnow().isoformat()
        
        logger.info(f"🚀 Starting enhanced crawl: {self.target_url}")
        logger.info(f"   Engagement: {self.engagement_id}")
        logger.info(f"   Max states: {self.state_manager.max_states}")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='CyberHuntAI/2.0 (Security Scanner)',
            )
            
            # Setup network interception
            context.on('request', self._on_request)
            context.on('response', self._on_response)
            
            page = await context.new_page()
            
            # Seed frontier with initial URL
            self.frontier.push(FrontierItem(
                url=self.target_url,
                action_type=ActionType.NAVIGATE,
                depth=0,
                content_type_score=1.0,
            ))
            
            # Main crawl loop
            while not self.frontier.is_empty() and not self.state_manager.should_stop_crawl():
                item = self.frontier.pop()
                if not item:
                    break
                
                await self._explore_state(page, item)
                
                # Periodic metrics logging
                if self.metrics['pages_crawled'] % 100 == 0:
                    self._log_progress()
            
            await browser.close()
        
        # Finalize
        self.metrics['end_time'] = datetime.utcnow().isoformat()
        results = self._generate_results()
        self._export_results(results)
        
        logger.info("✅ Crawl complete!")
        self._log_final_stats()
        
        return results
    
    async def _explore_state(self, page: Page, item: FrontierItem) -> None:
        """Explore a single state."""
        try:
            # Navigate to URL
            response = await page.goto(item.url, wait_until='networkidle', timeout=30000)
            if not response:
                return
            
            self.metrics['pages_crawled'] += 1
            
            # Get DOM content
            html = await page.content()
            
            # Compute hashes
            simhash = self.dom_hasher.compute_simhash(html)
            dom_hash = self.dom_hasher.compute_sha256(html)
            
            # Extract attack surface metrics
            forms = await page.query_selector_all('form')
            inputs = await page.query_selector_all('input, textarea, select')
            
            forms_count = len(forms)
            inputs_count = len(inputs)
            
            self.metrics['forms_discovered'] += forms_count
            self.metrics['inputs_discovered'] += inputs_count
            
            # Calculate attack surface score
            attack_surface_score = (
                forms_count * 15.0 +
                inputs_count * 10.0 +
                len(self.captured_requests) * 5.0
            )
            
            # Check if we should accept this state
            should_accept, cluster_id = self.state_manager.should_accept_state(
                state_id=dom_hash,
                simhash=simhash,
                attack_surface_score=attack_surface_score,
            )
            
            if not should_accept:
                logger.debug(f"State rejected or clustered: {item.url[:60]}")
                return
            
            # Register new state
            state_id = dom_hash
            cluster_id = self.state_manager.register_state(
                state_id=state_id,
                simhash=simhash,
                url=item.url,
                forms_count=forms_count,
                inputs_count=inputs_count,
                api_calls_count=len(self.captured_requests),
            )
            
            # Take screenshot
            screenshot_path = self.screenshot_dir / f"{state_id[:12]}.png"
            await page.screenshot(path=screenshot_path, full_page=False)
            
            # Write to WARC
            warc_ref = await self._write_to_warc(item.url, html, response)
            
            # Extract insertion points
            await self._extract_insertion_points(item.url, html, forms)
            
            # Discover new states
            await self._discover_new_states(page, item, forms_count, inputs_count)
            
        except Exception as e:
            logger.debug(f"Error exploring {item.url}: {e}")
    
    async def _write_to_warc(self, url: str, html: str, response: Any) -> str:
        """Write capture to WARC."""
        try:
            # Build request/response for WARC
            request_data = {
                'method': 'GET',
                'url': url,
                'headers': {},
            }
            
            response_data = {
                'status': response.status if response else 200,
                'headers': response.headers if response else {},
                'body': html.encode('utf-8'),
            }
            
            warc_ref = self.warc_writer.write_request_response(
                request_data,
                response_data,
            )
            
            self.metrics['bytes_captured'] += len(html)
            self.metrics['warc_records_written'] += 1
            
            return warc_ref
            
        except Exception as e:
            logger.debug(f"WARC write error: {e}")
            return ""
    
    async def _extract_insertion_points(
        self,
        url: str,
        html: str,
        forms: List,
    ) -> None:
        """Extract insertion points from page."""
        try:
            # Extract from forms
            for form in forms:
                form_html = await form.inner_html()
                points = self.insertion_extractor.extract_from_html(form_html)
                
                for point in points:
                    is_novel = self.novelty_tracker.is_novel(point)
                    if is_novel:
                        self.metrics['insertion_points_found'] += 1
                        
        except Exception as e:
            logger.debug(f"Insertion point extraction error: {e}")
    
    async def _discover_new_states(
        self,
        page: Page,
        current_item: FrontierItem,
        forms_count: int,
        inputs_count: int,
    ) -> None:
        """Discover new states from current page."""
        try:
            # Extract links
            links = await page.query_selector_all('a[href]')
            
            for link in links[:50]:  # Limit to avoid explosion
                try:
                    href = await link.get_attribute('href')
                    if not href:
                        continue
                    
                    # Resolve relative URLs
                    absolute_url = urljoin(current_item.url, href)
                    
                    # Only same-origin
                    if not self._is_same_origin(absolute_url):
                        continue
                    
                    # Score the link
                    text = await link.inner_text()
                    is_admin = any(kw in absolute_url.lower() for kw in [
                        '/admin', '/api', '/dashboard', '/manage', '/settings'
                    ])
                    is_api = '/api/' in absolute_url.lower()
                    
                    # Create frontier item
                    item = FrontierItem(
                        url=absolute_url,
                        action_type=ActionType.NAVIGATE,
                        depth=current_item.depth + 1,
                        source_state_id=current_item.url,
                        has_forms=forms_count,
                        has_inputs=inputs_count,
                        is_admin_path=is_admin,
                        has_api_calls=1 if is_api else 0,
                        content_type_score=1.0 if is_api else 0.5,
                        novelty_score=1.0,
                    )
                    
                    self.frontier.push(item)
                    
                except Exception:
                    continue
                    
        except Exception as e:
            logger.debug(f"State discovery error: {e}")
    
    def _is_same_origin(self, url: str) -> bool:
        """Check if URL is same origin as target."""
        target_parsed = urlparse(self.target_url)
        url_parsed = urlparse(url)
        return target_parsed.netloc == url_parsed.netloc
    
    def _on_request(self, request: Any) -> None:
        """Capture outgoing requests."""
        try:
            if request.resource_type in ['xhr', 'fetch']:
                self.captured_requests.append({
                    'url': request.url,
                    'method': request.method,
                    'headers': request.headers,
                    'timestamp': datetime.utcnow().isoformat(),
                })
                self.metrics['api_calls_captured'] += 1
        except Exception:
            pass
    
    def _on_response(self, response: Any) -> None:
        """Capture responses."""
        # Could extract more data here
        pass
    
    def _log_progress(self) -> None:
        """Log crawl progress."""
        state_metrics = self.state_manager.get_metrics()
        frontier_stats = self.frontier.get_stats()
        
        logger.info(
            f"📊 Progress: {self.metrics['pages_crawled']} pages | "
            f"{state_metrics['unique_states_kept']} states | "
            f"{state_metrics['clusters_created']} clusters | "
            f"{self.metrics['insertion_points_found']} insertion points"
        )
    
    def _log_final_stats(self) -> None:
        """Log final statistics."""
        state_metrics = self.state_manager.get_metrics()
        
        logger.info("=" * 80)
        logger.info("📈 FINAL STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Pages crawled: {self.metrics['pages_crawled']}")
        logger.info(f"Unique states: {state_metrics['unique_states_kept']}")
        logger.info(f"States clustered: {state_metrics['states_clustered']}")
        logger.info(f"Deduplication rate: {state_metrics['deduplication_rate']:.1f}%")
        logger.info(f"Forms discovered: {self.metrics['forms_discovered']}")
        logger.info(f"Inputs discovered: {self.metrics['inputs_discovered']}")
        logger.info(f"Insertion points: {self.metrics['insertion_points_found']}")
        logger.info(f"API calls captured: {self.metrics['api_calls_captured']}")
        logger.info(f"Data captured: {self.metrics['bytes_captured'] / 1024 / 1024:.2f} MB")
        logger.info(f"WARC records: {self.metrics['warc_records_written']}")
        logger.info("=" * 80)
    
    def _generate_results(self) -> Dict[str, Any]:
        """Generate final results."""
        state_metrics = self.state_manager.get_metrics()
        frontier_stats = self.frontier.get_stats()
        novelty_stats = self.novelty_tracker.get_stats()
        
        return {
            'engagement_id': self.engagement_id,
            'target_url': self.target_url,
            'metrics': self.metrics,
            'state_management': state_metrics,
            'frontier': frontier_stats,
            'novelty': novelty_stats,
            'high_value_clusters': [
                {
                    'cluster_id': c.cluster_id,
                    'size': c.get_size(),
                    'attack_surface_score': c.attack_surface_score,
                    'forms': c.forms_count,
                    'inputs': c.inputs_count,
                }
                for c in self.state_manager.get_high_value_clusters(20)
            ],
        }
    
    def _export_results(self, results: Dict[str, Any]) -> None:
        """Export results to JSON."""
        results_path = self.output_dir / "crawl_results.json"
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results exported to {results_path}")
