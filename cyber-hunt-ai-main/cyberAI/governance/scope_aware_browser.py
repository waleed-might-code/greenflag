"""
Scope-aware browser pool that enforces engagement scope at the Playwright level.
Wraps the standard browser pool with automatic scope interception.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from loguru import logger
from playwright.async_api import BrowserContext, Page

from ..utils.browser import BrowserPool, get_browser_pool
from .engagement_config import EngagementConfig
from .scope_validator import ScopeValidator
from .playwright_interceptor import PlaywrightScopeInterceptor


class ScopeAwareBrowserPool:
    """
    Browser pool with automatic scope enforcement.
    
    Every page created through this pool has scope interception enabled,
    ensuring no out-of-scope requests are sent.
    """
    
    def __init__(self, engagement_config: EngagementConfig):
        """
        Initialize scope-aware browser pool.
        
        Args:
            engagement_config: Engagement configuration with scope rules
        """
        self.engagement_config = engagement_config
        self.scope_validator = ScopeValidator(
            target_domains=engagement_config.target_domains,
            out_of_scope_patterns=engagement_config.out_of_scope_patterns,
            allowed_schemes=engagement_config.allowed_schemes,
        )
        self.browser_pool = get_browser_pool()
        self._interceptors: dict[str, PlaywrightScopeInterceptor] = {}
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Scope-aware browser pool initialized for engagement: {engagement_config.name}"
        )
    
    async def initialize(self) -> None:
        """Initialize underlying browser pool."""
        await self.browser_pool.initialize()
    
    async def get_scope_aware_context(
        self,
        role: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> BrowserContext:
        """
        Get a browser context with scope enforcement.
        
        Args:
            role: Role for this context (e.g., "admin", "user")
            proxy: Optional proxy server
            
        Returns:
            BrowserContext with scope interception enabled
        """
        context = await self.browser_pool.get_browser_context(role=role, proxy=proxy)
        return context
    
    async def get_scope_aware_page(
        self,
        context: BrowserContext,
        page_id: Optional[str] = None,
    ) -> tuple[Page, PlaywrightScopeInterceptor]:
        """
        Create a new page with scope interception.
        
        Args:
            context: Browser context
            page_id: Optional page identifier for tracking
            
        Returns:
            Tuple of (Page, PlaywrightScopeInterceptor)
        """
        page = await context.new_page()
        
        # Create and attach interceptor
        page_id = page_id or f"page_{id(page)}"
        interceptor = PlaywrightScopeInterceptor(
            scope_validator=self.scope_validator,
            engagement_id=self.engagement_config.engagement_id,
        )
        
        await interceptor.attach_to_page(page)
        
        async with self._lock:
            self._interceptors[page_id] = interceptor
        
        return page, interceptor
    
    @asynccontextmanager
    async def scope_aware_session(
        self,
        role: Optional[str] = None,
        proxy: Optional[str] = None,
    ):
        """
        Context manager for a scope-aware browser session.
        
        Args:
            role: Role for this session
            proxy: Optional proxy server
            
        Yields:
            Tuple of (BrowserContext, Page, PlaywrightScopeInterceptor)
        """
        context = await self.get_scope_aware_context(role=role, proxy=proxy)
        page, interceptor = await self.get_scope_aware_page(context)
        
        try:
            yield context, page, interceptor
        finally:
            # Log stats before closing
            stats = interceptor.get_stats()
            logger.info(
                f"Session stats: {stats['allowed_requests']} allowed, "
                f"{stats['blocked_requests']} blocked "
                f"({stats['block_rate']:.1%} block rate)"
            )
            
            await page.close()
            await context.close()
    
    def get_all_stats(self) -> dict:
        """Get aggregated statistics from all interceptors."""
        total_stats = {
            "total_requests": 0,
            "allowed_requests": 0,
            "blocked_requests": 0,
            "redirects_blocked": 0,
            "third_party_blocked": 0,
        }
        
        for interceptor in self._interceptors.values():
            stats = interceptor.get_stats()
            for key in total_stats:
                if key in stats:
                    total_stats[key] += stats[key]
        
        if total_stats["total_requests"] > 0:
            total_stats["block_rate"] = (
                total_stats["blocked_requests"] / total_stats["total_requests"]
            )
        else:
            total_stats["block_rate"] = 0.0
        
        return total_stats
    
    async def close(self) -> None:
        """Close browser pool and log final stats."""
        stats = self.get_all_stats()
        logger.info(
            f"Final scope enforcement stats: "
            f"{stats['total_requests']} total requests, "
            f"{stats['blocked_requests']} blocked ({stats['block_rate']:.1%})"
        )
        
        await self.browser_pool.close()
