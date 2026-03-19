# Session Management System - Quick Reference Card

## 🚀 Quick Start (5 minutes)

### 1. Create Login Sequence
```bash
python cyberAI/cli_login_macro.py create --name "My App Login" --role admin
```

### 2. Test It
```bash
python cyberAI/cli_login_macro.py test login_sequences/admin_login.json
```

### 3. Use in Code
```python
from cyberAI.session_integration import create_session_integration

session_mgr = await create_session_integration(
    engagement_id="test-001",
    roles=["admin"],
    login_sequences_dir=Path("login_sequences"),
    credentials={"admin": {"username": "admin@example.com", "password": "pass"}},
    validation_url="/api/me"
)

context, session = await session_mgr.get_session_context(browser, "admin")
```

---

## 📋 Common Tasks

### Create Login Sequence Manually
```json
{
  "name": "My Login",
  "role": "user",
  "steps": [
    {"action": "navigate", "url": "https://example.com/login"},
    {"action": "fill", "selector": "#email", "value_ref": "{{username}}"},
    {"action": "fill", "selector": "#password", "value_ref": "{{password}}"},
    {"action": "click", "selector": "button[type='submit']"},
    {"action": "assert_url", "expected": "/dashboard"}
  ],
  "success_indicators": [
    {"type": "url_contains", "value": "/dashboard"}
  ]
}
```

### Check Session Health
```python
if await session_mgr.should_check_health("admin"):
    success, session = await session_mgr.validate_and_repair_session(
        browser=browser,
        role="admin",
        page=page
    )
```

### List All Sessions
```python
sessions = await session_mgr.list_sessions()
for session in sessions:
    print(f"{session.role}: healthy={session.is_healthy}, age={session.age_seconds()}s")
```

### Force Re-login
```python
await session_mgr.delete_session("admin")
# Next get_session_context() will trigger fresh login
```

---

## 🔧 Configuration

### Environment Variables
```bash
REDIS_URL=redis://localhost:6379/0
SESSION_TTL_SECONDS=3600
SESSION_HEALTH_CHECK_INTERVAL=100
SESSION_MAX_REPAIR_ATTEMPTS=3
SESSION_VALIDATION_URL=/api/me
LOGIN_SEQUENCES_DIR=login_sequences
```

### In Code
```python
from cyberAI.config_session import SessionConfig

config = SessionConfig.from_env()
```

---

## 📝 Login Sequence Actions

| Action | Description | Example |
|--------|-------------|---------|
| `navigate` | Go to URL | `{"action": "navigate", "url": "https://..."}` |
| `fill` | Fill form field | `{"action": "fill", "selector": "#email", "value_ref": "{{username}}"}` |
| `click` | Click element | `{"action": "click", "selector": "button.login"}` |
| `wait` | Wait N seconds | `{"action": "wait", "value": "2"}` |
| `wait_for_selector` | Wait for element | `{"action": "wait_for_selector", "selector": ".dashboard"}` |
| `wait_for_url` | Wait for URL | `{"action": "wait_for_url", "value": "**/dashboard"}` |
| `assert_url` | Assert URL contains | `{"action": "assert_url", "expected": "/dashboard"}` |
| `assert_text` | Assert element text | `{"action": "assert_text", "selector": "h1", "expected": "Welcome"}` |
| `extract_cookies` | Extract cookies | `{"action": "extract_cookies"}` |
| `extract_token` | Extract token | `{"action": "extract_token", "token_name": "auth", "token_source": "localstorage"}` |
| `manual_pause` | Pause for human | `{"action": "manual_pause", "description": "Solve CAPTCHA"}` |
| `screenshot` | Take screenshot | `{"action": "screenshot"}` |

---

## 🎯 Integration Patterns

### Pattern 1: Simple Crawler
```python
session_mgr = await create_session_integration(...)

async with async_playwright() as p:
    browser = await p.chromium.launch()
    context, session = await session_mgr.get_session_context(browser, "admin")
    page = await context.new_page()
    
    await page.goto("https://example.com/dashboard")
    # Your crawling logic
    
    await context.close()
    await browser.close()
    await session_mgr.cleanup()
```

### Pattern 2: Multi-Role Crawler
```python
for role in ["guest", "user", "admin"]:
    context, session = await session_mgr.get_session_context(browser, role)
    page = await context.new_page()
    
    # Crawl as this role
    await crawl_as_role(page, role)
    
    await context.close()
```

### Pattern 3: Long-Running Worker
```python
context, session = await session_mgr.get_session_context(browser, "admin")
page = await context.new_page()

for url in urls:
    # Check health every 10 requests
    if await session_mgr.should_check_health("admin"):
        success, _ = await session_mgr.validate_and_repair_session(
            browser, "admin", page
        )
        if not success:
            break
    
    await page.goto(url)
    # Process page
```

---

## 🐛 Troubleshooting

### Login Sequence Fails
```bash
# Test with visible browser
python cyberAI/cli_login_macro.py test sequence.json --headed

# Add screenshots for debugging
# In sequence JSON, add: {"action": "screenshot"}
```

### Session Repair Loops
- Check validation URL is correct
- Verify success indicators match actual page
- Ensure credentials are valid
- Check for rate limiting

### Redis Connection Fails
- System falls back to in-memory (sessions lost on restart)
- Check Redis is running: `redis-cli ping`
- Verify REDIS_URL in .env

### Import Errors
```bash
cd cyber-hunt-ai-main/cyberAI
pip install -r requirements.txt
playwright install chromium
```

---

## 📊 Monitoring

### Session Health Metrics
```python
sessions = await session_mgr.list_sessions()
for session in sessions:
    print(f"Role: {session.role}")
    print(f"  Healthy: {session.is_healthy}")
    print(f"  Age: {session.age_seconds():.1f}s")
    print(f"  Repair attempts: {session.repair_attempts}")
    print(f"  Cookies: {len(session.cookies)}")
```

### Repair Rate
```python
# Track repair attempts
total_repairs = sum(s.repair_attempts for s in sessions)
if total_repairs > threshold:
    logger.warning(f"High repair rate: {total_repairs}")
```

---

## 🔐 Security Best Practices

1. **Never commit credentials** - Use .env files (gitignored)
2. **Use Redis TLS** in production - `rediss://` URL scheme
3. **Rotate test accounts** - Use different accounts per engagement
4. **Monitor session logs** - Check for unusual repair patterns
5. **Limit session TTL** - Don't keep sessions alive indefinitely
6. **Validate scope** - Ensure sessions respect engagement boundaries

---

## 📚 Documentation

- **Full Guide**: `SESSION_MANAGEMENT.md`
- **Implementation**: `IMPLEMENTATION_SUMMARY.md`
- **System Overview**: `README_SESSION_SYSTEM.md`
- **API Docs**: Docstrings in `session_manager.py`, `login_macro.py`
- **Examples**: `cyberAI/examples/session_crawler_example.py`

---

## 🆘 Getting Help

1. Check the full documentation in `SESSION_MANAGEMENT.md`
2. Run the demo: `python run_demo.py`
3. Review examples in `cyberAI/examples/`
4. Check unit tests for usage patterns: `cyberAI/tests/test_session_management.py`

---

## ⚡ Performance Tips

- Use Redis for production (persistent sessions)
- Set appropriate health check interval (default: 100 requests)
- Batch operations when possible
- Monitor repair rate (high rate = sequence issues)
- Use connection pooling for Redis
- Cache session data in workers

---

## 🎓 Advanced Features

### Custom Health Checker
```python
from cyberAI.session_manager import SessionHealthChecker

checker = SessionHealthChecker({
    "default_url": "/api/me",
    "expected_status": [200],
    "expected_content": "authenticated",
    "redirect_patterns": ["/login", "/signin"]
})
```

### Custom Repair Logic
```python
async def custom_repair(engagement_id, role, page):
    # Your custom repair logic
    # Return dict with cookies, headers, tokens
    return {
        "cookies": [...],
        "headers": {...},
        "tokens": {...}
    }

success, session = await manager.validate_and_repair(
    engagement_id, role, page, repair_callback=custom_repair
)
```

### Session Metadata
```python
session.metadata = {
    "user_id": "12345",
    "permissions": ["read", "write"],
    "custom_field": "value"
}
await store.set(session)
```

---

**Version**: 1.0.0  
**Last Updated**: 2024  
**License**: See project LICENSE
