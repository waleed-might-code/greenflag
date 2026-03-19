# Reporting System - WARC-Backed Evidence

## Overview

The enhanced reporting system provides enterprise-grade security assessment reports with full evidence provenance. Every finding is traceable to raw HTTP captures stored in WARC (Web ARChive) format following ISO 28500 standard.

## Key Features

### 1. Evidence-Grade Archival
- **WARC Storage**: All HTTP request/response pairs archived in ISO 28500 format
- **Content-Addressed**: SHA-256 IDs for deduplication and integrity
- **Engagement-Scoped**: Organized by engagement ID for multi-tenant support
- **Compressed**: Gzip compression for efficient storage

### 2. Evidence Packs
- **Per-Finding Packages**: ZIP archives containing all evidence for a specific finding
- **Includes**:
  - HTTP headers (JSON format)
  - Response bodies (JSON or binary)
  - Raw WARC records for audit
  - Screenshots (when available)
  - Manifest with WARC references

### 3. Enhanced Reports
- **Executive Summary**: High-level overview with evidence statistics
- **Engineering Handoff**: Technical details with pattern-based remediation
- **Finding Records**: Detailed write-ups with WARC evidence trails
- **Remediation Queue**: Prioritized fix list with verification steps

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Reporting Pipeline                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Verified Findings (from verification phase)                 │
│  - Finding metadata                                          │
│  - evidence_warc_refs: ["warc://eng_id/file.warc.gz#..."]   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Report Generator                                            │
│  - Load findings                                             │
│  - Cluster by pattern                                        │
│  - Generate remediation queue                                │
│  - Create executive summary                                  │
│  - Create engineering handoff                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Evidence Pack Generator                                     │
│  - Parse WARC references                                     │
│  - Extract HTTP captures from WARC files                     │
│  - Package as ZIP with manifest                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Output Files                                                │
│  - reports/markdown/executive_summary.md                     │
│  - reports/markdown/engineering_handoff.md                   │
│  - reports/findings/{finding_id}.md                          │
│  - reports/evidence_packs/evidence_{finding_id}.zip          │
│  - reports/json/report.json                                  │
│  - reports/csv/findings.csv                                  │
└─────────────────────────────────────────────────────────────┘
```

## Usage

### Basic Report Generation

```python
from cyberAI.reporting.reporter import ReportGenerator

# Initialize generator
generator = ReportGenerator(run_id="scan_123")

# Load verified findings
generator.load_verified_findings()

# Generate complete report
report = generator.generate_report()

# Save all outputs
outputs = generator.save_all_outputs()

print(f"Generated {len(outputs)} report files")
```

### CLI Usage

```bash
# Generate reports from verified findings
python main.py report --verified-dir outputs/verification/confirmed

# Generate reports for specific run
python main.py report --run-id scan_123
```

### Evidence Pack Generation

Evidence packs are automatically generated for findings with WARC references:

```python
from cyberAI.reporting.evidence_pack import generate_evidence_pack
from cyberAI.models import VerifiedFinding

finding = VerifiedFinding(...)  # Load from verification
evidence_dir = Path("outputs/reports/evidence_packs")

evidence_pack = generate_evidence_pack(finding, evidence_dir)
# Returns: {
#   "finding_id": "...",
#   "screenshots": [...],
#   "warc_references": [...],
#   "evidence_pack_path": "outputs/reports/evidence_packs/evidence_xyz.zip"
# }
```

### Extracting Evidence

```bash
# List evidence packs
ls outputs/reports/evidence_packs/

# Extract a specific pack
unzip outputs/reports/evidence_packs/evidence_<finding_id>.zip -d evidence/

# View manifest
cat evidence/manifest.json

# View HTTP headers
cat evidence/evidence_000_headers.json

# View response body (if JSON)
cat evidence/evidence_000_body.json
```

## WARC Reference Format

WARC references follow this URI format:

```
warc://<engagement_id>/<file_path>#<offset>:<length>
```

Example:
```
warc://eng_abc123/eng_abc123_20240316_001.warc.gz#1024:2048
```

This reference points to:
- Engagement: `eng_abc123`
- File: `eng_abc123_20240316_001.warc.gz`
- Offset: byte 1024
- Length: 2048 bytes

## Data Model

### Finding with Evidence

```python
class Finding(BaseModel):
    id: str
    title: str
    severity: Severity
    category: TestCategory
    asset: str
    # ... other fields ...
    evidence_warc_refs: list[str] = []  # WARC URIs
    
class VerifiedFinding(Finding):
    verification_method: str
    confirmed_impact: str
    exploit_chain: list[str]
    # ... verification fields ...
```

### WARC Reference

```python
@dataclass
class WARCReference:
    warc_id: str  # SHA-256 content hash
    file_path: str  # Relative path
    offset: int  # Byte offset
    length: int  # Record length
    engagement_id: str
    timestamp: datetime
    
    def to_uri(self) -> str:
        return f"warc://{self.engagement_id}/{self.file_path}#{self.offset}:{self.length}"
```

## Storage Layout

```
outputs/
├── warc/
│   └── <engagement_id>/
│       ├── <engagement_id>_<timestamp>_001.warc.gz
│       ├── <engagement_id>_<timestamp>_002.warc.gz
│       └── ...
├── reports/
│   ├── markdown/
│   │   ├── executive_summary.md
│   │   └── engineering_handoff.md
│   ├── findings/
│   │   ├── <finding_id_1>.md
│   │   ├── <finding_id_2>.md
│   │   └── ...
│   ├── evidence_packs/
│   │   ├── evidence_<finding_id_1>.zip
│   │   ├── evidence_<finding_id_2>.zip
│   │   └── ...
│   ├── json/
│   │   └── report.json
│   └── csv/
│       └── findings.csv
```

## Integration with Testing Phase

To link findings to WARC evidence during testing:

```python
from cyberAI.storage import create_warc_writer

# Initialize WARC writer for engagement
warc_writer = create_warc_writer(engagement_id="eng_123")

# During testing, capture HTTP traffic
warc_ref = warc_writer.write_request_response(
    method="GET",
    url="https://target.com/api/users/123",
    request_headers={"Authorization": "Bearer ..."},
    request_body=b"",
    status_code=200,
    response_headers={"Content-Type": "application/json"},
    response_body=b'{"user": {...}}',
)

# Link to finding
finding = Finding(
    title="Unauthorized Access to User Data",
    severity=Severity.HIGH,
    # ... other fields ...
    evidence_warc_refs=[warc_ref.to_uri()],
)

# Close writer when done
warc_writer.close()
```

## Best Practices

1. **Always Link Evidence**: Every finding should have at least one WARC reference
2. **Content Addressing**: WARC IDs are content-addressed for deduplication
3. **Engagement Scoping**: Use unique engagement IDs for multi-tenant isolation
4. **File Rotation**: WARC files auto-rotate at 100MB for manageability
5. **Compression**: Always use gzip compression for storage efficiency
6. **Audit Trail**: Never delete WARC files during engagement retention period

## Compliance and Audit

The WARC-backed evidence system supports:

- **ISO 28500 Compliance**: Standard web archive format
- **Chain of Custody**: Content-addressed IDs ensure integrity
- **Reproducibility**: Complete HTTP captures enable verification
- **Retention Policies**: Engagement-scoped TTL for data governance
- **Audit Trail**: Every finding traceable to raw captures

## Performance Considerations

- **WARC Writing**: Thread-safe, supports concurrent writes
- **File Rotation**: Automatic at 100MB to prevent large files
- **Compression**: Gzip reduces storage by ~70%
- **Evidence Extraction**: On-demand, only when generating packs
- **Deduplication**: Content-addressed IDs prevent duplicate storage

## Future Enhancements

- [ ] Neo4j integration for knowledge graph
- [ ] Kafka streaming for real-time evidence capture
- [ ] MinHash/LSH for near-duplicate detection
- [ ] OCR pipeline for sensitive data in images
- [ ] Differential auth testing with evidence comparison
- [ ] RESTler-style API fuzzing with WARC capture
