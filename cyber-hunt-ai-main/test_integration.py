#!/usr/bin/env python3
"""
Quick integration test for state-flow crawler.
Tests the crawler on a real target and verifies output.
"""

import asyncio
import json
from pathlib import Path
from loguru import logger
from rich.console import Console

from cyberAI.crawl import StateFlowCrawler

console = Console()


async def test_integration():
    """Test state-flow crawler integration."""
    
    console.print("\n[bold cyan]State-Flow Crawler Integration Test[/bold cyan]\n")
    
    # Test configuration
    target_url = "https://example.com"
    output_dir = Path("outputs/integration_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    console.print(f"Target: {target_url}")
    console.print(f"Output: {output_dir}\n")
    
    # Create crawler
    crawler = StateFlowCrawler(
        target_url=target_url,
        max_states=5,  # Small test
        max_depth=2,
        screenshot_dir=output_dir / "screenshots",
        headless=True,
    )
    
    console.print("[yellow]Running crawler...[/yellow]\n")
    
    try:
        results = await crawler.crawl()
        
        # Verify results
        assert results["states_discovered"] > 0, "No states discovered"
        assert "frontier_stats" in results, "Missing frontier stats"
        assert "states" in results, "Missing states list"
        
        console.print("[green]✓ Crawler completed successfully[/green]")
        console.print(f"  States: {results['states_discovered']}")
        console.print(f"  Transitions: {results['transitions_discovered']}")
        console.print(f"  Forms: {results['total_forms']}")
        console.print(f"  Inputs: {results['total_inputs']}")
        
        # Save results
        results_file = output_dir / "test_results.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        console.print(f"\n[green]✓ Results saved to {results_file}[/green]")
        
        # Verify screenshots
        screenshot_dir = output_dir / "screenshots"
        screenshots = list(screenshot_dir.glob("*.png"))
        console.print(f"[green]✓ Screenshots: {len(screenshots)}[/green]")
        
        console.print("\n[bold green]All tests passed![/bold green]\n")
        return True
        
    except Exception as e:
        console.print(f"\n[bold red]Test failed: {e}[/bold red]\n")
        logger.exception("Integration test failed")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_integration())
    exit(0 if success else 1)
