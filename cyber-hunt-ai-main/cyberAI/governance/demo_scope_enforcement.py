"""
Demo script showing scope enforcement in action.
Run this to see how the governance layer protects against out-of-scope requests.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from governance.engagement_config import EngagementConfig
from governance.scope_enforcing_client import ScopeEnforcingClient, ScopeViolation


async def demo_scope_enforcement():
    """Demonstrate scope enforcement with real HTTP requests."""
    
    logger.info("=" * 100)
    logger.info("SCOPE ENFORCEMENT DEMO")
    logger.info("=" * 100)
    
    # Create a simple engagement config
    config = EngagementConfig.create_default(
        target_url="https://httpbin.org",
        name="HTTPBin Test Engagement"
    )
    
    # Add some out-of-scope patterns
    config.out_of_scope_patterns = ["*/status/500", "*/delay/*"]
    
    logger.info(f"\nEngagement: {config.name}")
    logger.info(f"Target domains: {config.target_domains}")
    logger.info(f"Out-of-scope patterns: {config.out_of_scope_patterns}")
    logger.info(f"Rate limits: {config.rate_limits.per_host_rps} req/s per host")
    
    # Create scope-enforcing client
    client = ScopeEnforcingClient(
        engagement_config=config,
        audit_log_path="outputs/logs/scope_demo_audit.jsonl",
    )
    
    logger.info("\n" + "=" * 100)
    logger.info("TEST 1: In-scope request (should succeed)")
    logger.info("=" * 100)
    
    try:
        response, record = await client.get("https://httpbin.org/get?test=value")
        logger.success(f"✓ Request allowed: {response.status_code} {response.url}")
        logger.info(f"  Response size: {len(response.content)} bytes")
    except Exception as e:
        logger.error(f"✗ Request failed: {e}")
    
    logger.info("\n" + "=" * 100)
    logger.info("TEST 2: Out-of-scope request - pattern match (should be blocked)")
    logger.info("=" * 100)
    
    try:
        response, record = await client.get("https://httpbin.org/status/500")
        logger.error(f"✗ Request should have been blocked but succeeded!")
    except ScopeViolation as e:
        logger.success(f"✓ Request correctly blocked: {e.reason}")
        logger.info(f"  Matched pattern: {e.matched_pattern}")
    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
    
    logger.info("\n" + "=" * 100)
    logger.info("TEST 3: Out-of-scope request - different domain (should be blocked)")
    logger.info("=" * 100)
    
    try:
        response, record = await client.get("https://example.com/")
        logger.error(f"✗ Request should have been blocked but succeeded!")
    except ScopeViolation as e:
        logger.success(f"✓ Request correctly blocked: {e.reason}")
    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
    
    logger.info("\n" + "=" * 100)
    logger.info("TEST 4: Multiple in-scope requests (rate limiting)")
    logger.info("=" * 100)
    
    import time
    start = time.time()
    
    for i in range(5):
        try:
            response, record = await client.get(f"https://httpbin.org/get?request={i}")
            elapsed = time.time() - start
            logger.success(f"✓ Request {i+1}/5: {response.status_code} (elapsed: {elapsed:.2f}s)")
        except Exception as e:
            logger.error(f"✗ Request {i+1}/5 failed: {e}")
    
    # Print statistics
    logger.info("\n" + "=" * 100)
    logger.info("ENFORCEMENT STATISTICS")
    logger.info("=" * 100)
    
    stats = client.get_stats()
    logger.info(f"Total requests: {stats['total']}")
    logger.info(f"Allowed: {stats['allowed']}")
    logger.info(f"Denied: {stats['denied']}")
    logger.info(f"Errors: {stats['errors']}")
    
    # Show audit log sample
    audit_log = client.get_audit_log()
    if audit_log:
        logger.info(f"\nAudit log entries: {len(audit_log)}")
        logger.info("Sample entries:")
        for entry in audit_log[:3]:
            logger.info(f"  {entry['timestamp']}: {entry['decision']} - {entry['url']}")
    
    await client.close()
    
    logger.info("\n" + "=" * 100)
    logger.success("DEMO COMPLETE - Scope enforcement working correctly!")
    logger.info("=" * 100)


if __name__ == "__main__":
    asyncio.run(demo_scope_enforcement())
