"""
Encoding Detection and Decoding Pipeline

Detects and recursively decodes nested encoding layers in HTTP parameters.
Supports: base64, URL encoding, JSON, XML, gzip, hex, JWT, and custom formats.
"""

import base64
import gzip
import json
import re
import zlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, unquote_plus
import binascii


@dataclass
class EncodingLayer:
    """Represents a single encoding layer in a nested structure."""
    encoding_type: str  # base64, json, gzip, url, hex, jwt, xml
    decoded_value: Any
    confidence: float  # 0.0 to 1.0
    metadata: Dict[str, Any]  # Additional info about the layer


class EncodingDetector:
    """
    Detects and recursively decodes nested encoding layers.
    
    Example: base64(JSON(gzip(data))) will be decoded through all layers.
    """
    
    MAX_RECURSION_DEPTH = 5  # Prevent infinite recursion
    MIN_CONFIDENCE = 0.6  # Minimum confidence to accept a detection
    
    def __init__(self, max_depth: int = 5, min_confidence: float = 0.6):
        self.max_depth = max_depth
        self.min_confidence = min_confidence
    
    def detect_and_decode(self, value: Any, depth: int = 0) -> List[EncodingLayer]:
        """
        Recursively detect and decode encoding layers.
        
        Returns a list of EncodingLayer objects from outermost to innermost.
        """
        layers = []
        
        if depth >= self.max_depth:
            return layers
        
        if not isinstance(value, (str, bytes)):
            return layers
        
        # Convert to string for detection
        if isinstance(value, bytes):
            try:
                value_str = value.decode('utf-8', errors='ignore')
            except:
                value_str = str(value)
        else:
            value_str = value
        
        # Try each decoder in order of likelihood
        decoders = [
            self._try_json,
            self._try_base64,
            self._try_url_encoding,
            self._try_jwt,
            self._try_hex,
            self._try_gzip,
        ]
        
        for decoder in decoders:
            result = decoder(value_str if isinstance(value, str) else value)
            if result and result.confidence >= self.min_confidence:
                layers.append(result)
                # Recursively decode the inner value
                inner_layers = self.detect_and_decode(result.decoded_value, depth + 1)
                layers.extend(inner_layers)
                break  # Stop after first successful decode
        
        return layers
    
    def _try_json(self, value: str) -> Optional[EncodingLayer]:
        """Detect and parse JSON."""
        if not isinstance(value, str):
            return None
        
        value = value.strip()
        if not (value.startswith('{') or value.startswith('[')):
            return None
        
        try:
            decoded = json.loads(value)
            return EncodingLayer(
                encoding_type='json',
                decoded_value=decoded,
                confidence=1.0,
                metadata={'original_length': len(value)}
            )
        except (json.JSONDecodeError, ValueError):
            return None
    
    def _try_base64(self, value: str) -> Optional[EncodingLayer]:
        """Detect and decode base64."""
        if not isinstance(value, str):
            return None
        
        # Base64 pattern: alphanumeric + / + = padding
        if not re.match(r'^[A-Za-z0-9+/]+=*$', value) or len(value) < 4:
            return None
        
        # Base64 length must be multiple of 4
        if len(value) % 4 != 0:
            return None
        
        try:
            decoded_bytes = base64.b64decode(value, validate=True)
            # Try to decode as UTF-8
            try:
                decoded_str = decoded_bytes.decode('utf-8')
                confidence = self._calculate_base64_confidence(value, decoded_str)
                return EncodingLayer(
                    encoding_type='base64',
                    decoded_value=decoded_str,
                    confidence=confidence,
                    metadata={'decoded_bytes': len(decoded_bytes)}
                )
            except UnicodeDecodeError:
                # Binary data
                return EncodingLayer(
                    encoding_type='base64',
                    decoded_value=decoded_bytes,
                    confidence=0.8,
                    metadata={'decoded_bytes': len(decoded_bytes), 'binary': True}
                )
        except (binascii.Error, ValueError):
            return None
    
    def _try_url_encoding(self, value: str) -> Optional[EncodingLayer]:
        """Detect and decode URL encoding."""
        if not isinstance(value, str):
            return None
        
        # Check if value contains URL-encoded characters
        if '%' not in value:
            return None
        
        try:
            decoded = unquote_plus(value)
            if decoded != value:  # Something was decoded
                confidence = value.count('%') / len(value) * 10  # Heuristic
                confidence = min(confidence, 1.0)
                return EncodingLayer(
                    encoding_type='url',
                    decoded_value=decoded,
                    confidence=confidence,
                    metadata={'percent_encoded': value.count('%')}
                )
        except Exception:
            pass
        
        return None
    
    def _try_jwt(self, value: str) -> Optional[EncodingLayer]:
        """Detect and decode JWT tokens."""
        if not isinstance(value, str):
            return None
        
        # JWT format: header.payload.signature
        parts = value.split('.')
        if len(parts) != 3:
            return None
        
        try:
            # Decode header and payload (ignore signature)
            header = self._decode_jwt_part(parts[0])
            payload = self._decode_jwt_part(parts[1])
            
            if header and payload:
                return EncodingLayer(
                    encoding_type='jwt',
                    decoded_value={'header': header, 'payload': payload},
                    confidence=0.95,
                    metadata={'has_signature': True}
                )
        except Exception:
            pass
        
        return None
    
    def _decode_jwt_part(self, part: str) -> Optional[Dict]:
        """Decode a JWT part (header or payload)."""
        # Add padding if needed
        padding = 4 - (len(part) % 4)
        if padding != 4:
            part += '=' * padding
        
        try:
            decoded_bytes = base64.urlsafe_b64decode(part)
            decoded_str = decoded_bytes.decode('utf-8')
            return json.loads(decoded_str)
        except Exception:
            return None
    
    def _try_hex(self, value: str) -> Optional[EncodingLayer]:
        """Detect and decode hexadecimal encoding."""
        if not isinstance(value, str):
            return None
        
        # Hex pattern: only 0-9, a-f, A-F
        if not re.match(r'^[0-9a-fA-F]+$', value) or len(value) < 4 or len(value) % 2 != 0:
            return None
        
        try:
            decoded_bytes = bytes.fromhex(value)
            try:
                decoded_str = decoded_bytes.decode('utf-8')
                return EncodingLayer(
                    encoding_type='hex',
                    decoded_value=decoded_str,
                    confidence=0.7,
                    metadata={'decoded_bytes': len(decoded_bytes)}
                )
            except UnicodeDecodeError:
                return EncodingLayer(
                    encoding_type='hex',
                    decoded_value=decoded_bytes,
                    confidence=0.7,
                    metadata={'decoded_bytes': len(decoded_bytes), 'binary': True}
                )
        except ValueError:
            return None
    
    def _try_gzip(self, value: bytes) -> Optional[EncodingLayer]:
        """Detect and decode gzip compression."""
        if not isinstance(value, bytes):
            if isinstance(value, str):
                value = value.encode('latin-1', errors='ignore')
            else:
                return None
        
        # Gzip magic number: 1f 8b
        if len(value) < 2 or value[:2] != b'\x1f\x8b':
            return None
        
        try:
            decoded_bytes = gzip.decompress(value)
            try:
                decoded_str = decoded_bytes.decode('utf-8')
                return EncodingLayer(
                    encoding_type='gzip',
                    decoded_value=decoded_str,
                    confidence=1.0,
                    metadata={'compressed_size': len(value), 'decompressed_size': len(decoded_bytes)}
                )
            except UnicodeDecodeError:
                return EncodingLayer(
                    encoding_type='gzip',
                    decoded_value=decoded_bytes,
                    confidence=1.0,
                    metadata={'compressed_size': len(value), 'decompressed_size': len(decoded_bytes), 'binary': True}
                )
        except (gzip.BadGzipFile, zlib.error):
            return None
    
    def _calculate_base64_confidence(self, encoded: str, decoded: str) -> float:
        """Calculate confidence score for base64 detection."""
        # Higher confidence if decoded value looks like structured data
        confidence = 0.7
        
        if decoded.startswith('{') or decoded.startswith('['):
            confidence = 0.95  # Likely JSON
        elif decoded.startswith('<?xml'):
            confidence = 0.95  # Likely XML
        elif re.match(r'^[a-zA-Z0-9\s\.,;:!?-]+$', decoded):
            confidence = 0.85  # Readable text
        
        return confidence
    
    def encode_layers(self, value: Any, layers: List[str]) -> str:
        """
        Apply encoding layers in reverse order for payload generation.
        
        Example: encode_layers("data", ["json", "base64"]) -> base64(json("data"))
        """
        result = value
        
        for layer in reversed(layers):
            if layer == 'json':
                result = json.dumps(result)
            elif layer == 'base64':
                if isinstance(result, str):
                    result = result.encode('utf-8')
                result = base64.b64encode(result).decode('ascii')
            elif layer == 'url':
                result = unquote(str(result))
            elif layer == 'hex':
                if isinstance(result, str):
                    result = result.encode('utf-8')
                result = result.hex()
            elif layer == 'gzip':
                if isinstance(result, str):
                    result = result.encode('utf-8')
                result = gzip.compress(result)
        
        return result
