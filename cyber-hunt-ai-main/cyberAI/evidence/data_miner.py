"""
Data Mining Integration - Massive Data Collection with Evidence Capture
Demonstrates how to use the evidence system for large-scale data mining.
"""

import asyncio
from pathlib import Path
from typing import List, Set
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

from cyberAI.evidence import CaptureSession, CaptureMiddleware
from cyberAI.evidence.integration import wrap_playwright_page
from cyberAI.config import Config


class MassiveDataMiner:
    """
    Large-scale data mining crawler with evidence capture.
    Mines every data point from web apps, APIs, and all scrapable sources.
    """
    
    def __init__(self, target_url: str, engagement_id: str, output_dir: Path):
        self.target_url = target_url
        self.engagement_id = engagement_id
        self.output_dir = output_dir
        
        # Evidence capture
        self.evidence_session = CaptureSession(engagement_id, output_dir / "evidence")
        self.middleware = CaptureMiddleware(self.evidence_session)
        
        # Crawl state
        self.visited_urls: Set[str] = set()
        self.discovered_urls: Set[str] = set()
        self.api_endpoints: Set[str] = set()
        self.data_points_collected = 0
        
        # Stats
        self.stats = {
            "pages_crawled": 0,
            "api_calls_captured": 0,
            "forms_discovered": 0,
            "data_points": 0,
            "warc_files": 0
        }
    
    async def mine_target(self, max_pages: int = 1000):
        """
        Mine massive amounts of data from target application.
        Captures every HTTP request/response for analysis.
        """
        print(f"🚀 Starting massive data mining for {self.target_url}")
        print(f"📦 Evidence will be stored in: {self.evidence_session.warc_dir}")
        print(f"🎯 Target: Mine up to {max_pages} pages\n")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="CyberAI/1.0 DataMiner",
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()
            
            # Wrap page for evidence capture
            wrap_playwright_page(page, self.middleware)
            
            # Start with seed URL
            self.discovered_urls.add(self.target_url)
            
            while self.discovered_urls and len(self.visited_urls) < max_pages:
                url = self.discovered_urls.pop()
                
                if url in self.visited_urls:
                    continue
                
                await self._mine_page(page, url)
                self.visited_urls.add(url)
                
                if len(self.visited_urls) % 10 == 0:
                    self._print_progress()
            
            await browser.close()
        
        self.evidence_session.close()
        self._print_final_stats()
    
    async def _mine_page(self, page, url: str):
        """Mine a single page for all data points."""
        try:
            print(f"⛏️  Mining: {url}")
            
            # Navigate and capture all traffic
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            self.stats["pages_crawled"] += 1
            
            # Extract links
            links = await page.eval_on_selector_all(
                "a[href]",
                "elements => elements.map(e => e.href)"
            )
            self._process_links(links)
            
            # Extract forms
            forms = await page.eval_on_selector_all(
                "form",
                """forms => forms.map(f => ({
                    action: f.action,
                    method: f.method,
                    fields: Array.from(f.elements).map(e => ({
                        name: e.name,
                        type: e.type
                    }))
                }))"""
            )
            self.stats["forms_discovered"] += len(forms)
            
            # Extract API endpoints from network traffic
            await self._extract_api_endpoints(page)
            
            # Count data points
            self.data_points_collected += 1
            self.stats["data_points"] = len(self.middleware.session.request_map)
            
        except Exception as e:
            print(f"   ⚠️  Error mining {url}: {e}")
    
    def _process_links(self, links: List[str]):
        """Process discovered links."""
        base_domain = urlparse(self.target_url).netloc
        
        for link in links:
            parsed = urlparse(link)
            
            # Only follow same-domain links
            if parsed.netloc == base_domain or not parsed.netloc:
                full_url = urljoin(self.target_url, link)
                
                if full_url not in self.visited_urls:
                    self.discovered_urls.add(full_url)
    
    async def _extract_api_endpoints(self, page):
        """Extract API endpoints from network traffic."""
        # This would be enhanced with actual network listener
        # For now, we track via the middleware
        for req_id, record in self.middleware.session.request_map.items():
            if "/api/" in record.target_uri or record.target_uri.endswith(".json"):
                self.api_endpoints.add(record.target_uri)
                self.stats["api_calls_captured"] += 1
    
    def _print_progress(self):
        """Print mining progress."""
        print(f"\n📊 Progress Update:")
        print(f"   Pages crawled: {self.stats['pages_crawled']}")
        print(f"   Data points captured: {self.stats['data_points']}")
        print(f"   API endpoints found: {len(self.api_endpoints)}")
        print(f"   Forms discovered: {self.stats['forms_discovered']}")
        print(f"   Queue size: {len(self.discovered_urls)}\n")
    
    def _print_final_stats(self):
        """Print final mining statistics."""
        warc_files = list(self.evidence_session.warc_dir.glob("*.warc.gz"))
        total_size = sum(f.stat().st_size for f in warc_files)
        
        print("\n" + "="*60)
        print("✅ DATA MINING COMPLETE")
        print("="*60)
        print(f"📄 Pages crawled: {self.stats['pages_crawled']}")
        print(f"🔗 Unique URLs visited: {len(self.visited_urls)}")
        print(f"🌐 API endpoints discovered: {len(self.api_endpoints)}")
        print(f"📝 Forms discovered: {self.stats['forms_discovered']}")
        print(f"💾 Data points captured: {self.stats['data_points']}")
        print(f"📦 WARC files created: {len(warc_files)}")
        print(f"💿 Total storage: {total_size / 1024 / 1024:.2f} MB")
        print(f"📂 Evidence location: {self.evidence_session.warc_dir}")
        print("="*60)


async def main():
    """Demo: Mine data from a target application."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python data_miner.py <target_url> [max_pages]")
        print("Example: python data_miner.py https://example.com 100")
        sys.exit(1)
    
    target_url = sys.argv[1]
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    
    miner = MassiveDataMiner(
        target_url=target_url,
        engagement_id=f"mining-{urlparse(target_url).netloc}",
        output_dir=Path("outputs")
    )
    
    await miner.mine_target(max_pages=max_pages)


if __name__ == "__main__":
    asyncio.run(main())
