#!/usr/bin/env python3
"""
Quick test script for state-flow crawler.
Tests basic functionality without full integration.
"""

import asyncio
from pathlib import Path
from cyberAI.crawl import StateFlowCrawler
from loguru import logger


async def test_crawler():
    """Test the state-flow crawler on a simple target."""
    
    # Use a simple test target
    target_url = "https://example.com"
    
    logger.info(f"Testing state-flow crawler on {target_url}")
    
    output_dir = Path("outputs/test_crawl")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    crawler = StateFlowCrawler(
        target_url=target_url,
        max_states=10,  # Small test
        max_depth=3,
        screenshot_dir=output_dir / "screenshots",
        headless=True,
    )
    
    try:
        results = await crawler.crawl()
        
        logger.info("Crawl completed successfully!")
        logger.info(f"States discovered: {results['states_discovered']}")
        logger.info(f"Transitions: {results['transitions_discovered']}")
        logger.info(f"Forms: {results['total_forms']}")
        logger.info(f"Inputs: {results['total_inputs']}")
        
        return True
        
    except Exception as e:
        logger.error(f"Crawl failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_crawler())
    exit(0 if success else 1)
