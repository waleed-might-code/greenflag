# Evidence Capture Integration Guide

This guide shows how to integrate the WARC-based evidence capture system into your existing CyberAI workflows.

## Quick Start

### 1. Basic Usage

```python
from cyberAI.evidence import CaptureSession
from pathlib import Path

# Create capture session
session = CaptureSession("engagement-123", Path("outputs/evidence"))

# Capture a request
req_ref = session.capture_request(
    request_id="req-001",
    method="GET",
    url="https://target.com/api/users/123",
    headers={"Authorization": "Bearer token"},
    body=None
)

# Capture response
resp_ref = session.capture_response(
    request_id="req-001",
    url="https://target.com/api/users/123",
    status_code=200,
    headers={"Content-Type": "application/json"},
    body=b'{"id": 123, "role": "admin"}'
)

# Link to finding
session.link_finding("finding-idor-001", ["req-001"])

session.close()
```

### 2. Playwright Integration

```python
from playwright.async_api import async_playwright
from cyberAI.evidence import CaptureSession, CaptureMiddleware
from cyberAI.evidence.integration import wrap_playwright_page

async def crawl_with_capture():
    session = CaptureSession("engagement-123", Path("outputs/evidence"))
    middleware = CaptureMiddleware(session)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # Wrap page - all traffic now captured
        wrap_playwright_page(page, middleware)
        
        await page.goto("https://target.com")
        # ... interact with page ...
        
        await browser.close()
    
    session.close()
```

### 3. Integrate with Existing Recon

Modify `cyberAI/recon/core_discovery.py`:

```python
# Add at top
from cyberAI.evidence import CaptureSession, CaptureMiddleware
from cyberAI.evidence.integration import wrap_playwright_page

# In run_core_discovery function
async def run_core_discovery(config: Config) -> dict:
    # Create evidence session
    evidence_session = CaptureSession(
        engagement_id=config.run_id,
        output_dir=config.get_output_path("evidence")
    )
    middleware = CaptureMiddleware(evidence_session)
    
    # ... existing browser setup ...
    page = await context.new_page()
    
    # Wrap page for capture
    wrap_playwright_page(page, middleware)
    
    # ... rest of existing code ...
    
    # At end
    evidence_session.close()
```

### 4. Integrate with Testing

Modify `cyberAI/testing/authz_tester.py`:

```python
from cyberAI.evidence import CaptureSession

class AuthzTester:
    def __init__(self, config: Config, evidence_session: CaptureSession):
        self.config = config
        self.evidence_session = evidence_session
    
    async def test_endpoint(self, endpoint, roles):
        request_ids = []
        
        for role in roles:
            # Make request
            req_id = str(uuid4())
            response = await self.client.get(endpoint.url)
            
            # Capture evidence
            self.evidence_session.capture_request(
                req_id, "GET", endpoint.url, 
                dict(response.request.headers), None
            )
            self.evidence_session.capture_response(
                req_id, endpoint.url, response.status_code,
                dict(response.headers), response.content
            )
            
            request_ids.append(req_id)
        
        # If vulnerability found
        if is_vulnerable:
            finding = Finding(...)
            self.evidence_session.link_finding(finding.id, request_ids)
            finding.evidence_warc_refs = [
                self.evidence_session.request_map[rid].warc_ref 
                for rid in request_ids
            ]
```

## API Server

Start the evidence API:

```bash
cd cyber-hunt-ai-main/cyberAI/evidence
python api.py
```

Endpoints:
- `GET /health` - Health check
- `GET /api/evidence/findings/<finding_id>` - Get evidence for finding
- `GET /api/evidence/pack/<finding_id>` - Download evidence pack
- `GET /api/evidence/stats` - Evidence statistics
- `GET /api/evidence/engagements` - List engagements

## Evidence Pack Generation

```python
from cyberAI.evidence import ProvenanceTracker

tracker = ProvenanceTracker(Path("outputs/evidence/provenance"))
tracker.generate_evidence_pack(
    finding_id="finding-idor-001",
    warc_dir=Path("outputs/evidence/warc"),
    output_path=Path("evidence_pack.warc.gz")
)
```

## Best Practices

1. **Create one CaptureSession per engagement** - Don't reuse across engagements
2. **Always close sessions** - Use context managers or explicit close()
3. **Link findings immediately** - Don't wait until end of scan
4. **Use meaningful request IDs** - Include context (e.g., "authz-test-admin-001")
5. **Monitor WARC file sizes** - Files rotate at 10k records automatically

## Storage Requirements

- ~1KB per request/response pair (compressed)
- 10,000 requests = ~10MB WARC file
- 1 million requests = ~1GB storage
- Automatic file rotation prevents single large files

## Troubleshooting

**Issue**: Module import errors
```bash
cd cyber-hunt-ai-main/cyberAI
pip install -r requirements.txt
```

**Issue**: WARC files not created
- Check output directory permissions
- Verify CaptureSession was initialized
- Check logs for errors

**Issue**: Evidence not linked to findings
- Ensure request_id matches between capture and link
- Verify finding ID is correct
- Check provenance_index.jsonl exists

## Next Steps

1. Integrate with all recon modules
2. Integrate with all test modules
3. Add WARC refs to report templates
4. Implement retention policies
5. Add deduplication for similar responses
