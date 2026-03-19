"""
Integration: Session-Aware Recon Runner

This extends the existing main.py recon command to support multi-role
authenticated crawling with automatic session management.
"""

import asyncio
from pathlib import Path
from typing import List, Optional
from loguru import logger
from playwright.async_api import async_playwright

from cyberAI.config import Config
from cyberAI.session_integration import create_session_integration, SessionIntegration
from cyberAI.models import Route, Endpoint, MasterIntelligence, BaseMeta


async def run_authenticated_recon(
    target_url: str,
    roles: List[str],
    login_sequences_dir: Path,
    credentials: dict,
    output_dir: Path,
    redis_url: Optional[str] = None
) -> MasterIntelligence:
    """
    Run reconnaissance with multi-role session management.
    
    Args:
        target_url: Target URL to scan
        roles: List of roles to test (e.g., ["guest", "user", "admin"])
        login_sequences_dir: Directory containing login sequence JSON files
        credentials: Dict mapping role -> credentials
        output_dir: Output directory for results
        redis_url: Optional Redis URL for session storage
    
    Returns:
        MasterIntelligence object with aggregated results
    """
    logger.info(f"Starting authenticated recon for {target_url}")
    logger.info(f"Roles: {', '.join(roles)}")
    
    # Initialize session integration
    session_integration = await create_session_integration(
        engagement_id=f"recon-{target_url.replace('://', '-').replace('/', '-')}",
        roles=roles,
        login_sequences_dir=login_sequences_dir,
        credentials=credentials,
        validation_url="/api/me",  # Customize per target
        redis_url=redis_url
    )
    
    # Aggregate results from all roles
    all_routes = []
    all_endpoints = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        try:
            for role in roles:
                logger.info(f"\n{'='*60}")
                logger.info(f"Scanning as role: {role}")
                logger.info(f"{'='*60}\n")
                
                # Get session-aware context
                context, session = await session_integration.get_session_context(
                    browser=browser,
                    role=role
                )
                
                page = await context.new_page()
                
                try:
                    # Discover routes for this role
                    routes = await discover_routes_for_role(
                        page=page,
                        target_url=target_url,
                        role=role,
                        session_integration=session_integration,
                        browser=browser
                    )
                    
                    all_routes.extend(routes)
                    logger.info(f"Discovered {len(routes)} routes as {role}")
                    
                    # Discover API endpoints
                    endpoints = await discover_endpoints_for_role(
                        page=page,
                        target_url=target_url,
                        role=role,
                        session_integration=session_integration,
                        browser=browser
                    )
                    
                    all_endpoints.extend(endpoints)
                    logger.info(f"Discovered {len(endpoints)} endpoints as {role}")
                    
                except Exception as e:
                    logger.error(f"Error scanning as {role}: {e}")
                
                finally:
                    await context.close()
        
        finally:
            await browser.close()
            await session_integration.cleanup()
    
    # Build master intelligence
    intelligence = MasterIntelligence(
        meta=BaseMeta(
            target_url=target_url,
            phase="authenticated_recon"
        ),
        routes=all_routes,
        endpoints=all_endpoints
    )
    
    # Save results
    output_path = output_dir / "authenticated_recon.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        f.write(intelligence.model_dump_json(indent=2))
    
    logger.info(f"\nResults saved to: {output_path}")
    logger.info(f"Total routes discovered: {len(all_routes)}")
    logger.info(f"Total endpoints discovered: {len(all_endpoints)}")
    
    return intelligence


async def discover_routes_for_role(
    page,
    target_url: str,
    role: str,
    session_integration: SessionIntegration,
    browser
) -> List[Route]:
    """Discover routes accessible to a specific role."""
    routes = []
    request_count = 0
    
    try:
        # Navigate to target
        await page.goto(target_url, wait_until="networkidle", timeout=30000)
        request_count += 1
        
        # Check session health periodically
        if await session_integration.should_check_health(role):
            success, _ = await session_integration.validate_and_repair_session(
                browser=browser,
                role=role,
                page=page
            )
            if not success:
                logger.warning(f"Session repair failed for {role}")
                return routes
        
        # Extract current route
        route = Route(
            slug=page.url.split("/")[-1] or "index",
            url=page.url,
            role_context=role,
            page_title=await page.title()
        )
        routes.append(route)
        
        # Extract links
        links = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(href => href.startsWith(window.location.origin));
                return [...new Set(links)].slice(0, 20);  // Limit for demo
            }
        """)
        
        # Visit each link
        for link in links:
            request_count += 1
            
            # Check session health every 10 requests
            if request_count % 10 == 0:
                if await session_integration.should_check_health(role):
                    success, _ = await session_integration.validate_and_repair_session(
                        browser=browser,
                        role=role,
                        page=page
                    )
                    if not success:
                        break
            
            try:
                await page.goto(link, wait_until="networkidle", timeout=10000)
                
                sub_route = Route(
                    slug=link.split("/")[-1] or "page",
                    url=page.url,
                    role_context=role,
                    page_title=await page.title()
                )
                routes.append(sub_route)
                
            except Exception as e:
                logger.debug(f"Failed to visit {link}: {e}")
    
    except Exception as e:
        logger.error(f"Route discovery error for {role}: {e}")
    
    return routes


async def discover_endpoints_for_role(
    page,
    target_url: str,
    role: str,
    session_integration: SessionIntegration,
    browser
) -> List[Endpoint]:
    """Discover API endpoints accessible to a specific role."""
    endpoints = []
    captured_requests = []
    
    # Setup request interception
    async def capture_request(route, request):
        if request.resource_type in ["xhr", "fetch"]:
            captured_requests.append({
                "url": request.url,
                "method": request.method,
                "headers": request.headers
            })
        await route.continue_()
    
    await page.route("**/*", capture_request)
    
    try:
        # Navigate and trigger XHR/fetch requests
        await page.goto(target_url, wait_until="networkidle", timeout=30000)
        
        # Wait for any async requests
        await asyncio.sleep(2)
        
        # Convert captured requests to Endpoint objects
        for req in captured_requests:
            endpoint = Endpoint(
                url=req["url"],
                method=req["method"],
                role_context=role,
                auth_required=role != "guest"
            )
            endpoints.append(endpoint)
    
    except Exception as e:
        logger.error(f"Endpoint discovery error for {role}: {e}")
    
    return endpoints


async def main_demo():
    """Demo of authenticated recon."""
    
    # Example configuration
    target_url = "https://example.com"
    roles = ["guest", "user"]  # Add "admin" if you have admin credentials
    
    credentials = {
        "guest": {},  # No login needed
        "user": {
            "username": "demo@example.com",
            "password": "demopass123"
        }
    }
    
    login_sequences_dir = Path("login_sequences")
    output_dir = Path("outputs/authenticated_recon")
    
    # Run authenticated recon
    intelligence = await run_authenticated_recon(
        target_url=target_url,
        roles=roles,
        login_sequences_dir=login_sequences_dir,
        credentials=credentials,
        output_dir=output_dir,
        redis_url=None  # Use in-memory for demo
    )
    
    logger.info("\n" + "="*60)
    logger.info("Authenticated Recon Complete!")
    logger.info("="*60)
    logger.info(f"Routes discovered: {len(intelligence.routes)}")
    logger.info(f"Endpoints discovered: {len(intelligence.endpoints)}")
    
    # Show role-specific access
    role_routes = {}
    for route in intelligence.routes:
        role = route.role_context or "unknown"
        role_routes[role] = role_routes.get(role, 0) + 1
    
    logger.info("\nRoutes by role:")
    for role, count in role_routes.items():
        logger.info(f"  {role}: {count} routes")


if __name__ == "__main__":
    asyncio.run(main_demo())
