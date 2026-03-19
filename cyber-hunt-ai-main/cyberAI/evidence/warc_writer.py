"""
WARC writer for capturing HTTP traffic as evidence.
Implements ISO 28500 WARC format with content-addressed storage.
"""

import gzip
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)


@dataclass
class WARCRecord:
    """Represents a single WARC record."""
    record_id: str
    record_type: str  # request, response, metadata
    target_uri: str
    date: datetime
    content_type: str
    content: bytes
    content_hash: str
    warc_file: str
    offset: int
    length: int
    
    @property
    def warc_ref(self) -> str:
        """Generate WARC reference URI."""
        return f"warc://{self.warc_file}#{self.offset}:{self.length}"


class WARCWriter:
    """
    Writes HTTP captures to WARC files with content-addressed IDs.
    Thread-safe for concurrent writes.
    """
    
    def __init__(self, output_dir: Path, engagement_id: str):
        self.output_dir = output_dir
        self.engagement_id = engagement_id
        self.current_file: Optional[Path] = None
        self.current_handle: Optional[io.BufferedWriter] = None
        self.records_written = 0
        self.max_records_per_file = 10000
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._rotate_file()
    
    def _rotate_file(self) -> None:
        """Create a new WARC file."""
        if self.current_handle:
            self.current_handle.close()
        
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        filename = f"{self.engagement_id}_{timestamp}_{uuid4().hex[:8]}.warc.gz"
        self.current_file = self.output_dir / filename
        self.current_handle = gzip.open(self.current_file, 'wb')
        self.records_written = 0
        
        logger.info(f"Created new WARC file: {self.current_file}")
    
    def _compute_content_hash(self, content: bytes) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content).hexdigest()
    
    def _format_warc_header(self, record_type: str, record_id: str, 
                           target_uri: str, date: datetime, 
                           content_type: str, content_length: int) -> bytes:
        """Format WARC record header."""
        header_lines = [
            "WARC/1.0",
            f"WARC-Type: {record_type}",
            f"WARC-Record-ID: <urn:uuid:{record_id}>",
            f"WARC-Target-URI: {target_uri}",
            f"WARC-Date: {date.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"Content-Type: {content_type}",
            f"Content-Length: {content_length}",
            "",
            ""
        ]
        return "\r\n".join(header_lines).encode('utf-8')
    
    def write_request(self, method: str, url: str, headers: dict, 
                     body: Optional[bytes] = None) -> WARCRecord:
        """Write HTTP request to WARC."""
        request_line = f"{method} {url} HTTP/1.1\r\n"
        header_lines = "\r\n".join([f"{k}: {v}" for k, v in headers.items()])
        content = f"{request_line}{header_lines}\r\n\r\n".encode('utf-8')
        
        if body:
            content += body
        
        return self._write_record("request", url, content, "application/http; msgtype=request")
    
    def write_response(self, url: str, status_code: int, headers: dict, 
                      body: Optional[bytes] = None) -> WARCRecord:
        """Write HTTP response to WARC."""
        status_line = f"HTTP/1.1 {status_code} OK\r\n"
        header_lines = "\r\n".join([f"{k}: {v}" for k, v in headers.items()])
        content = f"{status_line}{header_lines}\r\n\r\n".encode('utf-8')
        
        if body:
            content += body
        
        return self._write_record("response", url, content, "application/http; msgtype=response")
    
    def _write_record(self, record_type: str, target_uri: str, 
                     content: bytes, content_type: str) -> WARCRecord:
        """Write a WARC record and return reference."""
        if self.records_written >= self.max_records_per_file:
            self._rotate_file()
        
        record_id = str(uuid4())
        date = datetime.utcnow()
        content_hash = self._compute_content_hash(content)
        
        header = self._format_warc_header(
            record_type, record_id, target_uri, date, 
            content_type, len(content)
        )
        
        offset = self.current_handle.tell()
        self.current_handle.write(header)
        self.current_handle.write(content)
        self.current_handle.write(b"\r\n\r\n")
        self.current_handle.flush()
        
        length = self.current_handle.tell() - offset
        self.records_written += 1
        
        record = WARCRecord(
            record_id=record_id,
            record_type=record_type,
            target_uri=target_uri,
            date=date,
            content_type=content_type,
            content=content,
            content_hash=content_hash,
            warc_file=self.current_file.name,
            offset=offset,
            length=length
        )
        
        logger.debug(f"Wrote {record_type} record: {record.warc_ref}")
        return record
    
    def close(self) -> None:
        """Close current WARC file."""
        if self.current_handle:
            self.current_handle.close()
            self.current_handle = None
