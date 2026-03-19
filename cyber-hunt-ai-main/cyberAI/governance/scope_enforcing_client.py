"""
Scope-enforcing HTTP client wrapper.
Intercepts all requests and validates against engagement scope before sending.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger

from .engagement_config import EngagementConfig
from .scope_validator import ScopeDecision, ScopeValidator

# Handle imports for both module and standalone usage
try:
    from ..models import RequestRecord
    from ..utils.http_client import AsyncHTTPClient
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from models import RequestRecord
    from utils.http_client import AsyncHTTPClient


@dataclass
class ScopeViolation(Exception):
    """Raised when a request violates scope."""
    url: str
    reason: str
    matched_pattern: Optional[str] = None
    
    def __str__(self) -> str:
        msg = f"Scope violation: {self.url} - {self.reason}"
        if self.matched_pattern:
            msg += f" (pattern: {self.matched_pattern})"
        return msg


@dataclass
class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    limit_type: str
    current_rate: float
    limit: float
    
    def __str__(self) -> str:
        return f"Rate limit exceeded: {self.limit_type} - {self.current_rate:.2f} > {self.limit}"


class RateLimiter:
    """
    Token bucket rate limiter for per-host and global rate limiting.
    """
    
    def __init__(self, per_host_rps: int, global_rps: int):
        self.per_host_rps = per_host_rps
        self.global_rps = global_rps
        
        # Token buckets: host -> (tokens, last_refill_time)
        self._host_buckets: dict[str, tuple[float, float]] = defaultdict(lambda: (per_host_rps, time.time()))
        self._global_bucket: tuple[float, float] = (global_rps, time.time())
        self._lock = asyncio.Lock()
    
    async def acquire(self, host: str) -> None:
        """
        Acquire permission to make a request.
        Blocks if rate limit would be exceeded.
        """
        async with self._lock:
            now = time.time()
            
            # Refill global bucket
            global_tokens, global_last = self._global_bucket
            elapsed = now - global_last
            global_tokens = min(self.global_rps, global_tokens + elapsed * self.global_rps)
            
            # Refill host bucket
            host_tokens, host_last = self._host_buckets[host]
            host_elapsed = now - host_last
            host_tokens = min(self.per_host_rps, host_tokens + host_elapsed * self.per_host_rps)
            
            # Check if we can proceed
            if global_tokens < 1.0:
                wait_time = (1.0 - global_tokens) / self.global_rps
                logger.debug(f"Global rate limit: waiting {wait_time:.3f}s")
                await asyncio.sleep(wait_time)
                global_tokens = 1.0
            
            if host_tokens < 1.0:
                wait_time = (1.0 - host_tokens) / self.per_host_rps
                logger.debug(f"Host rate limit ({host}): waiting {wait_time:.3f}s")
                await asyncio.sleep(wait_time)
                host_tokens = 1.0
            
            # Consume tokens
            global_tokens -= 1.0
            host_tokens -= 1.0
            
            # Update buckets
            self._global_bucket = (global_tokens, time.time())
            self._host_buckets[host] = (host_tokens, time.time())


class ScopeEnforcingClient:
    """
    HTTP client wrapper that enforces engagement scope and rate limits.
    
    All requests are validated against the engagement config before being sent.
    Out-of-scope requests are blocked and logged.
    """
    
    def __init__(
        self,
        engagement_config: EngagementConfig,
        underlying_client: Optional[AsyncHTTPClient] = None,
        audit_log_path: Optional[str] = None,
    ):
        """
        Initialize scope-enforcing client.
        
        Args:
            engagement_config: Engagement configuration with scope rules
            underlying_client: Optional existing AsyncHTTPClient to wrap
            audit_log_path: Optional path to write audit log
        """
        self.config = engagement_config
        self.validator = ScopeValidator(
            target_domains=engagement_config.target_domains,
            out_of_scope_patterns=engagement_config.out_of_scope_patterns,
            allowed_schemes=engagement_config.allowed_schemes,
        )
        self.rate_limiter = RateLimiter(
            per_host_rps=engagement_config.rate_limits.per_host_rps,
            global_rps=engagement_config.rate_limits.global_rps,
        )
        
        self._client = underlying_client or AsyncHTTPClient()
        self._audit_log_path = audit_log_path
        self._audit_entries: list[dict] = []
        self._stats = {
            "allowed": 0,
            "denied": 0,
            "errors": 0,
        }
    
    def _log_audit(self, url: str, method: str, decision: ScopeDecision, reason: str) -> None:
        """Log scope decision to audit log."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "engagement_id": self.config.engagement_id,
            "url": url,
            "method": method,
            "decision": decision.value,
            "reason": reason,
        }
        self._audit_entries.append(entry)
        
        if decision == ScopeDecision.ALLOW:
            self._stats["allowed"] += 1
        elif decision == ScopeDecision.DENY:
            self._stats["denied"] += 1
        
        # Write to file if configured
        if self._audit_log_path:
            try:
                import json
                with open(self._audit_log_path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                logger.error(f"Failed to write audit log: {e}")
    
    async def _enforce_scope(self, url: str, method: str) -> str:
        """
        Enforce scope validation before request.
        
        Returns:
            Normalized URL if allowed
            
        Raises:
            ScopeViolation if request is out of scope
        """
        result = self.validator.is_in_scope(url, method)
        
        self._log_audit(url, method, result.decision, result.reason)
        
        if result.decision == ScopeDecision.DENY:
            logger.warning(f"Blocked out-of-scope request: {method} {url} - {result.reason}")
            raise ScopeViolation(
                url=url,
                reason=result.reason,
                matched_pattern=result.matched_pattern,
            )
        
        return result.normalized_url
    
    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> tuple[httpx.Response, Optional[RequestRecord]]:
        """
        Make an HTTP request with scope enforcement.
        
        Args:
            method: HTTP method
            url: Request URL
            **kwargs: Additional arguments passed to underlying client
            
        Returns:
            Tuple of (response, request_record)
            
        Raises:
            ScopeViolation: If request is out of scope
            RateLimitExceeded: If rate limit is exceeded
        """
        # Enforce scope
        normalized_url = await self._enforce_scope(url, method)
        
        # Apply rate limiting
        from urllib.parse import urlparse
        host = urlparse(normalized_url).netloc
        await self.rate_limiter.acquire(host)
        
        # Forward to underlying client
        try:
            return await self._client.request(method, url, **kwargs)
        except Exception as e:
            self._stats["errors"] += 1
            raise
    
    async def get(self, url: str, **kwargs: Any) -> tuple[httpx.Response, Optional[RequestRecord]]:
        """GET request with scope enforcement."""
        return await self.request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs: Any) -> tuple[httpx.Response, Optional[RequestRecord]]:
        """POST request with scope enforcement."""
        return await self.request("POST", url, **kwargs)
    
    async def put(self, url: str, **kwargs: Any) -> tuple[httpx.Response, Optional[RequestRecord]]:
        """PUT request with scope enforcement."""
        return await self.request("PUT", url, **kwargs)
    
    async def delete(self, url: str, **kwargs: Any) -> tuple[httpx.Response, Optional[RequestRecord]]:
        """DELETE request with scope enforcement."""
        return await self.request("DELETE", url, **kwargs)
    
    async def patch(self, url: str, **kwargs: Any) -> tuple[httpx.Response, Optional[RequestRecord]]:
        """PATCH request with scope enforcement."""
        return await self.request("PATCH", url, **kwargs)
    
    def get_stats(self) -> dict:
        """Get enforcement statistics."""
        return {
            **self._stats,
            "total": self._stats["allowed"] + self._stats["denied"],
            "validator_stats": self.validator.get_stats(),
        }
    
    def get_audit_log(self) -> list[dict]:
        """Get all audit log entries."""
        return self._audit_entries.copy()
    
    async def close(self) -> None:
        """Close underlying client."""
        await self._client.close()
