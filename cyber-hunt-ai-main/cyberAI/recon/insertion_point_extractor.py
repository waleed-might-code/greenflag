"""
Insertion Point Extractor - Phase 2 Component
Extracts all user-controllable input points from HTTP requests.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from loguru import logger


class InsertionPointType(Enum):
    """Type of insertion point."""
    URL_PATH_SEGMENT = "url_path_segment"
    QUERY_PARAM = "query_param"
    HEADER = "header"
    BODY_JSON = "body_json"
    BODY_FORM = "body_form"
    BODY_XML = "body_xml"
    BODY_MULTIPART = "body_multipart"
    COOKIE = "cookie"


class EncodingLayer(Enum):
    """Encoding layer applied to a value."""
    NONE = "none"
    BASE64 = "base64"
    URL_ENCODE = "url_encode"
    JSON = "json"
    XML = "xml"


@dataclass
class InsertionPoint:
    """
    Represents a single insertion point in an HTTP request.
    """
    location: str  # e.g., "query.search", "body.user.id", "header.X-User-Id"
    point_type: InsertionPointType
    encoding_layers: list[EncodingLayer] = field(default_factory=list)
    inferred_type: str = "string"  # id, string, token, email, etc.
    sample_value: Optional[str] = None
    is_csrf_token: bool = False
    
    def __hash__(self):
        return hash((self.location, self.point_type))


@dataclass
class CanonicalRequest:
    """
    Canonical representation of an HTTP request with placeholders.
    """
    method: str
    url_template: str  # e.g., "/api/users/{id}"
    query_params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body_ast: Optional[dict] = None
    insertion_points: list[InsertionPoint] = field(default_factory=list)
    shape_hash: Optional[str] = None


class InsertionPointExtractor:
    """
    Extracts insertion points from HTTP requests.
    
    Supports:
    - URL path segments (numeric, UUID, etc.)
    - Query parameters
    - Headers (especially auth-related)
    - JSON body (nested)
    - Form data
    - Cookies
    - Nested encoding (base64, JSON-in-JSON)
    """
    
    def __init__(self, max_nesting_depth: int = 3):
        """
        Initialize extractor.
        
        Args:
            max_nesting_depth: Maximum depth for nested encoding detection
        """
        self.max_nesting_depth = max_nesting_depth
        
        # Patterns for identifying special values
        self._uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )
        self._numeric_pattern = re.compile(r'^\d+$')
        self._email_pattern = re.compile(r'^[^@]+@[^@]+\.[^@]+$')
        self._jwt_pattern = re.compile(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$')
        
        # CSRF/token indicators
        self._csrf_indicators = {'csrf', 'token', 'nonce', '_token', 'authenticity'}
    
    def extract(
        self,
        method: str,
        url: str,
        headers: Optional[dict] = None,
        body: Optional[bytes] = None,
        content_type: Optional[str] = None,
    ) -> CanonicalRequest:
        """
        Extract insertion points from an HTTP request.
        
        Args:
            method: HTTP method
            url: Full URL
            headers: Request headers
            body: Request body
            content_type: Content-Type header
            
        Returns:
            CanonicalRequest with extracted insertion points
        """
        headers = headers or {}
        insertion_points = []
        
        # Parse URL
        parsed = urlparse(url)
        
        # Extract from URL path
        url_template, path_points = self._extract_from_path(parsed.path)
        insertion_points.extend(path_points)
        
        # Extract from query parameters
        query_params, query_points = self._extract_from_query(parsed.query)
        insertion_points.extend(query_points)
        
        # Extract from headers
        header_dict, header_points = self._extract_from_headers(headers)
        insertion_points.extend(header_points)
        
        # Extract from body
        body_ast = None
        if body:
            body_ast, body_points = self._extract_from_body(body, content_type)
            insertion_points.extend(body_points)
        
        # Create canonical request
        canonical = CanonicalRequest(
            method=method,
            url_template=url_template,
            query_params=query_params,
            headers=header_dict,
            body_ast=body_ast,
            insertion_points=insertion_points,
        )
        
        # Compute shape hash
        canonical.shape_hash = self._compute_shape_hash(canonical)
        
        return canonical
    
    def _extract_from_path(self, path: str) -> tuple[str, list[InsertionPoint]]:
        """Extract insertion points from URL path."""
        segments = path.strip('/').split('/')
        template_segments = []
        points = []
        
        for i, segment in enumerate(segments):
            if self._is_variable_segment(segment):
                # Replace with placeholder
                inferred_type = self._infer_type(segment)
                placeholder = f"{{{inferred_type}_{i}}}"
                template_segments.append(placeholder)
                
                # Create insertion point
                point = InsertionPoint(
                    location=f"path_segment_{i}",
                    point_type=InsertionPointType.URL_PATH_SEGMENT,
                    inferred_type=inferred_type,
                    sample_value=segment,
                )
                points.append(point)
            else:
                template_segments.append(segment)
        
        template = '/' + '/'.join(template_segments)
        return template, points
    
    def _extract_from_query(self, query: str) -> tuple[dict, list[InsertionPoint]]:
        """Extract insertion points from query parameters."""
        params = parse_qs(query, keep_blank_values=True)
        canonical_params = {}
        points = []
        
        for key, values in params.items():
            value = values[0] if values else ""
            inferred_type = self._infer_type(value)
            canonical_params[key] = f"<{inferred_type.upper()}>"
            
            # Check for CSRF token
            is_csrf = any(indicator in key.lower() for indicator in self._csrf_indicators)
            
            point = InsertionPoint(
                location=f"query.{key}",
                point_type=InsertionPointType.QUERY_PARAM,
                inferred_type=inferred_type,
                sample_value=value,
                is_csrf_token=is_csrf,
            )
            points.append(point)
        
        return canonical_params, points
    
    def _extract_from_headers(self, headers: dict) -> tuple[dict, list[InsertionPoint]]:
        """Extract insertion points from headers."""
        canonical_headers = {}
        points = []
        
        # Headers that commonly contain user-controllable data
        interesting_headers = {
            'authorization', 'x-api-key', 'x-user-id', 'x-tenant-id',
            'x-session-id', 'x-request-id', 'x-correlation-id',
            'x-forwarded-for', 'x-real-ip', 'referer', 'origin',
        }
        
        for key, value in headers.items():
            key_lower = key.lower()
            
            if key_lower in interesting_headers:
                inferred_type = self._infer_type(value)
                canonical_headers[key] = f"<{inferred_type.upper()}>"
                
                point = InsertionPoint(
                    location=f"header.{key}",
                    point_type=InsertionPointType.HEADER,
                    inferred_type=inferred_type,
                    sample_value=value,
                )
                points.append(point)
            else:
                canonical_headers[key] = value
        
        return canonical_headers, points
    
    def _extract_from_body(
        self,
        body: bytes,
        content_type: Optional[str],
    ) -> tuple[Optional[dict], list[InsertionPoint]]:
        """Extract insertion points from request body."""
        if not body:
            return None, []
        
        content_type = (content_type or "").lower()
        
        # JSON body
        if 'json' in content_type:
            return self._extract_from_json_body(body)
        
        # Form data
        elif 'form-urlencoded' in content_type:
            return self._extract_from_form_body(body)
        
        # Multipart
        elif 'multipart' in content_type:
            return self._extract_from_multipart_body(body)
        
        # Unknown - treat as blob
        else:
            point = InsertionPoint(
                location="body",
                point_type=InsertionPointType.BODY_JSON,
                inferred_type="blob",
                sample_value=body[:100].decode('utf-8', errors='ignore'),
            )
            return None, [point]
    
    def _extract_from_json_body(self, body: bytes) -> tuple[dict, list[InsertionPoint]]:
        """Extract insertion points from JSON body."""
        try:
            data = json.loads(body)
            ast, points = self._walk_json(data, prefix="body")
            return ast, points
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON body")
            return None, []
    
    def _walk_json(
        self,
        data: Any,
        prefix: str,
        depth: int = 0,
    ) -> tuple[Any, list[InsertionPoint]]:
        """Recursively walk JSON structure and extract insertion points."""
        if depth > self.max_nesting_depth:
            return data, []
        
        points = []
        
        if isinstance(data, dict):
            ast = {}
            for key, value in data.items():
                location = f"{prefix}.{key}"
                
                # Check for nested encoding
                if isinstance(value, str) and self._looks_like_base64(value):
                    decoded_points = self._try_decode_nested(value, location)
                    points.extend(decoded_points)
                
                # Recursively walk
                child_ast, child_points = self._walk_json(value, location, depth + 1)
                ast[key] = child_ast
                points.extend(child_points)
                
                # Create insertion point for leaf values
                if not isinstance(value, (dict, list)):
                    inferred_type = self._infer_type(str(value))
                    is_csrf = any(ind in key.lower() for ind in self._csrf_indicators)
                    
                    point = InsertionPoint(
                        location=location,
                        point_type=InsertionPointType.BODY_JSON,
                        inferred_type=inferred_type,
                        sample_value=str(value),
                        is_csrf_token=is_csrf,
                    )
                    points.append(point)
            
            return ast, points
        
        elif isinstance(data, list):
            if data:
                # Process first item as representative
                child_ast, child_points = self._walk_json(data[0], f"{prefix}[0]", depth + 1)
                return [child_ast], child_points
            return [], []
        
        else:
            return data, []
    
    def _extract_from_form_body(self, body: bytes) -> tuple[dict, list[InsertionPoint]]:
        """Extract insertion points from form-urlencoded body."""
        try:
            form_str = body.decode('utf-8')
            params = parse_qs(form_str, keep_blank_values=True)
            
            ast = {}
            points = []
            
            for key, values in params.items():
                value = values[0] if values else ""
                inferred_type = self._infer_type(value)
                ast[key] = f"<{inferred_type.upper()}>"
                
                is_csrf = any(ind in key.lower() for ind in self._csrf_indicators)
                
                point = InsertionPoint(
                    location=f"body.{key}",
                    point_type=InsertionPointType.BODY_FORM,
                    inferred_type=inferred_type,
                    sample_value=value,
                    is_csrf_token=is_csrf,
                )
                points.append(point)
            
            return ast, points
        
        except Exception as e:
            logger.warning(f"Failed to parse form body: {e}")
            return None, []
    
    def _extract_from_multipart_body(self, body: bytes) -> tuple[dict, list[InsertionPoint]]:
        """Extract insertion points from multipart body."""
        # Simplified - full implementation would parse multipart boundaries
        point = InsertionPoint(
            location="body.multipart",
            point_type=InsertionPointType.BODY_MULTIPART,
            inferred_type="multipart",
        )
        return None, [point]
    
    def _is_variable_segment(self, segment: str) -> bool:
        """Check if a path segment looks like a variable."""
        if not segment:
            return False
        
        # Numeric ID
        if self._numeric_pattern.match(segment):
            return True
        
        # UUID
        if self._uuid_pattern.match(segment):
            return True
        
        # Long alphanumeric (likely ID)
        if len(segment) > 16 and segment.isalnum():
            return True
        
        return False
    
    def _infer_type(self, value: str) -> str:
        """Infer the type of a value."""
        if not value:
            return "string"
        
        if self._numeric_pattern.match(value):
            return "id"
        
        if self._uuid_pattern.match(value):
            return "uuid"
        
        if self._email_pattern.match(value):
            return "email"
        
        if self._jwt_pattern.match(value):
            return "jwt"
        
        if len(value) > 32 and value.isalnum():
            return "token"
        
        return "string"
    
    def _looks_like_base64(self, value: str) -> bool:
        """Check if a string looks like base64."""
        if len(value) < 16:
            return False
        
        # Base64 uses A-Z, a-z, 0-9, +, /, =
        if not re.match(r'^[A-Za-z0-9+/]+=*$', value):
            return False
        
        # Length should be multiple of 4
        if len(value) % 4 != 0:
            return False
        
        return True
    
    def _try_decode_nested(self, value: str, location: str) -> list[InsertionPoint]:
        """Try to decode nested encoding and extract insertion points."""
        points = []
        
        try:
            decoded = base64.b64decode(value).decode('utf-8')
            
            # Try to parse as JSON
            try:
                data = json.loads(decoded)
                _, nested_points = self._walk_json(data, f"{location}.base64")
                
                # Mark encoding layer
                for point in nested_points:
                    point.encoding_layers.append(EncodingLayer.BASE64)
                
                points.extend(nested_points)
            except json.JSONDecodeError:
                pass
        
        except Exception:
            pass
        
        return points
    
    def _compute_shape_hash(self, canonical: CanonicalRequest) -> str:
        """Compute a hash representing the shape of the request."""
        import hashlib
        
        shape_str = f"{canonical.method}:{canonical.url_template}"
        shape_str += f":{sorted(canonical.query_params.keys())}"
        
        if canonical.body_ast:
            shape_str += f":{sorted(canonical.body_ast.keys())}"
        
        return hashlib.sha256(shape_str.encode()).hexdigest()[:16]
