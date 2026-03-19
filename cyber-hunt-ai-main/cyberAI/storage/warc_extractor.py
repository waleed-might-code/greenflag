"""
WARC data extraction and analysis utilities.
Tools for mining data from WARC archives at scale.
"""

import gzip
import json
from pathlib import Path
from typing import Iterator, Optional, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlparse

from loguru import logger


@dataclass
class WARCRecord:
    """Parsed WARC record."""
    record_type: str  # request or response
    warc_id: str
    target_uri: str
    date: str
    content_type: str
    content: bytes
    headers: Dict[str, str]


class WARCExtractor:
    """
    Extract and analyze data from WARC archives.
    
    Usage:
        extractor = WARCExtractor("outputs/warc/eng_001")
        
        # Extract all API responses
        for record in extractor.extract_responses(content_type="application/json"):
            data = json.loads(record.content)
            # Process data...
        
        # Find all endpoints
        endpoints = extractor.discover_endpoints()
    """
    
    def __init__(self, warc_dir: Path | str):
        """Initialize extractor with WARC directory."""
        self.warc_dir = Path(warc_dir)
        if not self.warc_dir.exists():
            raise FileNotFoundError(f"WARC directory not found: {warc_dir}")
    
    def get_warc_files(self) -> list[Path]:
        """Get all WARC files in directory."""
        files = list(self.warc_dir.glob("*.warc.gz"))
        files.extend(self.warc_dir.glob("*.warc"))
        return sorted(files)
    
    def parse_warc_file(self, warc_file: Path) -> Iterator[WARCRecord]:
        """Parse WARC file and yield records."""
        try:
            if warc_file.suffix == ".gz":
                f = gzip.open(warc_file, "rb")
            else:
                f = open(warc_file, "rb")
            
            with f:
                while True:
                    record = self._read_warc_record(f)
                    if record is None:
                        break
                    yield record
        
        except Exception as e:
            logger.error(f"Error parsing {warc_file}: {e}")
    
    def _read_warc_record(self, f) -> Optional[WARCRecord]:
        """Read single WARC record from file."""
        # Read WARC header
        line = f.readline()
        if not line or not line.startswith(b"WARC/"):
            return None
        
        headers = {}
        while True:
            line = f.readline()
            if line == b"\r\n":
                break
            if b":" in line:
                key, value = line.decode("utf-8").strip().split(":", 1)
                headers[key.strip()] = value.strip()
        
        # Read content
        content_length = int(headers.get("Content-Length", 0))
        content = f.read(content_length)
        
        # Skip trailing newlines
        f.readline()
        f.readline()
        
        return WARCRecord(
            record_type=headers.get("WARC-Type", ""),
            warc_id=headers.get("WARC-Record-ID", ""),
            target_uri=headers.get("WARC-Target-URI", ""),
            date=headers.get("WARC-Date", ""),
            content_type=headers.get("Content-Type", ""),
            content=content,
            headers=headers
        )
    
    def extract_responses(
        self,
        content_type: Optional[str] = None,
        url_pattern: Optional[str] = None
    ) -> Iterator[WARCRecord]:
        """
        Extract response records from WARC files.
        
        Args:
            content_type: Filter by content type (e.g., "application/json")
            url_pattern: Filter by URL pattern (substring match)
        """
        for warc_file in self.get_warc_files():
            for record in self.parse_warc_file(warc_file):
                if record.record_type != "response":
                    continue
                
                if content_type and content_type not in record.content_type:
                    continue
                
                if url_pattern and url_pattern not in record.target_uri:
                    continue
                
                yield record
    
    def discover_endpoints(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover all unique endpoints from WARC archives.
        
        Returns:
            Dict mapping URL patterns to endpoint metadata
        """
        endpoints = {}
        
        for warc_file in self.get_warc_files():
            for record in self.parse_warc_file(warc_file):
                if record.record_type != "request":
                    continue
                
                # Parse URL
                parsed = urlparse(record.target_uri)
                path = parsed.path
                
                # Extract method from HTTP request line
                http_line = record.content.split(b"\r\n")[0].decode("utf-8", errors="ignore")
                method = http_line.split()[0] if http_line else "GET"
                
                # Create endpoint key
                key = f"{method} {path}"
                
                if key not in endpoints:
                    endpoints[key] = {
                        "method": method,
                        "path": path,
                        "url": record.target_uri,
                        "count": 0,
                        "first_seen": record.date,
                    }
                
                endpoints[key]["count"] += 1
                endpoints[key]["last_seen"] = record.date
        
        return endpoints
    
    def extract_json_data(self) -> Iterator[Dict[str, Any]]:
        """Extract all JSON data from API responses."""
        for record in self.extract_responses(content_type="application/json"):
            try:
                # Skip HTTP headers, get body
                body_start = record.content.find(b"\r\n\r\n")
                if body_start == -1:
                    continue
                
                body = record.content[body_start + 4:]
                data = json.loads(body)
                
                yield {
                    "url": record.target_uri,
                    "date": record.date,
                    "data": data
                }
            
            except json.JSONDecodeError:
                continue
    
    def extract_parameters(self) -> Dict[str, set]:
        """
        Extract all unique parameters from requests.
        
        Returns:
            Dict mapping parameter names to set of example values
        """
        params = {}
        
        for record in self.extract_responses():
            # Parse URL for query params
            parsed = urlparse(record.target_uri)
            if parsed.query:
                for param in parsed.query.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        if key not in params:
                            params[key] = set()
                        params[key].add(value[:100])  # Limit value length
        
        return params
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about WARC archives."""
        stats = {
            "total_files": 0,
            "total_records": 0,
            "requests": 0,
            "responses": 0,
            "unique_urls": set(),
            "content_types": {},
            "methods": {},
        }
        
        for warc_file in self.get_warc_files():
            stats["total_files"] += 1
            
            for record in self.parse_warc_file(warc_file):
                stats["total_records"] += 1
                
                if record.record_type == "request":
                    stats["requests"] += 1
                    # Extract method
                    http_line = record.content.split(b"\r\n")[0].decode("utf-8", errors="ignore")
                    method = http_line.split()[0] if http_line else "GET"
                    stats["methods"][method] = stats["methods"].get(method, 0) + 1
                
                elif record.record_type == "response":
                    stats["responses"] += 1
                    # Track content types
                    ct = record.content_type.split(";")[0].strip()
                    stats["content_types"][ct] = stats["content_types"].get(ct, 0) + 1
                
                stats["unique_urls"].add(record.target_uri)
        
        stats["unique_urls"] = len(stats["unique_urls"])
        return stats


def extract_data_from_engagement(engagement_id: str, output_dir: Optional[Path] = None):
    """
    Extract all data from an engagement's WARC archives.
    
    Args:
        engagement_id: Engagement identifier
        output_dir: Optional output directory for extracted data
    """
    warc_dir = Path(f"outputs/warc/{engagement_id}")
    if not warc_dir.exists():
        logger.error(f"No WARC data found for engagement: {engagement_id}")
        return
    
    extractor = WARCExtractor(warc_dir)
    
    # Get statistics
    stats = extractor.get_statistics()
    logger.info(f"WARC Statistics for {engagement_id}:")
    logger.info(f"  Files: {stats['total_files']}")
    logger.info(f"  Records: {stats['total_records']}")
    logger.info(f"  Requests: {stats['requests']}")
    logger.info(f"  Responses: {stats['responses']}")
    logger.info(f"  Unique URLs: {stats['unique_urls']}")
    
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract endpoints
        endpoints = extractor.discover_endpoints()
        with open(output_dir / "endpoints.json", "w") as f:
            json.dump(endpoints, f, indent=2)
        logger.info(f"Extracted {len(endpoints)} endpoints")
        
        # Extract JSON data
        json_data = list(extractor.extract_json_data())
        with open(output_dir / "json_responses.json", "w") as f:
            json.dump(json_data, f, indent=2)
        logger.info(f"Extracted {len(json_data)} JSON responses")
        
        # Extract parameters
        params = extractor.extract_parameters()
        params_serializable = {k: list(v) for k, v in params.items()}
        with open(output_dir / "parameters.json", "w") as f:
            json.dump(params_serializable, f, indent=2)
        logger.info(f"Extracted {len(params)} unique parameters")
