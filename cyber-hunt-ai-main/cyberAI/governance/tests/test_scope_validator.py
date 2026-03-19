"""
Unit tests for ScopeValidator.
"""

import pytest

from cyberAI.governance.scope_validator import ScopeDecision, ScopeValidator


class TestScopeValidator:
    """Test suite for ScopeValidator."""
    
    def test_basic_domain_matching(self):
        """Test basic domain matching."""
        validator = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=[],
            allowed_schemes=["https"],
        )
        
        # In scope
        result = validator.is_in_scope("https://example.com/api/users")
        assert result.decision == ScopeDecision.ALLOW
        
        # Out of scope - different domain
        result = validator.is_in_scope("https://evil.com/")
        assert result.decision == ScopeDecision.DENY
    
    def test_subdomain_matching(self):
        """Test that subdomains are allowed."""
        validator = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=[],
            allowed_schemes=["https"],
        )
        
        # Subdomain should be allowed
        result = validator.is_in_scope("https://api.example.com/v1/data")
        assert result.decision == ScopeDecision.ALLOW
        
        result = validator.is_in_scope("https://admin.example.com/dashboard")
        assert result.decision == ScopeDecision.ALLOW
    
    def test_scheme_validation(self):
        """Test scheme validation."""
        validator = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=[],
            allowed_schemes=["https"],
        )
        
        # HTTPS allowed
        result = validator.is_in_scope("https://example.com/")
        assert result.decision == ScopeDecision.ALLOW
        
        # HTTP not allowed
        result = validator.is_in_scope("http://example.com/")
        assert result.decision == ScopeDecision.DENY
        assert "scheme" in result.reason.lower()
    
    def test_glob_pattern_matching(self):
        """Test glob pattern matching for out-of-scope URLs."""
        validator = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=["*/logout", "*/delete/*"],
            allowed_schemes=["https"],
        )
        
        # Normal URL - allowed
        result = validator.is_in_scope("https://example.com/api/users")
        assert result.decision == ScopeDecision.ALLOW
        
        # Logout - denied
        result = validator.is_in_scope("https://example.com/logout")
        assert result.decision == ScopeDecision.DENY
        assert result.matched_pattern == "*/logout"
        
        # Delete path - denied
        result = validator.is_in_scope("https://example.com/admin/delete/user")
        assert result.decision == ScopeDecision.DENY
        assert result.matched_pattern == "*/delete/*"
    
    def test_url_normalization(self):
        """Test URL normalization."""
        validator = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=[],
            allowed_schemes=["https"],
        )
        
        # Fragment should be stripped
        result = validator.is_in_scope("https://example.com/page#section")
        assert result.decision == ScopeDecision.ALLOW
        assert "#section" not in result.normalized_url
        
        # Query params should be sorted
        url1 = "https://example.com/api?b=2&a=1"
        url2 = "https://example.com/api?a=1&b=2"
        result1 = validator.is_in_scope(url1)
        result2 = validator.is_in_scope(url2)
        assert result1.normalized_url == result2.normalized_url
    
    def test_default_port_removal(self):
        """Test that default ports are removed during normalization."""
        validator = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=[],
            allowed_schemes=["https", "http"],
        )
        
        # HTTPS default port 443
        result = validator.is_in_scope("https://example.com:443/api")
        assert result.decision == ScopeDecision.ALLOW
        assert ":443" not in result.normalized_url
        
        # HTTP default port 80
        result = validator.is_in_scope("http://example.com:80/api")
        assert result.decision == ScopeDecision.ALLOW
        assert ":80" not in result.normalized_url
    
    def test_multiple_target_domains(self):
        """Test with multiple target domains."""
        validator = ScopeValidator(
            target_domains=[
                "https://example.com",
                "https://api.example.org",
            ],
            out_of_scope_patterns=[],
            allowed_schemes=["https"],
        )
        
        # Both domains should be allowed
        result = validator.is_in_scope("https://example.com/page")
        assert result.decision == ScopeDecision.ALLOW
        
        result = validator.is_in_scope("https://api.example.org/v1/data")
        assert result.decision == ScopeDecision.ALLOW
        
        # Different domain should be denied
        result = validator.is_in_scope("https://evil.com/")
        assert result.decision == ScopeDecision.DENY
    
    def test_is_allowed_convenience_method(self):
        """Test the is_allowed convenience method."""
        validator = ScopeValidator(
            target_domains=["https://example.com"],
            out_of_scope_patterns=["*/logout"],
            allowed_schemes=["https"],
        )
        
        assert validator.is_allowed("https://example.com/api") is True
        assert validator.is_allowed("https://example.com/logout") is False
        assert validator.is_allowed("https://evil.com/") is False
    
    def test_stats(self):
        """Test validator statistics."""
        validator = ScopeValidator(
            target_domains=["https://example.com", "https://api.example.com"],
            out_of_scope_patterns=["*/logout", "*/delete/*"],
            allowed_schemes=["https", "http"],
        )
        
        stats = validator.get_stats()
        assert stats["allowed_domains"] == 2
        assert stats["out_of_scope_globs"] == 2
        assert "https" in stats["allowed_schemes"]
        assert "http" in stats["allowed_schemes"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
