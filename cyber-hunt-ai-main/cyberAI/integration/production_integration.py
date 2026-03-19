"""
Production Integration Guide - Session Management System

This module shows how to integrate the session management system into
the existing CyberAI main.py orchestrator for production use.
"""

import asyncio
from pathlib import Path
from typing import List, Optional
from loguru import logger

from cyberAI.config import Config
from cyberAI.session_integration import create_session_integration, SessionIntegration
from cyberAI.models import MasterIntelligence


async def run_authenticated_recon_phase(
    config: Config,
    roles: List[str],
    output_dir: Path
) -> MasterIntelligence:
    """
    Enhanced recon phase with multi-role session management.
    
    This replaces or augments the existing run_recon() function in main.py
    to add authenticated crawling capabilities.
    
    Args:
        config: CyberAI configuration
        roles: List of roles to test (from config.role_accounts)
        output_dir: Output directory for results
    
    Returns:
        MasterIntelligence with aggregated results from all roles
    """
    logger.info("Starting authenticated reconnaissance phase")
    
    # Extract credentials from config
    credentials = {}
    for role_account in config.role_accounts:
        credentials[role_account.role] = {
            "username": role_account.username,
            "password": role_account.password
        }
        if role_account.mfa_secret:
            credentials[role_account.role]["mfa_secret"] = role_account.mfa_secret
    
    # Initialize session integration
    session_integration = await create_session_integration(
        engagement_id=f"recon-{config.run_id}",
        roles=roles,
        login_sequences_dir=Path("login_sequences"),
        credentials=credentials,
        validation_url="/api/me",  # Configure per target
        redis_url=None  # Add to config if using Redis
    )
    
    try:
        # Import existing recon modules
        from cyberAI.recon import (
            run_core_discovery,
            run_frontend_parser,
            run_role_discovery,
            run_permission_inference
        )
        
        # Run recon for each role
        all_intelligence = []
        
        for role in roles:
            logger.info(f"\n{'='*60}")
            logger.info(f"Running recon as role: {role}")
            logger.info(f"{'='*60}\n")
            
            # Get session for this role
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=config.headless)
                context, session = await session_integration.get_session_context(
                    browser=browser,
                    role=role
                )
                
                try:
                    # Run existing recon modules with session-aware context
                    # Pass the context to your existing recon functions
                    
                    # Example: Core discovery
                    routes = await run_core_discovery_with_session(
                        config=config,
                        context=context,
                        session=session,
                        session_integration=session_integration,
                        browser=browser,
                        role=role
                    )
                    
                    # Example: Frontend parsing
                    # parsed_data = await run_frontend_parser_with_session(...)
                    
                    # Store results
                    # all_intelligence.append(...)
                    
                except Exception as e:
                    logger.error(f"Error during recon as {role}: {e}")
                
                finally:
                    await context.close()
                    await browser.close()
        
        # Aggregate results
        # intelligence = aggregate_intelligence(all_intelligence)
        
        # For now, return empty intelligence
        from cyberAI.models import BaseMeta
        intelligence = MasterIntelligence(
            meta=BaseMeta(
                target_url=config.target_url,
                phase="authenticated_recon",
                run_id=config.run_id
            )
        )
        
        return intelligence
    
    finally:
        await session_integration.cleanup()


async def run_core_discovery_with_session(
    config: Config,
    context,
    session,
    session_integration: SessionIntegration,
    browser,
    role: str
):
    """
    Wrapper for existing core discovery that adds session management.
    """
    from cyberAI.recon import run_core_discovery
    
    # Create a page from the session-aware context
    page = await context.new_page()
    
    try:
        # Your existing core discovery logic here
        # But now it runs with authenticated session
        
        # Example: Navigate to target
        await page.goto(config.target_url, wait_until="networkidle")
        
        # Check session health periodically
        if await session_integration.should_check_health(role):
            success, _ = await session_integration.validate_and_repair_session(
                browser=browser,
                role=role,
                page=page
            )
            if not success:
                logger.error(f"Session repair failed for {role}")
                return []
        
        # Continue with existing discovery logic
        # routes = await run_core_discovery(...)
        
        return []
    
    finally:
        await page.close()


def add_session_management_to_config(config: Config) -> Config:
    """
    Extend existing Config with session management settings.
    
    Add this to your config.py or call it during initialization.
    """
    # Add session-related attributes if not present
    if not hasattr(config, 'session_ttl_seconds'):
        config.session_ttl_seconds = 3600
    
    if not hasattr(config, 'session_health_check_interval'):
        config.session_health_check_interval = 100
    
    if not hasattr(config, 'session_max_repair_attempts'):
        config.session_max_repair_attempts = 3
    
    if not hasattr(config, 'redis_url'):
        config.redis_url = None
    
    return config


# ============================================================================
# INTEGRATION PATTERNS
# ============================================================================

class SessionAwareWorker:
    """
    Base class for workers that need session management.
    Use this for test workers, crawlers, etc.
    """
    
    def __init__(self, session_integration: SessionIntegration, role: str):
        self.session_integration = session_integration
        self.role = role
        self._request_count = 0
    
    async def execute_with_session(self, browser, work_func):
        """
        Execute work function with session management.
        
        Args:
            browser: Playwright browser
            work_func: Async function that receives (page, session)
        """
        context, session = await self.session_integration.get_session_context(
            browser=browser,
            role=self.role
        )
        
        page = await context.new_page()
        
        try:
            # Execute work
            result = await work_func(page, session)
            
            # Check session health
            self._request_count += 1
            if self._request_count % 10 == 0:
                if await self.session_integration.should_check_health(self.role):
                    success, _ = await self.session_integration.validate_and_repair_session(
                        browser=browser,
                        role=self.role,
                        page=page
                    )
                    if not success:
                        logger.warning(f"Session repair failed for {self.role}")
            
            return result
        
        finally:
            await context.close()


# ============================================================================
# EXAMPLE: Integrating with existing main.py
# ============================================================================

async def enhanced_main_recon(args):
    """
    Enhanced version of main.py's run_recon() function.
    
    Replace or augment your existing run_recon() with this.
    """
    from cyberAI.config import Config
    
    config = Config.load()
    config = add_session_management_to_config(config)
    
    # Extract roles from config
    roles = [acc.role for acc in config.role_accounts] if config.role_accounts else ["guest"]
    
    # Run authenticated recon
    intelligence = await run_authenticated_recon_phase(
        config=config,
        roles=roles,
        output_dir=config.output_dir
    )
    
    # Save results
    output_path = config.get_output_path("recon", "intelligence", f"authenticated_{config.run_id}.json")
    with open(output_path, "w") as f:
        f.write(intelligence.model_dump_json(indent=2))
    
    logger.info(f"Authenticated recon complete: {output_path}")


# ============================================================================
# QUICK START FOR DEVELOPERS
# ============================================================================

"""
QUICK START - Add Session Management to Your Module

1. Import the session integration:
   
   from cyberAI.session_integration import create_session_integration

2. Initialize at the start of your module:
   
   session_integration = await create_session_integration(
       engagement_id="my-engagement",
       roles=["user", "admin"],
       login_sequences_dir=Path("login_sequences"),
       credentials={
           "user": {"username": "user@example.com", "password": "pass"},
           "admin": {"username": "admin@example.com", "password": "adminpass"}
       },
       validation_url="/api/me"
   )

3. Get a session-aware browser context:
   
   context, session = await session_integration.get_session_context(
       browser=browser,
       role="admin"
   )
   page = await context.new_page()

4. Check session health periodically:
   
   if await session_integration.should_check_health("admin"):
       success, _ = await session_integration.validate_and_repair_session(
           browser=browser,
           role="admin",
           page=page
       )

5. Cleanup when done:
   
   await session_integration.cleanup()

That's it! Your module now has enterprise-grade session management.
"""
