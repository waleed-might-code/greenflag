"""
Unit tests for Session Management System
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from cyberAI.session_manager import SessionStore, SessionData, SessionHealthChecker, SessionManager
from cyberAI.login_macro import LoginSequence, LoginStep, StepAction, LoginMacroExecutor


@pytest.fixture
def sample_session_data():
    """Create sample session data for testing."""
    return SessionData(
        engagement_id="test-engagement",
        role="admin",
        cookies=[
            {"name": "session_id", "value": "abc123", "domain": "example.com"}
        ],
        headers={"Authorization": "Bearer token123"},
        tokens={"auth_token": "token123"},
        created_at=1234567890.0,
        last_validated=1234567890.0,
        validation_url="/api/me",
        is_healthy=True,
        repair_attempts=0
    )


@pytest.fixture
def sample_login_sequence():
    """Create sample login sequence for testing."""
    steps = [
        LoginStep(
            action=StepAction.NAVIGATE,
            url="https://example.com/login",
            description="Navigate to login"
        ),
        LoginStep(
            action=StepAction.FILL,
            selector="input[name='email']",
            value_ref="{{username}}",
            description="Fill email"
        ),
        LoginStep(
            action=StepAction.FILL,
            selector="input[name='password']",
            value_ref="{{password}}",
            description="Fill password"
        ),
        LoginStep(
            action=StepAction.CLICK,
            selector="button[type='submit']",
            description="Submit"
        ),
        LoginStep(
            action=StepAction.ASSERT_URL,
            expected="/dashboard",
            description="Verify success"
        )
    ]
    
    return LoginSequence(
        name="Test Login",
        role="admin",
        steps=steps,
        success_indicators=[
            {"type": "url_contains", "value": "/dashboard"}
        ],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z"
    )


class TestSessionData:
    """Test SessionData model."""
    
    def test_session_data_creation(self, sample_session_data):
        assert sample_session_data.engagement_id == "test-engagement"
        assert sample_session_data.role == "admin"
        assert len(sample_session_data.cookies) == 1
        assert sample_session_data.is_healthy is True
    
    def test_session_data_serialization(self, sample_session_data):
        data_dict = sample_session_data.to_dict()
        assert isinstance(data_dict, dict)
        assert data_dict["engagement_id"] == "test-engagement"
        
        # Deserialize
        restored = SessionData.from_dict(data_dict)
        assert restored.engagement_id == sample_session_data.engagement_id
        assert restored.role == sample_session_data.role
    
    def test_session_expiry(self, sample_session_data):
        # Should not be expired with default TTL
        assert not sample_session_data.is_expired(ttl_seconds=3600)
        
        # Should be expired with very short TTL
        assert sample_session_data.is_expired(ttl_seconds=1)


class TestSessionStore:
    """Test SessionStore."""
    
    @pytest.mark.asyncio
    async def test_memory_store_operations(self, sample_session_data):
        store = SessionStore(redis_url=None, ttl_seconds=3600)
        await store.connect()
        
        # Set session
        success = await store.set(sample_session_data)
        assert success is True
        
        # Get session
        retrieved = await store.get("test-engagement", "admin")
        assert retrieved is not None
        assert retrieved.engagement_id == "test-engagement"
        assert retrieved.role == "admin"
        
        # Delete session
        deleted = await store.delete("test-engagement", "admin")
        assert deleted is True
        
        # Verify deleted
        retrieved = await store.get("test-engagement", "admin")
        assert retrieved is None
        
        await store.close()
    
    @pytest.mark.asyncio
    async def test_list_sessions(self, sample_session_data):
        store = SessionStore(redis_url=None)
        await store.connect()
        
        # Add multiple sessions
        await store.set(sample_session_data)
        
        session2 = SessionData(
            engagement_id="test-engagement",
            role="user",
            cookies=[],
            headers={},
            tokens={},
            created_at=1234567890.0,
            last_validated=1234567890.0
        )
        await store.set(session2)
        
        # List sessions
        sessions = await store.list_sessions("test-engagement")
        assert len(sessions) == 2
        
        roles = {s.role for s in sessions}
        assert "admin" in roles
        assert "user" in roles
        
        await store.close()


class TestLoginSequence:
    """Test LoginSequence."""
    
    def test_sequence_creation(self, sample_login_sequence):
        assert sample_login_sequence.name == "Test Login"
        assert sample_login_sequence.role == "admin"
        assert len(sample_login_sequence.steps) == 5
    
    def test_sequence_serialization(self, sample_login_sequence, tmp_path):
        # Save to file
        file_path = tmp_path / "test_sequence.json"
        sample_login_sequence.save(file_path)
        
        assert file_path.exists()
        
        # Load from file
        loaded = LoginSequence.load(file_path)
        assert loaded.name == sample_login_sequence.name
        assert loaded.role == sample_login_sequence.role
        assert len(loaded.steps) == len(sample_login_sequence.steps)
    
    def test_sequence_to_dict(self, sample_login_sequence):
        data = sample_login_sequence.to_dict()
        assert isinstance(data, dict)
        assert data["name"] == "Test Login"
        assert len(data["steps"]) == 5
        
        # Verify steps are serialized
        for step in data["steps"]:
            assert "action" in step


class TestLoginMacroExecutor:
    """Test LoginMacroExecutor."""
    
    @pytest.mark.asyncio
    async def test_credential_substitution(self):
        executor = LoginMacroExecutor()
        
        template = "Hello {{username}}, your password is {{password}}"
        credentials = {"username": "john", "password": "secret123"}
        
        result = executor._substitute_credentials(template, credentials)
        assert result == "Hello john, your password is secret123"
    
    @pytest.mark.asyncio
    async def test_success_indicators_url_contains(self):
        executor = LoginMacroExecutor()
        
        # Mock page
        page = AsyncMock()
        page.url = "https://example.com/dashboard"
        
        indicators = [
            {"type": "url_contains", "value": "/dashboard"}
        ]
        
        result = await executor._check_success_indicators(page, indicators)
        assert result is True
        
        # Test failure
        page.url = "https://example.com/login"
        result = await executor._check_success_indicators(page, indicators)
        assert result is False


class TestSessionHealthChecker:
    """Test SessionHealthChecker."""
    
    @pytest.mark.asyncio
    async def test_health_check_success(self, sample_session_data):
        checker = SessionHealthChecker({
            "default_url": "/api/me",
            "expected_status": [200]
        })
        
        # Mock page and response
        page = AsyncMock()
        response = AsyncMock()
        response.status = 200
        page.goto = AsyncMock(return_value=response)
        page.url = "https://example.com/api/me"
        page.context.add_cookies = AsyncMock()
        page.set_extra_http_headers = AsyncMock()
        
        is_healthy, reason = await checker.check_session(page, sample_session_data)
        
        assert is_healthy is True
        assert reason == "Session healthy"
    
    @pytest.mark.asyncio
    async def test_health_check_auth_failure(self, sample_session_data):
        checker = SessionHealthChecker()
        
        # Mock 401 response
        page = AsyncMock()
        response = AsyncMock()
        response.status = 401
        page.goto = AsyncMock(return_value=response)
        page.context.add_cookies = AsyncMock()
        page.set_extra_http_headers = AsyncMock()
        
        is_healthy, reason = await checker.check_session(page, sample_session_data)
        
        assert is_healthy is False
        assert "401" in reason
    
    @pytest.mark.asyncio
    async def test_health_check_redirect_to_login(self, sample_session_data):
        checker = SessionHealthChecker({
            "redirect_patterns": ["/login", "/signin"]
        })
        
        # Mock redirect to login
        page = AsyncMock()
        response = AsyncMock()
        response.status = 200
        page.goto = AsyncMock(return_value=response)
        page.url = "https://example.com/login"
        page.context.add_cookies = AsyncMock()
        page.set_extra_http_headers = AsyncMock()
        
        is_healthy, reason = await checker.check_session(page, sample_session_data)
        
        assert is_healthy is False
        assert "login" in reason.lower()


class TestSessionManager:
    """Test SessionManager."""
    
    @pytest.mark.asyncio
    async def test_create_session(self):
        store = SessionStore(redis_url=None)
        await store.connect()
        
        health_checker = SessionHealthChecker()
        manager = SessionManager(store, health_checker)
        
        session = await manager.create_session(
            engagement_id="test-eng",
            role="admin",
            cookies=[{"name": "sid", "value": "123"}],
            headers={"Auth": "Bearer token"},
            tokens={"token": "abc"}
        )
        
        assert session.engagement_id == "test-eng"
        assert session.role == "admin"
        assert session.is_healthy is True
        
        # Verify stored
        retrieved = await manager.get_session("test-eng", "admin")
        assert retrieved is not None
        assert retrieved.role == "admin"
        
        await manager.cleanup()
    
    @pytest.mark.asyncio
    async def test_should_check_health(self):
        store = SessionStore(redis_url=None)
        await store.connect()
        
        health_checker = SessionHealthChecker()
        manager = SessionManager(
            store,
            health_checker,
            health_check_interval=5
        )
        
        # First 4 calls should return False
        for i in range(4):
            should_check = await manager.should_check_health("test-eng", "admin")
            assert should_check is False
        
        # 5th call should return True
        should_check = await manager.should_check_health("test-eng", "admin")
        assert should_check is True
        
        # Counter should reset
        should_check = await manager.should_check_health("test-eng", "admin")
        assert should_check is False
        
        await manager.cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
