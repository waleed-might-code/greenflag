# CyberAI Evidence System - Deployment Plan

## What We Built

A complete WARC-based provenance system that captures every HTTP request/response and links them to security findings. This solves the critical challenge of evidence traceability at scale.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  CyberAI Platform                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Recon      │  │   Testing    │  │  Reporting   │  │
│  │   Module     │  │   Module     │  │   Module     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │          │
│         └─────────────────┼──────────────────┘          │
│                           ▼                             │
│              ┌────────────────────────┐                 │
│              │  Evidence Middleware   │                 │
│              │  (CaptureSession)      │                 │
│              └────────┬───────────────┘                 │
│                       │                                 │
│         ┌─────────────┼─────────────┐                   │
│         ▼             ▼             ▼                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │   WARC   │  │Provenance│  │ Evidence │              │
│  │  Writer  │  │ Tracker  │  │   API    │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │  Storage Layer │
              │  - WARC files  │
              │  - Index JSONL │
              └────────────────┘
```

## Components Delivered

### 1. Core Evidence Module (`cyberAI/evidence/`)
- ✅ `warc_writer.py` - ISO 28500 WARC format writer
- ✅ `provenance.py` - Finding-to-evidence linking
- ✅ `capture.py` - Session management
- ✅ `integration.py` - Playwright/httpx wrappers
- ✅ `api.py` - REST API for evidence retrieval
- ✅ `example_usage.py` - Usage examples
- ✅ `integration_example.py` - Recon integration example

### 2. Data Model Updates
- ✅ Extended `Finding` model with `evidence_warc_refs` field
- ✅ Added `evidence_hashes` for content verification

### 3. Documentation
- ✅ `evidence/README.md` - Module documentation
- ✅ `EVIDENCE_INTEGRATION_GUIDE.md` - Integration guide
- ✅ `IMPLEMENTATION_SUMMARY.md` - Technical summary

## Deployment Steps

### Phase 1: Standalone Testing (Now)
```bash
# Test the evidence module
cd cyber-hunt-ai-main/cyberAI
python3 evidence/example_usage.py

# Start evidence API
python3 evidence/api.py
# Access at http://localhost:5004
```

### Phase 2: Integration with Recon (Week 1)
1. Modify `recon/core_discovery.py` to create CaptureSession
2. Wrap all Playwright pages with evidence middleware
3. Test on sample target
4. Verify WARC files are created

### Phase 3: Integration with Testing (Week 2)
1. Modify all test modules to use CaptureSession
2. Link findings to evidence in real-time
3. Update Finding creation to include WARC refs
4. Test authz/IDOR detection with evidence

### Phase 4: Reporting Integration (Week 3)
1. Update report templates to include evidence refs
2. Add evidence pack generation to report workflow
3. Create evidence viewer UI (optional)
4. Test end-to-end: scan → findings → evidence pack

### Phase 5: Production Deployment (Week 4)
1. Deploy evidence API as systemd service
2. Configure retention policies
3. Set up monitoring and alerts
4. Document operational procedures

## API Deployment

### Local Development
```bash
cd cyber-hunt-ai-main/cyberAI/evidence
python3 api.py
```

### Production Deployment
```bash
# On server
cd /root/services
git clone <repo>
cd cyber-hunt-ai-main/cyberAI

# Install dependencies
python3 -m venv venv
source venv/bin/python
pip install -r requirements.txt flask

# Create systemd service
sudo tee /etc/systemd/system/cyberai-evidence.service << 'SERVICE'
[Unit]
Description=CyberAI Evidence API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/services/cyber-hunt-ai-main/cyberAI
ExecStart=/root/services/cyber-hunt-ai-main/cyberAI/venv/bin/python evidence/api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

# Start service
sudo systemctl daemon-reload
sudo systemctl enable cyberai-evidence
sudo systemctl start cyberai-evidence

# Expose via Cloudflare Tunnel
$PEXO_PYTHON $PEXO_TUNNEL expose cyberai-evidence 5004
```

## Storage Planning

### Capacity Estimates
- Small engagement (10k requests): ~10 MB
- Medium engagement (100k requests): ~100 MB
- Large engagement (1M requests): ~1 GB
- Enterprise (10M requests): ~10 GB

### Retention Policy
```python
# In engagement config
data_retention:
  raw_capture_ttl_days: 90      # WARC files
  structured_ttl_days: 365      # Database records
  findings_ttl_days: 1825       # 5 years
```

### Cleanup Job
```bash
# Cron job to clean old evidence
0 2 * * * /usr/bin/python3 /root/services/cyber-hunt-ai-main/cyberAI/evidence/cleanup.py
```

## Monitoring

### Key Metrics
- WARC files created per day
- Total storage used
- Findings with evidence linked
- Evidence pack generation requests
- API response times

### Health Checks
```bash
# Check API
curl http://localhost:5004/health

# Check storage
du -sh outputs/evidence/warc/

# Check provenance index
wc -l outputs/evidence/provenance/provenance_index.jsonl
```

## Security Considerations

1. **Access Control**: Evidence API should require authentication
2. **Encryption**: Consider encrypting WARC files at rest
3. **Audit Logging**: Log all evidence access
4. **Data Retention**: Comply with engagement agreements
5. **PII Handling**: Redact sensitive data if required

## Performance Tuning

### For High-Volume Scans
```python
# Increase records per file
writer = WARCWriter(output_dir, engagement_id)
writer.max_records_per_file = 50000  # Default: 10000

# Use multiple writers (shard by domain)
writers = {
    "api": WARCWriter(output_dir / "api", engagement_id),
    "web": WARCWriter(output_dir / "web", engagement_id),
}
```

### For Large Responses
```python
# Truncate large bodies
MAX_BODY_SIZE = 1024 * 1024  # 1MB
if len(body) > MAX_BODY_SIZE:
    body = body[:MAX_BODY_SIZE] + b"... [truncated]"
```

## Success Criteria

✅ Every finding has at least one WARC reference
✅ Evidence packs can be generated for any finding
✅ WARC files are readable by standard tools
✅ Storage growth is predictable and manageable
✅ API responds in <100ms for evidence lookups
✅ Integration doesn't slow down scans by >10%

## Next Steps

1. **Immediate**: Test the evidence module standalone
2. **This Week**: Integrate with one recon module
3. **Next Week**: Integrate with one test module
4. **Month 1**: Full integration and production deployment
5. **Month 2**: Add advanced features (deduplication, compression)

## Support

For issues or questions:
- Check logs: `outputs/logs/`
- Review documentation: `EVIDENCE_INTEGRATION_GUIDE.md`
- Test module: `python3 evidence/example_usage.py`
