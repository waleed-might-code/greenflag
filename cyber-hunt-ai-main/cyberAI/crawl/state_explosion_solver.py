"""
State Explosion Solver - Complete integration of all anti-explosion strategies.

This module solves Challenge #1: State explosion in state-flow crawling.

Solution components:
1. Priority queue for intelligent state expansion (attack surface contribution)
2. SimHash-based state clustering to merge visually equivalent states
3. Adaptive state caps that adjust based on attack surface density
4. Automatic pruning of low-value states when approaching limits
5. Real-time metrics and monitoring

Architecture:
- PriorityFrontier: Decides which state to explore next
- AdaptiveStateManager: Prevents explosion via clustering and pruning
- DOMHasher: Detects near-duplicate states
- Scope enforcement: Ensures all exploration stays in-scope
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4

from playwright.async_api import Page, Browser, async_playwright
from loguru import logger

from .priority_frontier import PriorityFrontier, FrontierItem, SourceType, FeatureVector
from .adaptive_state_manager import AdaptiveStateManager
from .dom_hasher import DOMHasher
from ..governance.engagement_config import EngagementConfig
from ..governance.scope_aware_browser import ScopeAwareBrowserPool
from ..models import Route, Action, HttpMethod


class StateExplosionSolver:
    """
    Production-grade state-flow crawler with complete state explosion prevention.
    
    Key features:
    - Caps at 10k states by default (configurable)
    - Priority-based exploration (high-value states first)
    - SimHash clustering merges similar states
    - Automatic pruning when 90% full
    - Adaptive caps based on attack surface density
    - Scope enforcement at browser level
    """
    
    def __init__(
        self,
        target_url: str,
        engagement_config: Optional[EngagementConfig] = None,
        max_states: int = 10000,
        max_depth: int = 10,
        max_concurrent: int = 3,
        screenshot_dir: Optional[Path] = None,
        headless: bool = True,
    ):
        """
        Initialize state explosion solver.
        
        Args:
            target_url: Starting URL
            engagement_config: Optional engagement config for scope enforcement
            max_states: Maximum states to explore (default 10k)
            max_depth: Maximum depth from entry
            max_concurrent: Max concurrent browser contexts
            screenshot_dir: Directory for screenshots
            headless: Run browser in headless mode
        """
        self.target_url = target_url
        self.engagement_config = engagement_config
        self.max_states = max_states
        self.max_depth = max_depth
        self.max_concurrent = max_concurrent
        self.screenshot_dir = screenshot_dir or Path("outputs/state_explosion/screenshots")
        self.headless = headless
        
        # Core components
        self.frontier = PriorityFrontier(max_size=max_states * 2)  # Allow 2x for queue
        self.state_manager = AdaptiveStateManager(
            initial_max_states=max_states,
            min_max_states=max(1000, max_states // 10),
            max_max_states=max_states * 2,
            clustering_threshold=5,  # SimHash hamming distance
            prune_threshold=0.9,  # Prune at 90% full
        )
        self.dom_hasher = DOMHasher(similarity_threshold=3)
        
        # Scope-aware browser pool if engagement config provided
        self.browser_pool = None
        if engagement_config:
            self.browser_pool = ScopeAwareBrowserPool(engagement_config)
        
        # Tracking
        self.visited_urls: set[str] = set()
        self.transitions: List[Dict[str, Any]] = []
        
        # Metrics
        self.metrics = {
            "states_explored": 0,
            "states_skipped_duplicate": 0,
            "states_skipped_scope": 0,
            "states_pruned": 0,
            "transitions_discovered": 0,
            "forms_found": 0,
            "inputs_found": 0,
            "api_calls_found": 0,
        }
        
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            f"StateExplosionSolver initialized: "
            f"max_states={max_states}, max_depth={max_depth}"
        )
    
    async def crawl(self) -> Dict[str, Any]:
        """
        Run state-flow crawl with explosion prevention.
        
        Returns:
            Crawl results with metrics
        """
        logger.info(f"Starting state-flow crawl: {self.target_url}")
        start_time = datetime.utcnow()
        
        # Initialize browser
        if self.browser_pool:
            await self.browser_pool.initialize()
            async with self.browser_pool.scope_aware_session() as (context, page, interceptor):
                await self._crawl_with_page(page)
        else:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="ASRTS-StateFlowCrawler/1.0",
                )
                page = await context.new_page()
                
                try:
                    await self._crawl_with_page(page)
                finally:
                    await context.close()
                    await browser.close()
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        # Generate results
        results = self._generate_results(duration)
        
        logger.info(
            f"Crawl complete: {results['states_explored']} states explored, "
            f"{results['states_clustered']} clustered, "
            f"{results['states_pruned']} pruned in {duration:.1f}s"
        )
        
        return results
    
    async def _crawl_with_page(self, page: Page) -> None:
        """Main crawl loop with a single page."""
        # Seed the frontier
        seed_item = FrontierItem(
            priority=1.0,
            url=self.target_url,
            method="GET",
            features=FeatureVector(
                source_type=SourceType.SEED,
                endpoint_novelty=1.0,
            ),
            depth=0,
        )
        self.frontier.push(seed_item)
        
        # Crawl loop
        while not self.frontier.is_empty():
            # Check if we should stop
            if self.state_manager.should_stop_crawl():
                logger.warning(
                    f"State cap reached: {self.state_manager.max_states} states"
                )
                break
            
            # Get next item
            item = self.frontier.pop()
            if not item:
                break
            
            # Skip if already visited
            if item.url in self.visited_urls:
                continue
            
            # Skip if too deep
            if item.depth > self.max_depth:
                continue
            
            # Explore this state
            try:
                await self._explore_state(page, item)
            except Exception as e:
                logger.debug(f"Error exploring {item.url}: {e}")
                continue
    
    async def _explore_state(self, page: Page, item: FrontierItem) -> None:
        """Explore a single state."""
        url = item.url
        depth = item.depth
        
        logger.debug(f"Exploring state: {url} (depth={depth})")
        
        # Navigate
        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            if not response or response.status >= 400:
                return
        except Exception as e:
            logger.debug(f"Navigation failed for {url}: {e}")
            return
        
        # Wait for dynamic content
        await asyncio.sleep(2)
        
        # Get HTML
        html = await page.content()
        
        # Compute hashes
        simhash = self.dom_hasher.compute_simhash(html)
        sha256 = self.dom_hasher.compute_sha256(html)
        
        # Check if state is new or similar to existing
        state_id = str(uuid4())[:8]
        
        # Extract attack surface metrics
        forms = await page.query_selector_all('form')
        inputs = await page.query_selector_all('input, textarea, select')
        links = await page.query_selector_all('a[href]')
        
        forms_count = len(forms)
        inputs_count = len(inputs)
        links_count = len(links)
        
        # Count API calls (from network activity)
        # Note: In production, use page.route() to intercept and count
        api_calls_count = 0
        
        # Register state with manager
        is_new = self.state_manager.register_state(
            state_id=state_id,
            url=url,
            simhash=simhash,
            sha256=sha256,
            forms_count=forms_count,
            inputs_count=inputs_count,
            api_calls_count=api_calls_count,
            depth=depth,
        )
        
        if not is_new:
            self.metrics["states_skipped_duplicate"] += 1
            logger.debug(f"State {url} is duplicate/similar, skipping")
            return
        
        # Mark as visited
        self.visited_urls.add(url)
        self.metrics["states_explored"] += 1
        self.metrics["forms_found"] += forms_count
        self.metrics["inputs_found"] += inputs_count
        
        # Capture screenshot
        screenshot_path = self.screenshot_dir / f"{state_id}.png"
        try:
            await page.screenshot(path=str(screenshot_path))
        except Exception:
            screenshot_path = None
        
        # Extract and queue links
        if depth < self.max_depth:
            await self._extract_and_queue_links(page, url, depth, links)
        
        # Extract and queue forms
        await self._extract_and_queue_forms(page, url, depth, forms)
        
        logger.debug(
            f"State {state_id} registered: "
            f"{forms_count} forms, {inputs_count} inputs, {links_count} links"
        )
    
    async def _extract_and_queue_links(
        self,
        page: Page,
        current_url: str,
        depth: int,
        links: List,
    ) -> None:
        """Extract links and add to frontier with priority."""
        for link in links:
            try:
                href = await link.get_attribute('href')
                if not href or href.startswith(('javascript:', 'mailto:', '#')):
                    continue
                
                # Make absolute
                if href.startswith('/'):
                    from urllib.parse import urljoin
                    href = urljoin(current_url, href)
                
                # Skip if already visited
                if href in self.visited_urls:
                    continue
                
                # Get link text for context
                text = await link.inner_text()
                text = text.strip()[:50] if text else ''
                
                # Build feature vector
                features = self._build_features_from_url(href, text)
                features.depth_from_root = depth + 1
                
                # Create frontier item
                item = FrontierItem(
                    priority=0.0,  # Will be computed by frontier
                    url=href,
                    method="GET",
                    features=features,
                    depth=depth + 1,
                    parent_url=current_url,
                    metadata={"link_text": text},
                )
                
                self.frontier.push(item)
                
            except Exception:
                continue
    
    async def _extract_and_queue_forms(
        self,
        page: Page,
        current_url: str,
        depth: int,
        forms: List,
    ) -> None:
        """Extract forms and add to frontier."""
        for form in forms:
            try:
                action = await form.get_attribute('action')
                method = await form.get_attribute('method') or 'GET'
                method = method.upper()
                
                if not action:
                    action = current_url
                elif action.startswith('/'):
                    from urllib.parse import urljoin
                    action = urljoin(current_url, action)
                
                # Build feature vector for form
                features = FeatureVector(
                    source_type=SourceType.FORM,
                    is_form=True,
                    endpoint_novelty=0.8,  # Forms are high value
                    depth_from_root=depth,
                )
                
                # Check for upload inputs
                inputs = await form.query_selector_all('input[type="file"]')
                if inputs:
                    features.has_upload = True
                
                item = FrontierItem(
                    priority=0.0,
                    url=action,
                    method=method,
                    features=features,
                    depth=depth,
                    parent_url=current_url,
                    metadata={"form": True},
                )
                
                self.frontier.push(item)
                
            except Exception:
                continue
    
    def _build_features_from_url(self, url: str, context: str = "") -> FeatureVector:
        """Build feature vector from URL analysis."""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        features = FeatureVector(source_type=SourceType.LINK)
        
        # API detection
        features.is_api = any(
            indicator in path
            for indicator in ['/api/', '/v1/', '/v2/', '/rest/', '/graphql']
        )
        
        # Admin path detection
        features.is_admin_path = any(
            pattern in path
            for pattern in ['/admin', '/dashboard', '/manage', '/console']
        )
        
        # Upload detection
        features.has_upload = any(
            pattern in path
            for pattern in ['/upload', '/file', '/attachment']
        )
        
        # Sensitive params
        query = parsed.query.lower()
        features.has_sensitive_params = any(
            param in query
            for param in ['password', 'token', 'secret', 'key', 'api_key']
        )
        
        # Novelty (simplified - in production, check against seen endpoints)
        features.endpoint_novelty = 0.5
        
        return features
    
    def _generate_results(self, duration: float) -> Dict[str, Any]:
        """Generate comprehensive results."""
        state_manager_metrics = self.state_manager.get_metrics()
        frontier_stats = self.frontier.get_stats()
        
        results = {
            # Basic stats
            "target_url": self.target_url,
            "duration_seconds": duration,
            "states_explored": self.metrics["states_explored"],
            "states_skipped_duplicate": self.metrics["states_skipped_duplicate"],
            "states_skipped_scope": self.metrics["states_skipped_scope"],
            
            # State explosion prevention metrics
            "states_clustered": state_manager_metrics["states_clustered"],
            "states_pruned": state_manager_metrics["states_pruned"],
            "clusters_created": state_manager_metrics["clusters_created"],
            "avg_cluster_size": state_manager_metrics["avg_cluster_size"],
            "deduplication_rate": state_manager_metrics["deduplication_rate"],
            
            # Attack surface
            "forms_found": self.metrics["forms_found"],
            "inputs_found": self.metrics["inputs_found"],
            "api_calls_found": self.metrics["api_calls_found"],
            "attack_surface_density": state_manager_metrics["attack_surface_density"],
            
            # Frontier stats
            "frontier_items_processed": frontier_stats["items_popped"],
            "frontier_items_skipped": frontier_stats["items_skipped_seen"],
            
            # Adaptive behavior
            "final_state_cap": state_manager_metrics["current_state_cap"],
            "state_cap_adjustments": state_manager_metrics["state_cap_adjustments"],
            
            # Efficiency
            "states_per_second": (
                self.metrics["states_explored"] / duration if duration > 0 else 0
            ),
            "explosion_prevented": (
                state_manager_metrics["states_clustered"] +
                state_manager_metrics["states_pruned"]
            ),
        }
        
        return results
    
    async def close(self) -> None:
        """Clean up resources."""
        if self.browser_pool:
            await self.browser_pool.close()
