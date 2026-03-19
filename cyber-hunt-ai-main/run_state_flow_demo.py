#!/usr/bin/env python3
"""
Complete demo of state-flow crawler integration.
Shows how the crawler solves state explosion and integrates with the system.
"""

import asyncio
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


async def demo_state_explosion_solution():
    """Demonstrate the state explosion solution."""
    
    console.print("\n")
    console.print(Panel.fit(
        "[bold cyan]State-Flow Crawler Demo[/bold cyan]\n"
        "[yellow]Agent #1: State Explosion Solution[/yellow]\n\n"
        "This demo shows how the crawler solves state explosion\n"
        "in modern SPAs through intelligent prioritization and deduplication.",
        border_style="cyan"
    ))
    
    # Configuration
    target_url = "https://example.com"
    max_states = 10
    max_depth = 3
    output_dir = Path("outputs/demo")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    console.print("\n[bold]Configuration:[/bold]")
    config_table = Table(show_header=False, box=None)
    config_table.add_column("Key", style="cyan")
    config_table.add_column("Value", style="white")
    config_table.add_row("Target URL", target_url)
    config_table.add_row("Max States", str(max_states))
    config_table.add_row("Max Depth", str(max_depth))
    config_table.add_row("Output Dir", str(output_dir))
    console.print(config_table)
    
    console.print("\n[bold yellow]Starting crawl...[/bold yellow]\n")
    
    try:
        from cyberAI.crawl import StateFlowCrawler
        
        crawler = StateFlowCrawler(
            target_url=target_url,
            max_states=max_states,
            max_depth=max_depth,
            screenshot_dir=output_dir / "screenshots",
            headless=True,
        )
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Crawling...", total=None)
            results = await crawler.crawl()
            progress.update(task, completed=True)
        
        # Display results
        console.print("\n[bold green]✓ Crawl Complete![/bold green]\n")
        
        # Summary table
        summary = Table(title="Crawl Summary", border_style="green")
        summary.add_column("Metric", style="cyan", justify="left")
        summary.add_column("Value", style="magenta", justify="right")
        
        summary.add_row("States Discovered", str(results["states_discovered"]))
        summary.add_row("Transitions", str(results["transitions_discovered"]))
        summary.add_row("Unique URLs", str(results["unique_urls"]))
        summary.add_row("Forms Found", str(results["total_forms"]))
        summary.add_row("Input Fields", str(results["total_inputs"]))
        summary.add_row("Links Found", str(results["total_links"]))
        
        console.print(summary)
        
        # Frontier statistics
        console.print("\n[bold]Frontier Statistics:[/bold]")
        stats = results["frontier_stats"]
        frontier_table = Table(show_header=False, box=None)
        frontier_table.add_column("Metric", style="cyan")
        frontier_table.add_column("Value", style="white")
        
        for key, value in stats.items():
            frontier_table.add_row(key.replace("_", " ").title(), str(value))
        
        console.print(frontier_table)
        
        # State explosion solution demonstration
        console.print("\n[bold]State Explosion Solution:[/bold]")
        solution_table = Table(box=None)
        solution_table.add_column("Feature", style="cyan")
        solution_table.add_column("Status", style="green")
        solution_table.add_column("Impact", style="yellow")
        
        solution_table.add_row(
            "Priority Queue",
            "✓ Active",
            f"Explored {stats['states_explored']} high-value states first"
        )
        solution_table.add_row(
            "State Cap",
            "✓ Enforced",
            f"Limited to {stats['max_states']} states (finite completion)"
        )
        solution_table.add_row(
            "Deduplication",
            "✓ Active",
            f"SimHash prevented duplicate exploration"
        )
        solution_table.add_row(
            "Pruning",
            "✓ Active",
            f"Pruned {stats['states_pruned']} low-priority states"
        )
        
        console.print(solution_table)
        
        # Save results
        results_file = output_dir / "demo_results.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        console.print(f"\n[green]Results saved to: {results_file}[/green]")
        
        # Show attack surface
        if results["states"]:
            console.print("\n[bold]Attack Surface Discovered:[/bold]")
            attack_table = Table()
            attack_table.add_column("State ID", style="cyan")
            attack_table.add_column("URL", style="white", max_width=40)
            attack_table.add_column("Forms", style="green", justify="center")
            attack_table.add_column("Inputs", style="yellow", justify="center")
            attack_table.add_column("Depth", style="blue", justify="center")
            
            for state in sorted(results["states"], key=lambda s: s["forms"] + s["inputs"], reverse=True)[:5]:
                attack_table.add_row(
                    state["state_id"],
                    state["url"][:40] + "..." if len(state["url"]) > 40 else state["url"],
                    str(state["forms"]),
                    str(state["inputs"]),
                    str(state["depth"]),
                )
            
            console.print(attack_table)
        
        console.print("\n[bold green]Demo completed successfully![/bold green]\n")
        
        return True
        
    except ImportError as e:
        console.print(f"\n[red]Import error: {e}[/red]")
        console.print("[yellow]Make sure dependencies are installed:[/yellow]")
        console.print("  pip install playwright beautifulsoup4 lxml simhash rich loguru")
        console.print("  playwright install chromium")
        return False
        
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())
        return False


if __name__ == "__main__":
    console.print("\n[bold cyan]═" * 40 + "[/bold cyan]")
    console.print("[bold cyan]State-Flow Crawler - State Explosion Solution[/bold cyan]")
    console.print("[bold cyan]═" * 40 + "[/bold cyan]")
    
    success = asyncio.run(demo_state_explosion_solution())
    
    if success:
        console.print("\n[bold green]✓ All systems operational[/bold green]")
        console.print("\n[dim]Next steps:[/dim]")
        console.print("  1. Review results in outputs/demo/")
        console.print("  2. Check docs/QUICKSTART.md for usage examples")
        console.print("  3. Integrate with main recon pipeline")
        console.print("  4. Run on real targets with higher state limits\n")
    else:
        console.print("\n[bold red]✗ Demo failed[/bold red]\n")
    
    exit(0 if success else 1)
