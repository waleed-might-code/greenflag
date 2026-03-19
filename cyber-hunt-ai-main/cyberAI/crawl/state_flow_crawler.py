"""
State-flow crawler with intelligent exploration and deduplication.
Implements Crawljax-style state exploration with priority-based frontier.
"""

import asyncio
from pathlib import Path
from typing import Optional, Any
from datetime import datetime
from uuid import uuid4

from playwright.async_api import Page, Browser, async_playwright
from loguru import logger

from .frontier import CrawlFrontier, FrontierItem, ActionType
from .dom_hasher import DOMHasher
from cyberAI.models import Route, Action, HttpMethod


class CrawlState:
    """Represents a discovered application state."""
    
    def __init__(
        self,
        state_id: str,
        url: str,
        dom_hash: str,
        simhash: int,
        screenshot_path: Optional[str] = None,
        depth: int = 0,
    ):
        self.state_id = state_id
        self.url = url
        self.dom_hash = dom_hash
        self.simhash = simhash
        self.screenshot_path = screenshot_path
        self.depth = depth
        self.discovered_at = datetime.utcnow()
        self.actions: list[Action] = []
        self.forms_count = 0
        self.inputs_count = 0
        self.links_count = 0
        self.api_calls_count = 0
    
    def to_route(self) -> Route:
        """Convert to Route model."""
        return Route(
            id=self.state_id,
            slug=self.url.split('/')[-1] or 'index',
            url=self.url,
            method=HttpMethod.GET,
            screenshot_path=self.screenshot_path,
            actions=self.actions,
            discovered_at=self.discovered_at,
        )


class StateFlowCrawler:
    """
    State-flow crawler with intelligent exploration.
    
    Features:
    - Priority-based frontier with attack surface scoring
    - SimHash-based state deduplication
    - Configurable state cap (default 10k)
    - Automatic pruning of low-value states
    """
    
    def __init__(
        self,
        target_url: str,
        max_states: int = 10000,
        max_depth: int = 10,
        screenshot_dir: Optional[Path] = None,
        headless: bool = True,
    ):
        """
        Initialize state-flow crawler.
        
        Args:
            target_url: Starting URL
            max_states: Maximum states to explore
            max_depth: Maximum depth from entry
            screenshot_dir: Directory for screenshots
            headless: Run browser in headless mode
        """
        self.target_url = target_url
        self.max_states = max_states
        self.max_depth = max_depth
        self.screenshot_dir = screenshot_dir or Path("outputs/crawl/screenshots")
        self.headless = headless
        
        self.frontier = CrawlFrontier(max_states=max_states, max_depth=max_depth)
        self.dom_hasher = DOMHasher(similarity_threshold=3)
        
        self.states: dict[str, CrawlState] = {}
        self.transitions: list[dict[str, Any]] = []
        
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
    
    async def crawl(self) -> dict[str, Any]:
        """
        Run the state-flow crawl.
        
        Returns:
            Crawl results with states, transitions, and statistics
        """
        logger.info(f"Starting state-flow crawl of {self.target_url}")
        logger.info(f"Max states: {self.max_states}, Max depth: {self.max_depth}")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            try:
                # Seed frontier with initial URL
                seed_item = FrontierItem(
                    url=self.target_url,
                    action_type=ActionType.NAVIGATE,
                    depth=0,
                    content_type_score=0.5,
                )
                self.frontier.push(seed_item)
                
                # Main crawl loop
                while not self.frontier.is_empty() and not self.frontier.should_stop():
                    item = self.frontier.pop()
                    if not item:
                        break
                    
                    await self._explore_state(page, item)
                    
                    # Periodic pruning to keep frontier manageable
                    if self.frontier.size() > 5000:
                        self.frontier.prune_low_priority(keep_top_n=2000)
                
                logger.info("Crawl completed")
                
            finally:
                await browser.close()
        
        return self._generate_results()
    
    async def _explore_state(self, page: Page, item: FrontierItem) -> None:
        """
        Explore a single state and discover new transitions.
        
        Args:
            page: Playwright page
            item: Frontier item to explore
        """
        try:
            # Navigate or perform action
            if item.action_type == ActionType.NAVIGATE:
                await page.goto(item.url, wait_until='networkidle', timeout=30000)
            elif item.action_type == ActionType.CLICK and item.selector:
                await page.click(item.selector, timeout=5000)
                await page.wait_for_load_state('networkidle', timeout=10000)
            elif item.action_type == ActionType.SUBMIT and item.selector:
                await page.click(item.selector, timeout=5000)
                await page.wait_for_load_state('networkidle', timeout=10000)
            
            # Wait for dynamic content
            await asyncio.sleep(1)
            
            # Get current state
            html = await page.content()
            url = page.url
            
            # Compute hashes
            simhash = self.dom_hasher.compute_simhash(html)
            dom_hash = self.dom_hasher.compute_sha256(html)
            
            # Check if state is new
            similar_state = self.dom_hasher.find_similar_state(simhash)
            if similar_state:
                logger.debug(f"State is similar to {similar_state}, skipping")
                return
            
            # Register new state
            state_id = str(uuid4())[:8]
            self.dom_hasher.register_state(simhash, state_id)
            
            # Take screenshot
            screenshot_path = self.screenshot_dir / f"state_{state_id}.png"
            await page.screenshot(path=str(screenshot_path), full_page=False)
            
            # Analyze page
            state = CrawlState(
                state_id=state_id,
                url=url,
                dom_hash=dom_hash,
                simhash=simhash,
                screenshot_path=str(screenshot_path),
                depth=item.depth,
            )
            
            # Discover actions and forms
            await self._discover_actions(page, state, item.depth)
            
            self.states[state_id] = state
            
            # Record transition
            if item.source_state_id:
                self.transitions.append({
                    'from_state': item.source_state_id,
                    'to_state': state_id,
                    'action_type': item.action_type.value,
                    'selector': item.selector,
                })
            
            logger.info(
                f"Discovered state {state_id}: {url[:60]} "
                f"(forms={state.forms_count}, inputs={state.inputs_count}, links={state.links_count})"
            )
            
        except Exception as e:
            logger.warning(f"Error exploring state: {e}")
    
    async def _discover_actions(self, page: Page, state: CrawlState, current_depth: int) -> None:
        """
        Discover clickable elements, forms, and links in current state.
        
        Args:
            page: Playwright page
            state: Current crawl state
            current_depth: Current depth in crawl tree
        """
        # Discover forms
        forms = await page.query_selector_all('form')
        state.forms_count = len(forms)
        
        for i, form in enumerate(forms[:10]):  # Limit to 10 forms per page
            submit_button = await form.query_selector('button[type="submit"], input[type="submit"]')
            if submit_button:
                selector = f'form:nth-of-type({i+1}) button[type="submit"], form:nth-of-type({i+1}) input[type="submit"]'
                
                # Count inputs in form
                inputs = await form.query_selector_all('input, textarea, select')
                input_count = len(inputs)
                
                state.actions.append(Action(
                    action_type='submit',
                    selector=selector,
                    form_fields=[],
                ))
                
                # Add to frontier
                item = FrontierItem(
                    url=state.url,
                    action_type=ActionType.SUBMIT,
                    selector=selector,
                    depth=current_depth + 1,
                    source_state_id=state.state_id,
                    has_forms=1,
                    has_inputs=input_count,
                    content_type_score=0.8,  # Forms are high value
                    novelty_score=1.0,
                )
                self.frontier.push(item)
        
        # Discover clickable buttons (non-submit)
        buttons = await page.query_selector_all('button:not([type="submit"]), a.btn, [role="button"]')
        for i, button in enumerate(buttons[:20]):  # Limit to 20 buttons
            try:
                text = await button.inner_text()
                text = text.strip()[:50]
                
                if not text:
                    continue
                
                selector = f'button:nth-of-type({i+1})'
                
                state.actions.append(Action(
                    action_type='click',
                    selector=selector,
                    text=text,
                ))
                
                # Score based on button text
                is_admin = any(kw in text.lower() for kw in ['admin', 'manage', 'delete', 'edit'])
                
                item = FrontierItem(
                    url=state.url,
                    action_type=ActionType.CLICK,
                    selector=selector,
                    depth=current_depth + 1,
                    source_state_id=state.state_id,
                    is_admin_path=is_admin,
                    content_type_score=0.6,
                )
                self.frontier.push(item)
                
            except Exception:
                continue
        
        # Discover links
        links = await page.query_selector_all('a[href]')
        state.links_count = len(links)
        
        for link in links[:30]:  # Limit to 30 links
            try:
                href = await link.get_attribute('href')
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue
                
                # Resolve relative URLs
                if href.startswith('/'):
                    from urllib.parse import urljoin
                    href = urljoin(state.url, href)
                
                # Only follow same-origin links
                if not href.startswith(self.target_url.split('/')[0] + '//' + self.target_url.split('/')[2]):
                    continue
                
                text = await link.inner_text()
                text = text.strip()[:50] if text else ''
                
                state.actions.append(Action(
                    action_type='navigate',
                    selector='',
                    text=text,
                    href=href,
                ))
                
                # Score based on URL path
                is_admin = any(kw in href.lower() for kw in ['/admin', '/manage', '/dashboard', '/api'])
                is_api = '/api/' in href.lower()
                
                item = FrontierItem(
                    url=href,
                    action_type=ActionType.NAVIGATE,
                    depth=current_depth + 1,
                    source_state_id=state.state_id,
                    is_admin_path=is_admin,
                    has_api_calls=1 if is_api else 0,
                    content_type_score=1.0 if is_api else 0.3,
                )
                self.frontier.push(item)
                
            except Exception:
                continue
        
        # Count inputs
        inputs = await page.query_selector_all('input, textarea, select')
        state.inputs_count = len(inputs)
    
    def _generate_results(self) -> dict[str, Any]:
        """Generate crawl results summary."""
        frontier_stats = self.frontier.get_stats()
        
        results = {
            'target_url': self.target_url,
            'states_discovered': len(self.states),
            'transitions_discovered': len(self.transitions),
            'unique_urls': len(set(s.url for s in self.states.values())),
            'total_forms': sum(s.forms_count for s in self.states.values()),
            'total_inputs': sum(s.inputs_count for s in self.states.values()),
            'total_links': sum(s.links_count for s in self.states.values()),
            'frontier_stats': frontier_stats,
            'states': [
                {
                    'state_id': s.state_id,
                    'url': s.url,
                    'depth': s.depth,
                    'forms': s.forms_count,
                    'inputs': s.inputs_count,
                    'links': s.links_count,
                    'screenshot': s.screenshot_path,
                }
                for s in self.states.values()
            ],
            'transitions': self.transitions,
        }
        
        logger.info(f"Crawl results: {results['states_discovered']} states, {results['transitions_discovered']} transitions")
        logger.info(f"Attack surface: {results['total_forms']} forms, {results['total_inputs']} inputs")
        
        return results
