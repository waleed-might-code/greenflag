"""
Integration of state-flow crawler into main recon pipeline.
Adds state-flow discovery as a recon step.
"""

from pathlib import Path
from typing import Optional
from loguru import logger

from cyberAI.crawl.integration import run_state_flow_discovery
from cyberAI.models import MasterIntelligence


async def integrate_state_flow_crawler(
    target_url: str,
    output_dir: Path,
    intelligence: Optional[MasterIntelligence] = None,
    max_states: int = 10000,
    max_depth: int = 10,
    enabled: bool = True,
) -> MasterIntelligence:
    """
    Integrate state-flow crawler into recon pipeline.
    
    This is the main entry point for adding state-flow crawling
    to the existing reconnaissance system.
    
    Args:
        target_url: Target URL to crawl
        output_dir: Output directory for results
        intelligence: Existing intelligence to merge with (optional)
        max_states: Maximum states to explore
        max_depth: Maximum depth from entry
        enabled: Enable/disable state-flow crawler
        
    Returns:
        Updated master intelligence with discovered routes
    """
    if not enabled:
        logger.info("State-flow crawler disabled, skipping")
        return intelligence or MasterIntelligence()
    
    logger.info("=" * 80)
    logger.info("PHASE: State-Flow Discovery (Agent #1)")
    logger.info("=" * 80)
    logger.info(f"Target: {target_url}")
    logger.info(f"Max states: {max_states}")
    logger.info(f"Max depth: {max_depth}")
    
    try:
        # Run state-flow discovery
        results = await run_state_flow_discovery(
            target_url=target_url,
            output_dir=output_dir,
            max_states=max_states,
            max_depth=max_depth,
        )
        
        # Merge with existing intelligence
        if intelligence:
            from cyberAI.crawl.integration import merge_with_intelligence
            intelligence = merge_with_intelligence(intelligence, results)
        else:
            from cyberAI.models import BaseMeta
            intelligence = MasterIntelligence(
                meta=BaseMeta(target_url=target_url, phase="state_flow_discovery"),
                routes=results["routes"],
            )
        
        # Log statistics
        stats = results["stats"]
        logger.info("=" * 80)
        logger.info("State-Flow Discovery Complete")
        logger.info("=" * 80)
        logger.info(f"States discovered: {stats['states_discovered']}")
        logger.info(f"Transitions: {stats['transitions']}")
        logger.info(f"Attack surface:")
        logger.info(f"  - Forms: {stats['attack_surface']['forms']}")
        logger.info(f"  - Inputs: {stats['attack_surface']['inputs']}")
        logger.info(f"  - Links: {stats['attack_surface']['links']}")
        logger.info(f"Total routes in intelligence: {len(intelligence.routes)}")
        logger.info("=" * 80)
        
        return intelligence
        
    except Exception as e:
        logger.error(f"State-flow discovery failed: {e}")
        logger.exception("Full traceback:")
        return intelligence or MasterIntelligence()
