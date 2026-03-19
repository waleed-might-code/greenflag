"""
Integration layer between state-flow crawler and existing recon system.
Converts crawl results to recon intelligence format.
"""

from pathlib import Path
from typing import Any
from loguru import logger

from .state_flow_crawler import StateFlowCrawler
from cyberAI.models import Route, MasterIntelligence, BaseMeta


async def run_state_flow_discovery(
    target_url: str,
    output_dir: Path,
    max_states: int = 10000,
    max_depth: int = 10,
    headless: bool = True,
) -> dict[str, Any]:
    """
    Run state-flow crawl and integrate with recon system.
    
    Args:
        target_url: Target URL to crawl
        output_dir: Output directory for results
        max_states: Maximum states to explore
        max_depth: Maximum depth from entry
        headless: Run browser in headless mode
        
    Returns:
        Crawl results with discovered routes and states
    """
    logger.info(f"Starting state-flow discovery for {target_url}")
    
    screenshot_dir = output_dir / "screenshots" / "state_flow"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    
    crawler = StateFlowCrawler(
        target_url=target_url,
        max_states=max_states,
        max_depth=max_depth,
        screenshot_dir=screenshot_dir,
        headless=headless,
    )
    
    results = await crawler.crawl()
    
    # Convert to Route models
    routes = [crawler.states[state_id].to_route() for state_id in crawler.states]
    
    logger.info(f"State-flow discovery complete: {len(routes)} routes discovered")
    
    return {
        "routes": routes,
        "raw_results": results,
        "stats": {
            "states_discovered": results["states_discovered"],
            "transitions": results["transitions_discovered"],
            "attack_surface": {
                "forms": results["total_forms"],
                "inputs": results["total_inputs"],
                "links": results["total_links"],
            }
        }
    }


def merge_with_intelligence(
    intelligence: MasterIntelligence,
    crawl_results: dict[str, Any],
) -> MasterIntelligence:
    """
    Merge state-flow crawl results into master intelligence.
    
    Args:
        intelligence: Existing master intelligence
        crawl_results: Results from state-flow crawler
        
    Returns:
        Updated master intelligence
    """
    # Add discovered routes
    existing_urls = {route.url for route in intelligence.routes}
    
    new_routes = 0
    for route in crawl_results["routes"]:
        if route.url not in existing_urls:
            intelligence.routes.append(route)
            new_routes += 1
    
    logger.info(f"Merged {new_routes} new routes into intelligence")
    
    return intelligence
