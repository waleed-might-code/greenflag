"""
Payload encoder - applies encoding layers in reverse for test payload generation.
Complements the encoding detector by encoding payloads with the same layers.
"""

import base64
import gzip
import json
import zlib
from typing import Any
from urllib.parse import quote

from loguru import logger


class PayloadEncoder:
    """
    Encodes payloads by applying encoding layers in reverse order.
    Used by replay engine to generate test payloads that match the original encoding.
    """
    
    def __init__(self):
        """Initialize payload encoder."""
        self.encoding_count = 0
    
    def encode(self, payload: Any, encoding_layers: list[str]) -> str | bytes:
        """
        Apply encoding layers to a payload in reverse order.
        
        Args:
            payload: Raw payload (string, dict, list, etc.)
            encoding_layers: List of encoding types in detection order
                           (will be applied in reverse)
        
        Returns:
            Encoded payload as string or bytes
        
        Example:
            If encoding_layers = ["url_encode", "base64", "json"],
            this means the original was: JSON -> base64 -> URL-encode
            So we apply: payload -> JSON -> base64 -> URL-encode
        """
        if not encoding_layers:
            # No encoding, return as-is
            return self._to_string(payload)
        
        # Start with the payload
        current = payload
        
        # Apply each encoding layer in reverse order
        # (reverse because we're encoding, not decoding)
        for encoding_type in reversed(encoding_layers):
            current = self._apply_encoding(current, encoding_type)
            self.encoding_count += 1
        
        logger.debug(
            f"Encoded payload through {len(encoding_layers)} layers: "
            f"{' -> '.join(reversed(encoding_layers))}"
        )
        
        return current
    
    def _apply_encoding(self, data: Any, encoding_type: str) -> str | bytes:
        """Apply a single encoding layer."""
        if encoding_type == "json":
            return self._encode_json(data)
        elif encoding_type == "base64":
            return self._encode_base64(data)
        elif encoding_type == "url_encode":
            return self._encode_url(data)
        elif encoding_type == "gzip":
            return self._encode_gzip(data)
        elif encoding_type == "hex":
            return self._encode_hex(data)
        elif encoding_type == "jwt":
            # JWT encoding is complex and typically not fuzzed
            # Return as-is or handle specially
            logger.warning("JWT encoding not supported for payload generation")
            return self._to_string(data)
        else:
            logger.warning(f"Unknown encoding type: {encoding_type}")
            return self._to_string(data)
    
    def _encode_json(self, data: Any) -> str:
        """Encode data as JSON."""
        if isinstance(data, (str, bytes)):
            # Already a string, wrap in JSON
            if isinstance(data, bytes):
                data = data.decode('utf-8', errors='ignore')
            return json.dumps(data)
        else:
            # Dict, list, etc.
            return json.dumps(data)
    
    def _encode_base64(self, data: Any) -> str:
        """Encode data as base64."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        elif not isinstance(data, bytes):
            # Convert to JSON first
            data = json.dumps(data).encode('utf-8')
        
        return base64.b64encode(data).decode('ascii')
    
    def _encode_url(self, data: Any) -> str:
        """URL-encode data."""
        data_str = self._to_string(data)
        return quote(data_str, safe='')
    
    def _encode_gzip(self, data: Any) -> bytes:
        """Gzip compress data."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        elif not isinstance(data, bytes):
            data = json.dumps(data).encode('utf-8')
        
        return gzip.compress(data)
    
    def _encode_hex(self, data: Any) -> str:
        """Hex encode data."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        elif not isinstance(data, bytes):
            data = json.dumps(data).encode('utf-8')
        
        return data.hex()
    
    def _to_string(self, data: Any) -> str:
        """Convert data to string."""
        if isinstance(data, str):
            return data
        elif isinstance(data, bytes):
            return data.decode('utf-8', errors='ignore')
        else:
            return json.dumps(data)
    
    def get_stats(self) -> dict:
        """Get encoding statistics."""
        return {
            "total_encodings": self.encoding_count,
        }


class PayloadGenerator:
    """
    Generates test payloads for insertion points with proper encoding.
    """
    
    def __init__(self):
        """Initialize payload generator."""
        self.encoder = PayloadEncoder()
        self.payloads_generated = 0
    
    def generate_payload(
        self,
        insertion_point_location: str,
        encoding_layers: list[str],
        payload_value: Any,
    ) -> str | bytes:
        """
        Generate a test payload for an insertion point.
        
        Args:
            insertion_point_location: Location of the insertion point
            encoding_layers: Encoding layers to apply
            payload_value: The test payload value
        
        Returns:
            Encoded payload ready for injection
        """
        self.payloads_generated += 1
        
        # Apply encoding layers
        encoded = self.encoder.encode(payload_value, encoding_layers)
        
        logger.debug(
            f"Generated payload for {insertion_point_location}: "
            f"{len(encoding_layers)} layers, "
            f"size={len(str(encoded))} bytes"
        )
        
        return encoded
    
    def generate_test_suite(
        self,
        insertion_point_location: str,
        encoding_layers: list[str],
        inferred_type: str,
    ) -> list[tuple[str, Any]]:
        """
        Generate a suite of test payloads for an insertion point.
        
        Args:
            insertion_point_location: Location of the insertion point
            encoding_layers: Encoding layers to apply
            inferred_type: Inferred type of the insertion point
        
        Returns:
            List of (test_name, encoded_payload) tuples
        """
        # Get base payloads based on type
        base_payloads = self._get_base_payloads(inferred_type)
        
        # Encode each payload
        test_suite = []
        for test_name, payload_value in base_payloads:
            encoded = self.generate_payload(
                insertion_point_location,
                encoding_layers,
                payload_value,
            )
            test_suite.append((test_name, encoded))
        
        return test_suite
    
    def _get_base_payloads(self, inferred_type: str) -> list[tuple[str, Any]]:
        """Get base test payloads for a given type."""
        if inferred_type == "id":
            return [
                ("boundary_zero", 0),
                ("boundary_negative", -1),
                ("boundary_max_int", 2147483647),
                ("idor_other_user", 999999),
                ("sql_injection", "1' OR '1'='1"),
            ]
        elif inferred_type == "string":
            return [
                ("xss_basic", "<script>alert(1)</script>"),
                ("xss_encoded", "&#60;script&#62;alert(1)&#60;/script&#62;"),
                ("sql_injection", "' OR '1'='1' --"),
                ("path_traversal", "../../../etc/passwd"),
                ("command_injection", "; cat /etc/passwd"),
            ]
        elif inferred_type == "email":
            return [
                ("invalid_format", "not-an-email"),
                ("sql_injection", "admin'--@example.com"),
                ("xss", "<script>@example.com"),
            ]
        elif inferred_type == "token":
            return [
                ("empty", ""),
                ("invalid", "invalid_token_12345"),
                ("expired", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.expired"),
            ]
        else:
            # Generic payloads
            return [
                ("null", None),
                ("empty_string", ""),
                ("long_string", "A" * 10000),
                ("special_chars", "!@#$%^&*()"),
            ]
    
    def get_stats(self) -> dict:
        """Get generation statistics."""
        return {
            "payloads_generated": self.payloads_generated,
            "encoder_stats": self.encoder.get_stats(),
        }
