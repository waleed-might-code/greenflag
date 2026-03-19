"""
Novelty Tracking Module

Tracks insertion point shapes and request patterns to identify novel attack surface
and avoid redundant testing. Uses Redis or in-memory storage for fast lookups.
"""

import hashlib
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta


@dataclass
class NoveltyRecord:
    """Record of when a shape was first seen."""
    shape_hash: str
    first_seen: float  # Unix timestamp
    count: int
    last_seen: float
    metadata: Dict


class NoveltyTracker:
    """
    Tracks novelty of insertion points and request shapes.
    
    Supports:
    - In-memory tracking (fast, for single process)
    - Redis tracking (distributed, for multi-worker)
    - Shape-based deduplication
    - Coverage metrics
    """
    
    def __init__(self, storage_backend: str = "memory", redis_client=None):
        """
        Initialize novelty tracker.
        
        Args:
            storage_backend: "memory" or "redis"
            redis_client: Redis client instance (required if backend is "redis")
        """
        self.storage_backend = storage_backend
        self.redis_client = redis_client
        
        # In-memory storage
        self._memory_store: Dict[str, NoveltyRecord] = {}
        
        # Statistics
        self.stats = {
            'total_checked': 0,
            'novel_count': 0,
            'duplicate_count': 0
        }
    
    def is_novel(self, shape_hash: str, metadata: Optional[Dict] = None) -> bool:
        """
        Check if a shape hash is novel (not seen before).
        
        Args:
            shape_hash: Hash of the insertion point or request shape
            metadata: Optional metadata to store with the record
        
        Returns:
            True if novel, False if already seen
        """
        self.stats['total_checked'] += 1
        
        if self.storage_backend == "redis":
            return self._is_novel_redis(shape_hash, metadata)
        else:
            return self._is_novel_memory(shape_hash, metadata)
    
    def _is_novel_memory(self, shape_hash: str, metadata: Optional[Dict]) -> bool:
        """Check novelty using in-memory storage."""
        now = time.time()
        
        if shape_hash in self._memory_store:
            # Update existing record
            record = self._memory_store[shape_hash]
            record.count += 1
            record.last_seen = now
            self.stats['duplicate_count'] += 1
            return False
        else:
            # New record
            self._memory_store[shape_hash] = NoveltyRecord(
                shape_hash=shape_hash,
                first_seen=now,
                count=1,
                last_seen=now,
                metadata=metadata or {}
            )
            self.stats['novel_count'] += 1
            return True
    
    def _is_novel_redis(self, shape_hash: str, metadata: Optional[Dict]) -> bool:
        """Check novelty using Redis storage."""
        if not self.redis_client:
            raise ValueError("Redis client required for redis backend")
        
        key = f"novelty:{shape_hash}"
        now = time.time()
        
        # Try to set with NX (only if not exists)
        if self.redis_client.setnx(key, now):
            # New record
            self.redis_client.expire(key, 86400 * 90)  # 90 days TTL
            if metadata:
                self.redis_client.hset(f"novelty:meta:{shape_hash}", mapping=metadata)
            self.stats['novel_count'] += 1
            return True
        else:
            # Already exists
            self.redis_client.incr(f"novelty:count:{shape_hash}")
            self.stats['duplicate_count'] += 1
            return False
    
    def get_record(self, shape_hash: str) -> Optional[NoveltyRecord]:
        """Get the novelty record for a shape hash."""
        if self.storage_backend == "redis":
            return self._get_record_redis(shape_hash)
        else:
            return self._memory_store.get(shape_hash)
    
    def _get_record_redis(self, shape_hash: str) -> Optional[NoveltyRecord]:
        """Get record from Redis."""
        if not self.redis_client:
            return None
        
        key = f"novelty:{shape_hash}"
        first_seen = self.redis_client.get(key)
        
        if not first_seen:
            return None
        
        count_key = f"novelty:count:{shape_hash}"
        count = self.redis_client.get(count_key)
        
        meta_key = f"novelty:meta:{shape_hash}"
        metadata = self.redis_client.hgetall(meta_key)
        
        return NoveltyRecord(
            shape_hash=shape_hash,
            first_seen=float(first_seen),
            count=int(count) if count else 1,
            last_seen=time.time(),
            metadata=metadata or {}
        )
    
    def get_novel_shapes(self, limit: int = 100) -> List[NoveltyRecord]:
        """Get the most recently discovered novel shapes."""
        if self.storage_backend == "redis":
            # Not implemented for Redis (would need sorted set)
            return []
        else:
            records = sorted(
                self._memory_store.values(),
                key=lambda r: r.first_seen,
                reverse=True
            )
            return records[:limit]
    
    def get_coverage_stats(self) -> Dict:
        """Get coverage statistics."""
        if self.storage_backend == "redis":
            total_shapes = len(self.redis_client.keys("novelty:*"))
        else:
            total_shapes = len(self._memory_store)
        
        return {
            'total_shapes': total_shapes,
            'total_checked': self.stats['total_checked'],
            'novel_count': self.stats['novel_count'],
            'duplicate_count': self.stats['duplicate_count'],
            'novelty_rate': self.stats['novel_count'] / max(self.stats['total_checked'], 1)
        }
    
    def clear(self):
        """Clear all novelty records."""
        if self.storage_backend == "redis":
            if self.redis_client:
                for key in self.redis_client.scan_iter("novelty:*"):
                    self.redis_client.delete(key)
        else:
            self._memory_store.clear()
        
        self.stats = {
            'total_checked': 0,
            'novel_count': 0,
            'duplicate_count': 0
        }
    
    def export_shapes(self) -> List[Dict]:
        """Export all tracked shapes for analysis."""
        if self.storage_backend == "redis":
            # Not implemented for Redis
            return []
        else:
            return [asdict(record) for record in self._memory_store.values()]
    
    def compute_endpoint_shape(self, method: str, url_template: str,
                               param_names: List[str]) -> str:
        """
        Compute shape hash for an endpoint.
        
        Args:
            method: HTTP method
            url_template: URL with placeholders
            param_names: List of parameter names
        
        Returns:
            Shape hash string
        """
        shape_parts = [
            method.upper(),
            url_template,
            ','.join(sorted(param_names))
        ]
        shape_str = '|'.join(shape_parts)
        return hashlib.sha256(shape_str.encode('utf-8')).hexdigest()[:16]
    
    def compute_insertion_point_shape(self, location: str, param_name: str,
                                     inferred_type: str, encoding_layers: List[str]) -> str:
        """
        Compute shape hash for an insertion point.
        
        Args:
            location: Parameter location (query, body, header, path)
            param_name: Parameter name
            inferred_type: Type placeholder (<INT>, <STRING>, etc.)
            encoding_layers: List of encoding types
        
        Returns:
            Shape hash string
        """
        shape_parts = [
            location,
            param_name,
            inferred_type,
            ','.join(encoding_layers)
        ]
        shape_str = '|'.join(shape_parts)
        return hashlib.sha256(shape_str.encode('utf-8')).hexdigest()[:16]
