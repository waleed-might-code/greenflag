"""
Enhanced priority frontier for intelligent crawling.
Prioritizes URLs/actions based on attack surface value, novelty, and security relevance.
"""

import heapq
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlparse

from loguru import logger


class SourceType(Enum):
    """Source of a frontier item."""
    SEED = "seed"
    SITEMAP = "sitemap"
    LINK = "link"
    FORM = "form"
    API_SPEC = "api_spec"
    GRAPHQL = "graphql"
    XHR = "xhr"
    WEBSOCKET = "websocket"
    REDIRECT = "redirect"


@dataclass
class FeatureVector:
    """Features for priority scoring."""
    # Novelty features
    insertion_point_novelty: float = 0.0  # 0.0 to 1.0
    endpoint_novelty: float = 0.0  # 0.0 to 1.0
    
    # Content type features
    is_api: bool = False
    is_form: bool = False
    is_authenticated: bool = False
    is_admin_path: bool = False
    
    # Depth features
    depth_from_root: int = 0
    depth_from_auth: int = 0
    
    # Security relevance
    has_upload: bool = False
    has_sensitive_params: bool = False
    has_auth_headers: bool = False
    
    # Source quality
    source_type: SourceType = SourceType.LINK
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "insertion_point_novelty": self.insertion_point_novelty,
            "endpoint_novelty": self.endpoint_novelty,
            "is_api": self.is_api,
            "is_form": self.is_form,
            "is_authenticated": self.is_authenticated,
            "is_admin_path": self.is_admin_path,
            "depth_from_root": self.depth_from_root,
            "depth_from_auth": self.depth_from_auth,
            "has_upload": self.has_upload,
            "has_sensitive_params": self.has_sensitive_params,
            "has_auth_headers": self.has_auth_headers,
            "source_type": self.source_type.value,
        }


@dataclass(order=True)
class FrontierItem:
    """Item in the crawl frontier with priority."""
    priority: float = field(compare=True)  # Higher = more important
    url: str = field(compare=False)
    method: str = field(default="GET", compare=False)
    features: FeatureVector = field(default_factory=FeatureVector, compare=False)
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)
    depth: int = field(default=0, compare=False)
    parent_url: Optional[str] = field(default=None, compare=False)
    
    def get_url_hash(self) -> str:
        """Get hash of URL for deduplication."""
        return hashlib.sha256(f"{self.method}:{self.url}".encode()).hexdigest()[:16]


class PriorityFrontier:
    """
    Priority queue for crawl frontier.
    Uses heap for O(log n) insertion and O(1) peek.
    Tracks seen URLs for deduplication.
    """
    
    # Weights for priority scoring
    WEIGHTS = {
        "insertion_point_novelty": 3.0,
        "endpoint_novelty": 2.5,
        "is_api": 2.0,
        "is_form": 1.5,
        "is_authenticated": 1.8,
        "is_admin_path": 2.5,
        "has_upload": 2.0,
        "has_sensitive_params": 1.5,
        "has_auth_headers": 1.3,
        "source_api_spec": 2.0,
        "source_graphql": 1.8,
        "source_xhr": 1.5,
        "depth_penalty": 0.1,  # Penalty per depth level
    }
    
    def __init__(self, max_depth: int = 10, max_items: int = 100000):
        """
        Initialize frontier.
        
        Args:
            max_depth: Maximum crawl depth
            max_items: Maximum items in frontier (prevent memory explosion)
        """
        self._heap: list[FrontierItem] = []
        self._seen: set[str] = set()  # URL hashes
        self._url_to_item: dict[str, FrontierItem] = {}
        self.max_depth = max_depth
        self.max_items = max_items
        
        self.stats = {
            "total_added": 0,
            "total_popped": 0,
            "duplicates_skipped": 0,
            "depth_exceeded": 0,
            "capacity_drops": 0,
        }
    
    def add(self, item: FrontierItem) -> bool:
        """
        Add item to frontier.
        
        Returns:
            True if added, False if duplicate or rejected
        """
        # Check depth
        if item.depth > self.max_depth:
            self.stats["depth_exceeded"] += 1
            return False
        
        # Check for duplicates
        url_hash = item.get_url_hash()
        if url_hash in self._seen:
            self.stats["duplicates_skipped"] += 1
            return False
        
        # Check capacity
        if len(self._heap) >= self.max_items:
            # Drop lowest priority item if new item has higher priority
            if self._heap and item.priority > self._heap[0].priority:
                dropped = heapq.heappop(self._heap)
                dropped_hash = dropped.get_url_hash()
                self._seen.discard(dropped_hash)
                self._url_to_item.pop(dropped_hash, None)
                self.stats["capacity_drops"] += 1
            else:
                return False
        
        # Compute priority if not set
        if item.priority == 0.0:
            item.priority = self._compute_priority(item.features, item.depth)
        
        # Add to heap (negate priority for max-heap behavior)
        heapq.heappush(self._heap, FrontierItem(
            priority=-item.priority,  # Negate for max-heap
            url=item.url,
            method=item.method,
            features=item.features,
            metadata=item.metadata,
            depth=item.depth,
            parent_url=item.parent_url,
        ))
        
        self._seen.add(url_hash)
        self._url_to_item[url_hash] = item
        self.stats["total_added"] += 1
        
        return True
    
    def pop(self) -> Optional[FrontierItem]:
        """Pop highest priority item from frontier."""
        if not self._heap:
            return None
        
        item = heapq.heappop(self._heap)
        # Restore original priority (was negated)
        item.priority = -item.priority
        
        url_hash = item.get_url_hash()
        self._url_to_item.pop(url_hash, None)
        
        self.stats["total_popped"] += 1
        
        return item
    
    def peek(self) -> Optional[FrontierItem]:
        """Peek at highest priority item without removing."""
        if not self._heap:
            return None
        return self._heap[0]
    
    def is_empty(self) -> bool:
        """Check if frontier is empty."""
        return len(self._heap) == 0
    
    def size(self) -> int:
        """Get current size of frontier."""
        return len(self._heap)
    
    def has_seen(self, url: str, method: str = "GET") -> bool:
        """Check if URL has been seen."""
        url_hash = hashlib.sha256(f"{method}:{url}".encode()).hexdigest()[:16]
        return url_hash in self._seen
    
    def _compute_priority(self, features: FeatureVector, depth: int) -> float:
        """
        Compute priority score from features.
        Higher score = higher priority.
        """
        score = 0.0
        
        # Novelty features (most important)
        score += features.insertion_point_novelty * self.WEIGHTS["insertion_point_novelty"]
        score += features.endpoint_novelty * self.WEIGHTS["endpoint_novelty"]
        
        # Content type features
        if features.is_api:
            score += self.WEIGHTS["is_api"]
        if features.is_form:
            score += self.WEIGHTS["is_form"]
        if features.is_authenticated:
            score += self.WEIGHTS["is_authenticated"]
        if features.is_admin_path:
            score += self.WEIGHTS["is_admin_path"]
        
        # Security features
        if features.has_upload:
            score += self.WEIGHTS["has_upload"]
        if features.has_sensitive_params:
            score += self.WEIGHTS["has_sensitive_params"]
        if features.has_auth_headers:
            score += self.WEIGHTS["has_auth_headers"]
        
        # Source type bonus
        if features.source_type == SourceType.API_SPEC:
            score += self.WEIGHTS["source_api_spec"]
        elif features.source_type == SourceType.GRAPHQL:
            score += self.WEIGHTS["source_graphql"]
        elif features.source_type == SourceType.XHR:
            score += self.WEIGHTS["source_xhr"]
        
        # Depth penalty (prefer shallower pages)
        score -= depth * self.WEIGHTS["depth_penalty"]
        
        return max(0.0, score)
    
    def get_stats(self) -> dict:
        """Get frontier statistics."""
        return {
            **self.stats,
            "current_size": len(self._heap),
            "seen_urls": len(self._seen),
        }
    
    def clear(self):
        """Clear the frontier."""
        self._heap.clear()
        self._seen.clear()
        self._url_to_item.clear()


class SmartFrontierBuilder:
    """Helper to build frontier items with intelligent feature extraction."""
    
    # Patterns for path analysis
    ADMIN_PATTERNS = ["/admin", "/dashboard", "/manage", "/console", "/backend"]
    SENSITIVE_PARAMS = ["password", "token", "secret", "key", "api_key", "auth"]
    UPLOAD_PATTERNS = ["/upload", "/file", "/attachment", "/media"]
    
    @classmethod
    def from_url(
        cls,
        url: str,
        method: str = "GET",
        source_type: SourceType = SourceType.LINK,
        depth: int = 0,
        parent_url: Optional[str] = None,
        novelty_score: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> FrontierItem:
        """
        Create frontier item from URL with automatic feature extraction.
        
        Args:
            url: Target URL
            method: HTTP method
            source_type: How this URL was discovered
            depth: Crawl depth
            parent_url: Parent URL
            novelty_score: Pre-computed novelty score (0.0 to 1.0)
            metadata: Additional metadata
        
        Returns:
            FrontierItem with computed features
        """
        parsed = urlparse(url)
        path = parsed.path.lower()
        query = parsed.query.lower()
        
        # Build features
        features = FeatureVector(source_type=source_type)
        
        # Novelty
        features.endpoint_novelty = novelty_score
        features.insertion_point_novelty = novelty_score
        
        # Content type detection
        features.is_api = cls._is_api_endpoint(path, parsed.netloc)
        features.is_form = method == "POST" or "form" in path
        
        # Path analysis
        features.is_admin_path = any(pattern in path for pattern in cls.ADMIN_PATTERNS)
        features.has_upload = any(pattern in path for pattern in cls.UPLOAD_PATTERNS)
        
        # Parameter analysis
        features.has_sensitive_params = any(
            param in query for param in cls.SENSITIVE_PARAMS
        )
        
        # Depth
        features.depth_from_root = depth
        
        return FrontierItem(
            priority=0.0,  # Will be computed
            url=url,
            method=method,
            features=features,
            metadata=metadata or {},
            depth=depth,
            parent_url=parent_url,
        )
    
    @staticmethod
    def _is_api_endpoint(path: str, netloc: str) -> bool:
        """Check if URL looks like an API endpoint."""
        api_indicators = [
            "/api/", "/v1/", "/v2/", "/v3/", "/rest/", "/graphql",
            "/json", "/xml", "api.", "api-"
        ]
        return any(indicator in path or indicator in netloc for indicator in api_indicators)
