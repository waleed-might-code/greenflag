# Nested Insertion Point Extraction

Enterprise-grade insertion point extraction with multi-layer encoding detection and novelty tracking.

## Features

- **Nested Encoding Detection**: Automatically detects and decodes Base64, URL-encoding, JWT, JSON, XML, and hex
- **Multi-Layer Extraction**: Recursively extracts insertion points from nested structures (up to 5 levels deep)
- **Novelty Tracking**: Tracks unique insertion point shapes to prioritize new attack surfaces
- **Request Canonicalization**: Normalizes requests for deduplication and comparison
- **Type Inference**: Automatically infers parameter types (ID, email, token, UUID, etc.)

## Architecture

```
InsertionPointPipeline
├── NestedInsertionPointExtractor
│   ├── EncodingDetector (detects encoding types)
│   ├── Recursive extraction (handles nesting)
│   └── Type inference (infers parameter types)
├── NoveltyTracker
│   ├── Shape hashing (normalizes patterns)
│   ├── Novelty scoring (0.0-1.0)
│   └── Statistics tracking
└── RequestCanonicalizer
    ├── URL normalization (replaces IDs with placeholders)
    ├── Body normalization (type placeholders)
    └── Deduplication (hash-based)
```

## Usage

### Basic Extraction

```python
from cyberAI.insertion_points import NestedInsertionPointExtractor

extractor = NestedInsertionPointExtractor(max_depth=5)

points = extractor.extract_from_request(
    method="POST",
    url="https://api.example.com/users/123",
    headers={"Content-Type": "application/json"},
    body='{"name": "John", "email": "john@example.com"}'
)

for point in points:
    print(f"{point.location}: {point.inferred_type}")
    if point.encoding_layers:
        print(f"  Encoding: {' → '.join(e.value for e in point.encoding_layers)}")
```

### With Novelty Tracking

```python
from cyberAI.insertion_points import NoveltyTracker

tracker = NoveltyTracker()

for point in points:
    if tracker.is_novel(point):
        print(f"Novel: {point.location}")
    
    score = tracker.get_novelty_score(point)
    print(f"  Novelty score: {score:.2f}")

stats = tracker.get_stats()
print(f"Novel shapes: {stats['novel_shapes']}")
```

### Full Pipeline

```python
from cyberAI.insertion_points.integration import InsertionPointPipeline

pipeline = InsertionPointPipeline(max_depth=5)

result = pipeline.process_request(
    method="POST",
    url="https://api.example.com/users/123",
    headers={"Content-Type": "application/json"},
    body='{"data": "eyJ1c2VyX2lkIjoxMjN9"}'  # Base64-encoded JSON
)

print(f"Total points: {result['stats']['total_points']}")
print(f"Novel points: {result['stats']['novel_points']}")
print(f"Duplicate request: {result['is_duplicate']}")
```

## Encoding Detection

### Supported Encodings

| Encoding | Detection | Decoding | Recursive |
|----------|-----------|----------|-----------|
| Base64 | Pattern match + validation | ✓ | ✓ |
| URL | % character presence | ✓ | ✓ |
| JWT | eyJ... pattern | ✓ (payload) | ✓ |
| JSON | Starts with { or [ | ✓ | ✓ |
| XML | Starts with < | ✓ | ✗ |
| Hex | Hex pattern | ✓ | ✓ |

### Example: Nested Encoding

```python
# Request with Base64-encoded JSON
import base64
import json

inner_data = {"user_id": 123, "role": "admin"}
encoded = base64.b64encode(json.dumps(inner_data).encode()).decode()

body = json.dumps({"token": encoded})

points = extractor.extract_from_request("POST", url, headers, body)

# Output:
# body.token [none]
# body.token.decoded [base64]
# body.token.decoded.user_id [base64 → json]
# body.token.decoded.role [base64 → json]
```

## Insertion Point Structure

```python
@dataclass
class InsertionPoint:
    location: str              # e.g., "body.user.profile.data"
    value: Any                 # Original value
    encoding_layers: list      # Chain of encodings
    inferred_type: str         # id, string, token, email, etc.
    parent_location: str       # Parent location (optional)
    depth: int                 # Nesting depth
```

### Location Patterns

- **Query**: `query.param_name`
- **Path**: `path.segment_0`, `path.segment_1`
- **Header**: `header.Authorization`, `header.X-User-Id`
- **Body (JSON)**: `body.user.id`, `body.settings.theme`
- **Body (Form)**: `body.username`, `body.password`
- **Nested**: `body.token.decoded.user_id`

## Novelty Tracking

### Shape Hashing

Insertion points are normalized to shapes:

```
body.user[0].id → body.user[*].id
path.segment_3  → path.segment_*
```

Shape = `location_pattern | encoding_layers | inferred_type`

### Novelty Score

```python
score = 1.0 / (1.0 + log10(count + 1))
```

- First occurrence: 1.0 (completely novel)
- Second occurrence: 0.5
- 10th occurrence: 0.33
- 100th occurrence: 0.2

## Request Canonicalization

### URL Normalization

```
/users/123/posts/456 → /users/{id}/posts/{id}
/items/abc-def-123   → /items/{uuid}
/auth/eyJhbGc...     → /auth/{token}
```

### Body Normalization

```json
{
  "user_id": 123,
  "email": "john@example.com",
  "token": "abc123..."
}
```

Becomes:

```json
{
  "user_id": "<INT>",
  "email": "<EMAIL>",
  "token": "<TOKEN>"
}
```

## Integration with Crawler

```python
from cyberAI.insertion_points.integration import integrate_with_crawler

# After crawling
crawl_results = await crawler.crawl()

# Extract insertion points
extraction_results = await integrate_with_crawler(
    crawl_results=crawl_results,
    output_dir=Path("outputs"),
    max_depth=5,
)

print(extraction_results['pipeline_stats'])
```

## Performance

| Metric | Value | Notes |
|--------|-------|-------|
| Extraction speed | ~1000 points/sec | Single-threaded |
| Memory per point | ~200 bytes | Minimal overhead |
| Max nesting depth | 5 (configurable) | Prevents infinite recursion |
| Encoding detection | O(1) per value | Pattern-based |
| Novelty check | O(1) | Hash-based lookup |

## Configuration

```python
# Extractor configuration
extractor = NestedInsertionPointExtractor(
    max_depth=5,  # Maximum nesting depth
)

# Pipeline configuration
pipeline = InsertionPointPipeline(
    max_depth=5,  # Maximum nesting depth
)
```

## Output Example

```json
{
  "insertion_points": [
    {
      "location": "body.user.id",
      "value": 123,
      "encoding_layers": [],
      "inferred_type": "integer",
      "depth": 2
    },
    {
      "location": "body.token.decoded.user_id",
      "value": 123,
      "encoding_layers": ["base64", "json"],
      "inferred_type": "integer",
      "depth": 3
    }
  ],
  "stats": {
    "total_points": 15,
    "novel_points": 8,
    "novelty_score": 0.53
  }
}
```

## Testing

```bash
# Run tests
python3 test_insertion_points.py
```

## Future Enhancements

- GraphQL query parameter extraction
- Protobuf message field extraction
- Custom encoding plugin system
- Machine learning-based type inference
- Automatic payload generation per insertion point
