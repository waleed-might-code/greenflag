"""
Batched WARC writer for high-throughput capture at scale.

Problem: Writing one WARC record at a time is slow (disk I/O overhead).
Solution: Buffer records in memory and flush in batches.

Throughput target: 1000+ requests/second sustained.
"""

import gzip
import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from loguru import logger

from cyberAI.storage.warc_writer import WARCReference
from cyberAI.storage.warc_index import WARCIndex


@dataclass
class PendingRecord:
    """Record waiting to be written."""
    method: str
    url: str
    request_headers: dict
    request_body: bytes
    status_code: int
    reason: str
    response_headers: dict
    response_body: bytes
    timestamp: datetime
    content_hash: Optional[str] = None


class BatchedWARCWriter:
    """
    High-throughput WARC writer with batching and deduplication.
    
    Features:
    - In-memory buffer with configurable batch size
    - Automatic flush on size/time threshold
    - Content-based deduplication (skip duplicate responses)
    - Background flush thread for async writes
    - WARC index integration for fast lookups
    
    Usage:
        writer = BatchedWARCWriter(
            base_dir="outputs/warc",
            engagement_id="eng_123",
            batch_size=100,
            flush_interval_seconds=10
        )
        
        # Add records (non-blocking)
        ref = writer.add_record(method, url, ...)
        
        # Flush manually if needed
        writer.flush()
        
        # Close (flushes remaining records)
        writer.close()
    """
    
    def __init__(
        self,
        base_dir: Path | str,
        engagement_id: str,
        batch_size: int = 100,
        flush_interval_seconds: float = 10.0,
        enable_dedup: bool = True,
        max_file_size_mb: int = 100,
    ):
        """
        Initialize batched WARC writer.
        
        Args:
            base_dir: Base directory for WARC storage
            engagement_id: Engagement identifier
            batch_size: Number of records to buffer before flush
            flush_interval_seconds: Max time between flushes
            enable_dedup: Enable content-based deduplication
            max_file_size_mb: Max size per WARC file before rotation
        """
        self.base_dir = Path(base_dir)
        self.engagement_id = engagement_id
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self.enable_dedup = enable_dedup
        self.max_file_size = max_file_size_mb * 1024 * 1024
        
        # Create engagement directory
        self.engagement_dir = self.base_dir / engagement_id
        self.engagement_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize index
        index_path = self.engagement_dir / "index.jsonl"
        self.index = WARCIndex(index_path)
        
        # Buffer and state
        self._buffer: deque[PendingRecord] = deque()
        self._lock = threading.Lock()
        self._current_file: Optional[Path] = None
        self._current_handle: Optional[gzip.GzipFile] = None
        self._current_size = 0
        self._file_counter = 0
        self._last_flush = time.time()
        self._closed = False
        
        # Stats
        self._stats = {
            "records_written": 0,
            "records_deduped": 0,
            "bytes_written": 0,
            "flushes": 0,
        }
        
        # Start background flush thread
        self._flush_thread = threading.Thread(target=self._background_flush, daemon=True)
        self._flush_thread.start()
        
        logger.info(
            f"Batched WARC writer initialized: engagement={engagement_id}, "
            f"batch_size={batch_size}, flush_interval={flush_interval}s"
        )
    
    def add_record(
        self,
        method: str,
        url: str,
        request_headers: dict,
        request_body: bytes,
        status_code: int,
        reason: str,
        response_headers: dict,
        response_body: bytes,
    ) -> WARCReference:
        """
        Add a record to the buffer (non-blocking).
        
        Returns:
            WARCReference for linking from findings
        """
        if self._closed:
            raise RuntimeError("Writer is closed")
        
        timestamp = datetime.now(timezone.utc)
        
        # Compute content hash for dedup
        content_hash = None
        if self.enable_dedup:
            content_hash = hashlib.sha256(response_body).hexdigest()
            
            # Check if we've seen this content before
            existing = self.index.lookup_by_content_hash(content_hash)
            if existing:
                self._stats["records_deduped"] += 1
                logger.debug(f"Deduped record: {url} (content_hash={content_hash[:8]}...)")
                
                # Return reference to existing record
                return WARCReference(
                    warc_id=existing.warc_id,
                    file_path=existing.file_path,
                    offset=existing.offset,
                    length=existing.length,
                    engagement_id=self.engagement_id,
                    timestamp=existing.timestamp,
                )
        
        # Generate content-addressed ID
        warc_id = self._generate_content_id(method, url, request_headers)
        
        # Add to buffer
        record = PendingRecord(
            method=method,
            url=url,
            request_headers=request_headers,
            request_body=request_body,
            status_code=status_code,
            reason=reason,
            response_headers=response_headers,
            response_body=response_body,
            timestamp=timestamp,
            content_hash=content_hash,
        )
        
        with self._lock:
            self._buffer.append(record)
            
            # Flush if buffer is full
            if len(self._buffer) >= self.batch_size:
                self._flush_unlocked()
        
        # Create reference (optimistic - will be written on flush)
        ref = WARCReference(
            warc_id=warc_id,
            file_path="",  # Will be set on flush
            offset=0,  # Will be set on flush
            length=0,  # Will be set on flush
            engagement_id=self.engagement_id,
            timestamp=timestamp,
        )
        
        return ref
    
    def flush(self) -> None:
        """Flush buffered records to disk (blocking)."""
        with self._lock:
            self._flush_unlocked()
    
    def _flush_unlocked(self) -> None:
        """Flush without acquiring lock (caller must hold lock)."""
        if not self._buffer:
            return
        
        try:
            # Get current file
            file_path, handle = self._get_current_file()
            start_offset = self._current_size
            
            # Write all buffered records
            batch_size = len(self._buffer)
            bytes_written = 0
            
            while self._buffer:
                record = self._buffer.popleft()
                
                # Generate WARC ID
                warc_id = self._generate_content_id(
                    record.method, record.url, record.request_headers
                )
                
                # Format HTTP messages
                http_request = self._format_http_request(
                    record.method, record.url, record.request_headers, record.request_body
                )
                http_response = self._format_http_response(
                    record.status_code, record.reason, record.response_headers, record.response_body
                )
                
                # Create WARC records
                request_record = self._format_warc_record(
                    "request", http_request, {"uri": record.url, "warc-content-id": warc_id}, warc_id
                )
                response_record = self._format_warc_record(
                    "response", http_response, {"uri": record.url, "warc-content-id": warc_id}, warc_id
                )
                
                # Write
                record_offset = self._current_size
                handle.write(request_record)
                handle.write(response_record)
                
                record_length = len(request_record) + len(response_record)
                self._current_size += record_length
                bytes_written += record_length
                
                # Add to index
                self.index.add_entry(
                    warc_id=warc_id,
                    file_path=str(file_path.relative_to(self.base_dir)),
                    offset=record_offset,
                    length=record_length,
                    timestamp=record.timestamp,
                    content_hash=record.content_hash,
                )
                
                self._stats["records_written"] += 1
            
            handle.flush()
            self._stats["bytes_written"] += bytes_written
            self._stats["flushes"] += 1
            self._last_flush = time.time()
            
            logger.debug(
                f"Flushed {batch_size} records ({bytes_written} bytes) to {file_path.name}"
            )
        
        except Exception as e:
            logger.error(f"Failed to flush WARC records: {e}")
            raise
    
    def _background_flush(self) -> None:
        """Background thread that flushes on time interval."""
        while not self._closed:
            time.sleep(1.0)
            
            # Check if flush is needed
            with self._lock:
                if self._buffer and (time.time() - self._last_flush) >= self.flush_interval:
                    try:
                        self._flush_unlocked()
                    except Exception as e:
                        logger.error(f"Background flush failed: {e}")
    
    def _get_current_file(self) -> tuple[Path, gzip.GzipFile]:
        """Get current WARC file handle (creates new if needed)."""
        # Check if rotation needed
        if (
            self._current_handle is None
            or self._current_size >= self.max_file_size
        ):
            # Close current file
            if self._current_handle:
                self._current_handle.close()
            
            # Create new file
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"{self.engagement_id}_{timestamp}_{self._file_counter:03d}.warc.gz"
            self._current_file = self.engagement_dir / filename
            self._current_handle = gzip.open(self._current_file, "wb")
            self._current_size = 0
            self._file_counter += 1
            
            logger.info(f"Created new WARC file: {filename}")
        
        return self._current_file, self._current_handle
    
    def _generate_content_id(self, method: str, url: str, headers: dict) -> str:
        """Generate content-addressed ID for WARC record."""
        # Hash request line + key headers
        content = f"{method} {url}\n"
        for key in sorted(headers.keys()):
            if key.lower() not in ["cookie", "authorization", "date"]:
                content += f"{key}: {headers[key]}\n"
        
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _format_http_request(
        self, method: str, url: str, headers: dict, body: bytes
    ) -> bytes:
        """Format HTTP request message."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        
        lines = [f"{method} {path} HTTP/1.1"]
        lines.append(f"Host: {parsed.netloc}")
        
        for key, value in headers.items():
            lines.append(f"{key}: {value}")
        
        http_msg = "\r\n".join(lines) + "\r\n\r\n"
        return http_msg.encode() + body
    
    def _format_http_response(
        self, status_code: int, reason: str, headers: dict, body: bytes
    ) -> bytes:
        """Format HTTP response message."""
        lines = [f"HTTP/1.1 {status_code} {reason}"]
        
        for key, value in headers.items():
            lines.append(f"{key}: {value}")
        
        http_msg = "\r\n".join(lines) + "\r\n\r\n"
        return http_msg.encode() + body
    
    def _format_warc_record(
        self, record_type: str, content: bytes, headers: dict, warc_id: str
    ) -> bytes:
        """Format WARC record with headers."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        warc_headers = [
            "WARC/1.0",
            f"WARC-Type: {record_type}",
            f"WARC-Record-ID: <urn:uuid:{uuid4()}>",
            f"WARC-Date: {timestamp}",
            f"Content-Length: {len(content)}",
            f"Content-Type: application/http; msgtype={record_type}",
        ]
        
        for key, value in headers.items():
            warc_headers.append(f"WARC-{key.title()}: {value}")
        
        header_block = "\r\n".join(warc_headers) + "\r\n\r\n"
        return header_block.encode() + content + b"\r\n\r\n"
    
    def get_stats(self) -> dict:
        """Get writer statistics."""
        with self._lock:
            return {
                **self._stats,
                "buffer_size": len(self._buffer),
                "current_file": str(self._current_file) if self._current_file else None,
                "current_file_size": self._current_size,
                "index_stats": self.index.get_stats(),
            }
    
    def close(self) -> None:
        """Close writer and flush remaining records."""
        if self._closed:
            return
        
        self._closed = True
        
        # Flush remaining records
        with self._lock:
            if self._buffer:
                logger.info(f"Flushing {len(self._buffer)} remaining records...")
                self._flush_unlocked()
            
            # Close file
            if self._current_handle:
                self._current_handle.close()
                self._current_handle = None
        
        logger.info(
            f"Batched WARC writer closed: {self._stats['records_written']} records written, "
            f"{self._stats['records_deduped']} deduped"
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
