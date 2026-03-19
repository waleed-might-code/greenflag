"""
WARC Evidence Extractor for Reporting.
Extracts HTTP request/response pairs from WARC archives for evidence packs.
"""

import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class HTTPCapture:
    """Extracted HTTP request/response pair from WARC."""
    warc_id: str
    method: str
    url: str
    request_headers: dict[str, str]
    request_body: bytes
    status_code: int
    reason: str
    response_headers: dict[str, str]
    response_body: bytes
    timestamp: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "warc_id": self.warc_id,
            "method": self.method,
            "url": self.url,
            "request_headers": self.request_headers,
            "request_body": self.request_body.decode("utf-8", errors="replace"),
            "status_code": self.status_code,
            "reason": self.reason,
            "response_headers": self.response_headers,
            "response_body": self.response_body.decode("utf-8", errors="replace"),
            "timestamp": self.timestamp,
        }


class WARCEvidenceExtractor:
    """
    Extracts HTTP captures from WARC files for evidence generation.
    
    Usage:
        extractor = WARCEvidenceExtractor(base_dir="outputs/warc")
        capture = extractor.extract_by_uri("warc://eng_123/file.warc.gz#1234:5678")
    """
    
    def __init__(self, base_dir: Path | str):
        """
        Initialize extractor.
        
        Args:
            base_dir: Base directory containing WARC files
        """
        self.base_dir = Path(base_dir)
    
    def extract_by_uri(self, warc_uri: str) -> Optional[HTTPCapture]:
        """
        Extract HTTP capture by WARC URI.
        
        Args:
            warc_uri: WARC URI (warc://engagement_id/file.warc.gz#offset:length)
            
        Returns:
            HTTPCapture if found, None otherwise
        """
        try:
            # Parse WARC URI
            if not warc_uri.startswith("warc://"):
                logger.warning(f"Invalid WARC URI format: {warc_uri}")
                return None
            
            # Extract components: warc://engagement_id/file.warc.gz#offset:length
            uri_parts = warc_uri[7:]  # Remove "warc://"
            
            if "#" not in uri_parts:
                logger.warning(f"WARC URI missing offset/length: {warc_uri}")
                return None
            
            path_part, location = uri_parts.split("#", 1)
            
            if ":" not in location:
                logger.warning(f"WARC URI missing length: {warc_uri}")
                return None
            
            offset_str, length_str = location.split(":", 1)
            offset = int(offset_str)
            length = int(length_str)
            
            # Construct file path
            file_path = self.base_dir / path_part
            
            if not file_path.exists():
                logger.warning(f"WARC file not found: {file_path}")
                return None
            
            # Extract record
            return self._extract_record(file_path, offset, length)
        
        except Exception as e:
            logger.error(f"Failed to extract WARC record from {warc_uri}: {e}")
            return None
    
    def _extract_record(
        self,
        file_path: Path,
        offset: int,
        length: int,
    ) -> Optional[HTTPCapture]:
        """Extract WARC record at specific offset."""
        try:
            # Open WARC file (gzipped or plain)
            if file_path.suffix == ".gz":
                with gzip.open(file_path, "rb") as f:
                    f.seek(offset)
                    data = f.read(length)
            else:
                with open(file_path, "rb") as f:
                    f.seek(offset)
                    data = f.read(length)
            
            # Parse WARC records (request + response)
            return self._parse_warc_records(data)
        
        except Exception as e:
            logger.error(f"Failed to read WARC record: {e}")
            return None
    
    def _parse_warc_records(self, data: bytes) -> Optional[HTTPCapture]:
        """Parse WARC request and response records."""
        try:
            # Split into individual WARC records
            records = data.split(b"\r\n\r\n\r\n")
            
            if len(records) < 2:
                logger.warning("Expected at least 2 WARC records (request + response)")
                return None
            
            # Parse request record
            request_data = self._parse_single_record(records[0])
            if not request_data:
                return None
            
            # Parse response record
            response_data = self._parse_single_record(records[1])
            if not response_data:
                return None
            
            # Extract HTTP details
            req_http = self._parse_http_request(request_data["content"])
            resp_http = self._parse_http_response(response_data["content"])
            
            return HTTPCapture(
                warc_id=request_data["headers"].get("WARC-Record-ID", "unknown"),
                method=req_http["method"],
                url=req_http["url"],
                request_headers=req_http["headers"],
                request_body=req_http["body"],
                status_code=resp_http["status_code"],
                reason=resp_http["reason"],
                response_headers=resp_http["headers"],
                response_body=resp_http["body"],
                timestamp=request_data["headers"].get("WARC-Date", ""),
            )
        
        except Exception as e:
            logger.error(f"Failed to parse WARC records: {e}")
            return None

    
    def _parse_single_record(self, record_data: bytes) -> Optional[dict]:
        """Parse a single WARC record into headers and content."""
        try:
            # Split WARC headers from content
            parts = record_data.split(b"\r\n\r\n", 1)
            if len(parts) != 2:
                return None
            
            warc_headers_raw, content = parts
            
            # Parse WARC headers
            warc_headers = {}
            for line in warc_headers_raw.decode("utf-8", errors="replace").split("\r\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    warc_headers[key.strip()] = value.strip()
            
            return {
                "headers": warc_headers,
                "content": content,
            }
        
        except Exception as e:
            logger.error(f"Failed to parse WARC record: {e}")
            return None
    
    def _parse_http_request(self, http_data: bytes) -> dict:
        """Parse HTTP request from WARC content."""
        try:
            # Split request line, headers, and body
            parts = http_data.split(b"\r\n\r\n", 1)
            headers_section = parts[0]
            body = parts[1] if len(parts) > 1 else b""
            
            # Parse request line and headers
            lines = headers_section.decode("utf-8", errors="replace").split("\r\n")
            request_line = lines[0]
            
            # Extract method and URL
            method, url, _ = request_line.split(" ", 2)
            
            # Parse headers
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip()] = value.strip()
            
            return {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
            }
        
        except Exception as e:
            logger.error(f"Failed to parse HTTP request: {e}")
            return {
                "method": "UNKNOWN",
                "url": "",
                "headers": {},
                "body": b"",
            }
    
    def _parse_http_response(self, http_data: bytes) -> dict:
        """Parse HTTP response from WARC content."""
        try:
            # Split status line, headers, and body
            parts = http_data.split(b"\r\n\r\n", 1)
            headers_section = parts[0]
            body = parts[1] if len(parts) > 1 else b""
            
            # Parse status line and headers
            lines = headers_section.decode("utf-8", errors="replace").split("\r\n")
            status_line = lines[0]
            
            # Extract status code and reason
            parts = status_line.split(" ", 2)
            status_code = int(parts[1]) if len(parts) > 1 else 0
            reason = parts[2] if len(parts) > 2 else ""
            
            # Parse headers
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip()] = value.strip()
            
            return {
                "status_code": status_code,
                "reason": reason,
                "headers": headers,
                "body": body,
            }
        
        except Exception as e:
            logger.error(f"Failed to parse HTTP response: {e}")
            return {
                "status_code": 0,
                "reason": "",
                "headers": {},
                "body": b"",
            }
    
    def extract_multiple(self, warc_uris: list[str]) -> list[HTTPCapture]:
        """
        Extract multiple HTTP captures by WARC URIs.
        
        Args:
            warc_uris: List of WARC URIs
            
        Returns:
            List of HTTPCapture objects (skips failed extractions)
        """
        captures = []
        for uri in warc_uris:
            capture = self.extract_by_uri(uri)
            if capture:
                captures.append(capture)
        return captures
