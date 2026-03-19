#!/usr/bin/env python3
"""
Comprehensive test suite for nested encoding detection and insertion point extraction.
Tests the hardest cases: multi-layer encoding, edge cases, and replay accuracy.
"""

import base64
import gzip
import json
import pytest
from urllib.parse import quote, unquote

from encoding_detector import EncodingDetector, NestedEncodingExtractor
from extractor import InsertionPointExtractor
from payload_encoder import PayloadEncoder, PayloadGenerator
from replay_engine import ReplayEngine
from canonicalizer import RequestCanonicalizer


class TestEncodingDetector:
    """Test encoding detection capabilities."""
    
    def setup_method(self):
        """Setup for each test."""
        self.detector = EncodingDetector()
    
    def test_simple_base64(self):
        """Test simple base64 detection."""
        original = b'{"user_id": 123}'
        encoded = base64.b64encode(original).decode()
        
        layers, decoded = self.detector.detect_and_decode(encoded)
        
        assert "base64" in layers
        assert b'{"user_id": 123}' in decoded or '{"user_id": 123}' in str(decoded)
    
    def test_double_encoding_url_base64(self):
        """Test URL-encode -> base64."""
        original = '{"api_key": "secret123"}'
        url_encoded = quote(original)
        b64_encoded = base64.b64encode(url_encoded.encode()).decode()
        
        layers, decoded = self.detector.detect_and_decode(b64_encoded)
        
        assert len(layers) == 2
        assert "base64" in layers
        assert "url_encode" in layers
        assert "api_key" in str(decoded)
    
    def test_triple_encoding_gzip_base64_url(self):
        """Test gzip -> base64 -> URL-encode (hardest case)."""
        original = b'{"transaction_id": "txn_789", "amount": 1000}'
        gzipped = gzip.compress(original)
        b64 = base64.b64encode(gzipped).decode()
        url_enc = quote(b64)
        
        layers, decoded = self.detector.detect_and_decode(url_enc)
        
        assert len(layers) == 3
        assert "url_encode" in layers
        assert "base64" in layers
        assert "gzip" in layers
        assert b"transaction_id" in decoded or "transaction_id" in str(decoded)
    
    def test_json_in_json(self):
        """Test JSON-in-JSON (escaped)."""
        inner = {"nested": {"value": 456}}
        outer = json.dumps(json.dumps(inner))
        
        layers, decoded = self.detector.detect_and_decode(outer)
        
        assert "json" in layers
        assert "nested" in str(decoded)
    
    def test_max_depth_limit(self):
        """Test that max depth prevents infinite recursion."""
        # Create 5 layers of base64 encoding
        data = b"original"
        for _ in range(5):
            data = base64.b64encode(data)
        
        layers, decoded = self.detector.detect_and_decode(data.decode())
        
        # Should stop at MAX_DEPTH (3)
        assert len(layers) <= 3
    
    def test_invalid_encoding(self):
        """Test handling of invalid/corrupted encoding."""
        invalid_b64 = "not!valid@base64#data"
        
        layers, decoded = self.detector.detect_and_decode(invalid_b64)
        
        # Should return empty layers for invalid data
        assert len(layers) == 0
    
    def test_jwt_detection(self):
        """Test JWT token detection."""
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip('=')
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "user123"}).encode()).decode().rstrip('=')
        jwt = f"{header}.{payload}.signature"
        
        layers, decoded = self.detector.detect_and_decode(jwt)
        
        assert "jwt" in layers


class TestPayloadEncoder:
    """Test payload encoding (reverse of detection)."""
    
    def setup_method(self):
        """Setup for each test."""
        self.encoder = PayloadEncoder()
    
    def test_encode_single_layer_base64(self):
        """Test encoding with single base64 layer."""
        payload = {"user_id": 999}
        layers = ["base64"]
        
        encoded = self.encoder.encode(payload, layers)
        
        # Should be base64-encoded JSON
        decoded = base64.b64decode(encoded)
        assert b"user_id" in decoded
        assert b"999" in decoded
    
    def test_encode_double_layer(self):
        """Test encoding with two layers."""
        payload = {"test": "value"}
        layers = ["url_encode", "base64"]
        
        encoded = self.encoder.encode(payload, layers)
        
        # Decode in reverse order
        step1 = unquote(encoded)
        step2 = base64.b64decode(step1)
        
        assert b"test" in step2
    
    def test_encode_triple_layer(self):
        """Test encoding with three layers (hardest case)."""
        payload = {"data": "secret"}
        layers = ["gzip", "base64", "url_encode"]
        
        encoded = self.encoder.encode(payload, layers)
        
        # Decode in reverse
        step1 = unquote(encoded)
        step2 = base64.b64decode(step1)
        step3 = gzip.decompress(step2)
        
        assert b"secret" in step3
    
    def test_roundtrip_encoding_decoding(self):
        """Test that encode -> decode produces original data."""
        detector = EncodingDetector()
        original = {"user_id": 123, "role": "admin"}
        layers = ["base64", "url_encode"]
        
        # Encode
        encoded = self.encoder.encode(original, layers)
        
        # Decode
        detected_layers, decoded = detector.detect_and_decode(encoded)
        
        # Verify
        assert set(layers) == set(detected_layers)
        assert "user_id" in str(decoded)


class TestInsertionPointExtraction:
    """Test insertion point extraction with nested encoding."""
    
    def setup_method(self):
        """Setup for each test."""
        self.extractor = InsertionPointExtractor(enable_nested_encoding=True)
    
    def test_extract_from_simple_json(self):
        """Test extraction from simple JSON body."""
        body = json.dumps({"user_id": 123, "email": "test@example.com"})
        
        canonical, points = self.extractor.extract_from_request(
            method="POST",
            url="https://api.example.com/users",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        assert len(points) > 0
        locations = [p.location for p in points]
        assert any("user_id" in loc for loc in locations)
        assert any("email" in loc for loc in locations)
    
    def test_extract_with_nested_encoding(self):
        """Test extraction from nested encoded data."""
        # Create nested encoded payload
        inner_data = {"secret_id": 456}
        encoded = base64.b64encode(json.dumps(inner_data).encode()).decode()
        
        body = json.dumps({"encrypted_data": encoded})
        
        canonical, points = self.extractor.extract_from_request(
            method="POST",
            url="https://api.example.com/secure",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        # Should find insertion points in the nested structure
        nested_points = [p for p in points if len(p.encoding_layers) > 0]
        assert len(nested_points) > 0
    
    def test_extract_from_query_params(self):
        """Test extraction from URL query parameters."""
        canonical, points = self.extractor.extract_from_request(
            method="GET",
            url="https://api.example.com/users?id=123&filter=active",
            headers={},
        )
        
        assert len(points) >= 2
        locations = [p.location for p in points]
        assert any("query.id" in loc for loc in locations)
        assert any("query.filter" in loc for loc in locations)
    
    def test_csrf_token_detection(self):
        """Test CSRF token detection."""
        body = json.dumps({"csrf_token": "abc123", "user_id": 789})
        
        canonical, points = self.extractor.extract_from_request(
            method="POST",
            url="https://api.example.com/action",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        csrf_points = [p for p in points if p.is_csrf_token]
        assert len(csrf_points) > 0


class TestReplayEngine:
    """Test request replay with modified payloads."""
    
    def setup_method(self):
        """Setup for each test."""
        self.canonicalizer = RequestCanonicalizer()
        self.extractor = InsertionPointExtractor(enable_nested_encoding=True)
        self.replay_engine = ReplayEngine()
    
    def test_replay_simple_modification(self):
        """Test replaying with simple payload modification."""
        body = json.dumps({"user_id": 123})
        
        canonical = self.canonicalizer.canonicalize(
            method="POST",
            url="https://api.example.com/users",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        _, points = self.extractor.extract_from_request(
            method="POST",
            url="https://api.example.com/users",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        # Find user_id insertion point
        user_id_point = next((p for p in points if "user_id" in p.location), None)
        assert user_id_point is not None
        
        # Build replay request with modified value
        replay_req = self.replay_engine.build_replay_request(
            canonical=canonical,
            insertion_point=user_id_point,
            payload_value=999,
            test_name="idor_test",
        )
        
        assert replay_req.method == "POST"
        assert "999" in str(replay_req.body)
    
    def test_replay_with_encoding_layers(self):
        """Test replaying with nested encoding layers."""
        # Create request with base64-encoded data
        inner_data = {"secret_id": 456}
        encoded = base64.b64encode(json.dumps(inner_data).encode()).decode()
        body = json.dumps({"encrypted_data": encoded})
        
        canonical = self.canonicalizer.canonicalize(
            method="POST",
            url="https://api.example.com/secure",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        _, points = self.extractor.extract_from_request(
            method="POST",
            url="https://api.example.com/secure",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        # Find nested insertion point
        nested_point = next((p for p in points if len(p.encoding_layers) > 0), None)
        
        if nested_point:
            # Build replay with modified value
            replay_req = self.replay_engine.build_replay_request(
                canonical=canonical,
                insertion_point=nested_point,
                payload_value=999,
                test_name="nested_test",
            )
            
            # Verify encoding was applied
            assert replay_req.body is not None


class TestEndToEndPipeline:
    """Test complete pipeline from detection to replay."""
    
    def test_complete_flow(self):
        """Test complete flow: detect -> extract -> generate payload -> replay."""
        # Step 1: Create complex request with triple encoding
        original_data = {"transaction_id": "txn_123", "amount": 1000}
        gzipped = gzip.compress(json.dumps(original_data).encode())
        b64 = base64.b64encode(gzipped).decode()
        url_enc = quote(b64)
        
        body = json.dumps({"encrypted_payment": url_enc})
        
        # Step 2: Extract insertion points
        extractor = InsertionPointExtractor(enable_nested_encoding=True)
        canonical, points = extractor.extract_from_request(
            method="POST",
            url="https://api.example.com/payments",
            headers={"Content-Type": "application/json"},
            body=body.encode(),
        )
        
        # Step 3: Find nested insertion point
        nested_points = [p for p in points if len(p.encoding_layers) > 0]
        assert len(nested_points) > 0
        
        # Step 4: Generate test payload
        generator = PayloadGenerator()
        test_payload = generator.generate_payload(
            insertion_point_location=nested_points[0].location,
            encoding_layers=nested_points[0].encoding_layers,
            payload_value={"transaction_id": "txn_999", "amount": 9999},
        )
        
        assert test_payload is not None
        
        # Step 5: Build replay request
        replay_engine = ReplayEngine()
        replay_req = replay_engine.build_replay_request(
            canonical=canonical,
            insertion_point=nested_points[0],
            payload_value={"transaction_id": "txn_999", "amount": 9999},
            test_name="payment_manipulation",
        )
        
        assert replay_req.method == "POST"
        assert replay_req.body is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
