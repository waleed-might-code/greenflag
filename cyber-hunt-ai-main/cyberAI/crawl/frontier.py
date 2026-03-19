"""
Priority queue frontier for intelligent crawl ordering.
Scores states by attack surface contribution and novelty.
"""

import heapq
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum
from loguru import logger


class ActionType(str, Enum):
    """Types of actions that can be performed."""
    NAVIGATE = "navigate"
    CLICK = "click"
    SUBMIT = "submit"
    INPUT = "input"
    SCROLL = "scroll"


@dataclass
class FrontierItem:
    """
    Item in the crawl frontier with priority scoring.
    """
    url: str
    action_type: ActionType
    selector: Optional[str] = None
    depth: int = 0
    source_state_id: Optional[str] = None
    
    # Feature vector for scoring
    has_forms: int = 0
    has_inputs: int = 0
    has_api_calls: int = 0
    is_authenticated: bool = False
    is_admin_path: bool = False
    content_type_score: float = 0.0  # API=1.0, form=0.8, static=0.3
    novelty_score: float = 1.0  # Based on insertion point novelty
    
    # Computed priority (lower = higher priority)
    priority: float = field(init=False)
    
    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Compute priority score after initialization."""
        self.priority = self._compute_priority()
    
    def _compute_priority(self) -> float:
        """
        Compute priority score (lower = higher priority).
        
        Scoring factors:
        - Depth penalty: deeper states are lower priority
        - Attack surface: forms, inputs, API calls increase priority
        - Authentication: authenticated paths are higher priority
        - Admin paths: admin/privileged paths are highest priority
        - Content type: API > forms > static
        - Novelty: new insertion points increase priority
        """
        score = 100.0  # Base score
        
        # Depth penalty (exponential)
        score += self.depth * 10
        
        # Attack surface bonus (negative = higher priority)
        score -= self.has_forms * 15
        score -= self.has_inputs * 10
        score -= self.has_api_calls * 20
        
        # Authentication bonus
        if self.is_authenticated:
            score -= 25
        
        # Admin path bonus (highest priority)
        if self.is_admin_path:
            score -= 50
        
        # Content type bonus
        score -= self.content_type_score * 30
        
        # Novelty bonus
        score -= self.novelty_score * 20
        
        return max(0.0, score)  # Ensure non-negative
    
    def __lt__(self, other: "FrontierItem") -> bool:
        """Compare items for heap ordering (lower priority = higher in queue)."""
        return self.priority < other.priority
    
    def __repr__(self) -> str:
        return f"FrontierItem(url={self.url[:50]}, priority={self.priority:.1f}, depth={self.depth})"


class CrawlFrontier:
    """
    Priority queue frontier for managing crawl state exploration.
    Implements intelligent ordering and state cap enforcement.
    """
    
    def __init__(self, max_states: int = 10000, max_depth: int = 10):
        """
        Initialize crawl frontier.
        
        Args:
            max_states: Maximum number of states to explore
            max_depth: Maximum depth from entry point
        """
        self.max_states = max_states
        self.max_depth = max_depth
        
        self._heap: list[FrontierItem] = []
        self._seen_urls: set[str] = set()
        self._states_explored: int = 0
        self._states_pruned: int = 0
        
    def push(self, item: FrontierItem) -> bool:
        """
        Add item to frontier if not seen and within limits.
        
        Args:
            item: Frontier item to add
            
        Returns:
            True if added, False if rejected
        """
        # Check depth limit
        if item.depth > self.max_depth:
            logger.debug(f"Pruned item at depth {item.depth}: {item.url[:50]}")
            self._states_pruned += 1
            return False
        
        # Check if URL already seen
        url_key = f"{item.url}#{item.action_type}#{item.selector or ''}"
        if url_key in self._seen_urls:
            return False
        
        # Check state limit
        if self._states_explored >= self.max_states:
            # Only accept if priority is better than worst item in heap
            if self._heap and item.priority >= self._heap[0].priority:
                logger.debug(f"Pruned low-priority item: {item.url[:50]}")
                self._states_pruned += 1
                return False
        
        self._seen_urls.add(url_key)
        heapq.heappush(self._heap, item)
        logger.debug(f"Added to frontier: {item}")
        return True
    
    def pop(self) -> Optional[FrontierItem]:
        """
        Get highest priority item from frontier.
        
        Returns:
            Next item to explore, or None if empty
        """
        if not self._heap:
            return None
        
        item = heapq.heappop(self._heap)
        self._states_explored += 1
        
        logger.info(
            f"Exploring state {self._states_explored}/{self.max_states}: "
            f"{item.url[:60]} (priority={item.priority:.1f}, depth={item.depth})"
        )
        
        return item
    
    def is_empty(self) -> bool:
        """Check if frontier is empty."""
        return len(self._heap) == 0
    
    def size(self) -> int:
        """Get current frontier size."""
        return len(self._heap)
    
    def should_stop(self) -> bool:
        """Check if crawl should stop (state limit reached)."""
        return self._states_explored >= self.max_states
    
    def prune_low_priority(self, keep_top_n: int = 1000) -> int:
        """
        Prune low-priority items from frontier.
        
        Args:
            keep_top_n: Number of top-priority items to keep
            
        Returns:
            Number of items pruned
        """
        if len(self._heap) <= keep_top_n:
            return 0
        
        # Keep only top N items
        top_items = heapq.nsmallest(keep_top_n, self._heap)
        pruned_count = len(self._heap) - len(top_items)
        
        self._heap = top_items
        heapq.heapify(self._heap)
        
        self._states_pruned += pruned_count
        logger.info(f"Pruned {pruned_count} low-priority items from frontier")
        
        return pruned_count
    
    def get_stats(self) -> dict[str, Any]:
        """Get frontier statistics."""
        return {
            "states_explored": self._states_explored,
            "states_in_queue": len(self._heap),
            "states_pruned": self._states_pruned,
            "unique_urls_seen": len(self._seen_urls),
            "max_states": self.max_states,
            "max_depth": self.max_depth,
            "completion_pct": (self._states_explored / self.max_states * 100) if self.max_states > 0 else 0,
        }
    
    def clear(self) -> None:
        """Clear frontier and reset counters."""
        self._heap.clear()
        self._seen_urls.clear()
        self._states_explored = 0
        self._states_pruned = 0
