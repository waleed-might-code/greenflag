"""
Enhanced encoding detector - identifies and decodes nested encoding layers.
Supports: base64, gzip, URL-encode, JSON-in-JSON, hex, and custom encodings.
"""

import base64
import gzip
import json
import re
import zlib
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import unquote

from loguru import logger


@dataclass
class EncodingDetectionResult:
    """Result of encoding detection."""
    is_encoded: bool
    encoding_type: Optional[str]
    decoded_data: Optional[bytes]
    confidence: float  # 0.0 to 1.0
    

class EncodingDetector:
    """
    Detects and decodes multiple encoding layers.
    Applies heuristics to identify encoding types and recursively decode.
    """
    
    # Minimum confidence threshold for detection
    MIN_CONFIDENCE = 0.7
    
    # Maximum recursion depth to prevent DoS
    MAX_DEPTH = 3
    
    # Patterns for detection
    BASE64_PATTERN = re.compile(r'^[A-Za-z0-9+/]+=*$')
    HEX_PATTERN = re.compile(r'^[0-9a-fA-F]+$')
    URL_ENCODED_PATTERN = re.compile(r'%[0-9a-fA-F]{2}')
    JWT_PATTERN = re.compile(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$')
    
    def __init__(self):
        """Initialize encoding detector."""
        self.detection_stats = {
            "base64": 0,
            "gzip": 0,
            "url_encode": 0,
            "json": 0,
            "hex": 0,
            "jwt": 0,
        }
    
    def detect_and_decode(
        self,
        data: str | bytes,
        current_depth: int = 0,
    ) -> Tuple[list[str], str | bytes]:
        """
        Recursively detect and decode encoding layers.
        
        Args:
            data: Input data (string or bytes)
            current_depth: Current recursion depth
        
        Returns:
            Tuple of (encoding_layers, final_decoded_data)
        """
        if current_depth >= self.MAX_DEPTH:
            logger.debug(f"Max recursion depth {self.MAX_DEPTH} reached")
            return [], data
        
        # Convert to string if bytes
        if isinstance(data, bytes):
            try:
                data_str = data.decode('utf-8', errors='ignore')
            except Exception:
                return [], data
        else:
            data_str = data
        
        # Try each encoding detector in order
        detectors = [
            self._detect_url_encoding,
            self._detect_base64,
            self._detect_gzip,
            self._detect_hex,
            self._detect_json_in_json,
            self._detect_jwt,
        ]
        
        for detector in detectors:
            result = detector(data_str)
            if result.is_encoded and result.confidence >= self.MIN_CONFIDENCE:
                # Successfully detected and decoded
                self.detection_stats[result.encoding_type] += 1
                
                # Recursively decode the inner layer
                inner_layers, final_data = self.detect_and_decode(
                    result.decoded_data,
                    current_depth + 1
                )
                
                # Prepend this layer to the stack
                return [result.encoding_type] + inner_layers, final_data
        
        # No encoding detected
        return [], data
    
    def _detect_url_encoding(self, data: str) -> EncodingDetectionResult:
        """Detect URL encoding (percent-encoding)."""
        if not isinstance(data, str):
            return EncodingDetectionResult(False, None, None, 0.0)
        
        # Check if contains URL-encoded characters
        if self.URL_ENCODED_PATTERN.search(data):
            try:
                decoded = unquote(data)
                # Check if decoding actually changed the string
                if decoded != data:
                    confidence = min(1.0, data.count('%') / 10.0)
                    return EncodingDetectionResult(
                        True, "url_encode", decoded.encode('utf-8'), confidence
                    )
            except Exception:
                pass
        
        return EncodingDetectionResult(False, None, None, 0.0)
    
    def _detect_base64(self, data: str) -> EncodingDetectionResult:
        """Detect base64 encoding."""
        if not isinstance(data, str) or len(data) < 4:
            return EncodingDetectionResult(False, None, None, 0.0)
        
        # Remove whitespace
        data_clean = data.strip().replace('\n', '').replace('\r', '')
        
        # Check if it matches base64 pattern
        if not self.BASE64_PATTERN.match(data_clean):
            return EncodingDetectionResult(False, None, None, 0.0)
        
        # Check if length is valid (multiple of 4 or has padding)
        if len(data_clean) % 4 not in (0, 2, 3):
            return EncodingDetectionResult(False, None, None, 0.0)
        
        try:
            decoded = base64.b64decode(data_clean, validate=True)
            
            # Heuristic: base64 should decode to something meaningful
            # Check if decoded data has reasonable byte distribution
            if len(decoded) > 0:
                # Calculate confidence based on printable characters
                printable_ratio = sum(1 for b in decoded if 32 <= b <= 126) / len(decoded)
                confidence = 0.8 if printable_ratio > 0.5 else 0.6
                
                return EncodingDetectionResult(True, "base64", decoded, confidence)
        except Exception:
            pass
        
        return EncodingDetectionResult(False, None, None, 0.0)
    
    def _detect_gzip(self, data: str | bytes) -> EncodingDetectionResult:
        """Detect gzip compression."""
        # Convert to bytes if string
        if isinstance(data, str):
            try:
                data_bytes = data.encode('latin-1')
            except Exception:
                return EncodingDetectionResult(False, None, None, 0.0)
        else:
            data_bytes = data
        
        # Check for gzip magic bytes (1f 8b)
        if len(data_bytes) < 2:
            return EncodingDetectionResult(False, None, None, 0.0)
        
        if data_bytes[0:2] == b'\x1f\x8b':
            try:
                decompressed = gzip.decompress(data_bytes)
                return EncodingDetectionResult(True, "gzip", decompressed, 1.0)
            except Exception:
                pass
        
        # Try zlib (deflate) as fallback
        try:
            decompressed = zlib.decompress(data_bytes)
            return EncodingDetectionResult(True, "gzip", decompressed, 0.9)
        except Exception:
            pass
        
        return EncodingDetectionResult(False, None, None, 0.0)

    
    def _detect_hex(self, data: str) -> EncodingDetectionResult:
        """Detect hexadecimal encoding."""
        if not isinstance(data, str) or len(data) < 2:
            return EncodingDetectionResult(False, None, None, 0.0)
        
        data_clean = data.strip().replace(' ', '').replace('0x', '')
        
        # Check if it's valid hex
        if not self.HEX_PATTERN.match(data_clean):
            return EncodingDetectionResult(False, None, None, 0.0)
        
        # Must be even length
        if len(data_clean) % 2 != 0:
            return EncodingDetectionResult(False, None, None, 0.0)
        
        try:
            decoded = bytes.fromhex(data_clean)
            # Heuristic: hex-encoded data should be at least somewhat printable
            if len(decoded) > 0:
                printable_ratio = sum(1 for b in decoded if 32 <= b <= 126) / len(decoded)
                confidence = 0.7 if printable_ratio > 0.3 else 0.5
                return EncodingDetectionResult(True, "hex", decoded, confidence)
        except Exception:
            pass
        
        return EncodingDetectionResult(False, None, None, 0.0)
    
    def _detect_json_in_json(self, data: str) -> EncodingDetectionResult:
        """Detect JSON string containing escaped JSON."""
        if not isinstance(data, str):
            return EncodingDetectionResult(False, None, None, 0.0)
        
        # Check if it looks like escaped JSON (contains \" or \{ patterns)
        if '\\"' not in data and '\\{' not in data:
            return EncodingDetectionResult(False, None, None, 0.0)
        
        try:
            # Try to parse as JSON first
            parsed = json.loads(data)
            
            # If parsed result is a string, try to parse it again
            if isinstance(parsed, str):
                try:
                    inner_parsed = json.loads(parsed)
                    # Successfully parsed nested JSON
                    return EncodingDetectionResult(
                        True, "json", json.dumps(inner_parsed).encode('utf-8'), 0.9
                    )
                except Exception:
                    pass
        except Exception:
            pass
        
        return EncodingDetectionResult(False, None, None, 0.0)
    
    def _detect_jwt(self, data: str) -> EncodingDetectionResult:
        """Detect JWT (JSON Web Token) format."""
        if not isinstance(data, str) or len(data) < 10:
            return EncodingDetectionResult(False, None, None, 0.0)
        
        data_clean = data.strip()
        
        # Check JWT pattern (header.payload.signature)
        if not self.JWT_PATTERN.match(data_clean):
            return EncodingDetectionResult(False, None, None, 0.0)
        
        parts = data_clean.split('.')
        if len(parts) != 3:
            return EncodingDetectionResult(False, None, None, 0.0)
        
        try:
            # Decode the payload (second part)
            # JWT uses base64url encoding (- and _ instead of + and /)
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - (len(payload_b64) % 4)
            if padding != 4:
                payload_b64 += '=' * padding
            
            # Replace URL-safe characters
            payload_b64 = payload_b64.replace('-', '+').replace('_', '/')
            
            decoded = base64.b64decode(payload_b64)
            
            # Verify it's valid JSON
            json.loads(decoded)
            
            return EncodingDetectionResult(True, "jwt", decoded, 0.95)
        except Exception:
            pass
        
        return EncodingDetectionResult(False, None, None, 0.0)
    
    def get_stats(self) -> dict:
        """Get detection statistics."""
        return self.detection_stats.copy()


class NestedEncodingExtractor:
    """
    Extracts insertion points from nested encoded data.
    Integrates with the canonicalizer to handle multi-layer encodings.
    """
    
    def __init__(self, max_depth: int = 3):
        """
        Initialize nested encoding extractor.
        
        Args:
            max_depth: Maximum encoding depth to process
        """
        self.detector = EncodingDetector()
        self.max_depth = max_depth
        self.extraction_count = 0
    
    def extract_nested_structure(
        self,
        data: str | bytes,
        base_path: str = "root",
    ) -> Tuple[list[str], dict]:
        """
        Extract nested structure from encoded data.
        
        Args:
            data: Input data (potentially encoded)
            base_path: Base path for insertion points
        
        Returns:
            Tuple of (encoding_layers, parsed_structure)
        """
        # Detect and decode all layers
        encoding_layers, decoded_data = self.detector.detect_and_decode(data)
        
        if not encoding_layers:
            # No encoding detected, return as-is
            return [], {"type": "raw", "value": data}
        
        # Try to parse the decoded data
        parsed_structure = self._parse_decoded_data(decoded_data)
        
        self.extraction_count += 1
        logger.debug(
            f"Extracted nested structure: {len(encoding_layers)} layers "
            f"({' -> '.join(encoding_layers)})"
        )
        
        return encoding_layers, parsed_structure
    
    def _parse_decoded_data(self, data: str | bytes) -> dict:
        """Parse decoded data into structured format."""
        # Convert to string if bytes
        if isinstance(data, bytes):
            try:
                data_str = data.decode('utf-8', errors='ignore')
            except Exception:
                return {"type": "binary", "value": data}
        else:
            data_str = data
        
        # Try JSON
        try:
            parsed = json.loads(data_str)
            return {"type": "json", "value": parsed}
        except Exception:
            pass
        
        # Try form data (key=value&key2=value2)
        if '=' in data_str and ('&' in data_str or ';' in data_str):
            try:
                from urllib.parse import parse_qs
                parsed = parse_qs(data_str)
                return {"type": "form", "value": parsed}
            except Exception:
                pass
        
        # Default to string
        return {"type": "string", "value": data_str}
    
    def get_stats(self) -> dict:
        """Get extraction statistics."""
        return {
            "extractions": self.extraction_count,
            "detector_stats": self.detector.get_stats(),
        }
