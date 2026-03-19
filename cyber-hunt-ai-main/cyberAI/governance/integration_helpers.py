"""
Helper functions for integrating scope enforcement into existing components.
"""

from typing import Optional
from pathlib import Path

from loguru import logger

from .engagement_config import EngagementConfig
from .scope_validator import ScopeValidator
from .scope_enforcing_client import ScopeEnforcingClient
from .scope_aware_browser import ScopeAwareBrowserPool


def create_scope_enforcing_client(
    engagement_config: EngagementConfig,
    log_only: bool = False,
) -> ScopeEnforcingClient:
    """
    Create a scope-enforcing HTTP client from engagement config.
    
    Args:
        engagement_config: Engagement configuration
        log_only: If True, log violations but don't block
        
    Returns:
        ScopeEnforcingClient instance
    """
    client = ScopeEnforcingClient(
        engagement_config=engagement_config,
        log_only=log_only,
    )
    
    logger.info(
        f"Created scope-enforcing client for engagement: {engagement_config.name}"
    )
    
    return client


def create_scope_aware_browser_pool(
    engagement_config: EngagementConfig,
) -> ScopeAwareBrowserPool:
    """
    Create a scope-aware browser pool from engagement config.
    
    Args:
        engagement_config: Engagement configuration
        
    Returns:
        ScopeAwareBrowserPool instance
    """
    pool = ScopeAwareBrowserPool(engagement_config)
    
    logger.info(
        f"Created scope-aware browser pool for engagement: {engagement_config.name}"
    )
    
    return pool


def load_engagement_and_create_clients(
    engagement_config_path: str,
) -> tuple[EngagementConfig, ScopeEnforcingClient, ScopeAwareBrowserPool]:
    """
    Load engagement config and create all scope-enforcing clients.
    
    Args:
        engagement_config_path: Path to engagement config YAML/JSON
        
    Returns:
        Tuple of (EngagementConfig, ScopeEnforcingClient, ScopeAwareBrowserPool)
    """
    # Load config
    config = EngagementConfig.from_file(Path(engagement_config_path))
    
    # Create clients
    http_client = create_scope_enforcing_client(config)
    browser_pool = create_scope_aware_browser_pool(config)
    
    logger.info(
        f"Loaded engagement '{config.name}' with scope enforcement enabled"
    )
    
    return config, http_client, browser_pool


def validate_url_against_engagement(
    url: str,
    engagement_config: EngagementConfig,
    method: str = "GET",
) -> tuple[bool, str]:
    """
    Quick validation of a URL against engagement scope.
    
    Args:
        url: URL to validate
        engagement_config: Engagement configuration
        method: HTTP method
        
    Returns:
        Tuple of (is_allowed, reason)
    """
    validator = ScopeValidator(
        target_domains=engagement_config.target_domains,
        out_of_scope_patterns=engagement_config.out_of_scope_patterns,
        allowed_schemes=engagement_config.allowed_schemes,
    )
    
    result = validator.is_in_scope(url, method)
    return result.decision.value == "allow", result.reason
