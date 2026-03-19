# Phase 2 Progress: Data Mining Components

## Agent #5 Contribution

Building the comprehensive data mining pipeline to extract "insane amount of data" from web apps, APIs, and all discoverable surfaces.

### Components Built

#### 1. Novelty Index (`recon/novelty_index.py`)
- Tracks unique insertion point shapes
- Prioritizes novel endpoints over duplicates
- Statistics: unique shapes, novel endpoints, duplicate detection
- Used for intelligent crawl prioritization

#### 2. Insertion Point Extractor (`recon/insertion_point_extractor.py`)
- Extracts ALL user-controllable inputs from HTTP requests
- Supports: URL paths, query params, headers, JSON body, form data, cookies
- **Nested encoding detection**: base64, JSON-in-JSON (up to 3 levels deep)
- CSRF token detection
- Type inference: ID, UUID, email, JWT, token, string
- Canonical request representation with AST
- Shape hashing for deduplication

#### 3. API Discovery (`crawl/api_discovery.py`)
- Discovers APIs from OpenAPI/Swagger specs
- GraphQL introspection queries
- Traffic pattern analysis
- Extracts parameters, auth requirements, descriptions
- Supports OpenAPI 3.x and Swagger 2.0

#### 4. State Flow Detector (`crawl/state_flow.py`)
- Crawljax-style state detection for SPAs
- DOM hashing with dynamic content stripping
- State transition tracking
- State graph export (nodes + edges)
- Handles apps where URL doesn't change but DOM does

#### 5. Crawl Orchestrator (`crawl/orchestrator.py`)
- Ties everything together
- 4-phase crawl: API discovery → Seed → Crawl → Export
- Integrates frontier, state detection, API discovery, insertion extraction
- Novelty-based prioritization
- Comprehensive statistics and export

### Data Points Extracted

For each HTTP request, we now extract:
- URL template with placeholders
- All query parameters (with types)
- All headers (especially auth-related)
- JSON body structure (nested, with types)
- Form data fields
- Cookies
- Path segments (IDs, UUIDs)
- Nested encoded data (base64 → JSON → more nesting)
- CSRF tokens (flagged separately)
- Insertion point count and novelty

### Why This Mines "Insane Amount of Data"

1. **Comprehensive Coverage**
   - APIs from specs (OpenAPI, GraphQL)
   - HTML pages and forms
   - SPA states (DOM-based)
   - Traffic patterns
   - Common paths

2. **Deep Extraction**
   - Nested JSON structures
   - Nested encoding (base64 → JSON → base64)
   - All parameter types
   - All insertion points

3. **Intelligent Prioritization**
   - Novel endpoints first
   - APIs before static pages
   - Admin paths before user paths
   - High-value surfaces prioritized

4. **No Duplication**
   - Shape hashing deduplicates similar requests
   - Novelty index tracks what we've seen
   - State detection avoids re-crawling same DOM

### Files Created (Phase 2)

```
cyberAI/
├── recon/
│   ├── novelty_index.py              # Novelty tracking (4.3KB)
│   └── insertion_point_extractor.py  # Deep extraction (16KB)
├── crawl/
│   ├── api_discovery.py              # API discovery (11.9KB)
│   ├── state_flow.py                 # State detection (6.2KB)
│   └── orchestrator.py               # Orchestration (8.5KB)
└── demo_data_mining.py               # Demo script (1.5KB)
```

### Integration with Phase 1

The orchestrator can be wrapped with `ScopeEnforcingClient` from Phase 1:

```python
from governance import EngagementConfig, ScopeEnforcingClient
from crawl.orchestrator import CrawlOrchestrator

config = EngagementConfig.from_file("engagement.yaml")
client = ScopeEnforcingClient(engagement_config=config)

orchestrator = CrawlOrchestrator(base_url=config.target_domains[0])
orchestrator.client = client  # Use scope-enforcing client
```

### Next Steps

- WARC evidence storage (Phase 2 continuation)
- Multi-identity session management (Phase 2)
- Differential authorization testing (Phase 2)
- Neural prioritization (Phase 3)
- Kafka event pipeline (Phase 2)

### Statistics

- **Lines of Code**: ~2,170 (Phase 2 components)
- **Total with Phase 1**: ~3,515
- **Components**: 10 major modules
- **Test Coverage**: Core functionality validated

---

**Status**: Phase 2 in progress - Data mining pipeline operational
**Next**: Complete Phase 2 with session management and WARC storage
