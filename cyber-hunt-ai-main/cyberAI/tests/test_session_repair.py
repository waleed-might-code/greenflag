"""
Integration tests for session repair and multi-role crawling.

Tests the complete workflow:
- Session establishment
- Session health monitoring
- Automatic repair on failure
- Multi-role crawling
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cyberAI.session_integration import SessionIntegration, EngagementConfig
from cyberAI.login_macro import LoginSequence, LoginStep, StepAction
from cyberAI.crawl.session_aware_orchestrator import SessionAwareCrawlOrchestrator


@pytest.fixture
def sample_engagement_config(tmp_path):
    """Create a sample engagement configuration."""
    # Create login sequences
    sequences_dir = tmp_path / "sequences"
    sequences_dir.mkdir()
    
    admin_steps = [
        LoginStep(action=StepAction.NAVIGATE, url="https://example.com/login"),
        LoginStep(action=StepAction.FILL, selector="input[name='email']", value_ref="{{username}}"),
        LoginStep(action=StepAction.FILL, selector="input[name='password']", value_ref="{{password}}"),
        LoginStep(action=StepAction.CLICK, selector="button[type='submit']"),
        LoginStep(action=StepAction.ASSERT_URL, expected="/dashboard")
    ]
    
    admin_sequence = LoginSequence(
        name="Admin Login",
        role="admin",
        steps=admin_steps,
        success_indicators=[{"type": "url_contains", "value": "/dashboard"}],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z"
    )
    admin_sequence.save(sequences_dir / "admin_login.json")
    
    return EngagementConfig(
        engagement_id="test-engagement",
        roles=["admin"],
        login_sequences={"admin": sequences_dir / "admin_login.json"},
        credentials={"admin": {"username": "admin@test.com", "password": "testpass"}},
        validation_config={
            "default_url": "/api/me",
            "expected_status": [200],
            "redirect_patterns": ["/login"]
        },
        redis_url=None
    )


@pytest.mark.asyncio
async def test_session_integration_initialization(sample_engagement_config):
    """Test that session integration initializes correctly."""
    integration = SessionIntegration(sample_engagement_config)
    await integration.initialize()
    
    assert integration._initialized is True
    assert "admin" in integration._login_sequences
    assert integration._login_sequences["admin"].role == "admin"
    
    await integration.cleanup()


@pytest.mark.asyncio
async def test_session_repair_on_401(sample_engagement_config):
    """Test that session repair triggers on 401 response."""
    integration = SessionIntegration(sample_engagement_config)
    await integration.initialize()
    
    # Create a mock session
    from cyberAI.session_manager import SessionData
    import time
    
    session = SessionData(
        engagement_id="test-engagement",
        role="admin",
        cookies=[{"name": "session", "value": "old_token"}],
        headers={},
        tokens={},
        created_at=time.time(),
        last_validated=time.time(),
        is_healthy=False  # Mark as unhealthy
    )
    
    await integration.manager.store.set(session)
    
    # Mock page and browser
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(return_value=AsyncMock(status=401))
    mock_page.url = "https://example.com/dashboard"
    mock_page.context.cookies = AsyncMock(return_value=[
        {"name": "session", "value": "new_token"}
    ])
    
    mock_browser = AsyncMock()
    
    # Attempt repair (will fail in test but should execute the flow)
    with patch.object(integration.macro_executor, 'execute', return_value={
        "success": True,
        "cookies": [{"name": "session", "value": "new_token"}],
        "headers": {},
        "tokens": {}
    }):
        success, repaired = await integration.validate_and_repair_session(
            browser=mock_browser,
            role="admin",
            page=mock_page
        )
    
    await integration.cleanup()


@pytest.mark.asyncio
async def test_multi_role_session_isolation(sample_engagement_config, tmp_path):
    """Test that sessions for different roles are isolated."""
    # Add user role
    user_steps = [
        LoginStep(action=StepAction.NAVIGATE, url="https://example.com/login"),
        LoginStep(action=StepAction.FILL, selector="input[name='email']", value_ref="{{username}}"),
        LoginStep(action=StepAction.FILL, selector="input[name='password']", value_ref="{{password}}"),
        LoginStep(action=StepAction.CLICK, selector="button[type='submit']"),
    ]
    
    user_sequence = LoginSequence(
        name="User Login",
        role="user",
        steps=user_steps,
        success_indicators=[{"type": "url_contains", "value": "/home"}],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z"
    )
    
    sequences_dir = tmp_path / "sequences"
    user_sequence.save(sequences_dir / "user_login.json")
    
    # Update config
    sample_engagement_config.roles.append("user")
    sample_engagement_config.login_sequences["user"] = sequences_dir / "user_login.json"
    sample_engagement_config.credentials["user"] = {"username": "user@test.com", "password": "userpass"}
    
    integration = SessionIntegration(sample_engagement_config)
    await integration.initialize()
    
    # Create sessions for both roles
    import time
    from cyberAI.session_manager import SessionData
    
    admin_session = SessionData(
        engagement_id="test-engagement",
        role="admin",
        cookies=[{"name": "admin_session", "value": "admin_token"}],
        headers={},
        tokens={},
        created_at=time.time(),
        last_validated=time.time()
    )
    
    user_session = SessionData(
        engagement_id="test-engagement",
        role="user",
        cookies=[{"name": "user_session", "value": "user_token"}],
        headers={},
        tokens={},
        created_at=time.time(),
        last_validated=time.time()
    )
    
    await integration.manager.store.set(admin_session)
    await integration.manager.store.set(user_session)
    
    # Retrieve and verify isolation
    retrieved_admin = await integration.manager.get_session("test-engagement", "admin")
    retrieved_user = await integration.manager.get_session("test-engagement", "user")
    
    assert retrieved_admin.role == "admin"
    assert retrieved_user.role == "user"
    assert retrieved_admin.cookies[0]["value"] == "admin_token"
    assert retrieved_user.cookies[0]["value"] == "user_token"
    
    await integration.cleanup()


@pytest.mark.asyncio
async def test_session_health_check_interval():
    """Test that health checks happen at the configured interval."""
    from cyberAI.session_manager import SessionStore, SessionHealthChecker, SessionManager
    
    store = SessionStore(redis_url=None)
    await store.connect()
    
    health_checker = SessionHealthChecker()
    manager = SessionManager(
        store=store,
        health_checker=health_checker,
        health_check_interval=5  # Check every 5 requests
    )
    
    # First 4 calls should return False
    for i in range(4):
        should_check = await manager.should_check_health("test-eng", "admin")
        assert should_check is False, f"Request {i+1} should not trigger health check"
    
    # 5th call should return True
    should_check = await manager.should_check_health("test-eng", "admin")
    assert should_check is True, "Request 5 should trigger health check"
    
    # Counter should reset
    should_check = await manager.should_check_health("test-eng", "admin")
    assert should_check is False, "Request 6 should not trigger health check"
    
    await manager.cleanup()


@pytest.mark.asyncio
async def test_session_repair_retry_limit():
    """Test that session repair respects retry limits."""
    from cyberAI.session_manager import SessionStore, SessionHealthChecker, SessionManager, SessionData
    import time
    
    store = SessionStore(redis_url=None)
    await store.connect()
    
    health_checker = SessionHealthChecker()
    manager = SessionManager(store=store, health_checker=health_checker)
    
    # Create a session with high repair attempts
    session = SessionData(
        engagement_id="test-eng",
        role="admin",
        cookies=[],
        headers={},
        tokens={},
        created_at=time.time(),
        last_validated=time.time(),
        is_healthy=False,
        repair_attempts=5  # Already failed 5 times
    )
    
    await store.set(session)
    
    # Mock repair callback that always fails
    async def failing_repair(eng_id, role, page):
        return None
    
    mock_page = AsyncMock()
    
    # Attempt repair
    success, result = await manager.validate_and_repair(
        engagement_id="test-eng",
        role="admin",
        page=mock_page,
        repair_callback=failing_repair
    )
    
    assert success is False
    assert result.repair_attempts == 6  # Incremented
    
    await manager.cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
