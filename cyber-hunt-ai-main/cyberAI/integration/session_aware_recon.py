"""
Integration: Adding Session Management to Existing Recon Module

This shows how to integrate the session management system into the existing
reconnaissance modules (core_discovery, role_discovery, etc.)
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page

from cyberAI.session_integration import SessionIntegration, EngagementConfig
from cyberAI.models import Route, Action, HttpMethod


class SessionAwareReconModule:
    """
    Base class for reconnaissance modules with session management.
    Extend your existing recon modules from this.
    """
    
    def __init__(
        self,
        session_integration: SessionIntegration,
        target_url: str,
        role: str = "guest"
    ):
        self.session_integration = session_integration
        self.target_url = target_url
        self.role = role
        self._request_count = 0
    
    async def get_page(self, browser: Browser) -> tuple[Page, BrowserContext]:
        """
        Get a page with session applied.
        Automatically handles session creation and validation.
        """
        context, session = await self.session_integration.get_session_context(
            browser=browser,
            role=self.role
        )
        
        page = await context.new_page()
        
        # Setup request interception for monitoring
        await self._setup_request_monitoring(page)
        
        return page, context
    
    async def _setup_request_monitoring(self, page: Page):
        """Setup request/response monitoring."""
        async def handle_request(route, request):
            self._request_count += 1
            await route.continue_()
        
        await page.route("**/*", handle_request)
    
    async def check_and_repair_session(self, browser: Browser, page: Page) -> bool:
        """
        Check session health and repair if needed.
        Call this periodically during long-running operations.
        """
        if await self.session_integration.should_check_health(self.role):
            logger.debug(f"Checking session health for {self.role}")
            
            success, session = await self.session_integration.validate_and_repair_session(
                browser=browser,
                role=self.role,
                page=page
            )
            
            if not success:
                logger.error(f"Session repair failed for {self.role}")
                return False
            
            logger.debug(f"Session healthy for {self.role}")
        
        return True


class SessionAwareCoreDiscovery(SessionAwareReconModule):
    """
    Enhanced core discovery with session management.
    Discovers routes while maintaining authenticated sessions.
    """
    
    async def discover_routes(
        self,
        browser: Browser,
        max_depth: int = 3
    ) -> List[Route]:
        """
        Discover application routes with session awareness.
        """
        page, context = await self.get_page(browser)
        discovered_routes = []
        
        try:
            # Start from target URL
            await page.goto(self.target_url, wait_until="networkidle")
            
            # Check session after navigation
            if not await self.check_and_repair_session(browser, page):
                logger.error("Session check failed, aborting discovery")
                return discovered_routes
            
            # Extract links and actions
            links = await self._extract_links(page)
            actions = await self._extract_actions(page)
            
            # Create route object
            route = Route(
                slug=page.url.split("/")[-1] or "index",
                url=page.url,
                method=HttpMethod.GET,
                actions=actions,
                role_context=self.role,
                page_title=await page.title()
            )
            
            discovered_routes.append(route)
            
            # Recursively discover linked routes
            for link in links[:10]:  # Limit for demo
                if not await self.check_and_repair_session(browser, page):
                    break
                
                try:
                    await page.goto(link, wait_until="networkidle", timeout=10000)
                    
                    sub_route = Route(
                        slug=link.split("/")[-1] or "page",
                        url=page.url,
                        method=HttpMethod.GET,
                        role_context=self.role,
                        page_title=await page.title()
                    )
                    
                    discovered_routes.append(sub_route)
                    
                except Exception as e:
                    logger.warning(f"Failed to discover {link}: {e}")
            
            logger.info(f"Discovered {len(discovered_routes)} routes as {self.role}")
            
        finally:
            await context.close()
        
        return discovered_routes
    
    async def _extract_links(self, page: Page) -> List[str]:
        """Extract all links from page."""
        links = await page.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(href => href.startsWith('http'));
            }
        """)
        return links
    
    async def _extract_actions(self, page: Page) -> List[Action]:
        """Extract interactive actions from page."""
        buttons = await page.query_selector_all("button, input[type='submit']")
        actions = []
        
        for button in buttons[:5]:  # Limit for demo
            text = await button.text_content()
            if text:
                actions.append(Action(
                    action_type="click",
                    selector=f"button:has-text('{text.strip()}')",
                    text=text.strip()
                ))
        
        return actions


class SessionAwareRoleDiscovery(SessionAwareReconModule):
    """
    Role-based discovery that compares what different roles can access.
    """
    
    async def compare_role_access(
        self,
        browser: Browser,
        roles: List[str],
        endpoints: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compare access to endpoints across multiple roles.
        
        Returns:
            Dict mapping endpoint -> role -> access_result
        """
        results = {}
        
        for endpoint in endpoints:
            results[endpoint] = {}
            
            for role in roles:
                # Switch role
                self.role = role
                
                page, context = await self.get_page(browser)
                
                try:
                    # Check session health
                    if not await self.check_and_repair_session(browser, page):
                        results[endpoint][role] = {
                            "accessible": False,
                            "error": "Session check failed"
                        }
                        continue
                    
                    # Try to access endpoint
                    response = await page.goto(
                        f"{self.target_url}{endpoint}",
                        wait_until="networkidle",
                        timeout=10000
                    )
                    
                    results[endpoint][role] = {
                        "accessible": response.ok,
                        "status": response.status,
                        "url": page.url,
                        "redirected": page.url != f"{self.target_url}{endpoint}"
                    }
                    
                except Exception as e:
                    results[endpoint][role] = {
                        "accessible": False,
                        "error": str(e)
                    }
                
                finally:
                    await context.close()
        
        return results


async def example_integration():
    """
    Example showing how to use session-aware recon modules.
    """
    from playwright.async_api import async_playwright
    from cyberAI.session_integration import create_session_integration
    
    # Setup session integration
    session_integration = await create_session_integration(
        engagement_id="recon-integration-demo",
        roles=["guest", "user", "admin"],
        login_sequences_dir=Path("login_sequences"),
        credentials={
            "guest": {},
            "user": {"username": "user@example.com", "password": "pass123"},
            "admin": {"username": "admin@example.com", "password": "adminpass"}
        },
        validation_url="/api/me"
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        try:
            # Discover routes as admin
            admin_discovery = SessionAwareCoreDiscovery(
                session_integration=session_integration,
                target_url="https://example.com",
                role="admin"
            )
            
            admin_routes = await admin_discovery.discover_routes(browser, max_depth=2)
            logger.info(f"Admin discovered {len(admin_routes)} routes")
            
            # Compare role access
            role_discovery = SessionAwareRoleDiscovery(
                session_integration=session_integration,
                target_url="https://example.com",
                role="guest"
            )
            
            endpoints = ["/dashboard", "/admin", "/api/users", "/profile"]
            access_matrix = await role_discovery.compare_role_access(
                browser=browser,
                roles=["guest", "user", "admin"],
                endpoints=endpoints
            )
            
            # Print access matrix
            logger.info("\nAccess Matrix:")
            for endpoint, role_results in access_matrix.items():
                logger.info(f"\n{endpoint}:")
                for role, result in role_results.items():
                    accessible = result.get("accessible", False)
                    status = result.get("status", "N/A")
                    logger.info(f"  {role}: {'✓' if accessible else '✗'} (status: {status})")
        
        finally:
            await browser.close()
            await session_integration.cleanup()


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_integration())
