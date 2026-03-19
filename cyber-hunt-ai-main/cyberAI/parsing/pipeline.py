"""
Parsing Pipeline - Orchestrates the complete request analysis flow

This module ties together canonicalization, encoding detection, insertion point
extraction, and novelty tracking into a unified pipeline.
"""

import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import asdict
from .request_canonicalizer import RequestCanonicalizer, CanonicalRequest
from .insertion_point_extractor import InsertionPointExtractor, InsertionPoint
from .encoding_detectors import EncodingDetector
from .novelty_tracker import NoveltyTracker


class ParsingPipeline:
    """
    Complete parsing pipeline for HTTP requests.
    
    Flow:
    1. Canonicalize request (extract structure)
    2. Extract insertion points (including nested)
    3. Detect encoding layers
    4. Track novelty
    5. Prioritize for testing
    """
    
    def __init__(self, storage_backend: str = "memory", redis_client=None):
        """
        Initialize the parsing pipeline.
        
        Args:
            storage_backend: "memory" or "redis" for novelty tracking
            redis_client: Redis client (required if backend is "redis")
        """
        self.canonicalizer = RequestCanonicalizer()
        self.extractor = InsertionPointExtractor()
        self.encoding_detector = EncodingDetector()
        self.novelty_tracker = NoveltyTracker(storage_backend, redis_client)
        
        # Statistics
        self.stats = {
            'requests_processed': 0,
            'insertion_points_found': 0,
            'novel_insertion_points': 0,
            'nested_encodings_detected': 0
        }
    
    def process_request(self, method: str, url: str, headers: Dict[str, str],
                       body: Optional[bytes] = None) -> Dict[str, Any]:
        """
        Process a single HTTP request through the complete pipeline.
        
        Args:
            method: HTTP method
            url: Full URL
            headers: Request headers
            body: Request body bytes
        
        Returns:
            Dictionary with canonical request, insertion points, and metadata
        """
        self.stats['requests_processed'] += 1
        
        # Step 1: Canonicalize
        canonical = self.canonicalizer.canonicalize(method, url, headers, body)
        
        # Step 2: Extract insertion points
        insertion_points = self.extractor.extract(canonical)
        self.stats['insertion_points_found'] += len(insertion_points)
        
        # Step 3: Filter by novelty
        novel_points = []
        for ip in insertion_points:
            shape = self.novelty_tracker.compute_insertion_point_shape(
                ip.location, ip.parameter_name, ip.inferred_type, ip.encoding_layers
            )
            
            if self.novelty_tracker.is_novel(shape, {
                'location': ip.location,
                'parameter': ip.parameter_name,
                'type': ip.inferred_type
            }):
                novel_points.append(ip)
                self.stats['novel_insertion_points'] += 1
            
            # Track nested encodings
            if len(ip.encoding_layers) > 0:
                self.stats['nested_encodings_detected'] += 1
        
        # Step 4: Prioritize
        prioritized_points = self.extractor.prioritize(insertion_points)
        
        return {
            'canonical_request': canonical,
            'insertion_points': insertion_points,
            'novel_insertion_points': novel_points,
            'prioritized_insertion_points': prioritized_points,
            'stats': {
                'total_insertion_points': len(insertion_points),
                'novel_count': len(novel_points),
                'security_relevant_count': sum(1 for ip in insertion_points if ip.is_security_relevant),
                'nested_encoding_count': sum(1 for ip in insertion_points if len(ip.encoding_layers) > 0)
            }
        }
    
    def process_batch(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a batch of requests.
        
        Args:
            requests: List of dicts with keys: method, url, headers, body
        
        Returns:
            List of processing results
        """
        results = []
        
        for req in requests:
            result = self.process_request(
                req['method'],
                req['url'],
                req.get('headers', {}),
                req.get('body')
            )
            results.append(result)
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        novelty_stats = self.novelty_tracker.get_coverage_stats()
        
        return {
            **self.stats,
            **novelty_stats,
            'avg_insertion_points_per_request': (
                self.stats['insertion_points_found'] / max(self.stats['requests_processed'], 1)
            ),
            'novelty_rate': (
                self.stats['novel_insertion_points'] / max(self.stats['insertion_points_found'], 1)
            )
        }
    
    def export_insertion_points(self, insertion_points: List[InsertionPoint]) -> List[Dict]:
        """Export insertion points to JSON-serializable format."""
        return [
            {
                'insertion_id': ip.insertion_id,
                'request_id': ip.request_id,
                'location': ip.location,
                'parameter_name': ip.parameter_name,
                'original_value': str(ip.original_value),
                'inferred_type': ip.inferred_type,
                'encoding_layers': ip.encoding_layers,
                'parent_path': ip.parent_path,
                'is_security_relevant': ip.is_security_relevant,
                'metadata': ip.metadata
            }
            for ip in insertion_points
        ]
    
    def generate_test_payloads(self, insertion_point: InsertionPoint,
                              payloads: List[str]) -> List[str]:
        """
        Generate test payloads with proper encoding for an insertion point.
        
        Args:
            insertion_point: The insertion point to test
            payloads: List of raw payloads
        
        Returns:
            List of properly encoded payloads
        """
        encoded_payloads = []
        
        for payload in payloads:
            if insertion_point.encoding_layers:
                # Apply encoding layers
                encoded = insertion_point.get_payload_with_encoding(payload)
                encoded_payloads.append(encoded)
            else:
                # No encoding needed
                encoded_payloads.append(payload)
        
        return encoded_payloads
    
    def analyze_endpoint_coverage(self, canonical_requests: List[CanonicalRequest]) -> Dict:
        """
        Analyze coverage across multiple requests.
        
        Returns statistics about endpoint diversity and parameter coverage.
        """
        endpoints = {}
        all_params = set()
        
        for req in canonical_requests:
            endpoint_key = f"{req.method}:{req.url_template}"
            
            if endpoint_key not in endpoints:
                endpoints[endpoint_key] = {
                    'count': 0,
                    'params': set(),
                    'shape_hash': req.shape_hash
                }
            
            endpoints[endpoint_key]['count'] += 1
            
            # Collect parameter names
            for param in req.query_params + req.body_params:
                param_name = param.name
                endpoints[endpoint_key]['params'].add(param_name)
                all_params.add(param_name)
        
        return {
            'unique_endpoints': len(endpoints),
            'total_parameters': len(all_params),
            'endpoints': {
                k: {
                    'count': v['count'],
                    'params': list(v['params']),
                    'param_count': len(v['params'])
                }
                for k, v in endpoints.items()
            }
        }
