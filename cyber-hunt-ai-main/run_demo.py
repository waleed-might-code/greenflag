#!/usr/bin/env python3
"""
Simple Working Demo - Session Management System

This is a minimal, self-contained demo that actually runs and shows
the session management system in action without requiring a real target.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from loguru import logger
from playwright.async_api import async_playwright

# Configure simple logging
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO"
)


async def create_mock_login_sequence():
    """Create a simple login sequence for demo purposes."""
    sequences_dir = Path("login_sequences")
    sequences_dir.mkdir(exist_ok=True)
    
    # Simple mock sequence (won't actually work, just for demo)
    sequence = {
        "name": "Demo Login",
        "role": "demo_user",
        "steps": [
            {
                "action": "navigate",
                "url": "https://example.com",
                "timeout_ms": 30000,
                "description": "Navigate to site",
                "required": True,
                "retry_count": 0
            }
        ],
        "success_indicators": [
            {"type": "url_contains", "value": "example.com"}
        ],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "metadata": {"demo": True}
    }
    
    sequence_path = sequences_dir / "demo_user_login.json"
    with open(sequence_path, "w") as f:
        json.dump(sequence, f, indent=2)
    
    return sequence_path


async def demo_session_lifecycle():
    """
    Demonstrate session management lifecycle without requiring real login.
    """
    logger.info("="*70)
    logger.info("SESSION MANAGEMENT SYSTEM - LIVE DEMO")
    logger.info("="*70)
    logger.info("")
    
    # Import here to show it works
    from cyberAI.session_manager import SessionStore, SessionData, SessionHealthChecker, SessionManager
    
    logger.info("Step 1: Creating session store (in-memory)")
    store = SessionStore(redis_url=None, ttl_seconds=3600)
    await store.connect()
    logger.info("✓ Session store initialized\n")
    
    logger.info("Step 2: Creating a test session")
    session = SessionData(
        engagement_id="demo-engagement-001",
        role="demo_user",
        cookies=[
            {"name": "session_id", "value": "abc123xyz", "domain": "example.com", "path": "/"}
        ],
        headers={"Authorization": "Bearer demo_token_12345"},
        tokens={"auth_token": "demo_token_12345", "refresh_token": "refresh_xyz"},
        created_at=asyncio.get_event_loop().time(),
        last_validated=asyncio.get_event_loop().time(),
        validation_url="/api/me",
        is_healthy=True,
        repair_attempts=0,
        metadata={"demo": True, "user_id": "12345"}
    )
    
    logger.info(f"  Engagement ID: {session.engagement_id}")
    logger.info(f"  Role: {session.role}")
    logger.info(f"  Cookies: {len(session.cookies)} cookie(s)")
    logger.info(f"  Tokens: {len(session.tokens)} token(s)")
    logger.info(f"  Healthy: {session.is_healthy}\n")
    
    logger.info("Step 3: Storing session")
    await store.set(session)
    logger.info("✓ Session stored\n")
    
    logger.info("Step 4: Retrieving session")
    retrieved = await store.get("demo-engagement-001", "demo_user")
    if retrieved:
        logger.info(f"✓ Session retrieved successfully")
        logger.info(f"  Role: {retrieved.role}")
        logger.info(f"  Age: {retrieved.age_seconds():.2f} seconds")
        logger.info(f"  Expired: {retrieved.is_expired(ttl_seconds=3600)}\n")
    
    logger.info("Step 5: Creating session manager")
    health_checker = SessionHealthChecker({
        "default_url": "/api/me",
        "expected_status": [200]
    })
    manager = SessionManager(store, health_checker, health_check_interval=5)
    logger.info("✓ Session manager initialized\n")
    
    logger.info("Step 6: Simulating request counter")
    for i in range(7):
        should_check = await manager.should_check_health("demo-engagement-001", "demo_user")
        logger.info(f"  Request {i+1}: Health check due? {should_check}")
    logger.info("")
    
    logger.info("Step 7: Listing all sessions")
    sessions = await store.list_sessions("demo-engagement-001")
    logger.info(f"✓ Found {len(sessions)} session(s) for engagement\n")
    
    for sess in sessions:
        logger.info(f"  • {sess.role}")
        logger.info(f"    - Cookies: {len(sess.cookies)}")
        logger.info(f"    - Tokens: {list(sess.tokens.keys())}")
        logger.info(f"    - Healthy: {sess.is_healthy}")
        logger.info(f"    - Age: {sess.age_seconds():.2f}s\n")
    
    logger.info("Step 8: Simulating session expiry")
    session.is_healthy = False
    await store.set(session)
    logger.info("✓ Session marked as unhealthy\n")
    
    updated = await store.get("demo-engagement-001", "demo_user")
    logger.info(f"  Session health: {updated.is_healthy}")
    logger.info(f"  Repair attempts: {updated.repair_attempts}\n")
    
    logger.info("Step 9: Cleanup")
    await manager.cleanup()
    logger.info("✓ Resources cleaned up\n")
    
    logger.info("="*70)
    logger.info("DEMO COMPLETE - Session Management System Working!")
    logger.info("="*70)
    logger.info("")
    logger.info("Key Features Demonstrated:")
    logger.info("  ✓ Session creation and storage")
    logger.info("  ✓ Session retrieval")
    logger.info("  ✓ Health check scheduling")
    logger.info("  ✓ Session listing")
    logger.info("  ✓ Session state management")
    logger.info("")
    logger.info("Next Steps:")
    logger.info("  1. Create real login sequences for your target")
    logger.info("  2. Test with: python cyberAI/cli_login_macro.py test <sequence>")
    logger.info("  3. Integrate into your crawlers")
    logger.info("  4. Run authenticated recon")
    logger.info("")


async def demo_login_macro():
    """Demonstrate login macro system."""
    logger.info("\n" + "="*70)
    logger.info("LOGIN MACRO SYSTEM - DEMO")
    logger.info("="*70 + "\n")
    
    from cyberAI.login_macro import LoginSequence, LoginStep, StepAction, LoginMacroExecutor
    
    logger.info("Step 1: Creating a login sequence")
    
    steps = [
        LoginStep(
            action=StepAction.NAVIGATE,
            url="https://example.com/login",
            description="Navigate to login page"
        ),
        LoginStep(
            action=StepAction.FILL,
            selector="input[name='email']",
            value_ref="{{username}}",
            description="Fill email field"
        ),
        LoginStep(
            action=StepAction.FILL,
            selector="input[name='password']",
            value_ref="{{password}}",
            description="Fill password field"
        ),
        LoginStep(
            action=StepAction.CLICK,
            selector="button[type='submit']",
            description="Click submit button"
        ),
        LoginStep(
            action=StepAction.ASSERT_URL,
            expected="/dashboard",
            description="Verify redirect to dashboard"
        )
    ]
    
    sequence = LoginSequence(
        name="Example Login Flow",
        role="user",
        steps=steps,
        success_indicators=[
            {"type": "url_contains", "value": "/dashboard"}
        ],
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat()
    )
    
    logger.info(f"✓ Created sequence: {sequence.name}")
    logger.info(f"  Role: {sequence.role}")
    logger.info(f"  Steps: {len(sequence.steps)}\n")
    
    logger.info("Step 2: Showing sequence steps")
    for idx, step in enumerate(sequence.steps, 1):
        logger.info(f"  {idx}. {step.action.value}: {step.description}")
    logger.info("")
    
    logger.info("Step 3: Saving sequence to file")
    sequence_path = Path("login_sequences/example_login.json")
    sequence.save(sequence_path)
    logger.info(f"✓ Saved to: {sequence_path}\n")
    
    logger.info("Step 4: Loading sequence from file")
    loaded = LoginSequence.load(sequence_path)
    logger.info(f"✓ Loaded: {loaded.name}")
    logger.info(f"  Steps match: {len(loaded.steps) == len(sequence.steps)}\n")
    
    logger.info("Step 5: Credential substitution demo")
    executor = LoginMacroExecutor()
    template = "Hello {{username}}, your password is {{password}}"
    credentials = {"username": "john@example.com", "password": "secret123"}
    result = executor._substitute_credentials(template, credentials)
    logger.info(f"  Template: {template}")
    logger.info(f"  Result: {result}\n")
    
    logger.info("="*70)
    logger.info("LOGIN MACRO DEMO COMPLETE")
    logger.info("="*70 + "\n")


async def main():
    """Run all demos."""
    try:
        # Demo 1: Session lifecycle
        await demo_session_lifecycle()
        
        await asyncio.sleep(1)
        
        # Demo 2: Login macros
        await demo_login_macro()
        
        logger.info("\n" + "="*70)
        logger.info("ALL DEMOS COMPLETED SUCCESSFULLY!")
        logger.info("="*70)
        logger.info("\nThe session management system is ready to use.")
        logger.info("See SESSION_MANAGEMENT.md for full documentation.\n")
        
    except Exception as e:
        logger.error(f"\nDemo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
