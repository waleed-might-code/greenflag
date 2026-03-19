"""
Session-Aware Crawl Orchestrator - Multi-role authenticated crawling with auto-repair

Extends the base orchestrator with:
- Multi-role session management
- Automatic session health checking and repair
- Role-tagged data capture
- Differential coverage (what each role can access)
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, List, Set
from dataclasses import dataclass

from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .frontier import CrawlFrontier, SourceType
from .state_flow import StateFlowDetector
from .api_discovery import APIDiscovery
from ..recon.insertion_point_extractor import InsertionPointExtractor
from ..recon.novelty_index import NoveltyIndex
from ..session_integration import SessionIntegration, EngagementConfig
from ..storage.warc_writer import WARCWriter


@dataclass
class RoleCrawlStats:
    """Statistics for a single role's crawl."""
    role: str
    pages_crawled: int = 0
    apis_discovered: int = 0
    unique_endpoints: int = 0
    session_repairs: int = 0
    auth_failures: int = 0
    start_time: float = 0.0
    end_time: float = 0.0


class SessionAwareCrawlOrchestrator:
    """
    Multi-role crawl orchestrator with session management.
    
    Crawls the target as multiple roles (admin, user, guest) and tracks
    what each role can access for differential authorization testing.
    """
    
    def __init__(
        self,
        base_url: str,
        engagement_config: EngagementConfig,
        max_depth: int = 10,
        max_pages_per_role: int = 5000,
        output_dir: Path = Path("outputs/crawl"),
        warc_dir: Path = Path("outputs/warc"),
    ):
        self.base_url = base_url
        self.engagement_config = engagement_config
        self.max_depth = max_depth
        self.max_pages_per_role = max_pages_per_role
        self.output_dir = Path(output_dir)
        self.warc_dir = Path(warc_dir)
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.warc_dir.mkdir(parents=True, exist_ok=True)
        
        # Per-role components
        self.frontiers: Dict[str, CrawlFrontier] = {}
        self.state_detectors: Dict[str, StateFlowDetector] = {}
        self.role_stats: Dict[str, RoleCrawlStats] = {}
        
        # Shared components
        self.api_discovery = APIDiscovery()
        self.insertion_extractor = InsertionPointExtractor()
        self.novelty_index = NoveltyIndex()
        
        # Session management
        self.session_integration: Optional[SessionIntegration] = None
        
        # WARC writers per role
        self.warc_writers: Dict[str, WARCWriter] = {}
        
        # Track what each role discovered
        self.role_endpoints: Dict[str, Set[str]] = {}
        
        # Browser instance
        self.browser: Optional[Browser] = None
    
    async def initialize(self):
        """Initialize session integration and components."""
        # Initialize session management
        self.session_integration = SessionIntegration(self.engagement_config)
        await self.session_integration.initialize()
        
        # Initialize per-role components
        for role in self.engagement_config.roles:
            self.frontiers[role] = CrawlFrontier(
                max_depth=self.max_depth,
                max_items=self.max_pages_per_role * 2
            )
            self.state_detectors[role] = StateFlowDetector()
            self.role_stats[role] = RoleCrawlStats(role=role)
            self.role_endpoints[role] = set()
            
            # Initialize WARC writer for this role
            warc_path = self.warc_dir / f"{self.engagement_config.engagement_id}_{role}.warc.gz"
            self.warc_writers[role] = WARCWriter(str(warc_path))
        
        logger.info(f"Initialized session-aware orchestrator for {len(self.engagement_config.roles)} roles")
    
    async def crawl_all_roles(self) -> Dict[str, RoleCrawlStats]:
        """
        Crawl as all configured roles in parallel.
        
        Returns:
            Dictionary of role -> statistics
        """
        logger.info(f"Starting multi-role crawl of {self.base_url}")
        logger.info(f"Roles: {', '.join(self.engagement_config.roles)}")
        
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=True)
            
            try:
                # Crawl each role in parallel
                tasks = [
                    self._crawl_as_role(role)
                    for role in self.engagement_config.roles
                ]
                
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # Analyze differential access
                await self._analyze_differential_access()
                
                # Export results
                await self._export_results()
                
            finally:
                await self.browser.close()
                await self.session_integration.cleanup()
                
                # Close WARC writers
                for writer in self.warc_writers.values():
                    writer.close()
        
        return self.role_stats

    
    async def _crawl_as_role(self, role: str):
        """
        Crawl as a specific role with session management.
        
        Args:
            role: Role name to crawl as
        """
        stats = self.role_stats[role]
        stats.start_time = time.time()
        
        logger.info(f"[{role}] Starting crawl")
        
        try:
            # Get session-aware browser context
            context, session = await self.session_integration.get_session_context(
                browser=self.browser,
                role=role
            )
            
            if not session.is_healthy:
                logger.warning(f"[{role}] Initial session unhealthy, attempting repair")
                page = await context.new_page()
                success, session = await self.session_integration.validate_and_repair_session(
                    browser=self.browser,
                    role=role,
                    page=page
                )
                await page.close()
                
                if not success:
                    logger.error(f"[{role}] Failed to establish healthy session, skipping")
                    stats.auth_failures += 1
                    return
            
            logger.info(f"[{role}] Session established successfully")
            
            # Seed frontier with base URL
            self.frontiers[role].add(
                url=self.base_url,
                depth=0,
                source=SourceType.SEED,
                feature_vector={"novelty": 1.0, "role": role}
            )
            
            # Create page for crawling
            page = await context.new_page()
            
            # Setup network interception for API discovery
            await self._setup_network_interception(page, role)
            
            # Crawl loop
            request_counter = 0
            while not self.frontiers[role].is_empty() and stats.pages_crawled < self.max_pages_per_role:
                # Check session health periodically
                if await self.session_integration.should_check_health(role):
                    is_healthy = await self._check_and_repair_session(role, page)
                    if not is_healthy:
                        logger.error(f"[{role}] Session repair failed, stopping crawl")
                        break
                
                # Get next URL from frontier
                item = self.frontiers[role].get_next()
                if not item:
                    break
                
                url = item.url
                depth = item.depth
                
                logger.debug(f"[{role}] Crawling {url} (depth={depth})")
                
                # Crawl the page
                await self._crawl_page(page, url, depth, role)
                
                stats.pages_crawled += 1
                request_counter += 1
                
                # Small delay to avoid overwhelming target
                await asyncio.sleep(0.1)
            
            await page.close()
            await context.close()
            
            stats.end_time = time.time()
            duration = stats.end_time - stats.start_time
            logger.info(f"[{role}] Crawl complete: {stats.pages_crawled} pages in {duration:.1f}s")
            
        except Exception as e:
            logger.error(f"[{role}] Crawl failed: {e}")
            import traceback
            traceback.print_exc()
            stats.end_time = time.time()
    
    async def _setup_network_interception(self, page: Page, role: str):
        """Setup network interception to capture API calls."""
        async def handle_request(route, request):
            # Let request proceed
            await route.continue_()
        
        async def handle_response(response):
            try:
                url = response.url
                method = response.request.method
                status = response.status
                
                # Track endpoint
                endpoint_key = f"{method} {url}"
                self.role_endpoints[role].add(endpoint_key)
                
                # Check novelty
                is_novel = self.novelty_index.check_and_update(
                    method=method,
                    url=url,
                    query_params=dict(response.request.headers),
                    body_structure={}
                )
                
                # Capture to WARC
                await self._capture_to_warc(response, role)
                
                # Extract insertion points if novel
                if is_novel:
                    await self._extract_insertion_points(response, role)
                
            except Exception as e:
                logger.debug(f"[{role}] Response handler error: {e}")
        
        # Register handlers
        await page.route("**/*", handle_request)
        page.on("response", handle_response)
    
    async def _check_and_repair_session(self, role: str, page: Page) -> bool:
        """
        Check session health and repair if needed.
        
        Returns:
            True if session is healthy, False otherwise
        """
        logger.debug(f"[{role}] Checking session health")
        
        success, session = await self.session_integration.validate_and_repair_session(
            browser=self.browser,
            role=role,
            page=page
        )
        
        if not success:
            self.role_stats[role].auth_failures += 1
            logger.warning(f"[{role}] Session repair failed")
            return False
        
        if session.repair_attempts > self.role_stats[role].session_repairs:
            self.role_stats[role].session_repairs = session.repair_attempts
            logger.info(f"[{role}] Session repaired successfully")
        
        return True

    
    async def _crawl_page(self, page: Page, url: str, depth: int, role: str):
        """
        Crawl a single page with state detection.
        
        Args:
            page: Playwright page
            url: URL to crawl
            depth: Current depth
            role: Role name
        """
        try:
            # Navigate to page
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            
            if not response:
                return
            
            # Check if we got redirected to login (session expired)
            if "/login" in page.url or "/signin" in page.url:
                logger.warning(f"[{role}] Redirected to login at {url}, session may be expired")
                self.role_stats[role].auth_failures += 1
                return
            
            # Compute DOM state hash
            dom_hash = await self._compute_dom_hash(page)
            
            # Check if this is a new state
            is_new_state = self.state_detectors[role].add_state(
                state_id=dom_hash,
                url=page.url,
                dom_hash=dom_hash
            )
            
            if is_new_state:
                self.role_stats[role].unique_endpoints += 1
            
            # Extract links and add to frontier
            links = await self._extract_links_from_page(page)
            
            for link in links:
                # Calculate priority based on novelty
                novelty_score = 1.0 if is_new_state else 0.3
                
                self.frontiers[role].add(
                    url=link,
                    depth=depth + 1,
                    source=SourceType.LINK,
                    feature_vector={
                        "novelty": novelty_score,
                        "role": role,
                        "depth": depth + 1
                    },
                    parent_url=url
                )
            
            # Discover interactive elements (forms, buttons)
            await self._discover_interactive_elements(page, role, depth)
            
        except Exception as e:
            logger.debug(f"[{role}] Failed to crawl {url}: {e}")
    
    async def _compute_dom_hash(self, page: Page) -> str:
        """Compute a hash of the meaningful DOM structure."""
        try:
            # Extract meaningful DOM structure (strip dynamic content)
            dom_structure = await page.evaluate("""
                () => {
                    const stripDynamic = (node) => {
                        if (node.nodeType === Node.TEXT_NODE) {
                            return node.textContent.trim() ? 'TEXT' : '';
                        }
                        if (node.nodeType !== Node.ELEMENT_NODE) return '';
                        
                        // Skip script, style, noscript
                        if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(node.tagName)) {
                            return '';
                        }
                        
                        let result = node.tagName;
                        
                        // Include important attributes
                        if (node.id) result += `#${node.id}`;
                        if (node.className) result += `.${node.className.split(' ').join('.')}`;
                        
                        // Recurse children
                        const children = Array.from(node.childNodes)
                            .map(stripDynamic)
                            .filter(s => s)
                            .join('|');
                        
                        return children ? `${result}[${children}]` : result;
                    };
                    
                    return stripDynamic(document.body);
                }
            """)
            
            # Hash the structure
            import hashlib
            return hashlib.sha256(dom_structure.encode()).hexdigest()[:16]
            
        except Exception as e:
            logger.debug(f"DOM hash computation failed: {e}")
            return "unknown"
    
    async def _extract_links_from_page(self, page: Page) -> List[str]:
        """Extract all links from the current page."""
        try:
            links = await page.evaluate("""
                () => {
                    const links = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        const href = a.href;
                        if (href && href.startsWith(window.location.origin)) {
                            links.push(href);
                        }
                    });
                    return [...new Set(links)];
                }
            """)
            return links
        except Exception as e:
            logger.debug(f"Link extraction failed: {e}")
            return []
    
    async def _discover_interactive_elements(self, page: Page, role: str, depth: int):
        """Discover forms, buttons, and other interactive elements."""
        try:
            # Find forms
            forms = await page.query_selector_all("form")
            
            for form in forms:
                action = await form.get_attribute("action")
                method = await form.get_attribute("method") or "GET"
                
                if action:
                    # Add form submission to frontier
                    self.frontiers[role].add(
                        url=action,
                        depth=depth + 1,
                        source=SourceType.FORM,
                        feature_vector={
                            "novelty": 0.8,
                            "role": role,
                            "type": "form",
                            "method": method
                        }
                    )
            
            # Find clickable elements that might trigger state changes
            clickables = await page.query_selector_all("button, [role='button'], [onclick]")
            
            # Sample a few to avoid state explosion
            for i, elem in enumerate(clickables[:5]):
                try:
                    # Record this as a potential state transition
                    selector = await self._get_selector(elem)
                    if selector:
                        self.state_detectors[role].add_transition(
                            from_state=await self._compute_dom_hash(page),
                            to_state="pending",
                            event_type="click",
                            selector=selector
                        )
                except Exception:
                    pass
                    
        except Exception as e:
            logger.debug(f"Interactive element discovery failed: {e}")

    
    async def _get_selector(self, element) -> Optional[str]:
        """Generate a CSS selector for an element."""
        try:
            selector = await element.evaluate("""
                (el) => {
                    if (el.id) return `#${el.id}`;
                    if (el.className) return `.${el.className.split(' ')[0]}`;
                    return el.tagName.toLowerCase();
                }
            """)
            return selector
        except Exception:
            return None
    
    async def _capture_to_warc(self, response, role: str):
        """Capture HTTP response to WARC file."""
        try:
            request = response.request
            
            # Build request data
            request_data = {
                "method": request.method,
                "url": response.url,
                "headers": dict(request.headers),
                "body": request.post_data if request.post_data else None
            }
            
            # Build response data
            try:
                body = await response.body()
            except Exception:
                body = b""
            
            response_data = {
                "status": response.status,
                "headers": dict(response.headers),
                "body": body
            }
            
            # Write to WARC
            warc_ref = self.warc_writers[role].write_request_response(
                request_data=request_data,
                response_data=response_data,
                metadata={
                    "engagement_id": self.engagement_config.engagement_id,
                    "role": role,
                    "timestamp": time.time()
                }
            )
            
            logger.debug(f"[{role}] Captured to WARC: {response.url}")
            
        except Exception as e:
            logger.debug(f"[{role}] WARC capture failed: {e}")
    
    async def _extract_insertion_points(self, response, role: str):
        """Extract insertion points from response."""
        try:
            request = response.request
            
            # Extract insertion points
            insertion_points = self.insertion_extractor.extract_from_request(
                method=request.method,
                url=response.url,
                headers=dict(request.headers),
                body=request.post_data
            )
            
            if insertion_points:
                self.role_stats[role].unique_endpoints += len(insertion_points)
                logger.debug(f"[{role}] Found {len(insertion_points)} insertion points in {response.url}")
            
        except Exception as e:
            logger.debug(f"[{role}] Insertion point extraction failed: {e}")
    
    async def _analyze_differential_access(self):
        """
        Analyze what each role can access vs others.
        Identifies potential authorization issues.
        """
        logger.info("Analyzing differential access across roles")
        
        roles = list(self.role_endpoints.keys())
        
        # Compare each role pair
        differential_findings = []
        
        for i, role_a in enumerate(roles):
            for role_b in roles[i+1:]:
                endpoints_a = self.role_endpoints[role_a]
                endpoints_b = self.role_endpoints[role_b]
                
                # Find endpoints accessible to both
                common = endpoints_a & endpoints_b
                
                # Find endpoints unique to each
                only_a = endpoints_a - endpoints_b
                only_b = endpoints_b - endpoints_a
                
                differential_findings.append({
                    "role_a": role_a,
                    "role_b": role_b,
                    "common_endpoints": len(common),
                    "only_role_a": len(only_a),
                    "only_role_b": len(only_b),
                    "overlap_percentage": len(common) / len(endpoints_a | endpoints_b) * 100 if endpoints_a | endpoints_b else 0
                })
                
                # Log potential issues
                if role_a == "admin" and only_b:
                    logger.warning(f"Found {len(only_b)} endpoints accessible to {role_b} but not admin - potential privilege escalation?")
                
                if role_b == "guest" and len(common) > len(only_a):
                    logger.warning(f"Guest role has access to {len(common)} endpoints also accessible to {role_a} - check authorization")
        
        # Save differential analysis
        import json
        diff_path = self.output_dir / "differential_access.json"
        with open(diff_path, 'w') as f:
            json.dump({
                "findings": differential_findings,
                "role_endpoints": {
                    role: list(endpoints)
                    for role, endpoints in self.role_endpoints.items()
                }
            }, f, indent=2)
        
        logger.info(f"Differential access analysis saved to {diff_path}")
    
    async def _export_results(self):
        """Export all crawl results."""
        import json
        
        logger.info("Exporting results")
        
        # Export per-role stats
        for role, stats in self.role_stats.items():
            role_dir = self.output_dir / role
            role_dir.mkdir(exist_ok=True)
            
            # Stats
            stats_path = role_dir / "stats.json"
            with open(stats_path, 'w') as f:
                json.dump({
                    "role": stats.role,
                    "pages_crawled": stats.pages_crawled,
                    "apis_discovered": stats.apis_discovered,
                    "unique_endpoints": stats.unique_endpoints,
                    "session_repairs": stats.session_repairs,
                    "auth_failures": stats.auth_failures,
                    "duration_seconds": stats.end_time - stats.start_time if stats.end_time else 0
                }, f, indent=2)
            
            # State graph
            state_graph_path = role_dir / "state_graph.json"
            self.state_detectors[role].export_to_json(str(state_graph_path))
            
            # Frontier stats
            frontier_stats = self.frontiers[role].get_stats()
            frontier_path = role_dir / "frontier_stats.json"
            with open(frontier_path, 'w') as f:
                json.dump(frontier_stats, f, indent=2)
        
        # Export novelty stats
        novelty_stats = self.novelty_index.get_stats()
        novelty_path = self.output_dir / "novelty_stats.json"
        with open(novelty_path, 'w') as f:
            json.dump({
                "total_requests": novelty_stats.total_requests,
                "unique_shapes": novelty_stats.unique_shapes,
                "novel_endpoints": novelty_stats.novel_endpoints,
                "duplicate_requests": novelty_stats.duplicate_requests,
                "top_novel": self.novelty_index.get_top_novel_endpoints(20)
            }, f, indent=2)
        
        # Export summary
        summary_path = self.output_dir / "crawl_summary.json"
        with open(summary_path, 'w') as f:
            json.dump({
                "engagement_id": self.engagement_config.engagement_id,
                "base_url": self.base_url,
                "roles": self.engagement_config.roles,
                "total_pages": sum(s.pages_crawled for s in self.role_stats.values()),
                "total_unique_endpoints": sum(s.unique_endpoints for s in self.role_stats.values()),
                "total_session_repairs": sum(s.session_repairs for s in self.role_stats.values()),
                "role_stats": {
                    role: {
                        "pages": stats.pages_crawled,
                        "endpoints": stats.unique_endpoints,
                        "repairs": stats.session_repairs
                    }
                    for role, stats in self.role_stats.items()
                }
            }, f, indent=2)
        
        logger.info(f"Results exported to {self.output_dir}")
