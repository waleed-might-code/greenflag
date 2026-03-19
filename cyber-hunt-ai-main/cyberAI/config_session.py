"""
Configuration extensions for session management.
Add these to your existing Config class.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SessionConfig:
    """Session management configuration."""
    
    # Redis connection
    redis_url: Optional[str] = None  # e.g., "redis://localhost:6379/0"
    redis_password: Optional[str] = None
    redis_ssl: bool = False
    
    # Session lifecycle
    session_ttl_seconds: int = 3600  # 1 hour
    session_health_check_interval: int = 100  # Check every N requests
    session_max_repair_attempts: int = 3
    
    # Validation
    session_validation_url: str = "/api/me"
    session_expected_status: list[int] = None
    session_redirect_patterns: list[str] = None
    
    # Login sequences
    login_sequences_dir: str = "login_sequences"
    login_macro_timeout_ms: int = 30000
    login_macro_step_delay_ms: int = 500
    login_macro_max_retries: int = 3
    
    # Debug
    session_screenshot_dir: Optional[str] = None
    session_debug_mode: bool = False
    
    def __post_init__(self):
        if self.session_expected_status is None:
            self.session_expected_status = [200]
        if self.session_redirect_patterns is None:
            self.session_redirect_patterns = ["/login", "/signin", "/auth"]
    
    @classmethod
    def from_env(cls) -> "SessionConfig":
        """Load session config from environment variables."""
        import os
        
        return cls(
            redis_url=os.getenv("REDIS_URL"),
            redis_password=os.getenv("REDIS_PASSWORD"),
            redis_ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "3600")),
            session_health_check_interval=int(os.getenv("SESSION_HEALTH_CHECK_INTERVAL", "100")),
            session_max_repair_attempts=int(os.getenv("SESSION_MAX_REPAIR_ATTEMPTS", "3")),
            session_validation_url=os.getenv("SESSION_VALIDATION_URL", "/api/me"),
            login_sequences_dir=os.getenv("LOGIN_SEQUENCES_DIR", "login_sequences"),
            login_macro_timeout_ms=int(os.getenv("LOGIN_MACRO_TIMEOUT_MS", "30000")),
            login_macro_step_delay_ms=int(os.getenv("LOGIN_MACRO_STEP_DELAY_MS", "500")),
            login_macro_max_retries=int(os.getenv("LOGIN_MACRO_MAX_RETRIES", "3")),
            session_screenshot_dir=os.getenv("SESSION_SCREENSHOT_DIR"),
            session_debug_mode=os.getenv("SESSION_DEBUG_MODE", "false").lower() == "true"
        )


# Example .env additions:
"""
# Session Management
REDIS_URL=redis://localhost:6379/0
REDIS_PASSWORD=
REDIS_SSL=false

SESSION_TTL_SECONDS=3600
SESSION_HEALTH_CHECK_INTERVAL=100
SESSION_MAX_REPAIR_ATTEMPTS=3
SESSION_VALIDATION_URL=/api/me

LOGIN_SEQUENCES_DIR=login_sequences
LOGIN_MACRO_TIMEOUT_MS=30000
LOGIN_MACRO_STEP_DELAY_MS=500
LOGIN_MACRO_MAX_RETRIES=3

SESSION_SCREENSHOT_DIR=outputs/session_debug
SESSION_DEBUG_MODE=false
"""
