"""
Session Health Checker - Advanced session validation with multiple strategies.

Detects session expiry through:
- HTTP status codes (401, 403)
- Redirect to login page
- Response content analysis
- API endpoint checks
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Callable
from urllib.parse import urlparse

from loguru import logger


class HealthStatus(str, Enum):
    """Session health status."""
    HEALTHY = "healthy"
    EXPIRED = "expired"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    status: HealthStatus
    checked_at: datetime
    response_code: Optional[int] = None
    redirect_url: Optional[str] = None
    error_message: Optional[str] = None
    check_method: Optional[str] = None
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class SessionHealthChecker:
    """
    Advanced session health checker with multiple detection strategies.
    """
    
    def __init__(
        self,
        base_url: str,
        health_check_urls: Optional[List[str]] = None,
        login_url_patterns: Optional[List[str]] = None,
    ):
        """
        Initialize health checker.
        
        Args:
            base_url: Base URL of target application
            health_check_urls: List of URLs to check (e.g., ["/api/me", "/dashboard"])
            login_url_patterns: Patterns that indicate login page (e.g., ["/login", "/auth"])
        """
        self.base_url = base_url
        self.health_check_urls = health_check_urls or [f"{base_url}/api/me"]
        self.login_url_patterns = login_url_patterns or ["/login", "/auth", "/signin"]
        
        # Custom validators
        self.custom_validators: List[Callable] = []
        
        logger.info(f"Session health checker initialized for {base_url}")
    
    def add_custom_validator(self, validator: Callable):
        """
        Add a custom validation function.
        
        Args:
            validator: Async function that takes (response) and returns bool
        """
        self.custom_validators.append(validator)
    
    async def check_health(
        self,
        cookies: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
    ) -> HealthCheckResult:
        """
        Check session health using multiple strategies.
        
        Args:
            cookies: Session cookies
            headers: Optional headers (e.g., auth tokens)
        
        Returns:
            HealthCheckResult with status and details
        """
        headers = headers or {}
        
        # Strategy 1: Check primary health endpoint
        result = await self._check_endpoint(
            self.health_check_urls[0],
            cookies,
            headers
        )
        
        if result.status == HealthStatus.HEALTHY:
            return result
        
        # Strategy 2: Try additional endpoints
        for url in self.health_check_urls[1:]:
            result = await self._check_endpoint(url, cookies, headers)
            if result.status == HealthStatus.HEALTHY:
                return result
        
        # Strategy 3: Run custom validators
        for validator in self.custom_validators:
            try:
                is_valid = await validator(cookies, headers)
                if is_valid:
                    return HealthCheckResult(
                        status=HealthStatus.HEALTHY,
                        checked_at=datetime.utcnow(),
                        check_method="custom_validator"
                    )
            except Exception as e:
                logger.debug(f"Custom validator failed: {e}")
        
        return result
    
    async def _check_endpoint(
        self,
        url: str,
        cookies: Dict[str, str],
        headers: Dict[str, str],
    ) -> HealthCheckResult:
        """Check a single endpoint."""
        try:
            import httpx
            
            async with httpx.AsyncClient(follow_redirects=False) as client:
                response = await client.get(
                    url,
                    cookies=cookies,
                    headers=headers,
                    timeout=10.0,
                )
                
                # Check for redirect to login
                if response.status_code in [301, 302, 303, 307, 308]:
                    location = response.headers.get("location", "")
                    if self._is_login_redirect(location):
                        return HealthCheckResult(
                            status=HealthStatus.EXPIRED,
                            checked_at=datetime.utcnow(),
                            response_code=response.status_code,
                            redirect_url=location,
                            check_method="redirect_detection",
                            details={"reason": "Redirected to login page"}
                        )
                
                # Check status codes
                if response.status_code == 401:
                    return HealthCheckResult(
                        status=HealthStatus.EXPIRED,
                        checked_at=datetime.utcnow(),
                        response_code=401,
                        check_method="status_code",
                        details={"reason": "401 Unauthorized"}
                    )
                
                if response.status_code == 403:
                    return HealthCheckResult(
                        status=HealthStatus.DEGRADED,
                        checked_at=datetime.utcnow(),
                        response_code=403,
                        check_method="status_code",
                        details={"reason": "403 Forbidden - possible permission issue"}
                    )
                
                # Check for success
                if 200 <= response.status_code < 300:
                    # Additional content check
                    if self._contains_login_indicators(response.text):
                        return HealthCheckResult(
                            status=HealthStatus.EXPIRED,
                            checked_at=datetime.utcnow(),
                            response_code=response.status_code,
                            check_method="content_analysis",
                            details={"reason": "Response contains login form"}
                        )
                    
                    return HealthCheckResult(
                        status=HealthStatus.HEALTHY,
                        checked_at=datetime.utcnow(),
                        response_code=response.status_code,
                        check_method="status_code"
                    )
                
                # Other status codes
                return HealthCheckResult(
                    status=HealthStatus.UNKNOWN,
                    checked_at=datetime.utcnow(),
                    response_code=response.status_code,
                    check_method="status_code",
                    details={"reason": f"Unexpected status {response.status_code}"}
                )
        
        except Exception as e:
            logger.debug(f"Health check failed for {url}: {e}")
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                checked_at=datetime.utcnow(),
                error_message=str(e),
                check_method="exception"
            )
    
    def _is_login_redirect(self, location: str) -> bool:
        """Check if redirect location is a login page."""
        location_lower = location.lower()
        return any(pattern in location_lower for pattern in self.login_url_patterns)
    
    def _contains_login_indicators(self, content: str) -> bool:
        """Check if response content contains login form indicators."""
        content_lower = content.lower()
        indicators = [
            'type="password"',
            'name="password"',
            'id="password"',
            'login-form',
            'signin-form',
            'authentication required',
        ]
        return any(indicator in content_lower for indicator in indicators)
