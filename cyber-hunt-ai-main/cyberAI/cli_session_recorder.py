#!/usr/bin/env python3
"""
Interactive CLI for Recording Login Sequences

This tool helps you create login macros by:
1. Opening a browser where you perform the login manually
2. Recording your actions (navigate, fill, click)
3. Saving the sequence as a reusable JSON file
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.async_api import async_playwright, Page

from cyberAI.login_macro import LoginMacroRecorder, LoginSequence, StepAction


class InteractiveLoginRecorder:
    """Interactive login sequence recorder with browser automation."""
    
    def __init__(self):
        self.recorder = LoginMacroRecorder()
        self.recorded_cookies = []
        self.recorded_tokens = {}
    
    async def record_login(
        self,
        start_url: str,
        role: str,
        headless: bool = False
    ) -> Optional[LoginSequence]:
        """
        Record a login sequence interactively.
        
        Args:
            start_url: URL to start recording from
            role: Role name (e.g., 'admin', 'user')
            headless: Run in headless mode
        
        Returns:
            LoginSequence if successful, None otherwise
        """
        logger.info(f"Starting interactive login recorder for role: {role}")
        logger.info(f"Start URL: {start_url}")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()
            
            # Setup recording hooks
            await self._setup_recording_hooks(page)
            
            # Navigate to start URL
            logger.info(f"Navigating to {start_url}")
            self.recorder.add_navigate(start_url, f"Navigate to {start_url}")
            await page.goto(start_url)
            
            # Interactive recording
            logger.info("\n" + "="*60)
            logger.info("RECORDING MODE")
            logger.info("="*60)
            logger.info("Perform your login in the browser window.")
            logger.info("The recorder will capture your actions automatically.")
            logger.info("\nWhen you're done:")
            logger.info("  - Press ENTER in this terminal to finish recording")
            logger.info("  - Or close the browser window")
            logger.info("="*60 + "\n")
            
            # Wait for user to complete login
            try:
                await asyncio.wait_for(
                    self._wait_for_user_input(),
                    timeout=300  # 5 minute timeout
                )
            except asyncio.TimeoutError:
                logger.warning("Recording timed out after 5 minutes")
            
            # Capture final state
            final_url = page.url
            self.recorded_cookies = await context.cookies()
            
            logger.info(f"\nRecording complete. Final URL: {final_url}")
            logger.info(f"Captured {len(self.recorded_cookies)} cookies")
            
            await browser.close()
            
            # Build sequence
            return self._build_sequence(role, final_url)
    
    async def _setup_recording_hooks(self, page: Page):
        """Setup hooks to record user actions."""
        
        # Record navigation
        page.on("framenavigated", lambda frame: self._on_navigate(frame))
        
        # Record form submissions
        await page.expose_function("recordFormSubmit", self._on_form_submit)
        
        # Inject recording script
        await page.add_init_script("""
            // Record form submissions
            document.addEventListener('submit', (e) => {
                const form = e.target;
                window.recordFormSubmit({
                    action: form.action,
                    method: form.method || 'GET'
                });
            }, true);
            
            // Record input fills
            document.addEventListener('input', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                    e.target.setAttribute('data-recorded', 'true');
                }
            }, true);
        """)
    
    def _on_navigate(self, frame):
        """Handle navigation events."""
        if frame.parent_frame is None:  # Main frame only
            url = frame.url
            if url and not url.startswith("about:"):
                logger.debug(f"Navigated to: {url}")
    
    def _on_form_submit(self, data):
        """Handle form submission."""
        logger.debug(f"Form submitted: {data['method']} {data['action']}")
    
    async def _wait_for_user_input(self):
        """Wait for user to press ENTER."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, "Press ENTER when login is complete...")
    
    def _build_sequence(self, role: str, final_url: str) -> LoginSequence:
        """Build the login sequence from recorded actions."""
        
        # Add final validation steps
        self.recorder.add_assert_url(final_url.split('?')[0])
        
        # Add cookie extraction
        from cyberAI.login_macro import LoginStep
        self.recorder.recorded_steps.append(LoginStep(
            action=StepAction.EXTRACT_COOKIES,
            description="Extract session cookies"
        ))
        
        # Build sequence
        sequence = self.recorder.build_sequence(
            name=f"{role.capitalize()} Login",
            role=role,
            success_indicators=[
                {"type": "url_contains", "value": final_url.split('?')[0]},
                {"type": "has_cookies", "value": "true"}
            ]
        )
        
        return sequence


async def record_login_interactive():
    """Interactive CLI for recording login sequences."""
    print("\n" + "="*60)
    print("  LOGIN SEQUENCE RECORDER")
    print("="*60 + "\n")
    
    # Get inputs
    start_url = input("Enter login URL: ").strip()
    if not start_url:
        print("Error: URL is required")
        return
    
    role = input("Enter role name (e.g., admin, user): ").strip()
    if not role:
        print("Error: Role name is required")
        return
    
    output_dir = input("Output directory [login_sequences]: ").strip() or "login_sequences"
    
    headless_input = input("Run in headless mode? [y/N]: ").strip().lower()
    headless = headless_input == 'y'
    
    print()
    
    # Record
    recorder = InteractiveLoginRecorder()
    sequence = await recorder.record_login(start_url, role, headless)
    
    if sequence:
        # Save sequence
        output_path = Path(output_dir) / f"{role}_login.json"
        sequence.save(output_path)
        
        print("\n" + "="*60)
        print("✓ LOGIN SEQUENCE SAVED")
        print("="*60)
        print(f"File: {output_path}")
        print(f"Role: {role}")
        print(f"Steps: {len(sequence.steps)}")
        print("\nYou can now use this sequence in your crawls!")
        print("="*60 + "\n")
    else:
        print("\n✗ Failed to record login sequence\n")


async def create_manual_sequence():
    """Create a login sequence manually through prompts."""
    print("\n" + "="*60)
    print("  MANUAL LOGIN SEQUENCE BUILDER")
    print("="*60 + "\n")
    
    role = input("Enter role name: ").strip()
    if not role:
        print("Error: Role name is required")
        return
    
    recorder = LoginMacroRecorder()
    
    print("\nBuilding login sequence step by step...")
    print("Available actions: navigate, fill, click, wait, assert_url, done\n")
    
    while True:
        action = input("Action (or 'done' to finish): ").strip().lower()
        
        if action == "done":
            break
        elif action == "navigate":
            url = input("  URL: ").strip()
            recorder.add_navigate(url, f"Navigate to {url}")
            print(f"  ✓ Added: Navigate to {url}")
        
        elif action == "fill":
            selector = input("  Selector (e.g., input[name='email']): ").strip()
            value_ref = input("  Value reference (e.g., {{username}}): ").strip()
            recorder.add_fill(selector, value_ref, f"Fill {selector}")
            print(f"  ✓ Added: Fill {selector} with {value_ref}")
        
        elif action == "click":
            selector = input("  Selector (e.g., button[type='submit']): ").strip()
            recorder.add_click(selector, f"Click {selector}")
            print(f"  ✓ Added: Click {selector}")
        
        elif action == "wait":
            selector = input("  Wait for selector: ").strip()
            timeout = input("  Timeout (ms) [30000]: ").strip() or "30000"
            recorder.add_wait_for_selector(selector, int(timeout))
            print(f"  ✓ Added: Wait for {selector}")
        
        elif action == "assert_url":
            expected = input("  Expected URL contains: ").strip()
            recorder.add_assert_url(expected)
            print(f"  ✓ Added: Assert URL contains {expected}")
        
        else:
            print(f"  Unknown action: {action}")
        
        print()
    
    # Build sequence
    success_url = input("\nSuccess indicator (URL contains): ").strip()
    sequence = recorder.build_sequence(
        name=f"{role.capitalize()} Login",
        role=role,
        success_indicators=[
            {"type": "url_contains", "value": success_url}
        ]
    )
    
    # Save
    output_dir = input("Output directory [login_sequences]: ").strip() or "login_sequences"
    output_path = Path(output_dir) / f"{role}_login.json"
    sequence.save(output_path)
    
    print(f"\n✓ Sequence saved to {output_path}\n")


async def main():
    """Main CLI entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "manual":
        await create_manual_sequence()
    else:
        await record_login_interactive()


if __name__ == "__main__":
    asyncio.run(main())
