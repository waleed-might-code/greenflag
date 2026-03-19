#!/usr/bin/env python3
"""
Demo: Nested encoding detection and insertion point extraction.
Shows how the system handles multi-layer encoded payloads.
"""

import base64
import gzip
import json
from urllib.parse import quote

from loguru import logger

from encoding_detector import EncodingDetector, NestedEncodingExtractor
from extractor import InsertionPointExtractor


def demo_encoding_detection():
    """Demonstrate encoding detection capabilities."""
    logger.info("=== Encoding Detection Demo ===\n")
    
    detector = EncodingDetector()
    
    # Test 1: Simple base64
    logger.info("Test 1: Simple base64 encoding")
    data1 = base64.b64encode(b'{"user_id": 123, "role": "admin"}').decode()
    layers1, decoded1 = detector.detect_and_decode(data1)
    logger.info(f"Input: {data1[:50]}...")
    logger.info(f"Detected layers: {layers1}")
    logger.info(f"Decoded: {decoded1}\n")
    
    # Test 2: URL-encoded then base64
    logger.info("Test 2: Nested URL-encode -> base64")
    inner2 = '{"api_key": "secret123", "endpoint": "/admin/users"}'
    url_encoded2 = quote(inner2)
    data2 = base64.b64encode(url_encoded2.encode()).decode()
    layers2, decoded2 = detector.detect_and_decode(data2)
    logger.info(f"Input: {data2[:50]}...")
    logger.info(f"Detected layers: {layers2}")
    logger.info(f"Decoded: {decoded2}\n")
    
    # Test 3: JSON in JSON (escaped)
    logger.info("Test 3: JSON-in-JSON (escaped)")
    inner3 = {"nested": {"user_id": 456, "permissions": ["read", "write"]}}
    data3 = json.dumps(json.dumps(inner3))
    layers3, decoded3 = detector.detect_and_decode(data3)
    logger.info(f"Input: {data3[:50]}...")
    logger.info(f"Detected layers: {layers3}")
    logger.info(f"Decoded: {decoded3}\n")
    
    # Test 4: Triple encoding - gzip -> base64 -> URL-encode
    logger.info("Test 4: Triple encoding (gzip -> base64 -> URL-encode)")
    inner4 = b'{"transaction_id": "txn_789", "amount": 1000, "currency": "USD"}'
    gzipped4 = gzip.compress(inner4)
    b64_4 = base64.b64encode(gzipped4).decode()
    data4 = quote(b64_4)
    layers4, decoded4 = detector.detect_and_decode(data4)
    logger.info(f"Input: {data4[:50]}...")
    logger.info(f"Detected layers: {layers4}")
    logger.info(f"Decoded: {decoded4}\n")
    
    # Test 5: JWT token
    logger.info("Test 5: JWT token")
    # Simplified JWT (header.payload.signature)
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip('=')
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "user123", "role": "admin"}).encode()).decode().rstrip('=')
    signature = "fake_signature_here"
    data5 = f"{header}.{payload}.{signature}"
    layers5, decoded5 = detector.detect_and_decode(data5)
    logger.info(f"Input: {data5[:50]}...")
    logger.info(f"Detected layers: {layers5}")
    logger.info(f"Decoded: {decoded5}\n")
    
    logger.info(f"Detection stats: {detector.get_stats()}\n")


def demo_insertion_point_extraction():
    """Demonstrate insertion point extraction with nested encodings."""
    logger.info("=== Insertion Point Extraction Demo ===\n")
    
    extractor = InsertionPointExtractor(enable_nested_encoding=True, max_encoding_depth=3)
    
    # Test request with nested encoded parameter
    logger.info("Test: POST request with base64-encoded JSON in body")
    
    # Create a payload with nested encoding
    inner_data = {"user_id": 999, "action": "delete", "target": "/api/admin/users/123"}
    encoded_payload = base64.b64encode(json.dumps(inner_data).encode()).decode()
    
    body = json.dumps({
        "token": "abc123",
        "data": encoded_payload,  # This is base64(JSON)
        "timestamp": 1234567890
    })
    
    canonical, insertion_points = extractor.extract_from_request(
        method="POST",
        url="https://api.example.com/v1/execute",
        headers={"Content-Type": "application/json", "Authorization": "Bearer token123"},
        body=body.encode(),
    )
    
    logger.info(f"Canonical request:")
    logger.info(f"  Method: {canonical.method}")
    logger.info(f"  URL template: {canonical.url_template}")
    logger.info(f"  Host: {canonical.host}\n")
    
    logger.info(f"Found {len(insertion_points)} insertion points:")
    for i, ip in enumerate(insertion_points, 1):
        logger.info(f"\n{i}. Location: {ip.location}")
        logger.info(f"   Type: {ip.inferred_type}")
        logger.info(f"   Node type: {ip.node_type.value}")
        logger.info(f"   Encoding layers: {ip.encoding_layers}")
        logger.info(f"   Example value: {ip.example_value}")
        logger.info(f"   Shape hash: {ip.shape_hash}")
        logger.info(f"   Is CSRF: {ip.is_csrf_token}")
    
    logger.info(f"\nExtractor stats: {extractor.get_novelty_stats()}")


def demo_complex_scenario():
    """Demonstrate complex real-world scenario."""
    logger.info("\n=== Complex Real-World Scenario ===\n")
    
    extractor = InsertionPointExtractor(enable_nested_encoding=True)
    
    # Simulate a complex API request with multiple encoding layers
    logger.info("Scenario: E-commerce API with encrypted payment data")
    
    # Payment data (would be encrypted in real scenario, using base64 for demo)
    payment_info = {
        "card_number": "4111111111111111",
        "cvv": "123",
        "expiry": "12/25"
    }
    
    # First layer: JSON
    # Second layer: base64 encode
    # Third layer: URL encode (simulating form submission)
    payment_json = json.dumps(payment_info)
    payment_b64 = base64.b64encode(payment_json.encode()).decode()
    payment_urlenc = quote(payment_b64)
    
    # Full request body
    body = json.dumps({
        "order_id": "ORD-12345",
        "user_id": 789,
        "payment_data": payment_urlenc,  # Triple encoded!
        "shipping_address": {
            "street": "123 Main St",
            "city": "Springfield",
            "zip": "12345"
        }
    })
    
    canonical, insertion_points = extractor.extract_from_request(
        method="POST",
        url="https://api.shop.example.com/v2/orders/checkout?session_id=sess_abc123",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": "key_xyz789",
            "X-User-Token": "usr_token_456"
        },
        body=body.encode(),
    )
    
    logger.info(f"Extracted {len(insertion_points)} insertion points from complex request\n")
    
    # Show only the most interesting ones
    nested_points = [ip for ip in insertion_points if len(ip.encoding_layers) > 0]
    logger.info(f"Insertion points with nested encodings: {len(nested_points)}")
    
    for ip in nested_points:
        logger.info(f"\n  Location: {ip.location}")
        logger.info(f"  Encoding stack: {' -> '.join(ip.encoding_layers)}")
        logger.info(f"  Type: {ip.inferred_type}")
    
    logger.info(f"\nNovelty stats: {extractor.get_novelty_stats()}")


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), colorize=True, format="<level>{message}</level>")
    
    demo_encoding_detection()
    demo_insertion_point_extraction()
    demo_complex_scenario()
    
    logger.success("\n✓ All demos completed successfully!")
