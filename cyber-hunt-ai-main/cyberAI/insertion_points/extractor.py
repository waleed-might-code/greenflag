"""
Insertion point extractor - identifies all user-controllable input locations.
Tracks novelty to prioritize testing of new attack surfaces.
Enhanced with nested encoding detection.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from .canonicalizer import ASTNode, CanonicalRequest, NodeType, RequestCanonicalizer
from .encoding_detector import NestedEncodingExtractor


@dataclass
class InsertionPoint:
    """Represents a single insertion point in a request."""
    request_id: str
    location: str  # e.g., "query.id", "body.user.email", "header.X-User-Id"
    node_type: NodeType
    encoding_layers: list[str]
    inferred_type: str  # "id", "string", "token", "email", etc.
    shape_hash: str  # Hash of (method, url_template, location)
    example_value: Optional[str] = None
    is_csrf_token: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "location": self.location,
            "node_type": self.node_type.value,
            "encoding_layers": self.encoding_layers,
            "inferred_type": self.inferred_type,
            "shape_hash": self.shape_hash,
            "example_value": self.example_value,
            "is_csrf_token": self.is_csrf_token,
        }


@dataclass
class NoveltyStats:
    """Statistics about insertion point novelty."""
    total_requests: int = 0
    total_insertion_points: int = 0
    unique_shapes: int = 0
    novel_shapes_found: int = 0
    endpoints_discovered: int = 0


class NoveltyIndex:
    """
    Tracks unique insertion point shapes for novelty detection.
    Uses in-memory set for fast lookups (can be backed by Redis for distributed systems).
    """
    
    def __init__(self):
        """Initialize novelty index."""
        self._shapes: dict[str, dict] = {}  # shape_hash -> metadata
        self._endpoint_shapes: dict[str, set[str]] = {}  # endpoint -> set of shape_hashes
        self.stats = NoveltyStats()
    
    def is_novel(self, shape_hash: str) -> bool:
        """Check if a shape is novel (not seen before)."""
        return shape_hash not in self._shapes
    
    def record_shape(
        self,
        shape_hash: str,
        endpoint: str,
        location: str,
        node_type: str,
    ) -> bool:
        """
        Record a shape in the index.
        
        Returns:
            True if shape was novel, False if already seen
        """
        is_novel = shape_hash not in self._shapes
        
        if is_novel:
            self._shapes[shape_hash] = {
                "endpoint": endpoint,
                "location": location,
                "node_type": node_type,
                "first_seen": None,  # Could add timestamp
            }
            self.stats.novel_shapes_found += 1
            self.stats.unique_shapes += 1
        
        # Track per-endpoint
        if endpoint not in self._endpoint_shapes:
            self._endpoint_shapes[endpoint] = set()
            self.stats.endpoints_discovered += 1
        
        self._endpoint_shapes[endpoint].add(shape_hash)
        
        return is_novel
    
    def get_endpoint_novelty_score(self, endpoint: str) -> float:
        """
        Get novelty score for an endpoint (0.0 to 1.0).
        Higher score = more unique insertion points.
        """
        if endpoint not in self._endpoint_shapes:
            return 1.0  # Completely novel
        
        unique_shapes = len(self._endpoint_shapes[endpoint])
        # Normalize by log scale (endpoints with many shapes are interesting)
        import math
        return min(1.0, math.log(unique_shapes + 1) / math.log(10))
    
    def get_stats(self) -> dict:
        """Get novelty statistics."""
        return {
            "total_requests": self.stats.total_requests,
            "total_insertion_points": self.stats.total_insertion_points,
            "unique_shapes": self.stats.unique_shapes,
            "novel_shapes_found": self.stats.novel_shapes_found,
            "endpoints_discovered": self.stats.endpoints_discovered,
        }
    
    def export_shapes(self) -> dict:
        """Export all shapes for persistence."""
        return {
            "shapes": self._shapes,
            "endpoint_shapes": {k: list(v) for k, v in self._endpoint_shapes.items()},
            "stats": self.get_stats(),
        }
    
    def import_shapes(self, data: dict):
        """Import shapes from persistence."""
        self._shapes = data.get("shapes", {})
        self._endpoint_shapes = {
            k: set(v) for k, v in data.get("endpoint_shapes", {}).items()
        }
        stats_data = data.get("stats", {})
        self.stats = NoveltyStats(**stats_data)


class InsertionPointExtractor:
    """
    Extracts insertion points from canonical requests.
    Identifies CSRF tokens, tracks novelty, and supports nested encodings.
    """
    
    # Patterns for CSRF/nonce detection
    CSRF_KEYWORDS = {"csrf", "xsrf", "token", "nonce", "_token", "authenticity"}
    
    def __init__(self, novelty_index: Optional[NoveltyIndex] = None):
        """
        Initialize extractor.
        
        Args:
            novelty_index: Optional novelty index for tracking unique shapes
        """
        self.canonicalizer = RequestCanonicalizer()
        self.novelty_index = novelty_index or NoveltyIndex()
    
    def extract_from_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Optional[bytes] = None,
        request_id: Optional[str] = None,
    ) -> tuple[CanonicalRequest, list[InsertionPoint]]:
        """
        Extract insertion points from an HTTP request.
        
        Returns:
            Tuple of (canonical_request, insertion_points)
        """
        # Canonicalize request
        canonical = self.canonicalizer.canonicalize(
            method=method,
            url=url,
            headers=headers,
            body=body,
            request_id=request_id,
        )
        
        # Extract insertion points
        insertion_points = []
        all_points = canonical.get_all_insertion_points()
        
        for location, node in all_points:
            # Skip non-variable nodes
            if not self._is_variable_node(node, location):
                continue
            
            # Create insertion point
            ip = self._create_insertion_point(
                canonical=canonical,
                location=location,
                node=node,
            )
            
            insertion_points.append(ip)
        
        # Update stats
        self.novelty_index.stats.total_requests += 1
        self.novelty_index.stats.total_insertion_points += len(insertion_points)
        
        return canonical, insertion_points
    
    def _is_variable_node(self, node: ASTNode, location: str) -> bool:
        """Check if a node represents a variable insertion point."""
        # Skip static-looking values
        if node.node_type == NodeType.NULL:
            return False
        
        # Skip boolean literals (usually not interesting)
        if node.node_type == NodeType.BOOLEAN:
            return False
        
        # Include all other types
        return True
    
    def _create_insertion_point(
        self,
        canonical: CanonicalRequest,
        location: str,
        node: ASTNode,
    ) -> InsertionPoint:
        """Create an insertion point from a node."""
        # Compute shape hash
        shape_hash = self._compute_shape_hash(
            method=canonical.method,
            url_template=canonical.url_template,
            location=location,
        )
        
        # Check if it's a CSRF token
        is_csrf = self._is_csrf_token(location, node)
        
        # Infer type
        inferred_type = self._infer_insertion_type(node)
        
        # Record in novelty index
        endpoint = f"{canonical.method} {canonical.url_template}"
        self.novelty_index.record_shape(
            shape_hash=shape_hash,
            endpoint=endpoint,
            location=location,
            node_type=node.node_type.value,
        )
        
        # Get example value (truncate if too long)
        example_value = str(node.value)[:100] if node.value is not None else None
        
        return InsertionPoint(
            request_id=canonical.request_id,
            location=location,
            node_type=node.node_type,
            encoding_layers=node.encoding_layers,
            inferred_type=inferred_type,
            shape_hash=shape_hash,
            example_value=example_value,
            is_csrf_token=is_csrf,
        )
    
    def _compute_shape_hash(self, method: str, url_template: str, location: str) -> str:
        """Compute hash for insertion point shape."""
        shape_str = f"{method}|{url_template}|{location}"
        return hashlib.sha256(shape_str.encode()).hexdigest()[:16]
    
    def _is_csrf_token(self, location: str, node: ASTNode) -> bool:
        """Check if insertion point looks like a CSRF token."""
        location_lower = location.lower()
        
        # Check location name
        for keyword in self.CSRF_KEYWORDS:
            if keyword in location_lower:
                return True
        
        # Check if it's a token-like value
        if node.node_type == NodeType.TOKEN:
            return True
        
        return False
    
    def _infer_insertion_type(self, node: ASTNode) -> str:
        """Infer semantic type of insertion point."""
        if node.node_type == NodeType.UUID:
            return "id"
        elif node.node_type == NodeType.INTEGER:
            return "id"
        elif node.node_type == NodeType.EMAIL:
            return "email"
        elif node.node_type == NodeType.URL:
            return "url"
        elif node.node_type == NodeType.TOKEN:
            return "token"
        elif node.node_type == NodeType.STRING:
            return "string"
        elif node.node_type == NodeType.ARRAY:
            return "array"
        elif node.node_type == NodeType.OBJECT:
            return "object"
        else:
            return "unknown"
    
    def get_novelty_stats(self) -> dict:
        """Get novelty statistics."""
        stats = self.novelty_index.get_stats()
        if self.nested_extractor:
            stats["nested_encoding"] = self.nested_extractor.get_stats()
        return stats
    
    def export_novelty_index(self, path: str):
        """Export novelty index to file."""
        data = self.novelty_index.export_shapes()
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported novelty index to {path}")
    
    def import_novelty_index(self, path: str):
        """Import novelty index from file."""
        with open(path, "r") as f:
            data = json.load(f)
        self.novelty_index.import_shapes(data)
        logger.info(f"Imported novelty index from {path}")
