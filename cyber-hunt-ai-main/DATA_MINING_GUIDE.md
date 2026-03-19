# Massive Data Mining with CyberAI Evidence System

This guide shows how to use the evidence system to mine massive amounts of data from web applications and APIs for security analysis.

## Overview

The evidence system enables:
- **Massive data collection** from web apps, APIs, and all scrapable sources
- **Automatic capture** of every HTTP request/response
- **Scalable storage** in WARC format (handles millions of requests)
- **Batch analysis** of captured data to find vulnerabilities

## Architecture

```
Target Application
       ↓
Data Miner (Playwright + Evidence Capture)
       ↓
WARC Storage (Compressed, Content-Addressed)
       ↓
Data Analyzer (Pattern Matching, ML)
       ↓
Security Findings
```

## Step 1: Mine Data

### Basic Usage

```bash
cd cyber-hunt-ai-main/cyberAI/evidence
python data_miner.py https://target.com 1000
```

This will:
- Crawl up to 1000 pages
- Capture all HTTP traffic
- Store in WARC format
- Discover APIs, forms, and endpoints

### Advanced Usage

```python
from cyberAI.evidence.data_miner import MassiveDataMiner
from pathlib import Path

miner = MassiveDataMiner(
    target_url="https://api.target.com",
    engagement_id="engagement-001",
    output_dir=Path("outputs")
)

await miner.mine_target(max_pages=10000)
```

### Output

```
outputs/evidence/warc/
├── engagement-001_20240115120000_abc123.warc.gz
├── engagement-001_20240115130000_def456.warc.gz
└── engagement-001_20240115140000_ghi789.warc.gz
```

## Step 2: Analyze Data

### Run Analysis

```bash
python data_analyzer.py outputs/evidence/warc
```

This will:
- Scan all WARC files
- Detect sensitive data exposure
- Find vulnerability indicators
- Identify IDOR patterns
- Discover admin endpoints

### Analysis Output

```
📊 DATA ANALYSIS RESULTS
========================================
📈 Statistics:
   Total records analyzed: 50,000
   Findings discovered: 127
   Potential IDOR endpoints: 45
   Admin endpoints found: 12

🔐 Sensitive Data Exposure:
   API_KEY: 8 occurrences
   JWT: 234 occurrences
   EMAIL: 1,456 occurrences

⚠️  Vulnerability Indicators:
   SQL_ERROR: 3 occurrences
   STACK_TRACE: 7 occurrences
   DEBUG_INFO: 15 occurrences
```

## Step 3: Generate Findings

The analyzer automatically creates findings with WARC references:

```json
{
  "type": "sensitive_data_exposure",
  "category": "api_key",
  "warc_file": "engagement-001_20240115120000_abc123.warc.gz",
  "matches": 3,
  "severity": "high",
  "evidence_refs": [
    "warc://engagement-001_20240115120000_abc123.warc.gz#1024:2048"
  ]
}
```

## Scalability

### Performance Characteristics

| Scale | Pages | Requests | Storage | Time |
|-------|-------|----------|---------|------|
| Small | 100 | 1,000 | ~10 MB | 5 min |
| Medium | 1,000 | 10,000 | ~100 MB | 30 min |
| Large | 10,000 | 100,000 | ~1 GB | 3 hours |
| Enterprise | 100,000 | 1,000,000 | ~10 GB | 24 hours |

### Parallel Mining

For massive scale, run multiple miners in parallel:

```python
import asyncio

async def mine_parallel():
    miners = [
        MassiveDataMiner(f"https://target.com/section{i}", f"eng-{i}", Path("outputs"))
        for i in range(10)
    ]
    
    await asyncio.gather(*[m.mine_target(1000) for m in miners])
```

## Data Mining Patterns

### 1. API Discovery

The miner automatically discovers:
- REST API endpoints
- GraphQL endpoints
- WebSocket connections
- Hidden API routes

### 2. Form Mining

Captures all forms with:
- Field names and types
- Validation rules
- Submit endpoints
- CSRF tokens

### 3. Authentication Flows

Tracks:
- Login sequences
- Session tokens
- OAuth flows
- API keys

### 4. Data Relationships

Identifies:
- User IDs in URLs (IDOR candidates)
- Object relationships
- Access control patterns
- Data hierarchies

## Analysis Techniques

### 1. Pattern Matching

```python
# Custom patterns
analyzer.sensitive_patterns['custom'] = re.compile(r'secret["\s:=]+([^\s"]+)')
```

### 2. Differential Analysis

Compare responses across roles:
```python
# Analyze WARC data for authz issues
admin_responses = get_responses_for_role("admin")
user_responses = get_responses_for_role("user")
compare_responses(admin_responses, user_responses)
```

### 3. Time-Series Analysis

Track changes over time:
```python
# Analyze WARC data by timestamp
analyze_temporal_patterns(warc_dir)
```

## Integration with Testing

### Link Findings to Evidence

```python
from cyberAI.evidence import ProvenanceTracker

tracker = ProvenanceTracker(Path("outputs/evidence/provenance"))

# Link finding to WARC evidence
tracker.link_finding_to_evidence(
    "finding-idor-001",
    evidence_refs=[
        EvidenceRef(
            warc_ref="warc://file.warc.gz#1024:2048",
            content_hash="abc123...",
            request_id="req-001"
        )
    ]
)
```

### Generate Evidence Packs

```python
# Extract evidence for a specific finding
tracker.generate_evidence_pack(
    "finding-idor-001",
    warc_dir=Path("outputs/evidence/warc"),
    output_path=Path("evidence_pack.warc.gz")
)
```

## Best Practices

### 1. Scope Management

Always define scope before mining:
```python
miner.allowed_domains = ["target.com", "api.target.com"]
miner.excluded_patterns = ["*/logout", "*/delete"]
```

### 2. Rate Limiting

Respect target application:
```python
miner.request_delay_ms = 500  # 500ms between requests
miner.max_concurrent = 5      # Max 5 concurrent requests
```

### 3. Storage Management

Monitor storage usage:
```bash
# Check WARC storage
du -sh outputs/evidence/warc/

# Clean old data
find outputs/evidence/warc -mtime +90 -delete
```

### 4. Incremental Mining

Resume interrupted mining:
```python
miner.visited_urls = load_visited_urls("checkpoint.json")
await miner.mine_target(max_pages=10000)
```

## Advanced Features

### 1. Custom Extractors

Add custom data extractors:
```python
class CustomMiner(MassiveDataMiner):
    async def _extract_custom_data(self, page):
        # Extract custom data points
        data = await page.evaluate("() => window.customData")
        self.custom_data.append(data)
```

### 2. ML-Based Analysis

Use machine learning for analysis:
```python
from sklearn.ensemble import IsolationForest

# Train anomaly detector on WARC data
detector = train_anomaly_detector(warc_data)
anomalies = detector.predict(new_data)
```

### 3. Real-Time Analysis

Analyze data as it's captured:
```python
class RealtimeAnalyzer:
    async def on_response(self, response):
        # Analyze response immediately
        if self.is_vulnerable(response):
            self.create_finding(response)
```

## Troubleshooting

### Issue: Out of disk space

```bash
# Compress old WARC files
gzip -9 outputs/evidence/warc/*.warc

# Move to archive storage
mv outputs/evidence/warc/*.warc.gz /archive/
```

### Issue: Mining too slow

```python
# Increase concurrency
miner.max_concurrent = 10

# Reduce wait time
miner.wait_for_network = False
```

### Issue: Missing data

```python
# Enable verbose logging
miner.verbose = True

# Check WARC files
python -c "import gzip; print(gzip.open('file.warc.gz').read())"
```

## Next Steps

1. **Run your first mining session**: `python data_miner.py https://target.com 100`
2. **Analyze the data**: `python data_analyzer.py outputs/evidence/warc`
3. **Review findings**: Check `outputs/evidence/analysis_report.json`
4. **Generate evidence packs**: For each finding, create evidence pack
5. **Integrate with testing**: Use findings to guide security tests

## Resources

- `data_miner.py` - Massive data collection crawler
- `data_analyzer.py` - Batch analysis of WARC data
- `EVIDENCE_INTEGRATION_GUIDE.md` - Integration guide
- `DEPLOYMENT_PLAN.md` - Production deployment

---

**Ready to mine massive amounts of data and find vulnerabilities at scale!**
