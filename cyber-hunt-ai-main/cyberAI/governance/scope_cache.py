"""
High-performance LRU cache for scope validation results.
Reduces repeated validation overhead for frequently-accessed URLs.
"""

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from .scope_validator import ScopeCheckResult


@dataclass
class CacheStats:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_lookups: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        return self.hits / self.total_lookups if self.total_lookups > 0 else 0.0


class ScopeValidationCache:
    """
    Thread-safe LRU cache for scope validation results.
    
    Performance characteristics:
    - O(1) lookup and insertion
    - O(1) eviction (LRU)
    - Thread-safe with minimal lock contention
    - Configurable TTL to handle dynamic scope changes
    """
    
    def __init__(self, max_size: int = 10000, ttl_seconds: int = 3600):
        """
        Initialize cache.
        
        Args:
            max_size: Maximum number of entries
            ttl_seconds: Time-to-live for cache entries
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[ScopeCheckResult, float]] = OrderedDict()
        self._lock = Lock()
        self._stats = CacheStats()
    
    def _make_key(self, url: str, method: str) -> str:
        """Create cache key from URL and method."""
        return f"{method}:{url}"
    
    def get(self, url: str, method: str) -> Optional[ScopeCheckResult]:
        """
        Get cached validation result.
        
        Args:
            url: Request URL
            method: HTTP method
            
        Returns:
            Cached result if found and not expired, None otherwise
        """
        key = self._make_key(url, method)
        
        with self._lock:
            self._stats.total_lookups += 1
            
            if key not in self._cache:
                self._stats.misses += 1
                return None
            
            result, timestamp = self._cache[key]
            
            # Check TTL
            if time.time() - timestamp > self.ttl_seconds:
                del self._cache[key]
                self._stats.misses += 1
                return None
            
            # Move to end (LRU)
            self._cache.move_to_end(key)
            self._stats.hits += 1
            return result
    
    def put(self, url: str, method: str, result: ScopeCheckResult) -> None:
        """
        Store validation result in cache.
        
        Args:
            url: Request URL
            method: HTTP method
            result: Validation result
        """
        key = self._make_key(url, method)
        
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._cache.popitem(last=False)
                self._stats.evictions += 1
            
            self._cache[key] = (result, time.time())
            self._cache.move_to_end(key)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "evictions": self._stats.evictions,
                "total_lookups": self._stats.total_lookups,
                "hit_rate": self._stats.hit_rate,
                "ttl_seconds": self.ttl_seconds,
            }
