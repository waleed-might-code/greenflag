# 🚀 CyberAI Evidence System - Ready to Use

## Quick Start (5 Minutes)

### 1. Test the System

```bash
cd cyber-hunt-ai-main/cyberAI
python evidence/test_standalone.py
```

Expected output: ✅ All tests passed!

### 2. Run a Demo

```bash
python << 'EOF'
from evidence import CaptureSession
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    session = CaptureSession("demo", Path(tmpdir))
    session.capture_request("req-1", "GET", "https://example.com", {}, None)
    session.capture_response("req-1", "https://example.com", 200, {}, b"OK")
    session.link_finding("finding-1", ["req-1"])
    print("✅ Evidence system working!")
    session.close()
