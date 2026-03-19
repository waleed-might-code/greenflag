"""
Provenance pipeline: Links every finding to WARC evidence at scale.

Flow:
1. Capture HTTP traffic → WARC writer (content-addressed)
2. Parse requests → Extract insertion points
3. Run security tests → Generate findings with WARC refs
4. Store in database → Enable evidence pack generation

Key innovation: Store only WARC refs in DB, not full responses.
At millions of requests, this is the only scalable approach.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

from loguru import logger

from cyberAI.storage.database import (
    ProvenanceDB, Endpoint, Request, InsertionPoint, Finding,
    Severity, FindingStatus
)
from cyberAI.storage.warc_writer import WARCWriter, WARCReference


@dataclass
class CapturedRequest:
    """Raw HTTP request/response pair from crawler."""
    method: str
    url: str
    request_headers: dict
    request_body: bytes
    status_code: int
    reason: str
    response_headers: dict
    response_body: bytes
    role: str  # guest | user | admin
    engagement_id: str
    timestamp: Optional[datetime] = None


class RequestCanonicalizer:
    """
    Canonicalizes HTTP requests into templates for deduplication.
    
    Example:
        /api/users/123 → /api/users/{id}
        /api/users/456 → /api/users/{id}  (same template)
    """
    
    @staticmethod
    def canonicalize_path(path: str) -> str:
        """Replace numeric/UUID segments with placeholders."""
        segments = path.split("/")
        canonical = []
        
        for seg in segments:
            if not seg:
                canonical.append(seg)
            elif seg.isdigit():
                canonical.append("{id}")
            elif re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", seg, re.I):
                canonical.append("{uuid}")
            elif re.match(r"^[0-9a-f]{24,}$", seg, re.I):
                canonical.append("{hash}")
            else:
                canonical.append(seg)
        
        return "/".join(canonical)
    
    @staticmethod
    def extract_url_template(url: str) -> tuple[str, str]:
        """
        Extract URL template and host.
        
        Returns:
            (url_template, host)
        """
        parsed = urlparse(url)
        host = parsed.netloc
        path_template = RequestCanonicalizer.canonicalize_path(parsed.path)
        
        return path_template, host
    
    @staticmethod
    def classify_endpoint(url: str, headers: dict, body: bytes) -> str:
        """
        Classify endpoint type.
        
        Returns:
            api | form | static | graphql | websocket
        """
        content_type = headers.get("Content-Type", "").lower()
        
        if "graphql" in url.lower() or "graphql" in content_type:
            return "graphql"
        
        if content_type.startswith("application/json"):
            return "api"
        
        if content_type.startswith("application/x-www-form-urlencoded") or \
           content_type.startswith("multipart/form-data"):
            return "form"
        
        if url.endswith((".js", ".css", ".png", ".jpg", ".gif", ".svg", ".woff", ".woff2")):
            return "static"
        
        return "api" if "/api/" in url else "form"


class InsertionPointExtractor:
    """
    Extracts insertion points from HTTP requests.
    
    An insertion point is any place where user-controlled input can be supplied:
    - URL path segments
    - Query parameters
    - Request headers
    - Body fields (JSON, form-data, XML)
    - Nested/encoded values (base64, JSON-in-JSON)
    """
    
    @staticmethod
    def extract(request: CapturedRequest) -> list[InsertionPoint]:
        """Extract all insertion points from a request."""
        points = []
        request_id = str(uuid4())
        
        # Path segments
        parsed = urlparse(request.url)
        segments = [s for s in parsed.path.split("/") if s]
        for idx, seg in enumerate(segments):
            if seg and not seg.startswith("{"):  # Skip already templated
                points.append(InsertionPoint(
                    id=str(uuid4()),
                    request_id=request_id,
                    location=f"path_segment_{idx}",
                    encoding_layers=[],
                    inferred_type=InsertionPointExtractor._infer_type(seg),
                    shape_hash=hashlib.sha256(f"path_{idx}".encode()).hexdigest()[:16],
                    engagement_id=request.engagement_id,
                ))
        
        # Query parameters
        query_params = parse_qs(parsed.query)
        for key, values in query_params.items():
            for value in values:
                points.append(InsertionPoint(
                    id=str(uuid4()),
                    request_id=request_id,
                    location=f"query.{key}",
                    encoding_layers=[],
                    inferred_type=InsertionPointExtractor._infer_type(value),
                    shape_hash=hashlib.sha256(f"query_{key}".encode()).hexdigest()[:16],
                    engagement_id=request.engagement_id,
                ))
        
        # Headers (only user-controllable ones)
        user_headers = ["X-User-Id", "X-Role", "X-Tenant-Id", "Authorization", "Cookie"]
        for header in user_headers:
            if header in request.request_headers:
                points.append(InsertionPoint(
                    id=str(uuid4()),
                    request_id=request_id,
                    location=f"header.{header}",
                    encoding_layers=[],
                    inferred_type="token" if header == "Authorization" else "string",
                    shape_hash=hashlib.sha256(f"header_{header}".encode()).hexdigest()[:16],
                    engagement_id=request.engagement_id,
                ))
        
        # Body fields (JSON only for now)
        content_type = request.request_headers.get("Content-Type", "")
        if "application/json" in content_type and request.request_body:
            try:
                body_json = json.loads(request.request_body.decode("utf-8", errors="replace"))
                points.extend(InsertionPointExtractor._extract_json_points(
                    body_json, "body", request_id, request.engagement_id
                ))
            except:
                pass
        
        return points
    
    @staticmethod
    def _extract_json_points(obj, prefix: str, request_id: str, engagement_id: str, depth: int = 0) -> list[InsertionPoint]:
        """Recursively extract insertion points from JSON."""
        points = []
        
        if depth > 5:  # Prevent infinite recursion
            return points
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                location = f"{prefix}.{key}"
                
                if isinstance(value, (dict, list)):
                    points.extend(InsertionPointExtractor._extract_json_points(
                        value, location, request_id, engagement_id, depth + 1
                    ))
                else:
                    # Check for nested encoding (base64, etc.)
                    encoding_layers = []
                    inferred_type = InsertionPointExtractor._infer_type(str(value))
                    
                    if isinstance(value, str) and InsertionPointExtractor._looks_like_base64(value):
                        encoding_layers.append("base64")
                        # Could decode and recurse here for nested JSON
                    
                    points.append(InsertionPoint(
                        id=str(uuid4()),
                        request_id=request_id,
                        location=location,
                        encoding_layers=encoding_layers,
                        inferred_type=inferred_type,
                        shape_hash=hashlib.sha256(location.encode()).hexdigest()[:16],
                        engagement_id=engagement_id,
                    ))
        
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    points.extend(InsertionPointExtractor._extract_json_points(
                        item, f"{prefix}[{idx}]", request_id, engagement_id, depth + 1
                    ))
        
        return points
    
    @staticmethod
    def _infer_type(value: str) -> str:
        """Infer the type of a value."""
        if not value:
            return "string"
        
        if value.isdigit():
            return "id"
        
        if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", value, re.I):
            return "uuid"
        
        if re.match(r"^[A-Za-z0-9+/=]{20,}$", value):
            return "token"
        
        if "@" in value and "." in value:
            return "email"
        
        if value.startswith("http://") or value.startswith("https://"):
            return "url"
        
        return "string"
    
    @staticmethod
    def _looks_like_base64(value: str) -> bool:
        """Check if a string looks like base64."""
        if len(value) < 16:
            return False
        return bool(re.match(r"^[A-Za-z0-9+/=]+$", value))


class ProvenancePipeline:
    """
    Main pipeline that orchestrates provenance tracking.
    
    Usage:
        pipeline = ProvenancePipeline(engagement_id="eng_123")
        
        # Capture and store
        warc_ref = pipeline.capture_request(
            method="GET",
            url="https://api.example.com/users/123",
            ...
        )
        
        # Generate finding with evidence
        pipeline.create_finding(
            title="BOLA on user endpoint",
            severity=Severity.HIGH,
            category="BOLA",
            evidence_request_ids=[request_id],
            ...
        )
    """
    
    def __init__(
        self,
        engagement_id: str,
        warc_base_dir: str = "outputs/warc",
        db_path: Optional[str] = None,
        postgres_url: Optional[str] = None,
    ):
        """
        Initialize provenance pipeline.
        
        Args:
            engagement_id: Engagement identifier
            warc_base_dir: Base directory for WARC storage
            db_path: SQLite database path (for dev)
            postgres_url: PostgreSQL URL (for production)
        """
        self.engagement_id = engagement_id
        self.warc_writer = WARCWriter(
            base_dir=warc_base_dir,
            engagement_id=engagement_id,
        )
        self.db = ProvenanceDB(db_path=db_path, postgres_url=postgres_url)
        
        logger.info(f"Provenance pipeline initialized for engagement {engagement_id}")
    
    def capture_request(self, captured: CapturedRequest) -> tuple[str, WARCReference]:
        """
        Capture a request/response pair and store with provenance.
        
        Returns:
            (request_id, warc_reference)
        """
        # Write to WARC (content-addressed)
        warc_ref = self.warc_writer.write_request_response(
            method=captured.method,
            url=captured.url,
            request_headers=captured.request_headers,
            request_body=captured.request_body,
            status_code=captured.status_code,
            reason=captured.reason,
            response_headers=captured.response_headers,
            response_body=captured.response_body,
        )
        
        # Extract endpoint template
        url_template, host = RequestCanonicalizer.extract_url_template(captured.url)
        classification = RequestCanonicalizer.classify_endpoint(
            captured.url, captured.response_headers, captured.response_body
        )
        
        # Create or update endpoint
        endpoint_id = hashlib.sha256(
            f"{captured.method}:{url_template}:{self.engagement_id}".encode()
        ).hexdigest()[:16]
        
        endpoint = Endpoint(
            id=endpoint_id,
            method=captured.method,
            url_template=url_template,
            host=host,
            classification=classification,
            sensitivity="authenticated" if "Authorization" in captured.request_headers else "public",
            auth_required="Authorization" in captured.request_headers,
            first_seen=captured.timestamp or datetime.now(timezone.utc),
            last_seen=captured.timestamp or datetime.now(timezone.utc),
            engagement_id=self.engagement_id,
        )
        self.db.insert_endpoint(endpoint)
        
        # Create request record
        request_id = str(uuid4())
        request = Request(
            id=request_id,
            endpoint_id=endpoint_id,
            warc_ref=warc_ref.to_dict(),
            canonical_request_id=warc_ref.warc_id,  # Content-addressed dedup
            role=captured.role,
            timestamp=captured.timestamp or datetime.now(timezone.utc),
            engagement_id=self.engagement_id,
            method=captured.method,
            url=captured.url,
            status_code=captured.status_code,
        )
        self.db.insert_request(request)
        
        # Extract and store insertion points
        insertion_points = InsertionPointExtractor.extract(captured)
        for point in insertion_points:
            point.request_id = request_id  # Link to this request
            
            # Check novelty
            is_novel = self.db.check_shape_novelty(point.shape_hash, self.engagement_id)
            if is_novel:
                logger.debug(f"Novel insertion point: {point.location} (shape: {point.shape_hash})")
            
            self.db.insert_insertion_point(point)
        
        logger.debug(
            f"Captured {captured.method} {url_template} → "
            f"WARC {warc_ref.warc_id[:8]}... ({len(insertion_points)} insertion points)"
        )
        
        return request_id, warc_ref

    
    def create_finding(
        self,
        title: str,
        severity: Severity,
        category: str,
        description: str,
        asset: str,
        evidence_request_ids: list[str],
        metadata: Optional[dict] = None,
    ) -> Finding:
        """
        Create a security finding with WARC evidence links.
        
        Args:
            title: Finding title
            severity: Severity level
            category: Category (BOLA, IDOR, XSS, etc.)
            description: Detailed description
            asset: Affected asset (URL/endpoint)
            evidence_request_ids: List of request IDs that prove this finding
            metadata: Additional context
            
        Returns:
            Created Finding object
        """
        # Resolve request IDs to WARC refs
        evidence_warc_refs = []
        for req_id in evidence_request_ids:
            request = self.db.get_request_by_id(req_id)
            if request:
                evidence_warc_refs.append(request.warc_ref)
            else:
                logger.warning(f"Request {req_id} not found for finding evidence")
        
        if not evidence_warc_refs:
            logger.error(f"No evidence found for finding: {title}")
            raise ValueError("Finding must have at least one evidence reference")
        
        # Create finding
        finding = Finding(
            id=str(uuid4()),
            title=title,
            severity=severity,
            category=category,
            description=description,
            asset=asset,
            evidence_warc_refs=evidence_warc_refs,
            status=FindingStatus.NEW,
            engagement_id=self.engagement_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        
        self.db.insert_finding(finding)
        
        logger.info(
            f"Created finding: {title} ({severity.value}) with {len(evidence_warc_refs)} evidence refs"
        )
        
        return finding
    
    def get_findings(self, severity: Optional[Severity] = None) -> list[Finding]:
        """Get all findings for this engagement."""
        return self.db.get_findings_by_engagement(self.engagement_id, severity)
    
    def get_stats(self) -> dict:
        """Get statistics for this engagement."""
        return self.db.get_stats(self.engagement_id)
    
    def close(self):
        """Close all resources."""
        self.warc_writer.close()
        self.db.close()
        logger.info(f"Provenance pipeline closed for engagement {self.engagement_id}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_pipeline(engagement_id: str, **kwargs) -> ProvenancePipeline:
    """
    Factory function to create a provenance pipeline.
    
    Args:
        engagement_id: Engagement identifier
        **kwargs: Additional arguments for ProvenancePipeline
        
    Returns:
        Configured ProvenancePipeline instance
    """
    return ProvenancePipeline(engagement_id=engagement_id, **kwargs)
