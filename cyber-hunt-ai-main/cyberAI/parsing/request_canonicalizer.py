"""
Request Canonicalization Module

Converts HTTP requests into canonical AST representation with placeholders
for variable values, enabling insertion point extraction and deduplication.
"""

import re
import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, quote
import xml.etree.ElementTree as ET


@dataclass
class ParameterNode:
    """Represents a single parameter in the request AST."""
    name: str
    value: Any
    placeholder: str  # e.g., "<INT>", "<UUID>", "<STRING>"
    location: str  # path_segment_N, query, header, body
    parent_path: str = ""  # For nested structures: "body.user.profile.id"


@dataclass
class CanonicalRequest:
    """
    Canonical representation of an HTTP request with placeholders.
    
    This enables:
    - Deduplication of similar requests
    - Insertion point extraction
    - Request shape analysis
    """
    request_id: str
    method: str
    url_template: str  # Path with placeholders: /api/users/{id}/posts/{post_id}
    host: str
    scheme: str
    path_segments: List[ParameterNode]
    query_params: List[ParameterNode]
    headers: List[ParameterNode]
    body_ast: Optional[Dict[str, Any]]  # Parsed body structure
    body_params: List[ParameterNode]
    content_type: Optional[str]
    raw_body: Optional[bytes]
    shape_hash: str  # Hash of the request shape for deduplication
    metadata: Dict[str, Any] = field(default_factory=dict)


class RequestCanonicalizer:
    """
    Parses HTTP requests and produces canonical representations.
    
    Supports:
    - URL path parameterization
    - Query string parsing
    - JSON body parsing with nested structures
    - XML body parsing
    - Form data parsing
    - Multipart form data
    """
    
    # Patterns for detecting parameter types
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    INT_PATTERN = re.compile(r'^\d+$')
    FLOAT_PATTERN = re.compile(r'^\d+\.\d+$')
    BOOL_PATTERN = re.compile(r'^(true|false)$', re.I)
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    
    # Headers to exclude from canonicalization (too variable)
    EXCLUDED_HEADERS = {
        'cookie', 'set-cookie', 'date', 'expires', 'last-modified',
        'etag', 'age', 'x-request-id', 'x-trace-id', 'x-correlation-id'
    }
    
    def __init__(self):
        pass
    
    def canonicalize(self, method: str, url: str, headers: Dict[str, str],
                     body: Optional[bytes] = None) -> CanonicalRequest:
        """
        Convert an HTTP request into canonical form.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL
            headers: Request headers
            body: Request body bytes
        
        Returns:
            CanonicalRequest object
        """
        parsed_url = urlparse(url)
        
        # Parse path segments
        path_segments = self._parse_path(parsed_url.path)
        url_template = self._build_url_template(parsed_url.path, path_segments)
        
        # Parse query parameters
        query_params = self._parse_query(parsed_url.query)
        
        # Parse headers
        header_params = self._parse_headers(headers)
        
        # Parse body
        content_type = headers.get('content-type', '').lower()
        body_ast, body_params = self._parse_body(body, content_type)
        
        # Generate request ID and shape hash
        request_id = self._generate_request_id(method, url, body)
        shape_hash = self._generate_shape_hash(method, url_template, query_params,
                                                header_params, body_params)
        
        return CanonicalRequest(
            request_id=request_id,
            method=method.upper(),
            url_template=url_template,
            host=parsed_url.netloc,
            scheme=parsed_url.scheme,
            path_segments=path_segments,
            query_params=query_params,
            headers=header_params,
            body_ast=body_ast,
            body_params=body_params,
            content_type=content_type,
            raw_body=body,
            shape_hash=shape_hash,
            metadata={
                'original_url': url,
                'has_body': body is not None and len(body) > 0
            }
        )
    
    def _parse_path(self, path: str) -> List[ParameterNode]:
        """Parse URL path into segments with type detection."""
        segments = []
        parts = [p for p in path.split('/') if p]
        
        for i, part in enumerate(parts):
            placeholder = self._infer_type(part)
            segments.append(ParameterNode(
                name=f"segment_{i}",
                value=part,
                placeholder=placeholder,
                location=f"path_segment_{i}"
            ))
        
        return segments
    
    def _build_url_template(self, path: str, segments: List[ParameterNode]) -> str:
        """Build URL template with placeholders."""
        parts = [p for p in path.split('/') if p]
        template_parts = []
        
        for i, (part, segment) in enumerate(zip(parts, segments)):
            if segment.placeholder in ['<INT>', '<UUID>', '<HASH>']:
                template_parts.append(f"{{{segment.name}}}")
            else:
                template_parts.append(part)
        
        return '/' + '/'.join(template_parts) if template_parts else '/'
    
    def _parse_query(self, query_string: str) -> List[ParameterNode]:
        """Parse query string into parameters."""
        if not query_string:
            return []
        
        params = []
        parsed = parse_qs(query_string, keep_blank_values=True)
        
        for name, values in parsed.items():
            for value in values:
                placeholder = self._infer_type(value)
                params.append(ParameterNode(
                    name=name,
                    value=value,
                    placeholder=placeholder,
                    location="query",
                    parent_path=f"query.{name}"
                ))
        
        return params
    
    def _parse_headers(self, headers: Dict[str, str]) -> List[ParameterNode]:
        """Parse headers into parameters."""
        params = []
        
        for name, value in headers.items():
            name_lower = name.lower()
            if name_lower in self.EXCLUDED_HEADERS:
                continue
            
            # Focus on security-relevant headers
            if any(keyword in name_lower for keyword in ['auth', 'token', 'api', 'key', 'user', 'role', 'x-']):
                placeholder = self._infer_type(value)
                params.append(ParameterNode(
                    name=name,
                    value=value,
                    placeholder=placeholder,
                    location="header",
                    parent_path=f"header.{name}"
                ))
        
        return params
    
    def _parse_body(self, body: Optional[bytes], content_type: str) -> Tuple[Optional[Dict], List[ParameterNode]]:
        """Parse request body based on content type."""
        if not body:
            return None, []
        
        try:
            body_str = body.decode('utf-8', errors='ignore')
        except:
            return None, []
        
        # JSON
        if 'json' in content_type:
            return self._parse_json_body(body_str)
        
        # Form data
        elif 'application/x-www-form-urlencoded' in content_type:
            return self._parse_form_body(body_str)
        
        # XML
        elif 'xml' in content_type:
            return self._parse_xml_body(body_str)
        
        # Multipart (simplified - just extract field names)
        elif 'multipart' in content_type:
            return self._parse_multipart_body(body_str)
        
        # Unknown - treat as single blob
        else:
            return None, [ParameterNode(
                name="body",
                value=body_str[:100],  # Truncate
                placeholder="<BLOB>",
                location="body",
                parent_path="body"
            )]
    
    def _parse_json_body(self, body_str: str) -> Tuple[Optional[Dict], List[ParameterNode]]:
        """Parse JSON body and extract parameters."""
        try:
            data = json.loads(body_str)
            params = []
            ast = self._json_to_ast(data, params, "body")
            return ast, params
        except json.JSONDecodeError:
            return None, []
    
    def _json_to_ast(self, data: Any, params: List[ParameterNode], path: str) -> Any:
        """Recursively convert JSON to AST with placeholders."""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                child_path = f"{path}.{key}"
                result[key] = self._json_to_ast(value, params, child_path)
            return result
        
        elif isinstance(data, list):
            result = []
            for i, item in enumerate(data):
                child_path = f"{path}[{i}]"
                result.append(self._json_to_ast(item, params, child_path))
            return result
        
        else:
            # Leaf node - create parameter
            placeholder = self._infer_type(str(data) if data is not None else "")
            params.append(ParameterNode(
                name=path.split('.')[-1],
                value=data,
                placeholder=placeholder,
                location="body",
                parent_path=path
            ))
            return placeholder
    
    def _parse_form_body(self, body_str: str) -> Tuple[Optional[Dict], List[ParameterNode]]:
        """Parse form-encoded body."""
        params = []
        parsed = parse_qs(body_str, keep_blank_values=True)
        ast = {}
        
        for name, values in parsed.items():
            for value in values:
                placeholder = self._infer_type(value)
                params.append(ParameterNode(
                    name=name,
                    value=value,
                    placeholder=placeholder,
                    location="body",
                    parent_path=f"body.{name}"
                ))
                ast[name] = placeholder
        
        return ast, params
    
    def _parse_xml_body(self, body_str: str) -> Tuple[Optional[Dict], List[ParameterNode]]:
        """Parse XML body (simplified)."""
        try:
            root = ET.fromstring(body_str)
            params = []
            ast = self._xml_to_ast(root, params, "body")
            return ast, params
        except ET.ParseError:
            return None, []
    
    def _xml_to_ast(self, element: ET.Element, params: List[ParameterNode], path: str) -> Dict:
        """Convert XML element to AST."""
        result = {'_tag': element.tag}
        
        # Attributes
        for attr_name, attr_value in element.attrib.items():
            placeholder = self._infer_type(attr_value)
            params.append(ParameterNode(
                name=attr_name,
                value=attr_value,
                placeholder=placeholder,
                location="body",
                parent_path=f"{path}.@{attr_name}"
            ))
            result[f"@{attr_name}"] = placeholder
        
        # Text content
        if element.text and element.text.strip():
            placeholder = self._infer_type(element.text.strip())
            params.append(ParameterNode(
                name="text",
                value=element.text.strip(),
                placeholder=placeholder,
                location="body",
                parent_path=f"{path}.text"
            ))
            result['_text'] = placeholder
        
        # Child elements
        for child in element:
            child_path = f"{path}.{child.tag}"
            result[child.tag] = self._xml_to_ast(child, params, child_path)
        
        return result
    
    def _parse_multipart_body(self, body_str: str) -> Tuple[Optional[Dict], List[ParameterNode]]:
        """Parse multipart form data (simplified)."""
        params = []
        # Extract field names from Content-Disposition headers
        pattern = r'Content-Disposition:.*name="([^"]+)"'
        matches = re.findall(pattern, body_str, re.I)
        
        ast = {}
        for field_name in matches:
            params.append(ParameterNode(
                name=field_name,
                value="<MULTIPART_FIELD>",
                placeholder="<MULTIPART>",
                location="body",
                parent_path=f"body.{field_name}"
            ))
            ast[field_name] = "<MULTIPART>"
        
        return ast if ast else None, params
    
    def _infer_type(self, value: str) -> str:
        """Infer the type of a parameter value."""
        if not value:
            return "<EMPTY>"
        
        if self.UUID_PATTERN.match(value):
            return "<UUID>"
        elif self.INT_PATTERN.match(value):
            return "<INT>"
        elif self.FLOAT_PATTERN.match(value):
            return "<FLOAT>"
        elif self.BOOL_PATTERN.match(value):
            return "<BOOL>"
        elif self.EMAIL_PATTERN.match(value):
            return "<EMAIL>"
        elif len(value) == 32 and re.match(r'^[0-9a-f]+$', value, re.I):
            return "<HASH>"
        elif len(value) > 50 and re.match(r'^[A-Za-z0-9+/=]+$', value):
            return "<TOKEN>"
        else:
            return "<STRING>"
    
    def _generate_request_id(self, method: str, url: str, body: Optional[bytes]) -> str:
        """Generate unique request ID."""
        content = f"{method}:{url}".encode('utf-8')
        if body:
            content += body[:1000]  # First 1KB
        return hashlib.sha256(content).hexdigest()[:16]
    
    def _generate_shape_hash(self, method: str, url_template: str,
                            query_params: List[ParameterNode],
                            header_params: List[ParameterNode],
                            body_params: List[ParameterNode]) -> str:
        """Generate hash of request shape for deduplication."""
        shape_parts = [
            method,
            url_template,
            ','.join(sorted([p.name for p in query_params])),
            ','.join(sorted([p.name for p in header_params])),
            ','.join(sorted([p.parent_path for p in body_params]))
        ]
        shape_str = '|'.join(shape_parts)
        return hashlib.sha256(shape_str.encode('utf-8')).hexdigest()[:16]
