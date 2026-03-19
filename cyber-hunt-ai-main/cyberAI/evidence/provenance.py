"""
Provenance tracking - links findings to WARC evidence.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)


@dataclass
class EvidenceRef:
    """Reference to evidence in WARC storage."""
    warc_ref: str  # warc://file.warc.gz#offset:length
    content_hash: str
    request_id: str
    response_id: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


class ProvenanceTracker:
    """
    Tracks provenance from findings to raw WARC captures.
    Maintains index of finding_id -> evidence_refs.
    """
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.index_file = output_dir / "provenance_index.jsonl"
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def link_finding_to_evidence(self, finding_id: str, 
                                 evidence_refs: List[EvidenceRef]) -> None:
        """Link a finding to its evidence."""
        entry = {
            "finding_id": finding_id,
            "evidence_refs": [ref.to_dict() for ref in evidence_refs],
            "linked_at": datetime.utcnow().isoformat()
        }
        
        with open(self.index_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        
        logger.info(f"Linked finding {finding_id} to {len(evidence_refs)} evidence refs")
    
    def get_evidence_for_finding(self, finding_id: str) -> List[EvidenceRef]:
        """Retrieve evidence refs for a finding."""
        if not self.index_file.exists():
            return []
        
        refs = []
        with open(self.index_file, 'r') as f:
            for line in f:
                entry = json.loads(line)
                if entry['finding_id'] == finding_id:
                    for ref_dict in entry['evidence_refs']:
                        ref_dict['timestamp'] = datetime.fromisoformat(ref_dict['timestamp'])
                        refs.append(EvidenceRef(**ref_dict))
        
        return refs
    
    def generate_evidence_pack(self, finding_id: str, 
                              warc_dir: Path, output_path: Path) -> None:
        """
        Generate evidence pack for a finding.
        Extracts relevant WARC records into a standalone archive.
        """
        import gzip
        
        evidence_refs = self.get_evidence_for_finding(finding_id)
        if not evidence_refs:
            logger.warning(f"No evidence found for finding {finding_id}")
            return
        
        with gzip.open(output_path, 'wb') as out_f:
            for ref in evidence_refs:
                warc_file = warc_dir / ref.warc_ref.split('://')[1].split('#')[0]
                offset_length = ref.warc_ref.split('#')[1]
                offset, length = map(int, offset_length.split(':'))
                
                if not warc_file.exists():
                    logger.warning(f"WARC file not found: {warc_file}")
                    continue
                
                with gzip.open(warc_file, 'rb') as in_f:
                    in_f.seek(offset)
                    record_data = in_f.read(length)
                    out_f.write(record_data)
        
        logger.info(f"Generated evidence pack: {output_path}")
