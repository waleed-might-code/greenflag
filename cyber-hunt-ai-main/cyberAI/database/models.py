"""
SQLAlchemy models for structured data storage.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, 
    Integer, String, Text, Index
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Endpoint(Base):
    """Discovered endpoint/URL pattern."""
    __tablename__ = "endpoints"
    
    id = Column(Integer, primary_key=True)
    engagement_id = Column(String(64), nullable=False, index=True)
    method = Column(String(10), nullable=False)
    url_template = Column(String(2048), nullable=False)
    host = Column(String(256), nullable=False)
    classification = Column(String(64))  # api, form, static, admin
    sensitivity = Column(String(32))  # public, authenticated, admin
    auth_required = Column(Boolean, default=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    request_count = Column(Integer, default=0)
    
    # Relationships
    requests = relationship("Request", back_populates="endpoint")
    
    __table_args__ = (
        Index("idx_endpoint_lookup", "engagement_id", "method", "url_template"),
    )


class Request(Base):
    """Individual HTTP request with WARC reference."""
    __tablename__ = "requests"
    
    id = Column(Integer, primary_key=True)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"))
    engagement_id = Column(String(64), nullable=False, index=True)
    warc_ref = Column(String(512), nullable=False)
    canonical_request_id = Column(String(64))
    role = Column(String(64))  # admin, user, guest
    status_code = Column(Integer)
    response_size = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    endpoint = relationship("Endpoint", back_populates="requests")
    insertion_points = relationship("InsertionPoint", back_populates="request")


class InsertionPoint(Base):
    """Extracted insertion point from request."""
    __tablename__ = "insertion_points"
    
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("requests.id"))
    engagement_id = Column(String(64), nullable=False, index=True)
    location = Column(String(512), nullable=False)  # path_segment_3, query.id
    encoding_layers = Column(ARRAY(String))  # ["json", "base64"]
    inferred_type = Column(String(64))  # id, string, token, email
    shape_hash = Column(String(64), index=True)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    request = relationship("Request", back_populates="insertion_points")



class Finding(Base):
    """Security finding with evidence."""
    __tablename__ = "findings"
    
    id = Column(Integer, primary_key=True)
    engagement_id = Column(String(64), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    severity = Column(String(32), nullable=False)  # critical, high, medium, low
    category = Column(String(128))  # BOLA, XSS, SQLi, etc.
    asset = Column(String(1024))  # Affected URL/endpoint
    description = Column(Text)
    evidence_warc_refs = Column(ARRAY(String))
    status = Column(String(32), default="open")  # open, confirmed, false_positive
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_finding_severity", "engagement_id", "severity"),
    )
