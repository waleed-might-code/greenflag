"""
Demo script showing session management in action.

This demonstrates:
1. Creating login sequences
2. Executing login macros
3. Session health checking
4. Automatic session repair
5. Multi-role crawling
"""

import asyncio
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright

from cyberAI.session_integration import create_session_integration
from cyberAI.login_macro import LoginMacroRecorder, LoginStep, StepAction


async def create_demo_login_sequences():
    """Create demo login sequences for testing."""
    sequences_dir = Path("login_sequences")
    sequences_dir.mkdir(exist_ok=True)
    
    # Simple form-based login
    recorder = LoginMacroRecorder()
    recorder.add_navigate("https://example.com/login", "Go to login")
    recorder.add_fill("input[name='email']", "{{username}}", "Fill email")
    recorder.add_fill("input[name='password']", "{{password}}", "Fill password")
    recorder.add_click("button[type='submit']", "Submit form")
    recorder.add_wait_for_selector(".dashboard", 10000)
    recorder.add_assert_url("/dashboard")
    
    sequence = recorder.build_sequence(
        name="Demo Login",
        role="demo_user",
        success_indicators=[
            {"type": "url_contains", "value": "/dashboard"}
        ]
    )
    
    sequence.save(sequences_dir / "demo_user_login.json")
    logger.info("Created demo login sequence")


async def demo_session_lifecycle():
    """
    Demonstrate complete session lifecycle:
    - Initial login
    - Session validation
    - Session expiry simulation
    - Automatic repair
    """
    logger.info("=== Session Lifecycle Demo ===\n")
    
    # Create demo sequences
    await create_demo_login_sequences()
    
    # Setup session integration
    session_integration = await create_session_integration(
        engagement_id="demo-engagement",
        roles=["demo_user"],
        login_sequences_dir=Path("login_sequences"),
        credentials={
            "demo_user": {
                "username": "demo@example.com",
                "password": "demopass123"
            }
        },
        validation_url="/api/me",
        redis_url=None  # Use in-memory for demo
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Visible for demo
        
        try:
            logger.info("Step 1: Creating initial session")
            context, session = await session_integration.get_session_context(
                browser=browser,
                role="demo_user"
            )
            
            logger.info(f"Session created: {session.role}")
            logger.info(f"Cookies: {len(session.cookies)}")
            logger.info(f"Healthy: {session.is_healthy}\n")
            
            page = await context.new_page()
            
            # Simulate some crawling
            logger.info("Step 2: Simulating crawl requests")
            for i in range(5):
                logger.info(f"Request {i+1}/5")
                
                # Check if health validation is due
                if await session_integration.should_check_health("demo_user"):
                    logger.info("Health check triggered")
                    
                    success, updated_session = await session_integration.validate_and_repair_session(
                        browser=browser,
                        role="demo_user",
                        page=page
                    )
                    
                    if success:
                        logger.info("✓ Session healthy")
                    else:
                        logger.warning("✗ Session unhealthy, repair attempted")
                
                await asyncio.sleep(0.5)
            
            logger.info("\nStep 3: Listing all sessions")
            sessions = await session_integration.list_sessions()
            for s in sessions:
                logger.info(f"  - {s.role}: age={s.age_seconds():.1f}s, healthy={s.is_healthy}")
            
            logger.info("\nStep 4: Force session deletion (simulate expiry)")
            await session_integration.delete_session("demo_user")
            logger.info("Session deleted")
            
            logger.info("\nStep 5: Next request will trigger re-login")
            context2, session2 = await session_integration.get_session_context(
                browser=browser,
                role="demo_user"
            )
            logger.info(f"New session created: {session2.role}")
            
            await context.close()
            await context2.close()
            
        finally:
            await browser.close()
            await session_integration.cleanup()
    
    logger.info("\n=== Demo Complete ===")


async def demo_multi_role_crawling():
    """
    Demonstrate multi-role crawling with session management.
    """
    logger.info("=== Multi-Role Crawling Demo ===\n")
    
    # Setup for multiple roles
    session_integration = await create_session_integration(
        engagement_id="multi-role-demo",
        roles=["guest", "user", "admin"],
        login_sequences_dir=Path("login_sequences"),
        credentials={
            "guest": {},  # No login needed
            "user": {"username": "user@example.com", "password": "userpass"},
            "admin": {"username": "admin@example.com", "password": "adminpass"}
        },
        validation_url="/api/me"
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        try:
            # Crawl as each role
            for role in ["guest", "user", "admin"]:
                logger.info(f"\nCrawling as: {role}")
                
                context, session = await session_integration.get_session_context(
                    browser=browser,
                    role=role
                )
                
                page = await context.new_page()
                
                # Simulate crawling different endpoints
                endpoints = ["/", "/profile", "/admin", "/api/data"]
                
                for endpoint in endpoints:
                    logger.info(f"  {role} -> {endpoint}")
                    
                    # In real implementation, you'd navigate and extract data
                    # For demo, just log
                    await asyncio.sleep(0.2)
                
                await context.close()
            
            logger.info("\nAll roles crawled successfully")
            
        finally:
            await browser.close()
            await session_integration.cleanup()
    
    logger.info("\n=== Multi-Role Demo Complete ===")


async def demo_session_repair():
    """
    Demonstrate automatic session repair when session breaks.
    """
    logger.info("=== Session Repair Demo ===\n")
    
    session_integration = await create_session_integration(
        engagement_id="repair-demo",
        roles=["demo_user"],
        login_sequences_dir=Path("login_sequences"),
        credentials={
            "demo_user": {"username": "demo@example.com", "password": "pass123"}
        },
        validation_url="/api/me"
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        try:
            logger.info("Creating initial session")
            context, session = await session_integration.get_session_context(
                browser=browser,
                role="demo_user"
            )
            
            page = await context.new_page()
            
            logger.info("Session created successfully")
            logger.info(f"Initial repair attempts: {session.repair_attempts}")
            
            # Simulate session becoming unhealthy
            logger.info("\nSimulating session failure...")
            session.is_healthy = False
            await session_integration.manager.store.set(session)
            
            logger.info("Triggering health check (should repair)")
            success, repaired_session = await session_integration.validate_and_repair_session(
                browser=browser,
                role="demo_user",
                page=page
            )
            
            if success:
                logger.info("✓ Session repaired successfully")
                logger.info(f"Repair attempts: {repaired_session.repair_attempts}")
            else:
                logger.warning("✗ Session repair failed")
            
            await context.close()
            
        finally:
            await browser.close()
            await session_integration.cleanup()
    
    logger.info("\n=== Repair Demo Complete ===")


async def main():
    """Run all demos."""
    logger.info("Starting Session Management Demos\n")
    
    try:
        # Demo 1: Basic session lifecycle
        await demo_session_lifecycle()
        
        await asyncio.sleep(2)
        
        # Demo 2: Multi-role crawling
        # await demo_multi_role_crawling()
        
        # await asyncio.sleep(2)
        
        # Demo 3: Session repair
        # await demo_session_repair()
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Configure logging
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="INFO"
    )
    
    asyncio.run(main())
