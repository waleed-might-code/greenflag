"""
Integration example: Wrap existing recon crawler with evidence capture.
Shows how to add WARC capture to the existing CyberAI recon module.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

from cyberAI.evidence import CaptureSession
from cyberAI.evidence.integration import CaptureMiddleware, wrap_playwright_page
from cyberAI.config import Config


async def recon_with_evidence_capture(target_url: str, engagement_id: str):
    """
    Run reconnaissance with automatic evidence capture.
    This shows how to integrate with existing recon code.
    """
    
    # Initialize config
    config = Config.load()
    config.target_url = target_url
    
    # Create evidence capture session
    evidence_session = CaptureSession(
        engagement_id=engagement_id,
        output_dir=config.get_output_path("evidence")
    )
    
    middleware = CaptureMiddleware(evidence_session)
    
    print(f"🔍 Starting recon with evidence capture for {target_url}")
    print(f"📦 Evidence will be stored in: {evidence_session.warc_dir}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.headless)
        context = await browser.new_context(
            user_agent="CyberAI/1.0 Security Scanner"
        )
        page = await context.new_page()
        
        # Wrap page to capture all traffic
        wrap_playwright_page(page, middleware)
        
        # Perform reconnaissance
        print(f"→ Navigating to {target_url}")
        await page.goto(target_url, wait_until="networkidle")
        
        # Discover links
        links = await page.eval_on_selector_all(
            "a[href]", 
            "elements => elements.map(e => e.href)"
        )
        print(f"→ Found {len(links)} links")
        
        # Visit a few pages
        for link in links[:5]:
            if link.startswith(target_url):
                print(f"→ Visiting {link}")
                try:
                    await page.goto(link, timeout=10000)
                except Exception as e:
                    print(f"  ⚠ Error: {e}")
        
        await browser.close()
    
    # Summary
    print(f"\n✅ Recon complete")
    print(f"📊 Captured {len(middleware.session.request_map)} requests")
    print(f"💾 WARC files: {list(evidence_session.warc_dir.glob('*.warc.gz'))}")
    
    evidence_session.close()
    return evidence_session


if __name__ == "__main__":
    asyncio.run(recon_with_evidence_capture(
        "https://example.com",
        "demo-engagement-001"
    ))
