"""
Session Integration Layer - Connects session management to crawlers and test workers

Provides high-level API for:
- Initializing session management for an engagement
- Getting session-aware browser contexts
- Automatic health checking and repair during crawls
- Session lifecycle management
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page

from cyberAI.session_manager import SessionStore, SessionHealthChecker, SessionManager, SessionData
from cyberAI.login_macro import LoginSequence, LoginMacroExecutor


@dataclass
class EngagementConfig:
    """Configuration for an engagement's session management."""
    engagement_id: str
    roles: List[str]
    login_sequences: Dict[str, Path]  # role -> path to login sequence JSON
    credentials: Dict[str, Dict[str, str]]  # role -> {username, password, ...}
    validation_config: Dict[str, Any]
    redis_url: Optional[str] = None
    session_ttl_seconds: int = 3600
    health_check_interval: int = 100


class SessionIntegration:
    """
    High-level integration layer for session management.
    Use this in your crawlers and test workers.
    """
    
    def __init__(self, config: EngagementConfig):
        self.config = config
        self.store = SessionStore(
            redis_url=config.redis_url,
            ttl_seconds=config.session_ttl_seconds
        )
        self.health_checker = SessionHealthChecker(config.validation_config)
        self.manager = SessionManager(
            store=self.store,
            health_checker=self.health_checker,
            health_check_interval=config.health_check_interval
        )
        self.macro_executor = LoginMacroExecutor()
        self._login_sequences: Dict[str, LoginSequence] = {}
        self._initialized = False
    
    async def initialize(self):
        """Initialize session management (connect to Redis, load sequences)."""
        if self._initialized:
            return
        
        await self.store.connect()
        
        # Load login sequences
        for role, sequence_path in self.config.login_sequences.items():
            if sequence_path.exists():
                self._login_sequences[role] = LoginSequence.load(sequence_path)
                logger.info(f"Loaded login sequence for role: {role}")
            else:
                logger.warning(f"Login sequence not found for role {role}: {sequence_path}")
        
        self._initialized = True
        logger.info(f"Session integration initialized for engagement: {self.config.engagement_id}")
    
    async def get_session_context(
        self,
        browser: Browser,
        role: str,
        force_new: bool = False
    ) -> tuple[BrowserContext, SessionData]:
        """
        Get a browser context with session applied.
        
        Args:
            browser: Playwright browser instance
            role: Role name
            force_new: Force creation of new session (re-login)
        
        Returns:
            (context, session_data)
        """
        if not self._initialized:
            await self.initialize()
        
        # Check if session exists and is valid
        session = await self.manager.get_session(self.config.engagement_id, role)
        
        if not session or force_new or session.is_expired(self.config.session_ttl_seconds):
            logger.info(f"Creating new session for role: {role}")
            session = await self._create_new_session(browser, role)
        
        # Create browser context with session
        context = await browser.new_context()
        
        if session and session.cookies:
            await context.add_cookies(session.cookies)
        
        if session and session.headers:
            await context.set_extra_http_headers(session.headers)
        
        return context, session
    
    async def _create_new_session(self, browser: Browser, role: str) -> Optional[SessionData]:
        """Create a new session by executing login macro."""
        if role not in self._login_sequences:
            logger.error(f"No login sequence found for role: {role}")
            return None
        
        if role not in self.config.credentials:
            logger.error(f"No credentials found for role: {role}")
            return None
        
        sequence = self._login_sequences[role]
        credentials = self.config.credentials[role]
        
        # Create temporary context for login
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            # Execute login macro
            result = await self.macro_executor.execute(
                page=page,
                sequence=sequence,
                credentials=credentials
            )
            
            if result["success"]:
                # Create session in store
                session = await self.manager.create_session(
                    engagement_id=self.config.engagement_id,
                    role=role,
                    cookies=result["cookies"],
                    headers=result.get("headers", {}),
                    tokens=result.get("tokens", {}),
                    validation_url=self.config.validation_config.get("default_url")
                )
                
                logger.info(f"Successfully created session for role: {role}")
                return session
            else:
                logger.error(f"Login failed for role {role}: {result.get('error')}")
                return None
        
        finally:
            await context.close()
    
    async def validate_and_repair_session(
        self,
        browser: Browser,
        role: str,
        page: Page
    ) -> tuple[bool, Optional[SessionData]]:
        """
        Validate session health and repair if needed.
        
        Args:
            browser: Browser instance for repair
            role: Role name
            page: Page to test session on
        
        Returns:
            (success, session_data)
        """
        async def repair_callback(engagement_id: str, role: str, page: Page) -> Optional[Dict[str, Any]]:
            """Callback for session repair - executes login macro."""
            if role not in self._login_sequences or role not in self.config.credentials:
                return None
            
            sequence = self._login_sequences[role]
            credentials = self.config.credentials[role]
            
            result = await self.macro_executor.execute(
                page=page,
                sequence=sequence,
                credentials=credentials
            )
            
            if result["success"]:
                return {
                    "cookies": result["cookies"],
                    "headers": result.get("headers", {}),
                    "tokens": result.get("tokens", {})
                }
            
            return None
        
        return await self.manager.validate_and_repair(
            engagement_id=self.config.engagement_id,
            role=role,
            page=page,
            repair_callback=repair_callback
        )
    
    async def should_check_health(self, role: str) -> bool:
        """Check if health validation is due for this role."""
        return await self.manager.should_check_health(self.config.engagement_id, role)
    
    async def list_sessions(self) -> List[SessionData]:
        """List all active sessions for this engagement."""
        return await self.store.list_sessions(self.config.engagement_id)
    
    async def delete_session(self, role: str) -> bool:
        """Delete a session (force re-login on next use)."""
        return await self.store.delete(self.config.engagement_id, role)
    
    async def cleanup(self):
        """Cleanup resources."""
        await self.manager.cleanup()


async def create_session_integration(
    engagement_id: str,
    roles: List[str],
    login_sequences_dir: Path,
    credentials: Dict[str, Dict[str, str]],
    validation_url: str = "/api/me",
    redis_url: Optional[str] = None
) -> SessionIntegration:
    """
    Factory function to create and initialize SessionIntegration.
    
    Args:
        engagement_id: Unique engagement identifier
        roles: List of role names
        login_sequences_dir: Directory containing login sequence JSON files
        credentials: Dict mapping role -> credentials dict
        validation_url: URL to check session health
        redis_url: Optional Redis connection URL
    
    Returns:
        Initialized SessionIntegration instance
    """
    login_sequences = {}
    for role in roles:
        sequence_path = login_sequences_dir / f"{role}_login.json"
        login_sequences[role] = sequence_path
    
    config = EngagementConfig(
        engagement_id=engagement_id,
        roles=roles,
        login_sequences=login_sequences,
        credentials=credentials,
        validation_config={
            "default_url": validation_url,
            "expected_status": [200],
            "redirect_patterns": ["/login", "/signin", "/auth"]
        },
        redis_url=redis_url
    )
    
    integration = SessionIntegration(config)
    await integration.initialize()
    
    return integration
