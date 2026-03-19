"""
JavaScript Bundle Analyzer - Extracts API endpoints from JS files.
"""

import re
from typing import Optional

import httpx
from loguru import logger


class JSBundleAnalyzer:
    """
    Analyzes JavaScript bundles to extract API endpoints.
    
    Finds:
    - API endpoint strings
    - GraphQL queries
    - WebSocket URLs
    - Hardcoded secrets (for reporting)
    """
    
    def __init__(self):
        """Initialize JS analyzer."""
        # Patterns for API endpoints
        self.api_patterns = [
            r'["\']/(api|rest|graphql|v\d+)/[^"\']+["\']',
            r'["\']https?://[^"\']+/api[^"\']*["\']',
            r'fetch\(["\']([^"\']+)["\']',
            r'axios\.[a-z]+\(["\']([^"\']+)["\']',
            r'\.get\(["\']([^"\']+)["\']',
            r'\.post\(["\']([^"\']+)["\']',
        ]
        
        # Patterns for GraphQL
        self.graphql_patterns = [
            r'query\s+\w+\s*\{[^}]+\}',
            r'mutation\s+\w+\s*\{[^}]+\}',
        ]
        
        # Patterns for secrets (for reporting, not exploitation)
        self.secret_patterns = [
            r'api[_-]?key["\']?\s*[:=]\s*["\']([^"\']{20,})["\']',
            r'secret["\']?\s*[:=]\s*["\']([^"\']{20,})["\']',
            r'token["\']?\s*[:=]\s*["\']([^"\']{20,})["\']',
        ]
    
    async def analyze_js_bundle(
        self,
        js_url: str,
        client: httpx.AsyncClient,
    ) -> dict:
        """
        Analyze a JavaScript bundle.
        
        Args:
            js_url: URL of JS file
            client: HTTP client
            
        Returns:
            Dictionary with extracted data
        """
        try:
            response = await client.get(js_url, timeout=30.0)
            
            if response.status_code != 200:
                return {}
            
            js_content = response.text
            
            # Extract API endpoints
            endpoints = self._extract_endpoints(js_content)
            
            # Extract GraphQL queries
            graphql_queries = self._extract_graphql(js_content)
            
            # Check for secrets (for reporting)
            has_secrets = self._check_for_secrets(js_content)
            
            logger.info(
                f"Analyzed {js_url}: "
                f"{len(endpoints)} endpoints, "
                f"{len(graphql_queries)} GraphQL queries"
            )
            
            return {
                "url": js_url,
                "endpoints": endpoints,
                "graphql_queries": graphql_queries,
                "has_potential_secrets": has_secrets,
            }
        
        except Exception as e:
            logger.debug(f"Failed to analyze JS bundle {js_url}: {e}")
            return {}
    
    def _extract_endpoints(self, js_content: str) -> list[str]:
        """Extract API endpoints from JS content."""
        endpoints = set()
        
        for pattern in self.api_patterns:
            matches = re.findall(pattern, js_content, re.IGNORECASE)
            for match in matches:
                # Clean up the match
                if isinstance(match, tuple):
                    match = match[0]
                
                endpoint = match.strip('\'"')
                if endpoint and len(endpoint) > 1:
                    endpoints.add(endpoint)
        
        return list(endpoints)
    
    def _extract_graphql(self, js_content: str) -> list[str]:
        """Extract GraphQL queries from JS content."""
        queries = set()
        
        for pattern in self.graphql_patterns:
            matches = re.findall(pattern, js_content, re.DOTALL)
            for match in matches:
                # Truncate long queries
                query = match[:200] if len(match) > 200 else match
                queries.add(query)
        
        return list(queries)
    
    def _check_for_secrets(self, js_content: str) -> bool:
        """Check if JS contains potential secrets."""
        for pattern in self.secret_patterns:
            if re.search(pattern, js_content, re.IGNORECASE):
                return True
        
        return False
    
    async def analyze_page_js(
        self,
        html: str,
        base_url: str,
        client: httpx.AsyncClient,
    ) -> list[dict]:
        """
        Analyze all JS files linked from an HTML page.
        
        Args:
            html: HTML content
            base_url: Base URL for resolving relative paths
            client: HTTP client
            
        Returns:
            List of analysis results
        """
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        
        # Find all script tags with src
        for script in soup.find_all('script', src=True):
            js_url = urljoin(base_url, script['src'])
            
            # Only analyze same-origin scripts
            from urllib.parse import urlparse
            if urlparse(js_url).netloc == urlparse(base_url).netloc:
                result = await self.analyze_js_bundle(js_url, client)
                if result:
                    results.append(result)
        
        return results
