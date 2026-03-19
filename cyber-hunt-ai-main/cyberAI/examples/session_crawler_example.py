"""
Example: Integrating Session Management into a Crawler

This shows how to use the session management system in your crawlers
to maintain authenticated sessions across multiple roles.
"""

import asyncio
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright

from cyberAI.session_integration import create_session_integration


async def authenticated_crawler_example():
    """
    Example crawler that uses session management for multi-role testing.
    """
    
    # Setup engagement configuration
    engagement_id = "test-engagement-001"
    roles = ["guest", "user", "admin"]
    
    # Credentials for each role
    credentials = {
        "guest": {},  # No login needed
        "user": {
            "username": "testuser@example.com",
            "password": "userpass123"
        },
        "admin": {
            "username": "admin@example.com",
            "password": "adminpass123"
        }
    }
    
    # Initialize session integration
    session_integration = await create_session_integration(
        engagement_id=engagement_id,
        roles=roles,
        login_sequences_dir=Path("login_sequences"),
        credentials=credentials,
        validation_url="/api/me",
        redis_url="redis://localhost:6379/0"  # Optional, falls back to in-memory
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        try:
            # Crawl as each role
            for role in roles:
                logger.info(f"Starting crawl as role: {role}")
                
                # Get session-aware browser context
                context, session = await session_integration.get_session_context(
                    browser=browser,
                    role=role
                )
                
                page = await context.new_page()
                
                try:
                    # Your crawling logic here
                    await crawl_with_session(page, session, session_integration, role)
                    
                finally:
                    await context.close()
        
        finally:
            await browser.close()
            await session_integration.cleanup()


async def crawl_with_session(page, session, session_integration, role):
    """
    Crawl logic with automatic session health checking and repair.
    """
    target_url = "https://example.com"
    urls_to_crawl = [
        f"{target_url}/dashboard",
        f"{target_url}/profile",
        f"{target_url}/settings",
        f"{target_url}/api/data"
    ]
    
    request_count = 0
    
    for url in urls_to_crawl:
        # Check if health validation is due
        if await session_integration.should_check_health(role):
            logger.info(f"Performing session health check for {role}")
            
            success, updated_session = await session_integration.validate_and_repair_session(
                browser=page.context.browser,
                role=role,
                page=page
            )
            
            if not success:
                logger.error(f"Session repair failed for {role}, skipping remaining URLs")
                break
            
            logger.info(f"Session healthy for {role}")
        
        # Navigate and extract data
        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            
            if response and response.status in [401, 403]:
                logger.warning(f"Auth failure on {url}, attempting repair")
                
                success, _ = await session_integration.validate_and_repair_session(
                    browser=page.context.browser,
                    role=role,
                    page=page
                )
                
                if success:
                    # Retry the request
                    response = await page.goto(url, wait_until="networkidle", timeout=30000)
            
            if response and response.ok:
                # Extract data
                content = await page.content()
                logger.info(f"Successfully crawled {url} as {role} ({len(content)} bytes)")
                
                # Your data extraction logic here
                # ...
            
        except Exception as e:
            logger.error(f"Error crawling {url} as {role}: {e}")
        
        request_count += 1
        await asyncio.sleep(0.5)  # Rate limiting


async def parallel_multi_role_crawler():
    """
    Example of parallel crawling with multiple roles simultaneously.
    """
    engagement_id = "parallel-test-001"
    roles = ["user", "admin"]
    
    credentials = {
        "user": {"username": "user@example.com", "password": "pass123"},
        "admin": {"username": "admin@example.com", "password": "adminpass"}
    }
    
    session_integration = await create_session_integration(
        engagement_id=engagement_id,
        roles=roles,
        login_sequences_dir=Path("login_sequences"),
        credentials=credentials,
        validation_url="/api/me"
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        try:
            # Create tasks for each role
            tasks = []
            for role in roles:
                task = asyncio.create_task(
                    crawl_as_role(browser, session_integration, role)
                )
                tasks.append(task)
            
            # Run all roles in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for role, result in zip(roles, results):
                if isinstance(result, Exception):
                    logger.error(f"Crawl failed for {role}: {result}")
                else:
                    logger.info(f"Crawl completed for {role}: {result}")
        
        finally:
            await browser.close()
            await session_integration.cleanup()


async def crawl_as_role(browser, session_integration, role):
    """Worker function for parallel crawling."""
    context, session = await session_integration.get_session_context(browser, role)
    page = await context.new_page()
    
    try:
        await crawl_with_session(page, session, session_integration, role)
        return f"Success for {role}"
    finally:
        await context.close()


if __name__ == "__main__":
    # Run the example
    asyncio.run(authenticated_crawler_example())
