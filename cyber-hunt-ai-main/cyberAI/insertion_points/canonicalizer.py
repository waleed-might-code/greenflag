"""
Request canonicalizer - converts HTTP requests into typed AST for insertion point extraction.
Handles JSON, XML, form-data, and nested encodings (base64, URL-encode, JSON-in-JSON).
"""

import base64
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree as ET

from loguru import logger


class NodeType(Enum):
    """Types of AST nodes."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    NULL = "null"
    ARRAY = "array"
    OBJECT = "object"
    BINARY = "binary"
    UUID = "uuid"
    TOKEN = "token"
    EMAIL = "email"
    URL = "url"


@dataclass
class ASTNode:
    """Node in the canonical request AST."""
    node_type: NodeType
    value: Any
    placeholder: str
    path: str  # JSON path or XPath-style location
    encoding_layers: list[str] = field(default_factory=list)
    children: dict[str, 'ASTNode'] = field(default_factory=dict)
    
    def is_leaf(self) -> bool:
        return len(self.children) == 0


@dataclass
class CanonicalRequest:
    """Canonical representation of an HTTP request."""
    request_id: str
    method: str
    url_template: str  # Path with placeholders like /api/users/{id}
    host: str
    path_segments: list[ASTNode]
    query_params: dict[str, ASTNode]
    headers: dict[str, ASTNode]
    body_ast: Optional[ASTNode]
    content_type: Optional[str]
    raw_url: str
    
    def get_all_insertion_points(self) -> list[tuple[str, ASTNode]]:
        """Get all insertion points (location, node) from the request."""
        points = []
        
        # Path segments
        for i, node in enumerate(self.path_segments):
            points.append((f"path_segment_{i}", node))
        
        # Query params
        for key, node in self.query_params.items():
            points.append((f"query.{key}", node))
        
        # Headers (only variable ones)
        for key, node in self.headers.items():
            if self._is_variable_header(key):
                points.append((f"header.{key}", node))
        
        # Body
        if self.body_ast:
            points.extend(self._extract_body_points(self.body_ast, "body"))
        
        return points
    
    def _is_variable_header(self, key: str) -> bool:
        """Check if header is likely user-controllable."""
        variable_headers = {
            "authorization", "x-auth-token", "x-api-key", "x-user-id",
            "x-role", "x-tenant-id", "cookie", "x-csrf-token"
        }
        return key.lower() in variable_headers
    
    def _extract_body_points(self, node: ASTNode, prefix: str) -> list[tuple[str, ASTNode]]:
        """Recursively extract insertion points from body AST."""
        points = []
        
        if node.is_leaf():
            points.append((prefix, node))
        else:
            for key, child in node.children.items():
                child_prefix = f"{prefix}.{key}"
                points.extend(self._extract_body_points(child, child_prefix))
        
        return points


class RequestCanonicalizer:
    """
    Converts HTTP requests into canonical AST representation.
    Supports nested encoding detection and recursive parsing.
    """
    
    # Patterns for type inference
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    URL_PATTERN = re.compile(r'^https?://')
    TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9_-]{20,}$')  # JWT-like tokens
    
    def __init__(self, max_encoding_depth: int = 3):
        """
        Initialize canonicalizer.
        
        Args:
            max_encoding_depth: Maximum depth for nested encoding detection
        """
        self.max_encoding_depth = max_encoding_depth
    
    def canonicalize(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Optional[bytes] = None,
        request_id: Optional[str] = None,
    ) -> CanonicalRequest:
        """
        Canonicalize an HTTP request.
        
        Args:
            method: HTTP method
            url: Full URL
            headers: Request headers
            body: Request body (bytes)
            request_id: Optional request ID
        
        Returns:
            CanonicalRequest with AST
        """
        parsed = urlparse(url)
        
        # Parse path segments
        path_segments = self._parse_path(parsed.path)
        url_template = self._create_url_template(parsed.path, path_segments)
        
        # Parse query params
        query_params = self._parse_query(parsed.query)
        
        # Parse headers
        header_nodes = self._parse_headers(headers)
        
        # Parse body
        content_type = headers.get("Content-Type", "").split(";")[0].strip()
        body_ast = self._parse_body(body, content_type) if body else None
        
        return CanonicalRequest(
            request_id=request_id or f"{method}_{parsed.path}",
            method=method.upper(),
            url_template=url_template,
            host=parsed.netloc,
            path_segments=path_segments,
            query_params=query_params,
            headers=header_nodes,
            body_ast=body_ast,
            content_type=content_type,
            raw_url=url,
        )
    
    def _parse_path(self, path: str) -> list[ASTNode]:
        """Parse URL path into segments with type inference."""
        segments = [s for s in path.split("/") if s]
        nodes = []
        
        for i, segment in enumerate(segments):
            decoded = unquote(segment)
            node_type, placeholder = self._infer_type(decoded)
            
            node = ASTNode(
                node_type=node_type,
                value=decoded,
                placeholder=placeholder,
                path=f"path[{i}]",
            )
            nodes.append(node)
        
        return nodes
    
    def _create_url_template(self, path: str, segments: list[ASTNode]) -> str:
        """Create URL template with placeholders."""
        parts = path.split("/")
        template_parts = []
        
        seg_idx = 0
        for part in parts:
            if not part:
                template_parts.append("")
            else:
                if seg_idx < len(segments):
                    node = segments[seg_idx]
                    if node.node_type in (NodeType.INTEGER, NodeType.UUID):
                        template_parts.append(f"{{{node.placeholder}}}")
                    else:
                        template_parts.append(part)
                    seg_idx += 1
                else:
                    template_parts.append(part)
        
        return "/".join(template_parts)
    
    def _parse_query(self, query: str) -> dict[str, ASTNode]:
        """Parse query string into AST nodes."""
        if not query:
            return {}
        
        params = parse_qs(query, keep_blank_values=True)
        nodes = {}
        
        for key, values in params.items():
            # Take first value (most common case)
            value = values[0] if values else ""
            node_type, placeholder = self._infer_type(value)
            
            nodes[key] = ASTNode(
                node_type=node_type,
                value=value,
                placeholder=placeholder,
                path=f"query.{key}",
            )
        
        return nodes
    
    def _parse_headers(self, headers: dict[str, str]) -> dict[str, ASTNode]:
        """Parse headers into AST nodes."""
        nodes = {}
        
        for key, value in headers.items():
            node_type, placeholder = self._infer_type(value)
            
            nodes[key] = ASTNode(
                node_type=node_type,
                value=value,
                placeholder=placeholder,
                path=f"header.{key}",
            )
        
        return nodes
    
    def _parse_body(self, body: bytes, content_type: str) -> Optional[ASTNode]:
        """Parse request body based on content type."""
        if not body:
            return None
        
        try:
            body_str = body.decode("utf-8", errors="ignore")
        except Exception:
            return ASTNode(
                node_type=NodeType.BINARY,
                value=body,
                placeholder="<BINARY>",
                path="body",
            )
        
        # JSON
        if "json" in content_type:
            return self._parse_json(body_str, "body")
        
        # Form data
        elif "form-urlencoded" in content_type:
            return self._parse_form(body_str, "body")
        
        # XML
        elif "xml" in content_type:
            return self._parse_xml(body_str, "body")
        
        # Multipart (simplified - just mark as binary for now)
        elif "multipart" in content_type:
            return ASTNode(
                node_type=NodeType.BINARY,
                value=body_str,
                placeholder="<MULTIPART>",
                path="body",
            )
        
        # Unknown - treat as string and try nested detection
        else:
            return self._parse_unknown(body_str, "body")
    
    def _parse_json(self, data: str, path: str, depth: int = 0) -> ASTNode:
        """Parse JSON into AST with nested encoding detection."""
        try:
            obj = json.loads(data)
            return self._json_to_ast(obj, path, depth)
        except json.JSONDecodeError:
            # Not valid JSON, treat as string
            node_type, placeholder = self._infer_type(data)
            return ASTNode(
                node_type=node_type,
                value=data,
                placeholder=placeholder,
                path=path,
            )
    
    def _json_to_ast(self, obj: Any, path: str, depth: int = 0) -> ASTNode:
        """Convert JSON object to AST recursively."""
        if obj is None:
            return ASTNode(NodeType.NULL, None, "<NULL>", path)
        
        elif isinstance(obj, bool):
            return ASTNode(NodeType.BOOLEAN, obj, "<BOOL>", path)
        
        elif isinstance(obj, int):
            return ASTNode(NodeType.INTEGER, obj, "<INT>", path)
        
        elif isinstance(obj, float):
            return ASTNode(NodeType.FLOAT, obj, "<FLOAT>", path)
        
        elif isinstance(obj, str):
            # Check for nested encoding
            if depth < self.max_encoding_depth:
                nested = self._detect_nested_encoding(obj, path, depth)
                if nested:
                    return nested
            
            node_type, placeholder = self._infer_type(obj)
            return ASTNode(node_type, obj, placeholder, path)
        
        elif isinstance(obj, list):
            children = {}
            for i, item in enumerate(obj):
                children[str(i)] = self._json_to_ast(item, f"{path}[{i}]", depth)
            return ASTNode(NodeType.ARRAY, obj, "<ARRAY>", path, children=children)
        
        elif isinstance(obj, dict):
            children = {}
            for key, value in obj.items():
                children[key] = self._json_to_ast(value, f"{path}.{key}", depth)
            return ASTNode(NodeType.OBJECT, obj, "<OBJECT>", path, children=children)
        
        else:
            return ASTNode(NodeType.STRING, str(obj), "<STRING>", path)
    
    def _detect_nested_encoding(self, value: str, path: str, depth: int) -> Optional[ASTNode]:
        """Detect and parse nested encodings (base64, URL-encoded JSON, etc.)."""
        # Try base64
        if self._looks_like_base64(value):
            try:
                decoded = base64.b64decode(value).decode("utf-8", errors="ignore")
                # Try parsing as JSON
                inner_node = self._parse_json(decoded, path, depth + 1)
                inner_node.encoding_layers.insert(0, "base64")
                return inner_node
            except Exception:
                pass
        
        # Try URL-encoded JSON
        if "%7B" in value or "%22" in value:  # { or "
            try:
                decoded = unquote(value)
                inner_node = self._parse_json(decoded, path, depth + 1)
                inner_node.encoding_layers.insert(0, "url_encode")
                return inner_node
            except Exception:
                pass
        
        return None
    
    def _looks_like_base64(self, value: str) -> bool:
        """Check if string looks like base64."""
        if len(value) < 4 or len(value) % 4 != 0:
            return False
        return bool(re.match(r'^[A-Za-z0-9+/]+=*$', value))
    
    def _parse_form(self, data: str, path: str) -> ASTNode:
        """Parse form-urlencoded data."""
        params = parse_qs(data, keep_blank_values=True)
        children = {}
        
        for key, values in params.items():
            value = values[0] if values else ""
            node_type, placeholder = self._infer_type(value)
            children[key] = ASTNode(node_type, value, placeholder, f"{path}.{key}")
        
        return ASTNode(NodeType.OBJECT, data, "<FORM>", path, children=children)
    
    def _parse_xml(self, data: str, path: str) -> ASTNode:
        """Parse XML into AST (simplified)."""
        try:
            root = ET.fromstring(data)
            return self._xml_to_ast(root, path)
        except ET.ParseError:
            return ASTNode(NodeType.STRING, data, "<XML>", path)
    
    def _xml_to_ast(self, element: ET.Element, path: str) -> ASTNode:
        """Convert XML element to AST."""
        children = {}
        
        # Attributes
        for key, value in element.attrib.items():
            node_type, placeholder = self._infer_type(value)
            children[f"@{key}"] = ASTNode(node_type, value, placeholder, f"{path}@{key}")
        
        # Child elements
        for child in element:
            child_path = f"{path}.{child.tag}"
            children[child.tag] = self._xml_to_ast(child, child_path)
        
        # Text content
        if element.text and element.text.strip():
            node_type, placeholder = self._infer_type(element.text)
            children["_text"] = ASTNode(node_type, element.text, placeholder, f"{path}._text")
        
        return ASTNode(NodeType.OBJECT, element, "<XML>", path, children=children)
    
    def _parse_unknown(self, data: str, path: str) -> ASTNode:
        """Parse unknown content type."""
        # Try JSON first
        try:
            return self._parse_json(data, path)
        except Exception:
            pass
        
        # Treat as string
        node_type, placeholder = self._infer_type(data)
        return ASTNode(node_type, data, placeholder, path)
    
    def _infer_type(self, value: str) -> tuple[NodeType, str]:
        """Infer type of a string value."""
        if not value:
            return NodeType.STRING, "<STRING>"
        
        # UUID
        if self.UUID_PATTERN.match(value):
            return NodeType.UUID, "<UUID>"
        
        # Email
        if self.EMAIL_PATTERN.match(value):
            return NodeType.EMAIL, "<EMAIL>"
        
        # URL
        if self.URL_PATTERN.match(value):
            return NodeType.URL, "<URL>"
        
        # Token (JWT-like)
        if self.TOKEN_PATTERN.match(value):
            return NodeType.TOKEN, "<TOKEN>"
        
        # Integer
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            return NodeType.INTEGER, "<INT>"
        
        # Float
        try:
            float(value)
            return NodeType.FLOAT, "<FLOAT>"
        except ValueError:
            pass
        
        # Boolean
        if value.lower() in ("true", "false"):
            return NodeType.BOOLEAN, "<BOOL>"
        
        # Default to string
        return NodeType.STRING, "<STRING>"
