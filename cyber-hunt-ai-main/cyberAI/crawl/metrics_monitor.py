"""
Real-time metrics monitoring for data mining operations.
Tracks performance, throughput, and data extraction rates.
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger


@dataclass
class MetricSnapshot:
    """Snapshot of metrics at a point in time."""
    timestamp: float
    pages_crawled: int
    states_discovered: int
    insertion_points: int
    bytes_captured: int
    api_calls: int


class MetricsMonitor:
    """
    Real-time metrics monitoring for crawl operations.
    
    Tracks:
    - Throughput (pages/sec, bytes/sec)
    - State management efficiency
    - Data extraction rates
    - Resource utilization
    """
    
    def __init__(self, snapshot_interval: float = 10.0):
        """
        Initialize metrics monitor.
        
        Args:
            snapshot_interval: Seconds between snapshots
        """
        self.snapshot_interval = snapshot_interval
        self.start_time = time.time()
        self.last_snapshot_time = self.start_time
        
        # Snapshots for rate calculation
        self.snapshots: List[MetricSnapshot] = []
        
        # Current metrics
        self.current = {
            'pages_crawled': 0,
            'states_discovered': 0,
            'insertion_points': 0,
            'bytes_captured': 0,
            'api_calls': 0,
        }
        
        # Rates (per second)
        self.rates = {
            'pages_per_sec': 0.0,
            'states_per_sec': 0.0,
            'bytes_per_sec': 0.0,
            'insertion_points_per_sec': 0.0,
        }
    
    def update(self, metrics: Dict) -> None:
        """
        Update current metrics.
        
        Args:
            metrics: Dictionary of current metric values
        """
        self.current.update(metrics)
        
        # Take snapshot if interval elapsed
        now = time.time()
        if now - self.last_snapshot_time >= self.snapshot_interval:
            self._take_snapshot()
            self._calculate_rates()
            self.last_snapshot_time = now
    
    def _take_snapshot(self) -> None:
        """Take a snapshot of current metrics."""
        snapshot = MetricSnapshot(
            timestamp=time.time(),
            pages_crawled=self.current['pages_crawled'],
            states_discovered=self.current['states_discovered'],
            insertion_points=self.current['insertion_points'],
            bytes_captured=self.current['bytes_captured'],
            api_calls=self.current['api_calls'],
        )
        self.snapshots.append(snapshot)
        
        # Keep only last 100 snapshots
        if len(self.snapshots) > 100:
            self.snapshots = self.snapshots[-100:]
    
    def _calculate_rates(self) -> None:
        """Calculate rates from recent snapshots."""
        if len(self.snapshots) < 2:
            return
        
        # Compare last two snapshots
        prev = self.snapshots[-2]
        curr = self.snapshots[-1]
        
        time_delta = curr.timestamp - prev.timestamp
        if time_delta == 0:
            return
        
        self.rates['pages_per_sec'] = (curr.pages_crawled - prev.pages_crawled) / time_delta
        self.rates['states_per_sec'] = (curr.states_discovered - prev.states_discovered) / time_delta
        self.rates['bytes_per_sec'] = (curr.bytes_captured - prev.bytes_captured) / time_delta
        self.rates['insertion_points_per_sec'] = (curr.insertion_points - prev.insertion_points) / time_delta
    
    def get_current_rates(self) -> Dict[str, float]:
        """Get current rates."""
        return self.rates.copy()
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time
    
    def get_summary(self) -> Dict:
        """Get summary of all metrics."""
        elapsed = self.get_elapsed_time()
        
        return {
            'elapsed_seconds': elapsed,
            'elapsed_formatted': self._format_duration(elapsed),
            'current': self.current.copy(),
            'rates': self.rates.copy(),
            'averages': {
                'avg_pages_per_sec': self.current['pages_crawled'] / elapsed if elapsed > 0 else 0,
                'avg_bytes_per_sec': self.current['bytes_captured'] / elapsed if elapsed > 0 else 0,
            },
            'totals': {
                'total_pages': self.current['pages_crawled'],
                'total_states': self.current['states_discovered'],
                'total_insertion_points': self.current['insertion_points'],
                'total_mb_captured': self.current['bytes_captured'] / 1024 / 1024,
            },
        }
    
    def log_progress(self) -> None:
        """Log current progress."""
        summary = self.get_summary()
        
        logger.info(
            f"⚡ {summary['elapsed_formatted']} | "
            f"{summary['totals']['total_pages']} pages "
            f"({summary['rates']['pages_per_sec']:.1f}/s) | "
            f"{summary['totals']['total_states']} states | "
            f"{summary['totals']['total_insertion_points']} IPs | "
            f"{summary['totals']['total_mb_captured']:.1f} MB "
            f"({summary['rates']['bytes_per_sec'] / 1024:.1f} KB/s)"
        )
    
    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        else:
            return f"{seconds / 3600:.1f}h"
