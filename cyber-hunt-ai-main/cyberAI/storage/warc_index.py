"""
WARC Index for O(1) lookups at scale.

Problem: At millions of WARC records, seeking through gzipped files is too slow.
Solution: Maintain a separate index file mapping warc_id → (file, offset, length).

Index format: JSON Lines (one record per line for append-only writes)
{
  "warc_id": "sha256_hash",
  "file_path": "eng_123/eng_123_20240101_000.warc.gz",
  "offset": 1234,
  "length": 5678,
  "timestamp": "2024-01-01T12:00:00Z",
  "content_hash": "sha256_of_response_body"  # For dedup
}
"""

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class WARCIndexEntry:
    """Index entry for fast WARC lookups."""
    warc_id: str
    file_path: str
    offset: int
    length: int
    timestamp: datetime
    content_hash: Optional[str] = None  # For dedup
    
    def to_dict(self) -> dict:
        return {
            "warc_id": self.warc_id,
            "file_path": self.file_path,
            "offset": self.offset,
            "length": self.length,
            "timestamp": self.timestamp.isoformat(),
            "content_hash": self.content_hash,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "WARCIndexEntry":
        return cls(
            warc_id=data["warc_id"],
            file_path=data["file_path"],
            offset=data["offset"],
            length=data["length"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            content_hash=data.get("content_hash"),
        )


class WARCIndex:
    """
    Fast index for WARC record lookups.
    
    Features:
    - O(1) lookup by warc_id
    - Append-only writes (thread-safe)
    - In-memory cache with disk persistence
    - Content-hash based deduplication support
    
    Usage:
        index = WARCIndex("outputs/warc/eng_123/index.jsonl")
        index.add_entry(warc_id, file_path, offset, length, content_hash)
        entry = index.lookup(warc_id)
    """
    
    def __init__(self, index_path: Path | str):
        """
        Initialize WARC index.
        
        Args:
            index_path: Path to index file (JSON Lines format)
        """
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._cache: dict[str, WARCIndexEntry] = {}
        self._content_hash_map: dict[str, str] = {}  # content_hash → warc_id
        self._lock = threading.Lock()
        
        # Load existing index
        self._load_index()
    
    def _load_index(self) -> None:
        """Load index from disk into memory."""
        if not self.index_path.exists():
            logger.info(f"Creating new WARC index: {self.index_path}")
            return
        
        try:
            with open(self.index_path, "r") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        entry = WARCIndexEntry.from_dict(data)
                        self._cache[entry.warc_id] = entry
                        
                        # Build content hash map for dedup
                        if entry.content_hash:
                            self._content_hash_map[entry.content_hash] = entry.warc_id
                    
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping malformed index line {line_num}: {e}")
            
            logger.info(f"Loaded {len(self._cache)} entries from WARC index")
        
        except Exception as e:
            logger.error(f"Failed to load WARC index: {e}")
    
    def add_entry(
        self,
        warc_id: str,
        file_path: str,
        offset: int,
        length: int,
        timestamp: datetime,
        content_hash: Optional[str] = None,
    ) -> None:
        """
        Add entry to index.
        
        Args:
            warc_id: Content-addressed WARC ID
            file_path: Relative path to WARC file
            offset: Byte offset in file
            length: Record length
            timestamp: Capture timestamp
            content_hash: SHA-256 of response body (for dedup)
        """
        with self._lock:
            entry = WARCIndexEntry(
                warc_id=warc_id,
                file_path=file_path,
                offset=offset,
                length=length,
                timestamp=timestamp,
                content_hash=content_hash,
            )
            
            # Add to cache
            self._cache[warc_id] = entry
            
            if content_hash:
                self._content_hash_map[content_hash] = warc_id
            
            # Append to disk
            try:
                with open(self.index_path, "a") as f:
                    f.write(json.dumps(entry.to_dict()) + "\n")
            except Exception as e:
                logger.error(f"Failed to write index entry: {e}")
    
    def lookup(self, warc_id: str) -> Optional[WARCIndexEntry]:
        """
        Lookup WARC record by ID.
        
        Args:
            warc_id: Content-addressed WARC ID
            
        Returns:
            WARCIndexEntry if found, None otherwise
        """
        return self._cache.get(warc_id)
    
    def lookup_by_content_hash(self, content_hash: str) -> Optional[WARCIndexEntry]:
        """
        Lookup WARC record by content hash (for dedup).
        
        Args:
            content_hash: SHA-256 of response body
            
        Returns:
            WARCIndexEntry if found, None otherwise
        """
        warc_id = self._content_hash_map.get(content_hash)
        if warc_id:
            return self._cache.get(warc_id)
        return None
    
    def get_stats(self) -> dict:
        """Get index statistics."""
        return {
            "total_entries": len(self._cache),
            "unique_content_hashes": len(self._content_hash_map),
            "index_file": str(self.index_path),
            "index_size_bytes": self.index_path.stat().st_size if self.index_path.exists() else 0,
        }
