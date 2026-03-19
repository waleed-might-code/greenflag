"""
Insertion point extraction and analysis module.
Handles nested encoding, multi-layer extraction, novelty tracking, and test replay.
"""

from .canonicalizer import (
    RequestCanonicalizer,
    CanonicalRequest,
    ASTNode,
    NodeType,
)
from .encoding_detector import (
    EncodingDetector,
    EncodingDetectionResult,
    NestedEncodingExtractor,
)
from .extractor import (
    InsertionPointExtractor,
    InsertionPoint,
    NoveltyIndex,
    NoveltyStats,
)
from .novelty import (
    NoveltyTracker,
    InsertionPointShape,
)
from .payload_encoder import (
    PayloadEncoder,
    PayloadGenerator,
)
from .replay_engine import (
    ReplayEngine,
    ReplayRequest,
    ReplayResult,
)
from .test_worker_integration import (
    TestWorkerIntegration,
    TestJob,
)
from .integration import (
    InsertionPointPipeline,
    integrate_with_crawler,
)

__all__ = [
    # Canonicalization
    "RequestCanonicalizer",
    "CanonicalRequest",
    "ASTNode",
    "NodeType",
    # Encoding detection
    "EncodingDetector",
    "EncodingDetectionResult",
    "NestedEncodingExtractor",
    # Extraction
    "InsertionPointExtractor",
    "InsertionPoint",
    "NoveltyIndex",
    "NoveltyStats",
    # Novelty tracking
    "NoveltyTracker",
    "InsertionPointShape",
    # Payload generation
    "PayloadEncoder",
    "PayloadGenerator",
    # Replay
    "ReplayEngine",
    "ReplayRequest",
    "ReplayResult",
    # Test worker integration
    "TestWorkerIntegration",
    "TestJob",
    # Pipeline
    "InsertionPointPipeline",
    "integrate_with_crawler",
]
