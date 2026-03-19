"""
Session Management Layer - Enterprise Session Repair and Health Monitoring

Handles multi-role session lifecycle:
- Session storage (Redis-backed with Postgres fallback)
- Health checking and automatic repair
- Login macro execution
- Session context pooling for parallel workers
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from pathlib import Path

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, using in-memory session store")


@dataclass
class SessionData:
    """Session data for a specific role."""
    engagement_id: str
    role: str
    cookies: List[Dict[str, Any]]
    headers: Dict[str, str]
    tokens: Dict[str, str]  # auth_token, refresh_token, etc.
    created_at: float
    last_validated: float
    validation_url: Optional[str] = None
    is_healthy: bool = True
    repair_attempts: int = 0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "SessionData":
        return cls(**data)
    
    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """Check if session has exceeded TTL."""
        return (time.time() - self.last_validated) > ttl_seconds
    
    def age_seconds(self) -> float:
        """Get session age in seconds."""
        return time.time() - self.created_at


class SessionStore:
    """
    Session storage backend with Redis primary and in-memory fallback.
    Stores session data per (engagement_id, role) key.
    """
    
    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: int = 3600):
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.redis_client: Optional[redis.Redis] = None
        self._memory_store: Dict[str, SessionData] = {}
        self._use_redis = REDIS_AVAILABLE and redis_url is not None
    
    async def connect(self):
        """Initialize connection to Redis if available."""
        if self._use_redis:
            try:
                self.redis_client = redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                await self.redis_client.ping()
                logger.info("Connected to Redis session store")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, using in-memory store")
                self._use_redis = False
                self.redis_client = None
    
    async def close(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
    
    def _make_key(self, engagement_id: str, role: str) -> str:
        """Generate Redis/dict key for session."""
        return f"session:{engagement_id}:{role}"
    
    async def get(self, engagement_id: str, role: str) -> Optional[SessionData]:
        """Retrieve session data."""
        key = self._make_key(engagement_id, role)
        
        if self._use_redis and self.redis_client:
            try:
                data = await self.redis_client.get(key)
                if data:
                    return SessionData.from_dict(json.loads(data))
            except Exception as e:
                logger.error(f"Redis get failed: {e}")
        
        return self._memory_store.get(key)
    
    async def set(self, session: SessionData) -> bool:
        """Store session data with TTL."""
        key = self._make_key(session.engagement_id, session.role)
        data_json = json.dumps(session.to_dict())
        
        if self._use_redis and self.redis_client:
            try:
                await self.redis_client.setex(key, self.ttl_seconds, data_json)
                logger.debug(f"Stored session in Redis: {key}")
                return True
            except Exception as e:
                logger.error(f"Redis set failed: {e}")
        
        # Fallback to memory
        self._memory_store[key] = session
        logger.debug(f"Stored session in memory: {key}")
        return True
    
    async def delete(self, engagement_id: str, role: str) -> bool:
        """Delete session data."""
        key = self._make_key(engagement_id, role)
        
        if self._use_redis and self.redis_client:
            try:
                await self.redis_client.delete(key)
            except Exception as e:
                logger.error(f"Redis delete failed: {e}")
        
        if key in self._memory_store:
            del self._memory_store[key]
        
        return True
    
    async def list_sessions(self, engagement_id: str) -> List[SessionData]:
        """List all sessions for an engagement."""
        sessions = []
        pattern = f"session:{engagement_id}:*"
        
        if self._use_redis and self.redis_client:
            try:
                keys = await self.redis_client.keys(pattern)
                for key in keys:
                    data = await self.redis_client.get(key)
                    if data:
                        sessions.append(SessionData.from_dict(json.loads(data)))
            except Exception as e:
                logger.error(f"Redis list failed: {e}")
        
        # Add memory store sessions
        for key, session in self._memory_store.items():
            if key.startswith(f"session:{engagement_id}:"):
                sessions.append(session)
        
        return sessions


class SessionHealthChecker:
    """
    Monitors session health by making test requests to validation endpoints.
    Detects 401/403, redirects to login, or missing expected content.
    """
    
    def __init__(self, validation_config: Dict[str, Any] = None):
        self.validation_config = validation_config or {}
        self.default_validation_url = self.validation_config.get("default_url", "/api/me")
        self.expected_status_codes = self.validation_config.get("expected_status", [200])
        self.redirect_patterns = self.validation_config.get("redirect_patterns", ["/login", "/signin", "/auth"])
    
    async def check_session(
        self,
        page: Page,
        session: SessionData,
        validation_url: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Check if session is healthy by navigating to validation URL.
        
        Returns:
            (is_healthy, reason)
        """
        url = validation_url or session.validation_url or self.default_validation_url
        
        try:
            # Apply session cookies to page
            await self._apply_session_to_page(page, session)
            
            # Navigate to validation URL
            response = await page.goto(url, wait_until="networkidle", timeout=10000)
            
            if not response:
                return False, "No response received"
            
            # Check status code
            if response.status in [401, 403]:
                return False, f"Auth failure: {response.status}"
            
            # Check for redirect to login
            current_url = page.url
            for pattern in self.redirect_patterns:
                if pattern in current_url.lower():
                    return False, f"Redirected to login: {current_url}"
            
            # Check expected status
            if response.status not in self.expected_status_codes:
                return False, f"Unexpected status: {response.status}"
            
            # Optional: Check for expected content
            expected_content = self.validation_config.get("expected_content")
            if expected_content:
                content = await page.content()
                if expected_content not in content:
                    return False, "Expected content not found"
            
            return True, "Session healthy"
            
        except Exception as e:
            logger.error(f"Session health check failed: {e}")
            return False, f"Exception: {str(e)}"
    
    async def _apply_session_to_page(self, page: Page, session: SessionData):
        """Apply session cookies and headers to page context."""
        if session.cookies:
            await page.context.add_cookies(session.cookies)
        
        # Set custom headers if needed
        if session.headers:
            await page.set_extra_http_headers(session.headers)


class SessionManager:
    """
    Main session management orchestrator.
    Coordinates session store, health checking, and repair.
    """
    
    def __init__(
        self,
        store: SessionStore,
        health_checker: SessionHealthChecker,
        max_repair_attempts: int = 3,
        health_check_interval: int = 100  # Check every N requests
    ):
        self.store = store
        self.health_checker = health_checker
        self.max_repair_attempts = max_repair_attempts
        self.health_check_interval = health_check_interval
        self._request_counters: Dict[str, int] = {}
        self._repair_locks: Dict[str, asyncio.Lock] = {}
    
    async def get_session(self, engagement_id: str, role: str) -> Optional[SessionData]:
        """Get session for a role, returns None if not found."""
        return await self.store.get(engagement_id, role)
    
    async def create_session(
        self,
        engagement_id: str,
        role: str,
        cookies: List[Dict[str, Any]],
        headers: Dict[str, str] = None,
        tokens: Dict[str, str] = None,
        validation_url: Optional[str] = None
    ) -> SessionData:
        """Create and store a new session."""
        session = SessionData(
            engagement_id=engagement_id,
            role=role,
            cookies=cookies,
            headers=headers or {},
            tokens=tokens or {},
            created_at=time.time(),
            last_validated=time.time(),
            validation_url=validation_url,
            is_healthy=True,
            repair_attempts=0
        )
        
        await self.store.set(session)
        logger.info(f"Created session for {engagement_id}:{role}")
        return session
    
    async def validate_and_repair(
        self,
        engagement_id: str,
        role: str,
        page: Page,
        repair_callback: Optional[callable] = None
    ) -> tuple[bool, Optional[SessionData]]:
        """
        Validate session health and repair if needed.
        
        Args:
            engagement_id: Engagement ID
            role: Role name
            page: Playwright page for testing
            repair_callback: Async function to repair session, receives (engagement_id, role, page)
        
        Returns:
            (success, session_data)
        """
        session = await self.get_session(engagement_id, role)
        if not session:
            logger.warning(f"No session found for {engagement_id}:{role}")
            return False, None
        
        # Check health
        is_healthy, reason = await self.health_checker.check_session(page, session)
        
        if is_healthy:
            session.last_validated = time.time()
            session.is_healthy = True
            await self.store.set(session)
            return True, session
        
        logger.warning(f"Session unhealthy for {engagement_id}:{role}: {reason}")
        
        # Attempt repair
        if repair_callback and session.repair_attempts < self.max_repair_attempts:
            return await self._repair_session(engagement_id, role, page, repair_callback, session)
        
        session.is_healthy = False
        await self.store.set(session)
        return False, session
    
    async def _repair_session(
        self,
        engagement_id: str,
        role: str,
        page: Page,
        repair_callback: callable,
        session: SessionData
    ) -> tuple[bool, Optional[SessionData]]:
        """Execute session repair with locking to prevent concurrent repairs."""
        key = f"{engagement_id}:{role}"
        
        # Get or create lock for this session
        if key not in self._repair_locks:
            self._repair_locks[key] = asyncio.Lock()
        
        async with self._repair_locks[key]:
            # Re-check if another task already repaired
            current_session = await self.get_session(engagement_id, role)
            if current_session and current_session.is_healthy:
                return True, current_session
            
            logger.info(f"Attempting session repair for {engagement_id}:{role} (attempt {session.repair_attempts + 1})")
            
            try:
                # Execute repair callback (login macro)
                new_session_data = await repair_callback(engagement_id, role, page)
                
                if new_session_data:
                    # Create new session with repaired data
                    new_session = await self.create_session(
                        engagement_id=engagement_id,
                        role=role,
                        cookies=new_session_data.get("cookies", []),
                        headers=new_session_data.get("headers", {}),
                        tokens=new_session_data.get("tokens", {}),
                        validation_url=session.validation_url
                    )
                    
                    # Verify repair worked
                    is_healthy, reason = await self.health_checker.check_session(page, new_session)
                    
                    if is_healthy:
                        logger.info(f"Session repair successful for {engagement_id}:{role}")
                        return True, new_session
                    else:
                        logger.error(f"Session repair failed validation: {reason}")
                        new_session.repair_attempts = session.repair_attempts + 1
                        new_session.is_healthy = False
                        await self.store.set(new_session)
                        return False, new_session
                
            except Exception as e:
                logger.error(f"Session repair exception: {e}")
                session.repair_attempts += 1
                session.is_healthy = False
                await self.store.set(session)
                return False, session
        
        return False, session
    
    async def should_check_health(self, engagement_id: str, role: str) -> bool:
        """Determine if health check is due based on request counter."""
        key = f"{engagement_id}:{role}"
        self._request_counters[key] = self._request_counters.get(key, 0) + 1
        
        if self._request_counters[key] >= self.health_check_interval:
            self._request_counters[key] = 0
            return True
        
        return False
    
    async def cleanup(self):
        """Cleanup resources."""
        await self.store.close()
