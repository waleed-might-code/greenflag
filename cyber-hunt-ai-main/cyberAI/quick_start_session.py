"""
Quick Start Guide - Session Management System

This script provides a step-by-step walkthrough of setting up and using
the session management system.
"""

import asyncio
from pathlib import Path
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()


def print_step(step_num: int, title: str, description: str):
    """Print a formatted step."""
    console.print(f"\n[bold cyan]Step {step_num}: {title}[/bold cyan]")
    console.print(f"[dim]{description}[/dim]\n")


async def quick_start():
    """Interactive quick start guide."""
    console.print(Panel.fit(
        "[bold green]Session Management System - Quick Start[/bold green]\n"
        "This guide will help you set up session management for your security testing.",
        border_style="green"
    ))
    
    # Step 1: Check prerequisites
    print_step(
        1,
        "Check Prerequisites",
        "Ensure you have the required dependencies installed"
    )
    
    console.print("Required packages:")
    console.print("  • playwright")
    console.print("  • redis (optional, for persistent sessions)")
    console.print("  • click (for CLI tools)")
    
    if not Confirm.ask("\nAre all dependencies installed?"):
        console.print("\n[yellow]Install with:[/yellow]")
        console.print("  pip install -r requirements.txt")
        console.print("  playwright install chromium")
        return
    
    # Step 2: Create login sequences directory
    print_step(
        2,
        "Create Login Sequences Directory",
        "Login sequences are stored as JSON files"
    )
    
    sequences_dir = Path("login_sequences")
    sequences_dir.mkdir(exist_ok=True)
    console.print(f"[green]✓[/green] Created directory: {sequences_dir}")
    
    # Step 3: Create a login sequence
    print_step(
        3,
        "Create Your First Login Sequence",
        "Use the CLI tool to create a login sequence interactively"
    )
    
    console.print("Run this command:")
    console.print("[cyan]python cyberAI/cli_login_macro.py create[/cyan]\n")
    
    console.print("Or create manually from templates in login_sequences/")
    console.print("Example templates:")
    console.print("  • admin_login.json - Standard form login")
    console.print("  • user_login.json - Login with 2FA")
    console.print("  • oauth_login.json - OAuth flow")
    
    if not Confirm.ask("\nHave you created a login sequence?"):
        console.print("\n[yellow]Create one and come back to continue[/yellow]")
        return
    
    # Step 4: Test the login sequence
    print_step(
        4,
        "Test Your Login Sequence",
        "Verify the login sequence works correctly"
    )
    
    console.print("Run this command:")
    console.print("[cyan]python cyberAI/cli_login_macro.py test login_sequences/your_sequence.json[/cyan]\n")
    
    console.print("This will:")
    console.print("  • Execute the login sequence")
    console.print("  • Show you each step in the browser")
    console.print("  • Capture cookies and tokens")
    console.print("  • Verify success indicators")
    
    # Step 5: Setup Redis (optional)
    print_step(
        5,
        "Setup Redis (Optional)",
        "Redis provides persistent session storage across restarts"
    )
    
    use_redis = Confirm.ask("Do you want to use Redis?")
    
    if use_redis:
        console.print("\n1. Install Redis:")
        console.print("   • macOS: brew install redis")
        console.print("   • Ubuntu: sudo apt-get install redis-server")
        console.print("   • Docker: docker run -d -p 6379:6379 redis")
        
        console.print("\n2. Add to your .env file:")
        console.print("   REDIS_URL=redis://localhost:6379/0")
    else:
        console.print("\n[dim]Skipping Redis - sessions will be stored in memory[/dim]")
    
    # Step 6: Configure your engagement
    print_step(
        6,
        "Configure Your Engagement",
        "Set up engagement configuration with roles and credentials"
    )
    
    console.print("Example configuration:")
    console.print("""
[cyan]from cyberAI.session_integration import create_session_integration

session_integration = await create_session_integration(
    engagement_id="my-engagement-001",
    roles=["guest", "user", "admin"],
    login_sequences_dir=Path("login_sequences"),
    credentials={
        "guest": {},
        "user": {"username": "user@example.com", "password": "pass123"},
        "admin": {"username": "admin@example.com", "password": "adminpass"}
    },
    validation_url="/api/me",
    redis_url="redis://localhost:6379/0"  # Optional
)[/cyan]
    """)
    
    # Step 7: Integrate with your crawler
    print_step(
        7,
        "Integrate with Your Crawler",
        "Add session management to your existing crawler"
    )
    
    console.print("Basic integration:")
    console.print("""
[cyan]# Get session-aware browser context
context, session = await session_integration.get_session_context(
    browser=browser,
    role="admin"
)

page = await context.new_page()

# Your crawling logic here
await page.goto("https://example.com/dashboard")

# Periodically check session health
if await session_integration.should_check_health("admin"):
    success, _ = await session_integration.validate_and_repair_session(
        browser=browser,
        role="admin",
        page=page
    )[/cyan]
    """)
    
    # Step 8: Run the demo
    print_step(
        8,
        "Run the Demo",
        "See the session management system in action"
    )
    
    console.print("Run the demo script:")
    console.print("[cyan]python cyberAI/demo_session_management.py[/cyan]\n")
    
    console.print("This demonstrates:")
    console.print("  • Session creation and storage")
    console.print("  • Health checking")
    console.print("  • Automatic repair")
    console.print("  • Multi-role crawling")
    
    # Step 9: Review examples
    print_step(
        9,
        "Review Examples",
        "Check out the example implementations"
    )
    
    console.print("Example files:")
    console.print("  • examples/session_crawler_example.py - Full crawler integration")
    console.print("  • integration/session_aware_recon.py - Recon module integration")
    console.print("  • SESSION_MANAGEMENT.md - Complete documentation")
    
    # Final step
    console.print("\n" + "="*60)
    console.print("[bold green]Setup Complete![/bold green]")
    console.print("\nNext steps:")
    console.print("  1. Create login sequences for your target application")
    console.print("  2. Test each sequence thoroughly")
    console.print("  3. Integrate session management into your crawlers")
    console.print("  4. Monitor session health and repair rates")
    console.print("\nFor help, see SESSION_MANAGEMENT.md or run:")
    console.print("  python cyberAI/cli_login_macro.py --help")
    console.print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(quick_start())
