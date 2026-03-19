"""
Quick test script to verify scope enforcement is working.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from governance.engagement_config import EngagementConfig
from governance.scope_enforcing_client import ScopeEnforcingClient, ScopeViolation


async def quick_test():
    """Quick test of scope enforcement."""
    
    print("\n" + "=" * 80)
    print("SCOPE ENFORCEMENT QUICK TEST")
    print("=" * 80)
    
    # Create config
    config = EngagementConfig.create_default(
        target_url="https://httpbin.org",
        name="Quick Test"
    )
    config.out_of_scope_patterns = ["*/status/500"]
    
    client = ScopeEnforcingClient(engagement_config=config)
    
    # Test 1: Allowed request
    print("\n[TEST 1] In-scope request...")
    try:
        response, _ = await client.get("https://httpbin.org/get")
        print(f"✓ PASS: Got {response.status_code}")
    except Exception as e:
        print(f"✗ FAIL: {e}")
    
    # Test 2: Blocked by pattern
    print("\n[TEST 2] Out-of-scope pattern...")
    try:
        response, _ = await client.get("https://httpbin.org/status/500")
        print(f"✗ FAIL: Should have been blocked")
    except ScopeViolation as e:
        print(f"✓ PASS: Correctly blocked - {e.reason}")
    
    # Test 3: Blocked by domain
    print("\n[TEST 3] Out-of-scope domain...")
    try:
        response, _ = await client.get("https://example.com/")
        print(f"✗ FAIL: Should have been blocked")
    except ScopeViolation as e:
        print(f"✓ PASS: Correctly blocked - {e.reason}")
    
    # Stats
    stats = client.get_stats()
    print(f"\n[STATS] Allowed: {stats['allowed']}, Denied: {stats['denied']}")
    
    await client.close()
    
    print("\n" + "=" * 80)
    print("✓ SCOPE ENFORCEMENT WORKING!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(quick_test())
