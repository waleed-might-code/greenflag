"""
CLI Tool for Login Macro Management

Commands:
- record: Record a new login sequence interactively
- test: Test an existing login sequence
- list: List all login sequences
- create: Create a login sequence from template
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import click
from loguru import logger
from playwright.async_api import async_playwright
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table

from cyberAI.login_macro import (
    LoginSequence, LoginMacroExecutor, LoginMacroRecorder,
    LoginStep, StepAction
)

console = Console()


@click.group()
def cli():
    """Login Macro Management CLI"""
    pass


@cli.command()
@click.option("--name", prompt="Sequence name", help="Name for the login sequence")
@click.option("--role", prompt="Role name", help="Role this sequence is for (e.g., admin, user)")
@click.option("--output", type=click.Path(), help="Output path for sequence JSON")
def create(name: str, role: str, output: Optional[str]):
    """Create a login sequence from template interactively."""
    recorder = LoginMacroRecorder()
    
    console.print(f"\n[bold]Creating login sequence: {name} for role: {role}[/bold]\n")
    
    # Get login URL
    login_url = Prompt.ask("Login page URL")
    recorder.add_navigate(login_url, "Navigate to login page")
    
    # Username field
    username_selector = Prompt.ask("Username field selector (CSS)")
    recorder.add_fill(username_selector, "{{username}}", "Fill username")
    
    # Password field
    password_selector = Prompt.ask("Password field selector (CSS)")
    recorder.add_fill(password_selector, "{{password}}", "Fill password")
    
    # Submit button
    submit_selector = Prompt.ask("Submit button selector (CSS)")
    recorder.add_click(submit_selector, "Click submit")
    
    # Wait for navigation
    if Confirm.ask("Add wait for selector after submit?"):
        wait_selector = Prompt.ask("Selector to wait for (e.g., dashboard element)")
        recorder.add_wait_for_selector(wait_selector)
    
    # CAPTCHA/2FA
    if Confirm.ask("Does this login have CAPTCHA or 2FA?"):
        recorder.add_manual_pause("Solve CAPTCHA or complete 2FA")
    
    # Success indicators
    success_url = Prompt.ask("Success URL pattern (e.g., /dashboard)")
    success_indicators = [
        {"type": "url_contains", "value": success_url}
    ]
    
    # Build sequence
    sequence = recorder.build_sequence(name, role, success_indicators)
    
    # Save
    if not output:
        output = f"login_sequences/{role}_login.json"
    
    output_path = Path(output)
    sequence.save(output_path)
    
    console.print(f"\n[green]✓[/green] Login sequence saved to: {output_path}")
    console.print(f"\nSteps created: {len(sequence.steps)}")


@cli.command()
@click.argument("sequence_path", type=click.Path(exists=True))
@click.option("--username", prompt=True, help="Username for testing")
@click.option("--password", prompt=True, hide_input=True, help="Password for testing")
@click.option("--headless/--headed", default=False, help="Run in headless mode")
@click.option("--screenshot-dir", type=click.Path(), help="Directory for debug screenshots")
def test(sequence_path: str, username: str, password: str, headless: bool, screenshot_dir: Optional[str]):
    """Test a login sequence."""
    asyncio.run(_test_sequence(sequence_path, username, password, headless, screenshot_dir))


async def _test_sequence(
    sequence_path: str,
    username: str,
    password: str,
    headless: bool,
    screenshot_dir: Optional[str]
):
    """Async test execution."""
    console.print(f"\n[bold]Testing login sequence: {sequence_path}[/bold]\n")
    
    # Load sequence
    sequence = LoginSequence.load(Path(sequence_path))
    console.print(f"Sequence: {sequence.name}")
    console.print(f"Role: {sequence.role}")
    console.print(f"Steps: {len(sequence.steps)}\n")
    
    # Prepare credentials
    credentials = {
        "username": username,
        "password": password
    }
    
    # Setup screenshot dir
    screenshot_path = Path(screenshot_dir) if screenshot_dir else None
    if screenshot_path:
        screenshot_path.mkdir(parents=True, exist_ok=True)
    
    # Execute
    executor = LoginMacroExecutor()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            with console.status("[bold green]Executing login sequence..."):
                result = await executor.execute(
                    page=page,
                    sequence=sequence,
                    credentials=credentials,
                    screenshot_dir=screenshot_path
                )
            
            # Display results
            if result["success"]:
                console.print("\n[green]✓ Login successful![/green]\n")
                console.print(f"Cookies captured: {len(result['cookies'])}")
                console.print(f"Tokens captured: {len(result['tokens'])}")
                
                if result["tokens"]:
                    console.print("\nTokens:")
                    for name, value in result["tokens"].items():
                        console.print(f"  {name}: {value[:20]}...")
            else:
                console.print(f"\n[red]✗ Login failed: {result['error']}[/red]\n")
            
            # Show execution log
            console.print("\n[bold]Execution Log:[/bold]")
            table = Table(show_header=True)
            table.add_column("Step", style="cyan")
            table.add_column("Action", style="magenta")
            table.add_column("Status", style="green")
            table.add_column("Details")
            
            for log_entry in result["execution_log"]:
                status = "✓" if log_entry.get("success") else "✗"
                status_style = "green" if log_entry.get("success") else "red"
                details = log_entry.get("error", "") or log_entry.get("url", "") or log_entry.get("selector", "")
                
                table.add_row(
                    str(log_entry["step"]),
                    log_entry["action"],
                    f"[{status_style}]{status}[/{status_style}]",
                    details[:50]
                )
            
            console.print(table)
            
        finally:
            await browser.close()


@cli.command()
@click.option("--dir", "directory", type=click.Path(), default="login_sequences", help="Directory to scan")
def list(directory: str):
    """List all login sequences in a directory."""
    dir_path = Path(directory)
    
    if not dir_path.exists():
        console.print(f"[red]Directory not found: {directory}[/red]")
        return
    
    sequences = list(dir_path.glob("*.json"))
    
    if not sequences:
        console.print(f"[yellow]No login sequences found in {directory}[/yellow]")
        return
    
    console.print(f"\n[bold]Login Sequences in {directory}:[/bold]\n")
    
    table = Table(show_header=True)
    table.add_column("File", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Role", style="green")
    table.add_column("Steps", style="yellow")
    table.add_column("Updated")
    
    for seq_path in sequences:
        try:
            seq = LoginSequence.load(seq_path)
            table.add_row(
                seq_path.name,
                seq.name,
                seq.role,
                str(len(seq.steps)),
                seq.updated_at[:10]
            )
        except Exception as e:
            table.add_row(
                seq_path.name,
                "[red]Error loading[/red]",
                "",
                "",
                ""
            )
    
    console.print(table)


@cli.command()
@click.argument("sequence_path", type=click.Path(exists=True))
def show(sequence_path: str):
    """Show details of a login sequence."""
    sequence = LoginSequence.load(Path(sequence_path))
    
    console.print(f"\n[bold]{sequence.name}[/bold]")
    console.print(f"Role: {sequence.role}")
    console.print(f"Created: {sequence.created_at}")
    console.print(f"Updated: {sequence.updated_at}\n")
    
    console.print("[bold]Steps:[/bold]")
    table = Table(show_header=True)
    table.add_column("#", style="cyan")
    table.add_column("Action", style="magenta")
    table.add_column("Details", style="white")
    table.add_column("Required", style="yellow")
    
    for idx, step in enumerate(sequence.steps, 1):
        details = []
        if step.selector:
            details.append(f"selector: {step.selector}")
        if step.url:
            details.append(f"url: {step.url}")
        if step.value_ref:
            details.append(f"value: {step.value_ref}")
        if step.expected:
            details.append(f"expected: {step.expected}")
        
        table.add_row(
            str(idx),
            step.action.value,
            ", ".join(details) if details else "-",
            "Yes" if step.required else "No"
        )
    
    console.print(table)
    
    console.print("\n[bold]Success Indicators:[/bold]")
    for indicator in sequence.success_indicators:
        console.print(f"  • {indicator['type']}: {indicator['value']}")


if __name__ == "__main__":
    cli()
