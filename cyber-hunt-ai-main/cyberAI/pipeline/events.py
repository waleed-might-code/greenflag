"""
Event schemas for Kafka messages.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class RawCapture:
    """Raw HTTP request/response capture."""
    engagement_id: str
    url: str
    method: str
    request_headers: Dict[str, str]
    request_body: Optional[str]
    response_status: int
    response_headers: Dict[str, str]
    response_body: Optional[str]
    warc_ref: str
    role: Optional[str]
    timestamp: str
    
    def to_dict(self):
        return asdict(self)


@dataclass
class ParsedRequest:
    """Canonicalized request with insertion points."""
    engagement_id: str
    request_id: str
    method: str
    url_template: str
    host: str
    query_params: List[Dict[str, str]]
    headers: List[Dict[str, str]]
    body_ast: Optional[Dict]
    warc_ref: str
    timestamp: str
    
    def to_dict(self):
        return asdict(self)


@dataclass
class InsertionPointEvent:
    """Discovered insertion point."""
    engagement_id: str
    request_id: str
    location: str
    encoding_layers: List[str]
    inferred_type: str
    shape_hash: str
    timestamp: str
    
    def to_dict(self):
        return asdict(self)


@dataclass
class TestEvent:
    """Security test execution event."""
    engagement_id: str
    test_type: str
    endpoint: str
    role: str
    payload: Optional[str]
    result: str
    timestamp: str
    
    def to_dict(self):
        return asdict(self)



@dataclass
class FindingEvent:
    """Security finding discovered."""
    engagement_id: str
    title: str
    severity: str
    category: str
    asset: str
    description: str
    evidence_warc_refs: List[str]
    metadata: Dict
    timestamp: str
    
    def to_dict(self):
        return asdict(self)
