"""
Integration of insertion point extraction with crawl pipeline.
"""

from pathlib import Path
from typing import Any
from loguru import logger

from .extractor import InsertionPointExtractor
from .novelty import NoveltyTracker
from .canonicalizer import RequestCanonicalizer


class InsertionPointPipeline:
    """
    Pipeline for extracting and tracking insertion points from crawled requests.
    """
    
    def __init__(self, max_depth: int = 5):
        """
        Initialize pipeline.
        
        Args:
            max_depth: Maximum nesting depth for extraction
        """
        self.extractor = InsertionPointExtractor(max_depth=max_depth)
        self.novelty_tracker = NoveltyTracker()
        self.canonicalizer = RequestCanonicalizer()
        
        self.total_requests = 0
        self.total_points = 0
        self.novel_requests = 0
    
    def process_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: str = None,
    ) -> dict[str, Any]:
        """
        Process a request and extract insertion points.
        
        Args:
            method: HTTP method
            url: Request URL
            headers: Request headers
            body: Request body (optional)
            
        Returns:
            Processing results with insertion points and statistics
        """
        self.total_requests += 1
        
        # Canonicalize request
        canonical = self.canonicalizer.canonicalize(method, url, headers, body)
        is_duplicate = self.canonicalizer.is_duplicate(canonical)
        
        if not is_duplicate:
            self.novel_requests += 1
        
        # Extract insertion points
        points = self.extractor.extract_from_request(method, url, headers, body)
        self.total_points += len(points)
        
        # Track novelty
        novel_points = []
        for point in points:
            if self.novelty_tracker.is_novel(point):
                novel_points.append(point)
        
        logger.info(
            f"Processed {method} {url}: "
            f"{len(points)} points ({len(novel_points)} novel), "
            f"duplicate={is_duplicate}"
        )
        
        return {
            "canonical": canonical,
            "is_duplicate": is_duplicate,
            "insertion_points": points,
            "novel_points": novel_points,
            "stats": {
                "total_points": len(points),
                "novel_points": len(novel_points),
                "novelty_score": len(novel_points) / len(points) if points else 0.0,
            }
        }
    
    def get_stats(self) -> dict[str, Any]:
        """Get pipeline statistics."""
        novelty_stats = self.novelty_tracker.get_stats()
        canonicalizer_stats = self.canonicalizer.get_stats()
        
        return {
            "total_requests": self.total_requests,
            "novel_requests": self.novel_requests,
            "unique_requests": canonicalizer_stats["unique_requests"],
            "total_insertion_points": self.total_points,
            "novelty": novelty_stats,
        }
    
    def get_top_shapes(self, n: int = 10):
        """Get top N most common insertion point shapes."""
        return self.novelty_tracker.get_top_shapes(n)
    
    def clear(self) -> None:
        """Clear all tracking data."""
        self.novelty_tracker.clear()
        self.canonicalizer.clear()
        self.total_requests = 0
        self.total_points = 0
        self.novel_requests = 0


async def integrate_with_crawler(
    crawl_results: dict[str, Any],
    output_dir: Path,
    max_depth: int = 5,
) -> dict[str, Any]:
    """
    Integrate insertion point extraction with crawler results.
    
    Args:
        crawl_results: Results from state-flow crawler
        output_dir: Output directory
        max_depth: Maximum nesting depth
        
    Returns:
        Extraction results with insertion points
    """
    logger.info("Integrating insertion point extraction with crawler")
    
    pipeline = InsertionPointPipeline(max_depth=max_depth)
    
    # Process each discovered state
    # In real implementation, this would process actual HTTP requests
    # For now, we'll create a placeholder structure
    
    results = {
        "pipeline_stats": pipeline.get_stats(),
        "top_shapes": [
            {
                "location_pattern": shape.location_pattern,
                "encoding_layers": [e.value for e in shape.encoding_layers],
                "inferred_type": shape.inferred_type,
                "count": shape.count,
            }
            for shape in pipeline.get_top_shapes(10)
        ],
    }
    
    logger.info(f"Insertion point extraction complete: {pipeline.get_stats()}")
    
    return results
