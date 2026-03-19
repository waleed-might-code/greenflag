"""
Enhanced recon module with state-flow crawler integration.
"""

from pathlib import Path
from typing import Optional
from loguru import logger

from cyberAI.models import MasterIntelligence, BaseMeta
from cyberAI.crawl.integration import run_state_flow_discovery, merge_with_intelligence


async def run_enhanced_discovery(
    target_url: str,
    output_dir: Path,
    use_state_flow: bool = True,
    max_states: int = 10000,
    max_depth: int = 10,
) -> MasterIntelligence:
    """
    Run enhanced discovery with state-flow crawler.
    
    Args:
        target_url: Target URL
        output_dir: Output directory
        use_state_flow: Enable state-flow crawler
        max_states: Maximum states for crawler
        max_depth: Maximum depth for crawler
        
    Returns:
        Master intelligence with discovered routes and endpoints
    """
    logger.info("Starting enhanced discovery")
    
    # Initialize intelligence
    intelligence = MasterIntelligence(
        meta=BaseMeta(
            target_url=target_url,
            phase="enhanced_discovery",
        )
    )
    
    if use_state_flow:
        logger.info("Running state-flow crawler")
        crawl_results = await run_state_flow_discovery(
            target_url=target_url,
            output_dir=output_dir,
            max_states=max_states,
            max_depth=max_depth,
        )
        
        intelligence = merge_with_intelligence(intelligence, crawl_results)
        
        logger.info(
            f"State-flow discovery complete: "
            f"{len(intelligence.routes)} routes, "
            f"{crawl_results['stats']['attack_surface']['forms']} forms"
        )
    
    return intelligence
