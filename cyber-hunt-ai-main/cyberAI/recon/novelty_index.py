"""
Novelty Index - Tracks unique insertion point shapes for prioritization.
"""

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class NoveltyStats:
    """Statistics about insertion point novelty."""
    total_requests: int = 0
    unique_shapes: int = 0
    novel_endpoints: int = 0
    duplicate_requests: int = 0


class NoveltyIndex:
    """
    Tracks unique insertion point shapes to identify novel endpoints.
    
    Used for prioritization: novel endpoints (new shapes) are higher priority
    than endpoints we've already seen many times.
    """
    
    def __init__(self):
        """Initialize novelty index."""
        # shape_hash -> first_seen_timestamp
        self._shapes: dict[str, float] = {}
        
        # endpoint_template -> count
        self._endpoint_counts: dict[str, int] = defaultdict(int)
        
        # endpoint_template -> set of shape_hashes
        self._endpoint_shapes: dict[str, set[str]] = defaultdict(set)
        
        self._stats = NoveltyStats()
    
    def record(self, endpoint_template: str, shape_hash: str) -> bool:
        """
        Record a request shape.
        
        Args:
            endpoint_template: URL template (e.g., "/api/users/{id}")
            shape_hash: Hash of the request shape
            
        Returns:
            True if this is a novel shape, False if seen before
        """
        self._stats.total_requests += 1
        self._endpoint_counts[endpoint_template] += 1
        
        # Check if shape is novel
        is_novel = shape_hash not in self._shapes
        
        if is_novel:
            self._shapes[shape_hash] = time.time()
            self._stats.unique_shapes += 1
            
            # Check if this is a novel endpoint (first shape for this template)
            if endpoint_template not in self._endpoint_shapes:
                self._stats.novel_endpoints += 1
            
            self._endpoint_shapes[endpoint_template].add(shape_hash)
        else:
            self._stats.duplicate_requests += 1
        
        return is_novel
    
    def get_novelty_score(self, endpoint_template: str, shape_hash: str) -> float:
        """
        Get novelty score for a request.
        
        Higher score = more novel = higher priority.
        
        Score factors:
        - New shape: 1.0
        - Seen shape: 0.1
        - Endpoint frequency: 1.0 / log(count + 1)
        
        Returns:
            Novelty score between 0.0 and 1.0
        """
        # Base score: is this shape novel?
        if shape_hash not in self._shapes:
            base_score = 1.0
        else:
            base_score = 0.1
        
        # Frequency penalty: endpoints we've seen many times are lower priority
        count = self._endpoint_counts.get(endpoint_template, 0)
        if count > 0:
            import math
            frequency_factor = 1.0 / math.log(count + 2)
        else:
            frequency_factor = 1.0
        
        return base_score * frequency_factor
    
    def get_endpoint_stats(self, endpoint_template: str) -> dict:
        """Get statistics for a specific endpoint."""
        return {
            "count": self._endpoint_counts.get(endpoint_template, 0),
            "unique_shapes": len(self._endpoint_shapes.get(endpoint_template, set())),
        }
    
    def get_stats(self) -> NoveltyStats:
        """Get overall statistics."""
        return self._stats
    
    def get_top_novel_endpoints(self, limit: int = 10) -> list[tuple[str, int]]:
        """
        Get top novel endpoints (most unique shapes).
        
        Returns:
            List of (endpoint_template, unique_shape_count) tuples
        """
        endpoint_novelty = [
            (endpoint, len(shapes))
            for endpoint, shapes in self._endpoint_shapes.items()
        ]
        
        # Sort by unique shape count (descending)
        endpoint_novelty.sort(key=lambda x: x[1], reverse=True)
        
        return endpoint_novelty[:limit]
    
    def clear(self) -> None:
        """Clear all data."""
        self._shapes.clear()
        self._endpoint_counts.clear()
        self._endpoint_shapes.clear()
        self._stats = NoveltyStats()
        logger.info("Novelty index cleared")
