"""
Fast, in-process scope validation.
Pre-compiles scope rules for O(1) domain checks and O(n) pattern matching.
With LRU caching for repeated URL validation.
"""

import fnmatch
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode

from loguru import logger

try:
    from .scope_cache import ScopeValidationCache
except ImportError:
    ScopeValidationCache = None


class ScopeDecision(Enum):
    """Scope validation decision."""
    ALLOW = "allow"
    DENY = "deny"
    LOG_ONLY = "log_only"


@dataclass
class ScopeCheckResult:
    """Result of a scope check."""
    decision: ScopeDecision
    reason: str
    normalized_url: str
    matched_pattern: Optional[str] = None


class ScopeValidator:
    """
    Fast scope validator with pre-compiled rules.
    
    Design:
    - Domain checking: O(1) set lookup after normalization
    - Pattern matching: O(n) where n = number of out-of-scope patterns
    - No network calls, no DB queries - pure in-memory computation
    - Thread-safe (immutable after construction)
    """
    
    def __init__(
        self,
        target_domains: list[str],
        out_of_scope_patterns: list[str],
        allowed_schemes: list[str],
        enable_cache: bool = True,
        cache_size: int = 10000,
        cache_ttl: int = 3600,
    ):
        """
        Initialize scope validator.
        
        Args:
            target_domains: List of allowed domains (e.g., ["https://example.com"])
            out_of_scope_patterns: List of glob/regex patterns to exclude
            allowed_schemes: List of allowed URL schemes (e.g., ["https", "http"])
            enable_cache: Enable LRU cache for validation results
            cache_size: Maximum cache entries
            cache_ttl: Cache TTL in seconds
        """
        # Pre-compile domain set for O(1) lookup
        self._allowed_domains: set[str] = set()
        self._allowed_domain_suffixes: set[str] = set()
        
        for domain in target_domains:
            parsed = urlparse(domain)
            netloc = parsed.netloc.lower()
            self._allowed_domains.add(netloc)
            # Also allow subdomains
            self._allowed_domain_suffixes.add(f".{netloc}")
        
        # Pre-compile out-of-scope patterns
        self._out_of_scope_globs: list[str] = []
        self._out_of_scope_regexes: list[re.Pattern] = []
        
        for pattern in out_of_scope_patterns:
            if self._is_regex_pattern(pattern):
                try:
                    self._out_of_scope_regexes.append(re.compile(pattern))
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{pattern}': {e}")
            else:
                self._out_of_scope_globs.append(pattern)
        
        self._allowed_schemes = set(s.lower() for s in allowed_schemes)
        
        # Initialize cache
        self._cache = None
        if enable_cache and ScopeValidationCache:
            self._cache = ScopeValidationCache(max_size=cache_size, ttl_seconds=cache_ttl)
        
        # Performance tracking
        self._timing_samples: list[float] = []
        self._max_timing_samples = 1000
        
        logger.info(
            f"Scope validator initialized: "
            f"{len(self._allowed_domains)} domains, "
            f"{len(self._out_of_scope_globs)} glob patterns, "
            f"{len(self._out_of_scope_regexes)} regex patterns, "
            f"cache={'enabled' if self._cache else 'disabled'}"
        )
    
    @staticmethod
    def _is_regex_pattern(pattern: str) -> bool:
        """Check if pattern looks like a regex (contains regex metacharacters)."""
        regex_chars = r"[.^$+?{}[\]\\|()"
        return any(c in pattern for c in regex_chars) and not pattern.startswith("*")
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize URL for consistent comparison.
        
        - Strip fragment
        - Sort query parameters
        - Lowercase scheme and domain
        - Remove default ports
        """
        parsed = urlparse(url)
        
        # Normalize scheme and netloc
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        
        # Remove default ports
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]
        
        # Sort query parameters
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        sorted_query = urlencode(sorted(query_params.items()), doseq=True)
        
        # Reconstruct without fragment
        normalized = f"{scheme}://{netloc}{parsed.path}"
        if sorted_query:
            normalized += f"?{sorted_query}"
        
        return normalized
    
    def is_in_scope(self, url: str, method: str = "GET") -> ScopeCheckResult:
        """
        Check if URL is in scope.
        
        Fast path:
        1. Normalize URL (O(1))
        2. Check scheme (O(1))
        3. Check domain (O(1) set lookup)
        4. Check out-of-scope patterns (O(n) where n = pattern count)
        
        Args:
            url: URL to check
            method: HTTP method (for logging)
            
        Returns:
            ScopeCheckResult with decision and reason
        """
        try:
            normalized = self.normalize_url(url)
            parsed = urlparse(normalized)
            
            # Check scheme
            if parsed.scheme not in self._allowed_schemes:
                return ScopeCheckResult(
                    decision=ScopeDecision.DENY,
                    reason=f"Scheme '{parsed.scheme}' not in allowed schemes",
                    normalized_url=normalized,
                )
            
            # Check domain (O(1) lookup)
            netloc = parsed.netloc.lower()
            domain_allowed = False
            
            if netloc in self._allowed_domains:
                domain_allowed = True
            else:
                # Check if it's a subdomain of an allowed domain
                for suffix in self._allowed_domain_suffixes:
                    if netloc.endswith(suffix):
                        domain_allowed = True
                        break
            
            if not domain_allowed:
                return ScopeCheckResult(
                    decision=ScopeDecision.DENY,
                    reason=f"Domain '{netloc}' not in target domains",
                    normalized_url=normalized,
                )
            
            # Check out-of-scope patterns
            full_url = normalized
            path = parsed.path
            
            # Check glob patterns
            for pattern in self._out_of_scope_globs:
                if fnmatch.fnmatch(full_url, pattern) or fnmatch.fnmatch(path, pattern):
                    return ScopeCheckResult(
                        decision=ScopeDecision.DENY,
                        reason=f"Matched out-of-scope pattern",
                        normalized_url=normalized,
                        matched_pattern=pattern,
                    )
            
            # Check regex patterns
            for regex in self._out_of_scope_regexes:
                if regex.search(full_url) or regex.search(path):
                    return ScopeCheckResult(
                        decision=ScopeDecision.DENY,
                        reason=f"Matched out-of-scope regex",
                        normalized_url=normalized,
                        matched_pattern=regex.pattern,
                    )
            
            # All checks passed
            result = ScopeCheckResult(
                decision=ScopeDecision.ALLOW,
                reason="In scope",
                normalized_url=normalized,
            )
            
            # Cache result
            if self._cache:
                self._cache.put(url, method, result)
            
            self._record_timing(time.perf_counter() - start_time)
            return result
        
        except Exception as e:
            logger.error(f"Error validating scope for {url}: {e}")
            result = ScopeCheckResult(
                decision=ScopeDecision.DENY,
                reason=f"Validation error: {str(e)}",
                normalized_url=url,
            )
            self._record_timing(time.perf_counter() - start_time)
            return result
    
    def is_allowed(self, url: str, method: str = "GET") -> bool:
        """Quick boolean check if URL is allowed."""
        result = self.is_in_scope(url, method)
        return result.decision == ScopeDecision.ALLOW
    
    def _record_timing(self, duration: float) -> None:
        """Record validation timing for performance monitoring."""
        if len(self._timing_samples) >= self._max_timing_samples:
            self._timing_samples.pop(0)
        self._timing_samples.append(duration)
    
    def get_performance_stats(self) -> dict:
        """Get performance statistics."""
        if not self._timing_samples:
            return {
                "avg_latency_ms": 0.0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "max_latency_ms": 0.0,
                "samples": 0,
            }
        
        sorted_samples = sorted(self._timing_samples)
        n = len(sorted_samples)
        
        return {
            "avg_latency_ms": (sum(sorted_samples) / n) * 1000,
            "p50_latency_ms": sorted_samples[n // 2] * 1000,
            "p95_latency_ms": sorted_samples[int(n * 0.95)] * 1000,
            "p99_latency_ms": sorted_samples[int(n * 0.99)] * 1000,
            "max_latency_ms": sorted_samples[-1] * 1000,
            "samples": n,
        }
    
    def get_stats(self) -> dict:
        """Get validator statistics."""
        stats = {
            "allowed_domains": len(self._allowed_domains),
            "allowed_domain_suffixes": len(self._allowed_domain_suffixes),
            "out_of_scope_globs": len(self._out_of_scope_globs),
            "out_of_scope_regexes": len(self._out_of_scope_regexes),
            "allowed_schemes": list(self._allowed_schemes),
            "performance": self.get_performance_stats(),
        }
        
        if self._cache:
            stats["cache"] = self._cache.get_stats()
        
        return stats
