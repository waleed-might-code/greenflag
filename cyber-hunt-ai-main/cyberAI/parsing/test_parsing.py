"""
Integration Tests for Parsing Pipeline

Tests the complete flow from request to insertion points with encoding detection.
"""

import json
import base64
import pytest
from cyberAI.parsing import (
    ParsingPipeline,
    RequestCanonicalizer,
    InsertionPointExtractor,
    EncodingDetector,
    NoveltyTracker
)


class TestEncodingDetector:
    """Test encoding detection and decoding."""
    
    def test_base64_detection(self):
        detector = EncodingDetector()
        value = base64.b64encode(b"Hello World").decode('ascii')
        layers = detector.detect_and_decode(value)
        
        assert len(layers) > 0
        assert layers[0].encoding_type == 'base64'
        assert layers[0].decoded_value == "Hello World"
    
    def test_json_detection(self):
        detector = EncodingDetector()
        value = '{"key": "value", "number": 123}'
        layers = detector.detect_and_decode(value)
        
        assert len(layers) > 0
        assert layers[0].encoding_type == 'json'
        assert layers[0].decoded_value == {"key": "value", "number": 123}
    
    def test_nested_base64_json(self):
        detector = EncodingDetector()
        inner = json.dumps({"user_id": 999, "action": "delete"})
        outer = base64.b64encode(inner.encode('utf-8')).decode('ascii')
        
        layers = detector.detect_and_decode(outer)
        
        assert len(layers) >= 2
        assert layers[0].encoding_type == 'base64'
        assert layers[1].encoding_type == 'json'
    
    def test_url_encoding(self):
        detector = EncodingDetector()
        value = "hello%20world%21"
        layers = detector.detect_and_decode(value)
        
        assert len(layers) > 0
        assert layers[0].encoding_type == 'url'
        assert layers[0].decoded_value == "hello world!"
    
    def test_jwt_detection(self):
        detector = EncodingDetector()
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip('=')
        payload = base64.urlsafe_b64encode(json.dumps({"user_id": 123}).encode()).decode().rstrip('=')
        jwt = f"{header}.{payload}.signature"
        
        layers = detector.detect_and_decode(jwt)
        
        assert len(layers) > 0
        assert layers[0].encoding_type == 'jwt'
        assert 'header' in layers[0].decoded_value
        assert 'payload' in layers[0].decoded_value


class TestRequestCanonicalizer:
    """Test request canonicalization."""
    
    def test_basic_get_request(self):
        canonicalizer = RequestCanonicalizer()
        result = canonicalizer.canonicalize(
            method="GET",
            url="https://api.example.com/users/123?sort=date",
            headers={"Authorization": "Bearer token123"}
        )
        
        assert result.method == "GET"
        assert result.host == "api.example.com"
        assert "{segment_0}" in result.url_template  # /users/{id}
        assert len(result.query_params) > 0
        assert result.query_params[0].name == "sort"
    
    def test_json_body_parsing(self):
        canonicalizer = RequestCanonicalizer()
        body = json.dumps({"user_id": 123, "name": "Alice"}).encode('utf-8')
        
        result = canonicalizer.canonicalize(
            method="POST",
            url="https://api.example.com/users",
            headers={"Content-Type": "application/json"},
            body=body
        )
        
        assert result.body_ast is not None
        assert len(result.body_params) == 2
        assert any(p.name == "user_id" for p in result.body_params)
    
    def test_nested_json_parsing(self):
        canonicalizer = RequestCanonicalizer()
        body = json.dumps({
            "user": {
                "id": 123,
                "profile": {
                    "email": "test@example.com"
                }
            }
        }).encode('utf-8')
        
        result = canonicalizer.canonicalize(
            method="POST",
            url="https://api.example.com/users",
            headers={"Content-Type": "application/json"},
            body=body
        )
        
        # Should extract nested parameters
        assert len(result.body_params) >= 2
        paths = [p.parent_path for p in result.body_params]
        assert any("user.id" in p for p in paths)
        assert any("email" in p for p in paths)
    
    def test_shape_hash_consistency(self):
        canonicalizer = RequestCanonicalizer()
        
        # Two similar requests should have same shape
        result1 = canonicalizer.canonicalize(
            "GET", "https://api.example.com/users/123", {}
        )
        result2 = canonicalizer.canonicalize(
            "GET", "https://api.example.com/users/456", {}
        )
        
        assert result1.shape_hash == result2.shape_hash


class TestInsertionPointExtractor:
    """Test insertion point extraction."""
    
    def test_basic_extraction(self):
        canonicalizer = RequestCanonicalizer()
        extractor = InsertionPointExtractor()
        
        canonical = canonicalizer.canonicalize(
            method="GET",
            url="https://api.example.com/users/123?search=test",
            headers={"X-User-Id": "999"}
        )
        
        insertion_points = extractor.extract(canonical)
        
        assert len(insertion_points) > 0
        # Should have path segment, query param, and header
        locations = [ip.location for ip in insertion_points]
        assert any("path" in loc for loc in locations)
        assert any("query" in loc for loc in locations)
        assert any("header" in loc for loc in locations)
    
    def test_security_relevance_detection(self):
        canonicalizer = RequestCanonicalizer()
        extractor = InsertionPointExtractor()
        
        body = json.dumps({"user_id": 123, "role": "admin", "data": "test"}).encode('utf-8')
        canonical = canonicalizer.canonicalize(
            method="POST",
            url="https://api.example.com/update",
            headers={"Content-Type": "application/json"},
            body=body
        )
        
        insertion_points = extractor.extract(canonical)
        
        # user_id and role should be marked as security-relevant
        security_relevant = [ip for ip in insertion_points if ip.is_security_relevant]
        assert len(security_relevant) > 0
        names = [ip.parameter_name for ip in security_relevant]
        assert "user_id" in names or "role" in names
    
    def test_nested_encoding_detection(self):
        canonicalizer = RequestCanonicalizer()
        extractor = InsertionPointExtractor()
        
        # Create nested payload
        inner = json.dumps({"secret": "data"})
        outer = base64.b64encode(inner.encode('utf-8')).decode('ascii')
        body = json.dumps({"payload": outer}).encode('utf-8')
        
        canonical = canonicalizer.canonicalize(
            method="POST",
            url="https://api.example.com/execute",
            headers={"Content-Type": "application/json"},
            body=body
        )
        
        insertion_points = extractor.extract(canonical)
        
        # Should detect encoding layers
        encoded_points = [ip for ip in insertion_points if len(ip.encoding_layers) > 0]
        assert len(encoded_points) > 0
    
    def test_prioritization(self):
        canonicalizer = RequestCanonicalizer()
        extractor = InsertionPointExtractor()
        
        body = json.dumps({
            "user_id": 123,  # Security-relevant
            "role": "admin",  # Security-relevant
            "comment": "test"  # Not security-relevant
        }).encode('utf-8')
        
        canonical = canonicalizer.canonicalize(
            method="POST",
            url="https://api.example.com/update",
            headers={"Content-Type": "application/json"},
            body=body
        )
        
        insertion_points = extractor.extract(canonical)
        prioritized = extractor.prioritize(insertion_points)
        
        # Security-relevant should be first
        assert prioritized[0].is_security_relevant


class TestNoveltyTracker:
    """Test novelty tracking."""
    
    def test_novelty_detection(self):
        tracker = NoveltyTracker(storage_backend="memory")
        
        shape1 = "shape_hash_1"
        shape2 = "shape_hash_2"
        
        # First time should be novel
        assert tracker.is_novel(shape1) == True
        # Second time should not be novel
        assert tracker.is_novel(shape1) == False
        # Different shape should be novel
        assert tracker.is_novel(shape2) == True
    
    def test_statistics(self):
        tracker = NoveltyTracker(storage_backend="memory")
        
        tracker.is_novel("shape1")
        tracker.is_novel("shape1")  # Duplicate
        tracker.is_novel("shape2")
        
        stats = tracker.get_coverage_stats()
        
        assert stats['total_checked'] == 3
        assert stats['novel_count'] == 2
        assert stats['duplicate_count'] == 1


class TestParsingPipeline:
    """Test complete parsing pipeline."""
    
    def test_end_to_end_processing(self):
        pipeline = ParsingPipeline(storage_backend="memory")
        
        result = pipeline.process_request(
            method="POST",
            url="https://api.example.com/users/123/posts?sort=date",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer token123"
            },
            body=json.dumps({
                "title": "Test Post",
                "user_id": 123,
                "tags": ["test"]
            }).encode('utf-8')
        )
        
        assert 'canonical_request' in result
        assert 'insertion_points' in result
        assert 'novel_insertion_points' in result
        assert 'stats' in result
        
        assert result['stats']['total_insertion_points'] > 0
    
    def test_batch_processing(self):
        pipeline = ParsingPipeline(storage_backend="memory")
        
        requests = [
            {"method": "GET", "url": "https://api.example.com/users/1", "headers": {}},
            {"method": "GET", "url": "https://api.example.com/users/2", "headers": {}},
            {"method": "POST", "url": "https://api.example.com/users", "headers": {"Content-Type": "application/json"}, "body": json.dumps({"name": "Alice"}).encode('utf-8')}
        ]
        
        results = pipeline.process_batch(requests)
        
        assert len(results) == 3
        assert all('canonical_request' in r for r in results)
    
    def test_payload_generation(self):
        pipeline = ParsingPipeline(storage_backend="memory")
        
        # Create request with nested encoding
        inner = json.dumps({"data": "value"})
        outer = base64.b64encode(inner.encode('utf-8')).decode('ascii')
        
        result = pipeline.process_request(
            method="POST",
            url="https://api.example.com/execute",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"payload": outer}).encode('utf-8')
        )
        
        # Find insertion point with encoding
        encoded_ip = None
        for ip in result['insertion_points']:
            if len(ip.encoding_layers) > 0:
                encoded_ip = ip
                break
        
        if encoded_ip:
            payloads = pipeline.generate_test_payloads(encoded_ip, ["test1", "test2"])
            assert len(payloads) == 2
            # Payloads should be encoded
            assert payloads[0] != "test1"  # Should be encoded


def run_tests():
    """Run all tests."""
    print("Running parsing pipeline tests...\n")
    
    test_classes = [
        TestEncodingDetector,
        TestRequestCanonicalizer,
        TestInsertionPointExtractor,
        TestNoveltyTracker,
        TestParsingPipeline
    ]
    
    total_tests = 0
    passed_tests = 0
    
    for test_class in test_classes:
        print(f"Testing {test_class.__name__}...")
        instance = test_class()
        
        for method_name in dir(instance):
            if method_name.startswith('test_'):
                total_tests += 1
                try:
                    method = getattr(instance, method_name)
                    method()
                    print(f"  ✓ {method_name}")
                    passed_tests += 1
                except Exception as e:
                    print(f"  ✗ {method_name}: {e}")
        
        print()
    
    print(f"Results: {passed_tests}/{total_tests} tests passed")
    return passed_tests == total_tests


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
