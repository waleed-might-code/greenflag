# CyberAI Evidence System - Quick Start

## Installation

The evidence module is already integrated into the CyberAI platform. No additional installation needed.

## Basic Usage

### 1. Import the module

```python
from cyberAI.evidence import CaptureSession
from pathlib import Path
```

### 2. Create a capture session

```python
session = CaptureSession(
    engagement_id="engagement-001",
    output_dir=Path("outputs/evidence")
)
```

### 3. Capture HTTP traffic

```python
# Capture request
req_ref = session.capture_request(
    request_id="req-001",
    method="GET",
    url="https://api.target.com/users/123",
    headers={"Authorization": "Bearer token"},
    body=None
)

# Capture response
resp_ref = session.capture_response(
    request_id="req-001",
    url="https://api.target.com/users/123",
    status_code=200,
    headers={"Content-Type": "application/json"},
    body=b'{"id": 123, "role": "admin"}'
)
```

### 4. Link findings to evidence

```python
session.link_finding("finding-idor-001", ["req-001", "req-002"])
```

### 5. Close the session

```python
session.close()
```

## Run the Demo

```bash
cd cyber-hunt-ai-main/cyberAI
python3 << 'DEMO'
from pathlib import Path
import tempfile
from evidence import CaptureSession

with tempfile.TemporaryDirectory() as tmpdir:
    session = CaptureSession("demo", Path(tmpdir))
    
    # Capture traffic
    session.capture_request("req-1", "GET", "https://example.com", {}, None)
    session.capture_response("req-1", "https://example.com", 200, {}, b"OK")
    
    # Link finding
    session.link_finding("finding-1", ["req-1"])
    
    # Retrieve evidence
    refs = session.provenance.get_evidence_for_finding("finding-1")
    print(f"✓ Linked {len(refs)} evidence references")
    
    session.close()
DEMO
```

## Start the API Server

```bash
cd cyber-hunt-ai-main/cyberAI/evidence
python3 api.py
```

Access at: http://localhost:5004

**Endpoints:**
- `GET /health` - Health check
- `GET /api/evidence/findings/<id>` - Get evidence
- `GET /api/evidence/pack/<id>` - Download evidence pack
- `GET /api/evidence/stats` - Statistics

## Integration with Playwright

```python
from playwright.async_api import async_playwright
from cyberAI.evidence import CaptureSession, CaptureMiddleware
from cyberAI.evidence.integration import wrap_playwright_page

async def crawl():
    session = CaptureSession("engagement-001", Path("outputs/evidence"))
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

## File Structure

```
outputs/evidence/
├── warc/
│   └── engagement-001_20240115120000_abc123.warc.gz
└── provenance/
    └── provenance_index.jsonl
```

## WARC Reference Format

```
warc://filename.warc.gz#offset:length
```

Example:
```
warc://engagement-001_20240115120000_abc123.warc.gz#0:2048
```

## Next Steps

1. **Integrate with recon**: See `EVIDENCE_INTEGRATION_GUIDE.md`
2. **Integrate with testing**: See `EVIDENCE_INTEGRATION_GUIDE.md`
3. **Deploy API**: See `DEPLOYMENT_PLAN.md`
4. **Configure retention**: Edit engagement config

## Troubleshooting

**Issue**: Import errors
```bash
cd cyber-hunt-ai-main/cyberAI
python3 -c "from evidence import CaptureSession; print('✓ OK')"
```

**Issue**: WARC files not created
- Check directory permissions
- Verify session was initialized
- Check logs

**Issue**: Evidence not linked
- Ensure request_id matches
- Verify finding_id is correct
- Check provenance_index.jsonl exists

## Documentation

- `IMPLEMENTATION_SUMMARY.md` - Technical details
- `DEPLOYMENT_PLAN.md` - Production deployment
- `EVIDENCE_INTEGRATION_GUIDE.md` - Integration guide
- `evidence/README.md` - Module documentation

## Support

For issues:
1. Check logs in `outputs/logs/`
2. Review documentation
3. Run test: `python3 evidence/test_standalone.py`
