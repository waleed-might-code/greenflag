# WARC Storage Implementation for CyberAI

## Overview

The WARC (Web ARChive) storage layer provides evidence provenance for all security findings. Every HTTP request/response pair can be archived to WARC format (ISO 28500), enabling:

- **Traceability**: Every finding links to raw HTTP captures via WARC URIs
- **Reproducibility**: Auditors can replay exact requests from WARC archives
- **Compliance**: Standard format for evidence retention and chain of custody
- **Deduplication**: Content-addressed IDs prevent duplicate storage

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CyberAI Testing Pipeline                  │
│  Recon → Planning → Testing → Verification → Reporting      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              WARCIntegration (Capture Layer)                 │
│  - Intercepts RequestRecord objects                          │
│  - Converts to WARC format                                   │
│  - Returns WARCReference                                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    WARCWriter (Storage)                      │
│  - Thread-safe writes                                        │
│  - Content-addressed IDs (SHA-256)                           │
│  - Gzip compression                                          │
│  - Automatic file rotation                                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              WARC Files (Evidence Store)                     │
│  outputs/warc/{engagement_id}/{timestamp}_{seq}.warc.gz     │
│  - ISO 28500 format                                          │
│  - Request + Response records                                │
│  - Content-addressable refs                                  │
└─────────────────────────────────────────────────────────────┘
```

## Usage

### Basic Usage

```python
from cyberAI.storage import WARCWriter

# Create writer for an engagement
writer = WARCWriter(
    base_dir="outputs/warc",
    engagement_id="eng_001",
    max_file_size_mb=100,
    compress=True
)

# Write HTTP request/response
ref = writer.write_request_response(
    method="GET",
    url="https://api.example.com/users/123",
    request_headers={"Authorization": "Bearer token"},
    request_body=b"",
    status_code=200,
    response_headers={"Content-Type": "application/json"},
    response_body=b'{"id": 123, "email": "user@example.com"}'
)

# Get WARC URI for evidence linking
print(ref.to_uri())
# Output: warc://eng_001/eng_001_20240101_000.warc.gz#0:1234

writer.close()
```

### Integration with RequestRecord

```python
from cyberAI.storage import WARCIntegration
from cyberAI.models import RequestRecord, HttpMethod

# Create request record
request = RequestRecord(
    method=HttpMethod.GET,
    url="https://api.example.com/users/123",
    headers={"Authorization": "Bearer token"},
    response_status=200,
    response_body='{"id": 123}'
)

# Automatically capture to WARC
ref = WARCIntegration.capture_request("eng_001", request)

# RequestRecord now has warc_ref populated
print(request.warc_ref)
# Output: warc://eng_001/eng_001_20240101_000.warc.gz#0:1234
```

### Linking Findings to Evidence

```python
from cyberAI.models import Finding, Severity, TestCategory
from cyberAI.storage import WARCIntegration

# Capture evidence during testing
admin_ref = WARCIntegration.capture_request("eng_001", admin_request)
user_ref = WARCIntegration.capture_request("eng_001", user_request)

# Create finding with WARC evidence
finding = Finding(
    title="IDOR: Unauthorized Access to User Profile",
    severity=Severity.HIGH,
    category=TestCategory.AUTHZ,
    asset="https://api.example.com/users/{id}",
    evidence_warc_refs=[
        admin_ref.to_uri(),
        user_ref.to_uri()
    ],
    reproduction_steps=[
        "1. Authenticate as regular user",
        "2. Send GET /users/123",
        f"3. Evidence: {user_ref.to_uri()}"
    ]
)
```

## Configuration

Add to `.env`:

```bash
# WARC Storage
WARC_ENABLED=true
WARC_MAX_FILE_SIZE_MB=100
WARC_COMPRESS=true
```

## File Organization

```
outputs/warc/
├── eng_001/
│   ├── eng_001_20240101_120000_000.warc.gz
│   ├── eng_001_20240101_120500_001.warc.gz
│   └── eng_001_20240101_121000_002.warc.gz
├── eng_002/
│   └── eng_002_20240101_130000_000.warc.gz
└── ...
```

## WARC Record Format

Each HTTP transaction creates two WARC records:

```
WARC/1.0
WARC-Type: request
WARC-Record-ID: <urn:uuid:...>
WARC-Date: 2024-01-01T12:00:00Z
WARC-Target-URI: https://api.example.com/users/123
WARC-Content-ID: abc123...
Content-Type: application/http; msgtype=request
Content-Length: 234

GET /users/123 HTTP/1.1
Host: api.example.com
Authorization: Bearer token

[request body]


WARC/1.0
WARC-Type: response
WARC-Record-ID: <urn:uuid:...>
WARC-Date: 2024-01-01T12:00:00Z
WARC-Target-URI: https://api.example.com/users/123
WARC-Content-ID: abc123...
Content-Type: application/http; msgtype=response
Content-Length: 456

HTTP/1.1 200 OK
Content-Type: application/json

{"id": 123, "email": "user@example.com"}

```

## Content-Addressed IDs

Each request gets a SHA-256 ID based on:
- HTTP method
- URL
- Sorted headers (excluding auth/cookies)

This enables:
- Deduplication of identical requests
- Fast lookup by request signature
- Stable references across runs

## Thread Safety

WARCWriter uses internal locking for thread-safe writes:
- Multiple workers can share one writer
- Writes are serialized automatically
- File rotation is atomic

## Best Practices

1. **One writer per engagement**: Use `WARCIntegration.get_writer(engagement_id)`
2. **Close writers**: Call `WARCIntegration.close_all()` at end of run
3. **Link all findings**: Always populate `evidence_warc_refs` in Finding objects
4. **Retention policy**: Implement TTL cleanup based on engagement config
5. **Sensitive data**: WARC contains full request/response - apply retention rules

## Future Enhancements

- **Kafka integration**: Stream raw_captures to Kafka → WARC writer consumer
- **S3 storage**: Upload WARC files to object storage for long-term retention
- **Deduplication**: Skip writing duplicate responses (same content hash)
- **Replay tool**: CLI tool to extract and replay requests from WARC
- **Evidence packs**: Generate per-finding WARC subsets for handoff

## References

- ISO 28500: WARC specification
- [IIPC WARC format](https://iipc.github.io/warc-specifications/)
- Burp Suite evidence export (similar concept)
