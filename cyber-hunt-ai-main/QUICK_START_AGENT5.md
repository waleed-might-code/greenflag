# Quick Start: Data Mining System

## 5-Minute Setup

### 1. Install Dependencies

```bash
cd cyber-hunt-ai-main/cyberAI
pip install -r requirements.txt
```

### 2. Create Engagement Config

```yaml
# engagement.yaml
engagement_id: "test-001"
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

### 3. Run Basic Crawl

```python
import asyncio
from pathlib import Path
from governance import EngagementConfig, ScopeEnforcingClient
from crawl import CrawlOrchestrator

async def main():
    # Load config
    config = EngagementConfig.from_file(Path("engagement.yaml"))
    
    # Create scope-enforcing client
    client = ScopeEnforcingClient(engagement_config=config)
    
    # Create orchestrator
    orchestrator = CrawlOrchestrator(
        base_url=config.target_domains[0],
        max_depth=5,
        max_pages=100,
    )
    orchestrator.client = client
    
    # Run crawl
    stats = await orchestrator.crawl()
    
    print(f"✓ Crawled {stats['pages_crawled']} pages")
    print(f"✓ Found {stats['apis_discovered']} APIs")
    print(f"✓ Extracted {stats['insertion_points']} insertion points")
    
    await orchestrator.close()

asyncio.run(main())
```

### 4. Check Results

Results are saved to `outputs/crawl/`:
- `state_graph.json` - State transitions
- `novelty_stats.json` - Unique endpoints
- `frontier_stats.json` - Crawl statistics
- `crawl_stats.json` - Overall stats

## Common Use Cases

### Use Case 1: API Discovery Only

```python
from crawl import APIDiscovery
import httpx

async def discover_apis():
    client = httpx.AsyncClient()
    discovery = APIDiscovery()
    
    endpoints = await discovery.discover_from_base_url(
        "https://api.example.com",
        client
    )
    
    for ep in endpoints:
        print(f"{ep.method} {ep.path}")
        print(f"  Params: {len(ep.parameters)}")
        print(f"  Auth: {ep.auth_required}")
```

### Use Case 2: Form Extraction

```python
from crawl import FormExtractor

extractor = FormExtractor()
forms = extractor.extract_forms(html_content, base_url)

for form in forms:
    print(f"Form: {form.method} {form.action}")
    print(f"  Fields: {len(form.fields)}")
    print(f"  Has CSRF: {form.has_csrf_token}")
    print(f"  File upload: {form.has_file_upload}")
```

### Use Case 3: Insertion Point Extraction

```python
from recon import InsertionPointExtractor

extractor = InsertionPointExtractor()
canonical = extractor.extract(
    method="POST",
    url="https://api.example.com/users/123",
    headers={"Authorization": "Bearer token"},
    body=b'{"name": "test"}',
    content_type="application/json"
)

print(f"URL template: {canonical.url_template}")
print(f"Insertion points: {len(canonical.insertion_points)}")
for point in canonical.insertion_points:
    print(f"  - {point.location} ({point.inferred_type})")
```

### Use Case 4: Scope Enforcement Only

```python
from governance import EngagementConfig, ScopeEnforcingClient

config = EngagementConfig.create_default(
    target_url="https://example.com",
    name="Quick Test"
)
config.out_of_scope_patterns = ["*/logout", "*/admin/delete/*"]

client = ScopeEnforcingClient(engagement_config=config)

# This will succeed
response, _ = await client.get("https://example.com/api/users")

# This will raise ScopeViolation
try:
    response, _ = await client.get("https://example.com/logout")
except ScopeViolation as e:
    print(f"Blocked: {e.reason}")
```

## Configuration Options

### Engagement Config

```yaml
engagement_id: "uuid"
name: "Engagement Name"

# Required
target_domains:
  - "https://target.example.com"

# Optional
out_of_scope_patterns:
  - "*/logout"
  - "*/delete/*"
  - "*.staging.*"

allowed_schemes:
  - "https"
  - "http"

rate_limits:
  per_host_rps: 10    # Max requests per second per host
  global_rps: 50      # Max requests per second globally
  backoff_on_5xx: "exponential"

data_retention:
  raw_capture_ttl_days: 90
  structured_ttl_days: 365
  permitted_data_classes:
    - "request_response_meta"
    - "finding_evidence"
    - "insertion_point_schema"
```

### Orchestrator Options

```python
orchestrator = CrawlOrchestrator(
    base_url="https://target.example.com",
    max_depth=10,        # Maximum crawl depth
    max_pages=10000,     # Maximum pages to crawl
    output_dir=Path("outputs/crawl"),
)
```

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'loguru'"

```bash
pip install loguru
```

### Issue: "ModuleNotFoundError: No module named 'bs4'"

```bash
pip install beautifulsoup4
```

### Issue: Scope validation too strict

Check your `out_of_scope_patterns`. Use `*` for wildcards:
- `*/logout` - Matches any path ending in /logout
- `*/admin/*` - Matches any path with /admin/ in it
- `*.staging.*` - Matches any subdomain with "staging"

### Issue: Rate limiting too aggressive

Adjust in engagement config:
```yaml
rate_limits:
  per_host_rps: 20    # Increase from 10
  global_rps: 100     # Increase from 50
```

## Next Steps

1. **Add test identities** for multi-role testing
2. **Integrate with session management** (Agent #3)
3. **Add WARC storage** for evidence (Agent #6)
4. **Connect to reporting** (Agent #7)

## Support

- See `governance/README.md` for governance layer details
- See `IMPLEMENTATION_COMPLETE.md` for full system overview
- See `AGENT_5_FINAL_DELIVERY.md` for complete documentation
