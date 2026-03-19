"""
Test script for nested insertion point extraction.
"""

import asyncio
from cyberAI.insertion_points import (
    NestedInsertionPointExtractor,
    NoveltyTracker,
    RequestCanonicalizer,
    EncodingType,
)


def test_basic_extraction():
    """Test basic insertion point extraction."""
    print("=== Test: Basic Extraction ===\n")
    
    extractor = NestedInsertionPointExtractor(max_depth=5)
    
    # Test request
    method = "POST"
    url = "https://api.example.com/users/123/profile?format=json"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxMjN9.abc",
        "X-User-Id": "456",
    }
    body = '{"name": "John", "email": "john@example.com", "settings": {"theme": "dark"}}'
    
    points = extractor.extract_from_request(method, url, headers, body)
    
    print(f"Extracted {len(points)} insertion points:\n")
    for point in points:
        print(f"  - {point.get_full_path()}")
        print(f"    Type: {point.inferred_type}, Value: {str(point.value)[:50]}")
        print()
    
    assert len(points) > 0, "Should extract at least one insertion point"
    print("✓ Basic extraction test passed\n")


def test_nested_encoding():
    """Test nested encoding detection."""
    print("=== Test: Nested Encoding ===\n")
    
    extractor = NestedInsertionPointExtractor(max_depth=5)
    
    # Base64-encoded JSON
    import base64
    import json
    
    inner_data = {"user_id": 123, "role": "admin"}
    encoded = base64.b64encode(json.dumps(inner_data).encode()).decode()
    
    method = "POST"
    url = "https://api.example.com/auth"
    headers = {"Content-Type": "application/json"}
    body = json.dumps({"token": encoded})
    
    points = extractor.extract_from_request(method, url, headers, body)
    
    print(f"Extracted {len(points)} insertion points:\n")
    for point in points:
        if point.encoding_layers:
            print(f"  - {point.get_full_path()}")
            print(f"    Depth: {point.depth}, Type: {point.inferred_type}")
            print()
    
    # Should find nested points
    nested_points = [p for p in points if len(p.encoding_layers) > 0]
    assert len(nested_points) > 0, "Should detect nested encoding"
    print("✓ Nested encoding test passed\n")


def test_novelty_tracking():
    """Test novelty tracking."""
    print("=== Test: Novelty Tracking ===\n")
    
    tracker = NoveltyTracker()
    extractor = NestedInsertionPointExtractor()
    
    # Process same request twice
    method = "GET"
    url = "https://api.example.com/users/123"
    headers = {}
    
    points1 = extractor.extract_from_request(method, url, headers)
    points2 = extractor.extract_from_request(method, url.replace("123", "456"), headers)
    
    # Check novelty
    novel_count = 0
    for point in points1:
        if tracker.is_novel(point):
            novel_count += 1
    
    print(f"First request: {novel_count} novel points")
    
    novel_count = 0
    for point in points2:
        if tracker.is_novel(point):
            novel_count += 1
    
    print(f"Second request: {novel_count} novel points (should be 0)")
    
    stats = tracker.get_stats()
    print(f"\nNovelty stats: {stats}")
    
    assert stats["novel_shapes"] > 0, "Should track novel shapes"
    print("\n✓ Novelty tracking test passed\n")


def test_canonicalization():
    """Test request canonicalization."""
    print("=== Test: Canonicalization ===\n")
    
    canonicalizer = RequestCanonicalizer()
    
    # Two requests with different IDs but same structure
    method = "GET"
    url1 = "https://api.example.com/users/123/posts/456?page=1"
    url2 = "https://api.example.com/users/789/posts/012?page=2"
    headers = {"Content-Type": "application/json"}
    
    canonical1 = canonicalizer.canonicalize(method, url1, headers)
    canonical2 = canonicalizer.canonicalize(method, url2, headers)
    
    print(f"URL 1: {url1}")
    print(f"Template: {canonical1.url_template}\n")
    
    print(f"URL 2: {url2}")
    print(f"Template: {canonical2.url_template}\n")
    
    assert canonical1.url_template == canonical2.url_template, "Should have same template"
    print("✓ Canonicalization test passed\n")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*60)
    print("Nested Insertion Point Extraction - Test Suite")
    print("="*60 + "\n")
    
    try:
        test_basic_extraction()
        test_nested_encoding()
        test_novelty_tracking()
        test_canonicalization()
        
        print("="*60)
        print("✓ All tests passed!")
        print("="*60 + "\n")
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
