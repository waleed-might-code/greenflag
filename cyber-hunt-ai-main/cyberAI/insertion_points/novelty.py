"""
Novelty tracking for insertion points.
Tracks unique insertion point shapes to prioritize new attack surfaces.
"""

import hashlib
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from .extractor import InsertionPoint


@dataclass
class InsertionPointShape:
    """Represents the shape/signature of an insertion point."""
    shape_hash: str
    location_pattern: str
    encoding_layers: tuple
    inferred_type: str
    first_seen: datetime
    count: int = 1


class NoveltyTracker:
    """
    Tracks insertion point novelty to prioritize new attack surfaces.
    """
    
    def __init__(self):
        """Initialize novelty tracker."""
        self.shapes: dict[str, InsertionPointShape] = {}
        self.total_points = 0
        self.novel_points = 0
    
    def compute_shape_hash(self, point: InsertionPoint) -> str:
        """
        Compute a hash representing the shape of an insertion point.
        
        Args:
            point: Insertion point
            
        Returns:
            SHA-256 hash of the shape
        """
        # Normalize location (replace indices with placeholders)
        import re
        normalized_location = re.sub(r'\[\d+\]', '[*]', point.location)
        normalized_location = re.sub(r'segment_\d+', 'segment_*', normalized_location)
        
        # Create shape signature
        encoding_str = ','.join(e.value for e in point.encoding_layers)
        shape_str = f"{normalized_location}|{encoding_str}|{point.inferred_type}"
        
        return hashlib.sha256(shape_str.encode()).hexdigest()[:16]
    
    def is_novel(self, point: InsertionPoint) -> bool:
        """
        Check if an insertion point represents a novel shape.
        
        Args:
            point: Insertion point to check
            
        Returns:
            True if novel, False if seen before
        """
        self.total_points += 1
        shape_hash = self.compute_shape_hash(point)
        
        if shape_hash in self.shapes:
            # Seen before, increment count
            self.shapes[shape_hash].count += 1
            return False
        else:
            # Novel shape
            import re
            location_pattern = re.sub(r'\[\d+\]', '[*]', point.location)
            location_pattern = re.sub(r'segment_\d+', 'segment_*', location_pattern)
            
            self.shapes[shape_hash] = InsertionPointShape(
                shape_hash=shape_hash,
                location_pattern=location_pattern,
                encoding_layers=tuple(point.encoding_layers),
                inferred_type=point.inferred_type,
                first_seen=datetime.utcnow(),
            )
            self.novel_points += 1
            
            logger.info(f"Novel insertion point shape: {location_pattern} [{point.inferred_type}]")
            return True
    
    def get_novelty_score(self, point: InsertionPoint) -> float:
        """
        Get novelty score for an insertion point (0.0 to 1.0).
        
        Args:
            point: Insertion point
            
        Returns:
            Novelty score (1.0 = completely novel, 0.0 = very common)
        """
        shape_hash = self.compute_shape_hash(point)
        
        if shape_hash not in self.shapes:
            return 1.0  # Completely novel
        
        shape = self.shapes[shape_hash]
        
        # Score based on rarity (inverse of count)
        # Use logarithmic scale to avoid extreme values
        import math
        score = 1.0 / (1.0 + math.log10(shape.count + 1))
        
        return score
    
    def get_stats(self) -> dict:
        """Get novelty tracking statistics."""
        return {
            "total_points": self.total_points,
            "novel_shapes": self.novel_points,
            "unique_shapes": len(self.shapes),
            "novelty_rate": self.novel_points / self.total_points if self.total_points > 0 else 0.0,
        }
    
    def get_top_shapes(self, n: int = 10) -> list[InsertionPointShape]:
        """Get top N most common insertion point shapes."""
        return sorted(self.shapes.values(), key=lambda s: s.count, reverse=True)[:n]
    
    def clear(self) -> None:
        """Clear all tracked shapes."""
        self.shapes.clear()
        self.total_points = 0
        self.novel_points = 0
