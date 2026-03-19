"""
Adaptive State Manager - Prevents state explosion with intelligent caps and clustering.

Features:
- Dynamic state cap based on attack surface density
- State clustering to merge similar states
- Automatic pruning of low-value states
- Real-time metrics and monitoring
"""

import time
from typing import Optional, Dict, List, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from loguru import logger

from .dom_hasher import DOMHasher
from .frontier import CrawlFrontier, FrontierItem


@dataclass
class StateCluster:
    """Represents a cluster of similar states."""
    cluster_id: str
    representative_state_id: str
    member_state_ids: Set[str] = field(default_factory=set)
    simhash: int = 0
    attack_surface_score: float = 0.0
    forms_count: int = 0
    inputs_count: int = 0
    api_calls_count: int = 0
    
    def add_member(self, state_id: str) -> None:
        """Add a state to this cluster."""
        self.member_state_ids.add(state_id)
    
    def get_size(self) -> int:
        """Get cluster size."""
        return len(self.member_state_ids)


@dataclass
class StateMetrics:
    """Metrics for state explosion monitoring."""
    total_states_seen: int = 0
    unique_states_kept: int = 0
    states_clustered: int = 0
    states_pruned: int = 0
    clusters_created: int = 0
    avg_cluster_size: float = 0.0
    attack_surface_density: float = 0.0  # forms+inputs per state
    state_cap_adjustments: int = 0
    
    def update_avg_cluster_size(self, clusters: List[StateCluster]) -> None:
        """Update average cluster size."""
        if clusters:
            self.avg_cluster_size = sum(c.get_size() for c in clusters) / len(clusters)


class AdaptiveStateManager:
    """
    Manages state explosion with adaptive caps and clustering.
    
    Strategies:
    1. Cluster similar states (SimHash distance < threshold)
    2. Dynamically adjust state cap based on attack surface density
    3. Prune low-value states when approaching cap
    4. Prioritize high-value clusters for exploration
    """
    
    def __init__(
        self,
        initial_max_states: int = 10000,
        min_max_states: int = 1000,
        max_max_states: int = 50000,
        clustering_threshold: int = 5,  # SimHash hamming distance
        prune_threshold: float = 0.9,  # Prune when 90% full
    ):
        """
        Initialize adaptive state manager.
        
        Args:
            initial_max_states: Starting state cap
            min_max_states: Minimum state cap
            max_max_states: Maximum state cap
            clustering_threshold: SimHash distance for clustering
            prune_threshold: When to trigger pruning (0.0-1.0)
        """
        self.max_states = initial_max_states
        self.min_max_states = min_max_states
        self.max_max_states = max_max_states
        self.clustering_threshold = clustering_threshold
        self.prune_threshold = prune_threshold
        
        self.dom_hasher = DOMHasher(similarity_threshold=clustering_threshold)
        
        # State tracking
        self.states: Dict[str, Dict] = {}  # state_id -> state_data
        self.clusters: Dict[str, StateCluster] = {}  # cluster_id -> cluster
        self.state_to_cluster: Dict[str, str] = {}  # state_id -> cluster_id
        
        # Metrics
        self.metrics = StateMetrics()
        
        # Performance tracking
        self.last_adjustment_time = time.time()
        self.adjustment_interval = 60.0  # Adjust cap every 60s
    
    def should_accept_state(
        self,
        state_id: str,
        simhash: int,
        attack_surface_score: float,
    ) -> Tuple[bool, Optional[str]]:
        """
        Decide if a new state should be accepted.
        
        Args:
            state_id: State identifier
            simhash: SimHash of the state
            attack_surface_score: Attack surface score
            
        Returns:
            Tuple of (should_accept, cluster_id_if_merged)
        """
        self.metrics.total_states_seen += 1
        
        # Check if we've seen this exact state
        if state_id in self.states:
            return False, self.state_to_cluster.get(state_id)
        
        # Try to find a similar cluster
        similar_cluster = self._find_similar_cluster(simhash)
        
        if similar_cluster:
            # Merge into existing cluster
            similar_cluster.add_member(state_id)
            self.state_to_cluster[state_id] = similar_cluster.cluster_id
            self.metrics.states_clustered += 1
            
            logger.debug(
                f"State {state_id} merged into cluster {similar_cluster.cluster_id} "
                f"(size: {similar_cluster.get_size()})"
            )
            
            return False, similar_cluster.cluster_id
        
        # Check if we're approaching the cap
        if len(self.states) >= self.max_states * self.prune_threshold:
            # Trigger pruning
            self._prune_low_value_states()
        
        # Check if we're at the hard cap
        if len(self.states) >= self.max_states:
            # Only accept if attack surface score is high enough
            min_score = self._get_min_acceptable_score()
            if attack_surface_score < min_score:
                self.metrics.states_pruned += 1
                logger.debug(f"State {state_id} rejected: score {attack_surface_score:.2f} < {min_score:.2f}")
                return False, None
        
        # Accept the state and create a new cluster
        self.metrics.unique_states_kept += 1
        return True, None
    
    def register_state(
        self,
        state_id: str,
        simhash: int,
        url: str,
        forms_count: int = 0,
        inputs_count: int = 0,
        api_calls_count: int = 0,
    ) -> str:
        """
        Register a new state and create a cluster for it.
        
        Args:
            state_id: State identifier
            simhash: SimHash value
            url: State URL
            forms_count: Number of forms
            inputs_count: Number of inputs
            api_calls_count: Number of API calls
            
        Returns:
            Cluster ID
        """
        # Calculate attack surface score
        attack_surface_score = (
            forms_count * 15.0 +
            inputs_count * 10.0 +
            api_calls_count * 20.0
        )
        
        # Store state data
        self.states[state_id] = {
            'simhash': simhash,
            'url': url,
            'forms_count': forms_count,
            'inputs_count': inputs_count,
            'api_calls_count': api_calls_count,
            'attack_surface_score': attack_surface_score,
            'registered_at': time.time(),
        }
        
        # Create new cluster
        cluster_id = f"cluster_{len(self.clusters)}"
        cluster = StateCluster(
            cluster_id=cluster_id,
            representative_state_id=state_id,
            simhash=simhash,
            attack_surface_score=attack_surface_score,
            forms_count=forms_count,
            inputs_count=inputs_count,
            api_calls_count=api_calls_count,
        )
        cluster.add_member(state_id)
        
        self.clusters[cluster_id] = cluster
        self.state_to_cluster[state_id] = cluster_id
        self.metrics.clusters_created += 1
        
        # Adjust cap if needed
        self._maybe_adjust_cap()
        
        return cluster_id
    
    def _find_similar_cluster(self, simhash: int) -> Optional[StateCluster]:
        """Find a cluster with similar SimHash."""
        for cluster in self.clusters.values():
            distance = bin(simhash ^ cluster.simhash).count('1')
            if distance <= self.clustering_threshold:
                return cluster
        return None
    
    def _get_min_acceptable_score(self) -> float:
        """Get minimum attack surface score to accept new states."""
        if not self.states:
            return 0.0
        
        # Get scores of all states
        scores = [s['attack_surface_score'] for s in self.states.values()]
        scores.sort()
        
        # Return 75th percentile
        idx = int(len(scores) * 0.75)
        return scores[idx] if idx < len(scores) else 0.0
    
    def _prune_low_value_states(self) -> int:
        """
        Prune low-value states to make room.
        
        Returns:
            Number of states pruned
        """
        if len(self.states) < self.max_states * 0.5:
            return 0  # Don't prune if we're not that full
        
        # Calculate how many to prune (10% of current states)
        prune_count = max(1, int(len(self.states) * 0.1))
        
        # Sort states by attack surface score
        sorted_states = sorted(
            self.states.items(),
            key=lambda x: x[1]['attack_surface_score']
        )
        
        # Prune lowest-scoring states
        pruned = 0
        for state_id, _ in sorted_states[:prune_count]:
            # Remove from cluster
            cluster_id = self.state_to_cluster.get(state_id)
            if cluster_id and cluster_id in self.clusters:
                cluster = self.clusters[cluster_id]
                cluster.member_state_ids.discard(state_id)
                
                # If cluster is now empty, remove it
                if cluster.get_size() == 0:
                    del self.clusters[cluster_id]
            
            # Remove state
            del self.states[state_id]
            if state_id in self.state_to_cluster:
                del self.state_to_cluster[state_id]
            
            pruned += 1
        
        self.metrics.states_pruned += pruned
        logger.info(f"Pruned {pruned} low-value states (now {len(self.states)} states)")
        
        return pruned
    
    def _maybe_adjust_cap(self) -> None:
        """Dynamically adjust state cap based on attack surface density."""
        now = time.time()
        if now - self.last_adjustment_time < self.adjustment_interval:
            return
        
        self.last_adjustment_time = now
        
        if not self.states:
            return
        
        # Calculate attack surface density
        total_attack_surface = sum(
            s['forms_count'] + s['inputs_count'] + s['api_calls_count']
            for s in self.states.values()
        )
        density = total_attack_surface / len(self.states)
        self.metrics.attack_surface_density = density
        
        # Adjust cap based on density
        old_cap = self.max_states
        
        if density > 10.0:
            # High density: increase cap to explore more
            self.max_states = min(self.max_max_states, int(self.max_states * 1.2))
        elif density < 2.0:
            # Low density: decrease cap to avoid wasting time
            self.max_states = max(self.min_max_states, int(self.max_states * 0.8))
        
        if self.max_states != old_cap:
            self.metrics.state_cap_adjustments += 1
            logger.info(
                f"Adjusted state cap: {old_cap} -> {self.max_states} "
                f"(density: {density:.2f})"
            )
    
    def get_high_value_clusters(self, top_n: int = 100) -> List[StateCluster]:
        """Get top N highest-value clusters for exploration."""
        sorted_clusters = sorted(
            self.clusters.values(),
            key=lambda c: c.attack_surface_score,
            reverse=True
        )
        return sorted_clusters[:top_n]
    
    def get_metrics(self) -> Dict:
        """Get current metrics."""
        self.metrics.update_avg_cluster_size(list(self.clusters.values()))
        
        return {
            'total_states_seen': self.metrics.total_states_seen,
            'unique_states_kept': self.metrics.unique_states_kept,
            'states_clustered': self.metrics.states_clustered,
            'states_pruned': self.metrics.states_pruned,
            'clusters_created': self.metrics.clusters_created,
            'avg_cluster_size': self.metrics.avg_cluster_size,
            'attack_surface_density': self.metrics.attack_surface_density,
            'current_state_cap': self.max_states,
            'state_cap_adjustments': self.metrics.state_cap_adjustments,
            'deduplication_rate': (
                self.metrics.states_clustered / self.metrics.total_states_seen * 100
                if self.metrics.total_states_seen > 0 else 0.0
            ),
        }
    
    def should_stop_crawl(self) -> bool:
        """Check if crawl should stop."""
        return len(self.states) >= self.max_states
