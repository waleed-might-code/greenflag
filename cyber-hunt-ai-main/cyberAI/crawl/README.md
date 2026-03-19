# State-Flow Crawler

Enterprise-grade state-flow crawler with intelligent exploration and deduplication.

## Features

- **Priority-based frontier**: Explores high-value states first (forms, APIs, admin paths)
- **SimHash deduplication**: Avoids re-crawling similar states
- **State cap enforcement**: Configurable limit (default 10k states)
- **Attack surface scoring**: Prioritizes endpoints with forms, inputs, and API calls
- **Automatic pruning**: Removes low-value states when frontier grows too large

## Architecture

```
StateFlowCrawler
├── CrawlFrontier (priority queue)
│   ├── Priority scoring
│   ├── State cap enforcement
│   └── Automatic pruning
├── DOMHasher (deduplication)
│   ├── SimHash computation
│   ├── Similarity detection
│   └── State registration
└── State exploration
    ├── Action discovery
    ├── Form detection
    └── Link extraction
```

## Usage

### Basic Usage

```python
from cyberAI.crawl import StateFlowCrawler

crawler = StateFlowCrawler(
    target_url="https://example.com",
    max_states=10000,
    max_depth=10,
)

results = await crawler.crawl()
```

### Integration with Recon

```python
from cyberAI.crawl.integration import run_state_flow_discovery

results = await run_state_flow_discovery(
    target_url="https://example.com",
    output_dir=Path("outputs/recon"),
    max_states=10000,
)
```

### Demo Script

```bash
python -m cyberAI.crawl.demo https://example.com 100
```

## Priority Scoring

States are scored based on:

| Factor | Weight | Description |
|--------|--------|-------------|
| Depth | +10 per level | Deeper states have lower priority |
| Forms | -15 per form | Forms are high-value targets |
| Inputs | -10 per input | Input fields indicate attack surface |
| API calls | -20 per call | API endpoints are highest priority |
| Admin paths | -50 | Admin/privileged paths prioritized |
| Authentication | -25 | Authenticated states prioritized |
| Content type | -30 * score | API=1.0, forms=0.8, static=0.3 |
| Novelty | -20 * score | New insertion points prioritized |

Lower score = higher priority in queue.

## State Deduplication

Uses SimHash with configurable Hamming distance threshold (default: 3).

**How it works:**
1. Extract meaningful DOM (strip scripts, styles, dynamic IDs)
2. Compute 64-bit SimHash
3. Compare with existing states
4. If Hamming distance ≤ threshold, consider duplicate

**Benefits:**
- Avoids re-crawling pagination with same content
- Handles dynamic timestamps and IDs
- Reduces state explosion in SPAs

## Configuration

```python
crawler = StateFlowCrawler(
    target_url="https://example.com",
    max_states=10000,        # Maximum states to explore
    max_depth=10,            # Maximum depth from entry
    screenshot_dir=Path(...), # Screenshot directory
    headless=True,           # Headless browser mode
)
```

## Output

```json
{
  "states_discovered": 1234,
  "transitions_discovered": 2345,
  "unique_urls": 567,
  "total_forms": 89,
  "total_inputs": 234,
  "total_links": 1234,
  "states": [
    {
      "state_id": "abc123",
      "url": "https://example.com/page",
      "depth": 2,
      "forms": 3,
      "inputs": 12,
      "links": 45,
      "screenshot": "path/to/screenshot.png"
    }
  ],
  "transitions": [
    {
      "from_state": "abc123",
      "to_state": "def456",
      "action_type": "click",
      "selector": "button.submit"
    }
  ]
}
```

## Performance

- **Throughput**: ~10-20 states/minute (depends on target)
- **Memory**: ~100MB for 10k states
- **Storage**: ~1MB per state (screenshot + metadata)

## Limitations

- JavaScript-heavy SPAs may have infinite states
- CAPTCHA and 2FA require manual intervention
- Rate limiting may slow crawl
- Some dynamic content may not be captured

## Future Enhancements

- Neural prioritization (Phase 3)
- Infinite scroll detection
- WebSocket state tracking
- GraphQL query exploration
