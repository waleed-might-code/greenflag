"""
PostgreSQL database schema for enterprise-grade security testing.
Stores structured data from crawls, tests, and findings with WARC references.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, JSON, Text, ForeignKey,
    Index, UniqueConstraint, create_engine, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

Base = declarative_base()


class Engagement(Base):
    """Engagement/project configuration."""
    __tablename__ = "engagements"
    
    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    target_domains = Column(ARRAY(String), nullable=False)
    out_of_scope_patterns = Column(ARRAY(String), default=[])
    allowed_schemes = Column(ARRAY(String), default=["https"])
    config = Column(JSONB, default={})  # Full engagement config
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = Column(String(32), default="active")  # active, paused, closed
    
    # Relationships
    endpoints = relationship("Endpoint", back_populates="engagement", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="engagement", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_engagement_status", "status"),
    )


class Endpoint(Base):
    """Discovered API endpoint or route."""
    __tablename__ = "endpoints"
    
    id = Column(String(64), primary_key=True)
    engagement_id = Column(String(64), ForeignKey("engagements.id"), nullable=False)
    method = Column(String(16), nullable=False)  # GET, POST, etc.
    url_template = Column(String(2048), nullable=False)  # /api/users/{id}
    host = Column(String(255), nullable=False)
    path = Column(String(2048), nullable=False)
    classification = Column(String(32))  # read, create, update, delete, admin, auth
    sensitivity = Column(String(16))  # high, medium, low, public
    auth_required = Column(Boolean, default=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    request_count = Column(Integer, default=0)
    
    # Relationships
    engagement = relationship("Engagement", back_populates="endpoints")
    requests = relationship("Request", back_populates="endpoint", cascade="all, delete-orphan")
    insertion_points = relationship("InsertionPoint", back_populates="endpoint")
    
    __table_args__ = (
        Index("idx_endpoint_engagement", "engagement_id"),
        Index("idx_endpoint_method_template", "method", "url_template"),
        Index("idx_endpoint_classification", "classification"),
        UniqueConstraint("engagement_id", "method", "url_template", name="uq_endpoint"),
    )


class Request(Base):
    """Individual HTTP request/response capture."""
    __tablename__ = "requests"
    
    id = Column(String(64), primary_key=True)
    engagement_id = Column(String(64), ForeignKey("engagements.id"), nullable=False)
    endpoint_id = Column(String(64), ForeignKey("endpoints.id"), nullable=False)
    warc_ref = Column(String(512), nullable=False)  # WARC URI
    canonical_request_id = Column(String(64))  # Link to canonical form
    role = Column(String(64))  # admin, user, guest, etc.
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Request metadata
    url = Column(String(2048), nullable=False)
    method = Column(String(16), nullable=False)
    status_code = Column(Integer)
    response_time_ms = Column(Float)
    content_type = Column(String(128))
    content_length = Column(Integer)
    
    # Relationships
    endpoint = relationship("Endpoint", back_populates="requests")
    insertion_points = relationship("InsertionPoint", back_populates="request")
    
    __table_args__ = (
        Index("idx_request_engagement", "engagement_id"),
        Index("idx_request_endpoint", "endpoint_id"),
        Index("idx_request_timestamp", "timestamp"),
        Index("idx_request_role", "role"),
    )


class InsertionPoint(Base):
    """Identified insertion point for payload testing."""
    __tablename__ = "insertion_points"
    
    id = Column(String(64), primary_key=True)
    engagement_id = Column(String(64), ForeignKey("engagements.id"), nullable=False)
    endpoint_id = Column(String(64), ForeignKey("endpoints.id"), nullable=False)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=False)
    
    location = Column(String(512), nullable=False)  # path_segment_3, query.search, body.user.id
    encoding_layers = Column(ARRAY(String), default=[])  # ["json", "base64"]
    inferred_type = Column(String(32))  # id, string, token, email, etc.
    shape_hash = Column(String(64), nullable=False)  # For novelty tracking
    
    # Sample values for fuzzing
    sample_values = Column(ARRAY(String), default=[])
    
    first_seen = Column(DateTime, default=datetime.utcnow)
    test_count = Column(Integer, default=0)
    
    # Relationships
    endpoint = relationship("Endpoint", back_populates="insertion_points")
    request = relationship("Request", back_populates="insertion_points")
    
    __table_args__ = (
        Index("idx_insertion_point_endpoint", "endpoint_id"),
        Index("idx_insertion_point_shape", "shape_hash"),
        Index("idx_insertion_point_type", "inferred_type"),
    )


class Finding(Base):
    """Security finding/vulnerability."""
    __tablename__ = "findings"
    
    id = Column(String(64), primary_key=True)
    engagement_id = Column(String(64), ForeignKey("engagements.id"), nullable=False)
    
    title = Column(String(512), nullable=False)
    severity = Column(String(16), nullable=False)  # critical, high, medium, low, info
    category = Column(String(64), nullable=False)  # auth, authz, injection, etc.
    status = Column(String(32), default="confirmed")  # confirmed, likely, false_positive
    
    # Evidence
    evidence_warc_refs = Column(ARRAY(String), default=[])  # WARC URIs
    affected_endpoints = Column(ARRAY(String), default=[])  # Endpoint IDs
    
    # Details
    description = Column(Text)
    impact = Column(Text)
    remediation = Column(Text)
    cwe_ids = Column(ARRAY(String), default=[])
    cvss_score = Column(Float)
    
    discovered_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    engagement = relationship("Engagement", back_populates="findings")
    
    __table_args__ = (
        Index("idx_finding_engagement", "engagement_id"),
        Index("idx_finding_severity", "severity"),
        Index("idx_finding_category", "category"),
        Index("idx_finding_status", "status"),
    )


class CrawlState(Base):
    """State-flow crawler state node."""
    __tablename__ = "crawl_states"
    
    id = Column(String(64), primary_key=True)
    engagement_id = Column(String(64), ForeignKey("engagements.id"), nullable=False)
    
    dom_hash = Column(String(64), nullable=False, unique=True)
    url = Column(String(2048), nullable=False)
    screenshot_path = Column(String(512))
    warc_ref = Column(String(512))
    
    discovered_at = Column(DateTime, default=datetime.utcnow)
    visit_count = Column(Integer, default=0)
    
    __table_args__ = (
        Index("idx_crawl_state_engagement", "engagement_id"),
        Index("idx_crawl_state_hash", "dom_hash"),
    )


class CrawlTransition(Base):
    """State-flow crawler transition edge."""
    __tablename__ = "crawl_transitions"
    
    id = Column(String(64), primary_key=True)
    engagement_id = Column(String(64), ForeignKey("engagements.id"), nullable=False)
    
    from_state_id = Column(String(64), ForeignKey("crawl_states.id"), nullable=False)
    to_state_id = Column(String(64), ForeignKey("crawl_states.id"), nullable=False)
    
    event_type = Column(String(32), nullable=False)  # click, submit, input
    selector = Column(String(512))
    payload_preview = Column(String(256))
    
    discovered_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_transition_from", "from_state_id"),
        Index("idx_transition_to", "to_state_id"),
    )


class SessionRecord(Base):
    """Session/authentication record for multi-role testing."""
    __tablename__ = "sessions"
    
    id = Column(String(64), primary_key=True)
    engagement_id = Column(String(64), ForeignKey("engagements.id"), nullable=False)
    
    role = Column(String(64), nullable=False)
    cookies = Column(JSONB, default={})
    headers = Column(JSONB, default={})
    tokens = Column(JSONB, default={})
    
    is_healthy = Column(Boolean, default=True)
    last_health_check = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    __table_args__ = (
        Index("idx_session_engagement_role", "engagement_id", "role"),
        Index("idx_session_healthy", "is_healthy"),
    )


def create_database(database_url: str):
    """Create all tables in the database."""
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return engine


def get_session_maker(database_url: str):
    """Get SQLAlchemy session maker."""
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine)
