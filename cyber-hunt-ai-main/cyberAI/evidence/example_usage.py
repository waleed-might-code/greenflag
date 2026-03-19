"""
Example usage of the evidence capture system.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

from cyberAI.evidence import CaptureSession, CaptureMiddleware
from cyberAI.evidence.integration import wrap_playwright_page


async def example_crawl_with_capture():
    """Example: Crawl a site and capture all traffic to WARC."""
    
    # Initialize capture session
    session = CaptureSession(
        engagement_id="demo-engagement-001",
        output_dir=Path("outputs/evidence_demo")
    )
    
    middleware = CaptureMiddleware(session)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Wrap page to capture traffic
        wrap_playwright_page(page, middleware)
        
        # Navigate and interact
        await page.goto("https://example.com")
        await page.click("a")
        
        # Simulate finding a vulnerability
        finding_id = "finding-xss-001"
        request_ids = list(middleware.session.request_map.keys())[:2]
        
        # Link finding to evidence
        session.link_finding(finding_id, request_ids)
        
        await browser.close()
    
    # Generate evidence pack
    session.provenance.generate_evidence_pack(
        finding_id,
        session.warc_dir,
        Path("outputs/evidence_demo/finding-xss-001-evidence.warc.gz")
    )
    
    session.close()
    print(f"✓ Captured traffic to WARC")
    print(f"✓ Linked finding {finding_id} to evidence")


if __name__ == "__main__":
    asyncio.run(example_crawl_with_capture())
