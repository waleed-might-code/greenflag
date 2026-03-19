"""
Governance layer for authorized security testing.
Ensures all requests are within scope and properly authorized.
"""

from .scope_validator import ScopeValidator
from .engagement_config import EngagementConfig, TestIdentity
from .scope_enforcing_client import ScopeEnforcingClient

__all__ = [
    "ScopeValidator",
    "EngagementConfig",
    "TestIdentity",
    "ScopeEnforcingClient",
]
