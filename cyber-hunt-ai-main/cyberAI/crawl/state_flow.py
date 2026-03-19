"""
State-Flow Crawler - Crawljax-style state detection for SPAs.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class CrawlState:
    """Represents a unique state in the application."""
    state_id: str
    url: str
    dom_hash: str
    screenshot_path: Optional[str] = None
    discovered_at: float = 0.0
    actions: list[dict] = field(default_factory=list)
    
    def __hash__(self):
        return hash(self.state_id)


@dataclass
class StateTransition:
    """Represents a transition between states."""
    from_state_id: str
    to_state_id: str
    action_type: str  # click, submit, input, navigate
    selector: Optional[str] = None
    payload: Optional[dict] = None


class StateFlowDetector:
    """
    Detects application states and transitions (Crawljax-style).
    
    Used for SPAs where the URL doesn't change but the DOM does.
    """
    
    def __init__(self, similarity_threshold: float = 0.95):
        """
        Initialize state flow detector.
        
        Args:
            similarity_threshold: Threshold for considering states similar
        """
        self.similarity_threshold = similarity_threshold
        
        # state_id -> CrawlState
        self._states: dict[str, CrawlState] = {}
        
        # Transitions
        self._transitions: list[StateTransition] = []
        
        # DOM hash -> state_id mapping
        self._hash_to_state: dict[str, str] = {}
    
    def compute_dom_hash(self, dom: str) -> str:
        """
        Compute hash of DOM structure.
        
        Strips dynamic content (timestamps, random IDs) before hashing.
        """
        # Remove script and style tags
        import re
        dom = re.sub(r'<script[^>]*>.*?</script>', '', dom, flags=re.DOTALL | re.IGNORECASE)
        dom = re.sub(r'<style[^>]*>.*?</style>', '', dom, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove common dynamic attributes
        dom = re.sub(r'\s+data-reactid="[^"]*"', '', dom)
        dom = re.sub(r'\s+data-v-[a-f0-9]+="[^"]*"', '', dom)
        dom = re.sub(r'\s+id="[^"]*-\d+"', '', dom)  # IDs with numbers
        
        # Remove timestamps
        dom = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', 'TIMESTAMP', dom)
        dom = re.sub(r'\d{10,13}', 'TIMESTAMP', dom)  # Unix timestamps
        
        # Normalize whitespace
        dom = re.sub(r'\s+', ' ', dom)
        
        # Compute hash
        return hashlib.sha256(dom.encode()).hexdigest()[:16]
    
    def record_state(
        self,
        url: str,
        dom: str,
        screenshot_path: Optional[str] = None,
    ) -> tuple[CrawlState, bool]:
        """
        Record a state.
        
        Args:
            url: Current URL
            dom: DOM content
            screenshot_path: Optional screenshot path
            
        Returns:
            Tuple of (CrawlState, is_new)
        """
        import time
        
        dom_hash = self.compute_dom_hash(dom)
        
        # Check if state already exists
        if dom_hash in self._hash_to_state:
            state_id = self._hash_to_state[dom_hash]
            state = self._states[state_id]
            return state, False
        
        # Create new state
        state_id = f"state_{len(self._states)}"
        state = CrawlState(
            state_id=state_id,
            url=url,
            dom_hash=dom_hash,
            screenshot_path=screenshot_path,
            discovered_at=time.time(),
        )
        
        self._states[state_id] = state
        self._hash_to_state[dom_hash] = state_id
        
        logger.info(f"New state discovered: {state_id} at {url}")
        
        return state, True
    
    def record_transition(
        self,
        from_state: CrawlState,
        to_state: CrawlState,
        action_type: str,
        selector: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        """Record a state transition."""
        transition = StateTransition(
            from_state_id=from_state.state_id,
            to_state_id=to_state.state_id,
            action_type=action_type,
            selector=selector,
            payload=payload,
        )
        
        self._transitions.append(transition)
        
        logger.debug(
            f"Transition: {from_state.state_id} --[{action_type}]--> {to_state.state_id}"
        )
    
    def get_state_count(self) -> int:
        """Get number of discovered states."""
        return len(self._states)
    
    def get_transition_count(self) -> int:
        """Get number of recorded transitions."""
        return len(self._transitions)
    
    def get_state_graph(self) -> dict:
        """
        Get state graph as dictionary.
        
        Returns:
            Dictionary with nodes (states) and edges (transitions)
        """
        nodes = [
            {
                "id": state.state_id,
                "url": state.url,
                "dom_hash": state.dom_hash,
                "screenshot": state.screenshot_path,
            }
            for state in self._states.values()
        ]
        
        edges = [
            {
                "from": t.from_state_id,
                "to": t.to_state_id,
                "action": t.action_type,
                "selector": t.selector,
            }
            for t in self._transitions
        ]
        
        return {
            "nodes": nodes,
            "edges": edges,
        }
    
    def export_to_json(self, path: str) -> None:
        """Export state graph to JSON file."""
        graph = self.get_state_graph()
        
        with open(path, 'w') as f:
            json.dump(graph, f, indent=2)
        
        logger.info(f"Exported state graph to {path}")
    
    def get_stats(self) -> dict:
        """Get statistics."""
        return {
            "states": len(self._states),
            "transitions": len(self._transitions),
            "avg_transitions_per_state": (
                len(self._transitions) / len(self._states)
                if self._states else 0
            ),
        }
