"""
Storage layer for CyberAI platform.
Handles WARC writing, evidence storage, and content-addressed archival.
"""

from .warc_writer import WARCWriter, WARCReference, create_warc_writer
from .evidence_store import EvidenceStore

try:
    from .integration import WARCIntegration, capture_to_warc
    _has_integration = True
except ImportError:
    _has_integration = False

__all__ = [
    "WARCWriter",
    "WARCReference",
    "create_warc_writer",
    "EvidenceStore",
]

if _has_integration:
    __all__.extend(["WARCIntegration", "capture_to_warc"])
