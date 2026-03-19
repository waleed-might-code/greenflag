# State-Flow Crawler - Quick Start Guide

## Installation

```bash
cd cyber-hunt-ai-main
pip install -r cyberAI/requirements.txt
playwright install chromium
```

## Basic Usage

### 1. Simple Crawl

```python
import asyncio
from pathlib import Path
from cyberAI.crawl import StateFlowCrawler

async def crawl_target():
    crawler = StateFlowCrawler(
        target_url="https://example.com",
        max_states=100,
        max_depth=5,
        screenshot_dir=Path("outputs/screenshots"),
        headless=True,
    )
    
    results = await crawler.crawl()
    
    print(f"States discovered: {results['states_discovered']}")
    print(f"Forms found: {results['total_forms']}")
    print(f"Inputs found: {results['total_inputs']}")
    
    return results

# Run
asyncio.run(crawl_target())
```

### 2. Integration with Recon System

```python
from cyberAI.crawl.integration import run_state_flow_discovery
from pathlib import Path

# Run discovery
results = await run_state_flow_discovery(
    target_url="https://example.com",
    output_dir=Path("outputs/recon"),
    max_states=10000,
    max_depth=10,
)

# Access routes
routes = results["routes"]
for route in routes:
    print(f"{route.url} - {len(route.actions)} actions")
```

### 3. Demo Script

```bash
python -m cyberAI.crawl.demo https://example.com 100
```

## Configuration Options

```python
StateFlowCrawler(
    target_url="https://example.com",  # Required
    max_states=10000,                   # Max states to explore
    max_depth=10,                       # Max depth from entry
    screenshot_dir=Path("..."),         # Screenshot directory
    headless=True,                      # Headless browser
)
```

## Understanding Results

```python
results = {
    "states_discovered": 1234,          # Total unique states
    "transitions_discovered": 2345,     # State transitions
    "unique_urls": 567,                 # Unique URLs
    "total_forms": 89,                  # Forms found
    "total_inputs": 234,                # Input fields
    "total_links": 1234,                # Links discovered
    "states": [...],                    # State details
    "transitions": [...],               # Transition graph
    "frontier_stats": {...},            # Frontier statistics
}
```

## Priority Scoring

States are automatically prioritized:

| Element | Priority Boost | Why |
|---------|---------------|-----|
| Forms | High | Attack surface |
| API endpoints | Highest | Security testing |
| Admin paths | Highest | Privileged access |
| Input fields | Medium | Injection points |
| Static pages | Low | Limited value |

## Deduplication

SimHash automatically detects similar states:

```
Page 1: Product #123 → Hash: 0xABCD1234
Page 2: Product #456 → Hash: 0xABCD1238
Hamming distance: 2 → Considered duplicate → Skip
```

## Monitoring Progress

```python
# Check frontier stats during crawl
stats = crawler.frontier.get_stats()

print(f"Explored: {stats['states_explored']}")
print(f"In queue: {stats['states_in_queue']}")
print(f"Pruned: {stats['states_pruned']}")
print(f"Progress: {stats['completion_pct']:.1f}%")
```

## Common Patterns

### Pattern 1: Focus on Admin Panel

```python
# Seed frontier with admin URL
crawler = StateFlowCrawler(target_url="https://example.com/admin")
```

### Pattern 2: Multi-Role Crawling

```python
# Crawl as different roles
for role in ["guest", "user", "admin"]:
    crawler = StateFlowCrawler(
        target_url=f"https://example.com?role={role}",
        max_states=5000,
    )
    results = await crawler.crawl()
```

### Pattern 3: Incremental Discovery

```python
# Start with small crawl
results_1 = await crawler.crawl(max_states=100)

# Expand based on findings
if results_1["total_forms"] > 10:
    results_2 = await crawler.crawl(max_states=1000)
```

## Troubleshooting

### Issue: Too many states

**Solution**: Reduce `max_states` or `max_depth`

```python
crawler = StateFlowCrawler(
    target_url="...",
    max_states=1000,  # Reduce
    max_depth=5,      # Reduce
)
```

### Issue: Missing important pages

**Solution**: Increase priority for specific patterns

```python
# Modify frontier.py scoring
if "admin" in url or "api" in url:
    score -= 100  # Highest priority
```

### Issue: Too slow

**Solution**: Enable headless mode, reduce wait times

```python
crawler = StateFlowCrawler(
    target_url="...",
    headless=True,  # Faster
)
```

## Performance Tips

1. **Start small**: Test with `max_states=10` first
2. **Use headless**: 2-3x faster than headed mode
3. **Adjust depth**: Reduce `max_depth` for faster completion
4. **Monitor pruning**: High pruning = adjust priorities
5. **Check deduplication**: Low unique URLs = good dedup

## Next Steps

1. Review `docs/STATE_EXPLOSION_SOLUTION.md` for architecture
2. Check `cyberAI/crawl/README.md` for detailed docs
3. Run demo: `python -m cyberAI.crawl.demo <url> <max_states>`
4. Integrate with existing recon pipeline
5. Customize priority scoring for your targets

## Support

- Documentation: `cyber-hunt-ai-main/cyberAI/crawl/README.md`
- Examples: `cyber-hunt-ai-main/cyberAI/crawl/demo.py`
- Tests: `cyber-hunt-ai-main/test_integration.py`
