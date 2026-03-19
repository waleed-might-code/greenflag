"""
API Discovery Module - Discovers APIs from specs and traffic.
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger


@dataclass
class APIEndpoint:
    """Discovered API endpoint."""
    method: str
    path: str
    parameters: list[dict]
    description: Optional[str] = None
    auth_required: bool = False
    source: str = "unknown"


class APIDiscovery:
    """
    Discovers APIs from multiple sources:
    - OpenAPI/Swagger specs
    - GraphQL introspection
    - Common API paths
    - Traffic analysis
    """
    
    def __init__(self):
        """Initialize API discovery."""
        # Common API spec paths
        self.spec_paths = [
            "/openapi.json",
            "/swagger.json",
            "/api-docs",
            "/api/swagger.json",
            "/api/openapi.json",
            "/v1/swagger.json",
            "/v2/swagger.json",
            "/docs/swagger.json",
            "/.well-known/openapi.json",
        ]
        
        # Common GraphQL paths
        self.graphql_paths = [
            "/graphql",
            "/api/graphql",
            "/v1/graphql",
            "/query",
        ]
        
        # Common REST API patterns
        self.api_patterns = [
            r"/api/v\d+/",
            r"/rest/v\d+/",
            r"/v\d+/api/",
        ]
    
    async def discover_from_base_url(
        self,
        base_url: str,
        client: httpx.AsyncClient,
    ) -> list[APIEndpoint]:
        """
        Discover APIs from a base URL.
        
        Args:
            base_url: Base URL to scan
            client: HTTP client
            
        Returns:
            List of discovered API endpoints
        """
        endpoints = []
        
        # Try OpenAPI/Swagger specs
        for spec_path in self.spec_paths:
            url = base_url.rstrip('/') + spec_path
            spec_endpoints = await self._try_openapi_spec(url, client)
            if spec_endpoints:
                logger.info(f"Discovered {len(spec_endpoints)} endpoints from {spec_path}")
                endpoints.extend(spec_endpoints)
                break  # Found a spec, no need to try others
        
        # Try GraphQL introspection
        for graphql_path in self.graphql_paths:
            url = base_url.rstrip('/') + graphql_path
            graphql_endpoints = await self._try_graphql_introspection(url, client)
            if graphql_endpoints:
                logger.info(f"Discovered GraphQL schema at {graphql_path}")
                endpoints.extend(graphql_endpoints)
        
        return endpoints
    
    async def _try_openapi_spec(
        self,
        url: str,
        client: httpx.AsyncClient,
    ) -> list[APIEndpoint]:
        """Try to fetch and parse OpenAPI spec."""
        try:
            response = await client.get(url, timeout=10.0)
            if response.status_code != 200:
                return []
            
            spec = response.json()
            return self._parse_openapi_spec(spec, url)
        
        except Exception as e:
            logger.debug(f"Failed to fetch OpenAPI spec from {url}: {e}")
            return []
    
    def _parse_openapi_spec(self, spec: dict, source: str) -> list[APIEndpoint]:
        """Parse OpenAPI/Swagger spec."""
        endpoints = []
        
        # OpenAPI 3.x
        if "openapi" in spec and "paths" in spec:
            for path, methods in spec["paths"].items():
                for method, details in methods.items():
                    if method.upper() in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                        endpoint = APIEndpoint(
                            method=method.upper(),
                            path=path,
                            parameters=self._extract_parameters(details),
                            description=details.get("summary") or details.get("description"),
                            auth_required=self._check_auth_required(details),
                            source=f"openapi:{source}",
                        )
                        endpoints.append(endpoint)
        
        # Swagger 2.0
        elif "swagger" in spec and "paths" in spec:
            for path, methods in spec["paths"].items():
                for method, details in methods.items():
                    if method.upper() in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                        endpoint = APIEndpoint(
                            method=method.upper(),
                            path=path,
                            parameters=self._extract_parameters(details),
                            description=details.get("summary") or details.get("description"),
                            auth_required=self._check_auth_required(details),
                            source=f"swagger:{source}",
                        )
                        endpoints.append(endpoint)
        
        return endpoints
    
    def _extract_parameters(self, details: dict) -> list[dict]:
        """Extract parameters from OpenAPI operation."""
        params = []
        
        for param in details.get("parameters", []):
            params.append({
                "name": param.get("name"),
                "in": param.get("in"),  # query, path, header, cookie
                "required": param.get("required", False),
                "type": param.get("type") or param.get("schema", {}).get("type"),
            })
        
        # Request body parameters
        if "requestBody" in details:
            content = details["requestBody"].get("content", {})
            for content_type, schema_info in content.items():
                if "schema" in schema_info:
                    params.append({
                        "name": "body",
                        "in": "body",
                        "required": details["requestBody"].get("required", False),
                        "type": content_type,
                        "schema": schema_info["schema"],
                    })
        
        return params
    
    def _check_auth_required(self, details: dict) -> bool:
        """Check if endpoint requires authentication."""
        # Check for security requirements
        if "security" in details and details["security"]:
            return True
        
        # Check for auth-related parameters
        for param in details.get("parameters", []):
            name = param.get("name", "").lower()
            if any(keyword in name for keyword in ["auth", "token", "key", "bearer"]):
                return True
        
        return False
    
    async def _try_graphql_introspection(
        self,
        url: str,
        client: httpx.AsyncClient,
    ) -> list[APIEndpoint]:
        """Try GraphQL introspection query."""
        introspection_query = """
        {
          __schema {
            queryType { name }
            mutationType { name }
            types {
              name
              kind
              fields {
                name
                args {
                  name
                  type { name kind }
                }
              }
            }
          }
        }
        """
        
        try:
            response = await client.post(
                url,
                json={"query": introspection_query},
                timeout=10.0,
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            if "data" not in data or "__schema" not in data["data"]:
                return []
            
            return self._parse_graphql_schema(data["data"]["__schema"], url)
        
        except Exception as e:
            logger.debug(f"Failed GraphQL introspection at {url}: {e}")
            return []
    
    def _parse_graphql_schema(self, schema: dict, source: str) -> list[APIEndpoint]:
        """Parse GraphQL schema from introspection."""
        endpoints = []
        
        # Extract queries
        query_type = schema.get("queryType", {}).get("name")
        mutation_type = schema.get("mutationType", {}).get("name")
        
        for type_info in schema.get("types", []):
            type_name = type_info.get("name")
            
            # Skip internal types
            if type_name.startswith("__"):
                continue
            
            # Process queries
            if type_name == query_type:
                for field in type_info.get("fields", []):
                    endpoint = APIEndpoint(
                        method="POST",
                        path=f"/graphql?query={field['name']}",
                        parameters=[
                            {"name": arg["name"], "type": arg.get("type", {}).get("name")}
                            for arg in field.get("args", [])
                        ],
                        description=f"GraphQL query: {field['name']}",
                        source=f"graphql:{source}",
                    )
                    endpoints.append(endpoint)
            
            # Process mutations
            elif type_name == mutation_type:
                for field in type_info.get("fields", []):
                    endpoint = APIEndpoint(
                        method="POST",
                        path=f"/graphql?mutation={field['name']}",
                        parameters=[
                            {"name": arg["name"], "type": arg.get("type", {}).get("name")}
                            for arg in field.get("args", [])
                        ],
                        description=f"GraphQL mutation: {field['name']}",
                        auth_required=True,  # Mutations typically require auth
                        source=f"graphql:{source}",
                    )
                    endpoints.append(endpoint)
        
        return endpoints
    
    def discover_from_traffic(self, requests: list[dict]) -> list[APIEndpoint]:
        """
        Discover API patterns from observed traffic.
        
        Args:
            requests: List of request dictionaries with method, url, headers
            
        Returns:
            List of discovered API endpoints
        """
        endpoints = []
        seen_patterns = set()
        
        for req in requests:
            url = req.get("url", "")
            method = req.get("method", "GET")
            
            # Check if URL matches API patterns
            for pattern in self.api_patterns:
                if re.search(pattern, url):
                    # Extract path template
                    path = self._extract_path_template(url)
                    
                    # Avoid duplicates
                    key = f"{method}:{path}"
                    if key in seen_patterns:
                        continue
                    
                    seen_patterns.add(key)
                    
                    endpoint = APIEndpoint(
                        method=method,
                        path=path,
                        parameters=[],
                        description=f"Discovered from traffic",
                        source="traffic",
                    )
                    endpoints.append(endpoint)
        
        return endpoints
    
    def _extract_path_template(self, url: str) -> str:
        """Extract path template from URL."""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path = parsed.path
        
        # Replace numeric IDs with {id}
        path = re.sub(r'/\d+', '/{id}', path)
        
        # Replace UUIDs with {uuid}
        path = re.sub(
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '/{uuid}',
            path,
            flags=re.IGNORECASE
        )
        
        return path
