#!/usr/bin/env python3
"""
Demo script for state-flow crawler.
Tests the crawler on a target URL and shows results.
"""

import asyncio
import json
from pathlib import Path
from loguru import logger
from rich.console import Console
from rich.table import Table

from .state_flow_crawler import StateFlowCrawler


console = Console()


async def demo_crawl(target_url: str, max_states: int = 100):
    """
    Run a demo crawl and display results.
    
    Args:
        target_url: URL to crawl
        max_states: Maximum states to explore
    """
    console.print(f"\n[bold cyan]State-Flow Crawler Demo[/bold cyan]")
    console.print(f"Target: {target_url}")
    console.print(f"Max states: {max_states}\n")
    
    output_dir = Path("outputs/demo_crawl")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    crawler = StateFlowCrawler(
        target_url=target_url,
        max_states=max_states,
        max_depth=5,
        screenshot_dir=output_dir / "screenshots",
        headless=True,
    )
    
    console.print("[yellow]Starting crawl...[/yellow]\n")
    results = await crawler.crawl()
    
    # Display results
    console.print("\n[bold green]Crawl Complete![/bold green]\n")
    
    # Summary table
    table = Table(title="Crawl Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("States Discovered", str(results["states_discovered"]))
    table.add_row("Transitions", str(results["transitions_discovered"]))
    table.add_row("Unique URLs", str(results["unique_urls"]))
    table.add_row("Total Forms", str(results["total_forms"]))
    table.add_row("Total Inputs", str(results["total_inputs"]))
    table.add_row("Total Links", str(results["total_links"]))
    
    console.print(table)
    
    # Frontier stats
    console.print("\n[bold]Frontier Statistics:[/bold]")
    stats = results["frontier_stats"]
    for key, value in stats.items():
        console.print(f"  {key}: {value}")
    
    # Save results
    results_file = output_dir / "crawl_results.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    console.print(f"\n[green]Results saved to: {results_file}[/green]")
    
    # Show top states by attack surface
    console.print("\n[bold]Top States by Attack Surface:[/bold]")
    states_by_surface = sorted(
        results["states"],
        key=lambda s: s["forms"] + s["inputs"],
        reverse=True
    )[:10]
    
    surface_table = Table()
    surface_table.add_column("State ID", style="cyan")
    surface_table.add_column("URL", style="white", max_width=50)
    surface_table.add_column("Forms", style="green")
    surface_table.add_column("Inputs", style="yellow")
    surface_table.add_column("Depth", style="blue")
    
    for state in states_by_surface:
        surface_table.add_row(
            state["state_id"],
            state["url"][:50],
            str(state["forms"]),
            str(state["inputs"]),
            str(state["depth"]),
        )
    
    console.print(surface_table)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        console.print("[red]Usage: python -m cyberAI.crawl.demo <target_url> [max_states][/red]")
        sys.exit(1)
    
    target = sys.argv[1]
    max_states = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    
    asyncio.run(demo_crawl(target, max_states))
