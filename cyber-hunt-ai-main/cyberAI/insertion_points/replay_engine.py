"""
Replay engine - replays HTTP requests with modified payloads for testing.
Handles proper encoding layer application and request reconstruction.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from loguru import logger

from .canonicalizer import CanonicalRequest, NodeType
from .extractor import InsertionPoint
from .payload_encoder import PayloadEncoder


@dataclass
class ReplayRequest:
    """Represents a request ready for replay."""
    method: str
    url: str
    headers: dict[str, str]
    body: Optional[str | bytes]
    insertion_point: InsertionPoint
    payload_value: Any
    test_name: str


@dataclass
class ReplayResult:
    """Result of a replay attempt."""
    request: ReplayRequest
    success: bool
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    response_time_ms: Optional[float] = None


class ReplayEngine:
    """
    Replays HTTP requests with modified insertion point values.
    Properly applies encoding layers to maintain request validity.
    """
    
    def __init__(self):
        """Initialize replay engine."""
        self.encoder = PayloadEncoder()
        self.replays_generated = 0
    
    def build_replay_request(
        self,
        canonical: CanonicalRequest,
        insertion_point: InsertionPoint,
        payload_value: Any,
        test_name: str = "test",
    ) -> ReplayRequest:
        """
        Build a replay request with a modified insertion point value.
        
        Args:
            canonical: Original canonical request
            insertion_point: Insertion point to modify
            payload_value: New value for the insertion point
            test_name: Name of the test
        
        Returns:
            ReplayRequest ready to send
        """
        self.replays_generated += 1
        
        # Encode the payload with proper layers
        encoded_payload = self.encoder.encode(
            payload_value,
            insertion_point.encoding_layers,
        )
        
        # Reconstruct the request based on insertion point location
        location = insertion_point.location
        
        if location.startswith("query."):
            # Query parameter
            url = self._modify_query_param(
                canonical.raw_url,
                location[6:],  # Remove "query." prefix
                encoded_payload,
            )
            return ReplayRequest(
                method=canonical.method,
                url=url,
                headers=dict(canonical.headers),
                body=self._reconstruct_body(canonical),
                insertion_point=insertion_point,
                payload_value=payload_value,
                test_name=test_name,
            )
        
        elif location.startswith("header."):
            # Header
            headers = dict(canonical.headers)
            header_name = location[7:]  # Remove "header." prefix
            headers[header_name] = str(encoded_payload)
            return ReplayRequest(
                method=canonical.method,
                url=canonical.raw_url,
                headers=headers,
                body=self._reconstruct_body(canonical),
                insertion_point=insertion_point,
                payload_value=payload_value,
                test_name=test_name,
            )
        
        elif location.startswith("body."):
            # Body field
            body = self._modify_body_field(
                canonical,
                location[5:],  # Remove "body." prefix
                encoded_payload,
            )
            return ReplayRequest(
                method=canonical.method,
                url=canonical.raw_url,
                headers=dict(canonical.headers),
                body=body,
                insertion_point=insertion_point,
                payload_value=payload_value,
                test_name=test_name,
            )
        
        elif location.startswith("path_segment_"):
            # Path segment
            url = self._modify_path_segment(
                canonical.raw_url,
                location,
                encoded_payload,
            )
            return ReplayRequest(
                method=canonical.method,
                url=url,
                headers=dict(canonical.headers),
                body=self._reconstruct_body(canonical),
                insertion_point=insertion_point,
                payload_value=payload_value,
                test_name=test_name,
            )
        
        else:
            logger.warning(f"Unknown insertion point location: {location}")
            return ReplayRequest(
                method=canonical.method,
                url=canonical.raw_url,
                headers=dict(canonical.headers),
                body=self._reconstruct_body(canonical),
                insertion_point=insertion_point,
                payload_value=payload_value,
                test_name=test_name,
            )
    
    def _modify_query_param(
        self,
        url: str,
        param_name: str,
        new_value: Any,
    ) -> str:
        """Modify a query parameter in a URL."""
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        
        # Update the parameter
        params[param_name] = [str(new_value)]
        
        # Rebuild query string
        new_query = urlencode(params, doseq=True)
        
        # Rebuild URL
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))
    
    def _modify_path_segment(
        self,
        url: str,
        location: str,
        new_value: Any,
    ) -> str:
        """Modify a path segment in a URL."""
        parsed = urlparse(url)
        path_parts = parsed.path.split('/')
        
        # Extract segment index from location (e.g., "path_segment_3" -> 3)
        try:
            segment_idx = int(location.split('_')[-1])
            if 0 <= segment_idx < len(path_parts):
                path_parts[segment_idx] = str(new_value)
        except (ValueError, IndexError):
            logger.warning(f"Invalid path segment location: {location}")
        
        new_path = '/'.join(path_parts)
        
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            new_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))
    
    def _modify_body_field(
        self,
        canonical: CanonicalRequest,
        field_path: str,
        new_value: Any,
    ) -> str | bytes:
        """Modify a field in the request body."""
        if not canonical.body_ast:
            return None
        
        # Parse the field path (e.g., "user.id" -> ["user", "id"])
        path_parts = field_path.split('.')
        
        # Reconstruct body based on content type
        if canonical.content_type and 'json' in canonical.content_type.lower():
            return self._modify_json_body(canonical, path_parts, new_value)
        elif canonical.content_type and 'form' in canonical.content_type.lower():
            return self._modify_form_body(canonical, path_parts, new_value)
        else:
            # Unknown content type, return original
            logger.warning(f"Cannot modify body with content type: {canonical.content_type}")
            return self._reconstruct_body(canonical)
    
    def _modify_json_body(
        self,
        canonical: CanonicalRequest,
        path_parts: list[str],
        new_value: Any,
    ) -> str:
        """Modify a JSON body field."""
        # Reconstruct the original JSON structure
        body_dict = self._ast_to_dict(canonical.body_ast)
        
        # Navigate to the field and modify it
        current = body_dict
        for i, part in enumerate(path_parts[:-1]):
            if part in current:
                current = current[part]
            else:
                logger.warning(f"Path not found in body: {'.'.join(path_parts)}")
                return json.dumps(body_dict)
        
        # Set the new value
        if path_parts[-1] in current:
            current[path_parts[-1]] = new_value
        
        return json.dumps(body_dict)
    
    def _modify_form_body(
        self,
        canonical: CanonicalRequest,
        path_parts: list[str],
        new_value: Any,
    ) -> str:
        """Modify a form-encoded body field."""
        # Reconstruct the original form data
        body_dict = self._ast_to_dict(canonical.body_ast)
        
        # Modify the field
        field_name = path_parts[0]  # Form fields are flat
        if field_name in body_dict:
            body_dict[field_name] = str(new_value)
        
        return urlencode(body_dict)
    
    def _ast_to_dict(self, node) -> dict:
        """Convert AST node back to dictionary."""
        if node.node_type == NodeType.OBJECT:
            result = {}
            for key, child in node.children.items():
                if child.node_type in (NodeType.OBJECT, NodeType.ARRAY):
                    result[key] = self._ast_to_dict(child)
                else:
                    result[key] = child.value
            return result
        elif node.node_type == NodeType.ARRAY:
            return [self._ast_to_dict(child) for child in node.children.values()]
        else:
            return node.value
    
    def _reconstruct_body(self, canonical: CanonicalRequest) -> Optional[str | bytes]:
        """Reconstruct the original request body."""
        if not canonical.body_ast:
            return None
        
        if canonical.content_type and 'json' in canonical.content_type.lower():
            body_dict = self._ast_to_dict(canonical.body_ast)
            return json.dumps(body_dict)
        elif canonical.content_type and 'form' in canonical.content_type.lower():
            body_dict = self._ast_to_dict(canonical.body_ast)
            return urlencode(body_dict)
        else:
            # Return as-is
            return str(canonical.body_ast.value) if canonical.body_ast.value else None
    
    def get_stats(self) -> dict:
        """Get replay statistics."""
        return {
            "replays_generated": self.replays_generated,
            "encoder_stats": self.encoder.get_stats(),
        }
