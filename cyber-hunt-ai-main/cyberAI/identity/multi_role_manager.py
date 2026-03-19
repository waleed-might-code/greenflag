"""
Multi-role session manager for differential authorization testing.
Maintains sessions for multiple roles (admin, user, guest) with health checks and repair.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext


@dataclass
class SessionCredentials:
    """Credentials for a test identity."""
    role: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    cookies: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class SessionState:
    """Current state of a session."""
    role: str
    cookies: Dict[str, str]
    headers: Dict[str, str]
    is_healthy: bool = True
    last_check: Optional[datetime] = None
    last_repair: Optional[datetime] = None
    request_count: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "role": self.role,
            "cookies": self.cookies,
            "headers": self.headers,
            "is_healthy": self.is_healthy,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_repair": self.last_repair.isoformat() if self.last_repair else None,
            "request_count": self.request_count,
        }


class MultiRoleSessionManager:
    """
    Manages sessions for multiple test identities.
    Performs health checks and automatic session repair.
    """
    
    def __init__(
        self,
        base_url: str,
        health_check_url: Optional[str] = None,
        health_check_interval: int = 50,  # Check every N requests
    ):
        """
        Initialize session manager.
        
        Args:
            base_url: Base URL of target application
            health_check_url: URL to check session health (e.g., /api/me)
            health_check_interval: Check health every N requests
        """
        self.base_url = base_url
        self.health_check_url = health_check_url or f"{base_url}/api/me"
        self.health_check_interval = health_check_interval
        
        # Session storage
        self.sessions: Dict[str, SessionState] = {}
        self.credentials: Dict[str, SessionCredentials] = {}
        self.login_sequences: Dict[str, List[dict]] = {}
        
        # Browser for session operations
        self.browser: Optional[Browser] = None
        
        logger.info(f"Multi-role session manager initialized for {base_url}")
    
    def register_identity(
        self,
        role: str,
        credentials: SessionCredentials,
        login_sequence: Optional[List[dict]] = None,
    ):
        """
        Register a test identity.
        
        Args:
            role: Role name (e.g., "admin", "user", "guest")
            credentials: Credentials for this role
            login_sequence: Optional login sequence (Playwright actions)
        """
        self.credentials[role] = credentials
        if login_sequence:
            self.login_sequences[role] = login_sequence
        
        logger.info(f"Registered identity: {role}")
    
    async def initialize_sessions(self):
        """Initialize sessions for all registered identities."""
        logger.info(f"Initializing sessions for {len(self.credentials)} identities")
        
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=True)
            
            for role, creds in self.credentials.items():
                try:
                    session = await self._create_session(role, creds)
                    self.sessions[role] = session
                    logger.info(f"Initialized session for {role}")
                
                except Exception as e:
                    logger.error(f"Failed to initialize session for {role}: {e}")
            
            await self.browser.close()
            self.browser = None
    
    async def _create_session(
        self,
        role: str,
        credentials: SessionCredentials,
    ) -> SessionState:
        """Create a new session for a role."""
        # If we have a login sequence, execute it
        if role in self.login_sequences:
            return await self._execute_login_sequence(role, credentials)
        
        # Otherwise, use provided cookies/headers
        return SessionState(
            role=role,
            cookies=credentials.cookies,
            headers=credentials.headers,
            is_healthy=True,
            last_check=datetime.utcnow(),
        )
    
    async def _execute_login_sequence(
        self,
        role: str,
        credentials: SessionCredentials,
    ) -> SessionState:
        """Execute login sequence to obtain session."""
        if not self.browser:
            raise RuntimeError("Browser not initialized")
        
        context = await self.browser.new_context()
        page = await context.new_page()
        
        try:
            sequence = self.login_sequences[role]
            
            for step in sequence:
                action = step.get("action")
                
                if action == "navigate":
                    url = step.get("url", self.base_url)
                    await page.goto(url)
                
                elif action == "fill":
                    selector = step.get("selector")
                    value = step.get("value")
                    # Replace placeholders
                    if value == "{username}":
                        value = credentials.username
                    elif value == "{password}":
                        value = credentials.password
                    await page.fill(selector, value)
                
                elif action == "click":
                    selector = step.get("selector")
                    await page.click(selector)
                
                elif action == "wait":
                    ms = step.get("ms", 1000)
                    await asyncio.sleep(ms / 1000)
            
            # Wait for navigation to complete
            await page.wait_for_load_state("networkidle")
            
            # Extract cookies
            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            
            # Extract auth headers if present
            headers = {}
            if credentials.token:
                headers["Authorization"] = f"Bearer {credentials.token}"
            
            session = SessionState(
                role=role,
                cookies=cookie_dict,
                headers=headers,
                is_healthy=True,
                last_check=datetime.utcnow(),
            )
            
            logger.info(f"Login sequence completed for {role}")
            return session
        
        finally:
            await page.close()
            await context.close()
    
    async def get_session(self, role: str) -> Optional[SessionState]:
        """
        Get session for a role.
        Performs health check if needed.
        
        Args:
            role: Role name
        
        Returns:
            SessionState or None if not available
        """
        if role not in self.sessions:
            logger.warning(f"No session for role: {role}")
            return None
        
        session = self.sessions[role]
        session.request_count += 1
        
        # Check if health check is needed
        if session.request_count % self.health_check_interval == 0:
            is_healthy = await self._check_session_health(session)
            
            if not is_healthy:
                logger.warning(f"Session unhealthy for {role}, attempting repair")
                await self._repair_session(role)
        
        return session
    
    async def _check_session_health(self, session: SessionState) -> bool:
        """
        Check if a session is healthy.
        
        Args:
            session: Session to check
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.health_check_url,
                    cookies=session.cookies,
                    headers=session.headers,
                    timeout=10.0,
                )
                
                session.last_check = datetime.utcnow()
                
                # Consider 200-299 as healthy
                is_healthy = 200 <= response.status_code < 300
                session.is_healthy = is_healthy
                
                return is_healthy
        
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            session.is_healthy = False
            return False
    
    async def _repair_session(self, role: str):
        """
        Repair a broken session by re-running login sequence.
        
        Args:
            role: Role to repair
        """
        if role not in self.credentials:
            logger.error(f"Cannot repair session for {role}: no credentials")
            return
        
        try:
            async with async_playwright() as p:
                self.browser = await p.chromium.launch(headless=True)
                
                credentials = self.credentials[role]
                new_session = await self._create_session(role, credentials)
                
                self.sessions[role] = new_session
                new_session.last_repair = datetime.utcnow()
                
                logger.info(f"Session repaired for {role}")
                
                await self.browser.close()
                self.browser = None
        
        except Exception as e:
            logger.error(f"Failed to repair session for {role}: {e}")
    
    def get_all_roles(self) -> List[str]:
        """Get list of all registered roles."""
        return list(self.credentials.keys())
    
    def export_sessions(self, path: Path):
        """Export sessions to file."""
        data = {
            role: session.to_dict()
            for role, session in self.sessions.items()
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Exported sessions to {path}")
    
    def get_stats(self) -> dict:
        """Get session statistics."""
        return {
            "total_roles": len(self.credentials),
            "active_sessions": len(self.sessions),
            "healthy_sessions": sum(1 for s in self.sessions.values() if s.is_healthy),
            "sessions": {
                role: {
                    "is_healthy": session.is_healthy,
                    "request_count": session.request_count,
                    "last_check": session.last_check.isoformat() if session.last_check else None,
                }
                for role, session in self.sessions.items()
            },
        }
