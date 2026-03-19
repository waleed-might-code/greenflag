"""
Database models and schema for provenance tracking.
Links every finding to WARC evidence via content-addressed references.

Schema design:
- endpoints: Discovered API/web endpoints
- requests: Individual HTTP requests with WARC refs
- insertion_points: Attack surface points extracted from requests
- findings: Security issues with evidence links
- engagement_config: Per-engagement scope and settings
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import uuid4

from loguru import logger

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logger.warning("psycopg2 not available, using SQLite fallback")

import sqlite3


class Severity(str, Enum):
    """Finding severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(str, Enum):
    """Finding lifecycle status."""
    NEW = "new"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    FIXED = "fixed"
    ACCEPTED_RISK = "accepted_risk"


@dataclass
class Endpoint:
    """Discovered endpoint (API or web page)."""
    id: str
    method: str
    url_template: str  # Path with placeholders: /api/users/{id}
    host: str
    classification: str  # api | form | static | graphql
    sensitivity: str  # public | authenticated | admin
    auth_required: bool
    first_seen: datetime
    last_seen: datetime
    engagement_id: str
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "method": self.method,
            "url_template": self.url_template,
            "host": self.host,
            "classification": self.classification,
            "sensitivity": self.sensitivity,
            "auth_required": self.auth_required,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "engagement_id": self.engagement_id,
        }


@dataclass
class Request:
    """Individual HTTP request with WARC reference."""
    id: str
    endpoint_id: str
    warc_ref: dict  # WARCReference.to_dict()
    canonical_request_id: Optional[str]  # For dedup
    role: str  # guest | user | admin
    timestamp: datetime
    engagement_id: str
    method: str
    url: str
    status_code: Optional[int] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "endpoint_id": self.endpoint_id,
            "warc_ref": self.warc_ref,
            "canonical_request_id": self.canonical_request_id,
            "role": self.role,
            "timestamp": self.timestamp.isoformat(),
            "engagement_id": self.engagement_id,
            "method": self.method,
            "url": self.url,
            "status_code": self.status_code,
        }


@dataclass
class InsertionPoint:
    """Attack surface insertion point."""
    id: str
    request_id: str
    location: str  # path_segment_3 | query.search | body.user.id | header.X-Role
    encoding_layers: list[str]  # ["json", "base64"]
    inferred_type: str  # id | string | token | email | url
    shape_hash: str  # For novelty tracking
    engagement_id: str
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "location": self.location,
            "encoding_layers": self.encoding_layers,
            "inferred_type": self.inferred_type,
            "shape_hash": self.shape_hash,
            "engagement_id": self.engagement_id,
        }


@dataclass
class Finding:
    """Security finding with WARC evidence links."""
    id: str
    title: str
    severity: Severity
    category: str  # BOLA | IDOR | XSS | SQLi | etc
    description: str
    asset: str  # Affected endpoint/URL
    evidence_warc_refs: list[dict]  # List of WARCReference.to_dict()
    status: FindingStatus
    engagement_id: str
    created_at: datetime
    updated_at: datetime
    metadata: dict = field(default_factory=dict)  # Additional context
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity.value if isinstance(self.severity, Enum) else self.severity,
            "category": self.category,
            "description": self.description,
            "asset": self.asset,
            "evidence_warc_refs": self.evidence_warc_refs,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "engagement_id": self.engagement_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }


class ProvenanceDB:
    """
    Database for provenance tracking at scale.
    
    Features:
    - Content-addressed WARC references (no full response storage)
    - Engagement-scoped data
    - Efficient finding → evidence lookup
    - Support for PostgreSQL (production) and SQLite (dev)
    """
    
    def __init__(self, db_path: Optional[str] = None, postgres_url: Optional[str] = None):
        """
        Initialize database connection.
        
        Args:
            db_path: SQLite database path (for dev/testing)
            postgres_url: PostgreSQL connection URL (for production)
        """
        self.use_postgres = postgres_url is not None and POSTGRES_AVAILABLE
        
        if self.use_postgres:
            self.conn = psycopg2.connect(postgres_url)
            logger.info("Connected to PostgreSQL")
        else:
            db_path = db_path or "outputs/provenance.db"
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            logger.info(f"Connected to SQLite: {db_path}")
        
        self._init_schema()
    
    def _init_schema(self):
        """Create database schema if not exists."""
        cursor = self.conn.cursor()
        
        if self.use_postgres:
            # PostgreSQL schema
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS endpoints (
                    id TEXT PRIMARY KEY,
                    method TEXT NOT NULL,
                    url_template TEXT NOT NULL,
                    host TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    auth_required BOOLEAN NOT NULL,
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL,
                    engagement_id TEXT NOT NULL,
                    UNIQUE(method, url_template, engagement_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    endpoint_id TEXT NOT NULL REFERENCES endpoints(id),
                    warc_ref JSONB NOT NULL,
                    canonical_request_id TEXT,
                    role TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    engagement_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status_code INTEGER
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insertion_points (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES requests(id),
                    location TEXT NOT NULL,
                    encoding_layers JSONB NOT NULL,
                    inferred_type TEXT NOT NULL,
                    shape_hash TEXT NOT NULL,
                    engagement_id TEXT NOT NULL
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    evidence_warc_refs JSONB NOT NULL,
                    status TEXT NOT NULL,
                    engagement_id TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    metadata JSONB
                )
            """)
            
            # Indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_engagement ON requests(engagement_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_engagement ON findings(engagement_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_insertion_points_shape ON insertion_points(shape_hash)")
        
        else:
            # SQLite schema
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS endpoints (
                    id TEXT PRIMARY KEY,
                    method TEXT NOT NULL,
                    url_template TEXT NOT NULL,
                    host TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    auth_required INTEGER NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    engagement_id TEXT NOT NULL,
                    UNIQUE(method, url_template, engagement_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    endpoint_id TEXT NOT NULL,
                    warc_ref TEXT NOT NULL,
                    canonical_request_id TEXT,
                    role TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    engagement_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status_code INTEGER,
                    FOREIGN KEY(endpoint_id) REFERENCES endpoints(id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insertion_points (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    location TEXT NOT NULL,
                    encoding_layers TEXT NOT NULL,
                    inferred_type TEXT NOT NULL,
                    shape_hash TEXT NOT NULL,
                    engagement_id TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES requests(id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    evidence_warc_refs TEXT NOT NULL,
                    status TEXT NOT NULL,
                    engagement_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT
                )
            """)
            
            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_engagement ON requests(engagement_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_engagement ON findings(engagement_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_insertion_points_shape ON insertion_points(shape_hash)")
        
        self.conn.commit()
        logger.info("Database schema initialized")

    
    def insert_endpoint(self, endpoint: Endpoint) -> None:
        """Insert or update an endpoint."""
        cursor = self.conn.cursor()
        
        if self.use_postgres:
            cursor.execute("""
                INSERT INTO endpoints (id, method, url_template, host, classification, 
                                      sensitivity, auth_required, first_seen, last_seen, engagement_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (method, url_template, engagement_id) 
                DO UPDATE SET last_seen = EXCLUDED.last_seen
            """, (
                endpoint.id, endpoint.method, endpoint.url_template, endpoint.host,
                endpoint.classification, endpoint.sensitivity, endpoint.auth_required,
                endpoint.first_seen, endpoint.last_seen, endpoint.engagement_id
            ))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO endpoints 
                (id, method, url_template, host, classification, sensitivity, 
                 auth_required, first_seen, last_seen, engagement_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                endpoint.id, endpoint.method, endpoint.url_template, endpoint.host,
                endpoint.classification, endpoint.sensitivity, int(endpoint.auth_required),
                endpoint.first_seen.isoformat(), endpoint.last_seen.isoformat(), endpoint.engagement_id
            ))
        
        self.conn.commit()
    
    def insert_request(self, request: Request) -> None:
        """Insert a request with WARC reference."""
        cursor = self.conn.cursor()
        
        if self.use_postgres:
            cursor.execute("""
                INSERT INTO requests (id, endpoint_id, warc_ref, canonical_request_id, 
                                     role, timestamp, engagement_id, method, url, status_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.id, request.endpoint_id, Json(request.warc_ref), 
                request.canonical_request_id, request.role, request.timestamp,
                request.engagement_id, request.method, request.url, request.status_code
            ))
        else:
            cursor.execute("""
                INSERT INTO requests (id, endpoint_id, warc_ref, canonical_request_id,
                                     role, timestamp, engagement_id, method, url, status_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request.id, request.endpoint_id, json.dumps(request.warc_ref),
                request.canonical_request_id, request.role, request.timestamp.isoformat(),
                request.engagement_id, request.method, request.url, request.status_code
            ))
        
        self.conn.commit()
    
    def insert_insertion_point(self, point: InsertionPoint) -> None:
        """Insert an insertion point."""
        cursor = self.conn.cursor()
        
        if self.use_postgres:
            cursor.execute("""
                INSERT INTO insertion_points (id, request_id, location, encoding_layers,
                                             inferred_type, shape_hash, engagement_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                point.id, point.request_id, point.location, Json(point.encoding_layers),
                point.inferred_type, point.shape_hash, point.engagement_id
            ))
        else:
            cursor.execute("""
                INSERT INTO insertion_points (id, request_id, location, encoding_layers,
                                             inferred_type, shape_hash, engagement_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                point.id, point.request_id, point.location, json.dumps(point.encoding_layers),
                point.inferred_type, point.shape_hash, point.engagement_id
            ))
        
        self.conn.commit()
    
    def insert_finding(self, finding: Finding) -> None:
        """Insert or update a finding."""
        cursor = self.conn.cursor()
        
        severity = finding.severity.value if isinstance(finding.severity, Enum) else finding.severity
        status = finding.status.value if isinstance(finding.status, Enum) else finding.status
        
        if self.use_postgres:
            cursor.execute("""
                INSERT INTO findings (id, title, severity, category, description, asset,
                                     evidence_warc_refs, status, engagement_id, 
                                     created_at, updated_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    status = EXCLUDED.status,
                    metadata = EXCLUDED.metadata
            """, (
                finding.id, finding.title, severity, finding.category, finding.description,
                finding.asset, Json(finding.evidence_warc_refs), status, finding.engagement_id,
                finding.created_at, finding.updated_at, Json(finding.metadata)
            ))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO findings 
                (id, title, severity, category, description, asset, evidence_warc_refs,
                 status, engagement_id, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                finding.id, finding.title, severity, finding.category, finding.description,
                finding.asset, json.dumps(finding.evidence_warc_refs), status, 
                finding.engagement_id, finding.created_at.isoformat(), 
                finding.updated_at.isoformat(), json.dumps(finding.metadata)
            ))
        
        self.conn.commit()
    
    def get_finding(self, finding_id: str) -> Optional[Finding]:
        """Retrieve a finding by ID."""
        cursor = self.conn.cursor()
        
        if self.use_postgres:
            cursor.execute("SELECT * FROM findings WHERE id = %s", (finding_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return Finding(
                id=row[0], title=row[1], severity=Severity(row[2]), category=row[3],
                description=row[4], asset=row[5], evidence_warc_refs=row[6],
                status=FindingStatus(row[7]), engagement_id=row[8],
                created_at=row[9], updated_at=row[10], metadata=row[11] or {}
            )
        else:
            cursor.execute("SELECT * FROM findings WHERE id = ?", (finding_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return Finding(
                id=row["id"], title=row["title"], severity=Severity(row["severity"]),
                category=row["category"], description=row["description"], asset=row["asset"],
                evidence_warc_refs=json.loads(row["evidence_warc_refs"]),
                status=FindingStatus(row["status"]), engagement_id=row["engagement_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {}
            )
    
    def get_findings_by_engagement(self, engagement_id: str, severity: Optional[Severity] = None) -> list[Finding]:
        """Get all findings for an engagement, optionally filtered by severity."""
        cursor = self.conn.cursor()
        
        if severity:
            sev_val = severity.value if isinstance(severity, Enum) else severity
            if self.use_postgres:
                cursor.execute(
                    "SELECT * FROM findings WHERE engagement_id = %s AND severity = %s ORDER BY created_at DESC",
                    (engagement_id, sev_val)
                )
            else:
                cursor.execute(
                    "SELECT * FROM findings WHERE engagement_id = ? AND severity = ? ORDER BY created_at DESC",
                    (engagement_id, sev_val)
                )
        else:
            if self.use_postgres:
                cursor.execute(
                    "SELECT * FROM findings WHERE engagement_id = %s ORDER BY created_at DESC",
                    (engagement_id,)
                )
            else:
                cursor.execute(
                    "SELECT * FROM findings WHERE engagement_id = ? ORDER BY created_at DESC",
                    (engagement_id,)
                )
        
        findings = []
        for row in cursor.fetchall():
            if self.use_postgres:
                findings.append(Finding(
                    id=row[0], title=row[1], severity=Severity(row[2]), category=row[3],
                    description=row[4], asset=row[5], evidence_warc_refs=row[6],
                    status=FindingStatus(row[7]), engagement_id=row[8],
                    created_at=row[9], updated_at=row[10], metadata=row[11] or {}
                ))
            else:
                findings.append(Finding(
                    id=row["id"], title=row["title"], severity=Severity(row["severity"]),
                    category=row["category"], description=row["description"], asset=row["asset"],
                    evidence_warc_refs=json.loads(row["evidence_warc_refs"]),
                    status=FindingStatus(row["status"]), engagement_id=row["engagement_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {}
                ))
        
        return findings
    
    def get_request_by_id(self, request_id: str) -> Optional[Request]:
        """Get a request by ID."""
        cursor = self.conn.cursor()
        
        if self.use_postgres:
            cursor.execute("SELECT * FROM requests WHERE id = %s", (request_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return Request(
                id=row[0], endpoint_id=row[1], warc_ref=row[2], canonical_request_id=row[3],
                role=row[4], timestamp=row[5], engagement_id=row[6], method=row[7],
                url=row[8], status_code=row[9]
            )
        else:
            cursor.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return Request(
                id=row["id"], endpoint_id=row["endpoint_id"], 
                warc_ref=json.loads(row["warc_ref"]),
                canonical_request_id=row["canonical_request_id"], role=row["role"],
                timestamp=datetime.fromisoformat(row["timestamp"]), 
                engagement_id=row["engagement_id"],
                method=row["method"], url=row["url"], status_code=row["status_code"]
            )
    
    def check_shape_novelty(self, shape_hash: str, engagement_id: str) -> bool:
        """Check if an insertion point shape is novel (not seen before)."""
        cursor = self.conn.cursor()
        
        if self.use_postgres:
            cursor.execute(
                "SELECT COUNT(*) FROM insertion_points WHERE shape_hash = %s AND engagement_id = %s",
                (shape_hash, engagement_id)
            )
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM insertion_points WHERE shape_hash = ? AND engagement_id = ?",
                (shape_hash, engagement_id)
            )
        
        count = cursor.fetchone()[0]
        return count == 0
    
    def get_stats(self, engagement_id: str) -> dict:
        """Get statistics for an engagement."""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # Count endpoints
        if self.use_postgres:
            cursor.execute("SELECT COUNT(*) FROM endpoints WHERE engagement_id = %s", (engagement_id,))
        else:
            cursor.execute("SELECT COUNT(*) FROM endpoints WHERE engagement_id = ?", (engagement_id,))
        stats["endpoints"] = cursor.fetchone()[0]
        
        # Count requests
        if self.use_postgres:
            cursor.execute("SELECT COUNT(*) FROM requests WHERE engagement_id = %s", (engagement_id,))
        else:
            cursor.execute("SELECT COUNT(*) FROM requests WHERE engagement_id = ?", (engagement_id,))
        stats["requests"] = cursor.fetchone()[0]
        
        # Count insertion points
        if self.use_postgres:
            cursor.execute("SELECT COUNT(*) FROM insertion_points WHERE engagement_id = %s", (engagement_id,))
        else:
            cursor.execute("SELECT COUNT(*) FROM insertion_points WHERE engagement_id = ?", (engagement_id,))
        stats["insertion_points"] = cursor.fetchone()[0]
        
        # Count findings by severity
        if self.use_postgres:
            cursor.execute(
                "SELECT severity, COUNT(*) FROM findings WHERE engagement_id = %s GROUP BY severity",
                (engagement_id,)
            )
        else:
            cursor.execute(
                "SELECT severity, COUNT(*) FROM findings WHERE engagement_id = ? GROUP BY severity",
                (engagement_id,)
            )
        
        stats["findings_by_severity"] = {row[0]: row[1] for row in cursor.fetchall()}
        
        return stats
    
    def close(self):
        """Close database connection."""
        self.conn.close()
        logger.info("Database connection closed")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
