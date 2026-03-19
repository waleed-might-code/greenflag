# Session Management and Login Macro System

Enterprise-grade session management for authenticated security testing with automatic repair and multi-role support.

## Features

- **Multi-role session management**: Maintain separate sessions for guest, user, admin, etc.
- **Automatic health checking**: Periodically validate sessions and detect failures
- **Session repair**: Automatically re-login when sessions expire or break
- **Login macros**: Record and replay complex login sequences
- **Redis-backed storage**: Persistent session storage with in-memory fallback
- **Retry logic**: Robust error handling and retry mechanisms
- **CAPTCHA/2FA support**: Manual pause steps for human intervention
- **Token extraction**: Extract tokens from cookies, localStorage, or DOM

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Session Integration Layer                   │
│  (High-level API for crawlers and test workers)         │
└─────────────────┬───────────────────────────────────────┘
                  │
      ┌───────────┼───────────┐
      │           │           │
      ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Session  │ │  Health  │ │ Login Macro  │
│  Store   │ │ Checker  │ │  Executor    │
│ (Redis)  │ │          │ │              │
└──────────┘ └──────────┘ └──────────────┘
```

## Quick Start

### 1. Create a Login Sequence

Use the CLI tool to create a login sequence:

```bash
cd cyber-hunt-ai-main/cyberAI
python cli_login_macro.py create \
  --name "Admin Login" \
  --role admin \
  --output ../login_sequences/admin_login.json
```

Or create manually from the examples in `login_sequences/`.

### 2. Test the Login Sequence

```bash
python cli_login_macro.py test \
  ../login_sequences/admin_login.json \
  --username admin@example.com \
  --password yourpassword \
  --headed
```

### 3. Integrate into Your Crawler

```python
from cyberAI.session_integration import create_session_integration
from playwright.async_api import async_playwright

# Initialize session management
session_integration = await create_session_integration(
    engagement_id="engagement-001",
    roles=["user", "admin"],
    login_sequences_dir=Path("login_sequences"),
    credentials={
        "user": {"username": "user@example.com", "password": "pass123"},
        "admin": {"username": "admin@example.com", "password": "adminpass"}
    },
    validation_url="/api/me",
    redis_url="redis://localhost:6379/0"  # Optional
)

# Get session-aware browser context
async with async_playwright() as p:
    browser = await p.chromium.launch()
    context, session = await session_integration.get_session_context(
        browser=browser,
        role="admin"
    )
    
    page = await context.new_page()
    
    # Your crawling logic here
    # Session will be automatically validated and repaired
```

## Login Sequence Format

Login sequences are JSON files with step-by-step instructions:

```json
{
  "name": "Admin Login",
  "role": "admin",
  "steps": [
    {
      "action": "navigate",
      "url": "https://example.com/login",
      "description": "Go to login page"
    },
    {
      "action": "fill",
      "selector": "input[name='email']",
      "value_ref": "{{username}}",
      "description": "Fill email"
    },
    {
      "action": "fill",
      "selector": "input[name='password']",
      "value_ref": "{{password}}",
      "description": "Fill password"
    },
    {
      "action": "click",
      "selector": "button[type='submit']",
      "description": "Submit form"
    },
    {
      "action": "assert_url",
      "expected": "/dashboard",
      "description": "Verify login success"
    }
  ],
  "success_indicators": [
    {"type": "url_contains", "value": "/dashboard"}
  ]
}
```

### Available Actions

- `navigate`: Navigate to URL
- `fill`: Fill form field (supports `{{credential}}` placeholders)
- `click`: Click element
- `wait`: Wait for N seconds
- `wait_for_selector`: Wait for element to appear
- `wait_for_url`: Wait for URL pattern
- `assert_url`: Assert URL contains text
- `assert_text`: Assert element contains text
- `extract_cookies`: Extract cookies
- `extract_token`: Extract token from cookie/localStorage/DOM
- `manual_pause`: Pause for manual intervention (CAPTCHA/2FA)
- `screenshot`: Take debug screenshot

## Session Health Checking

Sessions are automatically validated:

```python
# Check every 100 requests
if await session_integration.should_check_health(role):
    success, session = await session_integration.validate_and_repair_session(
        browser=browser,
        role=role,
        page=page
    )
    
    if not success:
        logger.error("Session repair failed")
```

Health checks detect:
- 401/403 responses
- Redirects to login pages
- Missing expected content
- Expired sessions

## Session Repair

When a session fails health check, the system:

1. Locks the session to prevent concurrent repairs
2. Executes the login macro with stored credentials
3. Extracts new cookies and tokens
4. Validates the new session
5. Updates the session store
6. Retries up to N times (default: 3)

## Redis Configuration

For production use, configure Redis:

```python
session_integration = await create_session_integration(
    # ... other params ...
    redis_url="redis://localhost:6379/0"
)
```

Without Redis, sessions are stored in-memory (lost on restart).

## CLI Commands

```bash
# Create a new login sequence interactively
python cli_login_macro.py create

# Test a login sequence
python cli_login_macro.py test login_sequences/admin_login.json

# List all login sequences
python cli_login_macro.py list --dir login_sequences

# Show sequence details
python cli_login_macro.py show login_sequences/admin_login.json
```

## Examples

See `examples/session_crawler_example.py` for complete integration examples:

- Single-role authenticated crawling
- Multi-role parallel crawling
- Automatic session repair
- Health checking integration

## Configuration

Add to your `.env`:

```bash
# Session management
REDIS_URL=redis://localhost:6379/0
SESSION_TTL_SECONDS=3600
SESSION_HEALTH_CHECK_INTERVAL=100
SESSION_MAX_REPAIR_ATTEMPTS=3

# Validation
SESSION_VALIDATION_URL=/api/me
SESSION_EXPECTED_STATUS=200
```

## Best Practices

1. **Test login sequences** before production use
2. **Use selector strategies**: Prefer data-testid > id > class
3. **Add wait steps**: After navigation and before assertions
4. **Handle CAPTCHA**: Use manual_pause for human intervention
5. **Monitor repair rate**: High repair rates indicate sequence issues
6. **Use Redis in production**: For session persistence across restarts
7. **Rotate credentials**: Use different test accounts per engagement

## Troubleshooting

### Login sequence fails

- Run with `--headed` to see browser
- Add `screenshot` steps for debugging
- Check selectors are correct
- Increase timeout values
- Add wait_for_selector before interactions

### Session repair loops

- Check validation URL is correct
- Verify success indicators match actual page
- Ensure credentials are valid
- Check for rate limiting

### Redis connection fails

- System falls back to in-memory store
- Sessions won't persist across restarts
- Check Redis is running: `redis-cli ping`

## Integration with Existing System

The session management layer integrates with your existing crawler:

```python
# In your crawler worker
from cyberAI.session_integration import SessionIntegration

class AuthenticatedCrawler:
    def __init__(self, session_integration: SessionIntegration):
        self.session_integration = session_integration
    
    async def crawl(self, role: str):
        context, session = await self.session_integration.get_session_context(
            browser=self.browser,
            role=role
        )
        
        # Your existing crawl logic
        # Sessions are automatically managed
```

## Performance

- Session validation: ~100-500ms
- Session repair: ~2-5 seconds (full login)
- Redis operations: <10ms
- Health check overhead: Minimal (every N requests)

## Security

- Credentials stored in memory only
- Redis connection should use TLS in production
- Session tokens encrypted at rest (if using Redis with encryption)
- Audit log of all session operations
