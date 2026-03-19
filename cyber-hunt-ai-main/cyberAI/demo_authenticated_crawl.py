"""
Demo: Authenticated Multi-Role Crawling with Session Repair

This demonstrates the complete workflow:
1. Setting up engagement configuration
2. Creating login sequences for multiple roles
3. Running authenticated crawls as each role
4. Automatic session repair when sessions expire
5. Differential access analysis
"""

import asyncio
from pathlib import Path
from loguru import logger

from cyberAI.crawl.session_aware_orchestrator import SessionAwareCrawlOrchestrator
from cyberAI.session_integration import EngagementConfig
from cyberAI.login_macro import LoginMacroRecorder, StepAction


async def create_demo_login_sequences():
    """Create demo login sequences for different roles."""
    sequences_dir = Path("login_sequences")
    sequences_dir.mkdir(exist_ok=True)
    
    # Admin login sequence
    admin_recorder = LoginMacroRecorder()
    admin_recorder.add_navigate("https://demo.testfire.net/login.jsp", "Navigate to login")
    admin_recorder.add_fill("input[name='uid']", "{{username}}", "Fill username")
    admin_recorder.add_fill("input[name='passw']", "{{password}}", "Fill password")
    admin_recorder.add_click("input[type='submit']", "Submit login")
    admin_recorder.add_wait_for_url("/bank/main.jsp", 5000)
    admin_recorder.add_assert_url("/bank/main.jsp")
    
    admin_sequence = admin_recorder.build_sequence(
        name="Admin Login",
        role="admin",
        success_indicators=[
            {"type": "url_contains", "value": "/bank/main.jsp"}
        ]
    )
    admin_sequence.save(sequences_dir / "admin_login.json")
    
    # User login sequence (same flow, different credentials)
    user_recorder = LoginMacroRecorder()
    user_recorder.add_navigate("https://demo.testfire.net/login.jsp", "Navigate to login")
    user_recorder.add_fill("input[name='uid']", "{{username}}", "Fill username")
    user_recorder.add_fill("input[name='passw']", "{{password}}", "Fill password")
    user_recorder.add_click("input[type='submit']", "Submit login")
    user_recorder.add_wait_for_url("/bank/main.jsp", 5000)
    user_recorder.add_assert_url("/bank/main.jsp")
    
    user_sequence = user_recorder.build_sequence(
        name="User Login",
        role="user",
        success_indicators=[
            {"type": "url_contains", "value": "/bank/main.jsp"}
        ]
    )
    user_sequence.save(sequences_dir / "user_login.json")
    
    logger.info("Created login sequences for admin and user roles")


async def run_authenticated_crawl():
    """
    Run a complete authenticated crawl with multiple roles.
    """
    logger.info("=== Authenticated Multi-Role Crawl Demo ===\n")
    
    # Create login sequences
    await create_demo_login_sequences()
    
    # Setup engagement configuration
    engagement_config = EngagementConfig(
        engagement_id="demo-authenticated-crawl",
        roles=["admin", "user"],
        login_sequences={
            "admin": Path("login_sequences/admin_login.json"),
            "user": Path("login_sequences/user_login.json")
        },
        credentials={
            "admin": {
                "username": "admin",
                "password": "admin"
            },
            "user": {
                "username": "jsmith",
                "password": "demo1234"
            }
        },
        validation_config={
            "default_url": "/bank/main.jsp",
            "expected_status": [200],
            "redirect_patterns": ["/login.jsp", "/signin"]
        },
        redis_url=None,  # Use in-memory for demo
        session_ttl_seconds=1800,
        health_check_interval=50  # Check every 50 requests
    )
    
    # Create orchestrator
    orchestrator = SessionAwareCrawlOrchestrator(
        base_url="https://demo.testfire.net",
        engagement_config=engagement_config,
        max_depth=5,
        max_pages_per_role=100,
        output_dir=Path("outputs/authenticated_crawl"),
        warc_dir=Path("outputs/warc")
    )
    
    # Initialize
    await orchestrator.initialize()
    
    logger.info("Starting multi-role crawl...")
    logger.info("This will crawl as both admin and user, tracking what each role can access\n")
    
    # Run crawl
    stats = await orchestrator.crawl_all_roles()
    
    # Print results
    logger.info("\n=== Crawl Results ===")
    for role, role_stats in stats.items():
        logger.info(f"\n{role.upper()}:")
        logger.info(f"  Pages crawled: {role_stats.pages_crawled}")
        logger.info(f"  Unique endpoints: {role_stats.unique_endpoints}")
        logger.info(f"  Session repairs: {role_stats.session_repairs}")
        logger.info(f"  Auth failures: {role_stats.auth_failures}")
        logger.info(f"  Duration: {role_stats.end_time - role_stats.start_time:.1f}s")
    
    logger.info("\n✓ Results exported to outputs/authenticated_crawl/")
    logger.info("✓ WARC files saved to outputs/warc/")
    logger.info("✓ Check differential_access.json for authorization analysis")


async def demo_session_repair_scenario():
    """
    Demonstrate session repair in action.
    Simulates a session expiring mid-crawl and being automatically repaired.
    """
    logger.info("\n=== Session Repair Demo ===\n")
    
    # This would be a more controlled demo where we:
    # 1. Start a crawl
    # 2. Manually invalidate the session after N requests
    # 3. Show the automatic repair kicking in
    # 4. Continue crawling seamlessly
    
    logger.info("Session repair is automatically handled during crawls")
    logger.info("When a 401/403 or redirect to login is detected:")
    logger.info("  1. Session health check fails")
    logger.info("  2. Login macro is re-executed")
    logger.info("  3. New session is established")
    logger.info("  4. Crawl continues")
    logger.info("\nThis happens transparently without manual intervention")


async def main():
    """Run all demos."""
    try:
        # Main demo: authenticated crawl
        await run_authenticated_crawl()
        
        # Additional info about session repair
        await demo_session_repair_scenario()
        
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
