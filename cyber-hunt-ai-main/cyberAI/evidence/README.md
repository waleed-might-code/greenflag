# Evidence Capture & Provenance System

This module implements WARC-based evidence capture for the CyberAI platform.

## Components

- **warc_writer.py**: Writes HTTP traffic to WARC (ISO 28500) format
- **provenance.py**: Links findings to WARC evidence references
- **capture.py**: Manages capture sessions per engagement
- **integration.py**: Middleware for Playwright and httpx integration

## Usage

```python
from cyberAI.evidence import CaptureSession, CaptureMiddleware

# Create capture session
session = CaptureSession("engagement-123", Path("outputs"))

# Wrap Playwright page
middleware = CaptureMiddleware(session)
page = await browser.new_page()
wrap_playwright_page(page, middleware)

# Link findings to evidence
session.link_finding("finding-456", ["request-id-1", "request-id-2"])

# Generate evidence pack
session.provenance.generate_evidence_pack(
    "finding-456", 
    session.warc_dir, 
    Path("evidence_pack.warc.gz")
)
```

## WARC Format

Each WARC file contains:
- Request records (HTTP request line + headers + body)
- Response records (HTTP status + headers + body)
- Content-addressed IDs (SHA-256 hash)

References: `warc://filename.warc.gz#offset:length`
