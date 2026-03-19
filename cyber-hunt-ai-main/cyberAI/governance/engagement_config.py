"""
Engagement configuration schema and loader.
Defines scope, identities, rate limits, and data retention policies.
"""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from loguru import logger


@dataclass
class LoginSequenceStep:
    """Single step in a login sequence."""
    action: str  # navigate, fill, click, wait
    selector: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    seconds: Optional[float] = None


@dataclass
class TestIdentity:
    """Test identity with credentials and login sequence."""
    role: str
    credentials_type: str  # form_replay, recorded_login, oauth, token
    username: Optional[str] = None
    password: Optional[str] = None
    login_sequence: list[LoginSequenceStep] = field(default_factory=list)
    session_check_url: Optional[str] = None
    token: Optional[str] = None
    mfa_secret: Optional[str] = None


@dataclass
class RateLimits:
    """Rate limiting configuration."""
    per_host_rps: int = 10
    global_rps: int = 50
    backoff_on_5xx: str = "exponential"  # exponential, linear, none


@dataclass
class DataRetention:
    """Data retention and privacy policies."""
    raw_capture_ttl_days: int = 90
    structured_ttl_days: int = 365
    permitted_data_classes: list[str] = field(
        default_factory=lambda: ["request_response_meta", "finding_evidence", "insertion_point_schema"]
    )


@dataclass
class EngagementConfig:
    """
    Complete engagement configuration.
    Defines scope, identities, rate limits, and retention policies.
    """
    engagement_id: str
    name: str
    target_domains: list[str]
    out_of_scope_patterns: list[str] = field(default_factory=list)
    allowed_schemes: list[str] = field(default_factory=lambda: ["https"])
    test_identities: list[TestIdentity] = field(default_factory=list)
    rate_limits: RateLimits = field(default_factory=RateLimits)
    data_retention: DataRetention = field(default_factory=DataRetention)
    incident_contacts: list[str] = field(default_factory=list)
    
    @classmethod
    def from_file(cls, path: Path) -> "EngagementConfig":
        """Load engagement config from YAML or JSON file."""
        if not path.exists():
            raise FileNotFoundError(f"Engagement config not found: {path}")
        
        with open(path, "r") as f:
            if path.suffix in [".yaml", ".yml"]:
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EngagementConfig":
        """Create engagement config from dictionary."""
        # Parse test identities
        identities = []
        for identity_data in data.get("test_identities", []):
            steps = []
            for step_data in identity_data.get("login_sequence", []):
                steps.append(LoginSequenceStep(**step_data))
            
            identity = TestIdentity(
                role=identity_data["role"],
                credentials_type=identity_data.get("credentials", {}).get("type", "form_replay"),
                username=identity_data.get("credentials", {}).get("username"),
                password=identity_data.get("credentials", {}).get("password"),
                login_sequence=steps,
                session_check_url=identity_data.get("session_check_url"),
                token=identity_data.get("credentials", {}).get("token"),
                mfa_secret=identity_data.get("credentials", {}).get("mfa_secret"),
            )
            identities.append(identity)
        
        # Parse rate limits
        rate_limits_data = data.get("rate_limits", {})
        rate_limits = RateLimits(
            per_host_rps=rate_limits_data.get("per_host_rps", 10),
            global_rps=rate_limits_data.get("global_rps", 50),
            backoff_on_5xx=rate_limits_data.get("backoff_on_5xx", "exponential"),
        )
        
        # Parse data retention
        retention_data = data.get("data_retention", {})
        data_retention = DataRetention(
            raw_capture_ttl_days=retention_data.get("raw_capture_ttl_days", 90),
            structured_ttl_days=retention_data.get("structured_ttl_days", 365),
            permitted_data_classes=retention_data.get("permitted_data_classes", [
                "request_response_meta", "finding_evidence", "insertion_point_schema"
            ]),
        )
        
        return cls(
            engagement_id=data.get("engagement_id", str(uuid.uuid4())),
            name=data["name"],
            target_domains=data["target_domains"],
            out_of_scope_patterns=data.get("out_of_scope_patterns", []),
            allowed_schemes=data.get("allowed_schemes", ["https"]),
            test_identities=identities,
            rate_limits=rate_limits,
            data_retention=data_retention,
            incident_contacts=data.get("incident_contacts", []),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "engagement_id": self.engagement_id,
            "name": self.name,
            "target_domains": self.target_domains,
            "out_of_scope_patterns": self.out_of_scope_patterns,
            "allowed_schemes": self.allowed_schemes,
            "test_identities": [
                {
                    "role": identity.role,
                    "credentials_type": identity.credentials_type,
                    "session_check_url": identity.session_check_url,
                }
                for identity in self.test_identities
            ],
            "rate_limits": {
                "per_host_rps": self.rate_limits.per_host_rps,
                "global_rps": self.rate_limits.global_rps,
                "backoff_on_5xx": self.rate_limits.backoff_on_5xx,
            },
            "data_retention": {
                "raw_capture_ttl_days": self.data_retention.raw_capture_ttl_days,
                "structured_ttl_days": self.data_retention.structured_ttl_days,
                "permitted_data_classes": self.data_retention.permitted_data_classes,
            },
            "incident_contacts": self.incident_contacts,
        }
    
    def save(self, path: Path) -> None:
        """Save engagement config to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w") as f:
            if path.suffix in [".yaml", ".yml"]:
                yaml.dump(self.to_dict(), f, default_flow_style=False)
            else:
                json.dump(self.to_dict(), f, indent=2)
        
        logger.info(f"Saved engagement config to {path}")
    
    @classmethod
    def create_default(cls, target_url: str, name: str = "Default Engagement") -> "EngagementConfig":
        """Create a default engagement config for a target URL."""
        from urllib.parse import urlparse
        
        parsed = urlparse(target_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        return cls(
            engagement_id=str(uuid.uuid4()),
            name=name,
            target_domains=[domain],
            out_of_scope_patterns=[],
            allowed_schemes=["https", "http"],
            test_identities=[],
            rate_limits=RateLimits(),
            data_retention=DataRetention(),
            incident_contacts=[],
        )
