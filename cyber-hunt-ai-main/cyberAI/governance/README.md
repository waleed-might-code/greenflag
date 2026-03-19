# Governance Layer - Scope Enforcement

Enterprise-grade scope enforcement for authorized security testing. Ensures every HTTP request is validated against engagement configuration before being sent.

## Features

- **Fast O(1) domain validation** - Pre-compiled domain sets for instant lookup
- **Pattern-based exclusions** - Glob and regex patterns for out-of-scope URLs
- **Rate limiting** - Token bucket algorithm for per-host and global rate limits
- **Audit logging** - Every scope decision logged with timestamp and reason
- **Zero network overhead** - All validation happens in-process, no DB/API calls

## Quick Start

### 1. Create Engagement Config

```yaml
# engagement.yaml
engagement_id: "550e8400-e29b-41d4-a716-446655440000"
name: "My Security Test"

target_domains:
  - "https://target.example.com"

out_of_scope_patterns:
  - "*/logout"
  - "*/delete/*"

allowed_schemes:
  - "https"

rate_limits:
  per_host_rps: 10
  global_rps: 50
```

### 2. Use Scope-Enforcing Client

```python
from governance import EngagementConfig, ScopeEnforcingClient

# Load config
config = EngagementConfig.from_file("engagement.yaml")

# Create client
client = ScopeEnforcingClient(
    engagement_config=config,
    audit_log_path="scope_audit.jsonl"
)

# Make requests - automatically validated
response, record = await client.get("https://target.example.com/api/users")

# Out-of-scope requests are blocked
try:
    await client.get("https://target.example.com/logout")
except ScopeViolation as e:
    print(f"Blocked: {e.reason}")
```

### 3. Integrate with Existing Code

```python
from utils.http_client import AsyncHTTPClient
from governance import EngagementConfig, ScopeEnforcingClient

# Wrap existing client
existing_client = AsyncHTTPClient()
enforcing_client = ScopeEnforcingClient(
    engagement_config=config,
    underlying_client=existing_client
)

# All requests now scope-enforced
response, record = await enforcing_client.get(url)
```

## Architecture

```
Request → ScopeEnforcingClient → ScopeValidator → RateLimiter → AsyncHTTPClient → Network
                ↓                      ↓               ↓
           Audit Log            O(1) Check      Token Bucket
```

### Components

1. **EngagementConfig** - YAML/JSON schema for scope, identities, rate limits
2. **ScopeValidator** - Fast in-process validation (O(1) domain, O(n) patterns)
3. **ScopeEnforcingClient** - HTTP client wrapper that enforces scope
4. **RateLimiter** - Token bucket rate limiter (per-host + global)

## Performance

- **Domain check**: O(1) set lookup after normalization
- **Pattern check**: O(n) where n = number of patterns (typically < 20)
- **No blocking**: Rate limiter uses async sleep, doesn't block event loop
- **Memory**: ~1KB per engagement config, ~100 bytes per audit entry

## Integration Points

### With CoreDiscovery

```python
class CoreDiscovery:
    def __init__(self, engagement_config: Optional[EngagementConfig] = None):
        if engagement_config:
            self._http_client = ScopeEnforcingClient(engagement_config)
        else:
            self._http_client = AsyncHTTPClient()
```

### With Playwright Browser Workers

```python
# Use page.route() to intercept and validate
async def route_handler(route):
    url = route.request.url
    if not validator.is_allowed(url):
        await route.abort()
    else:
        await route.continue_()

await page.route("**/*", route_handler)
```

## Testing

```bash
# Run unit tests
python -m pytest governance/tests/test_scope_validator.py -v

# Run quick integration test
python governance/quick_test.py

# Run full demo
python governance/demo_scope_enforcement.py
```

## Audit Log Format

```json
{
  "timestamp": "2024-03-17T21:30:00.000Z",
  "engagement_id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://target.example.com/logout",
  "method": "GET",
  "decision": "deny",
  "reason": "Matched out-of-scope pattern"
}
```

## Next Steps

1. **Phase 2**: Insertion point extraction and canonicalization
2. **Phase 2**: Multi-identity session management
3. **Phase 2**: WARC writer for evidence storage
4. **Phase 3**: Neural prioritization for crawl frontier

## Files

- `engagement_config.py` - Config schema and loader
- `scope_validator.py` - Fast scope validation logic
- `scope_enforcing_client.py` - HTTP client wrapper
- `example_engagement.yaml` - Example configuration
- `integration_crawler.py` - Integration examples
- `quick_test.py` - Quick validation test
- `demo_scope_enforcement.py` - Full demo with real requests
