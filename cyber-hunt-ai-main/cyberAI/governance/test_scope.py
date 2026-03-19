"""
Test scope validation functionality.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cyberAI.governance import ScopeValidator, ScopeConfig


def test_scope_validation():
    """Test scope validator."""
    print("=== Testing Scope Validation ===\n")
    
    # Create scope config
    config = ScopeConfig(
        engagement_id="test_001",
        target_domains=["https://api.target.com", "https://app.target.com"],
        out_of_scope_patterns=["*/logout", "*/delete/*", "*.staging.*"],
        allowed_schemes=["https"],
        allow_subdomains=True
    )
    
    validator = ScopeValidator(config)
    
    # Test cases
    test_cases = [
        ("https://api.target.com/users", True, "Main API endpoint"),
        ("https://api.target.com/users/123", True, "User detail endpoint"),
        ("https://app.target.com/dashboard", True, "App domain"),
        ("https://admin.api.target.com/settings", True, "Subdomain (allowed)"),
        ("http://api.target.com/users", False, "HTTP not allowed"),
        ("https://api.target.com/logout", False, "Logout excluded"),
        ("https://api.target.com/users/delete/123", False, "Delete pattern excluded"),
        ("https://staging.api.target.com/users", False, "Staging excluded"),
        ("https://evil.com/phishing", False, "Out of scope domain"),
    ]
    
    passed = 0
    failed = 0
    
    for url, expected, description in test_cases:
        result = validator.is_in_scope(url)
        status = "✓" if result == expected else "✗"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} {description}")
        print(f"  URL: {url}")
        print(f"  Expected: {expected}, Got: {result}\n")
    
    print(f"=== Results ===")
    print(f"Passed: {passed}/{len(test_cases)}")
    print(f"Failed: {failed}/{len(test_cases)}")
    
    return failed == 0


if __name__ == "__main__":
    success = test_scope_validation()
    sys.exit(0 if success else 1)
