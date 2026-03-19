"""
HTTP capture integration for browser and API traffic.
Intercepts requests/responses and writes to WARC.
"""

from typing import Optional, Dict, Any
from pathlib import Path

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

from .warc_writer import WARCWriter, WARCRecord
from .provenance import ProvenanceTracker, EvidenceRef


class CaptureSession:
    """
    Manages evidence capture for a single engagement.
    Integrates with browser automation and HTTP clients.
    """
    
    def __init__(self, engagement_id: str, output_dir: Path):
        self.engagement_id = engagement_id
        self.warc_dir = output_dir / "warc"
        self.warc_writer = WARCWriter(self.warc_dir, engagement_id)
        self.provenance = ProvenanceTracker(output_dir / "provenance")
        self.request_map: Dict[str, WARCRecord] = {}
    
    def capture_request(self, request_id: str, method: str, url: str, 
                       headers: dict, body: Optional[bytes] = None) -> str:
        """Capture HTTP request and return WARC ref."""
        record = self.warc_writer.write_request(method, url, headers, body)
        self.request_map[request_id] = record
        return record.warc_ref
    
    def capture_response(self, request_id: str, url: str, status_code: int,
                        headers: dict, body: Optional[bytes] = None) -> str:
        """Capture HTTP response and return WARC ref."""
        record = self.warc_writer.write_response(url, status_code, headers, body)
        return record.warc_ref
    
    def link_finding(self, finding_id: str, request_ids: list) -> None:
        """Link a finding to captured requests."""
        evidence_refs = []
        
        for req_id in request_ids:
            if req_id in self.request_map:
                record = self.request_map[req_id]
                ref = EvidenceRef(
                    warc_ref=record.warc_ref,
                    content_hash=record.content_hash,
                    request_id=req_id
                )
                evidence_refs.append(ref)
        
        if evidence_refs:
            self.provenance.link_finding_to_evidence(finding_id, evidence_refs)
            logger.info(f"Linked finding {finding_id} to {len(evidence_refs)} captures")
    
    def close(self) -> None:
        """Close capture session."""
        self.warc_writer.close()
