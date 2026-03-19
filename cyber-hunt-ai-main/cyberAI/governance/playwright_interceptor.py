"""
Playwright request interceptor for scope enforcement.
Intercepts all browser requests and blocks out-of-scope URLs before they're sent.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from playwright.async_api import Page, Route, Request

from .scope_validator import ScopeValidator, ScopeDecision


@dataclass
class InterceptorStats:
    """Statistics for request interception."""
    total_requests: int = 0
    allowed_requests: int = 0
    blocked_requests: int = 0
    redirects_blocked: int = 0
    third_party_blocked: int = 0


class PlaywrightScopeInterceptor:
    """
    Fast Playwright request interceptor with scope enforcement.
    
    Uses page.route() to intercept ALL requests (navigation, XHR, fetch, images, etc.)
    and blocks out-of-scope requests before they hit the network.
    
    Performance: O(1) for domain check, O(n) for pattern matching where n = patterns.
    No network calls, no DB queries - pure in-memory validation.
    """
    
    def __init__(self, scope_validator: ScopeValidator, engagement_id: str):
        """
        Initialize interceptor.
        
        Args:
            scope_validator: Pre-compiled scope validator
            engagement_id: Engagement ID for logging
        """
        self.scope_validator = scope_validator
        self.engagement_id = engagement_id
        self.stats = InterceptorStats()
        self._lock = asyncio.Lock()
    
    async def intercept_request(self, route: Route, request: Request) -> None:
        """
        Intercept and validate a browser request.
        
        Args:
            route: Playwright route object
            request: Playwright request object
        """
        url = request.url
        method = request.method
        
        async with self._lock:
            self.stats.total_requests += 1
        
        # Fast scope check (synchronous, in-memory)
        result = self.scope_validator.is_in_scope(url, method)
        
        if result.decision == ScopeDecision.ALLOW:
            # Allow request to proceed
            async with self._lock:
                self.stats.allowed_requests += 1
            
            try:
                await route.continue_()
            except Exception as e:
                logger.debug(f"Error continuing route: {e}")
        
        else:
            # Block out-of-scope request
            async with self._lock:
                self.stats.blocked_requests += 1
                
                # Track reason
                if "redirect" in result.reason.lower():
                    self.stats.redirects_blocked += 1
                elif "domain" in result.reason.lower():
                    self.stats.third_party_blocked += 1
            
            logger.debug(
                f"[{self.engagement_id}] Blocked: {method} {url[:100]} - {result.reason}"
            )
            
            # Abort the request
            try:
                await route.abort("blockedbyclient")
            except Exception as e:
                logger.debug(f"Error aborting route: {e}")
    
    async def attach_to_page(self, page: Page) -> None:
        """
        Attach interceptor to a Playwright page.
        
        Args:
            page: Playwright page object
        """
        # Intercept ALL request types
        await page.route("**/*", self.intercept_request)
        logger.debug(f"[{self.engagement_id}] Scope interceptor attached to page")
    
    def get_stats(self) -> dict:
        """Get interception statistics."""
        return {
            "total_requests": self.stats.total_requests,
            "allowed_requests": self.stats.allowed_requests,
            "blocked_requests": self.stats.blocked_requests,
            "redirects_blocked": self.stats.redirects_blocked,
            "third_party_blocked": self.stats.third_party_blocked,
            "block_rate": (
                self.stats.blocked_requests / self.stats.total_requests
                if self.stats.total_requests > 0
                else 0.0
            ),
        }
