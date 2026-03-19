"""
Demo: Nested Insertion Points and Encoding Layers

This demo shows how the parsing pipeline extracts insertion points from
complex requests with nested encoding layers.
"""

import json
import base64
from cyberAI.parsing import (
    ParsingPipeline,
    RequestCanonicalizer,
    InsertionPointExtractor,
    EncodingDetector
)


def demo_basic_request():
    """Demo 1: Basic request with query and body parameters."""
    print("=" * 80)
    print("DEMO 1: Basic Request Parsing")
    print("=" * 80)
    
    pipeline = ParsingPipeline()
    
    # Simple API request
    result = pipeline.process_request(
        method="POST",
        url="https://api.example.com/users/12345/posts?sort=date&limit=10",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer abc123token",
            "X-User-Role": "admin"
        },
        body=json.dumps({
            "title": "My Post",
            "content": "Hello world",
            "user_id": 12345,
            "tags": ["security", "testing"]
        }).encode('utf-8')
    )
    
    print(f"\n✓ Processed request")
    print(f"  - Request ID: {result['canonical_request'].request_id}")
    print(f"  - URL Template: {result['canonical_request'].url_template}")
    print(f"  - Shape Hash: {result['canonical_request'].shape_hash}")
    print(f"\n✓ Found {result['stats']['total_insertion_points']} insertion points:")
    
    for ip in result['insertion_points'][:5]:  # Show first 5
        print(f"  - {ip.parent_path}: {ip.inferred_type} (security: {ip.is_security_relevant})")
    
    print(f"\n✓ Novel insertion points: {result['stats']['novel_count']}")
    print(f"✓ Security-relevant: {result['stats']['security_relevant_count']}")


def demo_nested_encoding():
    """Demo 2: Request with nested base64(JSON) encoding."""
    print("\n" + "=" * 80)
    print("DEMO 2: Nested Encoding Detection")
    print("=" * 80)
    
    pipeline = ParsingPipeline()
    
    # Create nested payload: base64(JSON(data))
    inner_data = {"user_id": 999, "action": "delete", "target": "admin"}
    json_encoded = json.dumps(inner_data)
    base64_encoded = base64.b64encode(json_encoded.encode('utf-8')).decode('ascii')
    
    print(f"\n✓ Original data: {inner_data}")
    print(f"✓ After JSON encoding: {json_encoded}")
    print(f"✓ After base64 encoding: {base64_encoded[:50]}...")
    
    # Send request with nested encoding
    result = pipeline.process_request(
        method="POST",
        url="https://api.example.com/execute",
        headers={"Content-Type": "application/json"},
        body=json.dumps({
            "command": "process",
            "data": base64_encoded  # Nested: base64(JSON)
        }).encode('utf-8')
    )
    
    print(f"\n✓ Insertion points with encoding layers:")
    for ip in result['insertion_points']:
        if ip.encoding_layers:
            print(f"  - {ip.parent_path}")
            print(f"    Type: {ip.inferred_type}")
            print(f"    Encoding layers: {' -> '.join(ip.encoding_layers)}")
            print(f"    Original value: {str(ip.original_value)[:50]}...")
    
    print(f"\n✓ Nested encodings detected: {result['stats']['nested_encoding_count']}")


def demo_encoding_detector():
    """Demo 3: Encoding detector capabilities."""
    print("\n" + "=" * 80)
    print("DEMO 3: Encoding Detector Capabilities")
    print("=" * 80)
    
    detector = EncodingDetector()
    
    # Test various encodings
    test_cases = [
        ("Base64", base64.b64encode(b"Hello World").decode('ascii')),
        ("URL Encoded", "hello%20world%21%40%23"),
        ("Hex", "48656c6c6f20576f726c64"),
        ("JSON", '{"key": "value", "number": 123}'),
    ]
    
    for name, value in test_cases:
        print(f"\n✓ Testing {name}: {value[:50]}...")
        layers = detector.detect_and_decode(value)
        
        if layers:
            print(f"  Detected {len(layers)} layer(s):")
            for i, layer in enumerate(layers, 1):
                print(f"    {i}. {layer.encoding_type} (confidence: {layer.confidence:.2f})")
                print(f"       Decoded: {str(layer.decoded_value)[:50]}...")
        else:
            print(f"  No encoding detected")


def demo_jwt_token():
    """Demo 4: JWT token parsing."""
    print("\n" + "=" * 80)
    print("DEMO 4: JWT Token Parsing")
    print("=" * 80)
    
    # Create a fake JWT token
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip('=')
    payload = base64.urlsafe_b64encode(json.dumps({"user_id": 123, "role": "admin", "exp": 1234567890}).encode()).decode().rstrip('=')
    signature = "fake_signature_here"
    jwt_token = f"{header}.{payload}.{signature}"
    
    print(f"\n✓ JWT Token: {jwt_token[:60]}...")
    
    detector = EncodingDetector()
    layers = detector.detect_and_decode(jwt_token)
    
    if layers:
        print(f"\n✓ Detected JWT token:")
        jwt_data = layers[0].decoded_value
        print(f"  Header: {json.dumps(jwt_data['header'], indent=2)}")
        print(f"  Payload: {json.dumps(jwt_data['payload'], indent=2)}")


def demo_payload_generation():
    """Demo 5: Generate payloads with proper encoding."""
    print("\n" + "=" * 80)
    print("DEMO 5: Payload Generation with Encoding")
    print("=" * 80)
    
    pipeline = ParsingPipeline()
    
    # Create request with nested encoding
    inner_data = {"user_id": 999}
    json_encoded = json.dumps(inner_data)
    base64_encoded = base64.b64encode(json_encoded.encode('utf-8')).decode('ascii')
    
    result = pipeline.process_request(
        method="POST",
        url="https://api.example.com/execute",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"data": base64_encoded}).encode('utf-8')
    )
    
    # Find insertion point with encoding
    encoded_ip = None
    for ip in result['insertion_points']:
        if ip.encoding_layers:
            encoded_ip = ip
            break
    
    if encoded_ip:
        print(f"\n✓ Found insertion point with encoding: {encoded_ip.parent_path}")
        print(f"  Encoding layers: {encoded_ip.encoding_layers}")
        
        # Generate test payloads
        test_payloads = ["' OR 1=1--", "<script>alert(1)</script>", "../../etc/passwd"]
        
        print(f"\n✓ Generating encoded payloads:")
        for payload in test_payloads:
            encoded = encoded_ip.get_payload_with_encoding(payload)
            print(f"  - Original: {payload}")
            print(f"    Encoded: {encoded[:60]}...")


def demo_coverage_analysis():
    """Demo 6: Coverage analysis across multiple requests."""
    print("\n" + "=" * 80)
    print("DEMO 6: Coverage Analysis")
    print("=" * 80)
    
    pipeline = ParsingPipeline()
    
    # Simulate multiple requests
    requests = [
        {
            "method": "GET",
            "url": "https://api.example.com/users/123",
            "headers": {"Authorization": "Bearer token1"}
        },
        {
            "method": "GET",
            "url": "https://api.example.com/users/456",
            "headers": {"Authorization": "Bearer token2"}
        },
        {
            "method": "POST",
            "url": "https://api.example.com/users",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"name": "Alice", "email": "alice@example.com"}).encode('utf-8')
        },
        {
            "method": "PUT",
            "url": "https://api.example.com/users/789",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"name": "Bob"}).encode('utf-8')
        }
    ]
    
    results = pipeline.process_batch(requests)
    
    print(f"\n✓ Processed {len(requests)} requests")
    
    # Get statistics
    stats = pipeline.get_statistics()
    print(f"\n✓ Pipeline Statistics:")
    print(f"  - Total requests: {stats['requests_processed']}")
    print(f"  - Total insertion points: {stats['insertion_points_found']}")
    print(f"  - Novel insertion points: {stats['novel_insertion_points']}")
    print(f"  - Avg insertion points per request: {stats['avg_insertion_points_per_request']:.2f}")
    print(f"  - Novelty rate: {stats['novelty_rate']:.2%}")
    
    # Analyze coverage
    canonical_requests = [r['canonical_request'] for r in results]
    coverage = pipeline.analyze_endpoint_coverage(canonical_requests)
    
    print(f"\n✓ Coverage Analysis:")
    print(f"  - Unique endpoints: {coverage['unique_endpoints']}")
    print(f"  - Total unique parameters: {coverage['total_parameters']}")
    print(f"\n  Endpoints:")
    for endpoint, data in coverage['endpoints'].items():
        print(f"    - {endpoint}")
        print(f"      Requests: {data['count']}, Parameters: {data['param_count']}")


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 15 + "NESTED INSERTION POINTS & ENCODING LAYERS DEMO" + " " * 16 + "║")
    print("╚" + "=" * 78 + "╝")
    
    try:
        demo_basic_request()
        demo_nested_encoding()
        demo_encoding_detector()
        demo_jwt_token()
        demo_payload_generation()
        demo_coverage_analysis()
        
        print("\n" + "=" * 80)
        print("✓ All demos completed successfully!")
        print("=" * 80 + "\n")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
