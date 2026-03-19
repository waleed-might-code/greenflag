"""
Evidence store for managing WARC-backed security findings.
Provides evidence pack generation and WARC record extraction.
"""

import gzip
import json
import zipfile
from pathlib import Path
from typing import Optional

from loguru import logger

from cyberAI.storage.warc_writer import WARCReference


class EvidenceStore:
    """
    Manages evidence extraction and packaging from WARC archives.
    Links security findings to raw HTTP captures for audit trail.
    """
    
    def __init__(self, warc_base_dir: Path):
        """
        Initialize evidence store.
        
        Args:
            warc_base_dir: Base directory containing WARC files
        """
        self.warc_base_dir = Path(warc_base_dir)
    
    def read_warc_record(self, ref: WARCReference) -> bytes:
        """
        Read a WARC record by reference.
        
        Args:
            ref: WARC reference with file path and offset
            
        Returns:
            Raw WARC record bytes
        """
        file_path = self.warc_base_dir / ref.file_path
        
        if not file_path.exists():
            logger.error(f"WARC file not found: {file_path}")
            raise FileNotFoundError(f"WARC file not found: {file_path}")
        
        try:
            with gzip.open(file_path, "rb") as f:
                f.seek(ref.offset)
                return f.read(ref.length)
        except Exception as e:
            logger.error(f"Failed to read WARC record: {e}")
            raise
    
    def extract_http_from_warc(self, record_bytes: bytes) -> tuple[dict, bytes]:
        """
        Extract HTTP headers and body from WARC record.
        
        Args:
            record_bytes: Raw WARC record
            
        Returns:
            Tuple of (headers_dict, body_bytes)
        """
        try:
            # Split WARC headers from HTTP content
            parts = record_bytes.split(b"\r\n\r\n", 2)
            if len(parts) < 2:
                return {}, b""
            
            http_content = parts[1]
            
            # Parse HTTP status/request line and headers
            http_parts = http_content.split(b"\r\n\r\n", 1)
            if len(http_parts) < 2:
                return {}, http_content
            
            header_block = http_parts[0].decode("utf-8", errors="replace")
            body = http_parts[1]
            
            headers = {}
            lines = header_block.split("\r\n")
            
            # Skip first line (status or request line)
            for line in lines[1:]:
                if ": " in line:
                    key, value = line.split(": ", 1)
                    headers[key] = value
            
            return headers, body
        except Exception as e:
            logger.error(f"Failed to parse WARC record: {e}")
            return {}, b""
    
    def generate_evidence_pack(
        self,
        finding_id: str,
        warc_refs: list[WARCReference],
        output_dir: Path,
        include_screenshots: bool = True,
        screenshot_paths: Optional[list[Path]] = None,
    ) -> Path:
        """
        Generate evidence pack ZIP for a finding.
        
        Args:
            finding_id: Finding identifier
            warc_refs: List of WARC references for this finding
            output_dir: Output directory for evidence pack
            include_screenshots: Include screenshots if available
            screenshot_paths: Optional list of screenshot paths
            
        Returns:
            Path to generated evidence pack ZIP
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        pack_path = output_dir / f"evidence_{finding_id}.zip"
        
        with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add manifest
            manifest = {
                "finding_id": finding_id,
                "evidence_count": len(warc_refs),
                "warc_references": [ref.to_dict() for ref in warc_refs],
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            
            # Extract and add HTTP request/response pairs
            for idx, ref in enumerate(warc_refs):
                try:
                    record_bytes = self.read_warc_record(ref)
                    headers, body = self.extract_http_from_warc(record_bytes)
                    
                    # Save headers
                    headers_json = json.dumps(headers, indent=2)
                    zf.writestr(f"evidence_{idx:03d}_headers.json", headers_json)
                    
                    # Save body
                    if body:
                        # Try to pretty-print JSON bodies
                        try:
                            if headers.get("Content-Type", "").startswith("application/json"):
                                body_obj = json.loads(body.decode("utf-8", errors="replace"))
                                body_str = json.dumps(body_obj, indent=2)
                                zf.writestr(f"evidence_{idx:03d}_body.json", body_str)
                            else:
                                zf.writestr(f"evidence_{idx:03d}_body.bin", body)
                        except:
                            zf.writestr(f"evidence_{idx:03d}_body.bin", body)
                    
                    # Save raw WARC record for audit
                    zf.writestr(f"evidence_{idx:03d}_raw.warc", record_bytes)
                    
                except Exception as e:
                    logger.error(f"Failed to extract evidence {idx} for finding {finding_id}: {e}")
                    # Add error note
                    zf.writestr(
                        f"evidence_{idx:03d}_ERROR.txt",
                        f"Failed to extract: {str(e)}\nWARC ref: {ref.to_uri()}"
                    )
            
            # Add screenshots if provided
            if include_screenshots and screenshot_paths:
                for idx, screenshot_path in enumerate(screenshot_paths):
                    if screenshot_path and Path(screenshot_path).exists():
                        zf.write(screenshot_path, f"screenshot_{idx:03d}.png")
        
        logger.info(f"Generated evidence pack: {pack_path} ({len(warc_refs)} records)")
        return pack_path
    
    def extract_evidence_summary(self, ref: WARCReference) -> dict:
        """
        Extract summary information from a WARC record.
        
        Args:
            ref: WARC reference
            
        Returns:
            Dictionary with summary info (method, url, status, content-type, size)
        """
        try:
            record_bytes = self.read_warc_record(ref)
            headers, body = self.extract_http_from_warc(record_bytes)
            
            # Parse first line for method/status
            parts = record_bytes.split(b"\r\n\r\n", 2)
            if len(parts) >= 2:
                http_content = parts[1]
                first_line = http_content.split(b"\r\n")[0].decode("utf-8", errors="replace")
                
                summary = {
                    "warc_id": ref.warc_id,
                    "timestamp": ref.timestamp.isoformat() if hasattr(ref.timestamp, 'isoformat') else str(ref.timestamp),
                    "first_line": first_line,
                    "content_type": headers.get("Content-Type", "unknown"),
                    "content_length": len(body),
                    "uri": ref.to_uri(),
                }
                
                return summary
        except Exception as e:
            logger.error(f"Failed to extract summary: {e}")
        
        return {
            "warc_id": ref.warc_id,
            "error": "Failed to extract",
            "uri": ref.to_uri(),
        }
