"""
Demo script showing the complete data mining pipeline.
"""

import asyncio
from pathlib import Path

from loguru import logger

from crawl.orchestrator import CrawlOrchestrator


async def demo_comprehensive_crawl():
    """Demonstrate comprehensive crawling with all components."""
    
    logger.info("=" * 100)
    logger.info("COMPREHENSIVE DATA MINING DEMO")
    logger.info("=" * 100)
    
    # Target URL (using httpbin for demo)
    target_url = "https://httpbin.org"
    
    # Create orchestrator
    orchestrator = CrawlOrchestrator(
        base_url=target_url,
        max_depth=3,
        max_pages=50,
        output_dir=Path("outputs/demo_crawl"),
    )
    
    try:
        # Run crawl
        stats = await orchestrator.crawl()
        
        # Print results
        logger.info("\n" + "=" * 100)
        logger.success("CRAWL COMPLETE")
        logger.info("=" * 100)
        logger.info(f"Pages crawled: {stats['pages_crawled']}")
        logger.info(f"APIs discovered: {stats['apis_discovered']}")
        logger.info(f"States discovered: {stats['states_discovered']}")
        logger.info(f"Insertion points: {stats['insertion_points']}")
        logger.info(f"Duration: {stats['end_time'] - stats['start_time']:.2f}s")
        
        # Show novelty stats
        novelty_stats = orchestrator.novelty_index.get_stats()
        logger.info(f"\nNovelty Index:")
        logger.info(f"  Unique shapes: {novelty_stats.unique_shapes}")
        logger.info(f"  Novel endpoints: {novelty_stats.novel_endpoints}")
        logger.info(f"  Duplicate requests: {novelty_stats.duplicate_requests}")
        
        # Show top novel endpoints
        top_novel = orchestrator.novelty_index.get_top_novel_endpoints(5)
        logger.info(f"\nTop 5 Novel Endpoints:")
        for endpoint, count in top_novel:
            logger.info(f"  {endpoint}: {count} unique shapes")
        
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(demo_comprehensive_crawl())
