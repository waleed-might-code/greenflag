#!/usr/bin/env python3
"""
Comprehensive test for state explosion solver.
Demonstrates that the solver prevents state explosion on complex SPAs.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .state_explosion_solver import StateExplosionSolver
from ..governance.engagement_config import EngagementConfig


console = Console()


async def test_state_explosion_prevention():
    """
    Test state explosion solver on a complex target.
    Shows that without the solver, we'd explore millions of states.
    With the solver, we cap at 10k and intelligently prioritize.
    """
    console.print(Panel.fit(
        "[bold cyan]State Explosion Solver Test[/bold cyan]\n"
        "Testing on complex SPA with potential for millions of states",
        border_style="cyan"
    ))
    
    # Test configuration
    target_url = "https://example.com"  # Replace with actual test target
    max_states = 1000  # Lower for testing
    output_dir = Path("outputs/state_explosion_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create engagement config for scope enforcement
    engagement_config = EngagementConfig(
        engagement_id="test-state-explosion",
        name="State Explosion Test",
        target_domains=["https://example.com"],
        out_of_scope_patterns=["*/logout", "*/delete"],
        rate_limits={
            "per_host_rps": 10,
            "global_rps": 50,
        }
    )
    
    console.print(f"\n[yellow]Configuration:[/yellow]")
    console.print(f"  Target: {target_url}")
    console.print(f"  Max states: {max_states}")
    console.print(f"  Output: {output_dir}\n")
    
    # Initialize solver
    solver = StateExplosionSolver(
        target_url=target_url,
        engagement_config=engagement_config,
        max_states=max_states,
        max_depth=8,
        max_concurrent=2,
        screenshot_dir=output_dir / "screenshots",
        headless=True,
    )
    
    console.print("[bold green]Starting crawl with state explosion prevention...[/bold green]\n")
    
    try:
        results = await solver.crawl()
        
        # Display comprehensive results
        display_results(results, output_dir)
        
        # Save detailed results
        results_file = output_dir / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        console.print(f"\n[green]✓ Results saved to: {results_file}[/green]")
        
        return results
        
    finally:
        await solver.close()


def display_results(results: dict, output_dir: Path):
    """Display comprehensive test results."""
    
    # Main metrics table
    console.print("\n[bold]═══ CRAWL SUMMARY ═══[/bold]\n")
    
    table = Table(title="Core Metrics", show_header=True)
    table.add_column("Metric", style="cyan", width=30)
    table.add_column("Value", style="magenta", justify="right")
    
    table.add_row("Duration", f"{results['duration_seconds']:.2f}s")
    table.add_row("States Explored", str(results['states_explored']))
    table.add_row("States/Second", f"{results['states_per_second']:.2f}")
    table.add_row("Forms Found", str(results['forms_found']))
    table.add_row("Inputs Found", str(results['inputs_found']))
    table.add_row("API Calls Found", str(results['api_calls_found']))
    
    console.print(table)
    
    # State explosion prevention metrics
    console.print("\n[bold]═══ STATE EXPLOSION PREVENTION ═══[/bold]\n")
    
    prevention_table = Table(title="Anti-Explosion Metrics", show_header=True)
    prevention_table.add_column("Metric", style="cyan", width=30)
    prevention_table.add_column("Value", style="yellow", justify="right")
    
    prevention_table.add_row("States Clustered", str(results['states_clustered']))
    prevention_table.add_row("States Pruned", str(results['states_pruned']))
    prevention_table.add_row("Total Prevented", str(results['explosion_prevented']))
    prevention_table.add_row("Clusters Created", str(results['clusters_created']))
    prevention_table.add_row("Avg Cluster Size", f"{results['avg_cluster_size']:.2f}")
    prevention_table.add_row("Deduplication Rate", f"{results['deduplication_rate']:.1f}%")
    
    console.print(prevention_table)
    
    # Adaptive behavior
    console.print("\n[bold]═══ ADAPTIVE BEHAVIOR ═══[/bold]\n")
    
    adaptive_table = Table(title="Dynamic Adjustments", show_header=True)
    adaptive_table.add_column("Metric", style="cyan", width=30)
    adaptive_table.add_column("Value", style="green", justify="right")
    
    adaptive_table.add_row("Attack Surface Density", f"{results['attack_surface_density']:.2f}")
    adaptive_table.add_row("Final State Cap", str(results['final_state_cap']))
    adaptive_table.add_row("Cap Adjustments", str(results['state_cap_adjustments']))
    
    console.print(adaptive_table)
    
    # Efficiency analysis
    console.print("\n[bold]═══ EFFICIENCY ANALYSIS ═══[/bold]\n")
    
    if results['states_explored'] > 0:
        efficiency_score = (
            (results['forms_found'] + results['inputs_found'] + results['api_calls_found']) /
            results['states_explored']
        )
        
        console.print(f"  Attack Surface per State: [bold]{efficiency_score:.2f}[/bold]")
        console.print(f"  Explosion Prevention Rate: [bold]{results['deduplication_rate']:.1f}%[/bold]")
        
        if results['explosion_prevented'] > 0:
            console.print(f"\n  [green]✓ Successfully prevented exploration of {results['explosion_prevented']} redundant states[/green]")
        
        if results['state_cap_adjustments'] > 0:
            console.print(f"  [green]✓ Dynamically adjusted state cap {results['state_cap_adjustments']} times[/green]")
    
    # Scope enforcement
    if results['states_skipped_scope'] > 0:
        console.print(f"\n  [yellow]⚠ Blocked {results['states_skipped_scope']} out-of-scope requests[/yellow]")


async def test_clustering_effectiveness():
    """Test that clustering effectively merges similar states."""
    console.print(Panel.fit(
        "[bold cyan]Clustering Effectiveness Test[/bold cyan]\n"
        "Verifying SimHash-based state clustering",
        border_style="cyan"
    ))
    
    from .adaptive_state_manager import AdaptiveStateManager
    from .dom_hasher import DOMHasher
    
    manager = AdaptiveStateManager(
        initial_max_states=100,
        clustering_threshold=5,
    )
    
    hasher = DOMHasher()
    
    # Simulate similar states (would be near-duplicates in real crawl)
    test_states = [
        {
            'state_id': f'state_{i}',
            'url': f'https://example.com/page?id={i}',
            'dom_hash': hasher.hash_dom(f'<html><body><h1>Page {i}</h1><p>Content</p></body></html>'),
            'simhash': hasher.simhash(f'<html><body><h1>Page {i}</h1><p>Content</p></body></html>'),
            'forms_count': 1,
            'inputs_count': 3,
            'api_calls_count': 0,
        }
        for i in range(50)
    ]
    
    # Add states
    clustered_count = 0
    for state in test_states:
        is_new = manager.add_state(
            state_id=state['state_id'],
            url=state['url'],
            dom_hash=state['dom_hash'],
            simhash=state['simhash'],
            forms_count=state['forms_count'],
            inputs_count=state['inputs_count'],
            api_calls_count=state['api_calls_count'],
        )
        if not is_new:
            clustered_count += 1
    
    metrics = manager.get_metrics()
    
    console.print(f"\n[bold]Clustering Results:[/bold]")
    console.print(f"  Total states processed: {len(test_states)}")
    console.print(f"  Unique states kept: {metrics['unique_states_kept']}")
    console.print(f"  States clustered: {metrics['states_clustered']}")
    console.print(f"  Clusters created: {metrics['clusters_created']}")
    console.print(f"  Deduplication rate: {metrics['deduplication_rate']:.1f}%")
    
    if metrics['states_clustered'] > 0:
        console.print(f"\n[green]✓ Clustering is working! Merged {metrics['states_clustered']} similar states[/green]")
    else:
        console.print(f"\n[yellow]⚠ No clustering occurred (states may be too different)[/yellow]")


async def run_all_tests():
    """Run all state explosion tests."""
    console.print("\n[bold magenta]═══════════════════════════════════════[/bold magenta]")
    console.print("[bold magenta]  STATE EXPLOSION SOLVER TEST SUITE  [/bold magenta]")
    console.print("[bold magenta]═══════════════════════════════════════[/bold magenta]\n")
    
    # Test 1: Clustering effectiveness
    console.print("[bold]Test 1: Clustering Effectiveness[/bold]")
    await test_clustering_effectiveness()
    
    console.print("\n" + "─" * 60 + "\n")
    
    # Test 2: Full state explosion prevention
    # Note: This requires a real target URL
    console.print("[bold]Test 2: Full State Explosion Prevention[/bold]")
    console.print("[yellow]Skipping full crawl test (requires live target)[/yellow]")
    console.print("[yellow]To run: python -m cyberAI.crawl.test_state_explosion --full <target_url>[/yellow]")
    
    console.print("\n[bold green]═══ ALL TESTS COMPLETE ═══[/bold green]\n")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        if len(sys.argv) < 3:
            console.print("[red]Usage: python -m cyberAI.crawl.test_state_explosion --full <target_url>[/red]")
            sys.exit(1)
        asyncio.run(test_state_explosion_prevention())
    else:
        asyncio.run(run_all_tests())
