"""
Insertion Point Extraction Module

Extracts all user-controllable insertion points from canonical requests,
including nested parameters with multiple encoding layers.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from .request_canonicalizer import CanonicalRequest, ParameterNode
from .encoding_detectors import EncodingDetector, EncodingLayer


@dataclass
class InsertionPoint:
    """
    Represents a single insertion point where payloads can be injected.
    
    Supports nested encoding layers for proper payload generation.
    """
    insertion_id: str  # Unique ID for this insertion point
    request_id: str  # Parent request ID
    location: str  # path_segment_3, query.search, body.user.id, header.X-Role
    parameter_name: str
    original_value: Any
    inferred_type: str  # <INT>, <STRING>, <UUID>, etc.
    encoding_layers: List[str]  # ["json", "base64"] for nested encoding
    parent_path: str  # Full path in request structure
    is_security_relevant: bool  # Auth, ID, role, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_payload_with_encoding(self, payload: str) -> str:
        """
        Apply encoding layers to a payload for injection.
        
        Example: If layers are ["json", "base64"], this will:
        1. JSON encode the payload
        2. Base64 encode the result
        """
        from .encoding_detectors import EncodingDetector
        detector = EncodingDetector()
        return detector.encode_layers(payload, self.encoding_layers)


class InsertionPointExtractor:
    """
    Extracts insertion points from canonical requests.
    
    Features:
    - Detects nested encoding layers
    - Identifies security-relevant parameters
    - Handles CSRF/nonce tokens specially
    - Supports recursive extraction from nested structures
    """
    
    # Security-relevant parameter patterns
    SECURITY_KEYWORDS = {
        'id', 'user', 'admin', 'role', 'auth', 'token', 'key', 'api',
        'session', 'csrf', 'nonce', 'permission', 'access', 'privilege'
    }
    
    # Parameters that should not be fuzzed (need fresh values)
    PROTECTED_KEYWORDS = {'csrf', 'nonce', '_token', 'authenticity'}
    
    def __init__(self, max_encoding_depth: int = 5):
        self.encoding_detector = EncodingDetector(max_depth=max_encoding_depth)
        self.extracted_count = 0
    
    def extract(self, canonical_request: CanonicalRequest) -> List[InsertionPoint]:
        """
        Extract all insertion points from a canonical request.
        
        Returns a list of InsertionPoint objects, including nested ones.
        """
        insertion_points = []
        
        # Extract from path segments
        for param in canonical_request.path_segments:
            ip = self._create_insertion_point(
                canonical_request.request_id,
                param,
                []  # Path segments typically not encoded
            )
            insertion_points.append(ip)
        
        # Extract from query parameters
        for param in canonical_request.query_params:
            # Check for nested encoding
            encoding_layers = self._detect_encoding_layers(param.value)
            ip = self._create_insertion_point(
                canonical_request.request_id,
                param,
                encoding_layers
            )
            insertion_points.append(ip)
        
        # Extract from headers
        for param in canonical_request.headers:
            encoding_layers = self._detect_encoding_layers(param.value)
            ip = self._create_insertion_point(
                canonical_request.request_id,
                param,
                encoding_layers
            )
            insertion_points.append(ip)
        
        # Extract from body parameters
        for param in canonical_request.body_params:
            encoding_layers = self._detect_encoding_layers(param.value)
            ip = self._create_insertion_point(
                canonical_request.request_id,
                param,
                encoding_layers
            )
            insertion_points.append(ip)
        
        # Recursively extract from nested structures in body
        if canonical_request.body_ast:
            nested_points = self._extract_nested_from_ast(
                canonical_request.request_id,
                canonical_request.body_ast,
                "body"
            )
            insertion_points.extend(nested_points)
        
        return insertion_points
    
    def _create_insertion_point(self, request_id: str, param: ParameterNode,
                                encoding_layers: List[str]) -> InsertionPoint:
        """Create an InsertionPoint from a ParameterNode."""
        # Generate unique ID
        insertion_id = self._generate_insertion_id(request_id, param.parent_path)
        
        # Check if security-relevant
        is_security_relevant = self._is_security_relevant(param.name, param.parent_path)
        
        # Check if protected (CSRF/nonce)
        is_protected = self._is_protected(param.name)
        
        return InsertionPoint(
            insertion_id=insertion_id,
            request_id=request_id,
            location=param.location,
            parameter_name=param.name,
            original_value=param.value,
            inferred_type=param.placeholder,
            encoding_layers=encoding_layers,
            parent_path=param.parent_path,
            is_security_relevant=is_security_relevant,
            metadata={
                'is_protected': is_protected,
                'encoding_depth': len(encoding_layers)
            }
        )
    
    def _detect_encoding_layers(self, value: Any) -> List[str]:
        """
        Detect encoding layers in a parameter value.
        
        Returns list of encoding types from outermost to innermost.
        """
        if not isinstance(value, (str, bytes)):
            return []
        
        layers = self.encoding_detector.detect_and_decode(value)
        return [layer.encoding_type for layer in layers]
    
    def _extract_nested_from_ast(self, request_id: str, ast: Any,
                                  path: str) -> List[InsertionPoint]:
        """
        Recursively extract insertion points from nested AST structures.
        
        This handles cases like:
        - JSON objects with nested fields
        - Arrays of objects
        - Deeply nested structures
        """
        insertion_points = []
        
        if isinstance(ast, dict):
            for key, value in ast.items():
                child_path = f"{path}.{key}"
                
                # If value is a placeholder, it's already extracted
                if isinstance(value, str) and value.startswith('<') and value.endswith('>'):
                    continue
                
                # If value is a primitive, create insertion point
                if isinstance(value, (str, int, float, bool)) and not (
                    isinstance(value, str) and value.startswith('<')
                ):
                    encoding_layers = self._detect_encoding_layers(value)
                    
                    param = ParameterNode(
                        name=key,
                        value=value,
                        placeholder=self._infer_type(value),
                        location="body",
                        parent_path=child_path
                    )
                    
                    ip = self._create_insertion_point(request_id, param, encoding_layers)
                    insertion_points.append(ip)
                
                # Recurse into nested structures
                elif isinstance(value, (dict, list)):
                    nested = self._extract_nested_from_ast(request_id, value, child_path)
                    insertion_points.extend(nested)
        
        elif isinstance(ast, list):
            for i, item in enumerate(ast):
                child_path = f"{path}[{i}]"
                nested = self._extract_nested_from_ast(request_id, item, child_path)
                insertion_points.extend(nested)
        
        return insertion_points
    
    def _is_security_relevant(self, param_name: str, path: str) -> bool:
        """Check if parameter is security-relevant."""
        name_lower = param_name.lower()
        path_lower = path.lower()
        
        for keyword in self.SECURITY_KEYWORDS:
            if keyword in name_lower or keyword in path_lower:
                return True
        
        return False
    
    def _is_protected(self, param_name: str) -> bool:
        """Check if parameter is protected (CSRF/nonce)."""
        name_lower = param_name.lower()
        
        for keyword in self.PROTECTED_KEYWORDS:
            if keyword in name_lower:
                return True
        
        return False
    
    def _infer_type(self, value: Any) -> str:
        """Infer type placeholder for a value."""
        if isinstance(value, bool):
            return "<BOOL>"
        elif isinstance(value, int):
            return "<INT>"
        elif isinstance(value, float):
            return "<FLOAT>"
        elif isinstance(value, str):
            if not value:
                return "<EMPTY>"
            # Use canonicalizer's type inference
            from .request_canonicalizer import RequestCanonicalizer
            canonicalizer = RequestCanonicalizer()
            return canonicalizer._infer_type(value)
        else:
            return "<UNKNOWN>"
    
    def _generate_insertion_id(self, request_id: str, path: str) -> str:
        """Generate unique insertion point ID."""
        content = f"{request_id}:{path}".encode('utf-8')
        return hashlib.sha256(content).hexdigest()[:16]
    
    def filter_by_novelty(self, insertion_points: List[InsertionPoint],
                         seen_shapes: Set[str]) -> List[InsertionPoint]:
        """
        Filter insertion points to only novel ones.
        
        Args:
            insertion_points: List of insertion points
            seen_shapes: Set of previously seen shape hashes
        
        Returns:
            List of novel insertion points
        """
        novel_points = []
        
        for ip in insertion_points:
            shape = self._compute_shape(ip)
            if shape not in seen_shapes:
                novel_points.append(ip)
                seen_shapes.add(shape)
        
        return novel_points
    
    def _compute_shape(self, ip: InsertionPoint) -> str:
        """Compute shape hash for an insertion point."""
        shape_parts = [
            ip.location,
            ip.parameter_name,
            ip.inferred_type,
            ','.join(ip.encoding_layers)
        ]
        shape_str = '|'.join(shape_parts)
        return hashlib.sha256(shape_str.encode('utf-8')).hexdigest()[:16]
    
    def group_by_endpoint(self, insertion_points: List[InsertionPoint]) -> Dict[str, List[InsertionPoint]]:
        """Group insertion points by their parent request."""
        groups = {}
        
        for ip in insertion_points:
            if ip.request_id not in groups:
                groups[ip.request_id] = []
            groups[ip.request_id].append(ip)
        
        return groups
    
    def prioritize(self, insertion_points: List[InsertionPoint]) -> List[InsertionPoint]:
        """
        Prioritize insertion points for testing.
        
        Priority factors:
        1. Security-relevant parameters (auth, id, role)
        2. Nested encoding (more layers = higher priority)
        3. Non-protected parameters
        """
        def priority_score(ip: InsertionPoint) -> float:
            score = 0.0
            
            # Security relevance
            if ip.is_security_relevant:
                score += 10.0
            
            # Encoding depth
            score += len(ip.encoding_layers) * 2.0
            
            # Protected parameters get lower priority
            if ip.metadata.get('is_protected'):
                score -= 5.0
            
            # Type-based priority
            if ip.inferred_type in ['<UUID>', '<INT>', '<HASH>']:
                score += 3.0  # IDs are high value
            
            return score
        
        return sorted(insertion_points, key=priority_score, reverse=True)
