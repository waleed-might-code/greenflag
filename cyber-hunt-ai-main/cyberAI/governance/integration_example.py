"""
Integration example: Using scope enforcement in the existing codebase.
"""

import asyncio
from pathlib import Path

from loguru import logger

from cyberAI.governance import EngagementConfig, ScopeEnforcingClient


async def example_basic_usage():
    """Basic usage example."""
    # Load engagement config
    config = EngagementConfig.from_file(Path("cyberAI/governance/example_engagement.yaml"))
    
    # Create scope-enforcing client
    client = ScopeEnforcingClient(
        engagement_config=config,
        audit_log_path="outputs/logs/scope_audit.jsonl",
    )
    
    try:
        # This request will be allowed (in scope)
        response, record = await client.get("https://target.example.com/api/users")
        logger.info(f"Allowed request: {response.status_code}")
        
        # This request will be blocked (out of scope - logout)
        try:
            response, record = await client.get("https://target.example.com/logout")
        except Exception as e:
            logger.warning(f"Blocked request: {e}")
        
        # This request will be blocked (out of scope - different domain)
        try:
            response, record = await client.get("https://evil.com/")
        except Exception as e:
            logger.warning(f"Blocked request: {e}")
        
        # Print statistics
        stats = client.get_stats()
        logger.info(f"Enforcement stats: {stats}")
        
    finally:
        await client.close()


async def example_with_existing_client():
    """Example wrapping an existing AsyncHTTPClient."""
    from cyberAI.utils.http_client import AsyncHTTPClient
    
    # Create engagement config
    config = EngagementConfig.create_default(
        target_url="https://target.example.com",
        name="Quick Test",
    )
    
    # Add out-of-scope patterns
    config.out_of_scope_patterns = ["*/logout", "*/delete/*"]
    
    # Create existing client
    existing_client = AsyncHTTPClient(base_url="https://target.example.com")
    
    # Wrap with scope enforcement
    client = ScopeEnforcingClient(
        engagement_config=config,
        underlying_client=existing_client,
    )
    
    try:
        # Use as normal
        response, record = await client.get("/api/users")
        logger.info(f"Response: {response.status_code}")
    finally:
        await client.close()


async def example_integration_with_discovery():
    """Example integrating with core discovery."""
    from cyberAI.recon.core_discovery import CoreDiscovery
    
    # Load engagement config
    config = EngagementConfig.from_file(Path("cyberAI/governance/example_engagement.yaml"))
    
    # Create scope-enforcing client
    client = ScopeEnforcingClient(engagement_config=config)
    
    # TODO: Modify CoreDiscovery to accept a custom HTTP client
    # For now, this shows the pattern:
    
    # discovery = CoreDiscovery()
    # discovery.set_http_client(client)  # Would need to add this method
    # await discovery.discover(config.target_domains[0])
    
    logger.info("Integration example - would modify CoreDiscovery to use scope-enforcing client")
    
    await client.close()


if __name__ == "__main__":
    logger.info("Running scope enforcement examples...")
    
    asyncio.run(example_basic_usage())
    asyncio.run(example_with_existing_client())
    asyncio.run(example_integration_with_discovery())
