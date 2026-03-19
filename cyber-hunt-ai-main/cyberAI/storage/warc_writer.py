"""
WARC (Web ARChive) writer for evidence storage.
Implements ISO 28500 standard for archiving HTTP request/response pairs.

Every security finding is traceable to raw WARC captures via content-addressed references.
"""

import gzip
import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from loguru import logger


@dataclass
class WARCReference:
    """Reference to a WARC record for evidence linking."""
    warc_id: str  # Content-addressed ID (SHA-256)
    file_path: str  # Relative path to WARC file
    offset: int  # Byte offset in file
    length: int  # Record length in bytes
    engagement_id: str
    timestamp: datetime
    
    def to_uri(self) -> str:
        """Generate WARC URI for this reference."""
        return f"warc://{self.engagement_id}/{self.file_path}#{self.offset}:{self.length}"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "warc_id": self.warc_id,
            "file_path": self.file_path,
            "offset": self.offset,
            "length": self.length,
            "engagement_id": self.engagement_id,
            "timestamp": self.timestamp.isoformat(),
            "uri": self.to_uri(),
        }


class WARCWriter:
    """
    Thread-safe WARC writer for HTTP traffic archival.
    
    Features:
    - Content-addressed IDs (SHA-256 of request line + headers)
    - Engagement-scoped file organization
    - Gzip compression
    - Automatic file rotation
    - Thread-safe writes
    
    Usage:
        writer = WARCWriter(base_dir="outputs/warc", engagement_id="eng_123")
        ref = writer.write_request_response(
            method="GET",
            url="https://example.com/api/users",
            request_headers={"Authorization": "Bearer ..."},
            request_body=b"",
            status_code=200,
            response_headers={"Content-Type": "application/json"},
            response_body=b'{"users": [...]}'
        )
        # ref.to_uri() -> "warc://eng_123/eng_123_20240101_000.warc.gz#1234:5678"
    """
    
    def __init__(
        self,
        base_dir: Path | str,
        engagement_id: str,
        max_file_size_mb: int = 100,
        compress: bool = True,
    ):
        """
        Initialize WARC writer.
        
        Args:
            base_dir: Base directory for WARC storage
            engagement_id: Engagement identifier for scoping
            max_file_size_mb: Max size per WARC file before rotation
            compress: Enable gzip compression
        """
        self.base_dir = Path(base_dir)
        self.engagement_id = engagement_id
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.compress = compress
        
        # Create engagement directory
        self.engagement_dir = self.base_dir / engagement_id
        self.engagement_dir.mkdir(parents=True, exist_ok=True)
        
        # Current file state
        self._lock = threading.Lock()
        self._current_file: Optional[Path] = None
        self._current_handle = None
        self._current_size = 0
        self._file_counter = 0
        
        logger.info(f"WARC writer initialized for engagement {engagement_id}")
    
    def _generate_content_id(self, method: str, url: str, request_headers: dict) -> str:
        """
        Generate content-addressed ID from request.
        
        Uses SHA-256 of: method + url + sorted headers (excluding auth/cookies)
        """
        # Build canonical request string
        parts = [method.upper(), url]
        
        # Add sorted headers (exclude sensitive/variable headers)
        excluded = {"authorization", "cookie", "x-request-id", "x-trace-id", "date"}
        sorted_headers = sorted(
            (k.lower(), v) for k, v in request_headers.items()
            if k.lower() not in excluded
        )
        parts.extend(f"{k}:{v}" for k, v in sorted_headers)
        
        canonical = "\n".join(parts).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
    
    def _get_current_file(self) -> tuple[Path, any]:
        """Get or create current WARC file handle."""
        if self._current_file is None or self._current_size >= self.max_file_size:
            self._rotate_file()
        
        return self._current_file, self._current_handle
    
    def _rotate_file(self) -> None:
        """Rotate to a new WARC file."""
        # Close current file
        if self._current_handle:
            self._current_handle.close()
        
        # Generate new filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{self.engagement_id}_{timestamp}_{self._file_counter:03d}.warc"
        if self.compress:
            filename += ".gz"
        
        self._current_file = self.engagement_dir / filename
        self._file_counter += 1
        self._current_size = 0
        
        # Open new file
        if self.compress:
            self._current_handle = gzip.open(self._current_file, "ab")
        else:
            self._current_handle = open(self._current_file, "ab")
        
        logger.debug(f"Rotated to new WARC file: {self._current_file.name}")
    
    def _format_warc_record(
        self,
        record_type: str,
        content: bytes,
        headers: dict,
        warc_id: str,
    ) -> bytes:
        """
        Format a WARC record per ISO 28500.
        
        WARC/1.0
        WARC-Type: request|response
        WARC-Record-ID: <urn:uuid:...>
        WARC-Date: 2024-01-01T00:00:00Z
        Content-Type: application/http; msgtype=request|response
        Content-Length: 1234
        
        [HTTP message]
        
        """
        record_id = f"<urn:uuid:{uuid4()}>"
        warc_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content_length = len(content)
        
        # Build WARC header
        warc_header = (
            f"WARC/1.0\r\n"
            f"WARC-Type: {record_type}\r\n"
            f"WARC-Record-ID: {record_id}\r\n"
            f"WARC-Date: {warc_date}\r\n"
            f"WARC-Target-URI: {headers.get('uri', 'unknown')}\r\n"
            f"Content-Type: application/http; msgtype={record_type}\r\n"
            f"Content-Length: {content_length}\r\n"
        )
        
        # Add custom headers
        if "warc-content-id" in headers:
            warc_header += f"WARC-Content-ID: {headers['warc-content-id']}\r\n"
        if "warc-concurrent-to" in headers:
            warc_header += f"WARC-Concurrent-To: {headers['warc-concurrent-to']}\r\n"
        
        warc_header += "\r\n"
        
        # Combine header + content + separator
        record = warc_header.encode("utf-8") + content + b"\r\n\r\n"
        return record
    
    def _format_http_request(
        self,
        method: str,
        url: str,
        headers: dict,
        body: bytes,
    ) -> bytes:
        """Format HTTP request message."""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        
        # Request line
        request_line = f"{method.upper()} {path} HTTP/1.1\r\n"
        
        # Headers
        header_lines = []
        for key, value in headers.items():
            header_lines.append(f"{key}: {value}\r\n")
        
        # Ensure Host header
        if "host" not in {k.lower() for k in headers.keys()}:
            header_lines.insert(0, f"Host: {parsed.netloc}\r\n")
        
        http_message = request_line + "".join(header_lines) + "\r\n"
        return http_message.encode("utf-8") + body
    
    def _format_http_response(
        self,
        status_code: int,
        reason: str,
        headers: dict,
        body: bytes,
    ) -> bytes:
        """Format HTTP response message."""
        # Status line
        status_line = f"HTTP/1.1 {status_code} {reason}\r\n"
        
        # Headers
        header_lines = []
        for key, value in headers.items():
            header_lines.append(f"{key}: {value}\r\n")
        
        http_message = status_line + "".join(header_lines) + "\r\n"
        return http_message.encode("utf-8") + body

    
    def write_request_response(
        self,
        method: str,
        url: str,
        request_headers: dict,
        request_body: bytes,
        status_code: int,
        response_headers: dict,
        response_body: bytes,
        reason: str = "OK",
    ) -> WARCReference:
        """
        Write HTTP request/response pair to WARC.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL
            request_headers: Request headers dict
            request_body: Request body bytes
            status_code: HTTP status code
            response_headers: Response headers dict
            response_body: Response body bytes
            reason: HTTP reason phrase
            
        Returns:
            WARCReference for linking from findings
        """
        with self._lock:
            # Generate content-addressed ID
            warc_id = self._generate_content_id(method, url, request_headers)
            
            # Get current file
            file_path, handle = self._get_current_file()
            offset = self._current_size
            
            # Format HTTP messages
            http_request = self._format_http_request(method, url, request_headers, request_body)
            http_response = self._format_http_response(status_code, reason, response_headers, response_body)
            
            # Create WARC records
            request_record = self._format_warc_record(
                "request",
                http_request,
                {"uri": url, "warc-content-id": warc_id},
                warc_id,
            )
            
            response_record = self._format_warc_record(
                "response",
                http_response,
                {"uri": url, "warc-content-id": warc_id},
                warc_id,
            )
            
            # Write both records
            handle.write(request_record)
            handle.write(response_record)
            handle.flush()
            
            # Update size
            total_length = len(request_record) + len(response_record)
            self._current_size += total_length
            
            # Create reference
            ref = WARCReference(
                warc_id=warc_id,
                file_path=str(file_path.relative_to(self.base_dir)),
                offset=offset,
                length=total_length,
                engagement_id=self.engagement_id,
                timestamp=datetime.now(timezone.utc),
            )
            
            logger.debug(f"Wrote WARC record: {warc_id[:8]}... ({total_length} bytes)")
            return ref
    
    def close(self) -> None:
        """Close current WARC file."""
        with self._lock:
            if self._current_handle:
                self._current_handle.close()
                self._current_handle = None
                logger.info(f"Closed WARC writer for engagement {self.engagement_id}")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False


def create_warc_writer(engagement_id: str, base_dir: Optional[Path] = None) -> WARCWriter:
    """
    Factory function to create a WARC writer.
    
    Args:
        engagement_id: Engagement identifier
        base_dir: Base directory (defaults to outputs/warc)
        
    Returns:
        Configured WARCWriter instance
    """
    if base_dir is None:
        from cyberAI.config import get_config
        config = get_config()
        base_dir = config.get_output_path("warc")
    
    return WARCWriter(base_dir=base_dir, engagement_id=engagement_id)
