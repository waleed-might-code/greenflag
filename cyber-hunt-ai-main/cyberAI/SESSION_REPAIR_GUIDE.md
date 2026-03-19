# Session Repair and Multi-Role Authentication System

## Overview

This system enables **enterprise-grade authenticated crawling** with automatic session repair, supporting multiple user roles (admin, user, guest) to discover authorization vulnerabilities and map differential access.

## Key Features

### 1. **Login Macro System**
- Record login sequences as reusable JSON files
- Support for complex flows (multi-step, CAPTCHA pauses, OAuth)
- Parameterized credentials (username/password injection)
- Selector-based (not coordinate-based) for reliability

### 2. **Session Management**
- Redis-backed session store with in-memory fallback
- Per-role session isolation
- TTL-based expiration
- Cookie, header, and token storage

### 3. **Automatic Session Repair**
- Health checks every N requests (configurable)
- Detects 401/403 responses and login redirects
- Re-executes login macro automatically
- Retry limits to prevent infinite loops
- Locking to prevent concurrent repairs

### 4. **Multi-Role Crawling**
- Crawl as multiple roles in parallel
- Track what each role can access
- Differential access analysis (BOLA/IDOR detection)
- Per-role WARC capture for evidence

## Quick Start

### Step 1: Record Login Sequences

Use the interactive recorder to create login macros:

```bash
cd cyber-hunt-ai-main/cyberAI
python cli_session_recorder.py
```

Follow the prompts:
- Enter login URL
- Enter role name (e.g., "admin")
- Perform login in the browser
- Press ENTER when done

This creates `login_sequences/admin_login.json`.

### Step 2: Configure Engagement

Create an engagement configuration:

```python
from pathlib import Path
from cyberAI.session_integration import EngagementConfig

config = EngagementConfig(
    engagement_id="my-pentest-2024",
    roles=["admin", "user", "guest"],
    login_sequences={
        "admin": Path("login_sequences/admin_login.json"),
        "user": Path("login_sequences/user_login.json"),
        "guest": Path("login_sequences/guest_login.json")
    },
    credentials={
        "admin": {"username": "admin@example.com", "password": "admin123"},
        "user": {"username": "user@example.com", "password": "user123"},
        "guest": {"username": "guest@example.com", "password": "guest123"}
    },
    validation_config={
        "default_url": "/api/me",
        "expected_status": [200],
        "redirect_patterns": ["/login", "/signin", "/auth"]
    },
    redis_url="redis://localhost:6379",  # Optional, uses in-memory if None
    session_ttl_seconds=3600,
    health_check_interval=100  # Check every 100 requests
)
```

### Step 3: Run Authenticated Crawl

```python
from cyberAI.crawl.session_aware_orchestrator import SessionAwareCrawlOrchestrator

orchestrator = SessionAwareCrawlOrchestrator(
    base_url="https://target.example.com",
    engagement_config=config,
    max_depth=10,
    max_pages_per_role=5000,
    output_dir=Path("outputs/crawl"),
    warc_dir=Path("outputs/warc")
)

await orchestrator.initialize()
stats = await orchestrator.crawl_all_roles()

# Results:
# - outputs/crawl/{role}/stats.json
# - outputs/crawl/differential_access.json
# - outputs/warc/{engagement_id}_{role}.warc.gz
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Session-Aware Orchestrator                  │
│  - Multi-role crawl coordination                             │
│  - Differential access tracking                              │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
┌──────────────┐    ┌──────────────┐
│ Role: Admin  │    │ Role: User   │
│ - Frontier   │    │ - Frontier   │
│ - Session    │    │ - Session    │
│ - WARC       │    │ - WARC       │
└──────┬───────┘    └──────┬───────┘
       │                   │
       └─────────┬─────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│              Session Integration Layer                       │
│  - Session health checking                                   │
│  - Automatic repair on failure                               │
│  - Login macro execution                                     │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
┌──────────────┐    ┌──────────────┐
│ Session      │    │ Login Macro  │
│ Manager      │    │ Executor     │
│ - Store      │    │ - Playwright │
│ - Health     │    │ - Retry      │
│ - Repair     │    │ - Validate   │
└──────────────┘    └──────────────┘
```

## Login Sequence Format

Login sequences are stored as JSON:

```json
{
  "name": "Admin Login",
  "role": "admin",
  "steps": [
    {
      "action": "navigate",
      "url": "https://example.com/login",
      "description": "Navigate to login"
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
      "description": "Verify success"
    }
  ],
  "success_indicators": [
    {"type": "url_contains", "value": "/dashboard"}
  ]
}
```

## Session Repair Flow

```
Request → Health Check Due?
              │
              ├─ No → Continue
              │
              └─ Yes → Validate Session
                          │
                          ├─ Healthy → Continue
                          │
                          └─ Unhealthy → Repair
                                           │
                                           ├─ Execute Login Macro
                                           ├─ Extract Cookies/Tokens
                                           ├─ Validate New Session
                                           │
                                           ├─ Success → Continue
                                           └─ Failure → Retry or Abort
```

## Configuration Options

### Health Check Interval
```python
health_check_interval=100  # Check every 100 requests
```

Lower values = more frequent checks = more overhead but faster detection.
Higher values = less overhead but slower detection.

**Recommended:** 50-100 for production, 10-20 for testing.

### Session TTL
```python
session_ttl_seconds=3600  # 1 hour
```

How long a session is considered valid before forced refresh.

### Validation Config
```python
validation_config={
    "default_url": "/api/me",           # URL to check session health
    "expected_status": [200],            # Expected status codes
    "redirect_patterns": ["/login"]      # Patterns indicating session loss
}
```

## Differential Access Analysis

After crawling, the system generates `differential_access.json`:

```json
{
  "findings": [
    {
      "role_a": "admin",
      "role_b": "user",
      "common_endpoints": 45,
      "only_role_a": 12,
      "only_role_b": 3,
      "overlap_percentage": 75.0
    }
  ]
}
```

**Interpretation:**
- `only_role_b > 0` when role_a is admin → Potential privilege escalation
- High overlap between low-priv and high-priv → Weak authorization

## Advanced: Manual Pause for CAPTCHA

For login flows with CAPTCHA or 2FA:

```python
from cyberAI.login_macro import LoginMacroRecorder, StepAction

recorder = LoginMacroRecorder()
recorder.add_navigate("https://example.com/login")
recorder.add_fill("input[name='email']", "{{username}}")
recorder.add_fill("input[name='password']", "{{password}}")
recorder.add_click("button[type='submit']")

# Add manual pause
recorder.add_manual_pause("Solve CAPTCHA manually")

recorder.add_wait_for_url("/dashboard", 60000)
recorder.add_assert_url("/dashboard")
```

During execution, the system will pause and wait for manual intervention.

## Troubleshooting

### Session Repair Keeps Failing

**Symptoms:** `session_repairs` count keeps increasing, crawl stops.

**Causes:**
1. Login sequence is incorrect
2. Credentials are wrong
3. Target has rate limiting
4. CAPTCHA/2FA not handled

**Solutions:**
- Re-record login sequence
- Verify credentials
- Add delays between requests
- Add manual pause step for CAPTCHA

### Sessions Expire Too Quickly

**Symptoms:** Health checks fail frequently, many repairs.

**Solutions:**
- Increase `session_ttl_seconds`
- Decrease `health_check_interval` for faster detection
- Check if target has aggressive session timeout

### Different Roles See Same Content

**Symptoms:** `differential_access.json` shows 100% overlap.

**Solutions:**
- Verify login sequences are correct for each role
- Check that credentials are different
- Ensure target actually has role-based access control

## Integration with Existing System

To integrate with your existing crawlers:

```python
from cyberAI.session_integration import create_session_integration

# Initialize session management
session_integration = await create_session_integration(
    engagement_id="my-engagement",
    roles=["admin", "user"],
    login_sequences_dir=Path("login_sequences"),
    credentials=credentials_dict,
    validation_url="/api/me"
)

# In your crawler
async with async_playwright() as p:
    browser = await p.chromium.launch()
    
    # Get session-aware context
    context, session = await session_integration.get_session_context(
        browser=browser,
        role="admin"
    )
    
    page = await context.new_page()
    
    # Crawl with automatic session repair
    for url in urls:
        # Check if health check is due
        if await session_integration.should_check_health("admin"):
            success, session = await session_integration.validate_and_repair_session(
                browser=browser,
                role="admin",
                page=page
            )
            if not success:
                break  # Session repair failed
        
        # Continue crawling
        await page.goto(url)
```

## Performance Considerations

- **Redis:** Use Redis for production (faster, persistent)
- **Parallel Roles:** Roles crawl in parallel, scales linearly
- **WARC Size:** Each role generates separate WARC files
- **Memory:** ~100MB per role for frontier + state tracking

## Security Notes

- **Credentials:** Store in environment variables or secure vault
- **WARC Files:** Contain full request/response including auth tokens
- **Session Store:** Redis should be secured (password, TLS)
- **Engagement Config:** Never commit credentials to git

## Next Steps

1. Record login sequences for your target
2. Configure engagement with roles and credentials
3. Run authenticated crawl
4. Analyze differential access findings
5. Use WARC files as evidence for vulnerabilities
