"""
Scope-enforcing HTTP client wrapper.
Blocks all out-of-scope requests before they hit the wire.
"""

import httpx
from typing import Optional
from loguru import logger

from cyberAI.governance import ScopeValidator


class ScopeEnforcingClient:
    """
    HTTP client that enforces scope validation.
    Wraps httpx.AsyncClient and blocks out-of-scope requests.
    
    Usage:
        async with ScopeEnforcingClient(validator) as client:
            response = await client.get("https://target.com/api/users")
            # Out-of-scope requests raise ScopeViolationError
    """
    
    def __init__(
        self,
        scope_validator: ScopeValidator,
        base_client: Optional[httpx.AsyncClient] = None,
        dry_run: bool = False,
    ):
        """
        Initialize scope-enforcing client.
        
        Args:
            scope_validator: ScopeValidator instance
            base_client: Optional httpx.AsyncClient to wrap
            dry_run: If True, log violations but don't block
        """
        self.validator = scope_validator
        self.client = base_client or httpx.AsyncClient()
        self.dry_run = dry_run
        self._blocked_count = 0
        self._allowed_count = 0
    
    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with scope enforcement."""
        # Validate scope
        if not self.validator.is_in_scope(url, method):
            self._blocked_count += 1
            
            if self.dry_run:
                logger.warning(f"[DRY RUN] Would block: {method} {url}")
                # In dry run, proceed anyway
            else:
                raise ScopeViolationError(f"Out of scope: {method} {url}")
        
        self._allowed_count += 1
        
        # Make request
        return await self.client.request(method, url, **kwargs)
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET request with scope enforcement."""
        return await self.request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST request with scope enforcement."""
        return await self.request("POST", url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT request with scope enforcement."""
        return await self.request("PUT", url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE request with scope enforcement."""
        return await self.request("DELETE", url, **kwargs)
    
    async def patch(self, url: str, **kwargs) -> httpx.Response:
        """PATCH request with scope enforcement."""
        return await self.request("PATCH", url, **kwargs)
    
    def get_stats(self) -> dict:
        """Get enforcement statistics."""
        return {
            "allowed": self._allowed_count,
            "blocked": self._blocked_count,
            "total": self._allowed_count + self._blocked_count,
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.client.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        return await self.client.__aexit__(exc_type, exc_val, exc_tb)
    
    async def aclose(self):
        """Close the client."""
        await self.client.aclose()


class ScopeViolationError(Exception):
    """Raised when a request violates engagement scope."""
    pass
