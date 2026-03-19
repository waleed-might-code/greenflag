"""
Comprehensive Seed Generator - Discovers all entry points.
Extracts URLs from: sitemaps, robots.txt, WordPress, common paths, etc.
"""

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger


class SeedGenerator:
    """
    Generates comprehensive seed URLs for crawling.
    
    Sources:
    - Sitemap.xml
    - Robots.txt
    - WordPress discovery (wp-json, wp-sitemap.xml)
    - Common paths
    - Meta tags
    - RSS/Atom feeds
    """
    
    def __init__(self):
        """Initialize seed generator."""
        self.common_paths = [
            "/",
            "/api",
            "/api/v1",
            "/api/v2",
            "/graphql",
            "/admin",
            "/dashboard",
            "/login",
            "/register",
            "/signup",
            "/profile",
            "/settings",
            "/search",
            "/about",
            "/contact",
            "/help",
            "/docs",
            "/documentation",
            "/blog",
            "/news",
            "/products",
            "/services",
            "/pricing",
        ]
        
        self.sitemap_paths = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/post-sitemap.xml",
            "/page-sitemap.xml",
            "/wp-sitemap.xml",
            "/sitemap1.xml",
        ]
        
        self.wordpress_paths = [
            "/wp-json",
            "/wp-json/wp/v2",
            "/wp-json/wp/v2/posts",
            "/wp-json/wp/v2/pages",
            "/wp-json/wp/v2/users",
            "/wp-sitemap.xml",
            "/wp-admin",
            "/wp-login.php",
        ]
    
    async def generate_seeds(
        self,
        base_url: str,
        client: httpx.AsyncClient,
    ) -> list[str]:
        """
        Generate comprehensive seed URLs.
        
        Args:
            base_url: Base URL to generate seeds for
            client: HTTP client
            
        Returns:
            List of seed URLs
        """
        seeds = set()
        
        # Add base URL
        seeds.add(base_url)
        
        # Try robots.txt
        robots_urls = await self._parse_robots_txt(base_url, client)
        seeds.update(robots_urls)
        logger.info(f"Found {len(robots_urls)} URLs from robots.txt")
        
        # Try sitemaps
        sitemap_urls = await self._parse_sitemaps(base_url, client)
        seeds.update(sitemap_urls)
        logger.info(f"Found {len(sitemap_urls)} URLs from sitemaps")
        
        # Try WordPress discovery
        wp_urls = await self._discover_wordpress(base_url, client)
        seeds.update(wp_urls)
        if wp_urls:
            logger.info(f"Found {len(wp_urls)} WordPress URLs")
        
        # Add common paths
        for path in self.common_paths:
            seeds.add(base_url.rstrip('/') + path)
        
        # Try homepage for meta links
        homepage_urls = await self._parse_homepage(base_url, client)
        seeds.update(homepage_urls)
        
        logger.info(f"Generated {len(seeds)} total seed URLs")
        
        return list(seeds)
    
    async def _parse_robots_txt(
        self,
        base_url: str,
        client: httpx.AsyncClient,
    ) -> set[str]:
        """Parse robots.txt for URLs."""
        urls = set()
        
        try:
            robots_url = base_url.rstrip('/') + '/robots.txt'
            response = await client.get(robots_url, timeout=10.0)
            
            if response.status_code != 200:
                return urls
            
            # Extract Sitemap directives
            for line in response.text.split('\n'):
                line = line.strip()
                if line.lower().startswith('sitemap:'):
                    sitemap_url = line.split(':', 1)[1].strip()
                    urls.add(sitemap_url)
                
                # Extract Disallow paths (these are interesting for security testing)
                elif line.lower().startswith('disallow:'):
                    path = line.split(':', 1)[1].strip()
                    if path and path != '/':
                        urls.add(base_url.rstrip('/') + path)
        
        except Exception as e:
            logger.debug(f"Failed to parse robots.txt: {e}")
        
        return urls
    
    async def _parse_sitemaps(
        self,
        base_url: str,
        client: httpx.AsyncClient,
    ) -> set[str]:
        """Parse sitemap.xml files."""
        urls = set()
        
        for sitemap_path in self.sitemap_paths:
            sitemap_url = base_url.rstrip('/') + sitemap_path
            
            try:
                response = await client.get(sitemap_url, timeout=10.0)
                
                if response.status_code != 200:
                    continue
                
                # Parse XML
                soup = BeautifulSoup(response.content, 'xml')
                
                # Extract <loc> tags
                for loc in soup.find_all('loc'):
                    url = loc.text.strip()
                    if url:
                        urls.add(url)
                
                # If this is a sitemap index, recursively parse child sitemaps
                for sitemap in soup.find_all('sitemap'):
                    loc = sitemap.find('loc')
                    if loc:
                        child_urls = await self._parse_single_sitemap(
                            loc.text.strip(),
                            client,
                        )
                        urls.update(child_urls)
            
            except Exception as e:
                logger.debug(f"Failed to parse {sitemap_path}: {e}")
        
        return urls
    
    async def _parse_single_sitemap(
        self,
        sitemap_url: str,
        client: httpx.AsyncClient,
    ) -> set[str]:
        """Parse a single sitemap file."""
        urls = set()
        
        try:
            response = await client.get(sitemap_url, timeout=10.0)
            
            if response.status_code != 200:
                return urls
            
            soup = BeautifulSoup(response.content, 'xml')
            
            for loc in soup.find_all('loc'):
                url = loc.text.strip()
                if url:
                    urls.add(url)
        
        except Exception as e:
            logger.debug(f"Failed to parse sitemap {sitemap_url}: {e}")
        
        return urls
    
    async def _discover_wordpress(
        self,
        base_url: str,
        client: httpx.AsyncClient,
    ) -> set[str]:
        """Discover WordPress endpoints."""
        urls = set()
        
        # Try wp-json API
        try:
            wp_json_url = base_url.rstrip('/') + '/wp-json'
            response = await client.get(wp_json_url, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract routes from API index
                if 'routes' in data:
                    for route in data['routes'].keys():
                        urls.add(base_url.rstrip('/') + route)
                
                # Add common WordPress endpoints
                for path in self.wordpress_paths:
                    urls.add(base_url.rstrip('/') + path)
        
        except Exception as e:
            logger.debug(f"WordPress discovery failed: {e}")
        
        return urls
    
    async def _parse_homepage(
        self,
        base_url: str,
        client: httpx.AsyncClient,
    ) -> set[str]:
        """Parse homepage for links and meta tags."""
        urls = set()
        
        try:
            response = await client.get(base_url, timeout=10.0)
            
            if response.status_code != 200:
                return urls
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract all links
            for tag in soup.find_all(['a', 'link']):
                href = tag.get('href')
                if href:
                    absolute_url = urljoin(base_url, href)
                    # Only same-origin
                    if urlparse(absolute_url).netloc == urlparse(base_url).netloc:
                        urls.add(absolute_url)
            
            # Extract RSS/Atom feeds
            for link in soup.find_all('link', type=['application/rss+xml', 'application/atom+xml']):
                href = link.get('href')
                if href:
                    urls.add(urljoin(base_url, href))
        
        except Exception as e:
            logger.debug(f"Failed to parse homepage: {e}")
        
        return urls
